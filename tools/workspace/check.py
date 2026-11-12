#!/usr/bin/env python3
"""Run isolated, model-free suites and retain fresh logs with honest skip/timeout status."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]


def classify_unittest_log(text: str, returncode: int | None, timed_out: bool = False) -> dict:
    runs = list(re.finditer(r"^Ran (\d+) tests? in [^\r\n]+$", text, re.MULTILINE))
    count = int(runs[-1].group(1)) if runs else None
    terminal = re.search(r"^OK(?: \(skipped=(\d+)\))?\s*\Z", text, re.MULTILINE)
    skipped = int(terminal.group(1) or 0) if terminal else None
    if timed_out:
        outcome, reason = "TIMEOUT", "suite_timeout"
    elif returncode != 0:
        outcome, reason = "FAIL", "nonzero_exit"
    elif not runs or not terminal or terminal.start() <= runs[-1].end():
        outcome, reason = "FAIL", "missing_final_unittest_summary"
    elif count == 0:
        outcome, reason = "FAIL", "no_tests_discovered"
    elif skipped is not None and skipped > count:
        outcome, reason = "FAIL", "invalid_skip_count"
    elif skipped == count:
        outcome, reason = "NOT_RUN", "all_tests_skipped"
    else:
        outcome, reason = ("PASS_WITH_SKIPS" if skipped else "PASS"), None
    return {"outcome": outcome, "reason": reason, "tests_collected": count,
            "skipped": skipped, "tests_executed": count - skipped if count is not None and skipped is not None else None,
            "returncode": returncode, "timed_out": timed_out}


def suite_spec(name: str) -> tuple[Path, list[str], Path]:
    if name == "seed":
        cwd = ROOT / "components/seed"
        return cwd, ["-m", "unittest", "discover", "-s", "tools/hosted/tests", "-p", "test_cellivane_*.py", "-v"], cwd / "tools/hosted/tests"
    if name == "testkit":
        return ROOT, ["-m", "unittest", "discover", "-s", "tools/testkit/tests", "-t", "tools/testkit", "-p", "test_*.py", "-v"], ROOT / "tools/testkit/tests"
    if name == "workspace":
        return ROOT, ["-m", "unittest", "discover", "-s", "tools/workspace/tests", "-p", "test_*.py", "-v"], ROOT / "tools/workspace/tests"
    return ROOT, ["-m", "unittest", "discover", "-s", "tools/hosted/tests", "-p", "test_*.py", "-v"], ROOT / "tools/hosted/tests"


def stop_owned_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        # This is the live process created by this runner; never target discovered PIDs.
        try:
            subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
        finally:
            if process.poll() is None:
                process.kill()
    else:
        os.killpg(process.pid, signal.SIGKILL)
    if process.poll() is None:
        process.kill()
    process.wait(timeout=30)


def run_suite(name: str, run_root: Path, timeout_seconds: int) -> dict:
    cwd, arguments, tests = suite_spec(name)
    log = run_root / (name + ".log")
    record = {"suite": name, "log": log.relative_to(ROOT).as_posix(), "command": [sys.executable, "-B", *arguments], "cwd": str(cwd)}
    if not tests.is_dir():
        log.write_text("Suite source directory is absent; tests were not run.\n", encoding="utf-8")
        return {**record, "outcome": "NOT_RUN", "reason": "suite_source_missing", "returncode": None, "timed_out": False}
    started = time.monotonic()
    timed_out = False
    interrupted = False
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    try:
        with log.open("xb") as stream:
            options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
            process = subprocess.Popen([sys.executable, "-B", *arguments], cwd=cwd, env=env,
                                       stdout=stream, stderr=subprocess.STDOUT, **options)
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                stop_owned_process(process)
            except KeyboardInterrupt:
                interrupted = True
                stop_owned_process(process)
        text = log.read_text(encoding="utf-8", errors="replace")
        result = {**record, **classify_unittest_log(text, process.returncode, timed_out),
                  "duration_seconds": round(time.monotonic() - started, 3)}
        if interrupted:
            result.update(outcome="CANCELLED", reason="runner_interrupted")
        return result
    except (OSError, subprocess.SubprocessError) as exc:
        return {**record, "outcome": "INFRA_ERROR", "reason": type(exc).__name__,
                "returncode": None, "timed_out": timed_out,
                "duration_seconds": round(time.monotonic() - started, 3)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("hosted", "testkit", "seed", "all"), default="all")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--json", action="store_true", help="Print a path-free summary; commands and machine paths remain in local reports")
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    names = ["workspace", "hosted", "testkit", "seed"] if args.suite == "all" else [args.suite]
    run_root = ROOT / "build/workspace" / ("check-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    run_root.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "scope": "local-model-free-regression-only", "outcome": "RUNNING",
              "model_runs": False, "native_qemu_runs": False, "requested_suites": names, "suites": []}
    summary_file = run_root / "summary.json"
    summary_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for name in names:
        if not args.json:
            print("Running " + name + "...", flush=True)
        record = run_suite(name, run_root, args.timeout_seconds)
        report["suites"].append(record)
        summary_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if not args.json:
            print("{suite}: {outcome}; tests={tests}; skipped={skips}; log={log}".format(
                **record, tests=record.get("tests_collected"), skips=record.get("skipped")), flush=True)
        if record["outcome"] == "CANCELLED":
            for pending in names[names.index(name) + 1:]:
                report["suites"].append({"suite": pending, "outcome": "NOT_RUN", "reason": "runner_interrupted", "returncode": None, "timed_out": False})
            break
    good = all(item["outcome"] in ("PASS", "PASS_WITH_SKIPS") for item in report["suites"])
    report["outcome"] = ("PASS_WITH_SKIPS" if any(item["outcome"] == "PASS_WITH_SKIPS" for item in report["suites"]) else "PASS") if good else "FAIL"
    summary_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.json:
        public = {k: v for k, v in report.items() if k != "suites"}
        public["suites"] = [{k: v for k, v in item.items() if k not in ("command", "cwd")} for item in report["suites"]]
        public["local_report"] = summary_file.relative_to(ROOT).as_posix()
        print(json.dumps(public, indent=2))
    else:
        print("Overall: " + report["outcome"] + "; report=" + summary_file.relative_to(ROOT).as_posix())
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
