#!/usr/bin/env python3
"""Check workspace tools; keep machine paths only in an explicitly requested report."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]


def inspect_tool(name: str, candidates: list[str], args: tuple[str, ...] = ("--version",)) -> dict:
    executable = next((p for p in candidates if p and Path(p).is_file()), None)
    if executable is None:
        executable = shutil.which(name)
    if executable is None:
        return {"name": name, "status": "MISSING", "path": None, "version": None}
    try:
        process = subprocess.run(
            [executable, *args], capture_output=True, timeout=10, check=False,
        )
        output = (process.stdout + process.stderr).decode("utf-8", errors="replace")
        version = re.search(r"\b\d+(?:\.\d+){1,3}(?:[-+][A-Za-z0-9.]+)?", output)
        return {
            "name": name, "status": "READY" if process.returncode == 0 else "UNAVAILABLE",
            "path": str(Path(executable).resolve()),
            "version": version.group(0) if process.returncode == 0 and version else None,
            "returncode": process.returncode, "detail": output[:4096],
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"name": name, "status": "UNAVAILABLE", "path": executable,
                "version": None, "error_type": type(exc).__name__}


def collect(native: bool = False) -> tuple[dict, dict]:
    config_path = ROOT / ".cellivane" / "local-tools.json"
    config = {}
    config_error = None
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8-sig"))
            if not isinstance(config, dict) or any(not isinstance(v, str) for v in config.values()):
                raise ValueError("Local tool config must be an object with string values")
        except (OSError, ValueError) as exc:
            config = {}
            config_error = type(exc).__name__
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    winlibs = local / "Microsoft/WinGet/Packages/BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe/mingw64/bin"
    elf = Path(config.get("x86_64_elf_root") or ROOT / ".toolchain/x86_64-elf")
    grub = Path(config.get("grub_root") or ROOT / ".toolchain/grub-2.12-for-windows")
    tools = [
        {"name": "python", "status": "READY" if sys.version_info[:2] == (3, 11) else "UNSUPPORTED",
         "version": platform.python_version(), "path": sys.executable},
        inspect_tool("git", [config.get("git", ""), r"C:\Program Files\Git\cmd\git.exe"]),
    ]
    native_specs = [
        ("make", [config.get("make", ""), str(local / "Microsoft/WinGet/Packages/ezwinports.make_Microsoft.Winget.Source_8wekyb3d8bbwe/bin/make.exe"), str(winlibs / "mingw32-make.exe")]),
        ("nasm", [config.get("nasm", ""), str(winlibs / "nasm.exe")]),
        ("x86_64-elf-gcc", [str(elf / "bin/x86_64-elf-gcc.exe")]),
        ("x86_64-elf-ld", [str(elf / "bin/x86_64-elf-ld.exe")]),
        ("x86_64-elf-objcopy", [str(elf / "bin/x86_64-elf-objcopy.exe")]),
        ("qemu-system-x86_64", [config.get("qemu", ""), r"C:\Program Files\QEMU\qemu-system-x86_64.exe"]),
        ("grub-mkimage", [str(grub / "grub-mkimage.exe")]),
        ("xorriso", [config.get("xorriso", "")]),
    ]
    for name, candidates in native_specs:
        item = inspect_tool(name, candidates, ("-version",) if name == "xorriso" else ("--version",))
        item["required"] = native
        tools.append(item)
    required_ok = all(t["status"] == "READY" for t in tools if t["name"] in ("python", "git") or t.get("required"))
    detailed = {
        "schema_version": 1, "scope": "workspace-tool-availability-only",
        "checked_at": datetime.now(timezone.utc).isoformat(), "workspace": str(ROOT),
        "platform": platform.system(), "native_required": native, "config_error": config_error,
        "outcome": "READY" if required_ok and config_error is None else "NOT_READY", "tools": tools,
        "runtime_tests_executed": False, "model_downloads": False,
    }
    public = {k: detailed[k] for k in ("schema_version", "scope", "checked_at", "platform", "native_required", "outcome", "runtime_tests_executed", "model_downloads")}
    public["config_error"] = config_error
    public["tools"] = [{k: t.get(k) for k in ("name", "status", "version")} for t in tools]
    return public, detailed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", action="store_true", help="Require native build/ISO/QEMU tools as well")
    parser.add_argument("--json", action="store_true", help="Print a path-free JSON summary and save machine details under build/workspace")
    args = parser.parse_args()
    public, detailed = collect(args.native)
    if args.json:
        report_root = ROOT / "build/workspace"
        report_root.mkdir(parents=True, exist_ok=True)
        report = report_root / ("doctor-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8] + ".json")
        with report.open("x", encoding="utf-8") as stream:
            json.dump(detailed, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        public["local_report"] = report.relative_to(ROOT).as_posix()
        print(json.dumps(public, ensure_ascii=False, indent=2))
    else:
        print("Workspace tools: " + public["outcome"] + " (availability only; no runtime/model validation)")
        for item in public["tools"]:
            print("{name}: {status}{version}".format(**{**item, "version": " " + item["version"] if item["version"] else ""}))
        if public["config_error"]:
            print("Local tool configuration could not be read: " + public["config_error"])
    return 0 if public["outcome"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
