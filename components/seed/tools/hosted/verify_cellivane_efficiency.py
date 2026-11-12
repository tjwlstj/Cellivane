#!/usr/bin/env python3
"""Independent single-run replay for measured Cellivane efficiency profiles.

Only independent historical readers are imported. No producer, runtime, profile
validator or incremental cursor is imported. PASS concerns recorded integrity
and bounded scan work; it does not select a hardware winner or prove speedup.
"""
from __future__ import annotations

import argparse
import codecs
from datetime import datetime, timedelta
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import statistics
from uuid import UUID
import zipfile

import verify_cellivane_soak as soak
from verify_cellivane_comparison import check, digest, encoded, hex_digest, integer, keys, load, number, raw_file, same

comparison = soak.comparison
MODEL = dict(soak.MODELS["8b-q4"])
SOURCE_PATHS = soak.SOURCE_PATHS | {"tools/hosted/cellivane_seed_optimize.py",
    "tools/hosted/cellivane_log_cursor.py", "hosted/experimental/cellivane_seed/efficiency.py"}
PROFILE_SETTINGS = {"reference": (21, 4), "gpu29": (29, 4), "gpu29-threads8": (29, 8)}
BASELINE_SUMMARY_SHA256 = "bc92e826895eef371028a64f101408776f741aa16d04736e1b85b8a11366cd7f"
REFERENCE_SIZE_VRAM_BYTES = 3100597288
GIB = 1024**3
SCOPE = "recorded-efficiency-single-run-integrity-and-bounded-log-work"
VERIFICATION_PATHS = {"tools/hosted/" + name + ".py" for name in
    ("verify_cellivane_efficiency", "verify_cellivane_soak", "verify_cellivane_comparison", "verify_cellivane_bridge")}
MATRIX_ORDER = ("reference", "gpu29", "gpu29-threads8", "gpu29-threads8", "gpu29", "reference")
MATRIX_SCOPE = {"input_order": "caller-declared-ABC-CBA-order-not-clock-attestation",
    "integrity": "local-unkeyed-record-and-reader-receipt-joins-not-host-attestation",
    "selection": "measured-selection-for-this-model-backend-host-only", "final_soak_completed": False,
    "full_regression_completed": False}
SUMMARY_KEYS = ("schema_version", "family", "run_id", "mode", "outcome", "error", "acceptance", "acceptance_errors",
    "duration_s", "minimum_responses", "repeat", "profile", "requested_profile", "selection", "host_profile", "audit_timings", "log_polls", "guards", "model_profile", "model",
    "rows", "cases", "system", "corpus_sha256", "source", "ports", "cleanup", "measurement_scope", "model_file", "preflight",
    "budget", "backend", "launch_probe", "alias", "plan", "configuration", "identity", "keep_alive", "version", "modelfile",
    "audit_directory", "warmup", "loaded_models_ready", "startup_log", "placement", "oversize", "service_start_s", "service_end_s",
    "bridge_report", "loaded_models_end", "state", "audit_status", "telemetry", "telemetry_errors", "resource_guard_reason",
    "cleanup_errors", "ports_closed", "model_unchanged", "source_unchanged", "backend_unchanged", "log", "metrics")


def profile_record(name):
    check(type(name) is str and name in PROFILE_SETTINGS, "unknown-efficiency-profile")
    layers, threads = PROFILE_SETTINGS[name]
    return {"schema_version": 1, "name": name, "backend": "ollama", "num_gpu": layers, "num_thread": threads,
        "context_tokens": 2048, "slots": 1, "temperature": 0, "flash_attention": "auto", "kv_cache_type": "f16",
        "ollama_options": {"num_gpu": layers, "num_thread": threads, "num_ctx": 2048, "temperature": 0},
        "environment": {"OLLAMA_KV_CACHE_TYPE": "f16"}, "unset_environment": ["OLLAMA_FLASH_ATTENTION"],
        "model_bytes": MODEL["bytes"], "model_sha256": MODEL["sha256"], "scope": "fixed-8b-requested-efficiency-profile-only"}


def forecast(profile, observation):
    available, free = observation["memory"]["available_bytes"], observation["gpu"]["free_bytes"]
    numerator = max(0, profile["num_gpu"] - 21) * MODEL["bytes"] * 115
    incremental = (numerator + 3699) // 3700
    predicted = REFERENCE_SIZE_VRAM_BYTES + incremental + 256 * 1024**2
    ram_required, vram_required = MODEL["bytes"] + 7 * GIB, predicted + GIB
    reasons = []
    if available < ram_required:
        reasons.append("insufficient-available-ram")
    if free < vram_required:
        reasons.append("insufficient-free-vram")
    return {"schema_version": 1, "profile_sha256": digest(profile), "model_bytes": MODEL["bytes"],
        "baseline_summary_sha256": BASELINE_SUMMARY_SHA256, "reference_layers": 21, "total_layers": 37,
        "reference_size_vram_bytes": REFERENCE_SIZE_VRAM_BYTES, "incremental_layer_estimate_bytes": incremental,
        "layer_estimate_safety_factor": 1.15, "runtime_allowance_bytes": 256 * 1024**2,
        "ram_overhead_bytes": 7 * GIB, "vram_headroom_bytes": GIB, "ram_required_bytes": ram_required,
        "vram_forecast_bytes": predicted, "vram_required_free_bytes": vram_required,
        "available_ram_bytes": available, "free_vram_bytes": free, "admitted": not reasons, "reasons": reasons,
        "scope": "baseline-observation-derived-advisory-not-reservation-or-fit-proof"}


