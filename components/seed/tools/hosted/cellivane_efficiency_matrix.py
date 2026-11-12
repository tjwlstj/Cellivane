"""Join six pre-existing ABC/CBA calibrations and frozen reader receipts.

Pipeline artifact tooling only: no model, subprocess, HTTP or upstream code is
executed.  The pure policy is loaded from the byte-checked source21 tree.
Unkeyed local hashes/receipts do not provide host or execution attestation.
Input CLI order declares ABC/CBA order; it does not reconstruct a trusted clock.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import sys
import types
from uuid import UUID


SOURCE_PATHS = frozenset(
    {"hosted/experimental/cellivane_bridge/" + name + ".py" for name in
     ("__init__", "__main__", "adapters", "cli", "contracts", "runtime", "storage")}
    | {"hosted/experimental/cellivane_seed/" + name + ".py" for name in
       ("__init__", "__main__", "core", "server", "ollama", "placement", "efficiency")}
    | {"tools/hosted/" + name + ".py" for name in
       ("cellivane_bridge_lab", "cellivane_seed_lab", "cellivane_seed_compare", "cellivane_seed_soak",
        "cellivane_resource_probe", "cellivane_seed_optimize", "cellivane_log_cursor")})
VERIFICATION_PATHS = frozenset("tools/hosted/" + name + ".py" for name in
    ("verify_cellivane_efficiency", "verify_cellivane_soak", "verify_cellivane_comparison", "verify_cellivane_bridge"))
MAIN_READER = "tools/hosted/verify_cellivane_efficiency.py"
POLICY = "hosted/experimental/cellivane_seed/efficiency.py"
ORDER = ("reference", "gpu29", "gpu29-threads8", "gpu29-threads8", "gpu29", "reference")
SCOPE = "recorded-efficiency-single-run-integrity-and-bounded-log-work"
HEX = re.compile(r"[0-9a-f]{64}\Z")
SIDECAR_KEYS = frozenset(("argv", "returncode", "stdout_sha256", "stderr_sha256", "verifier_sha256",
                         "summary_sha256_before", "summary_sha256_after", "verification_source_sha256"))
VERDICT_KEYS = frozenset(("verdict", "scope", "run_id", "mode", "profile", "computed_responses", "exact",
    "drained_requests", "recorded_service_s", "resource_samples", "source_files_checked", "current_source_files_compared",
    "audit_records", "audit_timings", "log_work", "observed_gpu_layers", "observed_native_threads", "claims"))
CLAIM_KEYS = frozenset(("hardware_winner_selected", "speedup_guaranteed", "native_runtime_gpu_qualified", "ttft_measured",
    "process_exclusive_vram_measured", "host_or_endpoint_attestation", "backend_kv_reuse_disabled", "quality_generalization",
    "timing_intervals_are_disjoint"))
MODEL = {"filename": "Qwen3-8B-Q4_K_M.gguf", "bytes": 5_027_783_488,
         "sha256": "d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785", "layers": 37}


def check(condition, reason):
    if not condition:
        raise ValueError(reason)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return sha256(encoded(value)).hexdigest()


def same(left, right):
    return encoded(left) == encoded(right)


def _pairs(rows):
    result = {}
    for key, value in rows:
        check(key not in result, "duplicate-json-key")
        result[key] = value
    return result


def load(raw):
    def invalid(_value):
        raise ValueError("nonfinite-json")
    result = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs, parse_constant=invalid)
    encoded(result)  # Also rejects finite JSON literals that overflow a float.
    return result


def integer(value, minimum=0, maximum=2 ** 63 - 1):
    return type(value) is int and minimum <= value <= maximum


def number(value, maximum=3600):
    return type(value) in (int, float) and 0 < value <= maximum and math.isfinite(value)


def hex_digest(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def absolute(value, *, exists=True):
    path = Path(value)
    check(path.is_absolute() and not str(path).startswith(("\\\\", "//")), "absolute-local-path-required")
    check(not path.is_symlink(), "symlink-input")
    return path.resolve(strict=exists)


def read(path, maximum):
    path = absolute(path)
    check(path.is_file(), "regular-file-required")
    before = path.stat()
    check(before.st_size <= maximum, "input-file-bound")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    after = path.stat()
    check(len(raw) <= maximum and (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
          and len(raw) == before.st_size, "input-changed-during-read")
    return raw


def file_record(path, raw):
    return {"path": str(absolute(path)), "bytes": len(raw), "sha256": sha256(raw).hexdigest()}


def hash_map(value, paths, reason):
    check(type(value) is dict and set(value) == paths and all(hex_digest(item) for item in value.values()), reason)
    return dict(value)


def current_hashes(root, paths):
    return {name: sha256(read(root / name, 4 * 1024 ** 2)).hexdigest() for name in sorted(paths)}


def host_profile(value):
    check(type(value) is dict and set(value) == {"logical_processors", "ram_total_bytes", "gpu"}, "host-profile-fields")
    check(integer(value["logical_processors"], 8, 4096) and integer(value["ram_total_bytes"], 1), "host-profile-cpu-ram")
    gpu = value["gpu"]
    check(type(gpu) is dict and set(gpu) == {"index", "name", "driver_version", "total_bytes"}, "host-profile-gpu-fields")
    check(type(gpu["index"]) is int and gpu["index"] == 0 and integer(gpu["total_bytes"], 1), "host-profile-gpu-counts")
    for name in ("name", "driver_version"):
        check(type(gpu[name]) is str and 1 <= len(gpu[name].encode("utf-8")) <= 256
              and all(ord(char) >= 32 for char in gpu[name]), "host-profile-gpu-text")
    return load(encoded(value))


def policy_from(root):
    name = "_cellivane_frozen_efficiency_policy"
    module = types.ModuleType(name)
    module.__file__ = str(root / POLICY)
    sys.modules[name] = module
    exec(compile(read(root / POLICY, 4 * 1024 ** 2), str(root / POLICY), "exec"), module.__dict__)
    return module


def verify_invocation(value, *, summary_path, summary_raw, verdict_raw, stderr_raw, root, verification):
    check(type(value) is dict and set(value) == SIDECAR_KEYS, "reader-sidecar-fields")
    check(type(value["returncode"]) is int and value["returncode"] == 0, "reader-exit-code")
    check(value["stdout_sha256"] == sha256(verdict_raw).hexdigest()
          and value["stderr_sha256"] == sha256(stderr_raw).hexdigest() and stderr_raw == b"", "reader-output-join")
    check(value["summary_sha256_before"] == value["summary_sha256_after"] == sha256(summary_raw).hexdigest(),
          "reader-summary-before-after-join")
    hashes = hash_map(value["verification_source_sha256"], VERIFICATION_PATHS, "reader-closure-fields")
    check(hashes == verification and value["verifier_sha256"] == verification[MAIN_READER], "reader-closure-changed")
    argv = value["argv"]
    check(type(argv) is list and all(type(part) is str and 0 < len(part) <= 4096 for part in argv), "reader-argv-type")
    check(len(argv) in (5, 6), "reader-argv-count")
    offset = 2 if len(argv) == 6 else 1
    check(len(argv) != 6 or argv[1] == "-B", "reader-python-flag")
    check(absolute(argv[0]).is_file() and absolute(argv[offset]) == root / MAIN_READER
          and absolute(argv[offset + 1]) == summary_path and argv[offset + 2] == "--source-root"
          and absolute(argv[offset + 3]) == root, "reader-argv-binding")


def verify_verdict(value, summary, profile, *, exact):
    check(type(value) is dict and set(value) == VERDICT_KEYS, "reader-verdict-fields")
    check(value["verdict"] == "PASS" and value["scope"] == SCOPE and value["run_id"] == summary["run_id"]
          and value["mode"] == "calibrate" and value["profile"] == profile.name, "reader-verdict-identity")
    expected = {"computed_responses": 56, "exact": exact, "drained_requests": 0, "source_files_checked": 21,
                "observed_gpu_layers": profile.num_gpu, "observed_native_threads": profile.num_thread}
    check(all(type(value[name]) is int and value[name] == wanted for name, wanted in expected.items())
          and value["current_source_files_compared"] is True, "reader-verdict-counts")
    check(number(value["recorded_service_s"]) and value["recorded_service_s"] == summary["service_end_s"] - summary["service_start_s"],
          "reader-service-duration-join")
    check(integer(value["resource_samples"], 1) and integer(value["audit_records"], 1)
          and type(value["audit_timings"]) is int and value["audit_timings"] == value["audit_records"], "reader-telemetry-audit-counts")
    claims = value["claims"]
    check(type(claims) is dict and set(claims) == CLAIM_KEYS and all(item is False for item in claims.values()), "reader-claim-scope")
    work = value["log_work"]
    check(type(work) is dict and set(work) == {"bytes", "polls", "bytes_read", "bytes_scanned"}
          and all(integer(item, 1) for item in work.values()) and work["polls"] == 59
          and work["bytes"] == summary["log"]["bytes"], "reader-log-work-join")


def samples_from(summary):
    cases = summary["cases"]
    check(type(cases) is list and len(cases) == 14 and summary["corpus_sha256"] == digest(cases), "case-corpus-digest")
    ids = []
    for case in cases:
        check(type(case) is dict and set(case) == {"id", "prompt", "expected"}
              and all(type(item) is str and item for item in case.values()), "case-fields")
        ids.append(case["id"])
    check(len(set(ids)) == 14 and type(summary["system"]) is str and summary["system"], "case-catalog")
    rows = summary["rows"]
    check(type(rows) is list and len(rows) == 56 and type(summary["repeat"]) is int and summary["repeat"] == 4, "matrix-response-count")
    samples, exact = [], 0
    for index, row in enumerate(rows):
        check(type(row) is dict and type(row.get("index")) is int and row["index"] == index
              and row.get("case") == ids[index % 14] and number(row.get("wall_s")), "matrix-row-order-or-wall")
        response, backend = row["response"], row["backend_receipt"]
        check(type(response) is dict and type(response.get("status")) is int and response["status"] == 200, "matrix-response-http")
        body = response["body"]
        choices = body["choices"]
        check(type(choices) is list and len(choices) == 1 and choices[0]["finish_reason"] == "stop"
              and choices[0]["message"]["role"] == "assistant", "matrix-response-stop")
        text = choices[0]["message"]["content"]
        check(type(text) is str and 0 < len(text.encode("utf-8")) <= 256 * 1024
              and type(backend) is dict and backend.get("outcome") == "ANSWERED" and backend.get("text") == text,
              "matrix-response-text-join")
        matches = text.strip() == cases[index % 14]["expected"]
        check(type(row["exact"]) is bool and row["exact"] == matches, "matrix-exact-join")
        exact += matches
        samples.append({"case_id": row["case"], "repeat": index // 14,
                        "wall_s": row["wall_s"], "text_sha256": sha256(text.encode("utf-8")).hexdigest()})
    return samples, exact


def collect(summaries, verdicts, invocations, stderrs, source_root):
    check(all(type(items) is list and len(items) == 6 for items in (summaries, verdicts, invocations, stderrs)), "six-run-inputs-required")
    root = absolute(source_root)
    check(root.is_dir(), "source-root-directory")
    current_sources = current_hashes(root, SOURCE_PATHS)
    verification = current_hashes(root, VERIFICATION_PATHS)
    policy = policy_from(root)
    check(sha256(read(root / POLICY, 4 * 1024 ** 2)).hexdigest() == current_sources[POLICY], "policy-changed-during-import")
    reports = {profile.name: {"profile": profile.record(), "identity": None, "outcome": "PASS",
                              "resource_guard_passed": True, "rounds": []} for profile in policy.PROFILES}
    ordered, files, seen_ids, common_host, common_binding = [], [], set(), None, None
    for position, (summary_file, verdict_file, invocation_file, stderr_file) in enumerate(zip(summaries, verdicts, invocations, stderrs)):
        paths = [absolute(path) for path in (summary_file, verdict_file, invocation_file, stderr_file)]
        raws = [read(path, bound) for path, bound in zip(paths, (32 * 1024 ** 2, 256 * 1024, 256 * 1024, 16 * 1024))]
        summary, verdict, invocation = [load(raw) for raw in raws[:3]]
        check(type(summary) is dict and type(summary.get("schema_version")) is int and summary["schema_version"] == 1
              and summary.get("family") == "cellivane-efficiency-run-v1" and summary.get("mode") == "calibrate"
              and summary.get("outcome") == "COMPLETED" and summary.get("acceptance") == "PASS"
              and summary.get("acceptance_errors") == [] and summary.get("error") is None, "calibration-not-terminal-pass")
        run_id = summary["run_id"]
        check(type(run_id) is str and str(UUID(run_id)) == run_id and run_id not in seen_ids and paths[0].parent.name == run_id,
              "run-id-directory-or-duplicate")
        seen_ids.add(run_id)
        profile = policy.get_profile(ORDER[position])
        check(same(summary["profile"], profile.record()) and same(summary["plan"], profile.record()), "ABC-CBA-profile-order")
        check(summary["model_profile"] == "8b-q4" and same(summary["model"], MODEL), "fixed-model-pin")
        host = host_profile(summary["host_profile"])
        observation = summary["launch_probe"]["observation"]
        check(host["ram_total_bytes"] == observation["memory"]["total_bytes"]
              and same(host["gpu"], {key: observation["gpu"][key] for key in host["gpu"]}), "host-launch-observation-join")
        source = summary["source"]
        check(type(source) is dict and set(source) == {"root", "sha256", "scope"}
              and absolute(source["root"]) == root and source["scope"] == "declared-21-file-efficiency-family-not-loader-attestation",
              "source-family-scope")
        hashes = hash_map(source["sha256"], SOURCE_PATHS, "source21-map")
        check(hashes == current_sources, "source21-live-byte-mismatch")
        for name in SOURCE_PATHS:
            check(sha256(read(paths[0].parent / "source-snapshot" / name, 4 * 1024 ** 2)).hexdigest() == hashes[name], "source21-snapshot-mismatch")
        backend = summary["backend"]
        check(backend["version"] == "0.40.2" and hex_digest(backend["tree_sha256"]), "backend-version-or-digest")
        binding = {"model": summary["model"], "backend": {"version": backend["version"], "tree_sha256": backend["tree_sha256"],
                   "executable_sha256": backend["executable"]["sha256"], "archive_sha256": backend["archive"]["sha256"]},
                   "source_sha256": hashes, "cases": summary["cases"], "system": summary["system"], "corpus_sha256": summary["corpus_sha256"]}
        check(common_host is None or same(common_host, host), "matrix-host-profile-mismatch")
        check(common_binding is None or same(common_binding, binding), "matrix-model-backend-source-corpus-mismatch")
        common_host, common_binding = host, binding
        check(all(summary.get(name) is True for name in ("model_unchanged", "backend_unchanged", "source_unchanged"))
              and summary.get("telemetry_errors") == [] and summary.get("resource_guard_reason") is None
              and summary.get("cleanup_errors") == [], "run-resource-or-artifact-guard")
        samples, exact = samples_from(summary)
        verify_verdict(verdict, summary, profile, exact=exact)
        verify_invocation(invocation, summary_path=paths[0], summary_raw=raws[0], verdict_raw=raws[1], stderr_raw=raws[3], root=root, verification=verification)
        identity = {"model_sha256": MODEL["sha256"], "backend_tree_sha256": backend["tree_sha256"],
                    "corpus_sha256": summary["corpus_sha256"], "source_sha256": digest(hashes)}
        report = reports[profile.name]
        report["identity"] = identity
        report["rounds"].append({"index": position // 3, "samples": samples})
        records = {name: file_record(path, raw) for name, path, raw in zip(("summary", "reader_stdout", "reader_invocation", "reader_stderr"), paths, raws)}
        files.extend((path, raw) for path, raw in zip(paths, raws))
        ordered.append({"position": position, "round": position // 3, "profile": profile.name, "run_id": run_id,
                        "records": records, "reader_verdict": verdict})
    candidate_reports = [reports[profile.name] for profile in policy.PROFILES]
    decision = policy.choose_profile(candidate_reports)
    check(decision["eligible"] is True, "reference-selection-not-eligible")
    selection = {"schema_version": 1, "family": "cellivane-efficiency-selection-v1",
                 "host_profile": common_host, "candidate_reports": candidate_reports}
    check(len(encoded(selection)) <= 256 * 1024, "selection-256KiB-bound")
    check(current_hashes(root, SOURCE_PATHS) == current_sources and current_hashes(root, VERIFICATION_PATHS) == verification,
          "source-or-reader-changed-during-collection")
    check(all(read(path, len(raw)) == raw for path, raw in files), "matrix-input-changed-during-collection")
    receipt = {"schema_version": 1, "family": "cellivane-efficiency-matrix-v1", "collected_at_utc": datetime.now(timezone.utc).isoformat(),
               "host_profile": common_host, "identity": candidate_reports[0]["identity"], "ordered_runs": ordered,
               "source_sha256": current_sources, "verification_source_sha256": verification,
               "selection_canonical_sha256": digest(selection), "decision": decision,
               "scope": {"input_order": "caller-declared-ABC-CBA-order-not-clock-attestation",
                         "integrity": "local-unkeyed-record-and-reader-receipt-joins-not-host-attestation",
                         "selection": "measured-selection-for-this-model-backend-host-only",
                         "final_soak_completed": False, "full_regression_completed": False}}
    return selection, receipt


def write_exclusive(path, value, maximum):
    path = absolute(path, exists=False)
    check(path.parent.is_dir(), "output-parent-directory")
    raw = encoded(value) + b"\n"
    check(len(raw) <= maximum, "output-file-bound")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        __import__("os").fsync(stream.fileno())
    return file_record(path, raw)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("summary", "verdict", "invocation", "stderr"):
        parser.add_argument("--" + name, action="append", required=True, help="Repeat six times in ABC/CBA order")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args(argv)
    try:
        output, receipt_path = absolute(args.output, exists=False), absolute(args.receipt, exists=False)
        check(output != receipt_path and not output.exists() and not receipt_path.exists(), "exclusive-new-output-paths-required")
        selection, receipt = collect(args.summary, args.verdict, args.invocation, args.stderr, args.source_root)
        selection_raw = encoded(selection) + b"\n"
        selection_record = {"path": str(output), "bytes": len(selection_raw), "sha256": sha256(selection_raw).hexdigest()}
        receipt["selection_file"] = selection_record
        receipt_record = write_exclusive(receipt_path, receipt, 2 * 1024 ** 2)
        # Publish the auto-CLI input last: a receipt write failure leaves no
        # selectable artifact. A race on output leaves only an orphan receipt.
        check(write_exclusive(output, selection, 256 * 1024) == selection_record, "selection-write-join")
        print(json.dumps({"outcome": "COLLECTED", "selection": selection_record, "receipt": receipt_record,
                          "selected_profile": receipt["decision"]["selected_profile"]["name"]}, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        print(json.dumps({"outcome": "REJECTED", "error": type(exc).__name__ + ":" + str(exc)[:512]}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
