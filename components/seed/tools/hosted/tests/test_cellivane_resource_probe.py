"""Resource observation boundaries; no models, GPU kernels or servers run."""
from __future__ import annotations

import importlib
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
probe = importlib.import_module("cellivane_resource_probe")
ROW = "0, NVIDIA GeForce RTX 5050, 617.42, 8151, 2503, 5408, 1, 34, 28.77\n"


def changed(index, value):
    fields = ROW.strip().split(", ")
    fields[index] = value
    return ", ".join(fields) + "\n"


class ResourceProbeTests(unittest.TestCase):
    def test_valid_row_preserves_exact_integer_mib_units_and_numeric_fields(self):
        value = probe.parse_gpu(ROW)
        self.assertEqual(set(value), {"source", "index", "name", "driver_version", "total_bytes", "used_bytes",
                                      "free_bytes", "utilization_percent", "temperature_c", "power_w"})
        self.assertEqual(value["total_bytes"], 8151 * 1048576)
        self.assertEqual(value["used_bytes"], 2503 * 1048576)
        self.assertEqual(value["free_bytes"], 5408 * 1048576)
        self.assertIs(type(value["total_bytes"]), int)
        self.assertEqual(value["power_w"], 28.77)
        self.assertIs(type(value["temperature_c"]), float)

    def test_only_power_may_be_unavailable(self):
        for value in ("N/A", "[N/A]"):
            self.assertIsNone(probe.parse_gpu(changed(8, value))["power_w"])
        for field in (1, 3, 4, 5, 6, 7):
            with self.subTest(field=field), self.assertRaises(ValueError):
                probe.parse_gpu(changed(field, "N/A"))
        self.assertEqual(probe.parse_gpu(changed(8, "0"))["power_w"], 0)

    def test_zero_or_two_gpu_rows_and_wrong_columns_rejected(self):
        for value in ("", "\n", ROW + ROW, ROW + "\n", ROW.rstrip() + ", extra\n", ",".join(ROW.split(",")[:-1])):
            with self.subTest(value=value[:50]), self.assertRaises(ValueError):
                probe.parse_gpu(value)
        with self.assertRaises(ValueError):
            probe.parse_gpu(changed(0, "1"))

    def test_nan_infinity_bool_fractional_memory_and_invalid_csv_rejected(self):
        for field in (3, 4, 5, 6, 7, 8):
            for value in ("NaN", "Infinity", "true", "-1", "1e999"):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    probe.parse_gpu(changed(field, value))
        for value in (changed(3, "8151.5"), changed(1, '"unterminated'), changed(1, '"line\nbreak"'), "x" * 4097, None, True):
            with self.subTest(value=repr(value)[:40]), self.assertRaises(ValueError):
                probe.parse_gpu(value)

    def test_memory_bounds_and_uint64_conversion_cannot_overflow(self):
        for field, value in ((3, "0"), (4, "8152"), (5, "8152"), (3, str(1 << 64)),
                             (3, str((1 << 64) // 1048576)), (6, "101"), (7, "201"), (8, "10001")):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                probe.parse_gpu(changed(field, value))
        self.assertEqual(probe.parse_gpu(changed(5, "0"))["free_bytes"], 0)

    def test_system32_path_wins_without_consulting_path_fallback(self):
        with mock.patch.object(probe, "_system_directory", return_value=Path("system32")), \
             mock.patch.object(Path, "is_file", return_value=True), mock.patch.object(probe.shutil, "which") as which:
            self.assertEqual(probe._smi_path(), str(Path("system32") / "nvidia-smi.exe"))
            which.assert_not_called()
        with mock.patch.object(probe, "_system_directory", return_value=Path("system32")), \
             mock.patch.object(Path, "is_file", return_value=False), mock.patch.object(probe.shutil, "which", return_value=None):
            with self.assertRaises(FileNotFoundError):
                probe._smi_path()

    def test_observe_uses_bounded_no_window_gpu0_query_and_exact_outer_shape(self):
        memory = {"source": "GlobalMemoryStatusEx", "available_bytes": 8, "total_bytes": 16}
        with mock.patch.object(probe.os, "name", "nt"), mock.patch.object(probe, "_memory", return_value=memory), \
             mock.patch.object(probe, "_smi_path", return_value="system32-nvidia-smi.exe"), \
             mock.patch.object(probe.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
             mock.patch.object(probe.subprocess, "run", return_value=mock.Mock(stdout=ROW.encode(), stderr=b"", returncode=0)) as run:
            value = probe.observe()
        self.assertEqual(set(value), {"schema_version", "memory", "gpu"})
        self.assertEqual(value["memory"], memory)
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], "system32-nvidia-smi.exe")
        self.assertIn("--id=0", args[0])
        self.assertIn("--query-gpu=" + probe._QUERY, args[0])
        self.assertEqual(kwargs["timeout"], 5)
        self.assertTrue(kwargs["check"])
        self.assertEqual(kwargs["creationflags"], 0x08000000)
        run.assert_called_once()

    def test_evidence_preserves_same_query_raw_stderr_and_rejects_oversize_or_invalid_utf8(self):
        for stdout, stderr, valid in ((ROW.encode(), b"diagnostic retained\n", True),
                                     (ROW.encode(), b"x" * (16 * 1024 + 1), False),
                                     (b"x" * (16 * 1024 + 1), b"", False), (ROW.encode(), b"\xff", False)):
            with self.subTest(stdout_bytes=len(stdout), stderr_bytes=len(stderr)), \
                 mock.patch.object(probe.os, "name", "nt"), \
                 mock.patch.object(probe, "_memory", return_value={"source": "GlobalMemoryStatusEx", "available_bytes": 8, "total_bytes": 16}), \
                 mock.patch.object(probe, "_smi_path", return_value="system32-nvidia-smi.exe"), \
                 mock.patch.object(probe.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
                 mock.patch.object(probe.subprocess, "run", return_value=mock.Mock(stdout=stdout, stderr=stderr, returncode=0)) as run:
                if not valid:
                    with self.assertRaises(ValueError):
                        probe.observe_with_evidence()
                else:
                    value = probe.observe_with_evidence()
                    self.assertEqual(set(value), {"observation", "gpu_raw"})
                    self.assertEqual(set(value["gpu_raw"]), {"argv", "returncode", "stdout", "stderr"})
                    self.assertEqual(value["gpu_raw"]["stdout"], ROW)
                    self.assertEqual(value["gpu_raw"]["stderr"], "diagnostic retained\n")
                    self.assertEqual(value["observation"]["gpu"], probe.parse_gpu(value["gpu_raw"]["stdout"]))
                    self.assertEqual(value["gpu_raw"]["argv"], run.call_args.args[0])
                run.assert_called_once()

    def test_subprocess_failure_or_timeout_does_not_fabricate_observation(self):
        for error in (subprocess.TimeoutExpired("nvidia-smi", 5), subprocess.CalledProcessError(1, "nvidia-smi")):
            with self.subTest(error=type(error).__name__), mock.patch.object(probe.os, "name", "nt"), \
                 mock.patch.object(probe, "_memory", return_value={}), mock.patch.object(probe, "_smi_path", return_value="smi"), \
                 mock.patch.object(probe.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
                 mock.patch.object(probe.subprocess, "run", side_effect=error):
                with self.assertRaises(type(error)):
                    probe.observe()

    def test_ram_os_error_or_inconsistent_unsigned_values_raise(self):
        for total, available, success in ((16, 8, True), (0, 0, True), (16, 17, True), (16, 8, False)):
            api = mock.Mock()

            def query(pointer):
                pointer._obj.total_phys = total
                pointer._obj.avail_phys = available
                return int(success)

            api.GlobalMemoryStatusEx.side_effect = query
            with self.subTest(total=total, available=available, success=success), \
                 mock.patch.object(probe.ctypes, "WinDLL", return_value=api, create=True), \
                 mock.patch.object(probe.ctypes, "get_last_error", return_value=5, create=True), \
                 mock.patch.object(probe.ctypes, "WinError", return_value=OSError("OS query failed"), create=True):
                if success and total > 0 and available <= total:
                    self.assertEqual(probe._memory(), {"source": "GlobalMemoryStatusEx", "available_bytes": 8, "total_bytes": 16})
                else:
                    with self.assertRaises((ValueError, OSError)):
                        probe._memory()


if __name__ == "__main__":
    unittest.main()