def verify_sources(value, directory, source_root=None):
    keys(value, ("root", "sha256", "scope"), "source-fields")
    soak.absolute(value["root"])
    hashes = value["sha256"]
    check(value["scope"] == "declared-21-file-efficiency-family-not-loader-attestation" and type(hashes) is dict
        and set(hashes) == SOURCE_PATHS and all(hex_digest(item) for item in hashes.values()), "efficiency-source-family")
    for name, expected in hashes.items():
        raw = raw_file(directory / "source-snapshot" / name, 4 * 1024**2)
        check(sha256(raw).hexdigest() == expected, "source-snapshot-changed")
        if source_root is not None:
            check(raw_file(soak.absolute(str(source_root)) / name, 4 * 1024**2) == raw, "current-source-changed")


def verify_configuration(summary, source_root=None, matrix_receipt=None):
    profile = summary["profile"]
    check(type(profile) is dict, "efficiency-profile-type")
    expected = profile_record(profile.get("name"))
    check(same(profile, expected) and same(summary["plan"], expected), "efficiency-profile-contract")
    launch = soak.resource_evidence(summary["launch_probe"])
    host = summary["host_profile"]
    keys(host, ("logical_processors", "ram_total_bytes", "gpu"), "host-profile-fields")
    check(integer(host["logical_processors"], expected["num_thread"], 4097)
        and type(host["ram_total_bytes"]) is int and host["ram_total_bytes"] == launch["memory"]["total_bytes"]
        and same(host["gpu"], {name: launch["gpu"][name] for name in ("index", "name", "driver_version", "total_bytes")}),
        "host-profile-observation-join")
    requested, selection = summary["requested_profile"], summary["selection"]
    check(type(requested) is str and requested in {"auto", *PROFILE_SETTINGS}, "requested-profile")
    if requested == "auto":
        if same(selection, {"mode": "reference-default", "artifact": None}):
            check(expected["name"] == "reference", "reference-default-profile")
        else:
            keys(selection, ("mode", "artifact", "decision", "host_profile", "identity"), "calibrated-selection-fields")
            check(selection["mode"] == "calibrated" and matrix_receipt is not None, "calibrated-selection-requires-matrix-receipt")
            raw_selection = soak.artifact(selection["artifact"], 256 * 1024)
            verified = verify_matrix(selection["artifact"]["path"], matrix_receipt, source_root)
            identity = {"model_sha256": MODEL["sha256"], "backend_tree_sha256": summary["backend"]["tree_sha256"],
                "corpus_sha256": summary["corpus_sha256"], "source_sha256": digest(summary["source"]["sha256"])}
            check(same(verified["host_profile"], host) and same(selection["host_profile"], host)
                and same(verified["identity"], identity) and same(selection["identity"], identity)
                and same(verified["decision"], selection["decision"])
                and same(verified["decision"]["selected_profile"], expected)
                and verified["selection_canonical_sha256"] == digest(load(raw_selection))
                and same(load(raw_selection)["host_profile"], host), "calibrated-selection-current-binding")
    else:
        check(requested == expected["name"] and same(selection, {"mode": "explicit", "artifact": None}), "explicit-selection-binding")
    check(same(summary["budget"], forecast(expected, launch)) and summary["budget"]["admitted"] is True,
        "efficiency-budget-recompute")
    check(forecast(expected, summary["preflight"])["admitted"] is True, "initial-resource-budget")
    check(launch["memory"]["available_bytes"] >= soak.GUARDS["minimum_ram_free_bytes"]
        and launch["gpu"]["free_bytes"] >= soak.GUARDS["minimum_vram_free_bytes"]
        and launch["gpu"]["temperature_c"] < soak.GUARDS["maximum_temperature_c"], "launch-resource-guard")
    alias = "cellivane-efficiency-" + expected["name"] + ":latest"
    configuration = {"schema_version": 1, "alias": alias, "options": expected["ollama_options"],
        "environment": {"CUDA_VISIBLE_DEVICES": "0", "HIP_VISIBLE_DEVICES": "-1", "ROCR_VISIBLE_DEVICES": "-1",
            "OLLAMA_VULKAN": "0", "OLLAMA_NO_CLOUD": "1", "OLLAMA_NUM_PARALLEL": "1", "OLLAMA_MAX_LOADED_MODELS": "1",
            "OLLAMA_CONTEXT_LENGTH": "2048", "OLLAMA_DEBUG": "1", "OLLAMA_KV_CACHE_TYPE": "f16"},
        "unset_environment": ["OLLAMA_FLASH_ATTENTION"], "device_scope": "one visible NVIDIA CUDA GPU; one slot"}
    check(summary["alias"] == alias and same(summary["configuration"], configuration)
        and summary["identity"] == digest({"model_sha256": MODEL["sha256"],
            "backend_tree_sha256": summary["backend"]["tree_sha256"], "configuration": configuration})
        and summary["keep_alive"] == "30m" and same(summary["version"], {"version": soak.OLLAMA_VERSION}), "execution-configuration")
    lines = soak.artifact(summary["modelfile"], 4096).decode("utf-8").splitlines()
    wanted = ['FROM "' + str(soak.absolute(summary["model_file"]["path"])).replace("\\", "/") + '"']
    wanted += [f"PARAMETER {key} {value}" for key, value in expected["ollama_options"].items()]
    check(lines == wanted, "modelfile-binding")
    return expected


