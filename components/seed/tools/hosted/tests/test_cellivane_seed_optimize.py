"""No-model timing/admission checks for the separate optimization launcher."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cellivane_seed_optimize as optimized


class EfficiencyRunnerTests(unittest.TestCase):
    def test_missing_auto_calibration_uses_named_reference_without_runtime_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            profile, decision = optimized.resolve_profile('auto', Path(folder) / 'missing.json')
            self.assertEqual(profile.name, 'reference')
            self.assertEqual(decision, {'mode': 'reference-default', 'artifact': None})

    def test_explicit_profile_does_not_adopt_an_unrelated_calibration_file(self):
        profile, decision = optimized.resolve_profile('gpu29', Path('does-not-exist'))
        self.assertEqual(profile.num_gpu, 29)
        self.assertEqual(decision['mode'], 'explicit')

    def test_duplicate_or_oversize_calibration_does_not_become_a_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'selection.json'
            for value in (b'{"schema_version":1,"schema_version":1}', b' ' * (256 * 1024 + 1)):
                path.write_bytes(value)
                with self.assertRaises(ValueError): optimized.resolve_profile('auto', path)

    def test_timed_audit_retains_real_durable_record_and_matching_sequence(self):
        with tempfile.TemporaryDirectory() as folder:
            audit = optimized.TimedAudit(Path(folder), time.perf_counter())
            with patch.object(optimized.os, 'fsync', wraps=optimized.os.fsync) as sync:
                audit.append('fixture', {'purpose': 'no-model'})
            self.assertEqual(sync.call_count, 1)
            self.assertEqual(audit.sequence, 1)
            self.assertEqual(audit.timings[0]['sequence'], 1)
            self.assertEqual(audit.timings[0]['kind'], 'fixture')
            self.assertGreater(audit.timings[0]['wall_s'], 0)
            raw = json.loads((audit.directory / '000001.json').read_text(encoding='utf-8'))
            self.assertEqual(raw['value'], {'purpose': 'no-model'})

    def test_response_timing_keeps_http_and_audit_reread_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            clock = time.perf_counter()
            audit = optimized.TimedAudit(Path(folder), clock)
            body = {'model': 'fixture'}
            def exchange(*args):
                audit.append('backend_exchange', {'fixture': True})
                return {'status': 200, 'request': body, 'body': {
                    'choices': [{'message': {'content': 'OK'}}], 'cellivane': {'execution': 'computed'}}}
            with patch.object(optimized, 'exchange', side_effect=exchange):
                row = optimized.response_row(18991, body, {'id': 'fixture', 'expected': 'OK'}, 0, audit, clock)
            self.assertTrue(optimized.answered(row))
            self.assertTrue(row['exact'])
            self.assertEqual(row['backend_receipt'], {'fixture': True})
            self.assertEqual(row['receipt_started_s'], row['completed_s'])
            self.assertGreaterEqual(row['receipt_completed_s'], row['receipt_started_s'])
            self.assertAlmostEqual(row['receipt_read_s'], row['receipt_completed_s'] - row['receipt_started_s'])
            self.assertAlmostEqual(row['wall_s'], row['completed_s'] - row['started_s'])

    @unittest.skipUnless(os.name == 'nt', 'Windows-owned-process launcher boundary')
    def test_bad_model_preserves_failed_record_without_launching_a_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model = root / 'wrong.gguf'
            model.write_bytes(b'wrong model fixture')
            with patch.object(optimized.lab, 'OwnedProcess') as launch, redirect_stdout(io.StringIO()):
                status = optimized.main(['--model-file', str(model), '--asset-root', str(root / 'assets'), '--storage-root', str(root)])
            self.assertEqual(status, 1)
            launch.assert_not_called()
            summary = json.loads(next(root.glob('efficiency-runs/*/soak.json')).read_text(encoding='utf-8'))
            self.assertEqual(summary['acceptance'], 'FAIL')
            self.assertEqual(summary['family'], 'cellivane-efficiency-run-v1')
            self.assertIn('soak-model-artifact-pin', summary['error'])
            self.assertEqual(len(summary['source']['sha256']), 21)


if __name__ == '__main__':
    unittest.main()
