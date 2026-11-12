"""Guard against false PASS from empty, skipped, stale, or timed-out suite output."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("workspace_check", Path(__file__).resolve().parents[1] / "check.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class UnittestOutcomeTests(unittest.TestCase):
    def test_complete_suite_passes(self):
        self.assertEqual(CHECK.classify_unittest_log("Ran 3 tests in 0.1s\n\nOK\n", 0)["outcome"], "PASS")

    def test_skips_are_reported(self):
        result = CHECK.classify_unittest_log("Ran 3 tests in 0.1s\n\nOK (skipped=1)\n", 0)
        self.assertEqual((result["outcome"], result["tests_executed"], result["skipped"]), ("PASS_WITH_SKIPS", 2, 1))

    def test_empty_or_zero_tests_never_pass(self):
        for text in ("", "Ran 0 tests in 0.0s\n\nOK\n"):
            self.assertEqual(CHECK.classify_unittest_log(text, 0)["outcome"], "FAIL")

    def test_all_skipped_is_not_run(self):
        self.assertEqual(CHECK.classify_unittest_log("Ran 3 tests in 0.1s\n\nOK (skipped=3)\n", 0)["outcome"], "NOT_RUN")

    def test_old_pass_cannot_override_failure_or_timeout(self):
        text = "Ran 3 tests in 0.1s\n\nOK\n"
        self.assertEqual(CHECK.classify_unittest_log(text, 1)["outcome"], "FAIL")
        self.assertEqual(CHECK.classify_unittest_log(text, 0, True)["outcome"], "TIMEOUT")

    def test_output_after_success_is_not_a_final_pass(self):
        text = "Ran 3 tests in 0.1s\n\nOK\nlate failure\n"
        self.assertEqual(CHECK.classify_unittest_log(text, 0)["outcome"], "FAIL")


if __name__ == "__main__":
    unittest.main()