def verify_rows(summary):
    mode, duration, rows = summary["mode"], summary["duration_s"], summary["rows"]
    check(mode in ("calibrate", "soak") and type(duration) is int
        and duration == (0 if mode == "calibrate" else 900)
        and type(summary["repeat"]) is int and summary["repeat"] == 4, "efficiency-run-profile")
    minimum = 56 if mode == "calibrate" else 24
    check(type(summary["minimum_responses"]) is int and summary["minimum_responses"] == minimum
        and type(rows) is list and minimum <= len(rows) <= 2048
        and (mode != "calibrate" or len(rows) == 56), "efficiency-corpus-count")
    guards = dict(soak.GUARDS, minimum_start_interval_s=0 if mode == "calibrate" else .5)
    check(same(summary["guards"], guards), "efficiency-guards")
    start, end = summary["service_start_s"], summary["service_end_s"]
    check(number(start) and number(end) and end > start
        and (mode != "soak" or 900 <= end - start <= 1020), "service-window-incomplete-or-drain-overrun")
    base_keys = ("index", "case", "started_s", "completed_s", "wall_s", "receipt_started_s", "receipt_completed_s",
        "receipt_read_s", "response", "backend_exchange_count", "backend_receipt", "exact")
    previous, drains = None, 0
    for index, row in enumerate([summary["warmup"], *rows]):
        keys(row, base_keys if index == 0 else (*base_keys, "phases", "post_complete_s"), "instrumented-row-fields")
        check(all(number(row[name]) for name in ("started_s", "completed_s", "wall_s", "receipt_started_s", "receipt_completed_s", "receipt_read_s"))
            and 0 < row["wall_s"] <= 120
            and abs(row["completed_s"] - row["started_s"] - row["wall_s"]) <= .000001
            and row["receipt_started_s"] == row["completed_s"] and row["receipt_completed_s"] >= row["receipt_started_s"]
            and abs(row["receipt_completed_s"] - row["receipt_started_s"] - row["receipt_read_s"]) <= .000001,
            "instrumented-request-timing")
        raw = row["backend_receipt"]["raw_response"]
        check(all(name in raw and integer(raw[name]) for name in ("total_duration", "prompt_eval_duration", "eval_duration"))
            and raw["total_duration"] > 0 and raw["eval_duration"] > 0
            and raw["total_duration"] / 1e9 <= row["backend_receipt"]["elapsed_s"] + .005, "native-request-timing")
        if index == 0:
            check(type(row["index"]) is int and row["index"] == -1 and row["case"] == "warmup"
                and row["receipt_completed_s"] <= start, "warmup-window")
            continue
        check(type(row["index"]) is int and row["index"] == index - 1
            and row["case"] == soak.CASES[(index - 1) % 14]["id"] and row["started_s"] >= start
            and row["completed_s"] <= end and (mode != "soak" or row["started_s"] < start + 900), "request-admission-window")
        phases = row["phases"]
        keys(phases, ("pacing_started_s", "pacing_completed_s", "pacing_wait_s", "log_started_s", "log_completed_s", "log_wall_s",
            "log_poll_sequence", "progress_write_s"), "instrumented-phase-fields")
        check(all(number(phases[name]) for name in phases if name != "log_poll_sequence")
            and number(row["post_complete_s"]) and phases["pacing_started_s"] >= start
            and phases["pacing_started_s"] <= phases["pacing_completed_s"] <= row["started_s"]
            and abs(phases["pacing_completed_s"] - phases["pacing_started_s"] - phases["pacing_wait_s"]) <= .000001
            and row["receipt_completed_s"] <= phases["log_started_s"] <= phases["log_completed_s"] <= row["post_complete_s"] <= end
            and abs(phases["log_completed_s"] - phases["log_started_s"] - phases["log_wall_s"]) <= .000001
            and phases["progress_write_s"] <= row["post_complete_s"] - phases["log_completed_s"] + .000001
            and type(phases["log_poll_sequence"]) is int and phases["log_poll_sequence"] == index + 1, "instrumented-phase-order-or-duration")
        if previous is None:
            check(row["started_s"] - start <= 10, "continuous-admission-first-gap")
        else:
            check(phases["pacing_started_s"] >= previous["post_complete_s"]
                and row["started_s"] - previous["completed_s"] <= 10
                and row["started_s"] - previous["started_s"] >= guards["minimum_start_interval_s"] - .002,
                "request-overlap-pacing-or-idle-gap")
        drains += mode == "soak" and row["completed_s"] > start + 900
        previous = row
    check(drains <= 1 and end - rows[-1]["completed_s"] <= 10, "service-end-idle-or-multiple-drains")
    return int(drains)


