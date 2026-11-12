"""Independent Ollama fixture evidence rejects resealed protocol/lifetime forgeries."""
from __future__ import annotations

import ast
import copy
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools/hosted'))
from verify_ollama_adapter import (FAMILY, SOURCE_FILES, STDOUT_LIMIT, STDERR_LIMIT,
                                   encoded, digest, parse, read, verify_record)


def fixture():
    deployment = {'engine': {'adapter_kind': 'ollama-chat', 'wire_protocol': 'ollama-api-chat',
        'evidence_kind': 'protocol-contract', 'contract_version': 1}, 'model_id': 'fixture-model',
        'service_id': '00000000-0000-4000-8000-000000000001',
        'instance_id': '00000000-0000-4000-8000-000000000002', 'start_generation': 1, 'ownership': 'attached'}
    endpoint = {'host': '127.0.0.1', 'port': 11435, 'path': '/api/chat'}
    body = encoded({'model': deployment['model_id'], 'messages': [{'role': 'user', 'content': 'hello'}],
                    'stream': False, 'think': False, 'options': {'num_predict': 64}}).decode()
    template = {'schema_version': 1, 'adapter_kind': 'ollama-chat',
        'request_id': '00000000-0000-4000-8000-000000000003', 'deployment': deployment, 'endpoint': endpoint,
        'request_body': body, 'request_sha256': digest(body.encode()), 'response_body': None,
        'response_sha256': None, 'http_status': None, 'content': None, 'usage': None, 'outcome': 'ERROR',
        'error': None, 'evidence_kind': 'protocol-contract', 'elapsed_ns': 0, 'actual_server_qualification': False}
    row = {'schema_version': 3, 'adapter_kind': template['adapter_kind'], 'request_id': template['request_id'],
        'owner': {'host_boot_id': '00000000-0000-4000-8000-000000000004', 'process_id': 303,
                  'process_start_ticks': 100, 'uid': 1000}, 'deployment': deployment, 'endpoint': endpoint,
        'source_before': None, 'management_before': None, 'backend_expected': None, 'space_context': None,
        'user_prompt': None, 'request_body': body, 'request_sha256': template['request_sha256'],
        'revision': 1, 'phase': 'ACCEPTED', 'model_outcome': None, 'accepted_ns': 10, 'updated_ns': 10,
        'started_ns': None, 'cancel_requested_ns': None, 'finished_ns': None, 'worker_process_id': None,
        'worker_exit_code': None, 'inference_receipt': None, 'backend_stop': None, 'backend_stopped_ns': None,
        'not_started_reason': None}
    snapshots = []
    def save(worker=None):
        snapshots.append(copy.deepcopy({'schema_version': 1, 'request_state': row, 'receipt_template': template,
            'worker_progress': worker, 'control_failure': None, 'backend_observation': None}))
    save()
    row.update(revision=2, phase='RUNNING', updated_ns=11, started_ns=11, worker_process_id=1009)
    worker = {'request_id': row['request_id'], 'done': False, 'worker_pid': 1009, 'worker_exit_code': None,
        'worker_exit_observed_monotonic_ns': None, 'cancel_requested': False, 'timed_out': False,
        'stop_reason': None, 'terminate_requested': False, 'kill_requested': False, 'signal_error': None,
        'io_error': None, 'output_bytes': {'stdout': 0, 'stderr': 0}, 'receipt': None}
    save(worker)
    response = encoded({'model': deployment['model_id'], 'created_at': '2026-10-09T00:00:00Z',
        'message': {'role': 'assistant', 'content': 'fixture answer'}, 'done': True, 'done_reason': 'stop',
        'total_duration': 100, 'eval_count': 2}).decode()
    receipt = {**template, 'response_body': response, 'response_sha256': digest(response.encode()),
               'http_status': 200, 'content': 'fixture answer', 'outcome': 'OK', 'elapsed_ns': 5}
    row.update(revision=3, phase='FINISHED', model_outcome='ANSWERED', updated_ns=20, finished_ns=20,
               worker_exit_code=0, inference_receipt=receipt)
    stdout = encoded({'http_status': 200, 'response_body': response}).decode()
    worker.update(done=True, worker_exit_code=0, worker_exit_observed_monotonic_ns=19, receipt=receipt,
                  output_bytes={'stdout': len(stdout.encode()), 'stderr': 0})
    save(worker)
    capabilities = {'deployment': deployment, 'text_completion': None, 'messages': True, 'streaming': None,
                    'usage': None, 'request_cancel': None, 'evidence_kind': 'protocol-contract', 'contract_version': 1}
    stdin = encoded({'schema_version': 1, 'request_id': row['request_id'], 'deployment': deployment,
                     'capabilities': capabilities, 'endpoint': endpoint, 'request': body}).decode()
    return {'artifact_family': FAMILY, 'schema_version': 1, 'snapshots': snapshots,
        'completed': [copy.deepcopy(row)], 'http_exchanges': [{'request_id': row['request_id'],
        'endpoint': copy.deepcopy(endpoint), 'request_body': body, 'http_status': 200, 'response_body': response,
        'request_method': 'POST', 'response_content_type': 'application/json', 'response_content_encoding': 'identity'}],
        'worker_capture': {'request_id': row['request_id'], 'worker_pid': 1009, 'input_body': stdin,
                           'stdout': stdout, 'stderr': ''}}


