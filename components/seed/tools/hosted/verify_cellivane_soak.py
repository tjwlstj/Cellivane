#!/usr/bin/env python3
"""Independent recorded-integrity replay for the bounded Ollama GPU soak.

No producer, runtime implementation or resource-probe validator is imported.
Device telemetry concerns the whole device, never exclusive process VRAM.
Nonstreaming responses do not measure TTFT. Recorded integrity is distinct
from host attestation, arbitrary workload quality and a speedup guarantee.
"""
from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import statistics
from uuid import UUID
import zipfile

import verify_cellivane_bridge as bridge
import verify_cellivane_comparison as comparison
from verify_cellivane_comparison import check, digest, encoded, hex_digest, integer, keys, load, number, raw_file, safe_path, same

MODEL_BYTES = 5027783488
MODEL_SHA = "d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785"
OLLAMA_VERSION = "0.40.2"
OLLAMA_ARCHIVE_BYTES = 1468085195
OLLAMA_ARCHIVE_SHA = "e29ad1d5063dd4b54b2492d9b00adab2cff9621bfa654b6c92aa8d6f1fdfe7fc"
GPU_QUERY = "index,name,driver_version,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,power.draw"
MODELS = {"4b-q8": {"filename": "Qwen3-4B-Q8_0.gguf", "bytes": 4280404704,
    "sha256": "8c2f07f26af9747e41988551106f149b03eb9b5cb6df636027b6bf6278473300", "layers": 37},
    "8b-q4": {"filename": "Qwen3-8B-Q4_K_M.gguf", "bytes": MODEL_BYTES, "sha256": MODEL_SHA, "layers": 37}}
CASES = [*comparison.CASES,
    {"id": "medium-lookup", "prompt": "Read these records and return only the value of TARGET_CODE.\n" +
        "\n".join(f"record {i}: ordinary value {i * 3}" for i in range(30)) +
        "\nTARGET_CODE = BLUE_742\nReturn only TARGET_CODE.", "expected": "BLUE_742"},
    {"id": "medium-ko", "prompt": "다음 기록에서 최종 승인된 색상만 한 단어로 답해 줘.\n" +
        "\n".join(f"검토 {i}: 아직 미정이며 승인이 필요하다." for i in range(20)) +
        "\n최종 승인: 파랑.\n최종 승인된 색상만 답해 줘.", "expected": "파랑"}]
SOURCE_PATHS = comparison.SOURCE_PATHS | {"tools/hosted/cellivane_seed_soak.py", "tools/hosted/cellivane_resource_probe.py"}
GUARDS = {"minimum_ram_free_bytes": 3 * 1024**3, "minimum_vram_free_bytes": 768 * 1024**2,
    "maximum_temperature_c": 85, "sample_interval_s": 3, "maximum_sample_gap_s": 10,
    "request_deadline_s": 120, "minimum_start_interval_s": .5, "maximum_requests": 2048,
    "maximum_log_bytes": 16 * 1024**2, "maximum_telemetry_bytes": 8 * 1024**2}
COUNTERS = ("backend_calls", "computed", "cache_hits", "coalesced", "failures", "rejected", "timeouts")
OFFLOAD = re.compile(r"^.*(?:offloaded [0-9]+/[0-9]+ layers to GPU|layers\.offload=[0-9]+).*", re.M)
FATAL = re.compile(r"\blevel=(?:ERROR|FATAL)\b|out of memory|cuda error|cudamalloc.*failed|cublas_status_alloc_failed|panic:|fatal error:|failed to (?:allocate|load|initialize)|error loading model|runner process has terminated", re.I)


def absolute(value):
    check(type(value) is str and Path(value).is_absolute(), "absolute-local-path-required")
    return safe_path(value)


def file_hash(path, maximum):
    path = absolute(str(path))
    check(path.is_file() and path.stat().st_size <= maximum, "artifact-file-bound")
    result = sha256()
    total = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
            total += len(chunk)
            check(total <= maximum, "artifact-file-grew-beyond-bound")
            result.update(chunk)
    return result.hexdigest()


def artifact(record, maximum=32 * 1024**2):
    keys(record, ("path", "bytes", "sha256"), "artifact-fields")
    check(integer(record["bytes"], 0, maximum + 1) and hex_digest(record["sha256"]), "artifact-size-or-digest")
    path = absolute(record["path"])
    raw = raw_file(path, maximum)
    check(len(raw) == record["bytes"] and sha256(raw).hexdigest() == record["sha256"], "artifact-content-changed")
    return raw


