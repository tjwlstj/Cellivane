"""Model-free controller gates; fake calibration is never model evidence."""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cellivane_murphy_lab as lab


def context():
    return {"host": {"synthetic": True}, "identity": {key: str(index) * 64 for index, key in enumerate((
        "runtime_source_sha256", "controller_source_sha256", "model_sha256", "worker_sha256",
        "build_receipt_sha256", "engine_identity"), 1)}}


def calibration(now):
    ctx = context()
    ids = ctx["identity"]
    mode = lambda preparation, wall: {"preparation_s": preparation, "request_wall_s": [wall, wall]}
    return {"envelope": {"host_before": ctx["host"], "created_at_utc": now},
            "summary": {"model": {"sha256": ids["model_sha256"]}, "worker": {"sha256": ids["worker_sha256"]},
                "build_receipt": {"sha256": ids["build_receipt_sha256"]}, "engine": {"engine_identity": ids["engine_identity"]}},
            "runtime_source_sha256": ids["runtime_source_sha256"],
            "controller_source_sha256": ids["controller_source_sha256"], "outputs_equal": True,
            "rounds": [{"none": mode(1, 1), "murphy": mode(2, .5)} for _ in range(2)]}


class ChoiceQualificationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc).isoformat()
        self.reference = {"path": "synthetic-calibration.json"}

    def decide(self, observed, ctx=None, now=None, count=100):
        with patch.object(lab.runtime, "read_json", return_value={"artifact_family": "synthetic"}), \
                patch.object(lab.verifier, "verified_calibration", return_value=observed) as replay:
            decision = lab.decide(self.reference, ctx or context(), now or self.now, count)
        replay.assert_called_once_with(self.reference["path"])
        return decision

    def test_missing_evidence_uses_baseline_without_reader(self):
        with patch.object(lab.verifier, "verified_calibration") as replay:
            decision = lab.decide(None, context(), self.now, 1)
        self.assertEqual(decision["reason"], "no-calibration")
        replay.assert_not_called()

    def test_legacy_record_is_replayed_but_has_no_host_qualification(self):
        with patch.object(lab.runtime, "read_json", return_value={"scope": "runtime-murphy-cpu-smoke"}), \
                patch.object(lab.raw_verifier, "replay", return_value={"verdict": "PASS"}) as replay:
            decision = lab.decide(self.reference, context(), self.now, 1024)
        replay.assert_called_once()
        self.assertFalse(decision["eligible"])
        self.assertEqual(decision["reason"], "legacy-no-host")

    def test_applicable_evidence_uses_cost_policy(self):
        decision = self.decide(calibration(self.now))
        self.assertTrue(decision["eligible"])
        self.assertEqual(decision["selected_mode"], "murphy")

    def test_source_identity_host_age_and_output_mismatch_disable_warmup(self):
        for kind, reason in (("source", "source-mismatch"), ("identity", "identity-mismatch"),
                             ("host", "host-profile-mismatch"), ("old", "calibration-expired"),
                             ("future", "calibration-expired"), ("output", "output-mismatch")):
            with self.subTest(kind=kind):
                observed = calibration(self.now)
                if kind == "source": observed["runtime_source_sha256"] = "f" * 64
                if kind == "identity": observed["summary"]["worker"]["sha256"] = "f" * 64
                if kind == "host": observed["envelope"]["host_before"] = {"other": True}
                if kind in ("old", "future"):
                    offset = timedelta(days=-2 if kind == "old" else 1)
                    observed["envelope"]["created_at_utc"] = (datetime.fromisoformat(self.now) + offset).isoformat()
                if kind == "output": observed["outputs_equal"] = False
                decision = self.decide(observed)
                self.assertEqual(decision["reason"], reason)
                self.assertEqual(decision["selected_mode"], "none")

    def test_corrupt_supplied_evidence_is_not_a_silent_fallback(self):
        with patch.object(lab.runtime, "read_json", return_value={}), \
                patch.object(lab.verifier, "verified_calibration", side_effect=ValueError("synthetic-corruption")):
            with self.assertRaises(ValueError): lab.decide(self.reference, context(), self.now, 1)


class ControllerDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.args = SimpleNamespace(mode="plan", calibration=None, expected_requests=1, port=18982)
        self.base = {"synthetic": True}
        self.chosen = lab.baseline(1, "no-calibration")

    def run_selected(self, *, decide_error=None, runtime_change=False, phase_error=None, snapshot_change=False):
        ctx = context()
        ctx["identity"]["runtime_source_sha256"] = lab.digest({})
        ctx["identity"]["controller_source_sha256"] = lab.digest({})
        if snapshot_change:
            ctx["identity"]["runtime_source_sha256"] = "f" * 64
        with patch.object(lab, "root_for", return_value=self.root), \
                patch.object(lab.runtime, "source_records", return_value={"files": []}), \
                patch.object(lab, "snapshot_controller", return_value={"files": []}), \
                patch.object(lab, "controller_hashes", return_value={}), \
                patch.object(lab, "context_for", return_value=ctx), \
                patch.object(lab, "checked_runtime", return_value={"changed": True} if runtime_change else self.base), \
                patch.object(lab, "decide", return_value=self.chosen, side_effect=decide_error), \
                patch.object(lab.verifier, "evaluate_choice", return_value={"verdict": "PASS"}), \
                patch.object(lab.runtime, "phase", return_value={"error": phase_error},
                             side_effect=phase_error if isinstance(phase_error, BaseException) else None) as phase, \
                redirect_stdout(io.StringIO()):
            result = lab.selected_run(self.args, self.base)
        return result, phase

    def test_plan_persists_choice_and_never_dispatches(self):
        result, phase = self.run_selected()
        self.assertEqual(result, 0)
        phase.assert_not_called()
        self.assertTrue((self.root / "choice.json").is_file())

    def test_bad_calibration_blocks_before_dispatch(self):
        result, phase = self.run_selected(decide_error=ValueError("synthetic-corruption"))
        self.assertEqual(result, 1)
        phase.assert_not_called()
        self.assertFalse(json.loads((self.root / "blocked.json").read_text())["native_dispatch_started"])

    def test_missing_supplied_path_blocks_before_dispatch(self):
        self.args.calibration = str(self.root / "missing.json")
        result, phase = self.run_selected()
        self.assertEqual(result, 1)
        phase.assert_not_called()
        self.assertTrue((self.root / "blocked.json").is_file())

    def test_artifact_change_during_replay_is_blocked_before_dispatch(self):
        self.args.mode = "smoke"
        result, phase = self.run_selected(runtime_change=True)
        self.assertEqual(result, 1)
        phase.assert_not_called()

    def test_source_change_between_snapshot_and_context_blocks_even_plan(self):
        result, phase = self.run_selected(snapshot_change=True)
        self.assertEqual(result, 1)
        phase.assert_not_called()
        self.assertFalse((self.root / "choice.json").exists())

    def test_selected_mode_is_dispatched_once_without_retry_after_failure(self):
        self.args.mode = "smoke"
        result, phase = self.run_selected(phase_error="synthetic-native-failure")
        self.assertEqual(result, 1)
        phase.assert_called_once()
        self.assertEqual(phase.call_args.args[2], "none")
        self.assertEqual(json.loads((self.root / "execution.json").read_text())["outcome"], "FAILED")

    def test_phase_preflight_exception_has_failed_execution_record(self):
        self.args.mode = "smoke"
        result, phase = self.run_selected(phase_error=RuntimeError("synthetic-ram-preflight"))
        self.assertEqual(result, 1)
        phase.assert_called_once()
        record = json.loads((self.root / "execution.json").read_text())
        self.assertIsNone(record["phase"])
        self.assertEqual(record["outcome"], "FAILED")
        self.assertIn("synthetic-ram-preflight", record["error"])


if __name__ == "__main__":
    unittest.main()
