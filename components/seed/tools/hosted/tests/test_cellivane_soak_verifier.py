"""Model-free independent soak replay fixtures and tampering tests.

The complete schema fixture will join raw telemetry, bounded request records,
audit, placement, assets, source, bridge and shutdown without producer imports.
"""
from hashlib import sha256
import copy
import importlib.util
from pathlib import Path
import json
import statistics
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
import zipfile

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("independent_soak", TOOLS / "verify_cellivane_soak.py")
v = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)


def resource(root):
    return {"observation": {"schema_version": 1,
        "memory": {"source": "GlobalMemoryStatusEx", "available_bytes": 8 * 1024**3, "total_bytes": 32 * 1024**3},
        "gpu": {"source": "nvidia-smi", "index": 0, "name": "SYNTHETIC GPU", "driver_version": "580.1",
            "total_bytes": 8192 * 1024**2, "used_bytes": 4096 * 1024**2, "free_bytes": 4096 * 1024**2,
            "utilization_percent": 40., "temperature_c": 65., "power_w": 55.5}},
        "gpu_raw": {"argv": [str(Path(root) / "nvidia-smi.exe"), "--id=0", "--query-gpu=" + v.GPU_QUERY,
            "--format=csv,noheader,nounits"], "returncode": 0,
            "stdout": "0, SYNTHETIC GPU, 580.1, 8192, 4096, 4096, 40, 65, 55.5\n", "stderr": ""}}


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def record(path):
    raw = Path(path).read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": sha256(raw).hexdigest()}


def reply(request, body, status=200):
    return {"status": status, "body": copy.deepcopy(body), "raw_response": encode(body).decode(), "request": copy.deepcopy(request)}


