#!/usr/bin/env python3
"""Bounded large-model CUDA/CPU soak through the existing Seed and Ollama path.

The native Cellivane Runtime remains CPU-only. Samples describe device/host
totals; backend KV reuse is not disabled. No TTFT or general quality claim.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from hashlib import sha256
import http.client
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import threading
import time
from uuid import uuid4

import cellivane_seed_compare as comparison
import cellivane_resource_probe as resources
from cellivane_bridge.adapters import _load
from cellivane_seed.core import InvalidRequest

lab, REPO = comparison.lab, comparison.REPO
GiB, MiB = 1024**3, 1024**2
MODELS = {
    "4b-q8": {"filename": "Qwen3-4B-Q8_0.gguf", "bytes": 4280404704,
        "sha256": "8c2f07f26af9747e41988551106f149b03eb9b5cb6df636027b6bf6278473300", "layers": 37},
    "8b-q4": {"filename": "Qwen3-8B-Q4_K_M.gguf", "bytes": 5027783488,
        "sha256": "d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785", "layers": 37},
}
CASES = [*comparison.CASES,
    {"id": "medium-lookup", "prompt": "Read these records and return only the value of TARGET_CODE.\n" +
        "\n".join(f"record {i}: ordinary value {i * 3}" for i in range(30)) +
        "\nTARGET_CODE = BLUE_742\nReturn only TARGET_CODE.", "expected": "BLUE_742"},
    {"id": "medium-ko", "prompt": "다음 기록에서 최종 승인된 색상만 한 단어로 답해 줘.\n" +
        "\n".join(f"검토 {i}: 아직 미정이며 승인이 필요하다." for i in range(20)) +
        "\n최종 승인: 파랑.\n최종 승인된 색상만 답해 줘.", "expected": "파랑"}]
GUARDS = {"minimum_ram_free_bytes": 3 * GiB, "minimum_vram_free_bytes": 768 * MiB,
          "maximum_temperature_c": 85, "sample_interval_s": 3, "maximum_sample_gap_s": 10,
          "request_deadline_s": 120, "minimum_start_interval_s": .5, "maximum_requests": 2048,
          "maximum_log_bytes": 16 * MiB, "maximum_telemetry_bytes": 8 * MiB}
FATAL = re.compile(r"out of memory|cuda error|cudamalloc.*failed|cublas_status_alloc_failed|panic:|fatal error:", re.I)
OFFLOAD = re.compile(r"^.*(?:offloaded [0-9]+/[0-9]+ layers to GPU|layers\.offload=[0-9]+).*", re.M)


def encoded(value):
    return comparison.encoded(value)


def record(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": lab.digest(path)}


def source_snapshot(root):
    files = comparison.source_hashes()
    files.update({"tools/hosted/" + name + ".py": lab.digest(REPO / "tools/hosted" / (name + ".py"))
                  for name in ("cellivane_seed_soak", "cellivane_resource_probe")})
    for name in files:
        target = root / "source-snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO / name).read_bytes())
    return {"root": str(REPO), "sha256": files, "scope": "declared-18-file-runtime-family-not-loader-attestation"}


def plan_for(model, observation):
    ram_required = model["bytes"] + 2 * GiB + GiB + 4 * GiB
    if observation["memory"]["available_bytes"] < ram_required:
        raise ValueError("soak-declared-ram-budget")
    usable = observation["gpu"]["free_bytes"] - int(1.5 * GiB) - 768 * MiB
    per_layer = model["bytes"] / model["layers"] * 1.15
    layers = min(model["layers"] - 1, int(usable // per_layer))
    if layers < 1:
        raise ValueError("soak-declared-vram-budget")
    return {"layers": layers, "ram_required_bytes": ram_required,
            "vram_headroom_bytes": int(1.5 * GiB), "vram_workspace_bytes": 768 * MiB,
            "layer_estimate_safety_factor": 1.15, "scope": "declared-preflight-not-reservation-or-fit-proof"}


def guard_failure(observation):
    if observation["memory"]["available_bytes"] < GUARDS["minimum_ram_free_bytes"]:
        return "ram-headroom"
    if observation["gpu"]["free_bytes"] < GUARDS["minimum_vram_free_bytes"]:
        return "vram-headroom"
    if observation["gpu"]["temperature_c"] >= GUARDS["maximum_temperature_c"]:
        return "gpu-temperature"
    return None


class Sampler:
    def __init__(self, path):
        self.path, self.started = Path(path), time.perf_counter()
        self.stream = self.path.open("xb")
        self.stage, self.rows, self.errors, self.reason = "preflight", [], [], None
        self.quit, self.guard = threading.Event(), threading.Event()
        self.thread = threading.Thread(target=self._run, name="cellivane-resource-sampler", daemon=True)

    def sample(self):
        begin = time.perf_counter()
        value = resources.observe_with_evidence()
        row = {"seq": len(self.rows) + 1, "elapsed_s": time.perf_counter() - self.started,
               "query_wall_s": time.perf_counter() - begin, "stage": self.stage, **value}
        raw = encoded(row) + b"\n"
        if self.stream.tell() + len(raw) > GUARDS["maximum_telemetry_bytes"]:
            raise RuntimeError("soak-telemetry-byte-limit")
        self.stream.write(raw)
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.rows.append(row)
        reason = guard_failure(value["observation"])
        if reason:
            self.reason = self.reason or reason
            self.guard.set()
        return value["observation"]

    def _run(self):
        while not self.quit.wait(GUARDS["sample_interval_s"]):
            try:
                self.sample()
            except BaseException as exc:
                self.errors.append(type(exc).__name__ + ":" + str(exc)[:256])
                self.guard.set()
                return

    def close(self):
        self.quit.set()
        if self.thread.ident is not None:
            self.thread.join(timeout=10)
            if self.thread.is_alive():
                self.errors.append("sampler-thread-still-active")
        self.stream.close()


class SoakSeed(comparison.SeedEngine):
    def _request(self, payload):
        value, key = super()._request(payload)
        if value["max_tokens"] > 128:
            raise InvalidRequest("soak-output-limit")
        return value, key


def exchange(port, path, payload=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=130)
    try:
        connection.request("GET" if payload is None else "POST", path,
            body=None if payload is None else encoded(payload), headers={"Content-Type": "application/json", "Connection": "close"})
        response = connection.getresponse()
        raw = response.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise ValueError("soak-response-size")
        return {"status": response.status, "body": _load(raw), "raw_response": raw.decode("utf-8"), "request": payload}
    finally:
        connection.close()


def response_row(port, body, case, index, audit, clock):
    before, began = audit.sequence, time.perf_counter()
    reply = exchange(port, "/v1/chat/completions", body)
    ended = time.perf_counter()
    exchanges = []
    for sequence in range(before + 1, audit.sequence + 1):
        value = json.loads((audit.directory / f"{sequence:06d}.json").read_text(encoding="utf-8"))
        if value["kind"] == "backend_exchange":
            exchanges.append(value["value"])
    text = reply["body"].get("choices", [{}])[0].get("message", {}).get("content", "")
    return {"index": index, "case": case["id"], "started_s": began - clock, "completed_s": ended - clock,
            "wall_s": ended - began, "response": reply, "backend_exchange_count": len(exchanges),
            "backend_receipt": exchanges[0] if len(exchanges) == 1 else None, "exact": text.strip() == case["expected"]}


def answered(row):
    return (row["response"]["status"] == 200 and row["backend_exchange_count"] == 1
            and row["response"]["body"].get("cellivane", {}).get("execution") == "computed")


def bridge_configuration(root, seed_port, worker_port, alias):
    engines = [comparison.EngineConfig("seed-reference", "openai", f"http://127.0.0.1:{seed_port}/v1", alias, "reference", 120, 128),
        comparison.EngineConfig("ollama-candidate", "ollama", f"http://127.0.0.1:{worker_port}", alias, "candidate", 120, 128)]
    return {"schema_version": 1, "storage_root": str(root), "parallelism": 1,
            "deadline_s": 180, "engines": [e.record() for e in engines]}, engines


def require_placement(place, requested_layers, total_layers):
    if (place["status"] != "GPU_OFFLOAD_OBSERVED" or "CUDA" not in place["runtimes"]
            or not 0 < place["offloaded_layers"] < place["total_layers"]
            or place["offloaded_layers"] != requested_layers or place["total_layers"] != total_layers):
        raise RuntimeError("soak-partial-cuda-not-observed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("smoke", "soak"), default="soak")
    parser.add_argument("--model", choices=tuple(MODELS), required=True)
    for name in ("model-file", "asset-root", "storage-root"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--duration-seconds", type=int)
    parser.add_argument("--port", type=int, default=18991)
    parser.add_argument("--worker-port", type=int, default=18992)
    args = parser.parse_args(argv)
    duration = args.duration_seconds if args.duration_seconds is not None else (60 if args.mode == "smoke" else 900)
    low, high = (30, 300) if args.mode == "smoke" else (900, 3600)
    if not low <= duration <= high or args.port == args.worker_port or any(not 1024 <= p <= 65535 for p in (args.port, args.worker_port)):
        parser.error("invalid duration or loopback ports")
    if os.name != "nt":
        parser.error("owned CUDA soak currently requires Windows")
    root = comparison.local_root(args.storage_root)
    directory = comparison.local_root(root / "soak-runs") / str(uuid4())
    directory.mkdir()
    summary = {"schema_version": 1, "family": "cellivane-large-model-soak-v1", "run_id": directory.name,
        "mode": args.mode, "outcome": "FAILED", "error": None, "acceptance": "FAIL", "acceptance_errors": [],
        "duration_s": duration, "minimum_responses": 4 if args.mode == "smoke" else 24,
        "guards": GUARDS, "model_profile": args.model, "model": MODELS[args.model], "rows": [],
        "cases": CASES, "system": comparison.SYSTEM, "corpus_sha256": sha256(encoded(CASES)).hexdigest(),
        "source": source_snapshot(directory), "ports": {"seed": args.port, "worker": args.worker_port},
        "cleanup": [], "measurement_scope": {"ttft": "NOT_MEASURED", "device_memory": "global-device-total-not-process-VRAM",
            "ram": "global-host-available-not-process-reservation", "backend_kv_reuse": "backend-controlled-not-disabled",
            "native_runtime_gpu_qualified": False, "native_mtp": False, "general_quality": False}}
    sampler, engine, server, thread, audit = None, None, None, None, None
    owned, cleanup_errors = [], []
    def finish(label, operation):
        try:
            return operation()
        except BaseException as exc:
            cleanup_errors.append(label + ":" + type(exc).__name__ + ":" + str(exc)[:256])
            return None
    try:
        model = Path(args.model_file).resolve(strict=True)
        comparison.local_root(model.parent)
        pin = summary["model"]
        if model.name != pin["filename"] or model.stat().st_size != pin["bytes"] or lab.digest(model) != pin["sha256"]:
            raise ValueError("soak-model-artifact-pin")
        summary["model_file"] = record(model)
        if shutil.disk_usage(root).free < pin["bytes"] * 2 + 5 * GiB:
            raise RuntimeError("soak-declared-disk-headroom")
        sampler = Sampler(directory / "resources.jsonl")
        summary["preflight"] = sampler.sample()
        summary["budget"] = plan_for(pin, summary["preflight"])
        if sampler.guard.is_set():
            raise RuntimeError("soak-preflight-resource-guard")
        sampler.thread.start()
        assets = lab.prepare(comparison.local_root(args.asset_root), Path(os.environ.get("LOCALAPPDATA", "")) / "AIOS/hosted-inference")
        members, tree_sha = comparison.backend_tree(assets["ollama"])
        summary["backend"] = {"version": lab.OLLAMA_VERSION, "executable": record(assets["ollama"]),
            "archive": record(Path(args.asset_root) / "downloads" / f"ollama-v{lab.OLLAMA_VERSION}-windows-amd64.zip"),
            "members": members, "tree_sha256": tree_sha}
        summary["launch_probe"] = resources.observe_with_evidence()
        summary["budget"] = plan_for(pin, summary["launch_probe"]["observation"])
        if sampler.guard.is_set():
            raise RuntimeError("soak-resource-guard-before-launch")
        plan = comparison.build_plan("hybrid", layers=summary["budget"]["layers"])
        alias = "cellivane-soak-" + args.model + ":latest"
        summary["alias"], summary["plan"] = alias, plan.record()
        summary["configuration"] = comparison.execution_configuration(alias, plan)
        summary["identity"] = sha256(encoded({"model_sha256": pin["sha256"], "backend_tree_sha256": tree_sha,
                                             "configuration": summary["configuration"]})).hexdigest()
        for port in (args.port, args.worker_port):
            lab.port_free(port)
        with ExitStack() as stack:
            sampler.stage = "loading"
            env = lab.child_env(root, assets["ollama"].parent)
            env.update(summary["configuration"]["environment"])
            env.update(OLLAMA_HOST=f"127.0.0.1:{args.worker_port}", OLLAMA_KEEP_ALIVE="30m")
            summary["keep_alive"] = "30m"
            worker = lab.OwnedProcess(stack, [str(assets["ollama"]), "serve"], env, directory, "ollama")
            owned.append(worker)
            summary["version"] = lab.ready(worker.process, args.worker_port, "/api/version")
            if summary["version"] != {"version": lab.OLLAMA_VERSION}:
                raise RuntimeError("soak-backend-version")
            modelfile = directory / "Modelfile"
            modelfile.write_text('FROM "' + str(model).replace('\\', '/') + '"\n' +
                ''.join(f"PARAMETER {key} {value}\n" for key, value in plan.ollama_options().items()), encoding="utf-8")
            summary["modelfile"] = record(modelfile)
            create = lab.OwnedProcess(stack, [str(assets["ollama"]), "create", alias, "-f", str(modelfile)], env, directory, "create")
            owned.append(create)
            if create.process.wait(timeout=180) != 0:
                raise RuntimeError("soak-create-failed")
            audit = comparison.Audit(root)
            summary["audit_directory"] = str(audit.directory)
            audit.append("soak_configuration", {"identity": summary["identity"], "plan": summary["plan"], "model_sha256": pin["sha256"]})
            backend = comparison.OllamaBackend(comparison.EngineConfig("ollama-tensor", "ollama",
                f"http://127.0.0.1:{args.worker_port}", alias, timeout_s=120, max_tokens=128), audit)
            engine = SoakSeed(backend, model=alias, identity=summary["identity"], cache_entries=0, cache_bytes=0,
                              max_waiters=0, timeout_s=120, event_sink=lambda event: audit.append("scheduler", event))
            server = comparison.SeedHTTPServer(("127.0.0.1", args.port), engine, audit)
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
            thread.start()
            body = lambda prompt: {"model": alias, "messages": [{"role": "system", "content": summary["system"]},
                {"role": "user", "content": prompt}], "max_tokens": 128, "temperature": 0, "stream": False}
            summary["warmup"] = response_row(args.port, body("Reply with only OK."), {"id": "warmup", "expected": "OK"}, -1, audit, sampler.started)
            if not answered(summary["warmup"]):
                raise RuntimeError("soak-warmup-not-computed")
            summary["loaded_models_ready"] = exchange(args.worker_port, "/api/ps")
            log_path = directory / "ollama.log"
            raw_log = log_path.read_bytes()
            startup = directory / "startup.log"
            startup.write_bytes(raw_log)
            summary["startup_log"] = record(startup)
            summary["placement"] = comparison.observe_placement(raw_log.decode("utf-8"))
            place = summary["placement"]
            require_placement(place, summary["budget"]["layers"], pin["layers"])
            rejected = body("must not dispatch"); rejected["max_tokens"] = 129
            summary["oversize"] = exchange(args.port, "/v1/chat/completions", rejected)
            if summary["oversize"]["status"] != 400 or engine.status()["backend_calls"] != 1:
                raise RuntimeError("soak-oversize-dispatched")
            sampler.stage = "service"
            began, last_start, next_progress = time.perf_counter(), None, 60
            summary["service_start_s"] = began - sampler.started
            print(json.dumps({"state": "READY", "directory": str(directory), "model": args.model,
                "requested_layers": summary["budget"]["layers"], "observed_layers": place["offloaded_layers"], "duration_s": duration}), flush=True)
            while time.perf_counter() - began < duration:
                if sampler.guard.is_set():
                    raise RuntimeError("soak-resource-guard:" + str(sampler.reason or sampler.errors))
                if last_start is not None:
                    sampler.guard.wait(max(0, GUARDS["minimum_start_interval_s"] - (time.perf_counter() - last_start)))
                if time.perf_counter() - began >= duration:
                    break
                if sampler.guard.is_set():
                    raise RuntimeError("soak-resource-guard-before-dispatch")
                if len(summary["rows"]) >= GUARDS["maximum_requests"]:
                    raise RuntimeError("soak-request-capacity")
                case = CASES[len(summary["rows"]) % len(CASES)]
                last_start = time.perf_counter()
                row = response_row(args.port, body(case["prompt"]), case, len(summary["rows"]), audit, sampler.started)
                summary["rows"].append(row)
                if not answered(row):
                    raise RuntimeError("soak-request-not-computed")
                if log_path.stat().st_size > GUARDS["maximum_log_bytes"] or FATAL.search(log_path.read_text(encoding="utf-8")):
                    raise RuntimeError("soak-backend-log-failure")
                elapsed = time.perf_counter() - began
                if elapsed >= next_progress:
                    last = sampler.rows[-1]["observation"]
                    print(json.dumps({"progress_s": elapsed, "responses": len(summary["rows"]),
                        "ram_free_bytes": last["memory"]["available_bytes"], "vram_free_bytes": last["gpu"]["free_bytes"],
                        "gpu_temperature_c": last["gpu"]["temperature_c"]}), flush=True)
                    lab.save(directory / f"progress-{int(next_progress):04d}.json", {"elapsed_s": elapsed, "responses": len(summary["rows"]), "last_resource": last})
                    next_progress += 60
            summary["service_end_s"] = time.perf_counter() - sampler.started
            if sampler.guard.is_set():
                raise RuntimeError("soak-resource-guard-after-drain")
            sampler.stage = "bridge"
            bridge_config, bridge_engines = bridge_configuration(root, args.port, args.worker_port, alias)
            summary["bridge_report"] = comparison.bridge_run(bridge_config, bridge_engines,
                "Reply with exactly this text and nothing else: CELLIVANE_OK")
            summary["loaded_models_end"] = exchange(args.worker_port, "/api/ps")
            sampler.stage = "cleanup"
        summary["outcome"] = "COMPLETED"
    except BaseException as exc:
        summary["error"] = type(exc).__name__ + ":" + str(exc)[:512]
    finally:
        if engine is not None:
            finish("seed-close", engine.close)
        if server is not None:
            if thread is not None and thread.is_alive():
                finish("server-shutdown", server.shutdown)
            finish("server-close", server.server_close)
        if thread is not None:
            finish("server-thread-join", lambda: thread.join(timeout=10))
            if thread.is_alive(): cleanup_errors.append("server-thread-active")
        if engine is not None:
            summary["state"] = finish("seed-state", engine.status)
            finish("audit-shutdown", lambda: audit.append("shutdown", summary["state"]))
            summary["audit_status"] = audit.status()
        summary["cleanup"] = [item.cleanup for item in owned]
        if sampler is not None:
            sampler.stage = "after"
            # Join before the final sample so only one writer appends resources.
            sampler.quit.set()
            if sampler.thread.ident is not None: sampler.thread.join(timeout=10)
            if not sampler.thread.is_alive():
                finish("final-resource", sampler.sample)
            else:
                cleanup_errors.append("sampler-thread-active-before-final-sample")
            finish("sampler-close", sampler.close)
            summary["telemetry"] = record(sampler.path)
            summary["telemetry_errors"] = sampler.errors
            summary["resource_guard_reason"] = sampler.reason
        summary["cleanup_errors"] = cleanup_errors
        summary["ports_closed"] = {}
        for port in (args.port, args.worker_port):
            try:
                lab.port_free(port); summary["ports_closed"][str(port)] = True
            except OSError:
                summary["ports_closed"][str(port)] = False
        if "model_file" in summary:
            summary["model_unchanged"] = finish("model-after-hash", lambda: lab.digest(summary["model_file"]["path"]) == summary["model"]["sha256"])
        summary["source_unchanged"] = finish("source-after-hash", lambda:
            all(lab.digest(REPO / name) == value for name, value in summary["source"]["sha256"].items()))
        if "backend" in summary:
            summary["backend_unchanged"] = finish("backend-after-hash", lambda:
                comparison.backend_tree(Path(summary["backend"]["executable"]["path"]))[1] == summary["backend"]["tree_sha256"])
        log = directory / "ollama.log"
        if log.exists(): summary["log"] = record(log)
        errors = summary["acceptance_errors"]
        if summary["outcome"] != "COMPLETED": errors.append("execution-incomplete")
        if len(summary["rows"]) < summary["minimum_responses"] or any(not answered(r) for r in summary["rows"]): errors.append("response-count-or-completion")
        if summary.get("service_end_s", 0) - summary.get("service_start_s", 0) < duration: errors.append("service-window-incomplete")
        if summary.get("telemetry_errors") or summary.get("resource_guard_reason") or cleanup_errors: errors.append("resource-or-cleanup-error")
        if any(summary.get(key) is not True for key in ("model_unchanged", "source_unchanged", "backend_unchanged")): errors.append("artifact-changed")
        if (not all(summary["ports_closed"].values()) or len(owned) != 2
                or any(type(p) is not dict or p.get("job_cleanup_confirmed") is not True
                    or p.get("process_exited") is not True or p.get("process_handle_closed") is not True
                    or p.get("process_error") is not None for p in summary["cleanup"])):
            errors.append("owned-cleanup-incomplete")
        if sampler is not None:
            times = [r["elapsed_s"] for r in sampler.rows]
            if (len(times) < 2 or any(not 0 < b - a <= GUARDS["maximum_sample_gap_s"] for a, b in zip(times, times[1:]))
                    or times[0] > summary.get("service_start_s", -1) or times[-1] < summary.get("service_end_s", math.inf)):
                errors.append("telemetry-coverage-or-gap")
        start = summary.get("service_start_s", 0)
        if any(not 0 <= r["started_s"] - start < duration or r["wall_s"] > 120 for r in summary["rows"]):
            errors.append("request-admission-or-deadline")
        if summary.get("service_end_s", 0) - start > duration + 120:
            errors.append("service-drain-deadline")
        count = len(summary["rows"])
        state = summary.get("state") or {}
        if (state.get("computed") != count + 2 or state.get("backend_calls") != count + 2 or state.get("rejected") != 1
                or any(state.get(k) != 0 for k in ("cache_hits", "coalesced", "failures", "timeouts", "active", "inflight", "waiters"))): errors.append("seed-counters")
        bridge = summary.get("bridge_report", {})
        if bridge.get("outcome") != "COMPLETE" or bridge.get("dispatch_count") != 2 or bridge.get("output_allowed") is not True: errors.append("bridge-incomplete")
        if log.exists():
            try:
                text = log.read_text(encoding="utf-8")
                if FATAL.search(text): errors.append("fatal-backend-log")
                if "startup_log" in summary and OFFLOAD.findall(text) != OFFLOAD.findall(Path(summary["startup_log"]["path"]).read_text(encoding="utf-8")): errors.append("model-reload-during-soak")
            except (OSError, UnicodeError):
                errors.append("unreadable-backend-log")
        summary["acceptance"] = "FAIL" if errors else "PASS"
        summary["metrics"] = {"responses": count, "exact": sum(r["exact"] for r in summary["rows"]),
            "median_wall_s": statistics.median(r["wall_s"] for r in summary["rows"]) if count else None,
            "scope": "repeated-fixed-corpus-not-general-quality-or-cold-throughput"}
        lab.save(directory / "soak.json", summary)
        print(json.dumps({"acceptance": summary["acceptance"], "error": summary["error"], "summary": str(directory / "soak.json")}), flush=True)
    return 0 if summary["acceptance"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
