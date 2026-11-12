"""Synthetic collector receipts; no backend or model is exercised."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from tools.hosted import cellivane_efficiency_matrix as collector


POLICY_SOURCE = Path(__file__).resolve().parents[3] / collector.POLICY


def save(path, value):
    path.write_bytes(collector.encoded(value) + b"\n")


class MatrixFixture:
    def __init__(self, root):
        self.root = root
        self.source = root / "source-root"
        self.source.mkdir()
        for name in collector.SOURCE_PATHS | collector.VERIFICATION_PATHS:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(POLICY_SOURCE.read_bytes() if name == collector.POLICY else ("# synthetic " + name + "\n").encode())
        self.policy = collector.policy_from(self.source)
        self.sources = collector.current_hashes(self.source, collector.SOURCE_PATHS)
        self.readers = collector.current_hashes(self.source, collector.VERIFICATION_PATHS)
        self.summaries, self.verdicts, self.invocations, self.stderrs = [], [], [], []
        host = {"logical_processors": 16, "ram_total_bytes": 32 * 1024 ** 3,
                "gpu": {"index": 0, "name": "synthetic GPU", "driver_version": "fixture", "total_bytes": 8 * 1024 ** 3}}
        cases = [{"id": f"case-{index:02}", "prompt": f"synthetic prompt {index}", "expected": f"fixture-{index}"} for index in range(14)]
        for position, profile_name in enumerate(collector.ORDER):
            profile = self.policy.get_profile(profile_name)
            folder = root / str(uuid4())
            folder.mkdir()
            for name in collector.SOURCE_PATHS:
                path = folder / "source-snapshot" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((self.source / name).read_bytes())
            wall = {"reference": 1., "gpu29": .9, "gpu29-threads8": .85}[profile_name]
            rows = []
            for index in range(56):
                text = cases[index % 14]["expected"]
                rows.append({"index": index, "case": cases[index % 14]["id"], "wall_s": wall,
                    "response": {"status": 200, "body": {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": text}}]}},
                    "backend_receipt": {"outcome": "ANSWERED", "text": text}, "exact": True})
            summary = {"schema_version": 1, "family": "cellivane-efficiency-run-v1", "mode": "calibrate", "run_id": folder.name,
                "outcome": "COMPLETED", "acceptance": "PASS", "acceptance_errors": [], "error": None,
                "profile": profile.record(), "plan": profile.record(), "model_profile": "8b-q4", "model": deepcopy(collector.MODEL),
                "host_profile": deepcopy(host), "launch_probe": {"observation": {"memory": {"total_bytes": host["ram_total_bytes"]}, "gpu": deepcopy(host["gpu"])}},
                "source": {"root": str(self.source), "sha256": self.sources, "scope": "declared-21-file-efficiency-family-not-loader-attestation"},
                "backend": {"version": "0.40.2", "tree_sha256": "b" * 64, "executable": {"sha256": "e" * 64}, "archive": {"sha256": "a" * 64}},
                "cases": deepcopy(cases), "system": "synthetic system", "corpus_sha256": collector.digest(cases),
                "model_unchanged": True, "backend_unchanged": True, "source_unchanged": True,
                "telemetry_errors": [], "resource_guard_reason": None, "cleanup_errors": [], "rows": rows, "repeat": 4,
                "service_start_s": 1., "service_end_s": 61., "log": {"bytes": 100}}
            verdict = {"verdict": "PASS", "scope": collector.SCOPE, "run_id": folder.name, "mode": "calibrate", "profile": profile_name,
                "computed_responses": 56, "exact": 56, "drained_requests": 0, "recorded_service_s": 60., "resource_samples": 5,
                "source_files_checked": 21, "current_source_files_compared": True, "audit_records": 175, "audit_timings": 175,
                "log_work": {"bytes": 100, "polls": 59, "bytes_read": 200, "bytes_scanned": 100},
                "observed_gpu_layers": profile.num_gpu, "observed_native_threads": profile.num_thread,
                "claims": {name: False for name in collector.CLAIM_KEYS}}
            summary_path, verdict_path = folder / "soak.json", folder / "reader.stdout.json"
            invocation_path, stderr_path = folder / "reader.invocation.json", folder / "reader.stderr.txt"
            save(summary_path, summary)
            save(verdict_path, verdict)
            stderr_path.write_bytes(b"")
            invocation = {"argv": [sys.executable, "-B", str(self.source / collector.MAIN_READER), str(summary_path), "--source-root", str(self.source)],
                "returncode": 0, "stdout_sha256": sha256(verdict_path.read_bytes()).hexdigest(), "stderr_sha256": sha256(b"").hexdigest(),
                "verifier_sha256": self.readers[collector.MAIN_READER], "summary_sha256_before": sha256(summary_path.read_bytes()).hexdigest(),
                "summary_sha256_after": sha256(summary_path.read_bytes()).hexdigest(), "verification_source_sha256": self.readers}
            save(invocation_path, invocation)
            self.summaries.append(summary_path)
            self.verdicts.append(verdict_path)
            self.invocations.append(invocation_path)
            self.stderrs.append(stderr_path)

    def reseal(self, index):
        invocation = collector.load(self.invocations[index].read_bytes())
        invocation["summary_sha256_before"] = invocation["summary_sha256_after"] = sha256(self.summaries[index].read_bytes()).hexdigest()
        invocation["stdout_sha256"] = sha256(self.verdicts[index].read_bytes()).hexdigest()
        invocation["stderr_sha256"] = sha256(self.stderrs[index].read_bytes()).hexdigest()
        save(self.invocations[index], invocation)

    def change_summary(self, index, change, *, reseal=True):
        summary = collector.load(self.summaries[index].read_bytes())
        change(summary)
        save(self.summaries[index], summary)
        if reseal:
            self.reseal(index)

    def collect(self):
        return collector.collect(self.summaries, self.verdicts, self.invocations, self.stderrs, self.source)

    def argv(self):
        args = ["--source-root", str(self.source), "--output", str(self.root / "selection.json"), "--receipt", str(self.root / "matrix.json")]
        for name, paths in (("summary", self.summaries), ("verdict", self.verdicts), ("invocation", self.invocations), ("stderr", self.stderrs)):
            for path in paths:
                args.extend(("--" + name, str(path)))
        return args


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = MatrixFixture(Path(self.temp.name))

    def test_complete_matrix_binds_all_files_and_derives_correct_repeat_and_text_sha(self):
        selection, receipt = self.fixture.collect()
        self.assertEqual(set(selection), {"schema_version", "family", "host_profile", "candidate_reports"})
        self.assertLessEqual(len(collector.encoded(selection)) + 1, 256 * 1024)
        self.assertEqual(receipt["decision"]["selected_profile"]["name"], "gpu29-threads8")
        self.assertEqual(len(receipt["ordered_runs"]), 6)
        self.assertEqual(len(receipt["verification_source_sha256"]), 4)
        for report in selection["candidate_reports"]:
            self.assertEqual([row["index"] for row in report["rounds"]], [0, 1])
            self.assertEqual(report["identity"]["source_sha256"], collector.digest(self.fixture.sources))
            for round_ in report["rounds"]:
                self.assertEqual(len(round_["samples"]), 56)
                self.assertEqual({row["repeat"] for row in round_["samples"]}, {0, 1, 2, 3})
                self.assertEqual(round_["samples"][0]["text_sha256"], sha256(b"fixture-0").hexdigest())
        self.assertFalse(receipt["scope"]["final_soak_completed"])
        self.assertIn("not-clock-attestation", receipt["scope"]["input_order"])

    def test_profile_order_and_duplicate_run_identity_rejected(self):
        self.fixture.summaries[1], self.fixture.summaries[2] = self.fixture.summaries[2], self.fixture.summaries[1]
        with self.assertRaisesRegex(ValueError, "ABC-CBA"):
            self.fixture.collect()
        self.fixture.summaries[1], self.fixture.summaries[2] = self.fixture.summaries[2], self.fixture.summaries[1]
        for values in (self.fixture.summaries, self.fixture.verdicts, self.fixture.invocations, self.fixture.stderrs):
            values[-1] = values[0]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.fixture.collect()

    def test_pass_reader_cannot_be_reused_after_summary_changes(self):
        self.fixture.change_summary(0, lambda row: row.__setitem__("unclaimed_annotation", "changed"), reseal=False)
        with self.assertRaisesRegex(ValueError, "before-after"):
            self.fixture.collect()

    def test_mismatched_host_backend_and_corpus_rejected_even_when_receipts_resealed(self):
        changes = [lambda row: (row["host_profile"].__setitem__("logical_processors", 32)),
                   lambda row: row["backend"].__setitem__("tree_sha256", "f" * 64),
                   lambda row: row.__setitem__("system", "different system")]
        for change in changes:
            original = self.fixture.summaries[1].read_bytes()
            self.fixture.change_summary(1, change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "matrix-"):
                self.fixture.collect()
            self.fixture.summaries[1].write_bytes(original)
            self.fixture.reseal(1)

    def test_model_pin_changed_rejected(self):
        self.fixture.change_summary(1, lambda row: row["model"].__setitem__("bytes", row["model"]["bytes"] - 1))
        with self.assertRaisesRegex(ValueError, "fixed-model-pin"):
            self.fixture.collect()

    def test_source_snapshot_and_live_bytes_must_match(self):
        name = sorted(collector.SOURCE_PATHS)[0]
        snapshot = self.fixture.summaries[0].parent / "source-snapshot" / name
        snapshot.write_bytes(b"# changed snapshot\n")
        with self.assertRaisesRegex(ValueError, "snapshot"):
            self.fixture.collect()
        snapshot.write_bytes((self.fixture.source / name).read_bytes())
        (self.fixture.source / name).write_bytes(b"# changed current source\n")
        with self.assertRaisesRegex(ValueError, "live-byte"):
            self.fixture.collect()

    def test_verdict_hash_scope_and_exit_code_are_required(self):
        verdict_path = self.fixture.verdicts[0]
        original = verdict_path.read_bytes()
        verdict = collector.load(original)
        verdict["scope"] = "unrelated PASS"
        save(verdict_path, verdict)
        self.fixture.reseal(0)
        with self.assertRaisesRegex(ValueError, "verdict-identity"):
            self.fixture.collect()
        verdict_path.write_bytes(original)
        self.fixture.reseal(0)
        invocation = collector.load(self.fixture.invocations[0].read_bytes())
        invocation["returncode"] = False
        save(self.fixture.invocations[0], invocation)
        with self.assertRaisesRegex(ValueError, "exit-code"):
            self.fixture.collect()

    def test_stderr_nonempty_and_main_only_reader_identity_rejected(self):
        self.fixture.stderrs[0].write_bytes(b"diagnostic\n")
        self.fixture.reseal(0)
        with self.assertRaisesRegex(ValueError, "output-join"):
            self.fixture.collect()
        self.fixture.stderrs[0].write_bytes(b"")
        self.fixture.reseal(0)
        invocation = collector.load(self.fixture.invocations[0].read_bytes())
        invocation["verification_source_sha256"] = {collector.MAIN_READER: self.fixture.readers[collector.MAIN_READER]}
        save(self.fixture.invocations[0], invocation)
        with self.assertRaisesRegex(ValueError, "closure-fields"):
            self.fixture.collect()

    def test_reader_command_rebinding_rejected(self):
        invocation = collector.load(self.fixture.invocations[0].read_bytes())
        invocation["argv"][3] = str(self.fixture.summaries[1])
        save(self.fixture.invocations[0], invocation)
        with self.assertRaisesRegex(ValueError, "argv-binding"):
            self.fixture.collect()

    def test_duplicate_json_and_bool_count_rejected(self):
        original = self.fixture.summaries[0].read_bytes()
        self.fixture.summaries[0].write_bytes(b'{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(ValueError, "duplicate-json-key"):
            self.fixture.collect()
        self.fixture.summaries[0].write_bytes(original)
        verdict = collector.load(self.fixture.verdicts[0].read_bytes())
        verdict["source_files_checked"] = True
        save(self.fixture.verdicts[0], verdict)
        self.fixture.reseal(0)
        with self.assertRaisesRegex(ValueError, "verdict-counts"):
            self.fixture.collect()

    def test_quality_mismatch_selects_reference_instead_of_best_synthetic_speed(self):
        for index in (1, 2):
            def mismatch(summary):
                row = summary["rows"][0]
                row["response"]["body"]["choices"][0]["message"]["content"] = "different answer"
                row["backend_receipt"]["text"] = "different answer"
                row["exact"] = False
            self.fixture.change_summary(index, mismatch)
            verdict = collector.load(self.fixture.verdicts[index].read_bytes())
            verdict["exact"] = 55
            save(self.fixture.verdicts[index], verdict)
            self.fixture.reseal(index)
        _selection, receipt = self.fixture.collect()
        self.assertEqual(receipt["decision"]["selected_profile"]["name"], "reference")
        self.assertTrue(all("output-mismatch" in row["reasons"] for row in receipt["decision"]["comparisons"]))

    def test_cli_exclusive_outputs_and_receipt_failure_never_publishes_selection(self):
        args = self.fixture.argv()
        original_write = collector.write_exclusive
        def reject_receipt(path, value, maximum):
            if Path(path).name == "matrix.json":
                raise OSError("synthetic receipt failure")
            return original_write(path, value, maximum)
        with patch.object(collector, "write_exclusive", side_effect=reject_receipt), patch("builtins.print"):
            self.assertEqual(collector.main(args), 1)
        self.assertFalse((self.fixture.root / "selection.json").exists())
        with patch("builtins.print"):
            self.assertEqual(collector.main(args), 0)
        output = self.fixture.root / "selection.json"
        saved = output.read_bytes()
        receipt = collector.load((self.fixture.root / "matrix.json").read_bytes())
        self.assertEqual(receipt["selection_file"]["sha256"], sha256(saved).hexdigest())
        with patch("builtins.print"):
            self.assertEqual(collector.main(args), 1)
        self.assertEqual(output.read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()