def error_fixture(*, cancel=False, timeout=False):
    value = fixture()
    final = value['snapshots'][-1]
    template = final['receipt_template']
    receipt = {**template, 'elapsed_ns': 5, 'error': 'backend-timeout' if timeout else 'backend-failed'}
    final['request_state'].update(model_outcome='UNKNOWN', inference_receipt=copy.deepcopy(receipt), worker_exit_code=-15)
    final['worker_progress'].update(receipt=copy.deepcopy(receipt), worker_exit_code=-15,
        timed_out=timeout, cancel_requested=cancel, stop_reason='cancel' if cancel else 'timeout' if timeout else None,
        terminate_requested=cancel or timeout, output_bytes={'stdout': 0, 'stderr': 0})
    if cancel:
        pending = copy.deepcopy(value['snapshots'][1])
        pending['request_state'].update(revision=3, phase='CANCEL_REQUESTED', updated_ns=12, cancel_requested_ns=12)
        value['snapshots'].insert(2, pending)
        final['request_state'].update(revision=4, cancel_requested_ns=12)
    value['completed'] = [copy.deepcopy(final['request_state'])]
    value['worker_capture'].update(stdout='', stderr='')
    value['http_exchanges'] = []
    return value


def not_started_fixture():
    value = fixture()
    admission = value['snapshots'][0]
    cancel = copy.deepcopy(admission)
    cancel['request_state'].update(revision=2, phase='CANCEL_REQUESTED', updated_ns=11, cancel_requested_ns=11)
    final = copy.deepcopy(cancel)
    final['request_state'].update(revision=3, phase='FINISHED', updated_ns=12, finished_ns=12,
                                  model_outcome='NOT_STARTED', not_started_reason='cancel-before-dispatch')
    value.update(snapshots=[admission, cancel, final], completed=[copy.deepcopy(final['request_state'])],
                 http_exchanges=[], worker_capture=None)
    return value