def verify_log_polls(summary):
    raw = soak.artifact(summary["log"], soak.GUARDS["maximum_log_bytes"])
    text = raw.decode("utf-8")
    check(not soak.FATAL.search(text), "fatal-backend-log")
    check(all(len(line) <= 65536 for line in raw.split(b"\n")), "log-line-limit")
    polls = summary["log_polls"]
    check(type(polls) is list and len(polls) == len(summary["rows"]) + 3, "log-poll-count")
    decoder, tail, offset, reads, scanned, prefix = codecs.getincrementaldecoder("utf-8")("strict"), "", 0, 0, 0, sha256()
    for index, poll in enumerate(polls, 1):
        keys(poll, ("seq", "start", "end", "new_bytes", "chunk_sha256", "prefix_sha256", "bytes_read_total", "bytes_scanned_total",
            "carry_bytes", "poll_wall_s", "fatal"), "log-poll-fields")
        check(type(poll["seq"]) is int and poll["seq"] == index and type(poll["start"]) is int and poll["start"] == offset
            and integer(poll["end"], offset, len(raw) + 1) and type(poll["new_bytes"]) is int
            and poll["new_bytes"] == poll["end"] - offset and number(poll["poll_wall_s"]) and poll["poll_wall_s"] > 0
            and poll["fatal"] is False, "log-poll-sequence-or-bound")
        segment = raw[offset:poll["end"]]
        reads += len(segment) + min(offset, 256) + min(poll["end"], 256)
        for begin in range(0, len(segment), 65536):
            chunk = segment[begin:begin + 65536]
            scanned += len(chunk) + len(tail.encode("utf-8"))
            tail = (tail + decoder.decode(chunk, final=False))[-64:]
        prefix.update(segment)
        if index == len(polls):
            scanned += len(tail.encode("utf-8"))
            tail = (tail + decoder.decode(b"", final=True))[-64:]
        check(poll["chunk_sha256"] == sha256(segment).hexdigest() and poll["prefix_sha256"] == prefix.hexdigest(), "log-poll-raw-hash-join")
        check(type(poll["bytes_read_total"]) is int and poll["bytes_read_total"] == reads
            and type(poll["bytes_scanned_total"]) is int and poll["bytes_scanned_total"] == scanned
            and type(poll["carry_bytes"]) is int and poll["carry_bytes"] == len(tail.encode("utf-8")) + len(decoder.getstate()[0]),
            "log-poll-work-or-carry-recompute")
        offset = poll["end"]
        if 2 <= index <= len(summary["rows"]) + 1:
            check(poll["poll_wall_s"] <= summary["rows"][index - 2]["phases"]["log_wall_s"] + .000001, "log-poll-outer-timing")
    check(offset == len(raw) and polls[0]["end"] >= summary["startup_log"]["bytes"], "log-poll-final-coverage")
    return {"bytes": len(raw), "polls": len(polls), "bytes_read": reads, "bytes_scanned": scanned}


def verify_audit_timings(summary):
    records = comparison.audit_records(soak.absolute(summary["audit_directory"]))
    timings = summary["audit_timings"]
    check(type(timings) is list and len(timings) == len(records), "audit-timing-count")
    previous = 0
    for index, (record, timing) in enumerate(zip(records, timings), 1):
        keys(timing, ("sequence", "kind", "started_s", "completed_s", "wall_s"), "audit-timing-fields")
        check(type(timing["sequence"]) is int and timing["sequence"] == index and timing["kind"] == record["kind"]
            and all(number(timing[name]) for name in ("started_s", "completed_s", "wall_s"))
            and timing["started_s"] >= previous and timing["completed_s"] >= timing["started_s"]
            and abs(timing["completed_s"] - timing["started_s"] - timing["wall_s"]) <= .000001, "audit-timing-sequence-or-duration")
        previous = timing["completed_s"]
    check(timings[0]["completed_s"] <= summary["warmup"]["started_s"]
        and timings[4]["started_s"] >= summary["warmup"]["completed_s"]
        and timings[4]["completed_s"] <= summary["rows"][0]["started_s"], "audit-config-reject-time-order")
    for offset, row in [(1, summary["warmup"])] + [(5 + index * 3, row) for index, row in enumerate(summary["rows"])]:
        group = timings[offset:offset + 3]
        check(row["started_s"] <= group[0]["started_s"] <= group[2]["completed_s"] <= row["completed_s"], "audit-outside-http-interval")
    bridge_start = 5 + 3 * len(summary["rows"])
    check(timings[bridge_start]["started_s"] >= summary["service_end_s"], "bridge-before-service-end")
    return len(timings)


def verify_cleanup(summary):
    cleanup = summary["cleanup"]
    check(type(cleanup) is list and len(cleanup) == 2 and {row.get("name") for row in cleanup} == {"ollama", "create"}, "cleanup-count")
    pids = set()
    for row in cleanup:
        keys(row, ("name", "pid", "method", "returncode", "process_exited", "process_error", "backend_stop_api_confirmed",
            "kv_release_confirmed", "job_assigned", "job_terminated", "job_active_processes", "job_closed", "job_cleanup_confirmed",
            "job_error", "created_suspended", "assigned_before_resume", "primary_thread_closed", "process_handle_closed"), "cleanup-fields")
        check(integer(row["pid"], 1) and row["pid"] not in pids and integer(row["returncode"], -(2**32), 2**32)
            and row["method"] == "owned-job-terminate-and-close" and all(row[name] is True for name in (
                "process_exited", "job_assigned", "job_terminated", "job_closed", "job_cleanup_confirmed", "created_suspended",
                "assigned_before_resume", "primary_thread_closed", "process_handle_closed"))
            and type(row["job_active_processes"]) is int and row["job_active_processes"] == 0
            and row["process_error"] is None and row["job_error"] is None and row["backend_stop_api_confirmed"] is False
            and row["kv_release_confirmed"] is False and (row["name"] != "create" or row["returncode"] == 0), "cleanup-unconfirmed")
        pids.add(row["pid"])


