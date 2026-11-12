"""No-model orchestration ordering, fail-fast and identity-drift checks."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cellivane_efficiency_lab as lab


class EfficiencyOrchestrationTests(unittest.TestCase):
    def test_fail_stops_after_first_phase_without_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(lab.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout=b'failed fixture\n')) as run, redirect_stdout(io.StringIO()):
                result = lab.main(['--model-file', 'fixture', '--asset-root', folder, '--storage-root', folder])
            self.assertEqual(result, 1)
            self.assertEqual(run.call_count, 1)
            saved = json.loads(next(Path(folder).glob('calibration-matrices/*/orchestration.json')).read_text())
            self.assertEqual(saved['outcome'], 'FAILED')
            self.assertEqual(saved['phases'][0]['exit_code'], 1)

    def test_exact_order_completes_and_identity_drift_is_rejected(self):
        for drift in (False, True):
            with self.subTest(drift=drift), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                profiles = []
                def simulate(argv, **unused):
                    profile = argv[argv.index('--profile') + 1]
                    profiles.append(profile)
                    path = root / 'efficiency-runs' / str(uuid4()) / 'soak.json'
                    path.parent.mkdir(parents=True)
                    value = {'run_id': path.parent.name, 'acceptance': 'PASS', 'outcome': 'COMPLETED', 'mode': 'calibrate',
                        'profile': {'name': profile}, 'rows': [{}] * 56, 'source': {'fixture': True},
                        'host_profile': {'fixture': len(profiles) if drift else 1}, 'model': {'fixture': True},
                        'corpus_sha256': 'a' * 64, 'backend': {'tree_sha256': 'b' * 64},
                        'metrics': {'median_wall_s': .25}}
                    path.write_text(json.dumps(value))
                    return SimpleNamespace(returncode=0, stdout=(json.dumps({'acceptance': 'PASS', 'summary': str(path)}) + '\n').encode())
                with patch.object(lab.subprocess, 'run', side_effect=simulate), redirect_stdout(io.StringIO()):
                    result = lab.main(['--model-file', 'fixture', '--asset-root', folder, '--storage-root', folder])
                self.assertEqual(result, 1 if drift else 0)
                self.assertEqual(profiles, list(lab.ORDER[:2] if drift else lab.ORDER))

    def test_timeout_preserves_partial_stdout_and_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            error = subprocess.TimeoutExpired('fixture', 600, output=b'partial fixture\n')
            with patch.object(lab.subprocess, 'run', side_effect=error) as run, redirect_stdout(io.StringIO()):
                result = lab.main(['--model-file', 'fixture', '--asset-root', folder, '--storage-root', folder])
            self.assertEqual(result, 1)
            self.assertEqual(run.call_count, 1)
            saved = json.loads(next(Path(folder).glob('calibration-matrices/*/orchestration.json')).read_text())
            self.assertTrue(saved['phases'][0]['timed_out'])
            self.assertEqual(Path(saved['phases'][0]['output']['path']).read_bytes(), b'partial fixture\n')


if __name__ == '__main__':
    unittest.main()