def resource_evidence(value):
    """Independently parse GPU-0 CSV and join the declared typed observation."""
    keys(value, ("observation", "gpu_raw"), "resource-evidence-fields")
    observation, raw = value["observation"], value["gpu_raw"]
    keys(observation, ("schema_version", "memory", "gpu"), "resource-observation-fields")
    check(type(observation["schema_version"]) is int and observation["schema_version"] == 1, "resource-version")
    keys(raw, ("argv", "returncode", "stdout", "stderr"), "resource-raw-fields")
    check(type(raw["argv"]) is list and len(raw["argv"]) == 4
        and all(type(part) is str for part in raw["argv"])
        and absolute(raw["argv"][0]).name.lower() == "nvidia-smi.exe"
        and raw["argv"][1:] == ["--id=0", "--query-gpu=" + GPU_QUERY, "--format=csv,noheader,nounits"]
        and type(raw["returncode"]) is int and raw["returncode"] == 0, "resource-query-command")
    check(all(type(raw[name]) is str and len(raw[name].encode("utf-8")) <= 16 * 1024 for name in ("stdout", "stderr"))
        and 1 <= len(raw["stdout"].encode("utf-8")) <= 4096, "resource-wire-bound")
    try:
        rows = list(csv.reader(io.StringIO(raw["stdout"], newline=""), strict=True, skipinitialspace=True))
    except csv.Error as exc:
        raise ValueError("resource-csv") from exc
    check(len(rows) == 1 and len(rows[0]) == 9, "resource-csv-shape")
    index, name, driver, total, used, free, utilization, temperature, power = (part.strip() for part in rows[0])

    def unsigned(part, maximum=2**64 - 1):
        check(re.fullmatch(r"[0-9]{1,20}", part, re.ASCII) is not None, "resource-csv-integer")
        result = int(part)
        check(result <= maximum, "resource-csv-integer-bound")
        return result

    def decimal(part, maximum):
        check(re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", part, re.ASCII) is not None, "resource-csv-number")
        result = float(part)
        check(math.isfinite(result) and 0 <= result <= maximum, "resource-csv-number-bound")
        return result

    check(unsigned(index) == 0 and 1 <= len(name) <= 256 and not any(ord(c) < 32 or ord(c) == 127 for c in name)
        and len(driver) <= 64 and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,4}", driver, re.ASCII), "resource-device-identity")
    mib = 1024**2
    total_bytes, used_bytes, free_bytes = [unsigned(part, (2**64 - 1) // mib) * mib for part in (total, used, free)]
    check(total_bytes > 0 and used_bytes <= total_bytes and free_bytes <= total_bytes, "resource-device-memory")
    gpu = {"source": "nvidia-smi", "index": 0, "name": name, "driver_version": driver, "total_bytes": total_bytes,
        "used_bytes": used_bytes, "free_bytes": free_bytes, "utilization_percent": decimal(utilization, 100),
        "temperature_c": decimal(temperature, 200), "power_w": None if power in ("N/A", "[N/A]") else decimal(power, 10000)}
    check(same(observation["gpu"], gpu), "resource-typed-raw-join")
    memory = observation["memory"]
    keys(memory, ("source", "available_bytes", "total_bytes"), "resource-memory-fields")
    check(memory["source"] == "GlobalMemoryStatusEx" and integer(memory["total_bytes"], 1, 2**64)
        and integer(memory["available_bytes"], 0, memory["total_bytes"] + 1), "resource-memory-values")
    return observation


def verify_sources(value, directory, source_root):
    keys(value, ("root", "sha256", "scope"), "source-fields")
    absolute(value["root"])
    hashes = value["sha256"]
    check(value["scope"] == "declared-18-file-runtime-family-not-loader-attestation" and type(hashes) is dict
        and set(hashes) == SOURCE_PATHS and all(hex_digest(h) for h in hashes.values()), "source-family")
    for name, expected in hashes.items():
        raw = raw_file(directory / "source-snapshot" / name, 4 * 1024**2)
        check(sha256(raw).hexdigest() == expected, "source-snapshot-changed")
        if source_root is not None:
            check(raw_file(absolute(str(source_root)) / name, 4 * 1024**2) == raw, "current-source-changed")


def verify_assets(value):
    keys(value, ("version", "executable", "archive", "members", "tree_sha256"), "backend-fields")
    check(value["version"] == OLLAMA_VERSION, "backend-version-pin")
    archive = value["archive"]
    keys(archive, ("path", "bytes", "sha256"), "backend-archive-fields")
    check(type(archive["bytes"]) is int and archive["bytes"] == OLLAMA_ARCHIVE_BYTES
        and archive["sha256"] == OLLAMA_ARCHIVE_SHA, "backend-archive-pin")
    archive_path = absolute(archive["path"])
    check(archive_path.stat().st_size == OLLAMA_ARCHIVE_BYTES
        and file_hash(archive_path, OLLAMA_ARCHIVE_BYTES) == OLLAMA_ARCHIVE_SHA, "backend-archive-changed")
    executable = value["executable"]
    keys(executable, ("path", "bytes", "sha256"), "backend-executable-fields")
    binary = absolute(executable["path"])
    check(binary.name == "ollama.exe" and integer(executable["bytes"], 1)
        and binary.stat().st_size == executable["bytes"] and hex_digest(executable["sha256"])
        and file_hash(binary, 512 * 1024**2) == executable["sha256"], "backend-executable-changed")
    base, binaries, names, total = binary.parent, {}, set(), 0
    with zipfile.ZipFile(archive_path) as package:
        check(1 <= len(package.infolist()) <= 10000, "backend-archive-members-bound")
        for member in package.infolist():
            name = PurePosixPath(member.filename.replace("\\", "/"))
            check(name.parts and not name.is_absolute() and ".." not in name.parts and all(":" not in p for p in name.parts)
                and (member.external_attr >> 16) & 0o170000 != 0o120000, "backend-member-path")
            if member.is_dir():
                continue
            normalized = name.as_posix()
            check(normalized not in names and member.file_size >= 0, "backend-duplicate-member")
            names.add(normalized)
            total += member.file_size
            check(total <= 8 * 1024**3, "backend-expanded-bound")
            target = absolute(str(base.joinpath(*name.parts)))
            check(target.stat().st_size == member.file_size, "backend-member-size")
            expected = sha256()
            with package.open(member) as stream:
                for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
                    expected.update(chunk)
            expected = expected.hexdigest()
            check(file_hash(target, member.file_size) == expected, "backend-member-changed")
            if target.suffix.lower() in (".exe", ".dll"):
                binaries[normalized] = expected
    actual = {path.relative_to(base).as_posix() for path in base.rglob("*") if path.is_file()}
    check(actual == names | {"cellivane-extraction.json"} and binaries.get("ollama.exe") == executable["sha256"]
        and same(value["members"], binaries) and value["tree_sha256"] == digest(binaries), "backend-tree-join")


def verify_telemetry(summary):
    raw = artifact(summary["telemetry"], GUARDS["maximum_telemetry_bytes"])
    check(raw and raw.endswith(b"\n"), "telemetry-truncated")
    lines = raw.splitlines()
    check(2 <= len(lines) <= 10000 and all(0 < len(line) <= 64 * 1024 for line in lines), "telemetry-line-bound")
    samples = [load(line) for line in lines]
    previous, stage_index, identity, ram_total = None, -1, None, None
    stages = ("preflight", "loading", "service", "bridge", "cleanup", "after")
    for index, row in enumerate(samples, 1):
        keys(row, ("seq", "elapsed_s", "query_wall_s", "stage", "observation", "gpu_raw"), "telemetry-fields")
        check(type(row["seq"]) is int and row["seq"] == index and number(row["elapsed_s"])
            and number(row["query_wall_s"]) and 0 < row["query_wall_s"] <= 10
            and row["query_wall_s"] <= row["elapsed_s"] and row["stage"] in stages, "telemetry-sequence-time")
        current_stage = stages.index(row["stage"])
        check(current_stage >= stage_index, "telemetry-stage-order")
        stage_index = current_stage
        if previous is not None:
            check(0 < row["elapsed_s"] - previous <= GUARDS["maximum_sample_gap_s"], "telemetry-gap")
        previous = row["elapsed_s"]
        observation = resource_evidence({name: row[name] for name in ("observation", "gpu_raw")})
        gpu, memory = observation["gpu"], observation["memory"]
        current_identity = {name: gpu[name] for name in ("index", "name", "driver_version", "total_bytes")}
        check(identity is None or same(identity, current_identity), "telemetry-device-changed")
        launch_gpu = summary["launch_probe"]["observation"]["gpu"]
        check(same(current_identity, {name: launch_gpu[name] for name in current_identity}), "launch-telemetry-device-mismatch")
        identity = current_identity
        check(ram_total is None or memory["total_bytes"] == ram_total, "telemetry-host-total-changed")
        ram_total = memory["total_bytes"]
        check(memory["available_bytes"] >= GUARDS["minimum_ram_free_bytes"]
            and gpu["free_bytes"] >= GUARDS["minimum_vram_free_bytes"]
            and gpu["temperature_c"] < GUARDS["maximum_temperature_c"], "telemetry-resource-guard")
    check(samples[0]["stage"] == "preflight" and samples[-1]["stage"] == "after"
        and same(samples[0]["observation"], summary["preflight"])
        and samples[0]["elapsed_s"] <= summary["service_start_s"]
        and samples[-1]["elapsed_s"] >= summary["service_end_s"], "telemetry-window-coverage")
    check(summary["telemetry_errors"] == [] and summary["resource_guard_reason"] is None, "telemetry-lost-or-guarded")
    return samples


def payload(alias, prompt):
    return {"model": alias, "messages": [{"role": "system", "content": comparison.SYSTEM}, {"role": "user", "content": prompt}],
        "max_tokens": 128, "temperature": 0, "stream": False}


def backend_receipt(row, request):
    keys(row, ("name", "kind", "model", "outcome", "text", "elapsed_s", "request_sha256", "response_sha256", "raw_response",
        "error", "usage", "request_body", "response_body", "http_status"), "backend-receipt-fields")
    check(row["name"] == "ollama-tensor" and row["kind"] == "ollama" and row["model"] == request["model"]
        and number(row["elapsed_s"]) and row["elapsed_s"] <= 120 and row["outcome"] == "ANSWERED"
        and type(row["http_status"]) is int and row["http_status"] == 200 and row["error"] is None, "backend-answer-scope")
    raw_request, raw_response = comparison.wire(row["request_body"], 16 * 1024), comparison.wire(row["response_body"])
    wanted = {"model": request["model"], "messages": request["messages"], "stream": False, "think": False, "options": {"num_predict": 128}}
    check(raw_request == encoded(wanted) and sha256(raw_request).hexdigest() == row["request_sha256"], "backend-request-wire")
    response = load(raw_response)
    check(sha256(raw_response).hexdigest() == row["response_sha256"] and same(response, row["raw_response"]), "backend-response-wire")
    check(type(response) is dict and {"model", "message", "done", "done_reason"} <= set(response)
        and set(response) <= {"model", "message", "done", "done_reason", "created_at"} | comparison.STATS
        and response["model"] == request["model"] and response["done"] is True and response["done_reason"] == "stop", "backend-response-finish")
    keys(response["message"], ("role", "content"), "backend-message-fields")
    text = response["message"]["content"]
    check(response["message"]["role"] == "assistant" and comparison.text(text) and row["text"] == text, "backend-answer-text")
    check(all(integer(response[name]) for name in comparison.STATS & set(response)), "backend-statistic")
    if "created_at" in response:
        check(type(response["created_at"]) is str and 1 <= len(response["created_at"]) <= 128, "backend-created-at")
    usage = {name: response[name] for name in ("prompt_eval_count", "eval_count") if name in response}
    check(set(usage) == {"prompt_eval_count", "eval_count"} and all(integer(n, 1, 2**62) for n in usage.values())
        and usage["eval_count"] <= 128 and same(row["usage"], usage), "backend-token-usage")
    normalized = {"model": request["model"], "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": usage["prompt_eval_count"], "completion_tokens": usage["eval_count"], "total_tokens": sum(usage.values())}}
    check(len(encoded(normalized)) <= 256 * 1024 - 1024, "backend-normalized-bound")
    return normalized


def verify_placement(summary):
    startup = artifact(summary["startup_log"], 1024**2)
    complete = artifact(summary["log"], GUARDS["maximum_log_bytes"])
    check(complete.startswith(startup), "startup-log-not-prefix")
    start_text, full_text = startup.decode("utf-8"), complete.decode("utf-8")
    check(not FATAL.search(full_text), "fatal-backend-log")
    check(OFFLOAD.findall(full_text.replace("\r\n", "\n")) == OFFLOAD.findall(start_text.replace("\r\n", "\n")), "model-reloaded-during-soak")
    counts, runtimes, buffers = set(), set(), []
    native, structured = False, False
    for line in start_text.splitlines():
        check(not re.search(r"no usable GPU found|no compatible GPUs|no CUDA-capable device|falling back to CPU", line, re.I), "gpu-unavailable")
        match = re.fullmatch(r"(?:llama_model_)?load_tensors:\s+offloaded ([0-9]{1,4})/([0-9]{1,4}) layers to GPU\s*", line)
        if match:
            counts.add(tuple(map(int, match.groups())))
            native = True
        elif re.match(r"(?:llama_model_)?load_tensors:\s+offloaded\b", line):
            raise ValueError("offload-line-format")
        if re.match(r'^time=\S+\s+level=(?:INFO|DEBUG)\s+source=\S+\s+msg="offload to (?:cpu|cuda|vulkan)"(?:\s|$)', line, re.I):
            fields = re.findall(r'(?:^|\s)layers\.(offload|model)=(\S+)', line)
            check(len(fields) == 2 and {key for key, _ in fields} == {"offload", "model"}
                and all(re.fullmatch(r"[0-9]{1,4}", value) for _, value in fields), "structured-offload-fields")
            values = {key: int(value) for key, value in fields}
            counts.add((values["offload"], values["model"]))
            structured = True
        match = re.match(r"load_backend:\s+loaded (CPU|CUDA|Vulkan) backend\b", line, re.I) or re.match(
            r'^time=\S+\s+level=INFO\s+source=\S+\s+msg="inference compute".*\blibrary=(cpu|cuda|vulkan)(?:\s|$)', line, re.I)
        if match:
            runtimes.add(match.group(1).upper())
        match = re.fullmatch(r"(?:load_tensors|llama_model_load_tensors|llama_context|llama_kv_cache|sched_reserve):\s+"
            r"(CPU|CUDA[0-9]*|Vulkan[0-9]*)\s+(model|KV|compute|output) buffer size\s*=\s*([0-9]+(?:\.[0-9]+)?) MiB\s*", line, re.I)
        if match:
            device, kind, size = match.groups()
            amount = float(size)
            check(math.isfinite(amount) and 0 <= amount <= 2**40, "placement-buffer-size")
            runtime_name = re.sub(r"[0-9]+$", "", device).upper()
            runtimes.add(runtime_name)
            buffers.append({"runtime": runtime_name, "device": device.upper(), "kind": kind.lower(), "mib": amount})
    check(len(counts) == 1, "offload-count-missing-or-conflicting")
    offloaded, total = next(iter(counts))
    check(0 < offloaded < total == summary["model"]["layers"] and offloaded == summary["budget"]["layers"]
        and "CUDA" in runtimes and "VULKAN" not in runtimes
        and any(row["device"] == "CUDA0" and row["kind"] == "model" and row["mib"] > 0 for row in buffers), "partial-cuda-not-observed")
    expected = {"schema_version": 1, "scope": "run-log-observation-only", "status": "GPU_OFFLOAD_OBSERVED",
        "offloaded_layers": offloaded, "total_layers": total, "offload_count_source": "native" if native else "structured" if structured else "none",
        "runtimes": sorted(runtimes), "buffers": buffers, "gpu_offload_observed": True, "gpu_qualified": False,
        "multi_gpu_qualified": False, "errors": [], "warnings": [], "log_sha256": sha256(startup).hexdigest()}
    check(same(summary["placement"], expected), "placement-raw-log-join")
    before = None
    quant = "Q4_K_M" if summary["model_profile"] == "8b-q4" else "Q8_0"
    for name in ("loaded_models_ready", "loaded_models_end"):
        value = summary[name]
        comparison.exchange(value)
        check(type(value["status"]) is int and value["status"] == 200 and value["request"] is None, "loaded-model-http")
        keys(value["body"], ("models",), "loaded-model-fields")
        models = value["body"]["models"]
        check(type(models) is list and len(models) == 1, "loaded-model-count")
        model = models[0]
        check(type(model) is dict and model.get("name") == model.get("model") == summary["alias"]
            and hex_digest(model.get("digest")) and integer(model.get("size"), 1)
            and integer(model.get("size_vram"), 1) and type(model.get("context_length")) is int and model["context_length"] == 2048
            and type(model.get("details")) is dict and model["details"].get("quantization_level") == quant, "loaded-model-binding")
        bound = {key: model[key] for key in ("name", "model", "digest", "size", "size_vram", "context_length", "details")}
        check(before is None or same(bound, before), "loaded-model-changed")
        before = bound
    return expected


def verify_bridge(summary):
    report = summary["bridge_report"]
    check(type(report) is dict and report.get("outcome") == "COMPLETE" and report.get("output_allowed") is True
        and type(report.get("dispatch_count")) is int and report["dispatch_count"] == 2
        and report.get("cancellation_requested") is False and report.get("deadline_exceeded") is False, "bridge-incomplete")
    directory = absolute(report["run_directory"])
    verdict = bridge.replay(directory)
    check(verdict["verdict"] == "PASS" and verdict["run_outcome"] == "COMPLETE", "bridge-raw-replay")
    paths = sorted(directory.iterdir())
    accepted = load(raw_file(paths[0], 4 * 1024**2))["payload"]
    final = load(raw_file(paths[-1], 4 * 1024**2))["payload"]
    check(same(report, final) and accepted["prompt"] == "Reply with exactly this text and nothing else: CELLIVANE_OK"
        and same(accepted["messages"], [{"role": "system", "content": "Answer the user briefly and accurately. /no_think"},
            {"role": "user", "content": accepted["prompt"]}])
        and type(accepted["parallelism"]) is int and accepted["parallelism"] == 1
        and type(accepted["deadline_s"]) is int and accepted["deadline_s"] == 180, "bridge-input-binding")
    engines = accepted["engines"]
    check(type(engines) is list and len(engines) == 2 and {e["name"] for e in engines} == {"seed-reference", "ollama-candidate"}, "bridge-engines")
    seed_port, worker_port = summary["ports"]["seed"], summary["ports"]["worker"]
    for row in engines:
        name, reference = row["name"], row["name"] == "seed-reference"
        check(same(row, {"name": name, "kind": "openai" if reference else "ollama", "model": summary["alias"],
            "base_url": f"http://127.0.0.1:{seed_port}/v1" if reference else f"http://127.0.0.1:{worker_port}",
            "role": "reference" if reference else "candidate", "timeout_s": 120, "max_tokens": 128}), "bridge-engine-contract")
    result = report["results"]["seed-reference"]
    wanted = {"model": summary["alias"], "messages": accepted["messages"], "temperature": 0, "max_tokens": 128, "stream": False}
    check(same(load(comparison.wire(result["request_body"])), wanted), "bridge-seed-input")
    return {"status": result["http_status"], "body": result["raw_response"], "raw_response": result["response_body"], "request": wanted}


def verify_scheduler(summary, bridge_response):
    records = comparison.audit_records(absolute(summary["audit_directory"]))
    n = len(summary["rows"])
    check(len(records) == 3 * n + 10 and records[0]["kind"] == "soak_configuration", "audit-record-count")
    check(same(records[0]["value"], {"identity": summary["identity"], "plan": summary["plan"], "model_sha256": summary["model"]["sha256"]}), "audit-configuration")
    counts, seq, cursor, ids = dict.fromkeys(COUNTERS, 0), 0, 1, set()

    def event(record, kind, key=None, normalized=None):
        nonlocal seq
        seq += 1
        check(record["kind"] == "scheduler", "scheduler-audit-kind")
        expected = {"seq": seq, "kind": kind, "key": key, "execution": "computed" if kind in ("start", "finish") else None,
            "reason": "invalid-request" if kind == "reject" else "engine-closed" if kind == "close" else None,
            "response_sha256": digest(normalized) if normalized is not None else None,
            "active": 1 if kind == "start" else 0, "waiters": 0, "cache_entries": 0, "cache_bytes": 0, **counts}
        check(same(record["value"], expected), "scheduler-event-recompute")

    def answer(reply, wanted, row=None):
        nonlocal cursor
        comparison.exchange(reply)
        check(type(reply["status"]) is int and reply["status"] == 200 and same(reply["request"], wanted), "seed-answer-http-request")
        key = digest({"identity": summary["identity"], "inference": wanted})
        start, backend, finish = records[cursor:cursor + 3]
        cursor += 3
        counts["backend_calls"] += 1
        event(start, "start", key)
        check(backend["kind"] == "backend_exchange", "backend-audit-order")
        normalized = backend_receipt(backend["value"], wanted)
        if row is not None:
            check(type(row["backend_exchange_count"]) is int and row["backend_exchange_count"] == 1
                and same(row["backend_receipt"], backend["value"])
                and backend["value"]["elapsed_s"] <= row["wall_s"] + .000001, "row-backend-audit-join")
        counts["computed"] += 1
        event(finish, "finish", key, normalized)
        value = reply["body"]
        keys(value, ("id", "object", "created", "model", "choices", "usage", "cellivane"), "seed-response-fields")
        check(type(value["id"]) is str and str(UUID(value["id"])) == value["id"] and value["id"] not in ids
            and integer(value["created"]) and value["object"] == "chat.completion", "seed-response-id")
        ids.add(value["id"])
        check(same({name: value[name] for name in normalized}, normalized)
            and same(value["cellivane"], {"engine": "seed", "version": "0.1.0", "execution": "computed", "key": key,
                "backend_calls": counts["backend_calls"]}), "seed-normalized-key-join")
        return normalized["choices"][0]["message"]["content"]

    warm_text = answer(summary["warmup"]["response"], payload(summary["alias"], "Reply with only OK."), summary["warmup"])
    check(type(summary["warmup"]["exact"]) is bool and summary["warmup"]["exact"] == (warm_text.strip() == "OK"), "warmup-exact-observation")
    oversized = payload(summary["alias"], "must not dispatch")
    oversized["max_tokens"] = 129
    comparison.exchange(summary["oversize"])
    check(same(summary["oversize"], {"status": 400, "body": {"error": {"message": "invalid-request"}},
        "raw_response": summary["oversize"]["raw_response"], "request": oversized}), "oversize-response")
    counts["rejected"] += 1
    event(records[cursor], "reject")
    cursor += 1
    for index, row in enumerate(summary["rows"]):
        case = CASES[index % len(CASES)]
        text = answer(row["response"], payload(summary["alias"], case["prompt"]), row)
        check(type(row["exact"]) is bool and row["exact"] == (text.strip() == case["expected"]), "quality-observation-join")
    answer(bridge_response, bridge_response["request"])
    event(records[cursor], "close")
    cursor += 1
    state = {"engine": "seed", "version": "0.1.0", "model": summary["alias"], "identity": summary["identity"],
        "closed": True, "poisoned": False, "slots": 1, "active": 0, "inflight": 0, "waiters": 0, "max_waiters": 0,
        "cache_entries": 0, "cache_bytes": 0, "cache_entries_limit": 0, "cache_bytes_limit": 0, **counts, "event_seq": seq}
    check(cursor == len(records) - 1 and records[cursor]["kind"] == "shutdown"
        and same(summary["state"], state) and same(records[cursor]["value"], state), "scheduler-shutdown-state")
    directory = absolute(summary["audit_directory"])
    total_bytes = sum(path.stat().st_size for path in directory.iterdir())
    total = len(records)
    expected = {"session_id": directory.name, "records": total, "bytes": total_bytes, "record_limit": 10000,
        "byte_limit": 64 * 1024**2, "remaining_records": 10000 - total, "remaining_bytes": 64 * 1024**2 - total_bytes,
        "warning_threshold_percent": 80, "near_capacity": total * 100 >= 10000 * 80 or total_bytes * 100 >= 64 * 1024**2 * 80, "poisoned": False}
    check(same(summary["audit_status"], expected), "audit-capacity-status")
    return total


def replay(summary_path, source_root=None):
    path = absolute(str(summary_path))
    summary = load(raw_file(path, 32 * 1024**2))
    keys(summary, ("schema_version", "family", "run_id", "mode", "outcome", "error", "acceptance", "acceptance_errors",
        "duration_s", "minimum_responses", "guards", "model_profile", "model", "rows", "cases", "system", "corpus_sha256",
        "source", "ports", "cleanup", "measurement_scope", "model_file", "preflight", "budget", "backend", "launch_probe",
        "alias", "plan", "configuration", "identity", "keep_alive", "version", "modelfile", "audit_directory", "warmup",
        "loaded_models_ready", "startup_log", "placement", "oversize", "service_start_s", "service_end_s", "bridge_report",
        "loaded_models_end", "state", "audit_status", "telemetry", "telemetry_errors", "resource_guard_reason", "cleanup_errors",
        "ports_closed", "model_unchanged", "source_unchanged", "backend_unchanged", "log", "metrics"), "summary-fields")
    check(type(summary["schema_version"]) is int and summary["schema_version"] == 1 and summary["family"] == "cellivane-large-model-soak-v1"
        and summary["outcome"] == "COMPLETED" and summary["acceptance"] == "PASS" and summary["error"] is None
        and summary["acceptance_errors"] == [], "soak-not-completed-or-accepted")
    check(type(summary["run_id"]) is str and str(UUID(summary["run_id"])) == summary["run_id"] and path.parent.name == summary["run_id"], "run-id-directory")
    mode, duration = summary["mode"], summary["duration_s"]
    check(mode in ("smoke", "soak") and type(duration) is int
        and ((mode == "smoke" and 30 <= duration <= 300) or (mode == "soak" and 900 <= duration <= 3600))
        and type(summary["minimum_responses"]) is int and summary["minimum_responses"] == (4 if mode == "smoke" else 24), "soak-window-profile")
    check(same(summary["guards"], GUARDS) and same(summary["cases"], CASES) and summary["system"] == comparison.SYSTEM
        and summary["corpus_sha256"] == digest(CASES), "guards-or-corpus-changed")
    check(same(summary["measurement_scope"], {"ttft": "NOT_MEASURED", "device_memory": "global-device-total-not-process-VRAM",
        "ram": "global-host-available-not-process-reservation", "backend_kv_reuse": "backend-controlled-not-disabled",
        "native_runtime_gpu_qualified": False, "native_mtp": False, "general_quality": False}), "unsupported-measurement-claim")
    check(summary["model_profile"] in MODELS and same(summary["model"], MODELS[summary["model_profile"]]), "model-profile-pin")
    model = summary["model"]
    model_file = summary["model_file"]
    keys(model_file, ("path", "bytes", "sha256"), "model-file-fields")
    model_path = absolute(model_file["path"])
    check(model_path.name == model["filename"] and type(model_file["bytes"]) is int and model_file["bytes"] == model["bytes"]
        and model_file["sha256"] == model["sha256"] and model_path.stat().st_size == model["bytes"]
        and file_hash(model_path, model["bytes"]) == model["sha256"], "model-file-changed")
    verify_sources(summary["source"], path.parent, source_root)
    verify_assets(summary["backend"])
    launch = resource_evidence(summary["launch_probe"])
    check(launch["memory"]["available_bytes"] >= GUARDS["minimum_ram_free_bytes"]
        and launch["gpu"]["free_bytes"] >= GUARDS["minimum_vram_free_bytes"]
        and launch["gpu"]["temperature_c"] < GUARDS["maximum_temperature_c"], "launch-resource-guard")
    ram_required = model["bytes"] + 7 * 1024**3
    usable = launch["gpu"]["free_bytes"] - int(1.5 * 1024**3) - 768 * 1024**2
    layers = min(model["layers"] - 1, int(usable // (model["bytes"] / model["layers"] * 1.15)))
    check(launch["memory"]["available_bytes"] >= ram_required and 1 <= layers < model["layers"]
        and same(summary["budget"], {"layers": layers, "ram_required_bytes": ram_required,
            "vram_headroom_bytes": int(1.5 * 1024**3), "vram_workspace_bytes": 768 * 1024**2,
            "layer_estimate_safety_factor": 1.15, "scope": "declared-preflight-not-reservation-or-fit-proof"}), "budget-recompute")
    initial = summary["preflight"]
    check(initial["memory"]["available_bytes"] >= ram_required
        and initial["gpu"]["free_bytes"] - int(1.5 * 1024**3) - 768 * 1024**2 >= model["bytes"] / model["layers"] * 1.15,
        "initial-resource-budget")
    alias = "cellivane-soak-" + summary["model_profile"] + ":latest"
    check(summary["alias"] == alias, "model-alias")
    options = {"num_ctx": 2048, "num_thread": 4, "num_gpu": layers, "temperature": 0}
    plan = {"schema_version": 1, "backend": "ollama", "profile": "hybrid", "num_ctx": 2048,
        "num_thread": 4, "slots": 1, "num_gpu": layers, "temperature": 0, "scope": "requested-placement-only"}
    configuration = {"schema_version": 1, "alias": alias, "options": options,
        "environment": {"CUDA_VISIBLE_DEVICES": "0", "HIP_VISIBLE_DEVICES": "-1", "ROCR_VISIBLE_DEVICES": "-1",
            "OLLAMA_VULKAN": "0", "OLLAMA_NO_CLOUD": "1", "OLLAMA_NUM_PARALLEL": "1", "OLLAMA_MAX_LOADED_MODELS": "1",
            "OLLAMA_CONTEXT_LENGTH": "2048", "OLLAMA_DEBUG": "1"},
        "device_scope": "one visible NVIDIA device for hybrid/auto; CPU-only for cpu"}
    check(same(summary["plan"], plan) and same(summary["configuration"], configuration)
        and summary["identity"] == digest({"model_sha256": model["sha256"], "backend_tree_sha256": summary["backend"]["tree_sha256"],
            "configuration": configuration}) and summary["keep_alive"] == "30m" and same(summary["version"], {"version": OLLAMA_VERSION}), "execution-configuration")
    modelfile = artifact(summary["modelfile"], 4096).decode("utf-8").splitlines()
    check(modelfile == ['FROM "' + str(model_path).replace("\\", "/") + '"'] +
        [f"PARAMETER {key} {value}" for key, value in options.items()], "modelfile-binding")
    keys(summary["ports"], ("seed", "worker"), "ports-fields")
    check(all(integer(summary["ports"][name], 1024, 65536) for name in ("seed", "worker"))
        and summary["ports"]["seed"] != summary["ports"]["worker"]
        and same(summary["ports_closed"], {str(port): True for port in summary["ports"].values()}), "ports-not-closed")
    check(all(summary[field] is True for field in ("source_unchanged", "model_unchanged", "backend_unchanged"))
        and summary["cleanup_errors"] == [], "changed-artifact-or-cleanup-error")
    start, end = summary["service_start_s"], summary["service_end_s"]
    check(number(start) and number(end) and duration <= end - start <= duration + 120, "service-window-incomplete-or-drain-overrun")
    rows = summary["rows"]
    check(type(rows) is list and summary["minimum_responses"] <= len(rows) <= GUARDS["maximum_requests"], "soak-response-count")
    previous, drains = None, 0
    for index, row in enumerate([summary["warmup"], *rows]):
        keys(row, ("index", "case", "started_s", "completed_s", "wall_s", "response", "backend_exchange_count", "backend_receipt", "exact"), "response-row-fields")
        check(all(number(row[name]) for name in ("started_s", "completed_s", "wall_s")) and 0 < row["wall_s"] <= 120
            and abs(row["completed_s"] - row["started_s"] - row["wall_s"]) <= .000001, "request-timing")
        if index == 0:
            check(type(row["index"]) is int and row["index"] == -1 and row["case"] == "warmup" and row["completed_s"] <= start, "warmup-window")
        else:
            check(type(row["index"]) is int and row["index"] == index - 1 and row["case"] == CASES[(index - 1) % len(CASES)]["id"]
                and 0 <= row["started_s"] - start < duration and row["completed_s"] <= end, "request-admission-window")
            if previous is not None:
                check(row["started_s"] >= previous["completed_s"]
                    and row["started_s"] - previous["started_s"] >= .5 - .002, "request-overlap-or-start-rate")
                check(row["started_s"] - previous["completed_s"] <= 10, "continuous-admission-idle-gap")
            else:
                check(row["started_s"] - start <= 10, "continuous-admission-first-gap")
            drains += row["completed_s"] > start + duration
            previous = row
    check(drains <= 1, "multiple-drained-requests")
    check(end - rows[-1]["completed_s"] <= 10, "continuous-admission-end-gap")
    samples = verify_telemetry(summary)
    verify_placement(summary)
    bridge_response = verify_bridge(summary)
    records = verify_scheduler(summary, bridge_response)
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
            and row["process_error"] is None and row["job_error"] is None
            and row["backend_stop_api_confirmed"] is False and row["kv_release_confirmed"] is False, "cleanup-unconfirmed")
        check(row["name"] != "create" or row["returncode"] == 0, "create-failed")
        pids.add(row["pid"])
    expected_metrics = {"responses": len(rows), "exact": sum(row["exact"] for row in rows),
        "median_wall_s": statistics.median(row["wall_s"] for row in rows), "scope": "repeated-fixed-corpus-not-general-quality-or-cold-throughput"}
    check(same(summary["metrics"], expected_metrics), "metrics-recompute")
    return {"verdict": "PASS", "scope": "recorded-ollama-soak-integrity", "run_id": summary["run_id"], "run_mode": mode,
        "admission_window_s": duration, "recorded_service_s": end - start, "computed_responses": len(rows), "drained_requests": drains,
        "resource_samples": len(samples), "audit_records": records, "source_files_checked": len(SOURCE_PATHS),
        "current_source_files_compared": source_root is not None, "offloaded_layers": layers,
        "claims": {"ttft_measured": False, "process_exclusive_vram_measured": False, "host_or_endpoint_attestation": False,
            "native_runtime_gpu_qualified": False, "quality_generalization": False, "backend_kv_reuse_disabled": False, "speedup_guaranteed": False}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary")
    parser.add_argument("--source-root")
    args = parser.parse_args(argv)
    try:
        result = replay(args.summary, args.source_root)
    except (ValueError, KeyError, TypeError, AttributeError, OSError, UnicodeError, zipfile.BadZipFile) as exc:
        result = {"verdict": "FAIL", "scope": "recorded-ollama-soak-integrity",
            "error": type(exc).__name__ + ":" + str(exc)[:512]}
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