def _replay(summary_path, source_root=None, matrix_receipt=None, *, large_artifacts=True):
    path = soak.absolute(str(summary_path))
    summary = load(raw_file(path, 32 * 1024**2))
    keys(summary, SUMMARY_KEYS, "efficiency-summary-fields")
    check(type(summary["schema_version"]) is int and summary["schema_version"] == 1
        and summary["family"] == "cellivane-efficiency-run-v1" and summary["outcome"] == "COMPLETED"
        and summary["acceptance"] == "PASS" and summary["acceptance_errors"] == [] and summary["error"] is None,
        "efficiency-not-completed-or-accepted")
    check(type(summary["run_id"]) is str and str(UUID(summary["run_id"])) == summary["run_id"]
        and path.parent.name == summary["run_id"], "run-id-directory")
    check(summary["model_profile"] == "8b-q4" and same(summary["model"], MODEL), "model-profile-pin")
    check(same(summary["cases"], soak.CASES) and summary["system"] == comparison.SYSTEM
        and summary["corpus_sha256"] == digest(soak.CASES), "corpus-changed")
    check(same(summary["measurement_scope"], {"ttft": "NOT_MEASURED", "device_memory": "global-device-total-not-process-VRAM",
        "ram": "global-host-available-not-process-reservation", "backend_kv_reuse": "backend-controlled-not-disabled",
        "native_runtime_gpu_qualified": False, "native_mtp": False, "general_quality": False}), "unsupported-measurement-claim")
    model_file = summary["model_file"]
    keys(model_file, ("path", "bytes", "sha256"), "model-file-fields")
    model_path = soak.absolute(model_file["path"])
    check(model_path.name == MODEL["filename"] and type(model_file["bytes"]) is int and model_file["bytes"] == MODEL["bytes"]
        and model_file["sha256"] == MODEL["sha256"] and model_path.stat().st_size == MODEL["bytes"], "model-file-changed")
    if large_artifacts:
        check(soak.file_hash(model_path, MODEL["bytes"]) == MODEL["sha256"], "model-file-changed")
    verify_sources(summary["source"], path.parent, source_root)
    if large_artifacts:
        soak.verify_assets(summary["backend"])
    else:
        # Matrix inputs already carry full single-run raw captures. Re-read the
        # small semantic evidence without rehashing the same multi-GB assets six
        # more times; their exact official pins remain mandatory metadata.
        backend = summary["backend"]
        keys(backend, ("version", "executable", "archive", "members", "tree_sha256"), "backend-fields")
        keys(backend["archive"], ("path", "bytes", "sha256"), "backend-archive-fields")
        keys(backend["executable"], ("path", "bytes", "sha256"), "backend-executable-fields")
        check(backend["version"] == soak.OLLAMA_VERSION and type(backend["archive"]["bytes"]) is int
            and backend["archive"]["bytes"] == soak.OLLAMA_ARCHIVE_BYTES and backend["archive"]["sha256"] == soak.OLLAMA_ARCHIVE_SHA
            and type(backend["members"]) is dict and backend["members"] and all(hex_digest(item) for item in backend["members"].values())
            and backend["tree_sha256"] == digest(backend["members"])
            and integer(backend["executable"]["bytes"], 1) and backend["members"].get("ollama.exe") == backend["executable"]["sha256"],
            "matrix-large-asset-pin-metadata")
    profile = verify_configuration(summary, source_root, matrix_receipt)
    keys(summary["ports"], ("seed", "worker"), "ports-fields")
    check(all(integer(port, 1024, 65536) for port in summary["ports"].values())
        and summary["ports"]["seed"] != summary["ports"]["worker"]
        and same(summary["ports_closed"], {str(port): True for port in summary["ports"].values()}), "ports-not-closed")
    check(all(summary[name] is True for name in ("source_unchanged", "model_unchanged", "backend_unchanged"))
        and summary["cleanup_errors"] == [], "changed-artifact-or-cleanup-error")
    drains = verify_rows(summary)
    samples = soak.verify_telemetry(summary)
    placement_view = dict(summary, budget={"layers": profile["num_gpu"]})
    soak.verify_placement(placement_view)
    startup = soak.artifact(summary["startup_log"], 1024**2).decode("utf-8")
    threads = {int(value) for value in re.findall(r"\bn_threads\s*=\s*([0-9]+)\b", startup)}
    check(threads == {profile["num_thread"]}, "native-thread-count-not-observed-or-conflicting")
    log_work = verify_log_polls(summary)
    bridge_response = soak.verify_bridge(summary)
    records = soak.verify_scheduler(summary, bridge_response)
    timing_count = verify_audit_timings(summary)
    verify_cleanup(summary)
    rows = summary["rows"]
    metrics = {"responses": len(rows), "exact": sum(row["exact"] for row in rows),
        "median_wall_s": statistics.median(row["wall_s"] for row in rows), "scope": "repeated-fixed-corpus-not-general-quality-or-cold-throughput"}
    check(same(summary["metrics"], metrics), "metric-recompute")
    return {"verdict": "PASS", "scope": SCOPE, "run_id": summary["run_id"], "mode": summary["mode"],
        "profile": profile["name"], "computed_responses": len(rows), "exact": metrics["exact"], "drained_requests": drains,
        "recorded_service_s": summary["service_end_s"] - summary["service_start_s"], "resource_samples": len(samples),
        "source_files_checked": len(SOURCE_PATHS), "current_source_files_compared": source_root is not None,
        "audit_records": records, "audit_timings": timing_count, "log_work": log_work,
        "observed_gpu_layers": profile["num_gpu"], "observed_native_threads": profile["num_thread"],
        "claims": {"hardware_winner_selected": False, "speedup_guaranteed": False, "native_runtime_gpu_qualified": False,
            "ttft_measured": False, "process_exclusive_vram_measured": False, "host_or_endpoint_attestation": False,
            "backend_kv_reuse_disabled": False, "quality_generalization": False, "timing_intervals_are_disjoint": False}}


def replay(summary_path, source_root=None, matrix_receipt=None):
    """Full single-run replay; calibrated auto additionally needs its matrix."""
    return _replay(summary_path, source_root, matrix_receipt)


