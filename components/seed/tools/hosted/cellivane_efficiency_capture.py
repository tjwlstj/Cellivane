"""Preserve binary stdout/stderr and an invocation receipt for the independent reader.

No model server is started. The receipt is an unkeyed local record, not execution
attestation. Calibration captures can be joined by cellivane_efficiency_matrix.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

READERS = tuple("tools/hosted/" + name + ".py" for name in (
    "verify_cellivane_efficiency", "verify_cellivane_soak",
    "verify_cellivane_comparison", "verify_cellivane_bridge"))


def closure(root):
    return {name: sha256((root / name).read_bytes()).hexdigest() for name in READERS}


def write(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def capture(summary, source_root, *, matrix_receipt=None, matrix_only=False):
    summary = Path(summary).resolve(strict=True)
    root = Path(source_root).resolve(strict=True)
    if matrix_only and matrix_receipt is None:
        raise ValueError("matrix-receipt-required")
    before = sha256(summary.read_bytes()).hexdigest()
    readers = closure(root)
    directory = summary.parent / ("reader-capture-" + str(uuid4()))
    directory.mkdir()
    command = [sys.executable, "-B", str(root / READERS[0]), str(summary), "--source-root", str(root)]
    if matrix_receipt is not None:
        command.extend(("--matrix-receipt", str(Path(matrix_receipt).resolve(strict=True))))
    if matrix_only:
        command.append("--matrix-only")
    timed_out = False
    try:
        result = subprocess.run(command, cwd=root, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
    except subprocess.TimeoutExpired as exc:
        # subprocess.run has killed and waited for the reader. Preserve partial
        # binary diagnostics; None cannot satisfy a collector's exit-zero gate.
        timed_out = True
        result = subprocess.CompletedProcess(command, None, exc.stdout or b"", exc.stderr or b"")
    stdout = directory / "stdout.json"
    stderr = directory / "stderr.txt"
    invocation = directory / "invocation.json"
    write(stdout, result.stdout)
    write(stderr, result.stderr)
    after = sha256(summary.read_bytes()).hexdigest()
    receipt = {"argv": command, "returncode": result.returncode,
        "stdout_sha256": sha256(result.stdout).hexdigest(), "stderr_sha256": sha256(result.stderr).hexdigest(),
        "verifier_sha256": readers[READERS[0]], "summary_sha256_before": before,
        "summary_sha256_after": after, "verification_source_sha256": readers}
    write(invocation, (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    stable = before == after and readers == closure(root)
    try:
        verdict = json.loads(result.stdout.decode("utf-8"))["verdict"]
    except (UnicodeError, ValueError, KeyError, TypeError):
        verdict = "INVALID"
    passed = stable and result.returncode == 0 and not result.stderr and verdict == "PASS"
    return {"outcome": "PASS" if passed else "FAIL", "stable_inputs": stable, "timed_out": timed_out,
            "stdout": str(stdout), "stderr": str(stderr), "invocation": str(invocation)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--matrix-receipt")
    parser.add_argument("--matrix-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = capture(args.summary, args.source_root, matrix_receipt=args.matrix_receipt,
                         matrix_only=args.matrix_only)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result = {"outcome": "FAIL", "error": type(exc).__name__ + ":" + str(exc)[:256]}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
