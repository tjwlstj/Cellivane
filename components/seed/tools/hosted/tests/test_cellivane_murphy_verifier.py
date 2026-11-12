"""Synthetic envelope/arithmetic attacks, without producer/runtime imports.

Most tests isolate the new envelope contract by mocking only the frozen raw
reader. One full physical synthetic ZIP/build/native-wire replay exercises
that reader too. No test launches a worker, model, compiler, HTTP or OS probe.
"""
from __future__ import annotations

import ast
import copy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("independent_murphy", TOOLS / "verify_cellivane_murphy.py")
v = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)

HOST = {"schema_version": 1, "scope": "local-nonidentifying-host-profile-not-attestation", "os": "Windows",
    "os_version": "SYNTHETIC-OS", "machine": "AMD64", "cpu_name": "SYNTHETIC-CPU", "cpu_vendor": "SYNTHETIC-VENDOR",
    "logical_processors": 8, "physical_memory_bytes": 32 * 1024**3}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def record(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": sha256(raw).hexdigest()}


def base(amount=8, reason="no-calibration"):
    return {"schema_version": 1, "policy": "murphy-session-cost-v1", "expected_requests": amount, "margin_percent": 5,
        "eligible": False, "selected_mode": "none", "reason": reason, "rounds": [], "scope": "fixed-calibration-corpus-cost-estimate"}


def eligible(amount=8, qualifies=(True, True)):
    # The fixture has P_none=10, G_none=1, P_murphy=12, G_murphy=.5.
    rounds = [{"index": index, "none": {"preparation_s": 10., "mean_request_s": 1., "estimated_session_s": 10. + amount},
        "murphy": {"preparation_s": 12., "mean_request_s": .5, "estimated_session_s": 12. + amount * .5},
        "qualifies": value} for index, value in enumerate(qualifies)]
    selected = all(qualifies)
    return {"schema_version": 1, "policy": "murphy-session-cost-v1", "expected_requests": amount, "margin_percent": 5,
        "eligible": True, "selected_mode": "murphy" if selected else "none",
        "reason": "consistent-session-savings" if selected else "insufficient-consistent-savings", "rounds": rounds,
        "scope": "fixed-calibration-corpus-cost-estimate"}


class Fixture:
    def __init__(self, root):
        self.root = Path(root)
        self.source_root = self.root / "synthetic-source"
        self.runtime_path = self.root / "runtime.json"
        self.calibration_path = self.root / "calibration.json"
        self.choice_path = self.root / "choice.json"
        sources = []
        for name in sorted(v.runtime.SOURCE_PATHS):
            path = self.source_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"# SYNTHETIC NOT EXECUTED " + name.encode())
            sources.append({"path": name, "sha256": record(path)["sha256"]})
        phases = []
        for index, mode in enumerate(("none", "murphy", "murphy", "none")):
            rows = []
            for case in ("addition", "word"):
                rows.append({"case": case, "wall_s": 1 if mode == "none" else .5,
                    "response": {"text": "SYNTHETIC", "tokens": [1, 2], "prompt_tokens": 10, "completion_tokens": 2,
                        "finish_reason": "stop", "rendered_prompt_sha256": sha256(case.encode()).hexdigest()}})
            phases.append({"mode": mode, "preparation": {"preparation_s": 10 if mode == "none" else 12}, "requests": rows})
        self.summary = {"schema_version": 1, "scope": "runtime-murphy-cpu-smoke", "source": {"files": sources},
            "model": {"sha256": "1" * 64}, "worker": {"sha256": "2" * 64}, "build_receipt": {"sha256": "3" * 64},
            "engine": {"engine_identity": "4" * 64}, "phases": phases}
        self.replayed = {"verdict": "PASS", "scope": "SYNTHETIC-FROZEN-READER-DOUBLE", "runtime_generations": 10}
        self.envelope = {"schema_version": 1, "artifact_family": "cellivane-murphy-calibration-v1", "run_id": str(uuid4()),
            "created_at_utc": "2026-10-15T00:00:00+00:00", "outcome": "COMPLETED", "error": None,
            "host_before": copy.deepcopy(HOST), "host_after": copy.deepcopy(HOST), "runtime_replay": copy.deepcopy(self.replayed),
            "controller_source": self.controllers(), "controller_after_sha256": None}
        controller_sha = v.digest({row["path"]: row["sha256"] for row in self.envelope["controller_source"]["files"]})
        self.envelope["controller_after_sha256"] = controller_sha
        self.choice = {"schema_version": 1, "artifact_family": "cellivane-murphy-choice-v1", "run_id": str(uuid4()),
            "created_at_utc": "2026-10-15T01:00:00+00:00", "context": {"host": copy.deepcopy(HOST), "identity": {
                "runtime_source_sha256": v.digest({row["path"]: row["sha256"] for row in sources}),
                "controller_source_sha256": controller_sha, "model_sha256": "1" * 64, "worker_sha256": "2" * 64,
                "build_receipt_sha256": "3" * 64, "engine_identity": "4" * 64}}, "calibration": None, "decision": eligible()}
        self.reseal()

    def controllers(self):
        rows = []
        for name in sorted(v.CONTROLLER_PATHS):
            raw = b"# SYNTHETIC CONTROLLER NOT EXECUTED " + name.encode()
            current = self.source_root / name
            current.parent.mkdir(parents=True, exist_ok=True)
            current.write_bytes(raw)
            snapshot = "controller-source-snapshot/" + name
            saved = self.root / snapshot
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(raw)
            rows.append({"path": name, "bytes": len(raw), "sha256": sha256(raw).hexdigest(), "snapshot": snapshot})
        return {"root": str(self.source_root), "files": rows, "scope": "declared-policy-controller-reader-source"}

    def reseal(self):
        self.runtime_path.write_bytes(encode(self.summary))
        self.envelope["runtime_summary"] = record(self.runtime_path)
        self.calibration_path.write_bytes(encode(self.envelope))
        self.choice["calibration"] = record(self.calibration_path)
        self.choice_path.write_bytes(encode(self.choice))


class MurphyContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.f = Fixture(self.temporary.name)
        context = patch.object(v.runtime, "replay", side_effect=lambda *args: copy.deepcopy(self.f.replayed))
        self.raw_reader = context.start()
        self.addCleanup(context.stop)

    def evaluate(self, source_root=None):
        self.f.reseal()
        return v.evaluate_choice(self.f.choice_path, source_root)

    def test_valid_calibration_and_both_rounds_cost_gate(self):
        candidate = v.verified_calibration(self.f.calibration_path)
        self.assertTrue(candidate["outputs_equal"])
        self.assertEqual(candidate["rounds"][1]["none"]["preparation_s"], 10.)
        result = self.evaluate(self.f.source_root)
        self.assertEqual((result["verdict"], result["selected"], result["eligible"]), ("PASS", "murphy", True))
        self.assertEqual(result["context_scope"], "current-source-files-compared")
        self.assertTrue(all(value is False for value in result["claims"].values()))
        self.assertEqual(self.raw_reader.call_count, 2)

    def test_no_calibration_uses_explicit_none_without_raw_reader(self):
        self.f.choice.update(calibration=None, decision=base())
        self.f.choice_path.write_bytes(encode(self.f.choice))
        result = v.evaluate_choice(self.f.choice_path)
        self.assertEqual((result["selected"], result["reason"], result["eligible"]), ("none", "no-calibration", False))
        self.raw_reader.assert_not_called()

    def test_legacy_raw_summary_requires_replay_and_never_infers_host(self):
        self.f.choice["calibration"] = record(self.f.runtime_path)
        self.f.choice["decision"] = base(reason="legacy-no-host")
        self.f.choice_path.write_bytes(encode(self.f.choice))
        result = v.evaluate_choice(self.f.choice_path)
        self.assertEqual(result["reason"], "legacy-no-host")
        self.raw_reader.assert_called_once_with(str(self.f.runtime_path), None)

    def test_one_failing_round_cannot_be_hidden_by_faster_other_round(self):
        rounds = v.normalized_rounds(self.f.summary)
        rounds[1]["murphy"]["request_wall_s"] = [2, 2]
        result = v.arithmetic(rounds, 8)
        self.assertEqual([row["qualifies"] for row in result["rounds"]], [True, False])
        self.assertEqual(result["selected_mode"], "none")
        self.assertTrue(result["eligible"])

    def test_five_percent_exact_boundary_and_just_above_are_distinct(self):
        rounds = [{mode: {"preparation_s": 0, "request_wall_s": [1, 1] if mode == "none" else [.95, .95]}
            for mode in ("none", "murphy")} for _ in range(2)]
        self.assertEqual(v.arithmetic(rounds, 1)["selected_mode"], "murphy")
        rounds[1]["murphy"]["request_wall_s"][1] = .950001
        self.assertEqual(v.arithmetic(rounds, 1)["selected_mode"], "none")

    def test_expected_count_bool_float_zero_and_overflow_fail(self):
        for amount in (True, False, 0, 1025, 1., "8", None):
            with self.subTest(amount=amount), self.assertRaisesRegex(ValueError, "expected-requests"):
                v.arithmetic(v.normalized_rounds(self.f.summary), amount)

    def test_request_count_endpoints_and_nonfinite_timings(self):
        self.assertEqual(v.arithmetic(v.normalized_rounds(self.f.summary), 1)["selected_mode"], "none")
        self.assertEqual(v.arithmetic(v.normalized_rounds(self.f.summary), 1024)["selected_mode"], "murphy")
        for value in (True, float("nan"), float("inf"), -1, 3601, 10**1000):
            rounds = v.normalized_rounds(self.f.summary)
            rounds[0]["none"]["preparation_s"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "calibration-seconds"):
                v.arithmetic(rounds, 8)

    def test_forged_policy_costs_or_eligibility_cannot_be_resealed(self):
        original = copy.deepcopy(self.f.choice["decision"])
        for change in (lambda d: d.update(eligible=False), lambda d: d.update(selected_mode="none"),
                lambda d: d["rounds"][0]["none"].update(estimated_session_s=1000.),
                lambda d: d.update(margin_percent=True)):
            self.f.choice["decision"] = copy.deepcopy(original)
            change(self.f.choice["decision"])
            with self.assertRaisesRegex(ValueError, "choice-decision-recompute"):
                self.evaluate()

    def test_stored_pass_label_does_not_replace_fresh_raw_replay(self):
        self.f.envelope["runtime_replay"]["runtime_generations"] = 9
        with self.assertRaisesRegex(ValueError, "calibration-raw-replay"):
            self.evaluate()

    def test_broken_raw_replay_never_becomes_safe_none(self):
        self.raw_reader.side_effect = ValueError("synthetic raw wire corrupted")
        self.f.choice["decision"] = base(reason="source-mismatch")
        with self.assertRaisesRegex(ValueError, "raw wire corrupted"):
            self.evaluate()

    def test_host_change_during_calibration_is_invalid_not_mismatch_baseline(self):
        self.f.envelope["host_after"]["logical_processors"] = 16
        self.f.choice["decision"] = base(reason="host-profile-mismatch")
        with self.assertRaisesRegex(ValueError, "calibration-host-changed"):
            self.evaluate()

    def test_host_bool_and_extra_identifier_fields_are_rejected(self):
        for field, value in (("logical_processors", True), ("physical_memory_bytes", True), ("machine", ""),
                ("serial_number", "not allowed")):
            host = copy.deepcopy(HOST)
            host[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                v.host(host)

    def test_controller_missing_duplicate_and_snapshot_traversal_fail(self):
        original = copy.deepcopy(self.f.envelope["controller_source"]["files"])
        for mutation in (lambda rows: rows.pop(), lambda rows: rows.__setitem__(1, copy.deepcopy(rows[0])),
                lambda rows: rows[0].update(snapshot="../../escape")):
            self.f.envelope["controller_source"]["files"] = copy.deepcopy(original)
            mutation(self.f.envelope["controller_source"]["files"])
            with self.assertRaisesRegex(ValueError, "controller-source"):
                self.evaluate()

    def test_controller_snapshot_bytes_and_after_digest_must_match(self):
        row = self.f.envelope["controller_source"]["files"][0]
        path = self.f.root / row["snapshot"]
        original = path.read_bytes()
        path.write_bytes(b"tampered controller")
        with self.assertRaisesRegex(ValueError, "controller-source-snapshot"):
            self.evaluate()
        path.write_bytes(original)
        self.f.envelope["controller_after_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "calibration-controller-changed"):
            self.evaluate()

    def test_source_mismatch_has_priority_over_other_inapplicability(self):
        identity = self.f.choice["context"]["identity"]
        identity["runtime_source_sha256"] = "f" * 64
        identity["model_sha256"] = "f" * 64
        self.f.choice["context"]["host"]["cpu_name"] = "OTHER CPU"
        self.f.choice["created_at_utc"] = "2026-10-17T00:00:00Z"
        self.f.choice["decision"] = base(reason="source-mismatch")
        self.assertEqual(self.evaluate()["reason"], "source-mismatch")

    def test_each_model_worker_build_engine_mismatch_has_explicit_none_reason(self):
        original = copy.deepcopy(self.f.choice["context"]["identity"])
        for field in ("model_sha256", "worker_sha256", "build_receipt_sha256", "engine_identity"):
            self.f.choice["context"]["identity"] = {**original, field: "f" * 64}
            self.f.choice["decision"] = base(reason="identity-mismatch")
            with self.subTest(field=field):
                self.assertEqual(self.evaluate()["reason"], "identity-mismatch")

    def test_recorded_host_mismatch_is_ineligible_not_attestation(self):
        self.f.choice["context"]["host"]["cpu_vendor"] = "OTHER VENDOR"
        self.f.choice["decision"] = base(reason="host-profile-mismatch")
        result = self.evaluate()
        self.assertFalse(result["eligible"])
        self.assertFalse(result["claims"]["host_attestation"])

    def test_age_boundaries_and_future_calibration(self):
        for stamp in ("2026-10-15T00:00:00Z", "2026-10-16T00:00:00+00:00"):
            self.f.choice["created_at_utc"] = stamp
            self.assertTrue(self.evaluate()["eligible"])
        for stamp in ("2026-10-14T23:59:59Z", "2026-10-16T00:00:01Z"):
            self.f.choice["created_at_utc"] = stamp
            self.f.choice["decision"] = base(reason="calibration-expired")
            self.assertEqual(self.evaluate()["reason"], "calibration-expired")

    def test_naive_or_non_utc_timestamp_is_rejected(self):
        for value in ("2026-10-15T00:00:00", "2026-10-15T09:00:00+09:00", "not a date", True):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "utc-timestamp"):
                v.timestamp(value)

    def test_each_output_field_is_compared_across_all_four_phases(self):
        response = self.f.summary["phases"][3]["requests"][0]["response"]
        original = copy.deepcopy(response)
        for field, value in (("text", "OTHER"), ("tokens", [7, 8]), ("prompt_tokens", 11), ("completion_tokens", 3),
                ("finish_reason", "length"), ("rendered_prompt_sha256", "f" * 64)):
            response.clear()
            response.update({**original, field: value})
            self.f.choice["decision"] = base(reason="output-mismatch")
            with self.subTest(field=field):
                self.assertEqual(self.evaluate()["reason"], "output-mismatch")

    def test_corrupt_or_failed_calibration_does_not_fallback(self):
        self.f.envelope["outcome"] = "FAILED"
        with self.assertRaisesRegex(ValueError, "calibration-not-completed"):
            self.evaluate()
        self.f.envelope["outcome"] = "COMPLETED"
        self.f.calibration_path.write_bytes(b'{"scope":"bad","scope":"bad"}')
        self.f.choice["calibration"] = record(self.f.calibration_path)
        self.f.choice_path.write_bytes(encode(self.f.choice))
        with self.assertRaisesRegex(ValueError, "duplicate-json-key"):
            v.evaluate_choice(self.f.choice_path)
        self.f.calibration_path.write_bytes(b"[]")
        self.f.choice["calibration"] = record(self.f.calibration_path)
        self.f.choice_path.write_bytes(encode(self.f.choice))
        with self.assertRaisesRegex(ValueError, "calibration-object-required"):
            v.evaluate_choice(self.f.choice_path)

    def test_choice_unknown_keys_and_bool_schema_do_not_pass(self):
        self.f.choice["requested_preparation"] = "murphy"
        with self.assertRaisesRegex(ValueError, "choice-fields"):
            self.evaluate()
        del self.f.choice["requested_preparation"]
        self.f.choice["schema_version"] = True
        with self.assertRaisesRegex(ValueError, "choice-family"):
            self.evaluate()

    def test_current_source_is_optional_but_declared_scope_is_explicit(self):
        self.assertEqual(self.evaluate()["context_scope"], "declared-context-not-current-source-attestation")
        file = self.f.source_root / "hosted/experimental/cellivane_runtime/core.py"
        file.write_bytes(b"changed current source")
        with self.assertRaisesRegex(ValueError, "choice-current-source-mismatch"):
            self.evaluate(self.f.source_root)

    def test_runtime_pairing_reverses_second_interleaved_round(self):
        self.f.summary["phases"][3]["preparation"]["preparation_s"] = 23
        self.f.summary["phases"][2]["preparation"]["preparation_s"] = 31
        rounds = v.normalized_rounds(self.f.summary)
        self.assertEqual(rounds[1]["none"]["preparation_s"], 23.)
        self.assertEqual(rounds[1]["murphy"]["preparation_s"], 31.)

    def test_reader_imports_only_independent_readers_and_stdlib(self):
        tree = ast.parse((TOOLS / "verify_cellivane_murphy.py").read_text(encoding="utf-8"))
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        self.assertFalse(any(name and (name.startswith("cellivane_") or name.startswith("hosted")) for name in imports))


class MurphyFullPhysicalReplayTests(unittest.TestCase):
    def test_complete_physical_synthetic_calibration_then_choice(self):
        support_spec = importlib.util.spec_from_file_location("runtime_fixture_support", TOOLS / "tests/test_cellivane_runtime_verifier.py")
        support = importlib.util.module_from_spec(support_spec)
        support_spec.loader.exec_module(support)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = support.SyntheticAssets(root / "assets")
            model = record(assets.model)
            with patch.object(v.runtime.spec, "ARCHIVE_SHA", assets.archive_sha), \
                    patch.object(v.runtime, "MODEL_BYTES", model["bytes"]), patch.object(v.runtime, "MODEL_SHA", model["sha256"]), \
                    patch.object(v.runtime, "INPUT_PINS", assets.input_pins):
                physical = support.FullFixture(root, assets)
                calibration_root = root / "new-envelope"
                calibration_root.mkdir()
                f = Fixture(calibration_root)
                f.summary = physical.summary
                f.runtime_path = physical.path
                f.envelope["runtime_replay"] = v.runtime.replay(physical.path)
                f.choice["context"]["identity"].update(runtime_source_sha256=v.digest(physical.hashes),
                    model_sha256=model["sha256"], worker_sha256=physical.summary["worker"]["sha256"],
                    build_receipt_sha256=physical.summary["build_receipt"]["sha256"], engine_identity=assets.identity)
                # Both modes in the physical fixture have identical measured
                # costs and Murphy adds preparation: no consistent saving.
                f.choice["decision"] = v.arithmetic(v.normalized_rounds(physical.summary), 8)
                f.reseal()
                candidate = v.verified_calibration(f.calibration_path)
                self.assertTrue(candidate["outputs_equal"])
                result = v.evaluate_choice(f.choice_path)
                self.assertEqual((result["verdict"], result["selected"], result["eligible"]), ("PASS", "none", True))
                self.assertEqual(result["reason"], "insufficient-consistent-savings")


if __name__ == "__main__":
    unittest.main()
