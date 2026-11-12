#!/usr/bin/env python3
"""Run a Cellivane native CPU worker with explicit Murphy preparation.

Smoke is a small paired functional observation, not a general speed benchmark.
Source/model hashing warms the OS page cache. No tensor weight values change.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import threading
import time
from uuid import uuid4

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "hosted/experimental"))
from cellivane_bridge.storage import local_root, read_json, encoded
from cellivane_runtime import NativeRuntime, MurphyPlan, RuntimeSeedEngine
from cellivane_seed.server import Audit, SeedHTTPServer
import cellivane_llama_assets as assets
from cellivane_runtime_transport import NativeTransport, memory_snapshot

ALIAS = "cellivane-runtime-target"
MODEL_BYTES = 639446688
MODEL_SHA = "9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031"
CASES = (("addition", "What is 2 + 3? Reply with only the number. /no_think"),
         ("word", "Reply with exactly OK and nothing else. /no_think"))


def save(path, value):
    raw = encoded(value)
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def file_record(path):
    path = Path(path).resolve(strict=True)
    local_root(path.parent)
    if not path.is_file() or path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
        raise ValueError("runtime-artifact-regular-local-required")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": assets.file_sha256(path)}


def source_records(root):
    names = ["native/cellivane_runtime/worker.cpp"]
    for directory in ("hosted/experimental/cellivane_runtime", "hosted/experimental/cellivane_seed", "hosted/experimental/cellivane_bridge"):
        names += [p.relative_to(REPO).as_posix() for p in sorted((REPO / directory).glob("*.py"))]
    names += ["tools/hosted/" + name + ".py" for name in ("cellivane_bridge_lab", "cellivane_llama_assets", "build_cellivane_runtime", "cellivane_runtime_lab", "cellivane_runtime_transport")]
    rows = []
    for name in names:
        raw = (REPO / name).read_bytes()
        snapshot = Path("source-snapshot") / name
        target = root / snapshot
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        rows.append({"path": name, "bytes": len(raw), "sha256": sha256(raw).hexdigest(), "snapshot": snapshot.as_posix()})
    return {"root": str(REPO), "files": rows, "scope": "declared-source-family-not-loader-attestation"}


def configuration(repeat):
    return {"alias": ALIAS, "target_profile": "0.6b", "context_tokens": 512, "threads": 4, "batch": 128,
            "max_tokens": 64, "warmup_max_tokens": 1, "rounds": repeat,
            "mode_order": [m for r in range(repeat) for m in (("none", "murphy") if r % 2 == 0 else ("murphy", "none"))],
            "no_result_cache": True, "placement": "cpu"}


def request(prompt):
    return {"model": ALIAS, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 64, "temperature": 0, "stream": False}


def artifact_state(model, worker, engine, native_files):
    binaries = {name: assets.file_sha256(Path(engine["directory"]) / name) for name in engine["binary_sha256"]}
    return {"model_sha256": assets.file_sha256(model["path"]), "worker_sha256": assets.file_sha256(worker["path"]),
            "engine_identity": sha256(encoded({"backend": "llama.cpp", "commit": assets.COMMIT,
                "archive_sha256": engine["archive_sha256"], "binary_sha256": binaries})).hexdigest(),
            "sealed_engine_sha256": sha256(encoded({row["relative_path"]: assets.file_sha256(row["path"])
                                                     for row in native_files})).hexdigest()}


def checked_build(receipt_record, worker, engine):
    receipt = read_json(receipt_record["path"], 4 * 1024**2)
    if (receipt.get("outcome") != "COMPILED" or receipt.get("exit_code") != 0
            or receipt.get("engine_commit") != assets.COMMIT or receipt.get("executable") != worker
            or receipt.get("source", {}).get("sha256") != assets.file_sha256(REPO / "native/cellivane_runtime/worker.cpp")
            or receipt.get("builder", {}).get("sha256") != assets.file_sha256(REPO / "tools/hosted/build_cellivane_runtime.py")):
        raise ValueError("runtime-build-identity")
    directory = local_root(receipt["engine_directory"])
    expected = set()
    for row in receipt["engine_files"]:
        name = row["relative_path"]
        if name in expected or Path(name).name != name or row["sha256"] != engine["member_sha256"].get(name):
            raise ValueError("runtime-sealed-library-pin")
        expected.add(name)
        actual = file_record(directory / name)
        if actual != {key: row[key] for key in ("path", "bytes", "sha256")}:
            raise ValueError("runtime-sealed-library-bytes")
    if {path.name for path in directory.iterdir()} != expected or not {"llama.dll", "ggml.dll", "ggml-base.dll"} <= expected:
        raise ValueError("runtime-sealed-library-tree")
    return receipt


def phase(root, index, mode, summary, *, serve=False, port=18981):
    directory = root / f"phase-{index:02d}-{mode}"
    directory.mkdir()
    model, worker, engine = summary["model"], summary["worker"], summary["engine"]
    snapshot = memory_snapshot()
    required = model["bytes"] + 2 * 1024**3 + 512 * 1024**2
    if required > snapshot["available_bytes"] - 4 * 1024**3:
        raise RuntimeError("runtime-declared-ram-budget")
    record = {"index": index, "mode": mode, "requests": [], "warmup": None,
              "memory": snapshot, "budget": {"required_bytes": required, "headroom_bytes": 4 * 1024**3,
                "scope": "declared-preflight-not-os-enforced"},
              "before": artifact_state(model, worker, engine, summary["native_engine_files"])}
    command = [worker["path"], "--engine-dir", summary["native_engine_directory"], "--model", model["path"],
               "--threads", "4", "--context", "512", "--batch", "128"]
    record["command"] = command
    transport = runtime = seed = server = thread = None
    failure = None
    try:
        transport = NativeTransport(command, directory)
        record["ready"] = transport.ready
        if transport.ready.get("engine_commit") != assets.COMMIT:
            raise RuntimeError("runtime-worker-engine-commit")
        runtime = NativeRuntime(transport.exchange, transport.ready, plan=MurphyPlan(mode=mode))
        prepared = runtime.prepare()
        record["warmup"] = prepared["warmup"]
        record["preparation"] = {"load_wall_s": transport.load_wall_s, "warmup_wall_s": prepared["wall_s"],
                                 "preparation_s": transport.load_wall_s + prepared["wall_s"]}
        identity_material = {"engine_identity": engine["engine_identity"], "worker_sha256": worker["sha256"],
                             "model_sha256": model["sha256"], "config": summary["config"]}
        record["seed_identity"] = sha256(encoded(identity_material)).hexdigest()
        audit = Audit(directory / "audit")
        seed = RuntimeSeedEngine(runtime, model=ALIAS, identity=record["seed_identity"], cache_entries=0, cache_bytes=0,
                          event_sink=lambda event: audit.append("scheduler", event))
        if serve:
            server = SeedHTTPServer(("127.0.0.1", port), seed, audit, tensor_backend="libllama-c-api")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            save(directory / "ready.json", {"port": port, "alias": ALIAS, "mode": mode})
            print(json.dumps({"state": "READY", "url": f"http://127.0.0.1:{port}/v1", "alias": ALIAS, "directory": str(directory)}), flush=True)
            while True:
                time.sleep(.2)
        else:
            for name, prompt in CASES:
                seed_response = seed.complete(request(prompt))
                record["requests"].append({"case": name, **runtime.last, "seed_response": seed_response})
                print(json.dumps({"phase": index, "mode": mode, "case": name,
                                  "text": runtime.last["response"]["text"], "wall_s": runtime.last["wall_s"]}, ensure_ascii=False), flush=True)
        record["seed_status"] = seed.status()
    except KeyboardInterrupt:
        if not serve:
            failure = "KeyboardInterrupt"
    except BaseException as exc:
        failure = type(exc).__name__ + ":" + str(exc)[:512]
    finally:
        def finish_step(label, action):
            nonlocal failure
            try:
                return action()
            except BaseException as exc:
                detail = label + ":" + type(exc).__name__ + ":" + str(exc)[:256]
                failure = failure or detail
                record.setdefault("cleanup_errors", []).append(detail)
                return None

        if server is not None:
            if thread is not None and thread.is_alive():
                finish_step("http-shutdown", server.shutdown)
            finish_step("http-close", server.server_close)
            if thread is not None and thread.ident is not None:
                finish_step("http-thread-join", lambda: thread.join(timeout=5))
                if thread.is_alive():
                    failure = failure or "http-thread-still-alive"
        if seed is not None:
            if "seed_status" not in record:
                record["seed_status"] = finish_step("seed-status", seed.status)
            finish_step("seed-close", seed.close)
        if runtime is not None and transport is not None:
            record["shutdown"] = finish_step("runtime-shutdown", runtime.shutdown)
        if transport is not None:
            finish_step("transport-close", transport.close)
            record["cleanup"] = transport.cleanup
        record["after"] = finish_step("after-artifact-hashes", lambda:
            artifact_state(model, worker, engine, summary["native_engine_files"]))
        record["source_unchanged"] = finish_step("after-source-hashes", lambda:
            all(assets.file_sha256(REPO / item["path"]) == item["sha256"] for item in summary["source"]["files"]))
        record["files"] = {}
        for key, name in (("stdin", "stdin.jsonl"), ("stdout", "stdout.jsonl"), ("stderr", "stderr.log")):
            if (directory / name).exists():
                record["files"][key] = finish_step("record-" + key, lambda name=name: file_record(directory / name))
        record["error"] = failure
        save(directory / "phase.json", record)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("smoke", "serve"), default="smoke")
    for option in ("worker-exe", "build-receipt", "asset-root", "model-file", "storage-root"):
        parser.add_argument("--" + option, required=True)
    parser.add_argument("--repeat", type=int, choices=(1, 2), default=2)
    parser.add_argument("--port", type=int, default=18981)
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("owned native runtime currently supports Windows CPU only")
    worker, build = file_record(args.worker_exe), file_record(args.build_receipt)
    model = file_record(args.model_file)
    if model["bytes"] != MODEL_BYTES or model["sha256"] != MODEL_SHA:
        raise ValueError("runtime-model-profile-pin")
    engine = assets.prepare_assets(args.asset_root, download=False)
    receipt = checked_build(build, worker, engine)
    root = local_root(local_root(args.storage_root) / "runs") / str(uuid4())
    root.mkdir()
    summary = {"schema_version": 1, "scope": "runtime-murphy-cpu-smoke" if args.mode == "smoke" else "runtime-murphy-cpu-serve",
               "run_id": root.name, "created_at_utc": datetime.now(timezone.utc).isoformat(),
               "outcome": "FAILED", "error": None, "config": configuration(args.repeat), "model": model,
               "worker": worker, "build_receipt": build, "engine": engine,
               "native_engine_directory": receipt["engine_directory"], "native_engine_files": receipt["engine_files"],
               "source": source_records(root), "phases": [],
               "results_scope": {"quality_verified": False, "speedup_guaranteed": False, "weight_repacked": False,
                                 "native_mtp": False, "os_memory_limit_enforced": False, "gpu_tested": False}}
    print(json.dumps({"run_directory": str(root)}), flush=True)
    order = ["murphy"] if args.mode == "serve" else summary["config"]["mode_order"]
    for index, mode in enumerate(order):
        try:
            result = phase(root, index, mode, summary, serve=args.mode == "serve", port=args.port)
        except BaseException as exc:
            summary["error"] = type(exc).__name__ + ":" + str(exc)[:512]
            break
        summary["phases"].append(result)
        if result["error"]:
            summary["error"] = result["error"]
            break
    if not summary["error"]:
        summary["outcome"] = "COMPLETED"
    save(root / "summary.json", summary)
    print(json.dumps({"outcome": summary["outcome"], "error": summary["error"], "summary": str(root / "summary.json")}), flush=True)
    return 0 if summary["outcome"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
