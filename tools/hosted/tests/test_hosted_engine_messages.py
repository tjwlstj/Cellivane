"""P0 protocol and real Task-lifetime fixture; never actual engine acceptance."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'hosted/linux'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from aios_engines.contracts import Deployment, CapabilityReport
from aios_engines.fixtures import SPEC, prepare_messages, PreparedMessages, MessagesFixtureAdapter, worker
from aios_agent import async_inference, inference
from aios_agent.request_runtime import RequestExecution, RequestExecutionFailure
import test_hosted_request_state as state_fixture
import test_hosted_request_runtime as runtime_fixture


class MessagesTaskTests(unittest.TestCase):
    def setUp(self):
        fixture = state_fixture.RequestStateTests()
        fixture.setUp()
        self.owner = fixture.kwargs['owner']
        self.request_id = str(uuid.uuid4())
        self.deployment = Deployment(SPEC, 'messages-model', str(uuid.uuid4()), str(uuid.uuid4()), 1)
        self.capabilities = CapabilityReport(self.deployment, False, True, False, None, None)
        self.messages = [{'role': 'user', 'content': '현재 상태를 설명해줘'}]
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

    def execution(self, **options):
        clock = options.pop('clock', self.clock)
        return RequestExecution.for_messages(save=self.save, complete=self.complete, request_id=self.request_id,
            owner=self.owner, deployment=self.deployment, capabilities=self.capabilities,
            messages=self.messages, clock=clock, **options)

    def prepared(self):
        return prepare_messages(self.deployment, self.capabilities, self.messages, request_id=self.request_id)

    def answer(self):
        prepared = self.prepared()
        result = prepared.receipt_template
        result.update(prepared.validated_output(inference.encoded(worker(inference.parse(prepared._input))), b'', 0))
        return result

    def fake(self):
        pending = runtime_fixture.FakePending(self.request_id, self.trace)
        patcher = mock.patch.object(async_inference, 'start', return_value=pending)
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return pending, started

    def test_actual_bounded_subprocess_task_with_distinct_response_and_saved_evidence(self):
        execution = self.execution(clock=time.monotonic_ns)
        self.addCleanup(execution.close)
        self.assertEqual(self.trace, ['save:ACCEPTED'])
        execution.dispatch()
        deadline = time.monotonic() + 10
        while not execution.terminal and time.monotonic() < deadline:
            execution.poll()
            time.sleep(0.01)
        self.assertTrue(execution.terminal)
        row = execution.snapshot()['request_state']
        self.assertEqual(row['model_outcome'], 'ANSWERED')
        self.assertEqual(len(self.completed), 1)
        envelope = row['inference_receipt']
        raw = json.loads(envelope['response_body'])
        self.assertNotIn('prompt', raw)
        self.assertNotIn('backend_execution', envelope)
        self.assertIsNone(envelope['usage'])
        self.assertEqual(envelope['evidence_kind'], 'fixture')
        for key in ('source_before', 'management_before', 'backend_expected'):
            self.assertIsNone(row[key])
        before = execution.snapshot(), copy.deepcopy(self.saved)
        for _ in range(10):
            execution.poll()
        self.assertEqual(before, (execution.snapshot(), self.saved))
        output = os.environ.get('AIOS_SERVE_EVIDENCE_DIR')
        if output:
            path = Path(output)
            path.mkdir(parents=True, exist_ok=True)
            (path / 'messages-task.json').write_bytes(inference.encoded({'schema_version': 1,
                'snapshots': self.saved, 'completed': self.completed}))

    def test_capability_false_unknown_and_stale_binding_submit_zero_workers(self):
        with mock.patch.object(async_inference, 'start') as start:
            for report in (replace(self.capabilities, messages=False), replace(self.capabilities, messages=None),
                           replace(self.capabilities, deployment=replace(self.deployment, start_generation=2))):
                self.capabilities = report
                with self.assertRaisesRegex(ValueError, 'engine-capability-'):
                    self.execution()
            start.assert_not_called()
        self.assertFalse(self.saved)

    def test_optional_streaming_and_usage_fail_before_admission(self):
        with mock.patch.object(async_inference, 'start') as start:
            for option in ({'streaming': True}, {'require_usage': True}):
                with self.assertRaisesRegex(ValueError, 'capability'):
                    self.execution(**option)
            start.assert_not_called()
        self.assertFalse(self.saved)

    def test_messages_factory_rejects_legacy_bindings_before_save_or_start(self):
        with mock.patch.object(async_inference, 'start') as start:
            for key in ('config', 'source', 'management', 'space_context', 'prompt', 'backend_expected',
                        'engine_request'):
                with self.subTest(key=key), self.assertRaises(TypeError):
                    self.execution(**{key: None})
            start.assert_not_called()
        self.assertFalse(self.trace)
        self.assertFalse(self.saved)
        self.assertFalse(self.completed)

    def test_messages_reject_chatml_and_bounded_invalid_input(self):
        for messages in ('ChatML', [{'role': 'user', 'content': '<|im_start|>user'}],
                         [{'role': 'tool', 'content': 'tool'}], [{'role': 'user', 'content': 'x' * 4097}],
                         [{'role': 'user', 'content': 'hello', 'extra': 1}]):
            with self.subTest(messages=str(messages)[:50]), self.assertRaises(ValueError):
                prepare_messages(self.deployment, self.capabilities, messages, request_id=self.request_id)

    def test_prepared_mutation_and_repeat_start_rejected_before_spawn(self):
        prepared = self.prepared()
        with mock.patch.object(async_inference.subprocess, 'Popen') as spawn:
            for altered in (replace(prepared, _timeout=100), replace(prepared, _template=b'{}'),
                            replace(prepared, _lease=mock.Mock())):
                with self.assertRaises((ValueError, KeyError)):
                    async_inference.start(altered)
            spawn.assert_not_called()
        self.assertFalse(prepared._lease.used)
        pending = async_inference.start(prepared)
        self.addCleanup(pending.close)
        with self.assertRaisesRegex(ValueError, 'already-started'):
            async_inference.start(prepared)

    def test_subclass_prepared_messages_cannot_validate_or_spawn(self):
        class DerivedMessages(PreparedMessages):
            def validate_prepared(self):
                raise AssertionError('untrusted preparation ran')

        prepared = self.prepared()
        derived = DerivedMessages(prepared._input, prepared._template, prepared._timeout)
        with mock.patch.object(async_inference.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(TypeError, 'prepared-inference-required'):
                async_inference.start(derived)
            spawn.assert_not_called()
        self.assertFalse(derived._lease.used)

    def test_instance_validator_shadow_cannot_skip_messages_admission(self):
        prepared = replace(self.prepared(), _timeout=100)
        shadow = mock.Mock()
        prepared.__dict__['validate_prepared'] = shadow
        with mock.patch.object(async_inference.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(ValueError, 'prepared-messages'):
                async_inference.start(prepared)
            spawn.assert_not_called()
        shadow.assert_not_called()
        self.assertFalse(prepared._lease.used)

    def test_instance_output_shadow_cannot_accept_malformed_messages_result(self):
        prepared = self.prepared()
        shadow = mock.Mock(return_value={'outcome': 'OK'})
        prepared.__dict__['validated_output'] = shadow
        real_popen = subprocess.Popen
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / 'owned_messages_fixture.py'
            script.write_text("import sys\nsys.stdin.buffer.read()\nprint('{}')\n", encoding='utf-8')
            def spawn(argv, **kwargs):
                self.assertEqual(argv, prepared.worker_command)
                return real_popen([sys.executable, '-B', str(script)], **kwargs)
            with mock.patch.object(async_inference.subprocess, 'Popen', side_effect=spawn):
                pending = async_inference.start(prepared)
            with pending:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    result = pending.poll()
                    if result['done']:
                        break
                    time.sleep(.005)
                self.assertTrue(result['done'])
        self.assertEqual(result['receipt']['outcome'], 'ERROR')
        self.assertEqual(result['receipt']['error'], 'backend-failed')
        shadow.assert_not_called()

    def test_forged_legacy_start_lease_cannot_dispatch_twice(self):
        fixture = state_fixture.RequestStateTests()
        fixture.setUp()
        prepared = async_inference.prepare(fixture.kwargs['config'], 'hello', request_id=self.request_id)
        altered = replace(prepared, _lease=mock.Mock())
        with mock.patch.object(async_inference.subprocess, 'Popen') as spawn:
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, 'prepared-inference-changed'):
                    async_inference.start(altered)
            spawn.assert_not_called()

    def test_cancel_before_dispatch_and_late_cancel_preserve_terminal(self):
        pending, start = self.fake()
        execution = self.execution()
        execution.cancel(self.owner)
        execution.dispatch()
        start.assert_not_called()
        self.assertEqual(execution.snapshot()['request_state']['model_outcome'], 'NOT_STARTED')
        before = list(self.trace)
        self.assertEqual(execution.cancel(self.owner)['outcome'], 'ALREADY_TERMINAL')
        self.assertEqual(self.trace, before)

    def test_controlled_cancel_then_valid_result_keeps_answer_and_once_finalizer(self):
        pending, start = self.fake()
        execution = self.execution()
        execution.dispatch()
        execution.cancel(self.owner)
        self.assertLess(self.trace.index('save:CANCEL_REQUESTED'), self.trace.index('signal'))
        before = list(self.trace)
        execution.cancel(self.owner)
        self.assertEqual(self.trace, before)
        pending.value.update(done=True, worker_exit_code=0, receipt=self.answer())
        execution.poll()
        row = execution.snapshot()['request_state']
        self.assertEqual(row['model_outcome'], 'ANSWERED')
        self.assertIsNotNone(row['cancel_requested_ns'])
        self.assertIsNone(row['backend_stop'])
        for _ in range(5):
            execution.poll()
        self.assertEqual(len(self.completed), 1)
        self.assertEqual(start.call_count, 1)

    def test_result_observed_before_cancel_wins_without_signal(self):
        pending, _ = self.fake()
        execution = self.execution()
        execution.dispatch()
        pending.value.update(done=True, worker_exit_code=0, receipt=self.answer())
        self.assertEqual(execution.cancel(self.owner)['outcome'], 'ALREADY_TERMINAL')
        self.assertNotIn('signal', self.trace)

    def test_unknown_timeout_does_not_prove_backend_or_memory_exit(self):
        pending, _ = self.fake()
        execution = self.execution()
        execution.dispatch()
        receipt = self.prepared().receipt_template
        receipt['error'] = 'backend-timeout'
        pending.value.update(done=True, worker_exit_code=1, receipt=receipt)
        execution.poll()
        row = execution.snapshot()['request_state']
        self.assertEqual(row['model_outcome'], 'UNKNOWN')
        self.assertIsNone(row['backend_stop'])

    def test_nonlegacy_cancel_never_invokes_whole_instance_verifier(self):
        pending, _ = self.fake()
        execution = self.execution()
        execution.dispatch()
        execution.cancel(self.owner)
        verify = mock.Mock()
        with self.assertRaisesRegex(ValueError, 'instance-stop-unsupported'):
            execution.observe_backend_stop(self.owner, verify)
        verify.assert_not_called()

    def test_old_request_or_generation_result_poisons_only_old_task(self):
        pending, _ = self.fake()
        old = self.execution()
        old.dispatch()
        receipt = self.answer()
        receipt['deployment']['start_generation'] = 2
        pending.value.update(done=True, worker_exit_code=0, receipt=receipt)
        with self.assertRaises(RequestExecutionFailure):
            old.poll()
        self.assertFalse(self.completed)
        self.assertTrue(pending.closed)
        self.assertIsNone(old.snapshot()['request_state']['model_outcome'])
        with self.assertRaises(RequestExecutionFailure):
            old.dispatch()

    def test_old_cleanup_callback_and_stop_cannot_touch_replacement_instance(self):
        old_pending = runtime_fixture.FakePending(self.request_id, self.trace)
        next_id = str(uuid.uuid4())
        new_trace = []
        new_pending = runtime_fixture.FakePending(next_id, new_trace)
        with mock.patch.object(async_inference, 'start', side_effect=[old_pending, new_pending]):
            old = self.execution()
            old.dispatch()
            timeout = self.prepared().receipt_template
            timeout['error'] = 'backend-timeout'
            old_pending.value.update(done=True, worker_exit_code=1, receipt=timeout)
            old.poll()
            next_deployment = replace(self.deployment, instance_id=str(uuid.uuid4()), start_generation=2)
            new = RequestExecution.for_messages(save=lambda _: None, complete=lambda _: None,
                request_id=next_id, owner=self.owner, deployment=next_deployment,
                capabilities=replace(self.capabilities, deployment=next_deployment), messages=self.messages,
                clock=self.clock)
            new.dispatch()
            before = new.snapshot()
            old.close()
            old.close()
            old.cancel(self.owner)
            verify = mock.Mock()
            with self.assertRaisesRegex(ValueError, 'instance-stop-unsupported'):
                old.observe_backend_stop(self.owner, verify)
            verify.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'terminal-rewrite'):
                old._state.record_worker_exit(old_pending.value['worker_pid'], 0,
                    receipt=self.answer(), now_ns=self.clock())
            self.assertEqual(new.snapshot(), before)
            self.assertEqual(new_trace, [])
            new.close()

    def test_foreign_owner_and_stale_worker_request_cannot_finalize_or_signal(self):
        pending, _ = self.fake()
        execution = self.execution()
        execution.dispatch()
        before = execution.snapshot()
        with self.assertRaisesRegex(ValueError, 'owner-mismatch'):
            execution.cancel({**self.owner, 'process_start_ticks': self.owner['process_start_ticks'] + 1})
        self.assertEqual(execution.snapshot(), before)
        self.assertNotIn('signal', self.trace)
        pending.value.update(request_id=str(uuid.uuid4()))
        with self.assertRaises(RequestExecutionFailure):
            execution.poll()
        self.assertFalse(self.completed)

    def test_admission_running_terminal_and_cancel_save_failures_poison_without_retry(self):
        for phase in ('ACCEPTED', 'RUNNING', 'FINISHED', 'CANCEL_REQUESTED'):
            with self.subTest(phase=phase):
                self.setUp()
                pending, start = self.fake()
                if phase == 'ACCEPTED':
                    self.failure = phase
                    with self.assertRaises(RequestExecutionFailure):
                        self.execution()
                    start.assert_not_called()
                    continue
                execution = self.execution()
                if phase == 'RUNNING':
                    self.failure = phase
                    with self.assertRaises(RequestExecutionFailure):
                        execution.dispatch()
                else:
                    execution.dispatch()
                    self.failure = phase
                    if phase == 'FINISHED':
                        pending.value.update(done=True, worker_exit_code=0, receipt=self.answer())
                        action = execution.poll
                    else:
                        action = lambda: execution.cancel(self.owner)
                    with self.assertRaises(RequestExecutionFailure):
                        action()
                self.assertTrue(pending.closed)
                self.assertFalse(self.completed)
                self.assertNotIn('signal', self.trace)
                with self.assertRaises(RequestExecutionFailure):
                    execution.poll()
                self.assertEqual(start.call_count, 1)

    def test_finalizer_failure_is_once_only_and_writer_mismatch_rejected(self):
        pending, _ = self.fake()
        execution = self.execution()
        execution.dispatch()
        pending.value.update(done=True, worker_exit_code=0, receipt=self.answer())
        self.finalizer_failure = True
        with self.assertRaises(RequestExecutionFailure):
            execution.poll()
        with self.assertRaises(RequestExecutionFailure):
            execution.poll()
        self.assertEqual(len(self.completed), 1)
        errors = []
        def other_writer():
            try:
                execution.snapshot()
            except ValueError as error:
                errors.append(str(error))
        thread = threading.Thread(target=other_writer)
        thread.start()
        thread.join()
        self.assertEqual(errors, ['request-writer-mismatch'])

    def test_missing_echo_does_not_allow_forged_legacy_or_invalid_response(self):
        prepared = self.prepared()
        envelope = self.answer()
        for changed in ({**envelope, 'backend_execution': {}}, {**envelope, 'usage': {'total_tokens': 3}},
                        {**envelope, 'request_id': str(uuid.uuid4())}, {**envelope, 'response_sha256': '0' * 64}):
            with self.assertRaises(ValueError):
                MessagesFixtureAdapter.validate_envelope(changed, template=prepared.receipt_template)
        raw = json.loads(envelope['response_body'])
        for altered in ({**raw, 'prompt': 'invented echo'}, {**raw, 'model': 'other'},
                        {**raw, 'choices': [{**raw['choices'][0], 'finish_reason': None}]}):
            with self.assertRaises(ValueError):
                prepared.validated_output(inference.encoded({'response_body': json.dumps(altered)}), b'', 0)


if __name__ == '__main__':
    unittest.main()
