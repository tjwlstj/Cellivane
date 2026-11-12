"""Owned localhost HTTP fixtures only; no Ollama server or model qualification."""
from __future__ import annotations

import copy
import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'hosted/linux'))
from aios_agent import async_inference, inference
from aios_agent.request_runtime import RequestExecution, RequestExecutionFailure
from aios_engines.contracts import Deployment, CapabilityReport, EngineSpec
from aios_engines import ollama_chat
from aios_engines.ollama_chat import SPEC, PreparedOllama, OllamaChatAdapter, prepare_ollama, worker


def raw_response(model='ollama-fixture'):
    # Whitespace is intentional: response evidence must retain actual bytes.
    return json.dumps({'model': model, 'created_at': '2026-10-09T00:00:00Z',
        'message': {'role': 'assistant', 'content': 'local protocol fixture answer'},
        'done': True, 'done_reason': 'stop', 'total_duration': 30,
        'load_duration': 0, 'prompt_eval_count': 5, 'prompt_eval_cached_count': 2,
        'prompt_eval_duration': 10, 'eval_count': 6, 'eval_duration': 20},
        ensure_ascii=False, indent=1).encode('utf-8')


@contextmanager
def http_fixture(request_id, *, response=None, status=200, gate=None, headers=None):
    exchanges, paths = [], []
    received = threading.Event()
    raw = raw_response() if response is None else response
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            paths.append(self.path)
            length = int(self.headers.get('Content-Length', '0'))
            request = self.rfile.read(min(length, inference.MAX_BODY + 1))
            exchanges.append({'request_id': request_id,
                'endpoint': {'host': '127.0.0.1', 'port': self.server.server_port, 'path': self.path},
                'request_method': 'POST', 'response_content_type': 'application/json',
                'response_content_encoding': (headers or {}).get('Content-Encoding', 'identity'),
                'request_body': request.decode('utf-8'), 'http_status': status,
                'response_body': raw.decode('utf-8')})
            received.set()
            if gate is not None:
                gate.wait(3)
            try:
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Connection', 'close')
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    try:
        yield server.server_port, exchanges, paths, received
    finally:
        if gate is not None:
            gate.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


class FakePending:
    def __init__(self, request_id, trace):
        self.trace, self.closed = trace, False
        self.value = {'done': False, 'request_id': request_id, 'worker_pid': 1009,
                      'worker_exit_code': None, 'receipt': None}

    def poll(self):
        return copy.deepcopy(self.value)

    def request_cancel(self):
        self.trace.append('signal')
        return True

    def close(self):
        self.trace.append('close')
        self.closed = True