class OllamaVerifierTests(unittest.TestCase):
    def setUp(self):
        self.value = fixture()

    def rejected(self, reason=None):
        result = verify_record(self.value)
        self.assertEqual(result['outcome'], 'FAIL', result)
        if reason is not None:
            self.assertIn(reason, result['reasons'][0])

    def receipts(self):
        final = self.value['snapshots'][-1]
        return (final['request_state']['inference_receipt'], final['worker_progress']['receipt'],
                self.value['completed'][0]['inference_receipt'])

    def reseal_response(self, raw):
        content = json.loads(raw).get('message', {}).get('content')
        for receipt in self.receipts():
            receipt.update(response_body=raw, response_sha256=digest(raw.encode()), content=content)
        self.value['http_exchanges'][0]['response_body'] = raw
        stdout = encoded({'http_status': 200, 'response_body': raw}).decode()
        self.value['worker_capture']['stdout'] = stdout
        self.value['snapshots'][-1]['worker_progress']['output_bytes']['stdout'] = len(stdout.encode())

    def test_normal_protocol_fixture_passes_without_actual_server_qualification(self):
        result = verify_record(self.value)
        self.assertEqual(result['outcome'], 'PASS', result)
        self.assertEqual(result['model_outcome'], 'ANSWERED')
        self.assertFalse(result['actual_server_qualification'])
        self.assertFalse(result['process_liveness_verified'])
        self.assertEqual(result['source_files_verified'], 0)

    def test_optional_raw_stats_remain_raw_and_normalized_usage_is_null(self):
        raw = json.loads(self.receipts()[0]['response_body'])
        raw.update(load_duration=0, prompt_eval_count=1, prompt_eval_cached_count=0,
                   prompt_eval_duration=3, eval_duration=4)
        self.reseal_response(encoded(raw).decode())
        self.assertEqual(verify_record(self.value)['outcome'], 'PASS')
        for receipt in self.receipts():
            receipt['usage'] = {'eval_count': 2}
        self.rejected('envelope-boundary')

    def test_unknown_response_echo_thinking_tool_calls_usage_and_stats_types_fail_after_reseal(self):
        for field, content in (('prompt', 'hello'), ('usage', {}), ('thinking', 'hidden'),
                               ('tool_calls', []), ('eval_count', True), ('eval_duration', -1)):
            self.value = fixture()
            raw = json.loads(self.receipts()[0]['response_body'])
            raw[field] = content
            self.reseal_response(encoded(raw).decode())
            with self.subTest(field=field):
                self.rejected('response')

    def test_response_model_done_reason_roles_and_time_fail(self):
        for field, content in (('model', 'wrong-model'), ('done', 1), ('done_reason', 'length'),
                               ('created_at', '2026-10-09T00:00:00'), ('created_at', '2026-10-09T00:00:00+09:00'),
                               ('message', {'role': 'user', 'content': 'fixture answer'}),
                               ('message', {'role': 'assistant', 'content': 'fixture\x00answer'})):
            self.value = fixture()
            raw = json.loads(self.receipts()[0]['response_body'])
            raw[field] = content
            self.reseal_response(encoded(raw).decode())
            with self.subTest(field=field, value=content):
                self.rejected('response')

    def test_duplicate_and_nonfinite_json_fail_in_raw_and_outer_records(self):
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse(raw)
        raw = self.receipts()[0]['response_body'].replace('"done":true', '"done":true,"done":true')
        self.reseal_response(raw)
        self.rejected('json-duplicate')
        raw = encoded(fixture()).decode().replace('"schema_version":1', '"schema_version":1,"schema_version":1', 1)
        with self.assertRaises(ValueError):
            parse(raw)

    def test_envelope_and_request_body_hashes_are_independently_checked(self):
        for field in ('request_sha256', 'response_sha256'):
            self.value = fixture()
            for receipt in self.receipts():
                receipt[field] = '0' * 64
            with self.subTest(field=field):
                self.rejected()
        self.value = fixture()
        for snapshot in self.value['snapshots']:
            snapshot['request_state']['request_sha256'] = '0' * 64
        self.rejected('request-bytes')

    def test_stale_deployment_generation_and_owner_worker_identities_fail(self):
        for field, content in (('request_id', '00000000-0000-4000-8000-000000000009'),
                               ('deployment', {**self.value['completed'][0]['deployment'], 'start_generation': 2})):
            self.value = fixture()
            for receipt in self.receipts():
                receipt[field] = content
            with self.subTest(field=field):
                self.rejected('envelope-join')
        self.value = fixture()
        self.value['snapshots'][-1]['request_state']['owner']['process_start_ticks'] += 1
        self.rejected('task-transition')
        self.value = fixture()
        self.value['snapshots'][-1]['worker_progress']['worker_pid'] += 1
        self.rejected('worker-identity')
        self.value = fixture()
        self.value['worker_capture']['worker_pid'] += 1
        self.rejected('capture-identity')

    def test_managed_ownership_legacy_binding_and_backend_stop_are_rejected(self):
        for field in ('source_before', 'management_before', 'backend_expected', 'space_context',
                      'user_prompt', 'backend_stop', 'backend_stopped_ns'):
            self.value = fixture()
            self.value['snapshots'][0]['request_state'][field] = {}
            with self.subTest(field=field):
                self.rejected('task-unbound')
        self.value = fixture()
        self.value['snapshots'][0]['request_state']['deployment']['ownership'] = 'managed'
        self.rejected('deployment-ownership')

    def test_loopback_port_path_and_bounded_request_modes_fail_closed(self):
        for field, content in (('host', 'localhost'), ('host', '10.0.0.1'), ('port', True),
                               ('port', 0), ('port', 65536), ('path', '/api/generate')):
            self.value = fixture()
            self.value['snapshots'][0]['request_state']['endpoint'][field] = content
            with self.subTest(field=field):
                self.rejected('endpoint')
        for field, content in (('stream', True), ('think', True), ('options', {'num_predict': True}),
                               ('options', {'num_predict': 65}), ('messages', [{'role': 'user', 'content': 'x' * 4097}]),
                               ('messages', [{'role': 'user', 'content': 'control\x00content'}])):
            self.value = fixture()
            row = self.value['snapshots'][0]['request_state']
            body = json.loads(row['request_body'])
            body[field] = content
            row['request_body'] = encoded(body).decode()
            row['request_sha256'] = digest(row['request_body'].encode())
            with self.subTest(field=field):
                self.rejected()

    def test_raw_http_status_body_request_and_worker_capture_must_join(self):
        for field, content in (('http_status', 201), ('response_body', '{}'), ('request_body', '{}'),
                               ('request_id', '00000000-0000-4000-8000-000000000009')):
            self.value = fixture()
            self.value['http_exchanges'][0][field] = content
            with self.subTest(field=field):
                self.rejected('http')
        self.value = fixture()
        self.value['worker_capture']['stdout'] += '\n'
        self.value['snapshots'][-1]['worker_progress']['output_bytes']['stdout'] += 1
        self.rejected('raw-worker-status')

    def test_raw_http_method_and_response_headers_are_required_for_answer(self):
        for field, content in (('request_method', 'GET'), ('response_content_type', 'text/plain'),
                               ('response_content_type', ''), ('response_content_encoding', 'gzip'),
                               ('response_content_encoding', ' identity')):
            self.value = fixture()
            self.value['http_exchanges'][0][field] = content
            with self.subTest(field=field, value=content):
                self.rejected('http')
        self.value = fixture()
        self.value['http_exchanges'][0].update(response_content_type='Application/JSON; charset=utf-8',
                                               response_content_encoding='IDENTITY')
        self.assertEqual(verify_record(self.value)['outcome'], 'PASS')

    def test_raw_response_whitespace_is_preserved_in_all_joins(self):
        raw = json.dumps(json.loads(self.receipts()[0]['response_body']), indent=2)
        self.reseal_response(raw)
        self.assertEqual(verify_record(self.value)['outcome'], 'PASS')
        self.value['http_exchanges'][0]['response_body'] = encoded(json.loads(raw)).decode()
        self.rejected('http-worker-envelope-join')

    def test_worker_stdin_capability_deployment_and_request_joins_are_checked(self):
        for mutation in ('generation', 'request', 'capability', 'schema'):
            self.value = fixture()
            packet = json.loads(self.value['worker_capture']['input_body'])
            if mutation == 'generation':
                packet['deployment']['start_generation'] = 2
            elif mutation == 'request':
                packet['request'] = '{}'
            elif mutation == 'capability':
                packet['capabilities']['messages'] = None
            else:
                packet['schema_version'] = True
            self.value['worker_capture']['input_body'] = encoded(packet).decode()
            with self.subTest(mutation=mutation):
                self.rejected('stdin' if mutation != 'capability' else 'capabilities')

    def test_oversized_raw_response_fails_even_after_all_evidence_is_resealed(self):
        raw = json.loads(self.receipts()[0]['response_body'])
        raw['message']['content'] = 'x' * 17000
        self.reseal_response(encoded(raw).decode())
        self.rejected('json-size')
        self.value = fixture()
        raw = json.loads(self.receipts()[0]['response_body'])
        raw['message']['content'] = '가' * 5500
        self.reseal_response(encoded(raw).decode())
        self.rejected('json-size')

    def test_wire_size_boundary_counts_utf8_bytes(self):
        raw = json.loads(self.receipts()[0]['response_body'])
        raw['message']['content'] = ''
        overhead = len(encoded(raw))
        raw['message']['content'] = 'x' * (16384 - overhead)
        self.reseal_response(encoded(raw).decode())
        self.assertEqual(len(self.receipts()[0]['response_body'].encode()), 16384)
        self.assertEqual(verify_record(self.value)['outcome'], 'PASS')
        raw['message']['content'] += 'x'
        self.reseal_response(encoded(raw).decode())
        self.rejected('json-size')

    def test_cancel_and_timeout_have_unknown_outcome_without_backend_stop_authority(self):
        for value in (error_fixture(cancel=True), error_fixture(timeout=True)):
            with self.subTest(cancel=value['snapshots'][-1]['worker_progress']['cancel_requested']):
                result = verify_record(value)
                self.assertEqual(result['outcome'], 'PASS', result)
                self.assertEqual(result['model_outcome'], 'UNKNOWN')
                self.assertFalse(result['actual_server_qualification'])
        self.value = fixture()
        self.value['snapshots'][-1]['worker_progress']['timed_out'] = True
        self.rejected('worker-answer')
        self.value = error_fixture(cancel=True)
        self.value['snapshots'][-1]['request_state']['cancel_requested_ns'] = None
        self.rejected('worker-cancel')

    def test_not_started_cancellation_has_no_worker_or_http(self):
        self.value = not_started_fixture()
        result = verify_record(self.value)
        self.assertEqual(result['outcome'], 'PASS', result)
        self.assertEqual(result['model_outcome'], 'NOT_STARTED')
        self.value['http_exchanges'] = fixture()['http_exchanges']
        self.rejected('not-started-transport')

    def test_late_unknown_cancel_preserves_first_completion_and_worker_terminal(self):
        self.value = error_fixture()
        late = copy.deepcopy(self.value['snapshots'][-1])
        late['request_state'].update(revision=4, updated_ns=21, cancel_requested_ns=21)
        self.value['snapshots'].append(late)
        result = verify_record(self.value)
        self.assertEqual(result['outcome'], 'PASS', result)
        self.assertEqual(result['model_outcome'], 'UNKNOWN')
        self.value['completed'][0] = copy.deepcopy(late['request_state'])
        self.rejected('finalization')
        self.value = fixture()
        late = copy.deepcopy(self.value['snapshots'][-1])
        late['request_state'].update(revision=4, updated_ns=21, cancel_requested_ns=21)
        self.value['snapshots'].append(late)
        self.rejected('late-cancel')
        self.value = error_fixture()
        late = copy.deepcopy(self.value['snapshots'][-1])
        late['request_state'].update(revision=4, updated_ns=21, cancel_requested_ns=21)
        late['worker_progress']['terminate_requested'] = True
        self.value['snapshots'].append(late)
        self.rejected('worker-terminal-rewrite')

    def test_malformed_http_worker_response_is_unknown_but_fabricated_failure_is_rejected(self):
        self.value = error_fixture()
        final = self.value['snapshots'][-1]
        final['request_state']['worker_exit_code'] = 0
        final['worker_progress']['worker_exit_code'] = 0
        self.value['completed'][0]['worker_exit_code'] = 0
        stdout = encoded({'http_status': 500, 'response_body': '{"error":"fixture"}'}).decode()
        self.value['worker_capture']['stdout'] = stdout
        final['worker_progress']['output_bytes']['stdout'] = len(stdout.encode())
        self.value['http_exchanges'] = fixture()['http_exchanges']
        self.value['http_exchanges'][0].update(http_status=500, response_body='{"error":"fixture"}')
        self.assertEqual(verify_record(self.value)['outcome'], 'PASS')
        valid = fixture()
        self.value['worker_capture']['stdout'] = valid['worker_capture']['stdout']
        final['worker_progress']['output_bytes']['stdout'] = len(self.value['worker_capture']['stdout'].encode())
        self.value['http_exchanges'] = valid['http_exchanges']
        self.rejected('fabricated-worker-error')

    def test_output_retention_and_overflow_counters_are_distinct(self):
        self.value['snapshots'][-1]['worker_progress']['output_bytes']['stdout'] += 1
        self.rejected('capture-bytes')
        self.value = error_fixture()
        worker = self.value['snapshots'][-1]['worker_progress']
        self.value['worker_capture']['stdout'] = 'x' * STDOUT_LIMIT
        worker.update(io_error='stdout-limit', stop_reason='io-failed', terminate_requested=True,
                      output_bytes={'stdout': STDOUT_LIMIT + 7, 'stderr': 0})
        self.assertEqual(verify_record(self.value)['outcome'], 'PASS')
        worker['output_bytes']['stdout'] = STDOUT_LIMIT
        self.rejected('worker-overflow')
        self.value = error_fixture()
        worker = self.value['snapshots'][-1]['worker_progress']
        self.value['worker_capture']['stderr'] = 'x' * STDERR_LIMIT
        worker.update(io_error='stderr-limit', stop_reason='io-failed', terminate_requested=True,
                      output_bytes={'stdout': 0, 'stderr': STDERR_LIMIT + 1})
        self.assertEqual(verify_record(self.value)['outcome'], 'PASS')

    def test_phase_revision_timestamp_counter_and_finalization_rewrites_fail(self):
        for mutation in ('revision', 'time', 'order', 'completion', 'duplicate-completion', 'exit-time', 'owner-worker'):
            self.value = fixture()
            final = self.value['snapshots'][-1]
            if mutation == 'revision':
                final['request_state']['revision'] += 1
            elif mutation == 'time':
                final['request_state']['updated_ns'] = 9
            elif mutation == 'order':
                self.value['snapshots'][0], self.value['snapshots'][1] = self.value['snapshots'][1], self.value['snapshots'][0]
            elif mutation == 'completion':
                self.value['completed'][0]['worker_exit_code'] = 1
            elif mutation == 'duplicate-completion':
                self.value['completed'].append(copy.deepcopy(self.value['completed'][0]))
            elif mutation == 'exit-time':
                final['worker_progress']['worker_exit_observed_monotonic_ns'] = 21
            else:
                self.value['snapshots'][1]['request_state']['worker_process_id'] = 303
            with self.subTest(mutation=mutation):
                self.rejected()
        self.value = fixture()
        self.value['snapshots'][1]['worker_progress']['output_bytes']['stdout'] = 1000
        self.rejected('worker-counter-regression')

    def test_unknown_keys_wrong_types_and_engine_qualification_cannot_pass(self):
        for mutate in ('outer', 'snapshot', 'envelope', 'true-schema', 'qualification', 'worker-flag'):
            self.value = fixture()
            if mutate == 'outer':
                self.value['actual_server_qualification'] = True
            elif mutate == 'snapshot':
                self.value['snapshots'][0]['unknown'] = None
            elif mutate == 'envelope':
                self.value['snapshots'][0]['receipt_template']['unknown'] = None
            elif mutate == 'true-schema':
                self.value['schema_version'] = True
            elif mutate == 'qualification':
                for receipt in self.receipts():
                    receipt['actual_server_qualification'] = True
            else:
                self.value['snapshots'][-1]['worker_progress']['done'] = 1
            with self.subTest(mutate=mutate):
                self.rejected()

    def test_source_manifest_has_exact_33_paths_and_content_hashes(self):
        self.assertEqual(len(SOURCE_FILES), 33)
        self.assertEqual(len(set(SOURCE_FILES)), 33)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hashes = {}
            for name in SOURCE_FILES:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(name.encode())
                hashes[name] = digest(name.encode())
            manifest = {'schema_version': 1, 'source_hashes': hashes}
            result = verify_record(self.value, source_manifest=manifest, source_root=root)
            self.assertEqual(result['outcome'], 'PASS', result)
            self.assertEqual(result['source_files_verified'], 33)
            (root / SOURCE_FILES[-1]).write_bytes(b'tampered')
            self.assertEqual(verify_record(self.value, source_manifest=manifest, source_root=root)['outcome'], 'FAIL')
            manifest['source_hashes'].pop(SOURCE_FILES[-1])
            result = verify_record(self.value, source_manifest=manifest, source_root=root)
            self.assertIn('source-inventory', result['reasons'][0])
            manifest['source_hashes']['../escaped.py'] = '0' * 64
            self.assertEqual(verify_record(self.value, source_manifest=manifest, source_root=root)['outcome'], 'FAIL')

    def test_source_symlink_and_directory_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / 'actual'
            target.write_bytes(b'example')
            with self.assertRaises(ValueError):
                read(root)
            original = Path.lstat
            for mode, attributes in ((stat.S_IFLNK, 0), (stat.S_IFREG, 0x400)):
                def observed(path):
                    if path == target:
                        return SimpleNamespace(st_mode=mode, st_file_attributes=attributes)
                    return original(path)
                with self.subTest(mode=mode, attributes=attributes), mock.patch.object(Path, 'lstat', observed):
                    with self.assertRaisesRegex(ValueError, 'source-path-link'):
                        read(target)

    def test_cli_strict_parser_fails_instead_of_reusing_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / 'artifact.json'
            manifest = Path(temporary) / 'manifest.json'
            artifact.write_text('{"schema_version":1,"schema_version":1}', encoding='utf-8')
            manifest.write_text('{}', encoding='utf-8')
            result = subprocess.run([sys.executable, str(ROOT / 'tools/hosted/verify_ollama_adapter.py'),
                '--artifact', str(artifact), '--source-manifest', str(manifest), '--source-root', temporary],
                capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 1, result.stderr)
            verdict = json.loads(result.stdout)
            self.assertEqual(verdict['outcome'], 'FAIL')
            self.assertIn('json-duplicate', verdict['reasons'][0])

    def test_verifier_has_no_producer_validator_or_runtime_imports(self):
        path = ROOT / 'tools/hosted/verify_ollama_adapter.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        allowed = {'__future__', 'argparse', 'hashlib', 'json', 'math', 'os', 're', 'stat', 'uuid', 'datetime', 'pathlib'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertTrue(all(alias.name in allowed for alias in node.names))
            elif isinstance(node, ast.ImportFrom):
                self.assertIn(node.module, allowed)

    def test_frozen_source_inventory_matches_p0_32_plus_only_ollama_adapter(self):
        from verify_agent import SERVE_SOURCES
        self.assertEqual(SOURCE_FILES[:-1], SERVE_SOURCES)
        self.assertEqual(SOURCE_FILES[-1], 'aios_engines/ollama_chat.py')

    def test_forged_signal_and_cancel_worker_observations_are_rejected(self):
        for mutation in ('kill', 'signal', 'cancel'):
            self.value = error_fixture(cancel=True)
            worker = self.value['snapshots'][-1]['worker_progress']
            if mutation == 'kill':
                worker.update(kill_requested=True, terminate_requested=False)
            elif mutation == 'signal':
                worker.update(signal_error='worker-kill', kill_requested=False)
            else:
                worker.update(terminate_requested=False)
            with self.subTest(mutation=mutation):
                self.rejected('worker')


if __name__ == '__main__':
    unittest.main()
