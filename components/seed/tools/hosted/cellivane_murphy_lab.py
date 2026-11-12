#!/usr/bin/env python3
"""Explicit calibration and conservative preparation selection for the CPU runtime.

Calibration is a separate, costly operation. Plan never launches a worker.
The selected mode is fixed before execution; supplied corrupt evidence blocks
launch. Estimates describe two fixed calibration prompts, not future workload.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import platform
import sys
from uuid import uuid4

import cellivane_runtime_lab as runtime
import verify_cellivane_runtime as raw_verifier
import verify_cellivane_murphy as verifier
from cellivane_murphy_policy import baseline, choose

REPO = runtime.REPO
CONTROLLER_PATHS = {
    "hosted/experimental/cellivane_murphy_policy/__init__.py",
    "hosted/experimental/cellivane_murphy_policy/policy.py",
    *{"tools/hosted/" + name + ".py" for name in (
        "cellivane_murphy_lab", "verify_cellivane_murphy", "verify_cellivane_runtime",
        "verify_cellivane_speculation", "verify_cellivane_comparison", "verify_cellivane_bridge")},
}


def digest(value):
    return sha256(runtime.encoded(value)).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def host_profile():
    if os.name != "nt":
        raise ValueError("murphy-host-windows-only")
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
        name = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        vendor = winreg.QueryValueEx(key, "VendorIdentifier")[0].strip()
    return {"schema_version": 1, "scope": "local-nonidentifying-host-profile-not-attestation",
            "os": "Windows", "os_version": platform.version(), "machine": platform.machine(),
            "cpu_name": name, "cpu_vendor": vendor, "logical_processors": os.cpu_count(),
            "physical_memory_bytes": runtime.memory_snapshot()["total_bytes"]}


def controller_hashes():
    return {name: runtime.assets.file_sha256(REPO / name) for name in sorted(CONTROLLER_PATHS)}


def runtime_hashes():
    return {name: runtime.assets.file_sha256(REPO / name) for name in sorted(raw_verifier.SOURCE_PATHS)}


def snapshot_controller(root):
    files = []
    for name in sorted(CONTROLLER_PATHS):
        data = (REPO / name).read_bytes()
        snapshot = "controller-source-snapshot/" + name
        target = root / snapshot
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
        files.append({"path": name, "bytes": len(data), "sha256": sha256(data).hexdigest(), "snapshot": snapshot})
    return {"root": str(REPO), "files": files, "scope": "declared-policy-controller-reader-source"}


def checked_runtime(args):
    model, worker, build = (runtime.file_record(value) for value in
                             (args.model_file, args.worker_exe, args.build_receipt))
    if model["bytes"] != runtime.MODEL_BYTES or model["sha256"] != runtime.MODEL_SHA:
        raise ValueError("murphy-model-profile-pin")
    engine = runtime.assets.prepare_assets(args.asset_root, download=False)
    receipt = runtime.checked_build(build, worker, engine)
    return {"model": model, "worker": worker, "build_receipt": build, "engine": engine,
            "native_engine_directory": receipt["engine_directory"], "native_engine_files": receipt["engine_files"],
            "config": runtime.configuration(2)}


def context_for(base):
    return {"host": host_profile(), "identity": {
        "runtime_source_sha256": digest(runtime_hashes()),
        "controller_source_sha256": digest(controller_hashes()),
        "model_sha256": base["model"]["sha256"], "worker_sha256": base["worker"]["sha256"],
        "build_receipt_sha256": base["build_receipt"]["sha256"],
        "engine_identity": base["engine"]["engine_identity"]}}


def decide(reference, context, created_at, expected_requests):
    # Validate the caller's horizon even when no calibration was supplied.
    default = baseline(expected_requests, "no-calibration")
    if reference is None:
        return default
    record = runtime.read_json(reference["path"], 4 * 1024**2)
    if record.get("scope") == "runtime-murphy-cpu-smoke" and "artifact_family" not in record:
        raw_verifier.replay(reference["path"])
        return baseline(expected_requests, "legacy-no-host")
    observed = verifier.verified_calibration(reference["path"])
    envelope, summary = observed["envelope"], observed["summary"]
    identity = context["identity"]
    if (identity["runtime_source_sha256"] != observed["runtime_source_sha256"]
            or identity["controller_source_sha256"] != observed["controller_source_sha256"]):
        return baseline(expected_requests, "source-mismatch")
    if any(identity[key] != actual for key, actual in (
            ("model_sha256", summary["model"]["sha256"]), ("worker_sha256", summary["worker"]["sha256"]),
            ("build_receipt_sha256", summary["build_receipt"]["sha256"]),
            ("engine_identity", summary["engine"]["engine_identity"]))):
        return baseline(expected_requests, "identity-mismatch")
    if context["host"] != envelope["host_before"]:
        return baseline(expected_requests, "host-profile-mismatch")
    age = (datetime.fromisoformat(created_at) - datetime.fromisoformat(envelope["created_at_utc"])).total_seconds()
    if not 0 <= age <= 86400:
        return baseline(expected_requests, "calibration-expired")
    if not observed["outputs_equal"]:
        return baseline(expected_requests, "output-mismatch")
    return choose(observed["rounds"], expected_requests)


def root_for(args, kind):
    directory = runtime.local_root(runtime.local_root(args.storage_root) / "murphy" / kind) / str(uuid4())
    directory.mkdir()
    return directory


def calibrate(args, base):
    root = root_for(args, "calibrations")
    record = {"schema_version": 1, "artifact_family": "cellivane-murphy-calibration-v1",
              "run_id": root.name, "created_at_utc": utc_now(), "outcome": "FAILED", "error": None}
    output = io.StringIO()
    try:
        record["controller_source"] = snapshot_controller(root)
        record["host_before"] = host_profile()
        argv = ["--mode", "smoke", "--repeat", "2"]
        for key in ("worker_exe", "build_receipt", "asset_root", "model_file", "storage_root"):
            argv.extend(["--" + key.replace("_", "-"), str(getattr(args, key))])
        with redirect_stdout(output):
            status = runtime.main(argv)
        summary_path = json.loads(output.getvalue().splitlines()[-1])["summary"]
        record["runtime_summary"] = runtime.file_record(summary_path)
        record["host_after"] = host_profile()
        record["controller_after_sha256"] = digest(controller_hashes())
        if status != 0 or record["host_before"] != record["host_after"]:
            raise RuntimeError("murphy-calibration-execution-or-host-change")
        if record["controller_after_sha256"] != digest({row["path"]: row["sha256"] for row in record["controller_source"]["files"]}):
            raise RuntimeError("murphy-controller-changed-during-calibration")
        record["runtime_replay"] = raw_verifier.replay(summary_path, REPO)
        observed_summary = runtime.read_json(summary_path, 4 * 1024**2)
        if any(observed_summary[key] != base[key] for key in ("model", "worker", "build_receipt", "engine")):
            raise RuntimeError("murphy-calibration-runtime-identity-changed")
        record["outcome"] = "COMPLETED"
    except BaseException as exc:
        record["error"] = type(exc).__name__ + ":" + str(exc)[:512]
    (root / "runtime-console.jsonl").write_text(output.getvalue(), encoding="utf-8")
    path = root / "calibration.json"
    runtime.save(path, record)
    qualification = {"verdict": "FAIL", "scope": "recorded-murphy-calibration-integrity", "error": record["error"]}
    if record["outcome"] == "COMPLETED":
        try:
            verifier.verified_calibration(path)
            qualification.update(verdict="PASS", error=None)
        except Exception as exc:
            qualification["error"] = type(exc).__name__ + ":" + str(exc)[:512]
    runtime.save(root / "calibration-verdict.json", qualification)
    print(json.dumps({"outcome": record["outcome"], "qualification": qualification["verdict"],
                      "error": qualification["error"], "calibration": str(path)}), flush=True)
    return 0 if qualification["verdict"] == "PASS" else 1


def selected_run(args, base):
    root = root_for(args, "choices")
    created_at = utc_now()
    try:
        source = runtime.source_records(root)
        controller = snapshot_controller(root)
        context = context_for(base)
        for field, snapshot in (("runtime_source_sha256", source), ("controller_source_sha256", controller)):
            if digest({row["path"]: row["sha256"] for row in snapshot["files"]}) != context["identity"][field]:
                raise RuntimeError("murphy-source-changed-during-snapshot")
        reference = runtime.file_record(args.calibration) if args.calibration is not None else None
        decision = decide(reference, context, created_at, args.expected_requests)
        choice = {"schema_version": 1, "artifact_family": "cellivane-murphy-choice-v1", "run_id": root.name,
                  "created_at_utc": created_at, "context": context, "calibration": reference, "decision": decision}
        path = root / "choice.json"
        runtime.save(path, choice)
        verdict = verifier.evaluate_choice(path, REPO)
        runtime.save(root / "choice-verdict.json", verdict)
        if verdict["verdict"] != "PASS":
            raise RuntimeError("murphy-choice-replay-failed")
        print(json.dumps({"choice": str(path), "selected_mode": decision["selected_mode"],
                          "reason": decision["reason"], "eligible": decision["eligible"],
                          "expected_requests": args.expected_requests}), flush=True)
        if args.mode == "plan":
            return 0
        if context_for(base) != context:
            raise RuntimeError("murphy-context-changed-before-launch")
        if checked_runtime(args) != base:
            raise RuntimeError("murphy-runtime-artifacts-changed-before-launch")
    except Exception as exc:
        runtime.save(root / "blocked.json", {"outcome": "BLOCKED", "error": type(exc).__name__ + ":" + str(exc)[:512],
                                            "native_dispatch_started": False})
        print(json.dumps({"outcome": "BLOCKED", "directory": str(root), "error": type(exc).__name__}), flush=True)
        return 1
    summary = {**base, "source": source}
    phase, error = None, None
    try:
        phase = runtime.phase(root, 0, decision["selected_mode"], summary, serve=args.mode == "serve", port=args.port)
        error = phase["error"]
    except BaseException as exc:
        error = type(exc).__name__ + ":" + str(exc)[:512]
    try:
        controller_unchanged = controller_hashes() == {row["path"]: row["sha256"] for row in controller["files"]}
    except Exception as exc:
        controller_unchanged = False
        error = error or "controller-recheck:" + type(exc).__name__
    outcome = "COMPLETED" if error is None and controller_unchanged else "FAILED"
    runtime.save(root / "execution.json", {"outcome": outcome, "error": error,
        "choice": runtime.file_record(path), "phase": phase,
        "controller_source": controller, "controller_source_unchanged": controller_unchanged,
        "scope": "selected-mode-functional-observation-not-independent-execution-replay"})
    print(json.dumps({"outcome": outcome, "execution": str(root / "execution.json")}), flush=True)
    return 0 if outcome == "COMPLETED" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("calibrate", "plan", "smoke", "serve"), default="plan")
    for option in ("worker-exe", "build-receipt", "asset-root", "model-file", "storage-root"):
        parser.add_argument("--" + option, required=True)
    parser.add_argument("--calibration")
    parser.add_argument("--expected-requests", type=int, default=1)
    parser.add_argument("--port", type=int, default=18982)
    args = parser.parse_args(argv)
    if not 1 <= args.expected_requests <= 1024:
        parser.error("expected requests must be 1..1024")
    if not 1024 <= args.port <= 65535:
        parser.error("port must be 1024..65535")
    if args.mode == "calibrate" and args.calibration is not None:
        parser.error("calibrate creates a new companion; do not supply calibration")
    base = checked_runtime(args)
    return calibrate(args, base) if args.mode == "calibrate" else selected_run(args, base)


if __name__ == "__main__":
    raise SystemExit(main())