def receipt(request, text, name="ollama-tensor"):
    body = {"model": request["model"], "message": {"role": "assistant", "content": text}, "done": True,
        "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 2, "eval_duration": 100000000}
    wanted = {"model": request["model"], "messages": request["messages"], "stream": False, "think": False, "options": {"num_predict": 128}}
    return {"name": name, "kind": "ollama", "model": request["model"], "outcome": "ANSWERED", "text": text, "elapsed_s": .1,
        "request_sha256": v.digest(wanted), "response_sha256": v.digest(body), "raw_response": body, "error": None,
        "usage": {"prompt_eval_count": 10, "eval_count": 2}, "request_body": encode(wanted).decode(), "response_body": encode(body).decode(), "http_status": 200}


def qualification(config):
    ollama = config["kind"] == "ollama"
    bodies = [{"version": "0.40.2"}, {"models": [{"name": config["model"], "model": config["model"], "digest": "a" * 64, "size": 10}]}] if ollama else [
        {"status": "ok"}, {"object": "list", "data": [{"id": config["model"]}]}]
    return {"schema_version": 1, "name": config["name"], "kind": config["kind"], "model": config["model"], "base_url": config["base_url"],
        "outcome": "CONFIRMED", "model_present": True, "server_version": "0.40.2" if ollama else None,
        "model_digest": "a" * 64 if ollama else None, "responses": [{"endpoint": endpoint, "status": 200,
            "response_body": encode(body).decode(), "response_sha256": v.digest(body), "raw_response": body}
            for endpoint, body in zip(("/api/version", "/api/tags") if ollama else ("/health", "/v1/models"), bodies)],
        "error": None, "elapsed_s": .01}


class Fixture:
    """Small physical synthetic pins; all wire/source/audit checks stay real."""
    def __init__(self, root, mode="smoke"):
        self.root = Path(root) / str(uuid4())
        self.root.mkdir()
        self.path = self.root / "soak.json"
        self.mode, self.duration = mode, 30 if mode == "smoke" else 900
        model_file = self.root / "Qwen3-8B-Q4_K_M.gguf"
        model_file.write_bytes(b"SYNTHETIC NOT A MODEL")
        self.model = {"filename": model_file.name, "bytes": model_file.stat().st_size, "sha256": record(model_file)["sha256"], "layers": 37}
        backend = self.root / "backend"
        backend.mkdir()
        archive = self.root / "synthetic-assets.zip"
        members = {"ollama.exe": b"SYNTHETIC NOT AN EXECUTABLE", "lib/cuda/ggml-cuda.dll": b"SYNTHETIC NOT A DLL"}
        with zipfile.ZipFile(archive, "w") as package:
            for name, raw in members.items():
                package.writestr(name, raw)
                target = backend / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
        (backend / "cellivane-extraction.json").write_bytes(b"{}")
        self.archive = record(archive)
        hashes = {name: sha256(raw).hexdigest() for name, raw in members.items()}
        source_root, sources = self.root / "current-source", {}
        for name in v.SOURCE_PATHS:
            raw = b"# SYNTHETIC NOT EXECUTED " + name.encode()
            path = source_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            saved = self.root / "source-snapshot" / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(raw)
            sources[name] = sha256(raw).hexdigest()
        alias, layers = "cellivane-soak-8b-q4:latest", 36
        options = {"num_ctx": 2048, "num_thread": 4, "num_gpu": layers, "temperature": 0}
        config = {"schema_version": 1, "alias": alias, "options": options, "environment": {"CUDA_VISIBLE_DEVICES": "0",
            "HIP_VISIBLE_DEVICES": "-1", "ROCR_VISIBLE_DEVICES": "-1", "OLLAMA_VULKAN": "0", "OLLAMA_NO_CLOUD": "1",
            "OLLAMA_NUM_PARALLEL": "1", "OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_CONTEXT_LENGTH": "2048", "OLLAMA_DEBUG": "1"},
            "device_scope": "one visible NVIDIA device for hybrid/auto; CPU-only for cpu"}
        plan = {"schema_version": 1, "backend": "ollama", "profile": "hybrid", "num_ctx": 2048, "num_thread": 4,
            "slots": 1, "num_gpu": layers, "temperature": 0, "scope": "requested-placement-only"}
        modelfile = self.root / "Modelfile"
        modelfile.write_text('FROM "' + str(model_file).replace("\\", "/") + '"\n' +
            "".join(f"PARAMETER {k} {value}\n" for k, value in options.items()), encoding="utf-8")
        identity = v.digest({"model_sha256": self.model["sha256"], "backend_tree_sha256": v.digest(hashes), "configuration": config})
        self.s = {"schema_version": 1, "family": "cellivane-large-model-soak-v1", "run_id": self.root.name, "mode": mode,
            "outcome": "COMPLETED", "error": None, "acceptance": "PASS", "acceptance_errors": [], "duration_s": self.duration,
            "minimum_responses": 4 if mode == "smoke" else 24, "guards": copy.deepcopy(v.GUARDS), "model_profile": "8b-q4",
            "model": self.model, "model_file": record(model_file), "rows": [], "cases": copy.deepcopy(v.CASES),
            "system": v.comparison.SYSTEM, "corpus_sha256": v.digest(v.CASES),
            "source": {"root": str(source_root), "sha256": sources, "scope": "declared-18-file-runtime-family-not-loader-attestation"},
            "ports": {"seed": 18991, "worker": 18992}, "ports_closed": {"18991": True, "18992": True},
            "measurement_scope": {"ttft": "NOT_MEASURED", "device_memory": "global-device-total-not-process-VRAM",
                "ram": "global-host-available-not-process-reservation", "backend_kv_reuse": "backend-controlled-not-disabled",
                "native_runtime_gpu_qualified": False, "native_mtp": False, "general_quality": False},
            "preflight": resource(self.root)["observation"], "launch_probe": resource(self.root),
            "budget": {"layers": layers, "ram_required_bytes": self.model["bytes"] + 7 * 1024**3,
                "vram_headroom_bytes": int(1.5 * 1024**3), "vram_workspace_bytes": 768 * 1024**2,
                "layer_estimate_safety_factor": 1.15, "scope": "declared-preflight-not-reservation-or-fit-proof"},
            "backend": {"version": "0.40.2", "executable": record(backend / "ollama.exe"), "archive": self.archive,
                "members": hashes, "tree_sha256": v.digest(hashes)}, "alias": alias, "plan": plan, "configuration": config,
            "identity": identity, "keep_alive": "30m", "version": {"version": "0.40.2"}, "modelfile": record(modelfile),
            "service_start_s": 4., "service_end_s": 4. + self.duration, "cleanup_errors": [], "telemetry_errors": [],
            "resource_guard_reason": None, "model_unchanged": True, "source_unchanged": True, "backend_unchanged": True}
        startup = ("load_backend: loaded CPU backend\nload_backend: loaded CUDA backend\n"
            "load_tensors: CPU model buffer size = 10.00 MiB\nload_tensors: CUDA0 model buffer size = 50.00 MiB\n"
            "load_tensors: offloaded 36/37 layers to GPU\n").encode()
        (self.root / "startup.log").write_bytes(startup)
        (self.root / "ollama.log").write_bytes(startup + b"normal shutdown\n")
        self.s.update(startup_log=record(self.root / "startup.log"), log=record(self.root / "ollama.log"), placement={"schema_version": 1,
            "scope": "run-log-observation-only", "status": "GPU_OFFLOAD_OBSERVED", "offloaded_layers": 36, "total_layers": 37,
            "offload_count_source": "native", "runtimes": ["CPU", "CUDA"], "buffers": [
                {"runtime": "CPU", "device": "CPU", "kind": "model", "mib": 10.},
                {"runtime": "CUDA", "device": "CUDA0", "kind": "model", "mib": 50.}],
            "gpu_offload_observed": True, "gpu_qualified": False, "multi_gpu_qualified": False,
            "errors": [], "warnings": [], "log_sha256": sha256(startup).hexdigest()})
        ps = {"models": [{"name": alias, "model": alias, "digest": "a" * 64, "size": 1000, "size_vram": 500,
            "context_length": 2048, "details": {"quantization_level": "Q4_K_M"}}]}
        self.s.update(loaded_models_ready=reply(None, ps), loaded_models_end=reply(None, ps))
        self.records = [("soak_configuration", {"identity": identity, "plan": plan, "model_sha256": self.model["sha256"]})]
        self.counts, self.seq = dict.fromkeys(v.COUNTERS, 0), 0
        self.s["warmup"] = self.call(v.payload(alias, "Reply with only OK."), "OK", -1, "warmup", 1., .2)
        oversized = v.payload(alias, "must not dispatch"); oversized["max_tokens"] = 129
        self.s["oversize"] = reply(oversized, {"error": {"message": "invalid-request"}}, 400)
        self.counts["rejected"] += 1
        self.emit("reject", reason="invalid-request")
        n = self.s["minimum_responses"]
        for index in range(n):
            case = v.CASES[index % len(v.CASES)]
            self.s["rows"].append(self.call(v.payload(alias, case["prompt"]), case["expected"], index, case["id"],
                4. + index * self.duration / n, self.duration / n - .2))
        self.make_bridge()
        self.emit("close", reason="engine-closed")
        self.s["state"] = {"engine": "seed", "version": "0.1.0", "model": alias, "identity": identity, "closed": True,
            "poisoned": False, "slots": 1, "active": 0, "inflight": 0, "waiters": 0, "max_waiters": 0,
            "cache_entries": 0, "cache_bytes": 0, "cache_entries_limit": 0, "cache_bytes_limit": 0,
            **self.counts, "event_seq": self.seq}
        self.records.append(("shutdown", copy.deepcopy(self.s["state"])))
        self.audit = self.root / "audit" / str(uuid4())
        self.audit.mkdir(parents=True)
        self.s["audit_directory"] = str(self.audit)
        self.samples = []
        for index, elapsed in enumerate([.1 + i * 3 for i in range(int((self.duration + 6) / 3) + 1)], 1):
            stage = "preflight" if index == 1 else "loading" if elapsed < 4 else "service" if elapsed < self.s["service_end_s"] else "after"
            self.samples.append({"seq": index, "elapsed_s": elapsed, "query_wall_s": .01, "stage": stage, **resource(self.root)})
        self.samples[-1]["stage"] = "after"
        self.s["cleanup"] = [{"name": name, "pid": index, "method": "owned-job-terminate-and-close", "returncode": 0,
            "process_exited": True, "process_error": None, "backend_stop_api_confirmed": False, "kv_release_confirmed": False,
            "job_assigned": True, "job_terminated": True, "job_active_processes": 0, "job_closed": True,
            "job_cleanup_confirmed": True, "job_error": None, "created_suspended": True, "assigned_before_resume": True,
            "primary_thread_closed": True, "process_handle_closed": True} for index, name in enumerate(("ollama", "create"), 1)]
        self.reseal()

    def emit(self, kind, key=None, value=None, reason=None):
        self.seq += 1
        self.records.append(("scheduler", {"seq": self.seq, "kind": kind, "key": key,
            "execution": "computed" if kind in ("start", "finish") else None, "reason": reason,
            "response_sha256": v.digest(value) if value is not None else None, "active": int(kind == "start"),
            "waiters": 0, "cache_entries": 0, "cache_bytes": 0, **self.counts}))

    def call(self, wanted, text, index=0, case="bridge", started=0., wall=.2):
        key = v.digest({"identity": self.s["identity"], "inference": wanted})
        self.counts["backend_calls"] += 1
        self.emit("start", key)
        backend = receipt(wanted, text)
        self.records.append(("backend_exchange", backend))
        normalized = {"model": wanted["model"], "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}
        self.counts["computed"] += 1
        self.emit("finish", key, normalized)
        response = reply(wanted, {"id": str(uuid4()), "object": "chat.completion", "created": 1, **normalized,
            "cellivane": {"engine": "seed", "version": "0.1.0", "execution": "computed", "key": key, "backend_calls": self.counts["backend_calls"]}})
        return {"index": index, "case": case, "started_s": started, "completed_s": started + wall, "wall_s": wall,
            "response": response, "backend_exchange_count": 1, "backend_receipt": copy.deepcopy(backend), "exact": True}

    def make_bridge(self):
        alias = self.s["alias"]
        prompt = "Reply with exactly this text and nothing else: CELLIVANE_OK"
        messages = [{"role": "system", "content": "Answer the user briefly and accurately. /no_think"}, {"role": "user", "content": prompt}]
        wanted = {"model": alias, "messages": messages, "temperature": 0, "max_tokens": 128, "stream": False}
        response = self.call(wanted, "CELLIVANE_OK")["response"]
        engines = [{"name": "seed-reference", "kind": "openai", "base_url": "http://127.0.0.1:18991/v1", "model": alias, "role": "reference", "timeout_s": 120, "max_tokens": 128},
            {"name": "ollama-candidate", "kind": "ollama", "base_url": "http://127.0.0.1:18992", "model": alias, "role": "candidate", "timeout_s": 120, "max_tokens": 128}]
        ref = {"name": "seed-reference", "kind": "openai", "model": alias, "outcome": "ANSWERED", "text": "CELLIVANE_OK", "elapsed_s": .1,
            "request_sha256": v.digest(wanted), "response_sha256": sha256(response["raw_response"].encode()).hexdigest(),
            "raw_response": response["body"], "error": None, "usage": response["body"]["usage"], "request_body": encode(wanted).decode(),
            "response_body": response["raw_response"], "http_status": 200}
        candidate = receipt(wanted, "CELLIVANE_OK", "ollama-candidate")
        quals = [qualification(e) for e in engines]
        directory = self.root / "bridge" / str(uuid4()); directory.mkdir(parents=True)
        accepted = {"prompt": prompt, "messages": messages, "engines": engines, "parallelism": 1, "call_budget": 2,
            "deadline_s": 180, "directory_fsync": False, "scope": "isolated-local-experiment", "policy": "reference-is-authoritative"}
        final = {"schema_version": 1, "run_id": directory.name, "run_directory": str(directory), "outcome": "COMPLETE", "error": None,
            "reference_engine": "seed-reference", "answer": "CELLIVANE_OK", "qualifications": {q["name"]: q for q in quals},
            "results": {"seed-reference": ref, "ollama-candidate": candidate}, "dispatch_count": 2, "call_budget": 2, "parallelism": 1,
            "elapsed_s": .5, "output_allowed": True, "model_training": False, "token_mtp": False, "kv_sharing": False,
            "canonical_main_binding": False, "directory_fsync": False, "cancellation_requested": False, "deadline_exceeded": False,
            "qualification_scope": "http-model-availability-only"}
        rows = [("accepted", accepted), ("qualification", quals[0]), ("qualification", quals[1]),
            ("dispatch", {"engine": "seed-reference", "role": "reference", "effective_timeout_s": 120}), ("result", ref),
            ("dispatch", {"engine": "ollama-candidate", "role": "candidate", "effective_timeout_s": 120}), ("result", candidate), ("final", final)]
        previous = "0" * 64
        for seq, (kind, value) in enumerate(rows, 1):
            raw = encode({"schema_version": 1, "sequence": seq, "kind": kind, "previous_sha256": previous, "payload": value})
            (directory / f"{seq:04d}-{kind}.json").write_bytes(raw)
            previous = sha256(raw).hexdigest()
        self.s["bridge_report"] = final

    def reseal(self):
        previous, total_bytes = None, 0
        for path in self.audit.iterdir():
            path.unlink()
        for index, (kind, value) in enumerate(self.records, 1):
            raw = encode({"seq": index, "kind": kind, "value": value, "previous_sha256": previous})
            (self.audit / f"{index:06d}.json").write_bytes(raw)
            previous = sha256(raw).hexdigest(); total_bytes += len(raw)
        n = len(self.records)
        self.s["audit_status"] = {"session_id": self.audit.name, "records": n, "bytes": total_bytes, "record_limit": 10000,
            "byte_limit": 64 * 1024**2, "remaining_records": 10000 - n, "remaining_bytes": 64 * 1024**2 - total_bytes,
            "warning_threshold_percent": 80, "near_capacity": False, "poisoned": False}
        telemetry = self.root / "resources.jsonl"
        telemetry.write_bytes(b"".join(encode(row) + b"\n" for row in self.samples))
        self.s["telemetry"] = record(telemetry)
        self.s["metrics"] = {"responses": len(self.s["rows"]), "exact": sum(r["exact"] for r in self.s["rows"]),
            "median_wall_s": statistics.median(r["wall_s"] for r in self.s["rows"]),
            "scope": "repeated-fixed-corpus-not-general-quality-or-cold-throughput"}
        self.path.write_bytes(encode(self.s))


class SoakRawBoundaryTests(unittest.TestCase):
    def test_strict_json_duplicate_and_nonfinite_input(self):
        for raw in (b'{"status":"PASS","status":"FAIL"}', b'{"elapsed":NaN}', b'{"elapsed":1e999}', b'{'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                v.load(raw)

    def test_physical_artifact_reseal_needs_matching_actual_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.json"
            path.write_bytes(b'{"synthetic":true}')
            record = {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path.read_bytes()).hexdigest()}
            self.assertEqual(v.artifact(record), path.read_bytes())
            path.write_bytes(b'{"synthetic":false}')
            with self.assertRaisesRegex(ValueError, "artifact-content-changed"):
                v.artifact(record)
            record["bytes"] = True
            with self.assertRaisesRegex(ValueError, "artifact-size-or-digest"):
                v.artifact(record)

    def test_raw_gpu_csv_and_typed_values_are_independently_joined(self):
        with tempfile.TemporaryDirectory() as temporary:
            value = resource(temporary)
            self.assertEqual(v.resource_evidence(value), value["observation"])
            value["observation"]["gpu"]["temperature_c"] = 60.
            with self.assertRaisesRegex(ValueError, "resource-typed-raw-join"):
                v.resource_evidence(value)


class SoakFullReplayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.f = Fixture(self.temporary.name)
        for field, value in (("MODELS", {"8b-q4": copy.deepcopy(self.f.model)}), ("OLLAMA_ARCHIVE_BYTES", self.f.archive["bytes"]),
                ("OLLAMA_ARCHIVE_SHA", self.f.archive["sha256"])):
            context = patch.object(v, field, value); context.start(); self.addCleanup(context.stop)

    def replay(self, current=False):
        self.f.reseal()
        return v.replay(self.f.path, self.f.s["source"]["root"] if current else None)

    def test_full_physical_smoke_gold_path_with_all_independent_readers(self):
        result = self.replay(True)
        self.assertEqual((result["verdict"], result["computed_responses"], result["audit_records"]), ("PASS", 4, 22))
        self.assertEqual(result["source_files_checked"], 18)
        self.assertTrue(all(value is False for value in result["claims"].values()))

    def test_single_late_response_drains_once_and_remains_recorded(self):
        row = self.f.s["rows"][-1]
        row.update(completed_s=35., wall_s=35. - row["started_s"])
        self.f.s["service_end_s"] = 35.
        self.assertEqual(self.replay()["drained_requests"], 1)

    def test_incorrect_answer_is_observed_without_promoting_quality_or_rejecting_valid_execution(self):
        row = self.f.s["rows"][0]
        backend = self.f.records[6][1]
        text = "SYNTHETIC WRONG ANSWER"
        for value in (backend, row["backend_receipt"]):
            value["text"] = text
            value["raw_response"]["message"]["content"] = text
            value["response_body"] = encode(value["raw_response"]).decode()
            value["response_sha256"] = v.digest(value["raw_response"])
        response = row["response"]
        response["body"]["choices"][0]["message"]["content"] = text
        response["raw_response"] = encode(response["body"]).decode()
        normalized = {name: response["body"][name] for name in ("model", "choices", "usage")}
        self.f.records[7][1]["response_sha256"] = v.digest(normalized)
        row["exact"] = False
        result = self.replay()
        self.assertEqual(result["verdict"], "PASS")
        self.assertFalse(result["claims"]["quality_generalization"])

    def test_launch_gpu_identity_must_match_all_device_samples(self):
        probe = self.f.s["launch_probe"]
        probe["gpu_raw"]["stdout"] = probe["gpu_raw"]["stdout"].replace("SYNTHETIC GPU", "OTHER GPU")
        probe["observation"]["gpu"]["name"] = "OTHER GPU"
        with self.assertRaisesRegex(ValueError, "launch-telemetry-device-mismatch"):
            self.replay()

    def test_full_900_second_synthetic_window_has24_responses_and82_audit_records(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory, "soak")
            with patch.object(v, "MODELS", {"8b-q4": f.model}):
                # The synthetic archive contents are identical across fixtures.
                result = v.replay(f.path)
            self.assertEqual((result["verdict"], result["admission_window_s"], result["computed_responses"], result["audit_records"]), ("PASS", 900, 24, 82))

    def test_short_window_and_bool_duration_cannot_claim_soak(self):
        self.f.s.update(mode="soak", minimum_responses=24)
        with self.assertRaisesRegex(ValueError, "soak-window-profile"):
            self.replay()
        self.f.s.update(mode="smoke", minimum_responses=4, duration_s=True)
        with self.assertRaisesRegex(ValueError, "soak-window-profile"):
            self.replay()

    def test_resealed_telemetry_gap_or_guard_failure_is_rejected(self):
        self.f.samples[3]["elapsed_s"] = 20
        with self.assertRaisesRegex(ValueError, "telemetry-gap"):
            self.replay()

    def test_resource_threshold_equal_memory_is_allowed_but85c_is_not(self):
        row = self.f.samples[4]
        row["observation"]["memory"]["available_bytes"] = 3 * 1024**3
        row["observation"]["gpu"]["free_bytes"] = 768 * 1024**2
        row["gpu_raw"]["stdout"] = row["gpu_raw"]["stdout"].replace("4096, 4096, 40", "4096, 768, 40")
        self.assertEqual(self.replay()["verdict"], "PASS")
        row["observation"]["gpu"]["temperature_c"] = 85.
        row["gpu_raw"]["stdout"] = row["gpu_raw"]["stdout"].replace(", 65,", ", 85,")
        with self.assertRaisesRegex(ValueError, "telemetry-resource-guard"):
            self.replay()

    def test_lost_query_or_stage_reversal_is_not_healthy_sampling(self):
        self.f.s["telemetry_errors"] = ["query timeout"]
        with self.assertRaisesRegex(ValueError, "telemetry-lost"):
            self.replay()
        self.f.s["telemetry_errors"] = []
        self.f.samples[-1]["stage"] = "preflight"
        with self.assertRaisesRegex(ValueError, "telemetry-stage-order"):
            self.replay()

    def test_rows_cannot_start_after_admission_or_exceed_deadline(self):
        row = self.f.s["rows"][-1]
        row.update(started_s=34., completed_s=34.2, wall_s=.2)
        self.f.s["service_end_s"] = 34.2
        with self.assertRaisesRegex(ValueError, "request-admission-window"):
            self.replay()
        row.update(started_s=26.5, completed_s=147.5, wall_s=121.)
        with self.assertRaisesRegex(ValueError, "request-timing"):
            self.replay()

    def test_serial_request_overlap_is_rejected(self):
        row = self.f.s["rows"][1]
        row.update(started_s=5., completed_s=12.3, wall_s=7.3)
        with self.assertRaisesRegex(ValueError, "request-overlap"):
            self.replay()

    def test_resealed_early_burst_plus_idle_window_does_not_prove_sustained_admission(self):
        for index, row in enumerate(self.f.s["rows"]):
            row.update(started_s=4. + index * .5, completed_s=4.2 + index * .5, wall_s=.2)
        with self.assertRaisesRegex(ValueError, "continuous-admission-end-gap"):
            self.replay()

    def test_source_snapshot_omission_and_current_mutation_fail(self):
        name = next(iter(self.f.s["source"]["sha256"]))
        original = self.f.s["source"]["sha256"].pop(name)
        with self.assertRaisesRegex(ValueError, "source-family"):
            self.replay()
        self.f.s["source"]["sha256"][name] = original
        (Path(self.f.s["source"]["root"]) / name).write_bytes(b"changed source")
        with self.assertRaisesRegex(ValueError, "current-source-changed"):
            self.replay(True)

    def test_model_or_backend_bytes_must_match_pinned_archive(self):
        dll = Path(self.f.s["backend"]["executable"]["path"]).parent / "lib/cuda/ggml-cuda.dll"
        dll.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "backend-member-size"):
            self.replay()

    def test_resealed_budget_cannot_omit_workspace_or_gpu_headroom(self):
        self.f.s["budget"]["ram_required_bytes"] -= 1024**3
        with self.assertRaisesRegex(ValueError, "budget-recompute"):
            self.replay()

    def test_raw_startup_prefix_and_late_fatal_are_required(self):
        path = self.f.root / "ollama.log"
        path.write_bytes(path.read_bytes() + b"CUDA error: allocation failed\n")
        self.f.s["log"] = record(path)
        with self.assertRaisesRegex(ValueError, "fatal-backend-log"):
            self.replay()

    def test_identical_second_offload_line_is_still_a_reload(self):
        path = self.f.root / "ollama.log"
        path.write_bytes(path.read_bytes() + b"load_tensors: offloaded 36/37 layers to GPU\n")
        self.f.s["log"] = record(path)
        with self.assertRaisesRegex(ValueError, "model-reloaded"):
            self.replay()

    def test_loaded_model_digest_or_quantization_cannot_change_at_end(self):
        value = self.f.s["loaded_models_end"]
        value["body"]["models"][0]["digest"] = "b" * 64
        value["raw_response"] = encode(value["body"]).decode()
        with self.assertRaisesRegex(ValueError, "loaded-model-changed"):
            self.replay()

    def test_normalized_usage_and_cache_execution_are_bound_to_raw_backend(self):
        row = self.f.s["rows"][0]
        row["response"]["body"]["cellivane"]["execution"] = "cache"
        row["response"]["raw_response"] = encode(row["response"]["body"]).decode()
        with self.assertRaisesRegex(ValueError, "seed-normalized-key"):
            self.replay()

    def test_resealed_backend_wire_cannot_enable_streaming_or_change_prompt(self):
        backend = self.f.records[6][1]
        raw = json.loads(backend["request_body"])
        raw["stream"] = True
        backend["request_body"] = encode(raw).decode()
        backend["request_sha256"] = v.digest(raw)
        self.f.s["rows"][0]["backend_receipt"] = copy.deepcopy(backend)
        with self.assertRaisesRegex(ValueError, "backend-request-wire"):
            self.replay()

    def test_stale33_layer_catalog_or_claimed_full_gpu_is_rejected(self):
        self.f.s["model"]["layers"] = 33
        with self.assertRaisesRegex(ValueError, "model-profile-pin"):
            self.replay()
        self.f.s["model"]["layers"] = 37
        self.f.s["placement"]["offloaded_layers"] = 37
        with self.assertRaisesRegex(ValueError, "placement-raw-log-join"):
            self.replay()

    def test_audit_missing_preflight_rejection_is_not_zero_dispatch_proof(self):
        self.f.records.pop(4)
        with self.assertRaisesRegex(ValueError, "audit-record-count"):
            self.replay()

    def test_truncated_or_duplicate_telemetry_is_rejected_after_hash_reseal(self):
        self.f.reseal()
        path = Path(self.f.s["telemetry"]["path"])
        raw = path.read_bytes()
        path.write_bytes(raw[:-1])
        self.f.s["telemetry"] = record(path)
        self.f.path.write_bytes(encode(self.f.s))
        with self.assertRaisesRegex(ValueError, "telemetry-truncated"):
            v.replay(self.f.path)
        line = encode(self.f.samples[0]).replace(b'"seq":1', b'"seq":1,"seq":1') + b"\n"
        path.write_bytes(line + raw.split(b"\n", 1)[1])
        self.f.s["telemetry"] = record(path)
        self.f.path.write_bytes(encode(self.f.s))
        with self.assertRaisesRegex(ValueError, "duplicate-json-key"):
            v.replay(self.f.path)

    def test_scheduler_backend_counter_and_reject_are_not_declarations(self):
        self.f.records[4][1]["backend_calls"] = 2
        with self.assertRaisesRegex(ValueError, "scheduler-event-recompute"):
            self.replay()

    def test_cleanup_or_port_failure_cannot_hide_behind_completed(self):
        self.f.s["cleanup"][0]["assigned_before_resume"] = False
        with self.assertRaisesRegex(ValueError, "cleanup-unconfirmed"):
            self.replay()
        self.f.s["cleanup"][0]["assigned_before_resume"] = True
        self.f.s["ports_closed"]["18992"] = False
        with self.assertRaisesRegex(ValueError, "ports-not-closed"):
            self.replay()

    def test_ttft_or_process_vram_claim_is_rejected(self):
        self.f.s["measurement_scope"]["ttft"] = "MEASURED"
        with self.assertRaisesRegex(ValueError, "unsupported-measurement-claim"):
            self.replay()

    def test_failed_telemetry_run_cannot_be_relabelled_complete_only(self):
        self.f.s.update(acceptance="FAIL", acceptance_errors=["telemetry-coverage-or-gap"])
        with self.assertRaisesRegex(ValueError, "soak-not-completed"):
            self.replay()

    def test_missing_mandatory_telemetry_or_wrong_gpu_does_not_become_zero(self):
        with tempfile.TemporaryDirectory() as temporary:
            original = resource(temporary)
            for wire in ("0, GPU, 580.1, 8192, 4096, N/A, 40, 65, 55.5\n",
                    "1, GPU, 580.1, 8192, 4096, 4096, 40, 65, 55.5\n",
                    "0, GPU, 580.1, 8192, 4096, 4096, 40, NaN, 55.5\n",
                    original["gpu_raw"]["stdout"] * 2, "0, GPU\n"):
                value = copy.deepcopy(original)
                value["gpu_raw"]["stdout"] = wire
                with self.subTest(wire=wire), self.assertRaises(ValueError):
                    v.resource_evidence(value)

    def test_optional_power_na_is_explicit_null_and_bool_status_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            value = resource(temporary)
            value["gpu_raw"]["stdout"] = value["gpu_raw"]["stdout"].replace("55.5", "N/A")
            value["observation"]["gpu"]["power_w"] = None
            self.assertIsNone(v.resource_evidence(value)["gpu"]["power_w"])
            value["gpu_raw"]["returncode"] = False
            with self.assertRaisesRegex(ValueError, "resource-query-command"):
                v.resource_evidence(value)


if __name__ == "__main__":
    unittest.main()
