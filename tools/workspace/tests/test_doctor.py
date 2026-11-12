"""Check public/private report separation and optional tool readiness."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("workspace_doctor", Path(__file__).resolve().parents[1] / "doctor.py")
DOCTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCTOR)


def fake_tool(name, candidates, args=("--version",)):
    return {"name": name, "status": "READY" if name == "git" else "MISSING",
            "path": "/private/account/tool", "version": "1.2.3",
            "detail": "/private/account/raw-output"}


class DoctorReportTests(unittest.TestCase):
    def test_public_report_excludes_machine_paths_and_raw_output(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(DOCTOR, "ROOT", Path(folder)), patch.object(DOCTOR, "inspect_tool", fake_tool):
            public, detailed = DOCTOR.collect()
        self.assertNotIn("/private/account", json.dumps(public))
        self.assertNotIn(folder, json.dumps(public))
        self.assertIn("/private/account", json.dumps(detailed))

    def test_native_tools_are_optional_until_explicitly_required(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(DOCTOR, "ROOT", Path(folder)), patch.object(DOCTOR, "inspect_tool", fake_tool), patch.object(DOCTOR.sys, "version_info", (3, 11)):
            self.assertEqual(DOCTOR.collect(False)[0]["outcome"], "READY")
            self.assertEqual(DOCTOR.collect(True)[0]["outcome"], "NOT_READY")

    def test_malformed_local_config_cannot_report_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".cellivane").mkdir()
            (root / ".cellivane/local-tools.json").write_text("{broken", encoding="utf-8")
            with patch.object(DOCTOR, "ROOT", root), patch.object(DOCTOR, "inspect_tool", fake_tool):
                public, _ = DOCTOR.collect()
        self.assertEqual(public["outcome"], "NOT_READY")
        self.assertEqual(public["config_error"], "JSONDecodeError")


if __name__ == "__main__":
    unittest.main()