def _selection_reports(reports):
    check(type(reports) is list and len(reports) == 3, "selection-report-count")
    parsed = {}
    wanted_cases = {case["id"] for case in soak.CASES}
    for report in reports:
        keys(report, ("profile", "identity", "outcome", "resource_guard_passed", "rounds"), "selection-report-fields")
        profile = report["profile"]
        check(type(profile) is dict and same(profile, profile_record(profile.get("name"))), "selection-report-profile")
        name = profile["name"]
        check(name not in parsed, "selection-duplicate-profile")
        identity = report["identity"]
        keys(identity, ("model_sha256", "backend_tree_sha256", "corpus_sha256", "source_sha256"), "selection-identity-fields")
        check(all(hex_digest(item) for item in identity.values()) and identity["model_sha256"] == MODEL["sha256"]
            and identity["corpus_sha256"] == digest(soak.CASES), "selection-identity-pin")
        check(type(report["outcome"]) is str and report["outcome"] in ("PASS", "FAIL")
            and type(report["resource_guard_passed"]) is bool, "selection-report-outcome")
        rounds = report["rounds"]
        check(type(rounds) is list and (len(rounds) == 2 or report["outcome"] == "FAIL" and rounds == []), "selection-round-count")
        normalized = []
        for index, round_value in enumerate(rounds):
            keys(round_value, ("index", "samples"), "selection-round-fields")
            check(type(round_value["index"]) is int and round_value["index"] == index
                and type(round_value["samples"]) is list and len(round_value["samples"]) == 56, "selection-round-index-or-count")
            samples = {}
            for sample in round_value["samples"]:
                keys(sample, ("case_id", "repeat", "wall_s", "text_sha256"), "selection-sample-fields")
                check(type(sample["case_id"]) is str and sample["case_id"] in wanted_cases
                    and integer(sample["repeat"], 0, 4) and type(sample["wall_s"]) in (int, float)
                    and math.isfinite(sample["wall_s"]) and 0 < sample["wall_s"] <= 3600
                    and hex_digest(sample["text_sha256"]), "selection-sample-value")
                key = (sample["case_id"], sample["repeat"])
                check(key not in samples, "selection-duplicate-sample")
                samples[key] = (float(sample["wall_s"]), sample["text_sha256"])
            check(set(samples) == {(case, repeat) for case in wanted_cases for repeat in range(4)}, "selection-case-repeat-grid")
            normalized.append(samples)
        parsed[name] = (identity, report["outcome"] == "PASS" and report["resource_guard_passed"], normalized)
    check(all(same(item[0], parsed["reference"][0]) for item in parsed.values()), "selection-identity-mismatch")
    return parsed


def _p95(values):
    ordered = sorted(values)
    position = (len(ordered) - 1) * .95
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _ratio(numerator, denominator):
    ratio = numerator / denominator
    check(math.isfinite(ratio), "selection-nonfinite-ratio")
    return ratio


def _comparison(reference, candidate, index):
    ref_values = [item[0] for item in reference.values()]
    candidate_values = [item[0] for item in candidate.values()]
    ref_p50, other_p50 = statistics.median(ref_values), statistics.median(candidate_values)
    cases = []
    for case in sorted({key[0] for key in reference}):
        ref_case = statistics.median(item[0] for key, item in reference.items() if key[0] == case)
        other_case = statistics.median(item[0] for key, item in candidate.items() if key[0] == case)
        cases.append({"case_id": case, "reference_p50_s": ref_case, "candidate_p50_s": other_case,
            "latency_ratio": _ratio(other_case, ref_case), "speedup_ratio": _ratio(ref_case, other_case)})
    speeds = sorted(item["speedup_ratio"] for item in cases)
    balanced_speedup = speeds[6] + (speeds[7] - speeds[6]) / 2
    p50_gate, balanced_gate = other_p50 <= ref_p50 * .95, balanced_speedup >= 1.05
    case_gate = all(item["latency_ratio"] <= 1.10 for item in cases)
    ref_p95, other_p95 = _p95(ref_values), _p95(candidate_values)
    return {"index": index, "reference_p50_s": ref_p50, "candidate_p50_s": other_p50,
        "reference_p95_s": ref_p95, "candidate_p95_s": other_p95,
        "p50_latency_ratio": _ratio(other_p50, ref_p50), "p95_latency_ratio": _ratio(other_p95, ref_p95),
        "median_case_speedup_ratio": balanced_speedup, "p50_gain_passed": p50_gate,
        "balanced_case_gain_passed": balanced_gate, "case_regression_guard_passed": case_gate,
        "qualifies": p50_gate and balanced_gate and case_gate, "cases": cases}


def independent_choice(reports):
    """Recompute the frozen balanced policy without importing its module."""
    parsed = _selection_reports(reports)
    identity, reference_ok, reference_rounds = parsed["reference"]
    comparisons = []
    for name in ("gpu29", "gpu29-threads8"):
        _identity, candidate_ok, candidate_rounds = parsed[name]
        reasons = []
        if not reference_ok: reasons.append("reference-not-qualified")
        if not candidate_ok: reasons.append("candidate-not-qualified")
        if not reference_rounds or not candidate_rounds: reasons.append("incomplete-rounds")
        rounds, overall = [], None
        if reference_rounds and candidate_rounds:
            if any(reference_rounds[index][key][1] != value[1]
                   for index, samples in enumerate(candidate_rounds) for key, value in samples.items()):
                reasons.append("output-mismatch")
            rounds = [_comparison(reference_rounds[index], samples, index) for index, samples in enumerate(candidate_rounds)]
            merged_ref = {(key[0], index * 4 + key[1]): value for index, samples in enumerate(reference_rounds) for key, value in samples.items()}
            merged_other = {(key[0], index * 4 + key[1]): value for index, samples in enumerate(candidate_rounds) for key, value in samples.items()}
            overall = _comparison(merged_ref, merged_other, "overall")
            if not all(item["qualifies"] for item in rounds) or not overall["qualifies"]:
                reasons.append("insufficient-balanced-p50-gain-or-case-regression")
            if overall["candidate_p95_s"] > overall["reference_p95_s"] * 1.05:
                reasons.append("p95-regression")
        comparisons.append({"profile": profile_record(name), "qualifies": not reasons, "reasons": reasons,
            "rounds": rounds, "overall": overall})
    qualified = [item for item in comparisons if item["qualifies"]]
    winner = min(qualified, key=lambda item: item["overall"]["candidate_p50_s"]) if qualified else None
    return {"schema_version": 1, "policy": "efficiency-balanced-v1", "eligible": reference_ok,
        "selected_profile": winner["profile"] if winner else profile_record("reference"),
        "reason": "measured-balanced-gain" if winner else "no-consistent-gain" if reference_ok else "reference-not-qualified",
        "identity": dict(identity), "comparisons": comparisons, "scope": "measured-selection-for-this-model-backend-host-only"}


