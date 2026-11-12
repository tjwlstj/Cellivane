"""Physical synthetic efficiency evidence; no producer/model/engine imports."""
import copy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).parent))
import test_cellivane_soak_verifier as fixtures

SPEC = importlib.util.spec_from_file_location("independent_efficiency", TOOLS / "verify_cellivane_efficiency.py")
v = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)
encode, record, reply = fixtures.encode, fixtures.record, fixtures.reply


class Fixture(fixtures.Fixture):
    """Reuse only the independent physical asset/audit/bridge fixture builder."""
    def call(self, *args, **kwargs):
        row = super().call(*args, **kwargs)
        row.update(receipt_started_s=row["completed_s"], receipt_completed_s=row["completed_s"] + .001, receipt_read_s=.001)
        for receipt in (row["backend_receipt"], self.records[-2][1]):
            receipt["raw_response"].update(total_duration=100000000, prompt_eval_duration=10000000, eval_duration=80000000)
            receipt["response_body"] = encode(receipt["raw_response"]).decode()
            receipt["response_sha256"] = sha256(receipt["response_body"].encode()).hexdigest()
        return row

    def __init__(self, root, profile_name="reference", mode="calibrate"):
        super().__init__(root, mode="smoke" if mode == "calibrate" else "soak")
        with patch.object(v, "MODEL", self.model):
            profile = v.profile_record(profile_name)
        s = self.s
        for name in v.SOURCE_PATHS - set(s["source"]["sha256"]):
            raw = b"# SYNTHETIC NOT EXECUTED " + name.encode()
            for base in (Path(s["source"]["root"]), self.root / "source-snapshot"):
                path = base / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
            s["source"]["sha256"][name] = sha256(raw).hexdigest()
        s["source"]["scope"] = "declared-21-file-efficiency-family-not-loader-attestation"
        s.update(family="cellivane-efficiency-run-v1", mode=mode, duration_s=0 if mode == "calibrate" else 900,
            minimum_responses=56 if mode == "calibrate" else 24, repeat=4, profile=profile, plan=copy.deepcopy(profile),
            requested_profile=profile_name, selection={"mode": "explicit", "artifact": None})
        s["guards"]["minimum_start_interval_s"] = 0 if mode == "calibrate" else .5
        for evidence in [s["launch_probe"], *self.samples]:
            evidence["observation"]["gpu"].update(free_bytes=6 * 1024**3, used_bytes=2 * 1024**3)
            evidence["gpu_raw"]["stdout"] = evidence["gpu_raw"]["stdout"].replace("8192, 4096, 4096", "8192, 2048, 6144")
        s["preflight"] = copy.deepcopy(self.samples[0]["observation"])
        with patch.object(v, "MODEL", self.model):
            s["budget"] = v.forecast(profile, s["launch_probe"]["observation"])
        observed = s["launch_probe"]["observation"]
        s["host_profile"] = {"logical_processors": 16, "ram_total_bytes": observed["memory"]["total_bytes"],
            "gpu": {key: observed["gpu"][key] for key in ("index", "name", "driver_version", "total_bytes")}}
        alias = "cellivane-efficiency-" + profile_name + ":latest"
        s["alias"] = alias
        s["configuration"].update(alias=alias, options=copy.deepcopy(profile["ollama_options"]),
            unset_environment=["OLLAMA_FLASH_ATTENTION"], device_scope="one visible NVIDIA CUDA GPU; one slot")
        s["configuration"]["environment"]["OLLAMA_KV_CACHE_TYPE"] = "f16"
        s["identity"] = v.digest({"model_sha256": self.model["sha256"], "backend_tree_sha256": s["backend"]["tree_sha256"],
            "configuration": s["configuration"]})
        modelfile = Path(s["modelfile"]["path"])
        modelfile.write_text('FROM "' + str(Path(s["model_file"]["path"])).replace("\\", "/") + '"\n' +
            "".join(f"PARAMETER {key} {value}\n" for key, value in profile["ollama_options"].items()), encoding="utf-8")
        s["modelfile"] = record(modelfile)
        for key in ("loaded_models_ready", "loaded_models_end"):
            body = copy.deepcopy(s[key]["body"])
            body["models"][0].update(name=alias, model=alias)
            s[key] = reply(None, body)
        startup = Path(s["startup_log"]["path"]).read_bytes().replace(b"36/37", f'{profile["num_gpu"]}/37'.encode())
        startup += f'llama_context: n_threads = {profile["num_thread"]} (n_threads_batch = {profile["num_thread"]})\n'.encode()
        self.replace_logs(startup)
        self.records = [("soak_configuration", {"identity": s["identity"], "plan": profile, "model_sha256": self.model["sha256"]})]
        self.counts, self.seq = dict.fromkeys(v.soak.COUNTERS, 0), 0
        s["warmup"] = self.call(v.soak.payload(alias, "Reply with only OK."), "OK", -1, "warmup", 1., .2)
        oversized = v.soak.payload(alias, "must not dispatch"); oversized["max_tokens"] = 129
        s["oversize"] = reply(oversized, {"error": {"message": "invalid-request"}}, 400)
        self.counts["rejected"] += 1; self.emit("reject", reason="invalid-request")
        s["rows"] = []
        n = s["minimum_responses"]
        for index in range(n):
            case = v.soak.CASES[index % 14]
            started = 4.01 + index * (.3 if mode == "calibrate" else 900 / n)
            row = self.call(v.soak.payload(alias, case["prompt"]), case["expected"], index, case["id"], started,
                .2 if mode == "calibrate" else 900 / n - .2)
            row["phases"] = {"pacing_started_s": started - .001, "pacing_completed_s": started - .0005, "pacing_wait_s": .0005,
                "log_started_s": row["receipt_completed_s"] + .0001, "log_completed_s": row["receipt_completed_s"] + .0011,
                "log_wall_s": .001, "log_poll_sequence": index + 2, "progress_write_s": 0}
            row["post_complete_s"] = row["phases"]["log_completed_s"] + .0002
            s["rows"].append(row)
        s["service_start_s"] = 4.
        s["service_end_s"] = s["rows"][-1]["post_complete_s"] + (.01 if mode == "calibrate" else .2)
        self.make_bridge()
        self.emit("close", reason="engine-closed")
        s["state"].update(model=alias, identity=s["identity"], **self.counts, event_seq=self.seq)
        self.records.append(("shutdown", copy.deepcopy(s["state"])))
        s["audit_timings"] = []
        for index, (kind, _value) in enumerate(self.records):
            if index == 0:
                began = .5
            elif 1 <= index <= 3:
                began = 1 + (.01, .11, .12)[index - 1]
            elif index == 4:
                began = 3.
            elif 5 <= index < 5 + n * 3:
                case_index, slot = divmod(index - 5, 3)
                began = s["rows"][case_index]["started_s"] + (.01, .11, .12)[slot]
            else:
                began = s["service_end_s"] + (.1, .21, .22, .4, .5)[index - 5 - n * 3]
            s["audit_timings"].append({"sequence": index + 1, "kind": kind, "started_s": began,
                "completed_s": began + .001, "wall_s": .001})
        self.make_polls()
        self.reseal()

    def replace_logs(self, startup, suffix=b"normal shutdown\n"):
        s = self.s
        Path(s["startup_log"]["path"]).write_bytes(startup)
        Path(s["log"]["path"]).write_bytes(startup + suffix)
        s["startup_log"] = record(s["startup_log"]["path"])
        s["log"] = record(s["log"]["path"])
        s["placement"].update(offloaded_layers=s["profile"]["num_gpu"], log_sha256=sha256(startup).hexdigest())

    def make_polls(self):
        # ASCII fixture chunks are shorter than the cursor's 64KiB chunk. No
        # implementation import is used to create these independent receipts.
        s, offset, reads, scanned, tail = self.s, 0, 0, 0, b""
        raw = Path(s["log"]["path"]).read_bytes()
        ends = [s["startup_log"]["bytes"]] * (len(s["rows"]) + 1) + [len(raw), len(raw)]
        polls = []
        for seq, end in enumerate(ends, 1):
            segment = raw[offset:end]
            reads += len(segment) + min(offset, 256) + min(end, 256)
            if segment:
                scanned += len(segment) + len(tail)
                tail = (tail + segment)[-64:]
            if seq == len(ends):
                scanned += len(tail)
            polls.append({"seq": seq, "start": offset, "end": end, "new_bytes": len(segment),
                "chunk_sha256": sha256(segment).hexdigest(), "prefix_sha256": sha256(raw[:end]).hexdigest(),
                "bytes_read_total": reads, "bytes_scanned_total": scanned, "carry_bytes": len(tail), "poll_wall_s": .0001, "fatal": False})
            offset = end
        s["log_polls"] = polls


class EfficiencyReplayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.f = Fixture(self.temporary.name)
        self.pin()

    def pin(self):
        for module, name, value in ((v, "MODEL", self.f.model), (v.soak, "OLLAMA_ARCHIVE_BYTES", self.f.archive["bytes"]),
                (v.soak, "OLLAMA_ARCHIVE_SHA", self.f.archive["sha256"])):
            context = patch.object(module, name, value); context.start(); self.addCleanup(context.stop)

    def replay(self, current=False):
        self.f.reseal()
        return v.replay(self.f.path, self.f.s["source"]["root"] if current else None)

    def test_complete_physical_56_case_calibration_gold_path(self):
        result = self.replay(True)
        self.assertEqual((result["verdict"], result["computed_responses"], result["audit_records"], result["source_files_checked"]), ("PASS", 56, 178, 21))
        self.assertEqual(result["log_work"]["polls"], 59)
        self.assertTrue(all(item is False for item in result["claims"].values()))

    def test_gpu29_eight_threads_profile_gold_path(self):
        self.f = Fixture(self.temporary.name, "gpu29-threads8"); self.pin()
        result = self.replay()
        self.assertEqual((result["observed_gpu_layers"], result["observed_native_threads"]), (29, 8))

    def test_complete_synthetic_900_second_soak_gold_path(self):
        self.f = Fixture(self.temporary.name, mode="soak"); self.pin()
        self.assertEqual((self.replay()["computed_responses"], self.replay()["drained_requests"]), (24, 0))

    def test_auto_without_calibration_is_reference_default(self):
        self.f.s.update(requested_profile="auto", selection={"mode": "reference-default", "artifact": None})
        self.assertEqual(self.replay()["profile"], "reference")

    def test_calibrated_selection_missing_metadata_fails_closed(self):
        self.f.s.update(requested_profile="auto", selection={"mode": "calibrated", "artifact": None})
        with self.assertRaisesRegex(ValueError, "calibrated-selection"):
            self.replay()

    def test_explicit_request_cannot_silently_select_different_profile(self):
        self.f.s["requested_profile"] = "gpu29"
        with self.assertRaisesRegex(ValueError, "explicit-selection"):
            self.replay()

    def test_profile_exact_types_reject_temperature_boolean(self):
        self.f.s["profile"]["temperature"] = False
        with self.assertRaisesRegex(ValueError, "profile-contract"):
            self.replay()

    def test_host_hardware_identity_must_join_launch_evidence(self):
        self.f.s["host_profile"]["gpu"]["name"] = "OTHER GPU"
        with self.assertRaisesRegex(ValueError, "host-profile"):
            self.replay()

    def test_thread_budget_rejects_boolean_logical_processors(self):
        self.f.s["host_profile"]["logical_processors"] = True
        with self.assertRaisesRegex(ValueError, "host-profile"):
            self.replay()

    def test_advisory_budget_is_independently_recomputed(self):
        self.f.s["budget"]["incremental_layer_estimate_bytes"] += 1
        with self.assertRaisesRegex(ValueError, "budget-recompute"):
            self.replay()

    def test_flash_attention_override_and_kv_change_rejected(self):
        self.f.s["configuration"]["environment"]["OLLAMA_FLASH_ATTENTION"] = "0"
        with self.assertRaisesRegex(ValueError, "execution-configuration"):
            self.replay()

    def test_source21_registry_omission_rejected(self):
        del self.f.s["source"]["sha256"]["hosted/experimental/cellivane_seed/efficiency.py"]
        with self.assertRaisesRegex(ValueError, "source-family"):
            self.replay()

    def test_current_source_and_snapshot_are_both_compared(self):
        name = "tools/hosted/cellivane_log_cursor.py"
        path = Path(self.f.s["source"]["root"]) / name
        path.write_bytes(b"# altered current file")
        with self.assertRaisesRegex(ValueError, "current-source-changed"):
            self.replay(True)

    def test_asset_dll_modification_rejected(self):
        exe = Path(self.f.s["backend"]["executable"]["path"])
        (exe.parent / "lib/cuda/ggml-cuda.dll").write_bytes(b"X")
        with self.assertRaises(ValueError):
            self.replay()

    def test_native_thread_count_must_be_observed(self):
        startup = Path(self.f.s["startup_log"]["path"]).read_bytes().replace(b"n_threads = 4", b"n_threads = 8")
        self.f.replace_logs(startup); self.f.make_polls()
        with self.assertRaisesRegex(ValueError, "native-thread"):
            self.replay()

    def test_conflicting_native_thread_count_rejected(self):
        startup = Path(self.f.s["startup_log"]["path"]).read_bytes() + b"n_threads = 8\n"
        self.f.replace_logs(startup); self.f.make_polls()
        with self.assertRaisesRegex(ValueError, "native-thread"):
            self.replay()

    def test_chunk_hash_tampering_rejected(self):
        self.f.s["log_polls"][0]["chunk_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "raw-hash"):
            self.replay()

    def test_prefix_hash_tampering_rejected(self):
        self.f.s["log_polls"][2]["prefix_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "raw-hash"):
            self.replay()

    def test_read_counter_underreport_rejected(self):
        self.f.s["log_polls"][3]["bytes_read_total"] -= 1
        with self.assertRaisesRegex(ValueError, "work-or-carry"):
            self.replay()

    def test_scan_counter_full_rescan_cannot_be_claimed_incremental(self):
        self.f.s["log_polls"][-1]["bytes_scanned_total"] += 100000
        with self.assertRaisesRegex(ValueError, "work-or-carry"):
            self.replay()

    def test_forged_carry_rejected(self):
        self.f.s["log_polls"][0]["carry_bytes"] = 0
        with self.assertRaisesRegex(ValueError, "work-or-carry"):
            self.replay()

    def test_log_gap_and_missing_poll_rejected(self):
        self.f.s["log_polls"].pop()
        with self.assertRaisesRegex(ValueError, "poll-count"):
            self.replay()

    def test_full_raw_scan_detects_resealed_late_fatal(self):
        startup = Path(self.f.s["startup_log"]["path"]).read_bytes()
        self.f.replace_logs(startup, b"normal shutdown\nlevel=ERROR bad\n"); self.f.make_polls()
        with self.assertRaisesRegex(ValueError, "fatal-backend-log"):
            self.replay()

    def test_row_log_poll_sequence_cannot_be_rebound(self):
        self.f.s["rows"][0]["phases"]["log_poll_sequence"] = 3
        with self.assertRaisesRegex(ValueError, "phase-order"):
            self.replay()

    def test_log_poll_wall_cannot_exceed_measured_outer_interval(self):
        self.f.s["log_polls"][1]["poll_wall_s"] = 1.
        with self.assertRaisesRegex(ValueError, "outer-timing"):
            self.replay()

    def test_receipt_read_time_is_separate_from_http(self):
        self.f.s["rows"][0]["receipt_started_s"] -= .1
        with self.assertRaisesRegex(ValueError, "request-timing"):
            self.replay()

    def test_post_complete_cannot_precede_log_completion(self):
        self.f.s["rows"][0]["post_complete_s"] = self.f.s["rows"][0]["completed_s"]
        with self.assertRaisesRegex(ValueError, "phase-order"):
            self.replay()

    def test_audit_duration_recomputed(self):
        self.f.s["audit_timings"][1]["wall_s"] = .1
        with self.assertRaisesRegex(ValueError, "audit-timing"):
            self.replay()

    def test_audit_kind_must_match_raw_record(self):
        self.f.s["audit_timings"][2]["kind"] = "scheduler"
        with self.assertRaisesRegex(ValueError, "audit-timing"):
            self.replay()

    def test_audit_inside_http_cannot_be_moved_before_http(self):
        self.f.s["audit_timings"][1].update(started_s=.9, completed_s=.901)
        with self.assertRaisesRegex(ValueError, "outside-http"):
            self.replay()

    def test_calibration_cannot_discard_a_corpus_row(self):
        self.f.s["rows"].pop()
        with self.assertRaisesRegex(ValueError, "corpus-count"):
            self.replay()

    def test_calibration_duration_and_pacing_profile_cannot_drift(self):
        self.f.s["duration_s"] = 900
        with self.assertRaisesRegex(ValueError, "run-profile"):
            self.replay()

    def test_failed_cleanup_rejects_success_summary(self):
        self.f.s["cleanup"][0]["job_cleanup_confirmed"] = False
        with self.assertRaisesRegex(ValueError, "cleanup-unconfirmed"):
            self.replay()

    def test_forged_metrics_rejected(self):
        self.f.s["metrics"]["exact"] += 1
        # Avoid the builder's ordinary metrics reseal for this metadata tamper.
        self.f.path.write_bytes(encode(self.f.s))
        with self.assertRaisesRegex(ValueError, "metric-recompute"):
            v.replay(self.f.path)

    def test_json_duplicate_and_nonfinite_rejected(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                v.load(raw)


def policy_reports(gpu29=.9, threads8=.85):
    identity = {"model_sha256": v.MODEL["sha256"], "backend_tree_sha256": "b" * 64,
        "corpus_sha256": v.digest(v.soak.CASES), "source_sha256": "c" * 64}
    return [{"profile": v.profile_record(name), "identity": dict(identity), "outcome": "PASS", "resource_guard_passed": True,
        "rounds": [{"index": round_index, "samples": [{"case_id": case["id"], "repeat": repeat, "wall_s": wall,
            "text_sha256": sha256((case["id"] + str(repeat)).encode()).hexdigest()}
            for repeat in range(4) for case in v.soak.CASES]} for round_index in range(2)]}
        for name, wall in zip(v.PROFILE_SETTINGS, (1., gpu29, threads8))]


class IndependentPolicyTests(unittest.TestCase):
    def disabled_third(self, values):
        values[2].update(outcome="FAIL", resource_guard_passed=False, rounds=[])

    def test_fastest_eligible_and_declared_tie_order(self):
        self.assertEqual(v.independent_choice(policy_reports())["selected_profile"]["name"], "gpu29-threads8")
        self.assertEqual(v.independent_choice(policy_reports(.9, .9)[::-1])["selected_profile"]["name"], "gpu29")

    def test_exact_five_percent_boundary_and_both_round_gate(self):
        for wall, name in ((.95, "gpu29"), (.9500001, "reference")):
            values = policy_reports(wall); self.disabled_third(values)
            self.assertEqual(v.independent_choice(values)["selected_profile"]["name"], name)
        values = policy_reports(.7); self.disabled_third(values)
        for sample in values[1]["rounds"][1]["samples"]: sample["wall_s"] = 1.01
        result = v.independent_choice(values)
        self.assertEqual(result["selected_profile"]["name"], "reference")
        self.assertTrue(result["comparisons"][0]["overall"]["p50_gain_passed"])
        self.assertFalse(result["comparisons"][0]["rounds"][1]["qualifies"])

    def test_p95_guard_cannot_hide_behind_fast_median(self):
        values = policy_reports(.8); self.disabled_third(values)
        for round_ in values[1]["rounds"]:
            for sample in round_["samples"][:4]: sample["wall_s"] = 1.050001
        result = v.independent_choice(values)
        self.assertEqual(result["selected_profile"]["name"], "reference")
        self.assertIn("p95-regression", result["comparisons"][0]["reasons"])

    def test_case_regression_and_balanced_gain_guards(self):
        values = policy_reports(.8); self.disabled_third(values)
        case_id = v.soak.CASES[0]["id"]
        for round_ in values[1]["rounds"]:
            for sample in round_["samples"]:
                if sample["case_id"] == case_id and sample["repeat"] < 2: sample["wall_s"] = 1.42
        result = v.independent_choice(values)
        self.assertEqual(result["selected_profile"]["name"], "reference")
        self.assertFalse(result["comparisons"][0]["overall"]["case_regression_guard_passed"])
        values = policy_reports(); self.disabled_third(values)
        high = {case["id"] for case in v.soak.CASES[7:]}
        for report, low, high_wall in ((values[0], 1., 10.), (values[1], 1., 9.2)):
            for round_ in report["rounds"]:
                for sample in round_["samples"]: sample["wall_s"] = high_wall if sample["case_id"] in high else low
        result = v.independent_choice(values)
        self.assertTrue(result["comparisons"][0]["overall"]["p50_gain_passed"])
        self.assertFalse(result["comparisons"][0]["overall"]["balanced_case_gain_passed"])

    def test_exact_raw_output_hash_parity_required(self):
        values = policy_reports(.8); self.disabled_third(values)
        values[1]["rounds"][1]["samples"][0]["text_sha256"] = "0" * 64
        result = v.independent_choice(values)
        self.assertEqual(result["selected_profile"]["name"], "reference")
        self.assertIn("output-mismatch", result["comparisons"][0]["reasons"])

    def test_failures_and_resource_guards_never_qualify(self):
        values = policy_reports(); values[0].update(outcome="FAIL", resource_guard_passed=False, rounds=[])
        result = v.independent_choice(values)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason"], "reference-not-qualified")
        self.assertFalse(any(item["qualifies"] for item in result["comparisons"]))

    def test_resealed_identity_and_duplicate_grid_rejected(self):
        values = policy_reports(); values[1]["identity"]["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "identity-mismatch"): v.independent_choice(values)
        values = policy_reports(); values[1]["rounds"][0]["samples"][1] = copy.deepcopy(values[1]["rounds"][0]["samples"][0])
        with self.assertRaisesRegex(ValueError, "duplicate-sample"): v.independent_choice(values)

    def test_bool_wall_and_nonfinite_ratios_fail_closed(self):
        values = policy_reports(); values[1]["rounds"][0]["samples"][0]["wall_s"] = True
        with self.assertRaisesRegex(ValueError, "sample-value"): v.independent_choice(values)
        values = policy_reports(1e-320); self.disabled_third(values)
        with self.assertRaisesRegex(ValueError, "nonfinite-ratio"): v.independent_choice(values)


class MatrixFixture:
    def __init__(self, root):
        self.root = Path(root)
        self.runs = [Fixture(root, name) for name in v.MATRIX_ORDER]
        self.source_root = Path(self.runs[0].s["source"]["root"])
        self.verification = {name: sha256((TOOLS.parents[1] / name).read_bytes()).hexdigest() for name in v.VERIFICATION_PATHS}
        for name in v.VERIFICATION_PATHS:
            path = self.source_root / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((TOOLS.parents[1] / name).read_bytes())
        self.selection_path, self.receipt_path = self.root / "selected-profile.json", self.root / "matrix-receipt.json"
        self.selection = {"schema_version": 1, "family": "cellivane-efficiency-selection-v1", "host_profile": copy.deepcopy(self.runs[0].s["host_profile"]), "candidate_reports": []}
        self.receipt = {"schema_version": 1, "family": "cellivane-efficiency-matrix-v1", "collected_at_utc": "2026-10-16T00:00:00+00:00",
            "host_profile": copy.deepcopy(self.selection["host_profile"]), "identity": None, "ordered_runs": [],
            "source_sha256": self.runs[0].s["source"]["sha256"], "verification_source_sha256": self.verification,
            "selection_canonical_sha256": None, "decision": None, "scope": copy.deepcopy(v.MATRIX_SCOPE), "selection_file": None}
        self.patches = [patch.object(v, "MODEL", self.runs[0].model),
            patch.object(v.soak, "OLLAMA_ARCHIVE_BYTES", self.runs[0].archive["bytes"]), patch.object(v.soak, "OLLAMA_ARCHIVE_SHA", self.runs[0].archive["sha256"])]
        for item in self.patches: item.start()
        try:
            reports = {name: {"profile": v.profile_record(name), "identity": None, "outcome": "PASS", "resource_guard_passed": True, "rounds": []} for name in v.PROFILE_SETTINGS}
            for position, run in enumerate(self.runs):
                run.s["source"]["root"] = str(self.source_root)
                run.s["backend"] = copy.deepcopy(self.runs[0].s["backend"])
                run.reseal()
                verdict = v.replay(run.path, self.source_root)
                stdout, stderr, invocation = run.root / "reader.stdout.json", run.root / "reader.stderr.txt", run.root / "reader.invocation.json"
                stdout.write_bytes(encode(verdict) + b"\n"); stderr.write_bytes(b"")
                summary_sha = record(run.path)["sha256"]
                argv = [sys.executable, "-B", str(self.source_root / "tools/hosted/verify_cellivane_efficiency.py"), str(run.path), "--source-root", str(self.source_root)]
                invocation.write_bytes(encode({"argv": argv, "returncode": 0, "stdout_sha256": record(stdout)["sha256"],
                    "stderr_sha256": record(stderr)["sha256"], "verifier_sha256": self.verification["tools/hosted/verify_cellivane_efficiency.py"],
                    "summary_sha256_before": summary_sha, "summary_sha256_after": summary_sha, "verification_source_sha256": self.verification}))
                records = {key: record(path) for key, path in (("summary", run.path), ("reader_stdout", stdout), ("reader_invocation", invocation), ("reader_stderr", stderr))}
                self.receipt["ordered_runs"].append({"position": position, "round": position // 3, "profile": v.MATRIX_ORDER[position],
                    "run_id": run.root.name, "records": records, "reader_verdict": verdict})
                identity = {"model_sha256": run.model["sha256"], "backend_tree_sha256": run.s["backend"]["tree_sha256"],
                    "corpus_sha256": run.s["corpus_sha256"], "source_sha256": v.digest(run.s["source"]["sha256"])}
                report = reports[v.MATRIX_ORDER[position]]; report["identity"] = identity
                report["rounds"].append({"index": position // 3, "samples": [{"case_id": row["case"], "repeat": index // 14,
                    "wall_s": row["wall_s"], "text_sha256": sha256(row["response"]["body"]["choices"][0]["message"]["content"].encode()).hexdigest()}
                    for index, row in enumerate(run.s["rows"])]})
            self.selection["candidate_reports"] = [reports[name] for name in v.PROFILE_SETTINGS]
            self.receipt["identity"] = self.selection["candidate_reports"][0]["identity"]
            self.reseal()
        except Exception:
            self.close(); raise

    def close(self):
        for item in reversed(self.patches): item.stop()

    def reseal(self):
        self.selection_path.write_bytes(encode(self.selection) + b"\n")
        self.receipt["selection_file"] = record(self.selection_path)
        self.receipt["selection_canonical_sha256"] = v.digest(self.selection)
        self.receipt["decision"] = v.independent_choice(self.selection["candidate_reports"])
        self.receipt_path.write_bytes(encode(self.receipt) + b"\n")


class IndependentMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        try: cls.f = MatrixFixture(cls.temporary.name)
        except Exception: cls.temporary.cleanup(); raise
        cls.initial_selection, cls.initial_receipt = copy.deepcopy(cls.f.selection), copy.deepcopy(cls.f.receipt)

    @classmethod
    def tearDownClass(cls):
        cls.f.close(); cls.temporary.cleanup()

    def setUp(self):
        self.f.selection, self.f.receipt = copy.deepcopy(self.initial_selection), copy.deepcopy(self.initial_receipt)
        self.f.reseal()
        self.restore_files = {}

    def tearDown(self):
        for path, raw in self.restore_files.items(): path.write_bytes(raw)

    def rewrite(self, item, key, value):
        path = Path(item["records"][key]["path"])
        self.restore_files.setdefault(path, path.read_bytes())
        path.write_bytes(encode(value))
        item["records"][key] = record(path)

    def replay(self):
        self.f.reseal()
        return v.verify_matrix(self.f.selection_path, self.f.receipt_path, self.f.source_root)

    def test_full_six_physical_synthetic_runs_and_captures_gold_path(self):
        result = self.replay()
        self.assertEqual((result["verdict"], result["runs"], result["decision"]["selected_profile"]["name"]), ("PASS", 6, "reference"))
        self.assertEqual(result["selection_file_sha256"], record(self.f.selection_path)["sha256"])
        self.assertFalse(result["large_assets_rehashed"])
        self.assertTrue(all(item is False for item in result["claims"].values()))

    def test_matrix_order_cannot_be_relabelled(self):
        self.f.receipt["ordered_runs"][1]["profile"] = "reference"
        with self.assertRaisesRegex(ValueError, "ABC-CBA"): self.replay()

    def test_duplicate_run_id_rejected(self):
        self.f.receipt["ordered_runs"][1]["run_id"] = self.f.receipt["ordered_runs"][0]["run_id"]
        with self.assertRaisesRegex(ValueError, "duplicate-or"): self.replay()

    def test_reader_capture_before_after_hash_cannot_be_resealed_to_different_summary(self):
        item = self.f.receipt["ordered_runs"][0]
        capture = v.load(Path(item["records"]["reader_invocation"]["path"]).read_bytes())
        capture["summary_sha256_after"] = "0" * 64
        self.rewrite(item, "reader_invocation", capture)
        with self.assertRaisesRegex(ValueError, "summary-before-after"): self.replay()

    def test_reader_command_must_join_exact_summary_and_source_root(self):
        item = self.f.receipt["ordered_runs"][0]
        capture = v.load(Path(item["records"]["reader_invocation"]["path"]).read_bytes())
        capture["argv"][3] = self.f.receipt["ordered_runs"][1]["records"]["summary"]["path"]
        self.rewrite(item, "reader_invocation", capture)
        with self.assertRaisesRegex(ValueError, "command-binding"): self.replay()

    def test_verification_closure4_tampering_rejected(self):
        self.f.receipt["verification_source_sha256"]["tools/hosted/verify_cellivane_bridge.py"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "verification-source4"): self.replay()

    def test_resealed_fake_pass_stdout_cannot_replace_semantic_replay(self):
        item = self.f.receipt["ordered_runs"][0]
        verdict = copy.deepcopy(item["reader_verdict"]); verdict["exact"] += 1
        self.rewrite(item, "reader_stdout", verdict)
        item["reader_verdict"] = verdict
        capture = v.load(Path(item["records"]["reader_invocation"]["path"]).read_bytes())
        capture["stdout_sha256"] = item["records"]["reader_stdout"]["sha256"]
        self.rewrite(item, "reader_invocation", capture)
        with self.assertRaisesRegex(ValueError, "verdict-replay"): self.replay()

    def test_resealed_unknown_backend_response_still_rejects(self):
        item = self.f.receipt["ordered_runs"][0]
        summary = v.load(Path(item["records"]["summary"]["path"]).read_bytes())
        summary["rows"][0]["backend_receipt"]["outcome"] = "UNKNOWN"
        self.rewrite(item, "summary", summary)
        capture = v.load(Path(item["records"]["reader_invocation"]["path"]).read_bytes())
        capture["summary_sha256_before"] = capture["summary_sha256_after"] = item["records"]["summary"]["sha256"]
        self.rewrite(item, "reader_invocation", capture)
        with self.assertRaises(ValueError): self.replay()

    def test_resealed_fast_reports_must_join_actual_matrix_rows(self):
        for round_ in self.f.selection["candidate_reports"][1]["rounds"]:
            for sample in round_["samples"]: sample["wall_s"] = .01
        with self.assertRaisesRegex(ValueError, "reports-raw-matrix-join"): self.replay()

    def test_host_and_source_identity_not_just_valid_digest(self):
        self.f.selection["host_profile"]["logical_processors"] = 32
        self.f.receipt["host_profile"]["logical_processors"] = 32
        with self.assertRaisesRegex(ValueError, "decision-host-identity"): self.replay()

    def test_caller_order_never_becomes_clock_attestation(self):
        self.f.receipt["scope"]["input_order"] = "trusted-wall-clock-order"
        with self.assertRaisesRegex(ValueError, "version-or-scope"): self.replay()

    def test_calibrated_auto_full_single_run_requires_and_replays_matrix(self):
        run = Fixture(self.temporary.name)
        run.s["source"]["root"] = str(self.f.source_root)
        run.s["backend"] = copy.deepcopy(self.f.runs[0].s["backend"])
        run.s.update(requested_profile="auto", selection={"mode": "calibrated", "artifact": record(self.f.selection_path),
            "decision": copy.deepcopy(self.f.receipt["decision"]), "host_profile": copy.deepcopy(self.f.selection["host_profile"]),
            "identity": copy.deepcopy(self.f.receipt["identity"])})
        run.reseal()
        with self.assertRaisesRegex(ValueError, "requires-matrix-receipt"): v.replay(run.path, self.f.source_root)
        result = v.replay(run.path, self.f.source_root, self.f.receipt_path)
        self.assertEqual((result["verdict"], result["profile"]), ("PASS", "reference"))


if __name__ == "__main__":
    unittest.main()
