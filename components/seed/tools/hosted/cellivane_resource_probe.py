"""Bounded Windows RAM/GPU-0 observation, not reservation or qualification.

No model, server endpoint, process list, serial number or environment dump is
read. The caller attaches its own timestamp and decides how to use observations.
"""
from __future__ import annotations

import csv
import ctypes
import io
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

_UINT64_MAX = (1 << 64) - 1
_MIB = 1 << 20
_QUERY = ("index,name,driver_version,memory.total,memory.used,memory.free,"
          "utilization.gpu,temperature.gpu,power.draw")


def _uint(text: str, maximum: int = _UINT64_MAX) -> int:
    if not re.fullmatch(r"[0-9]{1,20}", text, flags=re.ASCII):
        raise ValueError("resource-unsigned-integer")
    value = int(text)
    if value > maximum:
        raise ValueError("resource-integer-bound")
    return value


def _number(text: str, maximum: float) -> float:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", text, flags=re.ASCII):
        raise ValueError("resource-number")
    value = float(text)
    if not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError("resource-number-bound")
    return value


def parse_gpu(csvtext: str) -> dict:
    """Parse the exact nine-column, one-row GPU-0 query, with MiB wire units."""
    if type(csvtext) is not str or not 1 <= len(csvtext.encode("utf-8", errors="strict")) <= 4096:
        raise ValueError("resource-gpu-csv")
    try:
        rows = list(csv.reader(io.StringIO(csvtext, newline=""), strict=True, skipinitialspace=True))
    except csv.Error as exc:
        raise ValueError("resource-gpu-csv") from exc
    if len(rows) != 1 or len(rows[0]) != 9:
        raise ValueError("resource-gpu-row-count-or-columns")
    index, name, driver, total, used, free, utilization, temperature, power = (value.strip() for value in rows[0])
    if (_uint(index) != 0 or not 1 <= len(name) <= 256 or name in ("N/A", "[N/A]")
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,4}", driver, flags=re.ASCII) or len(driver) > 64):
        raise ValueError("resource-gpu-identity")
    total_bytes, used_bytes, free_bytes = (
        _uint(value, _UINT64_MAX // _MIB) * _MIB for value in (total, used, free)
    )
    if total_bytes == 0 or used_bytes > total_bytes or free_bytes > total_bytes:
        raise ValueError("resource-gpu-memory")
    return {"source": "nvidia-smi", "index": 0, "name": name, "driver_version": driver,
            "total_bytes": total_bytes, "used_bytes": used_bytes, "free_bytes": free_bytes,
            "utilization_percent": _number(utilization, 100), "temperature_c": _number(temperature, 200),
            "power_w": None if power in ("N/A", "[N/A]") else _number(power, 10000)}


def _memory() -> dict:
    class Status(ctypes.Structure):
        _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
            (name, ctypes.c_uint64) for name in ("total_phys", "avail_phys", "total_page", "avail_page",
                                                "total_virtual", "avail_virtual", "avail_extended")]

    status = Status()
    status.length = ctypes.sizeof(status)
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(Status)]
    api.GlobalMemoryStatusEx.restype = ctypes.c_int
    if not api.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError(ctypes.get_last_error())
    total, available = status.total_phys, status.avail_phys
    if type(total) is not int or type(available) is not int or not 1 <= total <= _UINT64_MAX or not 0 <= available <= total:
        raise ValueError("resource-ram-bound")
    return {"source": "GlobalMemoryStatusEx", "available_bytes": available, "total_bytes": total}


def _system_directory() -> Path:
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GetSystemDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    api.GetSystemDirectoryW.restype = ctypes.c_uint32
    buffer = ctypes.create_unicode_buffer(32768)
    count = api.GetSystemDirectoryW(buffer, len(buffer))
    if not 0 < count < len(buffer):
        raise OSError("resource-system-directory")
    return Path(buffer.value)


def _smi_path() -> str:
    preferred = _system_directory() / "nvidia-smi.exe"
    if preferred.is_file():
        return str(preferred)
    found = shutil.which("nvidia-smi")
    if found is None:
        raise FileNotFoundError("resource-nvidia-smi")
    return found


def observe_with_evidence() -> dict:
    """Return one observation and the same GPU query's bounded raw evidence."""
    if os.name != "nt":
        raise RuntimeError("resource-probe-windows-only")
    memory = _memory()
    argv = [_smi_path(), "--id=0", "--query-gpu=" + _QUERY, "--format=csv,noheader,nounits"]
    process = subprocess.run(argv,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=5,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    if (process.returncode != 0 or type(process.returncode) is not int
            or type(process.stdout) is not bytes or type(process.stderr) is not bytes
            or len(process.stdout) > 16 * 1024 or len(process.stderr) > 16 * 1024):
        raise ValueError("resource-gpu-output-limit")
    stdout = process.stdout.decode("utf-8", errors="strict")
    stderr = process.stderr.decode("utf-8", errors="strict")
    gpu = parse_gpu(stdout)
    return {"observation": {"schema_version": 1, "memory": memory, "gpu": gpu},
            "gpu_raw": {"argv": argv, "returncode": 0, "stdout": stdout, "stderr": stderr}}


def observe() -> dict:
    """Return typed fresh observations, or raise if any mandatory query fails."""
    return observe_with_evidence()["observation"]