def _capture(record, summary_path, summary_raw, stdout_raw, stderr_raw, source_root, verification):
    keys(record, ("argv", "returncode", "stdout_sha256", "stderr_sha256", "verifier_sha256", "summary_sha256_before",
        "summary_sha256_after", "verification_source_sha256"), "reader-capture-fields")
    check(type(record["returncode"]) is int and record["returncode"] == 0 and stderr_raw == b""
        and record["stdout_sha256"] == sha256(stdout_raw).hexdigest() and record["stderr_sha256"] == sha256(stderr_raw).hexdigest(),
        "reader-capture-exit-or-output")
    check(record["summary_sha256_before"] == record["summary_sha256_after"] == sha256(summary_raw).hexdigest(), "reader-capture-summary-before-after")
    check(same(record["verification_source_sha256"], verification)
        and record["verifier_sha256"] == verification["tools/hosted/verify_cellivane_efficiency.py"], "reader-capture-source4")
    argv = record["argv"]
    check(type(argv) is list and len(argv) in (5, 6) and all(type(part) is str and 0 < len(part) <= 4096 for part in argv), "reader-capture-argv")
    offset = 2 if len(argv) == 6 else 1
    check((len(argv) != 6 or argv[1] == "-B") and soak.absolute(argv[0]).is_file()
        and soak.absolute(argv[offset]) == source_root / "tools/hosted/verify_cellivane_efficiency.py"
        and soak.absolute(argv[offset + 1]) == summary_path and argv[offset + 2] == "--source-root"
        and soak.absolute(argv[offset + 3]) == source_root, "reader-capture-command-binding")