class OllamaAdapterTests(unittest.TestCase):
    def setUp(self):
        self.request_id = str(uuid.uuid4())
        self.owner = {'host_boot_id': str(uuid.uuid4()), 'process_id': 303,
                      'process_start_ticks': 102, 'uid': 1000}
        self.deployment = Deployment(SPEC, 'ollama-fixture', str(uuid.uuid4()), str(uuid.uuid4()), 1)
        self.capabilities = CapabilityReport(self.deployment, False, True, False, None, None,
                                             evidence_kind='protocol-contract')
        self.messages = [{'role': 'user', 'content': 'hi'}]
        self.saved, self.completed, self.trace = [], [], []
        self.now = 100
        self.failure = None
        self.finalizer_failure = False

    def clock(self):
        self.now += 1
        return self.now

    def save(self, snapshot):
        phase = snapshot['request_state']['phase']
        self.trace.append('save:' + phase)
        if self.failure == phase:
            raise OSError('durable fixture failure')
        self.saved.append(copy.deepcopy(snapshot))

    def complete(self, row):
        self.trace.append('complete')
        self.completed.append(copy.deepcopy(row))
        if self.finalizer_failure:
            raise OSError('finalizer fixture failure')

    def prepared(self, *, port=1, **options):
        return prepare_ollama(self.deployment, self.capabilities, self.messages,
                             request_id=self.request_id, port=port, **options)

    def execution(self, *, port=1, selector=False, **options):
        clock = options.pop('clock', self.clock)
        factory = RequestExecution.for_engine_messages if selector else RequestExecution.for_ollama
        return factory(save=self.save, complete=self.complete, request_id=self.request_id,
            owner=self.owner, deployment=self.deployment, capabilities=self.capabilities,
            messages=self.messages, port=port, clock=clock, **options)

    def answer(self):
        prepared = self.prepared()
        result = prepared.receipt_template
        result.update(PreparedOllama.validated_output(prepared,
            inference.encoded({'http_status': 200, 'response_body': raw_response().decode('utf-8')}), b'', 0))
        return result

    def fake(self):
        pending = FakePending(self.request_id, self.trace)
        patcher = mock.patch.object(async_inference, 'start', return_value=pending)
        start = patcher.start()
        self.addCleanup(patcher.stop)
        return pending, start

    def await_terminal(self, execution, seconds=8):
        deadline = time.monotonic() + seconds
        while not execution.terminal and time.monotonic() < deadline:
            execution.poll()
            time.sleep(.005)
        self.assertTrue(execution.terminal, execution.snapshot())

    def artifact(self, execution, exchanges):
        pending = execution._pending
        capture = None
        if pending is not None:
            output = {drain.name: drain.snapshot()[0].decode('utf-8') for drain in pending._drains}
            capture = {'request_id': self.request_id, 'worker_pid': pending._process.pid,
                'input_body': execution._prepared._input.decode('utf-8'),
                'stdout': output['stdout'], 'stderr': output['stderr']}
        return {'artifact_family': 'ollama-adapter-fixture-v1', 'schema_version': 1,
                'snapshots': self.saved, 'completed': self.completed,
                'http_exchanges': exchanges, 'worker_capture': capture}

    def emit(self, name, artifact):
        output = os.environ.get('AIOS_OLLAMA_EVIDENCE_DIR')
        if output:
            directory = Path(output)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / name).write_bytes(inference.encoded(artifact))

    def test_wire_byte_golden_and_supported_subset(self):
        prepared = self.prepared()
        self.assertEqual(prepared.request_body,
            b'{"messages":[{"content":"hi","role":"user"}],"model":"ollama-fixture",'
            b'"options":{"num_predict":64},"stream":false,"think":false}')
        packet = inference.parse(prepared._input)
        self.assertEqual(packet['endpoint'], {'host': '127.0.0.1', 'port': 1, 'path': '/api/chat'})
        self.assertEqual(packet['schema_version'], 1)
        self.assertEqual(prepared.receipt_template['evidence_kind'], 'protocol-contract')
        self.assertFalse(prepared.receipt_template['actual_server_qualification'])
        unicode_body = prepare_ollama(self.deployment, self.capabilities,
            [{'role': 'user', 'content': '상태를 설명해줘'}], request_id=self.request_id, port=1).request_body
        self.assertIn('상태를 설명해줘'.encode('utf-8'), unicode_body)

    def test_actual_owned_worker_and_raw_http_evidence(self):
        with http_fixture(self.request_id) as (port, exchanges, paths, _received):
            execution = self.execution(port=port, selector=True, clock=time.monotonic_ns)
            self.addCleanup(execution.close)
            self.assertEqual(self.trace, ['save:ACCEPTED'])
            execution.dispatch()
            self.await_terminal(execution)
            row = execution.snapshot()['request_state']
            self.assertEqual(row['schema_version'], 3)
            self.assertEqual(row['model_outcome'], 'ANSWERED')
            envelope = row['inference_receipt']
            self.assertEqual(envelope['response_body'].encode('utf-8'), raw_response())
            self.assertEqual(envelope['response_sha256'], inference.digest(raw_response()))
            self.assertEqual(envelope['http_status'], 200)
            self.assertIsNone(envelope['usage'])
            self.assertFalse(envelope['actual_server_qualification'])
            self.assertEqual(json.loads(envelope['response_body'])['prompt_eval_cached_count'], 2)
            for name in ('source_before', 'management_before', 'backend_expected', 'space_context',
                         'user_prompt', 'backend_stop', 'backend_stopped_ns'):
                self.assertIsNone(row[name])
            self.assertEqual(paths, ['/api/chat'])
            self.assertEqual(exchanges[0]['request_body'], envelope['request_body'])
            self.assertEqual(len(self.completed), 1)
            self.assertEqual(self.trace[-2:], ['save:FINISHED', 'complete'])
            before = execution.snapshot(), copy.deepcopy(self.saved)
            for _ in range(5):
                execution.poll()
            self.assertEqual(before, (execution.snapshot(), self.saved))
            artifact = self.artifact(execution, exchanges)
            progress = execution.snapshot()['worker_progress']
            self.assertEqual(progress['output_bytes']['stdout'],
                             len(artifact['worker_capture']['stdout'].encode('utf-8')))
            self.assertEqual(artifact['worker_capture']['stderr'], '')
            self.emit('ollama-task.json', artifact)

    def test_capabilities_false_unknown_stale_and_wrong_evidence_zero_save_submit(self):
        original = self.capabilities
        reports = [replace(original, messages=False), replace(original, messages=None),
            replace(original, deployment=replace(self.deployment, start_generation=2)),
            replace(original, deployment=replace(self.deployment, instance_id=str(uuid.uuid4())))]
        with mock.patch.object(async_inference, 'start') as start:
            for report in reports:
                self.capabilities = report
                with self.assertRaisesRegex(ValueError, 'engine-capability-'):
                    self.execution()
            start.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'engine-capability-report'):
            replace(original, evidence_kind='fixture')
        self.assertFalse(self.saved)

    def test_streaming_and_usage_are_unsupported_even_with_claimed_capability(self):
        self.capabilities = replace(self.capabilities, streaming=True, usage=True, request_cancel=True)
        with mock.patch.object(async_inference, 'start') as start:
            for option in ({'streaming': True}, {'require_usage': True}):
                with self.assertRaisesRegex(ValueError, 'engine-ollama-mode-unsupported'):
                    self.execution(**option)
            for option in ({'streaming': 1}, {'require_usage': None}):
                with self.assertRaisesRegex(ValueError, 'engine-request-options'):
                    self.execution(**option)
            start.assert_not_called()
        self.assertFalse(self.saved)

    def test_managed_wrong_spec_and_port_reject_before_save_submit(self):
        original = self.deployment
        with mock.patch.object(async_inference, 'start') as start:
            for deployment in (replace(original, ownership='managed'),
                    replace(original, engine=EngineSpec('ollama-chat', 'other', 'protocol-contract'))):
                self.deployment = deployment
                self.capabilities = replace(self.capabilities, deployment=deployment)
                with self.assertRaisesRegex(ValueError, 'engine-ollama-deployment'):
                    self.execution()
            self.deployment = original
            self.capabilities = replace(self.capabilities, deployment=original)
            for port in (None, True, 0, 65536, '11434', 1.5):
                with self.assertRaisesRegex(ValueError, 'engine-ollama-endpoint'):
                    self.execution(port=port)
            start.assert_not_called()
        self.assertFalse(self.saved)

    def test_text_message_bounds_and_roles_reject_before_admission(self):
        for messages in ('raw', [], [{'role': 'assistant', 'content': 'answer'}],
                [{'role': 'tool', 'content': 'tool'}], [{'role': 'user', 'content': ''}],
                [{'role': 'user', 'content': ' '}], [{'role': 'user', 'content': 'bad\x00'}],
                [{'role': 'user', 'content': 'x' * 4097}], [{'role': 'user', 'content': '한' * 1366}],
                [{'role': 'user', 'content': 'hi', 'tool_calls': []}],
                [{'role': 'user', 'content': [{'type': 'text', 'text': 'hi'}]}],
                [{'role': 'user', 'content': 'a'}] * 17):
            with self.subTest(messages=str(messages)[:60]), self.assertRaises(ValueError):
                prepare_ollama(self.deployment, self.capabilities, messages,
                               request_id=self.request_id, port=1)
        self.prepared()  # Valid exact boundary still admits.

    def test_selector_unknown_and_mismatched_spec_never_falls_back(self):
        with mock.patch.object(async_inference, 'start') as start:
            for spec in (EngineSpec('other', 'messages-json', 'fixture'),
                    EngineSpec('ollama-chat', 'other', 'protocol-contract')):
                self.deployment = replace(self.deployment, engine=spec)
                with self.assertRaisesRegex(ValueError, 'engine-messages-deployment'):
                    self.execution(selector=True)
            start.assert_not_called()
        self.assertFalse(self.saved)

    def test_selector_fixture_path_and_no_legacy_parameter_workaround(self):
        from aios_engines.fixtures import SPEC as fixture_spec
        self.deployment = replace(self.deployment, engine=fixture_spec)
        self.capabilities = replace(self.capabilities, deployment=self.deployment, evidence_kind='fixture')
        execution = self.execution(port=None, selector=True)
        self.assertEqual(execution.snapshot()['request_state']['adapter_kind'], 'messages-fixture')
        with self.assertRaisesRegex(ValueError, 'engine-fixture-endpoint'):
            self.execution(port=11434, selector=True)
        self.setUp()
        for name in ('config', 'source', 'management', 'space_context', 'prompt', 'backend_expected',
                     'engine_request', 'host', 'endpoint'):
            with self.subTest(name=name), self.assertRaises(TypeError):
                self.execution(**{name: None})
        self.assertFalse(self.saved)

    def test_fresh_legacy_fixture_import_closure_excludes_ollama(self):
        script = """import sys, uuid
from aios_agent import async_inference, inference
from aios_agent.request_runtime import RequestExecution
from aios_engines.contracts import Deployment, CapabilityReport
from aios_engines.fixtures import SPEC, prepare_messages
config={'schema_version':1,'endpoint':'http://127.0.0.1:8089','model_id':'fixture-main',
 'model_sha256':'a'*64,'backend_sha256':'d'*64,'provenance_sha256':'e'*64,
 'model_path':'fixture.gguf','backend_path':'fixture-backend'}
async_inference.prepare(config,'hi',request_id=str(uuid.uuid4()))
deployment=Deployment(SPEC,'fixture',str(uuid.uuid4()),str(uuid.uuid4()),1)
report=CapabilityReport(deployment,False,True,False,None,None)
prepared=prepare_messages(deployment,report,[{'role':'user','content':'hi'}],request_id=str(uuid.uuid4()))
owner={'host_boot_id':str(uuid.uuid4()),'process_id':303,'process_start_ticks':102,'uid':1000}
RequestExecution.for_engine_messages(save=lambda _:None,complete=lambda _:None,
 request_id=prepared.request_id,owner=owner,deployment=deployment,capabilities=report,
 messages=[{'role':'user','content':'hi'}])
assert 'aios_engines.ollama_chat' not in sys.modules
"""
        environment = {**os.environ, 'PYTHONPATH': str(ROOT / 'hosted/linux')}
        result = subprocess.run([sys.executable, '-B', '-c', script], env=environment,
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8'))

    def test_unknown_subclass_and_module_impostor_cannot_validate_or_spawn(self):
        class Derived(PreparedOllama):
            def validate_prepared(self):
                raise AssertionError('untrusted validator ran')
        prepared = self.prepared()
        derived = Derived(prepared._input, prepared._template, prepared._timeout)
        impostor = type('PreparedOllama', (), {'__module__': 'aios_engines.ollama_chat'})()
        with mock.patch.object(async_inference.subprocess, 'Popen') as spawn:
            for candidate in (object(), derived, impostor):
                with self.assertRaisesRegex(TypeError, 'prepared-inference-required'):
                    async_inference.start(candidate)
            spawn.assert_not_called()
        self.assertFalse(derived._lease.used)

    def test_mutated_timeout_template_packet_endpoint_and_lease_zero_spawn(self):
        prepared = self.prepared()
        packet = inference.parse(prepared._input)
        mutated = []
        for endpoint in ({'host': 'localhost', 'port': 1, 'path': '/api/chat'},
                {'host': '127.0.0.2', 'port': 1, 'path': '/api/chat'},
                {'host': '127.0.0.1', 'port': 1, 'path': '/completion'},
                {'host': '127.0.0.1', 'port': 1, 'path': '/api/chat', 'proxy': False}):
            mutated.append(replace(prepared, _input=inference.encoded({**packet, 'endpoint': endpoint})))
        for value in (replace(prepared, _timeout=100.0), replace(prepared, _timeout=30),
                replace(prepared, _template=b'{}'), replace(prepared, _lease=mock.Mock()),
                replace(prepared, _input=prepared._input + b' '),
                replace(prepared, _input=inference.encoded({**packet, 'extra': 1})), *mutated):
            with self.subTest(value=str(value)[:80]), mock.patch.object(async_inference.subprocess, 'Popen') as spawn:
                with self.assertRaises((ValueError, KeyError)):
                    async_inference.start(value)
                spawn.assert_not_called()
        self.assertFalse(prepared._lease.used)

    def test_instance_validator_and_lease_method_shadow_cannot_bypass_gates(self):
        prepared = replace(self.prepared(), _timeout=100.0)
        shadow = mock.Mock()
        prepared.__dict__['validate_prepared'] = shadow
        with mock.patch.object(async_inference.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(ValueError, 'prepared-ollama'):
                async_inference.start(prepared)
            spawn.assert_not_called()
        shadow.assert_not_called()
        good = self.prepared()
        good._lease.used = True
        good._lease.__dict__['claim'] = shadow
        with mock.patch.object(async_inference.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(ValueError, 'already-started'):
                async_inference.start(good)
            spawn.assert_not_called()
        shadow.assert_not_called()

    def test_valid_one_use_lease_submits_one_http_request(self):
        with http_fixture(self.request_id) as (port, exchanges, _paths, _received):
            prepared = self.prepared(port=port)
            with async_inference.start(prepared) as pending:
                with self.assertRaisesRegex(ValueError, 'already-started'):
                    async_inference.start(prepared)
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    result = pending.poll()
                    if result['done']:
                        break
                    time.sleep(.005)
                self.assertTrue(result['done'])
                self.assertEqual(result['receipt']['outcome'], 'OK')
            self.assertEqual(len(exchanges), 1)

    def test_instance_result_shadow_cannot_accept_invalid_http_output(self):
        with http_fixture(self.request_id, response=b'{}') as (port, exchanges, _paths, _received):
            execution = self.execution(port=port, clock=time.monotonic_ns)
            shadow = mock.Mock(return_value={'outcome': 'OK'})
            execution._prepared.__dict__['validated_output'] = shadow
            try:
                execution.dispatch()
                self.await_terminal(execution)
                self.assertEqual(execution.snapshot()['request_state']['model_outcome'], 'UNKNOWN')
                self.assertEqual(len(exchanges), 1)
            finally:
                execution.close()
            shadow.assert_not_called()

    def test_response_model_done_role_timestamp_and_finish_reason_fail_closed(self):
        original = json.loads(raw_response())
        alternatives = [dict(original, model='other'), dict(original, done=False), dict(original, done=1),
            dict(original, done_reason='length'), dict(original, done_reason=None),
            dict(original, created_at='2026-10-09T00:00:00'), dict(original, created_at='bad'),
            dict(original, created_at='2026-10-09T09:00:00+09:00'),
            dict(original, message={'role': 'user', 'content': 'hi'}),
            dict(original, message={'role': 'assistant', 'content': ' '}),
            dict(original, message={'role': 'assistant', 'content': 'bad\x00'}),
            {k: v for k, v in original.items() if k != 'done_reason'}]
        for response in alternatives:
            with self.subTest(response=response), self.assertRaises(ValueError):
                OllamaChatAdapter.response(self.deployment, inference.encoded(response))

    def test_tools_thinking_usage_stream_and_unknown_response_fields_fail_closed(self):
        original = json.loads(raw_response())
        for key, value in (('thinking', 'hidden'), ('tool_calls', []), ('logprobs', {}),
                ('usage', {'total_tokens': 11}), ('stream', False), ('extra', None)):
            for response in (dict(original, **{key: value}),
                    dict(original, message={**original['message'], key: value})):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    OllamaChatAdapter.response(self.deployment, inference.encoded(response))
        with self.assertRaises(ValueError):
            OllamaChatAdapter.response(self.deployment, raw_response() + b'\n' + raw_response())

    def test_known_statistics_exact_nonnegative_int_only(self):
        original = json.loads(raw_response())
        for name in ollama_chat.RESPONSE_STATS:
            for value in (True, -1, 1.5, '1', None, 1 << 63):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    OllamaChatAdapter.response(self.deployment, inference.encoded({**original, name: value}))
        response = {k: v for k, v in original.items() if k not in ollama_chat.RESPONSE_STATS}
        self.assertEqual(OllamaChatAdapter.response(self.deployment, inference.encoded(response)),
                         'local protocol fixture answer')

    def test_raw_response_duplicate_keys_nonfinite_and_size_reject(self):
        for raw in (b'{"model":"a","model":"b"}', b'{"model":NaN}',
                    b'{' + b' ' * ollama_chat.MAX_RESPONSE_BODY + b'}'):
            with self.assertRaises(ValueError):
                OllamaChatAdapter.response(self.deployment, raw)

    def test_envelope_joins_raw_digest_usage_and_qualification_reject_forgery(self):
        prepared, answer = self.prepared(), self.answer()
        for changed in (dict(answer, request_id=str(uuid.uuid4())),
                dict(answer, endpoint={**answer['endpoint'], 'port': 2}),
                dict(answer, deployment={**answer['deployment'], 'start_generation': 2}),
                dict(answer, response_sha256='0' * 64), dict(answer, http_status=True),
                dict(answer, content='invented'), dict(answer, usage={'total_tokens': 11}),
                dict(answer, actual_server_qualification=True), dict(answer, backend_execution={})):
            with self.subTest(changed=str(changed)[:80]), self.assertRaises(ValueError):
                OllamaChatAdapter.validate_envelope(changed, template=prepared.receipt_template)
        error = prepared.receipt_template
        error['error'] = 'backend-failed'
        OllamaChatAdapter.validate_envelope(error, template=prepared.receipt_template)
        for field in ('response_body', 'response_sha256', 'http_status', 'content'):
            with self.assertRaises(ValueError):
                OllamaChatAdapter.validate_envelope({**error, field: answer[field]},
                                                    template=prepared.receipt_template)

    def test_worker_rejects_changed_packet_before_http(self):
        packet = inference.parse(self.prepared()._input)
        for change in ({**packet, 'schema_version': True}, {**packet, 'extra': 1},
                {**packet, 'endpoint': {'host': 'localhost', 'port': 1, 'path': '/api/chat'}},
                {**packet, 'request': json.dumps({**json.loads(packet['request']), 'stream': True})}):
            with mock.patch.object(ollama_chat.http.client, 'HTTPConnection') as connection:
                with self.assertRaises(ValueError):
                    worker(change)
                connection.assert_not_called()

    def test_redirect_is_not_followed_and_failed_response_is_not_retried(self):
        with http_fixture(self.request_id) as (target_port, target_exchanges, _p, _r):
            for status, raw, headers in ((302, raw_response(),
                    {'Location': 'http://127.0.0.1:' + str(target_port) + '/api/chat'}),
                    (200, b'{}', {}), (500, raw_response(), {})):
                with self.subTest(status=status), http_fixture(self.request_id,
                        response=raw, status=status, headers=headers) as (port, exchanges, _paths, _received):
                    self.saved, self.completed, self.trace = [], [], []
                    execution = self.execution(port=port, clock=time.monotonic_ns)
                    try:
                        execution.dispatch()
                        self.await_terminal(execution)
                        row = execution.snapshot()['request_state']
                        self.assertEqual(row['model_outcome'], 'UNKNOWN')
                        self.assertIsNone(row['inference_receipt']['response_body'])
                        capture = self.artifact(execution, exchanges)['worker_capture']
                        self.assertEqual(json.loads(capture['stdout'])['http_status'], status)
                        self.assertEqual(json.loads(capture['stdout'])['response_body'], raw.decode('utf-8'))
                        self.assertEqual(len(exchanges), 1)
                    finally:
                        execution.close()
            self.assertFalse(target_exchanges)

    def test_direct_worker_deadline_bounds_silent_fixture(self):
        gate = threading.Event()
        with http_fixture(self.request_id, gate=gate) as (port, exchanges, _paths, _received):
            prepared = self.prepared(port=port)
            started = time.monotonic()
            with mock.patch.object(ollama_chat, 'TIMEOUT', .15):
                with self.assertRaises((OSError, ValueError, http.client.HTTPException)):
                    worker(inference.parse(prepared._input))
            self.assertLess(time.monotonic() - started, 2)
            self.assertEqual(len(exchanges), 1)

    def test_response_bytes_limit_is_unknown_without_retry(self):
        with http_fixture(self.request_id,
                response=b'x' * (ollama_chat.MAX_RESPONSE_BODY + 1)) as (port, exchanges, _paths, _received):
            execution = self.execution(port=port, clock=time.monotonic_ns)
            try:
                execution.dispatch()
                self.await_terminal(execution)
                self.assertEqual(execution.snapshot()['request_state']['model_outcome'], 'UNKNOWN')
                self.assertEqual(len(exchanges), 1)
            finally:
                execution.close()

    def test_unknown_terminal_late_cancel_is_durable_without_second_finalizer(self):
        with http_fixture(self.request_id, response=b'{}') as (port, exchanges, _paths, _received):
            execution = self.execution(port=port, clock=time.monotonic_ns)
            try:
                execution.dispatch()
                self.await_terminal(execution)
                first_terminal = execution.snapshot()['request_state']
                self.assertEqual(first_terminal['model_outcome'], 'UNKNOWN')
                self.assertEqual(execution.cancel(self.owner)['outcome'], 'ACCEPTED')
                row = execution.snapshot()['request_state']
                self.assertEqual(row['finished_ns'], first_terminal['finished_ns'])
                self.assertEqual(row['revision'], first_terminal['revision'] + 1)
                self.assertEqual(self.completed, [first_terminal])
                before = execution.snapshot(), copy.deepcopy(self.saved)
                self.assertEqual(execution.cancel(self.owner)['outcome'], 'ALREADY_REQUESTED')
                self.assertEqual(before, (execution.snapshot(), self.saved))
                self.emit('ollama-unknown-late-cancel-task.json', self.artifact(execution, exchanges))
            finally:
                execution.close()

    def test_cancel_before_dispatch_not_started_artifact_and_no_http(self):
        with http_fixture(self.request_id) as (port, exchanges, _paths, _received):
            with mock.patch.object(async_inference, 'start') as start:
                execution = self.execution(port=port)
                execution.cancel(self.owner)
                execution.dispatch()
                start.assert_not_called()
            self.assertEqual(execution.snapshot()['request_state']['model_outcome'], 'NOT_STARTED')
            self.assertFalse(exchanges)
            self.assertEqual(len(self.completed), 1)
            self.emit('ollama-not-started-task.json', self.artifact(execution, exchanges))

    def test_actual_owned_cancel_is_unknown_and_has_no_server_stop_authority(self):
        gate = threading.Event()
        with http_fixture(self.request_id, gate=gate) as (port, exchanges, _paths, received):
            execution = self.execution(port=port, clock=time.monotonic_ns)
            try:
                execution.dispatch()
                self.assertTrue(received.wait(5))
                execution.cancel(self.owner)
                self.await_terminal(execution)
                row = execution.snapshot()['request_state']
                self.assertEqual(row['model_outcome'], 'UNKNOWN')
                self.assertIsNone(row['backend_stop'])
                self.assertIsNone(row['backend_stopped_ns'])
                self.assertTrue(execution.snapshot()['worker_progress']['cancel_requested'])
                verify = mock.Mock()
                with self.assertRaisesRegex(ValueError, 'instance-stop-unsupported'):
                    execution.observe_backend_stop(self.owner, verify)
                verify.assert_not_called()
                self.emit('ollama-cancelled-task.json', self.artifact(execution, exchanges))
            finally:
                execution.close()

    def test_admission_save_failure_zero_dispatch(self):
        self.failure = 'ACCEPTED'
        with mock.patch.object(async_inference, 'start') as start:
            with self.assertRaisesRegex(RequestExecutionFailure, 'persistence'):
                self.execution()
            start.assert_not_called()
        self.assertEqual(self.trace, ['save:ACCEPTED'])
        self.assertFalse(self.completed)

    def test_cancel_save_precedes_signal_and_save_failure_never_signals_or_retries(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                self.setUp()
                pending, start = self.fake()
                execution = self.execution()
                execution.dispatch()
                if fail:
                    self.failure = 'CANCEL_REQUESTED'
                    with self.assertRaises(RequestExecutionFailure):
                        execution.cancel(self.owner)
                    self.assertNotIn('signal', self.trace)
                    self.assertTrue(pending.closed)
                    with self.assertRaises(RequestExecutionFailure):
                        execution.poll()
                else:
                    execution.cancel(self.owner)
                    self.assertLess(self.trace.index('save:CANCEL_REQUESTED'), self.trace.index('signal'))
                    before = list(self.trace)
                    execution.cancel(self.owner)
                    self.assertEqual(self.trace, before)
                self.assertEqual(start.call_count, 1)
                self.assertFalse(self.completed)

    def test_stale_owner_generation_result_and_terminal_callback_cannot_touch_new_task(self):
        pending, _start = self.fake()
        old = self.execution()
        old.dispatch()
        before = old.snapshot()
        with self.assertRaisesRegex(ValueError, 'owner-mismatch'):
            old.cancel({**self.owner, 'process_start_ticks': 103})
        self.assertEqual(old.snapshot(), before)
        receipt = self.answer()
        receipt['deployment']['start_generation'] = 2
        pending.value.update(done=True, worker_exit_code=0, receipt=receipt)
        with self.assertRaises(RequestExecutionFailure):
            old.poll()
        self.assertFalse(self.completed)
        self.assertTrue(pending.closed)
        next_deployment = replace(self.deployment, instance_id=str(uuid.uuid4()), start_generation=2)
        newer = RequestExecution.for_ollama(save=lambda _: None, complete=lambda _: None,
            request_id=str(uuid.uuid4()), owner=self.owner, deployment=next_deployment,
            capabilities=replace(self.capabilities, deployment=next_deployment), messages=self.messages,
            port=1, clock=self.clock)
        new_before = newer.snapshot()
        old.close()
        old.close()
        self.assertEqual(newer.snapshot(), new_before)

    def test_output_observed_before_cancel_preserves_answer_and_once_finalizer(self):
        pending, _start = self.fake()
        execution = self.execution()
        execution.dispatch()
        pending.value.update(done=True, worker_exit_code=0, receipt=self.answer())
        self.assertEqual(execution.cancel(self.owner)['outcome'], 'ALREADY_TERMINAL')
        self.assertNotIn('signal', self.trace)
        for _ in range(5):
            execution.poll()
        self.assertEqual(len(self.completed), 1)

    def test_timeout_receipt_is_unknown_and_retains_no_stop_or_usage_claim(self):
        pending, _start = self.fake()
        execution = self.execution()
        execution.dispatch()
        receipt = self.prepared().receipt_template
        receipt['error'] = 'backend-timeout'
        pending.value.update(done=True, worker_exit_code=1, receipt=receipt)
        execution.poll()
        row = execution.snapshot()['request_state']
        self.assertEqual(row['model_outcome'], 'UNKNOWN')
        self.assertIsNone(row['backend_stop'])
        self.assertIsNone(row['inference_receipt']['usage'])
        self.assertFalse(row['inference_receipt']['actual_server_qualification'])


if __name__ == '__main__':
    unittest.main()
