"""Exercise the reader subprocess boundary without running inference or large hashes."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("efficiency_capture", Path(__file__).resolve().parents[1] / "cellivane_efficiency_capture.py")
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.summary = self.root / "summary.json"
        self.summary.write_bytes(b"{}\n")
        for name in capture.READERS:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"# reader fixture\n")

    def invoke(self, result, **kwargs):
        with patch.object(capture.subprocess, "run", return_value=result) as run:
            output = capture.capture(self.summary, self.root, **kwargs)
        return output, run

    def test_binary_capture_exact_argv_and_exclusive_rerun(self):
        result = subprocess.CompletedProcess([], 0, b'{"verdict":"PASS"}\r\n', b'')
        first, run = self.invoke(result)
        second, _ = self.invoke(result)
        self.assertEqual(first["outcome"], "PASS")
        self.assertNotEqual(first["stdout"], second["stdout"])
        self.assertEqual(Path(first["stdout"]).read_bytes(), result.stdout)
        receipt = json.loads(Path(first["invocation"]).read_bytes())
        self.assertEqual(len(receipt), 8)
        self.assertEqual(len(receipt["argv"]), 6)
        self.assertEqual(receipt["stdout_sha256"], sha256(result.stdout).hexdigest())
        self.assertEqual(receipt["summary_sha256_before"], receipt["summary_sha256_after"])
        self.assertIs(run.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_reader_failure_and_stderr_remain_preserved(self):
        result = subprocess.CompletedProcess([], 1, b'{"verdict":"FAIL"}', b'raw error\r\n')
        output, _ = self.invoke(result)
        self.assertEqual(output["outcome"], "FAIL")
        self.assertEqual(Path(output["stderr"]).read_bytes(), result.stderr)
        self.assertEqual(json.loads(Path(output["invocation"]).read_bytes())["returncode"], 1)

    def test_midflight_input_change_fails_even_with_reader_pass(self):
        def changed(*args, **kwargs):
            self.summary.write_bytes(b'{"changed":true}')
            return subprocess.CompletedProcess([], 0, b'{"verdict":"PASS"}', b'')
        with patch.object(capture.subprocess, "run", side_effect=changed):
            output = capture.capture(self.summary, self.root)
        self.assertEqual(output["outcome"], "FAIL")
        self.assertFalse(output["stable_inputs"])

    def test_matrix_receipt_required_before_subprocess(self):
        with patch.object(capture.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "matrix-receipt-required"):
                capture.capture(self.summary, self.root, matrix_only=True)
        run.assert_not_called()

    def test_timeout_preserves_partial_binary_diagnostics_and_failure_receipt(self):
        timeout = subprocess.TimeoutExpired("reader", 600, output=b'{"unfinished":', stderr=b'partial\r\n')
        with patch.object(capture.subprocess, "run", side_effect=timeout):
            output = capture.capture(self.summary, self.root)
        self.assertEqual(output["outcome"], "FAIL")
        self.assertTrue(output["timed_out"])
        self.assertEqual(Path(output["stdout"]).read_bytes(), timeout.stdout)
        self.assertEqual(Path(output["stderr"]).read_bytes(), timeout.stderr)
        receipt = json.loads(Path(output["invocation"]).read_bytes())
        self.assertIsNone(receipt["returncode"])
        self.assertEqual(len(receipt), 8)


if __name__ == "__main__":
    unittest.main()
