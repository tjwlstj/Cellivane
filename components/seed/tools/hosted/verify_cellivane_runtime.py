#!/usr/bin/env python3
"""Independent raw replay of the bounded CPU Runtime/Murphy experiment.

No runtime, native-worker launcher or experiment producer is imported. PASS
concerns recorded integrity and the fixed experiment's functional subset.
It does not attest allocator state, token-to-text decoding, output quality,
portable speedup, weight repacking, KV sharing or model-native MTP.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from uuid import UUID
import zipfile

import verify_cellivane_speculation as spec
from verify_cellivane_comparison import (audit_records, check, digest, encoded, hex_digest,
    integer, keys, load, number, raw_file, safe_path, same, text)

ENGINE_COMMIT = "d81235049384534c167caea52b85a694f6103d14"
MODEL_BYTES = 639446688
MODEL_SHA = "9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031"
MODE_ORDER = ["none", "murphy", "murphy", "none"]
ALIAS = "cellivane-runtime-target"
CASES = [("addition", "What is 2 + 3? Reply with only the number. /no_think"),
         ("word", "Reply with exactly OK and nothing else. /no_think")]
SOURCE_PATHS = {"hosted/experimental/cellivane_seed/" + name + ".py" for name in
    ("__init__", "__main__", "adaptive", "capabilities", "core", "ollama", "placement", "profiles", "resources", "server")} | {
    "hosted/experimental/cellivane_bridge/" + name + ".py" for name in
    ("__init__", "__main__", "adapters", "cli", "contracts", "runtime", "storage")} | {
    "hosted/experimental/cellivane_runtime/" + name + ".py" for name in ("__init__", "core", "murphy")} | {
    "native/cellivane_runtime/worker.cpp"} | {"tools/hosted/" + name + ".py" for name in
    ("cellivane_bridge_lab", "cellivane_llama_assets", "build_cellivane_runtime", "cellivane_runtime_lab", "cellivane_runtime_transport")}
COUNTERS = ("backend_calls", "computed", "cache_hits", "coalesced", "failures", "rejected", "timeouts")
INPUT_PINS = {
    "include/llama.h": "c9a5f025ad7dbf07eda6660c8ff2c32cd80c07ba440d80728707a9c9d13c1bc3",
    "ggml/include/ggml.h": "12ee71f99db7db9b353bc02b1fbb57c344ee17c01ac5fb7952b41a637a747ea9",
    "ggml/include/ggml-cpu.h": "316279e004cdeb8e6ef78599acb602bf79a8abdf897fed9fd1914808c1518c6e",
    "ggml/include/ggml-backend.h": "5791edae1fb7622027621d15bc7a160198bd3b75ed8f96d06cb7b85e2b873756",
    "ggml/include/ggml-opt.h": "3586de1bc8a934b5c72339e2b6937b0641e8f149b512231e666f67de0736eea2",
    "ggml/include/gguf.h": "e56714aab702e5ce62ee587a409643c08f7e93e8fbb77f48ef7cc85075f96fa4",
    "ggml/include/ggml-alloc.h": "d114067f9099c4a0e2bbc0625c676d4894d9cf0ea27168ee072c7de0e71bb51d",
    "vendor/nlohmann/json.hpp": "aaf127c04cb31c406e5b04a63f1ae89369fccde6d8fa7cdda1ed4f32dfc5de63",
    "LICENSE": "94f29bbed6a22c35b992c5c6ebf0e7c92f13b836b90f36f461c9cf2f0f1d010d",
    "vendor/nlohmann/LICENSE.MIT": "46a65cffd1ea955132d95a8dd921640714a8d6b537d2e4e482d31145ae95b603",
}


def absolute(value):
    check(type(value) is str and Path(value).is_absolute(), "absolute-local-path-required")
    return safe_path(value)


def artifact(record, maximum=16 * 1024**2):
    keys(record, ("path", "bytes", "sha256"), "artifact-fields")
    path = absolute(record["path"])
    check(integer(record["bytes"], 0, maximum + 1) and hex_digest(record["sha256"]), "artifact-size-or-hash")
    raw = raw_file(path, maximum)
    check(len(raw) == record["bytes"] and sha256(raw).hexdigest() == record["sha256"], "artifact-bytes-changed")
    return raw


def json_lines(raw):
    check(type(raw) is bytes and 0 < len(raw) <= 1024**2 and raw.endswith(b"\n"), "protocol-wire-bound-or-truncated")
    lines = raw.splitlines()
    check(1 <= len(lines) <= 16 and all(0 < len(line) <= 256 * 1024 for line in lines), "protocol-line-bound")
    rows = [load(line) for line in lines]
    check(all(type(row) is dict for row in rows), "protocol-object-required")
    return rows


def ready(row):
    keys(row, ("kind", "protocol", "engine_commit", "threads", "context_tokens", "gpu_layers", "model_load_s", "template_mode"), "ready-fields")
    check(same({name: row[name] for name in ("kind", "protocol", "engine_commit", "threads", "context_tokens", "gpu_layers")},
        {"kind": "ready", "protocol": 1, "engine_commit": ENGINE_COMMIT, "threads": 4, "context_tokens": 512, "gpu_layers": 0})
        and number(row["model_load_s"]) and row["template_mode"] == "qwen3-nonthinking", "ready-pinned-cpu-profile")


def generation_request(row, maximum):
    keys(row, ("id", "op", "messages", "max_tokens"), "generate-command-fields")
    check(integer(row["id"]) and row["op"] == "generate" and type(row["max_tokens"]) is int
        and row["max_tokens"] == maximum, "generate-command-settings")
    messages = row["messages"]
    check(type(messages) is list and 1 <= len(messages) <= 32 and len(encoded(row)) <= 16 * 1024, "generate-input-bound")
    for message in messages:
        keys(message, ("role", "content"), "message-fields")
        check(type(message["role"]) is str and message["role"] in ("system", "user", "assistant")
            and type(message["content"]) is str and bool(message["content"].strip())
            and not any(ord(c) < 32 and c not in "\n\t" for c in message["content"]), "message-value")
    check(any(message["role"] == "user" for message in messages), "user-message-required")


def result(row, request, generation, *, measured):
    keys(row, ("kind", "id", "text", "tokens", "prompt_tokens", "completion_tokens", "finish_reason", "prefill_s",
        "decode_s", "elapsed_s", "context_id", "sampler_id", "context_disposed", "sampler_disposed", "peak_working_set_bytes", "rendered_prompt_sha256"), "result-fields")
    check(row["kind"] == "result" and type(row["id"]) is int and row["id"] == request["id"], "result-request-id")
    check(type(row["tokens"]) is list and 1 <= len(row["tokens"]) <= request["max_tokens"]
        and all(integer(token, 0, 2**31) for token in row["tokens"])
        and type(row["completion_tokens"]) is int and row["completion_tokens"] == len(row["tokens"])
        and integer(row["prompt_tokens"], 1, 513)
        and row["prompt_tokens"] + request["max_tokens"] <= 512, "result-token-accounting")
    check(type(row["text"]) is str and len(row["text"].encode("utf-8")) <= 256 * 1024
        and not any(ord(c) < 32 and c not in "\n\t" for c in row["text"]), "result-text")
    check(row["finish_reason"] in ("stop", "length")
        and ((row["finish_reason"] == "length" and row["completion_tokens"] == request["max_tokens"])
            or row["finish_reason"] == "stop"), "result-finish-accounting")
    check(hex_digest(row["rendered_prompt_sha256"]), "rendered-prompt-digest")
    if measured:
        check(row["finish_reason"] == "stop" and row["completion_tokens"] > 0 and text(row["text"]), "measured-answer-not-complete")
    check(type(row["context_id"]) is int and type(row["sampler_id"]) is int
        and row["context_id"] == row["sampler_id"] == generation
        and row["context_disposed"] is True and row["sampler_disposed"] is True, "generation-context-or-sampler-not-disposed")
    check(all(number(row[name]) for name in ("prefill_s", "decode_s", "elapsed_s"))
        and row["prefill_s"] + row["decode_s"] <= row["elapsed_s"] + .000001, "result-timing")
    check(row["peak_working_set_bytes"] is None or integer(row["peak_working_set_bytes"], 1), "result-memory-counter")


def protocol(phase):
    sent = json_lines(artifact(phase["files"]["stdin"]))
    received = json_lines(artifact(phase["files"]["stdout"]))
    count = 3 if phase["mode"] == "murphy" else 2
    check(len(sent) == count + 1 and len(received) == count + 2, "protocol-message-count")
    ready(received[0])
    check(same(phase["ready"], received[0]), "ready-raw-join")
    ids, index = set(), 0
    pairs = []
    if phase["mode"] == "murphy":
        check(type(phase["warmup"]) is dict, "murphy-warmup-missing")
        pairs.append((phase["warmup"], False))
    else:
        check(phase["warmup"] is None, "unexpected-baseline-warmup")
    check(type(phase["requests"]) is list and len(phase["requests"]) == 2, "measured-request-count")
    pairs.extend((item, True) for item in phase["requests"])
    for generation, (item, measured) in enumerate(pairs, 1):
        generation_request(sent[index], 64 if measured else 1)
        check(sent[index]["id"] not in ids, "duplicate-request-id")
        check(sent[index]["id"] == generation, "request-id-order")
        ids.add(sent[index]["id"])
        check(same(item["payload"], sent[index]) and same(item["response"], received[index + 1]), "generation-raw-wire-join")
        result(received[index + 1], sent[index], generation, measured=measured)
        check(number(item["wall_s"]) and item["wall_s"] > 0
            and received[index + 1]["elapsed_s"] <= item["wall_s"] + .000001, "generation-wall-scope")
        index += 1
    command, stopped = sent[-1], received[-1]
    keys(command, ("id", "op"), "shutdown-command-fields")
    check(integer(command["id"]) and command["id"] == count + 1 and command["id"] not in ids and command["op"] == "shutdown", "shutdown-command")
    keys(stopped, ("kind", "id", "model_disposed", "peak_working_set_bytes"), "stopped-fields")
    check(stopped["kind"] == "stopped" and type(stopped["id"]) is int and stopped["id"] == command["id"]
        and stopped["model_disposed"] is True and (stopped["peak_working_set_bytes"] is None
            or integer(stopped["peak_working_set_bytes"], 1)), "model-disposal-ack")
    check(same(phase["shutdown"], stopped), "shutdown-raw-wire-join")
    return count


def verify_source(value, run_root, source_root=None):
    keys(value, ("root", "files", "scope"), "source-fields")
    absolute(value["root"])
    check(value["scope"] == "declared-source-family-not-loader-attestation"
        and type(value["files"]) is list and len(value["files"]) == len(SOURCE_PATHS), "source-family-count")
    found, hashes = set(), {}
    for row in value["files"]:
        keys(row, ("path", "bytes", "sha256", "snapshot"), "source-file-fields")
        name = row["path"]
        check(type(name) is str and name in SOURCE_PATHS and name not in found
            and row["snapshot"] == "source-snapshot/" + name
            and integer(row["bytes"], 1, 4 * 1024**2) and hex_digest(row["sha256"]), "source-file-binding")
        found.add(name)
        raw = raw_file(run_root / row["snapshot"], 4 * 1024**2)
        check(len(raw) == row["bytes"] and sha256(raw).hexdigest() == row["sha256"], "source-snapshot-changed")
        if source_root is not None:
            check(raw_file(absolute(str(source_root)) / name, 4 * 1024**2) == raw, "source-root-changed")
        hashes[name] = row["sha256"]
    check(found == SOURCE_PATHS, "source-family-missing")
    return hashes


def verify_cleanup(value):
    keys(value, ("job_assigned", "job_terminated", "job_active_processes", "job_closed", "job_cleanup_confirmed",
        "job_error", "process_exited", "returncode", "error", "created_suspended", "assigned_before_resume",
        "primary_thread_closed", "process_handle_closed"), "cleanup-fields")
    check(all(value[name] is True for name in ("job_assigned", "job_terminated", "job_closed", "job_cleanup_confirmed",
        "process_exited", "created_suspended", "assigned_before_resume", "primary_thread_closed", "process_handle_closed"))
        and type(value["job_active_processes"]) is int and value["job_active_processes"] == 0
        and type(value["returncode"]) is int and value["returncode"] == 0
        and value["error"] is None and value["job_error"] is None, "cleanup-unconfirmed")


def verify_build(value, summary, source_hashes):
    keys(value, ("schema_version", "artifact_family", "outcome", "runtime_tested", "model_run", "observed_at_utc",
        "engine_commit", "engine_tag", "engine_archive_sha256", "upstream_repository", "source", "builder", "inputs",
        "engine_directory", "engine_files", "compiler_arguments", "compiler_environment", "exit_code", "build_log", "executable", "scope"), "build-fields")
    check(same({name: value[name] for name in ("schema_version", "artifact_family", "outcome", "runtime_tested", "model_run",
        "engine_commit", "engine_tag", "engine_archive_sha256", "upstream_repository", "exit_code", "scope")},
        {"schema_version": 1, "artifact_family": "cellivane-native-worker-build-v1", "outcome": "COMPILED", "runtime_tested": False,
        "model_run": False, "engine_commit": ENGINE_COMMIT, "engine_tag": "b11429", "engine_archive_sha256": spec.ARCHIVE_SHA,
        "upstream_repository": "https://github.com/ggml-org/llama.cpp", "exit_code": 0,
        "scope": "Windows x64 CPU compilation only; no model qualification, paging, GPU, shared KV, or MTP"}), "build-pin-or-scope")
    check(type(value["observed_at_utc"]) is str and len(value["observed_at_utc"]) <= 64, "build-date")
    for field, source_path in (("source", "native/cellivane_runtime/worker.cpp"), ("builder", "tools/hosted/build_cellivane_runtime.py")):
        keys(value[field], ("path", "sha256"), "build-source-fields")
        check(absolute(value[field]["path"]) == absolute(summary["source"]["root"]) / source_path
            and value[field]["sha256"] == source_hashes[source_path], "build-source-snapshot-join")
    check(same(value["executable"], summary["worker"]), "build-worker-join")
    check(type(value["inputs"]) is list and len(value["inputs"]) == len(INPUT_PINS), "build-input-count")
    found, input_root = set(), None
    for item in value["inputs"]:
        keys(item, ("path", "bytes", "sha256", "relative_path", "url"), "build-input-fields")
        name = item["relative_path"]
        check(type(name) is str and name in INPUT_PINS and name not in found and item["sha256"] == INPUT_PINS[name], "build-input-pin")
        found.add(name)
        expected_url = "https://raw.githubusercontent.com/ggml-org/llama.cpp/" + ENGINE_COMMIT + "/" + name
        if name == "vendor/nlohmann/LICENSE.MIT":
            expected_url = "https://raw.githubusercontent.com/nlohmann/json/55f93686c01528224f448c19128836e7df245f72/LICENSE.MIT"
        check(item["url"] == expected_url, "build-input-url")
        location = absolute(item["path"])
        root = location.parents[len(PurePosixPath(name).parts) - 1]
        check(input_root is None or root == input_root, "build-input-root")
        input_root = root
        artifact({name: item[name] for name in ("path", "bytes", "sha256")}, 2 * 1024**2)
    directory = absolute(value["engine_directory"])
    expected = {name: pin for name, pin in summary["engine"]["member_sha256"].items()
        if name in ("ggml-base.dll", "ggml.dll", "llama.dll", "libomp.dll", "LICENSE-LLVM-OpenMP")
        or re.fullmatch(r"ggml-cpu-[a-z0-9]+\.dll", name)}
    check({"ggml-base.dll", "ggml.dll", "llama.dll", "libomp.dll", "LICENSE-LLVM-OpenMP"} <= set(expected)
        and any(name.startswith("ggml-cpu-") for name in expected)
        and type(value["engine_files"]) is list and len(value["engine_files"]) == len(expected), "build-cpu-members")
    found = set()
    for item in value["engine_files"]:
        keys(item, ("path", "bytes", "sha256", "relative_path"), "build-engine-fields")
        name = item["relative_path"]
        check(type(name) is str and name in expected and name not in found and item["sha256"] == expected[name]
            and absolute(item["path"]) == directory / name, "build-engine-member-join")
        found.add(name)
        artifact({name: item[name] for name in ("path", "bytes", "sha256")}, 16 * 1024**2)
    check({file.name for file in directory.iterdir()} == set(expected), "build-engine-extra-or-missing")
    worker_path = absolute(summary["worker"]["path"])
    check(worker_path.name == "cellivane-runtime-worker.exe", "worker-name")
    expected_args = ["cl.exe", "/nologo", "/std:c++17", "/EHsc", "/O2", "/W4", "/MT", "/utf-8", "/DUNICODE", "/D_UNICODE",
        "/D_WIN32_WINNT=0x0A00", "/I" + str(input_root / "include"), "/I" + str(input_root / "ggml/include"),
        "/I" + str(input_root / "vendor/nlohmann"), value["source"]["path"], "/Fe:" + str(worker_path),
        "/Fo:" + str(worker_path.parent / "worker.obj"), "/link", "Psapi.lib", "Bcrypt.lib", "/DYNAMICBASE", "/NXCOMPAT"]
    check(same(value["compiler_arguments"], expected_args) and absolute(value["compiler_environment"]).name == "vcvars64.bat", "compiler-command")
    keys(value["build_log"], ("path", "sha256"), "build-log-fields")
    log = raw_file(absolute(value["build_log"]["path"]), 4 * 1024**2)
    check(hex_digest(value["build_log"]["sha256"]) and sha256(log).hexdigest() == value["build_log"]["sha256"]
        and log and not re.search(rb"fatal error|error C[0-9]+|error LNK[0-9]+", log), "build-log-failed-or-changed")
    return directory


def seed_answer(value, response, native_command, identity, ordinal, seen_ids):
    keys(value, ("id", "object", "created", "model", "choices", "usage", "cellivane"), "seed-response-fields")
    try:
        identifier = UUID(value["id"])
        check(str(identifier) == value["id"] and identifier.version == 4 and value["id"] not in seen_ids, "seed-response-id")
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("seed-response-id") from exc
    seen_ids.add(value["id"])
    normalized = {"model": ALIAS, "choices": [{"index": 0, "message": {"role": "assistant", "content": response["text"]},
        "finish_reason": "stop"}], "usage": {"prompt_tokens": response["prompt_tokens"],
        "completion_tokens": response["completion_tokens"], "total_tokens": response["prompt_tokens"] + response["completion_tokens"]}}
    check(value["object"] == "chat.completion" and integer(value["created"], 1)
        and same({name: value[name] for name in normalized}, normalized), "seed-native-answer-join")
    inference = {"model": ALIAS, "messages": native_command["messages"], "max_tokens": 64, "temperature": 0, "stream": False}
    key = digest({"identity": identity, "inference": inference})
    check(same(value["cellivane"], {"engine": "seed", "version": "0.1.0", "execution": "computed", "key": key,
        "backend_calls": ordinal}), "seed-no-cache-key-binding")
    return key, digest(normalized)


def verify_scheduler(phase, directory, seen_ids):
    identity = phase["seed_identity"]
    expected = []
    for index, row in enumerate(phase["requests"], 1):
        key, answer_sha = seed_answer(row["seed_response"], row["response"], row["payload"], identity, index, seen_ids)
        for finished in (False, True):
            expected.append({"seq": len(expected) + 1, "kind": "finish" if finished else "start", "key": key,
                "execution": "computed", "reason": None, "response_sha256": answer_sha if finished else None,
                "active": 0 if finished else 1, "waiters": 0, "backend_calls": index, "computed": index if finished else index - 1,
                "cache_hits": 0, "coalesced": 0, "failures": 0, "rejected": 0, "timeouts": 0, "cache_entries": 0, "cache_bytes": 0})
    expected.append({"seq": 5, "kind": "close", "key": None, "execution": None, "reason": "engine-closed",
        "response_sha256": None, "active": 0, "waiters": 0, "backend_calls": 2, "computed": 2, "cache_hits": 0,
        "coalesced": 0, "failures": 0, "rejected": 0, "timeouts": 0, "cache_entries": 0, "cache_bytes": 0})
    sessions = list(safe_path(directory / "audit/seed-runs").iterdir())
    check(len(sessions) == 1 and sessions[0].is_dir(), "scheduler-audit-session")
    try:
        check(str(UUID(sessions[0].name)) == sessions[0].name, "scheduler-session-id")
    except ValueError as exc:
        raise ValueError("scheduler-session-id") from exc
    records = audit_records(sessions[0])
    check(len(records) == 5 and all(row["kind"] == "scheduler" for row in records)
        and same([row["value"] for row in records], expected), "scheduler-raw-chain-join")
    status = {"engine": "seed", "version": "0.1.0", "model": ALIAS, "identity": identity,
        "closed": False, "poisoned": False, "slots": 1, "active": 0, "inflight": 0, "waiters": 0,
        "max_waiters": 8, "cache_entries": 0, "cache_bytes": 0, "cache_entries_limit": 0, "cache_bytes_limit": 0,
        "backend_calls": 2, "computed": 2, "cache_hits": 0, "coalesced": 0, "failures": 0, "rejected": 0, "timeouts": 0, "event_seq": 4}
    check(same(phase["seed_status"], status), "seed-final-status")


def verify_stderr(record):
    raw = artifact(record)
    check(raw and not re.search(rb"\b(?:fatal|assertion failed|abort|segmentation fault|access violation|out of memory)\b|\b(?:error|failed)\b", raw, re.I), "native-stderr-fatal")
    return {"bytes": len(raw), "sha256": sha256(raw).hexdigest()}


def replay(summary_path, source_root=None):
    path = absolute(str(summary_path))
    summary = load(raw_file(path, 16 * 1024**2))
    keys(summary, ("schema_version", "scope", "run_id", "created_at_utc", "outcome", "error", "config", "model", "worker",
        "build_receipt", "engine", "native_engine_directory", "native_engine_files", "source", "phases", "results_scope"), "summary-fields")
    check(type(summary["schema_version"]) is int and summary["schema_version"] == 1
        and summary["scope"] == "runtime-murphy-cpu-smoke" and summary["outcome"] == "COMPLETED"
        and summary["error"] is None, "summary-not-completed-smoke")
    check(type(summary["created_at_utc"]) is str and len(summary["created_at_utc"]) <= 64, "summary-date")
    check(str(UUID(summary["run_id"])) == summary["run_id"] and path.parent.name == summary["run_id"], "run-id-directory")
    expected_config = {"alias": ALIAS, "target_profile": "0.6b", "context_tokens": 512, "threads": 4, "batch": 128,
        "max_tokens": 64, "warmup_max_tokens": 1, "rounds": 2, "mode_order": MODE_ORDER, "no_result_cache": True, "placement": "cpu"}
    check(same(summary["config"], expected_config), "fixed-cpu-smoke-configuration")
    scope = {"quality_verified": False, "speedup_guaranteed": False, "weight_repacked": False,
        "native_mtp": False, "os_memory_limit_enforced": False, "gpu_tested": False}
    check(same(summary["results_scope"], scope), "unsupported-result-claim")
    hashes = verify_source(summary["source"], path.parent, source_root)
    engine_identity = spec.verify_assets(summary["engine"])
    model = summary["model"]
    keys(model, ("path", "bytes", "sha256"), "model-fields")
    check(type(model["bytes"]) is int and model["bytes"] == MODEL_BYTES and model["sha256"] == MODEL_SHA, "model-pin")
    model_path = absolute(model["path"])
    check(model_path.stat().st_size == MODEL_BYTES and spec.file_hash(model_path) == MODEL_SHA, "model-changed")
    artifact(summary["worker"], 16 * 1024**2)
    build = load(artifact(summary["build_receipt"], 4 * 1024**2))
    engine_directory = verify_build(build, summary, hashes)
    check(absolute(summary["native_engine_directory"]) == engine_directory
        and same(summary["native_engine_files"], build["engine_files"]), "native-engine-build-join")
    identity = digest({"engine_identity": engine_identity, "worker_sha256": summary["worker"]["sha256"],
        "model_sha256": MODEL_SHA, "config": summary["config"]})
    check(type(summary["phases"]) is list and len(summary["phases"]) == 4, "phase-count")
    seen_ids, timings, tokens = set(), {mode: [] for mode in ("none", "murphy")}, {mode: 0 for mode in ("none", "murphy")}
    rendered = {}
    for index, phase in enumerate(summary["phases"]):
        keys(phase, ("index", "mode", "requests", "warmup", "memory", "budget", "before", "command", "ready", "preparation",
            "seed_identity", "seed_status", "shutdown", "cleanup", "after", "source_unchanged", "files", "error"), "phase-fields")
        mode = MODE_ORDER[index]
        check(type(phase["index"]) is int and phase["index"] == index and phase["mode"] == mode
            and phase["error"] is None and phase["source_unchanged"] is True and phase["seed_identity"] == identity, "phase-binding-or-failure")
        directory = path.parent / f"phase-{index:02d}-{mode}"
        check(same(load(raw_file(directory / "phase.json", 4 * 1024**2)), phase), "phase-file-summary-join")
        expected_state = {"model_sha256": MODEL_SHA, "worker_sha256": summary["worker"]["sha256"], "engine_identity": engine_identity,
            "sealed_engine_sha256": digest({row["relative_path"]: row["sha256"] for row in build["engine_files"]})}
        check(same(phase["before"], expected_state) and same(phase["after"], expected_state), "phase-artifacts-mutated")
        expected_command = [summary["worker"]["path"], "--engine-dir", str(engine_directory), "--model", model["path"],
            "--threads", "4", "--context", "512", "--batch", "128"]
        check(same(phase["command"], expected_command), "worker-command")
        memory = phase["memory"]
        keys(memory, ("source", "available_bytes", "total_bytes"), "memory-fields")
        check(memory["source"] == "GlobalMemoryStatusEx" and integer(memory["available_bytes"])
            and integer(memory["total_bytes"], 1) and memory["available_bytes"] <= memory["total_bytes"], "memory-snapshot")
        required = MODEL_BYTES + 2 * 1024**3 + 512 * 1024**2
        check(same(phase["budget"], {"required_bytes": required, "headroom_bytes": 4 * 1024**3,
            "scope": "declared-preflight-not-os-enforced"}) and required <= memory["available_bytes"] - 4 * 1024**3, "ram-budget-fit")
        keys(phase["files"], ("stdin", "stdout", "stderr"), "protocol-files")
        for name, filename in (("stdin", "stdin.jsonl"), ("stdout", "stdout.jsonl"), ("stderr", "stderr.log")):
            check(absolute(phase["files"][name]["path"]) == safe_path(directory / filename), "protocol-file-location")
        protocol(phase)
        verify_stderr(phase["files"]["stderr"])
        prepared = phase["preparation"]
        keys(prepared, ("load_wall_s", "warmup_wall_s", "preparation_s"), "preparation-fields")
        check(all(number(prepared[name]) for name in prepared) and prepared["load_wall_s"] > 0
            and prepared["load_wall_s"] >= phase["ready"]["model_load_s"]
            and abs(prepared["preparation_s"] - prepared["load_wall_s"] - prepared["warmup_wall_s"]) <= .000001
            and (mode != "murphy" or prepared["warmup_wall_s"] >= phase["warmup"]["wall_s"]), "preparation-timing")
        if mode == "murphy":
            keys(phase["warmup"], ("payload", "response", "wall_s"), "warmup-record-fields")
            check(same(phase["warmup"]["payload"]["messages"], [{"role": "user", "content": "Reply briefly. /no_think"}]), "warmup-corpus")
        for row, (case, prompt) in zip(phase["requests"], CASES):
            keys(row, ("case", "payload", "response", "wall_s", "seed_response"), "request-record-fields")
            check(row["case"] == case and same(row["payload"]["messages"], [{"role": "user", "content": prompt}]), "measured-corpus")
            prompt_sha = row["response"]["rendered_prompt_sha256"]
            check(case not in rendered or rendered[case] == prompt_sha, "rendered-prompt-changed-across-phases")
            rendered[case] = prompt_sha
            timings[mode].append(row["wall_s"])
            tokens[mode] += row["response"]["completion_tokens"]
        verify_scheduler(phase, directory, seen_ids)
        verify_cleanup(phase["cleanup"])
    return {"verdict": "PASS", "scope": "recorded-native-runtime-murphy-cpu-integrity-and-functional-replay",
        "run_id": summary["run_id"], "source_files_checked": len(hashes), "fresh_worker_phases": 4,
        "measured_responses": 8, "discarded_warmups": 2, "runtime_generations": 10,
        "timing": {mode: {"measured_wall_s": sum(timings[mode]), "completion_tokens": tokens[mode]} for mode in timings},
        "claims": {"token_text_independently_decoded": False, "live_allocator_attestation": False,
            "general_quality": False, "portable_speedup": False, "weight_repack": False, "kv_sharing": False, "native_mtp": False}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary")
    parser.add_argument("--source-root")
    args = parser.parse_args(argv)
    try:
        verdict = replay(args.summary, args.source_root)
    except (ValueError, KeyError, TypeError, OSError, UnicodeError, zipfile.BadZipFile) as exc:
        verdict = {"verdict": "FAIL", "scope": "recorded-native-runtime-murphy-cpu-integrity-and-functional-replay",
            "error": type(exc).__name__ + ":" + str(exc)[:512]}
    print(json.dumps(verdict, sort_keys=True, ensure_ascii=False, allow_nan=False))
    return 0 if verdict["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

