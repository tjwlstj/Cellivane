#!/usr/bin/env python3
"""Replay Murphy calibration and startup-choice records independently.

The frozen 0.1 raw reader owns the recorded native execution replay. This
reader adds envelope/source/host-profile joins and independent cost arithmetic;
it never imports the policy producer, launcher or runtime implementation.
Matching host facts are recorded compatibility metadata, not host attestation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from hashlib import sha256
import json
import math
from pathlib import Path
from uuid import UUID
import zipfile

import verify_cellivane_runtime as runtime
from verify_cellivane_comparison import check, digest, hex_digest, integer, keys, load, raw_file, same

CONTROLLER_PATHS = {"hosted/experimental/cellivane_murphy_policy/" + name + ".py" for name in ("__init__", "policy")} | {
    "tools/hosted/" + name + ".py" for name in ("cellivane_murphy_lab", "verify_cellivane_murphy", "verify_cellivane_runtime",
        "verify_cellivane_speculation", "verify_cellivane_comparison", "verify_cellivane_bridge")}
IDENTITY_FIELDS = ("runtime_source_sha256", "controller_source_sha256", "model_sha256", "worker_sha256",
    "build_receipt_sha256", "engine_identity")
BASELINE_REASONS = {"no-calibration", "legacy-no-host", "source-mismatch", "identity-mismatch",
    "host-profile-mismatch", "calibration-expired", "output-mismatch"}
OUTPUT_FIELDS = ("text", "tokens", "prompt_tokens", "completion_tokens", "finish_reason", "rendered_prompt_sha256")


def timestamp(value):
    check(type(value) is str and 1 <= len(value) <= 64, "utc-timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("utc-timestamp") from exc
    check(parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0), "utc-timestamp")
    return parsed


def identifier(value):
    check(type(value) is str, "run-id")
    try:
        check(str(UUID(value)) == value, "run-id")
    except ValueError as exc:
        raise ValueError("run-id") from exc


def host(value):
    keys(value, ("schema_version", "scope", "os", "os_version", "machine", "cpu_name", "cpu_vendor",
        "logical_processors", "physical_memory_bytes"), "host-fields")
    check(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["os"] == "Windows"
        and value["scope"] == "local-nonidentifying-host-profile-not-attestation", "host-scope")
    for field, maximum in (("os_version", 128), ("machine", 128), ("cpu_name", 256), ("cpu_vendor", 256)):
        check(type(value[field]) is str and 1 <= len(value[field]) <= maximum
            and not any(ord(c) < 32 for c in value[field]), "host-string")
    check(integer(value["logical_processors"], 1, 4097) and integer(value["physical_memory_bytes"], 1), "host-integer")


def controller_source(value, run_root):
    keys(value, ("root", "files", "scope"), "controller-source-fields")
    runtime.absolute(value["root"])
    check(value["scope"] == "declared-policy-controller-reader-source" and type(value["files"]) is list
        and len(value["files"]) == len(CONTROLLER_PATHS), "controller-source-family")
    found = {}
    for row in value["files"]:
        keys(row, ("path", "bytes", "sha256", "snapshot"), "controller-source-file-fields")
        name = row["path"]
        check(type(name) is str and name in CONTROLLER_PATHS and name not in found
            and row["snapshot"] == "controller-source-snapshot/" + name
            and integer(row["bytes"], 1, 4 * 1024**2 + 1) and hex_digest(row["sha256"]), "controller-source-file")
        raw = raw_file(run_root / row["snapshot"], 4 * 1024**2)
        check(len(raw) == row["bytes"] and sha256(raw).hexdigest() == row["sha256"], "controller-source-snapshot-changed")
        found[name] = row["sha256"]
    check(set(found) == CONTROLLER_PATHS, "controller-source-missing")
    return digest(found)


def count(value):
    check(integer(value, 1, 1025), "expected-requests")
    return value


def seconds(value, *, positive=False):
    check(type(value) in (int, float) and 0 <= value <= 3600 and math.isfinite(value)
        and (not positive or value > 0), "calibration-seconds")
    return float(value)


def normalized_rounds(summary):
    phases = summary["phases"]
    rounds = []
    for none_index, murphy_index in ((0, 1), (3, 2)):
        row = {}
        for mode, index in (("none", none_index), ("murphy", murphy_index)):
            phase = phases[index]
            check(phase["mode"] == mode and len(phase["requests"]) == 2, "calibration-round-pair")
            row[mode] = {"preparation_s": seconds(phase["preparation"]["preparation_s"]),
                "request_wall_s": [seconds(item["wall_s"], positive=True) for item in phase["requests"]]}
        rounds.append(row)
    return rounds


def outputs_equal(summary):
    observed = {}
    for phase in summary["phases"]:
        for row in phase["requests"]:
            value = {field: row["response"][field] for field in OUTPUT_FIELDS}
            if row["case"] in observed and not same(observed[row["case"]], value):
                return False
            observed[row["case"]] = value
    return True


def _verified_calibration(path, raw):
    envelope = load(raw)
    keys(envelope, ("schema_version", "artifact_family", "run_id", "created_at_utc", "outcome", "error", "host_before",
        "host_after", "runtime_summary", "runtime_replay", "controller_source", "controller_after_sha256"), "calibration-fields")
    check(type(envelope["schema_version"]) is int and envelope["schema_version"] == 1
        and envelope["artifact_family"] == "cellivane-murphy-calibration-v1"
        and envelope["outcome"] == "COMPLETED" and envelope["error"] is None, "calibration-not-completed")
    identifier(envelope["run_id"])
    timestamp(envelope["created_at_utc"])
    host(envelope["host_before"])
    host(envelope["host_after"])
    check(same(envelope["host_before"], envelope["host_after"]), "calibration-host-changed")
    summary_raw = runtime.artifact(envelope["runtime_summary"], 16 * 1024**2)
    summary = load(summary_raw)
    replayed = runtime.replay(envelope["runtime_summary"]["path"], None)
    check(replayed.get("verdict") == "PASS" and same(replayed, envelope["runtime_replay"]), "calibration-raw-replay-join")
    # A second byte check detects ordinary mutation while replay opened the file.
    check(runtime.artifact(envelope["runtime_summary"], 16 * 1024**2) == summary_raw, "calibration-summary-changed")
    controller_sha = controller_source(envelope["controller_source"], path.parent)
    check(hex_digest(envelope["controller_after_sha256"]) and envelope["controller_after_sha256"] == controller_sha,
        "calibration-controller-changed")
    source_sha = digest({row["path"]: row["sha256"] for row in summary["source"]["files"]})
    return {"envelope": envelope, "summary": summary, "rounds": normalized_rounds(summary), "outputs_equal": outputs_equal(summary),
        "runtime_source_sha256": source_sha, "controller_source_sha256": controller_sha}


def verified_calibration(path):
    """Validate a new envelope plus frozen 0.1 raw evidence, never a PASS label."""
    path = runtime.absolute(str(path))
    return _verified_calibration(path, raw_file(path, 16 * 1024**2))


def baseline(expected_requests, reason):
    check(type(reason) is str and reason in BASELINE_REASONS, "baseline-reason")
    return {"schema_version": 1, "policy": "murphy-session-cost-v1", "expected_requests": count(expected_requests),
        "margin_percent": 5, "eligible": False, "selected_mode": "none", "reason": reason,
        "rounds": [], "scope": "fixed-calibration-corpus-cost-estimate"}


def arithmetic(rounds, expected_requests):
    amount = count(expected_requests)
    check(type(rounds) is list and len(rounds) == 2, "arithmetic-rounds")
    result = []
    for index, row in enumerate(rounds):
        keys(row, ("none", "murphy"), "arithmetic-round-fields")
        costs = {}
        for mode in ("none", "murphy"):
            keys(row[mode], ("preparation_s", "request_wall_s"), "arithmetic-mode-fields")
            walls = row[mode]["request_wall_s"]
            check(type(walls) is list and len(walls) == 2, "arithmetic-requests")
            mean = sum(seconds(value, positive=True) for value in walls) / 2
            preparation = seconds(row[mode]["preparation_s"])
            costs[mode] = {"preparation_s": preparation, "mean_request_s": mean,
                "estimated_session_s": preparation + amount * mean}
        none_cost, warm_cost = costs["none"]["estimated_session_s"], costs["murphy"]["estimated_session_s"]
        result.append({"index": index, **costs, "qualifies": warm_cost <= .95 * none_cost and warm_cost < none_cost})
    chosen = all(row["qualifies"] for row in result)
    return {"schema_version": 1, "policy": "murphy-session-cost-v1", "expected_requests": amount,
        "margin_percent": 5, "eligible": True, "selected_mode": "murphy" if chosen else "none",
        "reason": "consistent-session-savings" if chosen else "insufficient-consistent-savings",
        "rounds": result, "scope": "fixed-calibration-corpus-cost-estimate"}


def current_source(root, identity):
    root = runtime.absolute(str(root))
    for field, names in (("runtime_source_sha256", runtime.SOURCE_PATHS), ("controller_source_sha256", CONTROLLER_PATHS)):
        hashes = {name: sha256(raw_file(root / name, 4 * 1024**2)).hexdigest() for name in names}
        check(digest(hashes) == identity[field], "choice-current-source-mismatch")


def evaluate_choice(choice_path, source_root=None):
    path = runtime.absolute(str(choice_path))
    choice = load(raw_file(path, 16 * 1024**2))
    keys(choice, ("schema_version", "artifact_family", "run_id", "created_at_utc", "context", "calibration", "decision"), "choice-fields")
    check(type(choice["schema_version"]) is int and choice["schema_version"] == 1
        and choice["artifact_family"] == "cellivane-murphy-choice-v1", "choice-family")
    identifier(choice["run_id"])
    made = timestamp(choice["created_at_utc"])
    keys(choice["context"], ("host", "identity"), "choice-context-fields")
    host(choice["context"]["host"])
    identity = choice["context"]["identity"]
    keys(identity, IDENTITY_FIELDS, "choice-identity-fields")
    check(all(hex_digest(identity[field]) for field in IDENTITY_FIELDS), "choice-identity-digest")
    if source_root is not None:
        current_source(source_root, identity)
    check(type(choice["decision"]) is dict and "expected_requests" in choice["decision"], "choice-decision")
    expected_requests = count(choice["decision"]["expected_requests"])
    if choice["calibration"] is None:
        expected = baseline(expected_requests, "no-calibration")
    else:
        raw = runtime.artifact(choice["calibration"], 16 * 1024**2)
        provided = load(raw)
        check(type(provided) is dict, "calibration-object-required")
        if provided.get("scope") == "runtime-murphy-cpu-smoke":
            replayed = runtime.replay(choice["calibration"]["path"], None)
            check(replayed.get("verdict") == "PASS", "legacy-calibration-replay")
            check(runtime.artifact(choice["calibration"], 16 * 1024**2) == raw, "calibration-summary-changed")
            expected = baseline(expected_requests, "legacy-no-host")
        else:
            candidate = _verified_calibration(runtime.absolute(choice["calibration"]["path"]), raw)
            envelope, summary = candidate["envelope"], candidate["summary"]
            if any(identity[field] != candidate[field] for field in ("runtime_source_sha256", "controller_source_sha256")):
                reason = "source-mismatch"
            elif any(identity[field] != value for field, value in (("model_sha256", summary["model"]["sha256"]),
                    ("worker_sha256", summary["worker"]["sha256"]), ("build_receipt_sha256", summary["build_receipt"]["sha256"]),
                    ("engine_identity", summary["engine"]["engine_identity"]))):
                reason = "identity-mismatch"
            elif not same(choice["context"]["host"], envelope["host_before"]):
                reason = "host-profile-mismatch"
            elif not 0 <= (made - timestamp(envelope["created_at_utc"])).total_seconds() <= 86400:
                reason = "calibration-expired"
            elif not candidate["outputs_equal"]:
                reason = "output-mismatch"
            else:
                reason = None
            expected = baseline(expected_requests, reason) if reason else arithmetic(candidate["rounds"], expected_requests)
    check(same(choice["decision"], expected), "choice-decision-recompute")
    return {"verdict": "PASS", "scope": "recorded-murphy-choice-arithmetic-and-calibration-integrity",
        "run_id": choice["run_id"], "selected": expected["selected_mode"], "reason": expected["reason"], "eligible": expected["eligible"],
        "context_scope": "current-source-files-compared" if source_root is not None else "declared-context-not-current-source-attestation",
        "claims": {"host_attestation": False, "future_workload_speedup_guaranteed": False,
            "live_launch_or_tensor_execution_verified": False, "os_resource_reservation": False}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("choice")
    parser.add_argument("--source-root")
    args = parser.parse_args(argv)
    try:
        result = evaluate_choice(args.choice, args.source_root)
    except (ValueError, KeyError, TypeError, AttributeError, OSError, UnicodeError, zipfile.BadZipFile) as exc:
        result = {"verdict": "FAIL", "scope": "recorded-murphy-choice-arithmetic-and-calibration-integrity",
            "error": type(exc).__name__ + ":" + str(exc)[:512]}
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