def verify_matrix(selection_path, receipt_path, source_root=None):
    """Replay six small semantic evidence sets plus frozen full-reader captures.

    Multi-GB model/archive bytes are not rehashed here. The exact pins and full
    single-run capture joins remain mandatory; full auto-run replay rehashes its
    own assets. The matrix order is caller-declared, without clock attestation.
    """
    selection_path, receipt_path = soak.absolute(str(selection_path)), soak.absolute(str(receipt_path))
    selection_raw, receipt_raw = raw_file(selection_path, 256 * 1024), raw_file(receipt_path, 2 * 1024**2)
    selection, receipt = load(selection_raw), load(receipt_raw)
    keys(selection, ("schema_version", "family", "host_profile", "candidate_reports"), "selection-file-fields")
    keys(receipt, ("schema_version", "family", "collected_at_utc", "host_profile", "identity", "ordered_runs", "source_sha256",
        "verification_source_sha256", "selection_canonical_sha256", "decision", "scope", "selection_file"), "matrix-receipt-fields")
    check(type(selection["schema_version"]) is int and selection["schema_version"] == 1
        and selection["family"] == "cellivane-efficiency-selection-v1" and type(receipt["schema_version"]) is int
        and receipt["schema_version"] == 1 and receipt["family"] == "cellivane-efficiency-matrix-v1"
        and same(receipt["scope"], MATRIX_SCOPE), "matrix-version-or-scope")
    check(type(receipt["collected_at_utc"]) is str and len(receipt["collected_at_utc"]) <= 128, "matrix-collection-time")
    collected = datetime.fromisoformat(receipt["collected_at_utc"])
    check(collected.tzinfo is not None and collected.utcoffset() == timedelta(0), "matrix-collection-time")
    check(soak.absolute(receipt["selection_file"]["path"]) == selection_path
        and soak.artifact(receipt["selection_file"], 256 * 1024) == selection_raw
        and receipt["selection_canonical_sha256"] == digest(selection), "matrix-selection-file-join")
    actual_root = Path(__file__).resolve().parents[2]
    verification = {name: sha256(raw_file(actual_root / name, 4 * 1024**2)).hexdigest() for name in VERIFICATION_PATHS}
    check(same(receipt["verification_source_sha256"], verification), "matrix-verification-source4")
    ordered = receipt["ordered_runs"]
    check(type(ordered) is list and len(ordered) == 6, "matrix-six-runs")
    reports = {name: {"profile": profile_record(name), "identity": None, "outcome": "PASS", "resource_guard_passed": True, "rounds": []}
        for name in PROFILE_SETTINGS}
    seen, common_binding, common_host, original_root, input_records = set(), None, None, None, []
    for position, item in enumerate(ordered):
        keys(item, ("position", "round", "profile", "run_id", "records", "reader_verdict"), "matrix-run-fields")
        check(type(item["position"]) is int and item["position"] == position and type(item["round"]) is int
            and item["round"] == position // 3 and item["profile"] == MATRIX_ORDER[position], "matrix-ABC-CBA-order")
        records = item["records"]
        keys(records, ("summary", "reader_stdout", "reader_invocation", "reader_stderr"), "matrix-run-records")
        input_records.extend((record, limit) for record, limit in zip(
            (records[name] for name in ("summary", "reader_stdout", "reader_invocation", "reader_stderr")),
            (32 * 1024**2, 256 * 1024, 256 * 1024, 16 * 1024)))
        raw_summary = soak.artifact(records["summary"], 32 * 1024**2)
        stdout = soak.artifact(records["reader_stdout"], 256 * 1024)
        invocation = load(soak.artifact(records["reader_invocation"], 256 * 1024))
        stderr = soak.artifact(records["reader_stderr"], 16 * 1024)
        summary, verdict = load(raw_summary), load(stdout)
        summary_file = soak.absolute(records["summary"]["path"])
        uid = summary["run_id"]
        check(uid not in seen and uid == item["run_id"] and summary["mode"] == "calibrate"
            and summary["requested_profile"] == item["profile"] and same(summary["selection"], {"mode": "explicit", "artifact": None}),
            "matrix-run-duplicate-or-nonexplicit")
        seen.add(uid)
        root = soak.absolute(summary["source"]["root"])
        check(original_root is None or root == original_root, "matrix-source-root-mismatch")
        original_root = root
        _capture(invocation, summary_file, raw_summary, stdout, stderr, root, verification)
        # Revalidate every small wire/log/audit/source/resource/cleanup evidence;
        # the stored PASS is not treated as a substitute for semantic replay.
        recomputed = _replay(summary_file, source_root if source_root is not None else root, large_artifacts=False)
        check(same(verdict, recomputed) and same(item["reader_verdict"], verdict)
            and verdict["current_source_files_compared"] is True, "matrix-reader-verdict-replay")
        identity = {"model_sha256": MODEL["sha256"], "backend_tree_sha256": summary["backend"]["tree_sha256"],
            "corpus_sha256": summary["corpus_sha256"], "source_sha256": digest(summary["source"]["sha256"])}
        backend = summary["backend"]
        backend_identity = {"version": backend["version"], "tree_sha256": backend["tree_sha256"],
            "executable_sha256": backend["executable"]["sha256"], "archive_sha256": backend["archive"]["sha256"]}
        binding = {"source": summary["source"]["sha256"], "model": summary["model"], "backend": backend_identity,
            "corpus": summary["cases"], "system": summary["system"], "identity": identity}
        check(common_binding is None or same(common_binding, binding), "matrix-common-model-backend-source-corpus")
        check(common_host is None or same(common_host, summary["host_profile"]), "matrix-common-host")
        common_binding, common_host = binding, summary["host_profile"]
        samples = [{"case_id": row["case"], "repeat": index // 14, "wall_s": row["wall_s"],
            "text_sha256": sha256(row["response"]["body"]["choices"][0]["message"]["content"].encode("utf-8")).hexdigest()}
            for index, row in enumerate(summary["rows"])]
        report = reports[item["profile"]]
        report["identity"] = identity
        report["rounds"].append({"index": position // 3, "samples": samples})
    expected_reports = [reports[name] for name in PROFILE_SETTINGS]
    check(same(selection["candidate_reports"], expected_reports), "selection-reports-raw-matrix-join")
    decision = independent_choice(expected_reports)
    check(decision["eligible"] is True and same(receipt["decision"], decision)
        and same(receipt["identity"], decision["identity"]) and same(receipt["source_sha256"], common_binding["source"])
        and same(selection["host_profile"], common_host) and same(receipt["host_profile"], common_host), "matrix-decision-host-identity-join")
    for record, limit in input_records:
        soak.artifact(record, limit)
    check(raw_file(selection_path, 256 * 1024) == selection_raw and raw_file(receipt_path, 2 * 1024**2) == receipt_raw
        and verification == {name: sha256(raw_file(actual_root / name, 4 * 1024**2)).hexdigest() for name in VERIFICATION_PATHS},
        "matrix-input-or-reader-changed-during-replay")
    return {"verdict": "PASS", "scope": "recorded-efficiency-matrix-and-choice-integrity", "runs": 6,
        "host_profile": common_host, "identity": decision["identity"], "decision": decision,
        "selection_canonical_sha256": digest(selection), "selection_file_sha256": sha256(selection_raw).hexdigest(),
        "matrix_receipt_sha256": sha256(receipt_raw).hexdigest(), "source_files_checked": 21,
        "verification_source_sha256": verification, "large_assets_rehashed": False,
        "claims": {"execution_or_host_attestation": False, "caller_order_is_trusted_clock": False,
            "speedup_guaranteed": False, "general_quality": False}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary")
    parser.add_argument("--source-root")
    parser.add_argument("--matrix-receipt")
    parser.add_argument("--matrix-only", action="store_true", help="Treat the positional path as the selection file")
    args = parser.parse_args(argv)
    try:
        if args.matrix_only:
            check(args.matrix_receipt is not None, "matrix-receipt-required")
            result = verify_matrix(args.summary, args.matrix_receipt, args.source_root)
        else:
            result = replay(args.summary, args.source_root, args.matrix_receipt)
    except (ValueError, KeyError, TypeError, AttributeError, OSError, UnicodeError, zipfile.BadZipFile) as exc:
        result = {"verdict": "FAIL", "scope": SCOPE, "error": type(exc).__name__ + ":" + str(exc)[:512]}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
