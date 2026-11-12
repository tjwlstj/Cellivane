"""Independent raw-protocol and lifecycle forgeries fail even after resealing."""
from __future__ import annotations

import ast
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools/hosted'))
from verify_engine_fixture import encoded, digest, verify_record, read
from verify_agent import SERVE_SOURCES
from verify_boot import parse


def fixture():
    deployment = {'engine': {'adapter_kind': 'messages-fixture', 'wire_protocol': 'messages-json',
        'evidence_kind': 'fixture', 'contract_version': 1}, 'model_id': 'fixture-model',
        'service_id': '00000000-0000-4000-8000-000000000001',
        'instance_id': '00000000-0000-4000-8000-000000000002', 'start_generation': 1, 'ownership': 'attached'}
    body = encoded({'model': deployment['model_id'], 'messages': [{'role': 'user', 'content': 'hello'}],
                    'stream': False}).decode()
    template = {'schema_version': 1, 'adapter_kind': 'messages-fixture',
        'request_id': '00000000-0000-4000-8000-000000000003', 'deployment': deployment,
        'request_body': body, 'request_sha256': digest(body.encode()), 'response_body': None,
        'response_sha256': None, 'content': None, 'usage': None, 'outcome': 'ERROR', 'error': None,
        'evidence_kind': 'fixture', 'elapsed_ns': 0}
    row = {'schema_version': 2, 'adapter_kind': template['adapter_kind'], 'request_id': template['request_id'],
        'owner': {'host_boot_id': '00000000-0000-4000-8000-000000000004', 'process_id': 303,
                  'process_start_ticks': 100, 'uid': 1000}, 'deployment': deployment,
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
    response = encoded({'id': 'fixture-response', 'model': deployment['model_id'], 'choices': [
        {'index': 0, 'message': {'role': 'assistant', 'content': 'fixture answer'}, 'finish_reason': 'stop'}]}).decode()
    receipt = {**template, 'response_body': response, 'response_sha256': digest(response.encode()),
               'content': 'fixture answer', 'outcome': 'OK', 'elapsed_ns': 5}
    row.update(revision=3, phase='FINISHED', model_outcome='ANSWERED', updated_ns=20, finished_ns=20,
               worker_exit_code=0, inference_receipt=receipt)
    worker.update(done=True, worker_exit_code=0, worker_exit_observed_monotonic_ns=19, receipt=receipt,
                  output_bytes={'stdout': len(encoded({'response_body': response})), 'stderr': 0})
    save(worker)
    return {'schema_version': 1, 'snapshots': snapshots, 'completed': [copy.deepcopy(row)]}


class EngineFixtureVerifierTests(unittest.TestCase):
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

    def reseal_content(self, content):
        for receipt in self.receipts():
            response = json.loads(receipt['response_body'])
            response['choices'][0]['message']['content'] = content
            receipt.update(response_body=encoded(response).decode(), content=content)
            receipt['response_sha256'] = digest(receipt['response_body'].encode())
        worker = self.value['snapshots'][-1]['worker_progress']
        worker['output_bytes']['stdout'] = len(encoded({'response_body': worker['receipt']['response_body']}))
        return len(worker['receipt']['response_body'].encode())

    def test_distinct_raw_messages_protocol_passes_as_fixture_only(self):
        result = verify_record(self.value)
        self.assertEqual(result['outcome'], 'PASS', result)
        self.assertEqual(result['model_outcome'], 'ANSWERED')
        self.assertFalse(result['real_engine_compatibility'])
        self.assertFalse(result['process_liveness_verified'])
        self.assertEqual(result['source_files_verified'], 0)

    def test_fabricated_echo_usage_and_legacy_binding_are_rejected_after_hash_reseal(self):
        for field, value in (('prompt', 'hello'), ('usage', {}), ('backend_execution', {})):
            self.value = fixture()
            for receipt in self.receipts():
                raw = json.loads(receipt['response_body'])
                raw[field] = value
                receipt['response_body'] = encoded(raw).decode()
                receipt['response_sha256'] = digest(receipt['response_body'].encode())
            with self.subTest(field=field):
                self.rejected('fixture_response')
        self.value = fixture()
        for receipt in self.receipts():
            receipt['usage'] = {'total_tokens': 0}
        self.rejected('fixture_envelope_boundary')

    def test_stale_deployment_or_worker_callback_cannot_complete_new_task(self):
        for name, value in (('deployment', {**self.value['completed'][0]['deployment'], 'start_generation': 2}),
                            ('request_id', '00000000-0000-4000-8000-000000000009')):
            self.value = fixture()
            for receipt in self.receipts():
                receipt[name] = value
            with self.subTest(name=name):
                self.rejected('fixture_envelope_join')
        self.value = fixture()
        self.value['snapshots'][-1]['worker_progress']['worker_pid'] = 1010
        self.rejected('fixture_worker_identity')

    def test_timeout_or_unknown_is_never_an_answer(self):
        self.value['snapshots'][-1]['worker_progress']['timed_out'] = True
        self.rejected('fixture_worker_answer')
        self.value = fixture()
        for receipt in self.receipts():
            receipt.update(outcome='ERROR', error='backend-timeout', response_body=None,
                           response_sha256=None, content=None)
        self.rejected('fixture_model_outcome')

    def test_request_echo_chatml_and_response_identity_are_not_generalized(self):
        self.value['snapshots'][0]['request_state']['source_before'] = {}
        self.rejected('fixture_task_unbound')
        self.value = fixture()
        for receipt in self.receipts():
            raw = json.loads(receipt['response_body'])
            raw['model'] = 'other-model'
            receipt['response_body'] = encoded(raw).decode()
            receipt['response_sha256'] = digest(receipt['response_body'].encode())
        self.rejected('fixture_response_model')

    def test_completion_once_only_and_terminal_rewrite_fail(self):
        self.value['completed'].append(copy.deepcopy(self.value['completed'][0]))
        self.rejected('fixture_bundle_shape')
        self.value = fixture()
        self.value['completed'][0]['worker_process_id'] += 1
        self.rejected('fixture_finalization')
        self.value = fixture()
        self.value['snapshots'].append(copy.deepcopy(self.value['snapshots'][-1]))
        self.rejected('fixture_task_transition')

    def test_worker_exit_time_and_raw_output_length_are_checked(self):
        self.value['snapshots'][-1]['worker_progress']['worker_exit_observed_monotonic_ns'] = 21
        self.rejected('fixture_worker_exit_time')
        self.value = fixture()
        self.value['snapshots'][-1]['worker_progress']['output_bytes']['stdout'] += 1
        self.rejected('fixture_worker_answer_bytes')
        for name, limit in (('stdout', 131072), ('stderr', 16384)):
            self.value = fixture()
            self.value['snapshots'][-1]['worker_progress']['output_bytes'][name] = limit + 1
            with self.subTest(stream=name):
                self.rejected('fixture_worker_overflow')
        self.value = fixture()
        for receipt in self.receipts():
            receipt.update(outcome='ERROR', error='backend-failed', response_body=None,
                           response_sha256=None, content=None)
        for row in (self.value['snapshots'][-1]['request_state'], self.value['completed'][0]):
            row['model_outcome'] = 'UNKNOWN'
        worker = self.value['snapshots'][-1]['worker_progress']
        # total counts all drained bytes, while only the bounded prefix is kept.
        # Exit may precede the overflow callback, preserving code 0 and no stop.
        worker.update(io_error='stdout-limit', output_bytes={'stdout': 512 * 1024, 'stderr': 0})
        self.assertEqual(verify_record(self.value)['outcome'], 'PASS')
        worker['io_error'] = None
        self.rejected('fixture_worker_overflow')
        worker.update(io_error='stderr-limit', output_bytes={'stdout': 0, 'stderr': 16384})
        self.rejected('fixture_worker_overflow')

    def test_duplicate_raw_fields_cannot_pass_a_new_hash(self):
        for receipt in self.receipts():
            receipt['response_body'] = receipt['response_body'].replace('"model":', '"model":"duplicate","model":')
            receipt['response_sha256'] = digest(receipt['response_body'].encode())
        self.rejected('duplicate_key:model')

    def test_exact_source_manifest_and_modified_bytes_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hashes = {}
            for name in SERVE_SOURCES:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'# independent source fixture\n')
                hashes[name] = digest(target.read_bytes())
            manifest = {'schema_version': 1, 'source_hashes': hashes}
            result = verify_record(self.value, source_manifest=manifest, source_root=root)
            self.assertEqual((result['outcome'], result['source_files_verified']), ('PASS', 32), result)
            name = 'aios_engines/contracts.py'
            (root / name).write_bytes(b'# modified source\n')
            self.assertEqual(verify_record(self.value, source_manifest=manifest, source_root=root)['outcome'], 'FAIL')
            hashes.pop(name)
            self.assertEqual(verify_record(self.value, source_manifest=manifest, source_root=root)['outcome'], 'FAIL')

    def test_oversized_response_cannot_be_resealed_into_an_answer(self):
        self.assertGreater(self.reseal_content('x' * 17000), 16384)
        self.rejected('fixture_wire_size')
        self.value = fixture()
        overhead = self.reseal_content('x') - 1
        self.assertEqual(self.reseal_content('x' * (16384 - overhead)), 16384)
        self.assertEqual(verify_record(self.value)['outcome'], 'PASS')
        self.assertEqual(self.reseal_content('x' * (16385 - overhead)), 16385)
        self.rejected('fixture_wire_size')
        self.value = fixture()
        self.assertGreater(self.reseal_content('\ud55c' * 6000), 16384)
        self.rejected('fixture_wire_size')

    def test_verifier_imports_no_runtime_producer(self):
        source = ROOT / 'tools/hosted/verify_engine_fixture.py'
        modules = [node.module for node in ast.walk(ast.parse(source.read_text())) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any(name and name.startswith('aios_') for name in modules))


if __name__ == '__main__':
    unittest.main()
