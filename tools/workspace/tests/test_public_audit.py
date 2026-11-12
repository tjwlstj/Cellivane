"""Negative proofs for the bounded public-source guard; no real credentials."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


spec = importlib.util.spec_from_file_location("public_audit", Path(__file__).resolve().parents[1] / "public_audit.py")
audit_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_module)


class PublicAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.rows = []

    def add(self, path="README.md", data=b"Public source\n"):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        sha = audit_module.digest(data)
        self.rows.append({"component": "fixture", "source_path": path, "destination_path": path,
                          "source_bytes": len(data), "source_sha256": sha, "reference_commit": "0" * 40,
                          "snapshot_uncommitted_content_possible": False, "exported_sha256": sha,
                          "exported_bytes": len(data), "public_text_adjusted": False})
        return target

    def manifest(self):
        target = self.root / audit_module.DEFAULT_MANIFEST
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"schema_version": 1, "files": self.rows}), encoding="utf-8")
        return target

    def run_audit(self, **kwargs):
        self.manifest()
        return audit_module.audit(self.root, paths=[row["destination_path"] for row in self.rows], **kwargs)

    def rules(self, result):
        return {finding["rule"] for finding in result["findings"]}

    def test_clean_import_and_generic_windows_fixture_pass(self):
        path = "C:" + "\\" + "Users" + "\\" + "User" + "\\" + "fixture"
        self.add(data=path.encode())
        self.assertEqual(self.run_audit()["outcome"], "PASS")

    def test_token_fails_without_echoing_matched_secret(self):
        token = "gh" + "p_" + "A" * 36
        self.add(data=token.encode())
        result = self.run_audit()
        self.assertIn("github-token", self.rules(result))
        self.assertNotIn(token, json.dumps(result))

    def test_private_home_fails(self):
        path = "C:" + "\\" + "Users" + "\\" + "private-person" + "\\" + "project"
        self.add(data=path.encode())
        self.assertIn("personal-windows-home", self.rules(self.run_audit()))

    def test_private_address_fails_but_loopback_is_allowed(self):
        self.add(data=("192." + "168.31.1").encode())
        self.assertIn("private-ipv4-literal", self.rules(self.run_audit()))
        self.rows.clear()
        self.add(data=b"http://127.0.0.1:8080")
        self.assertEqual(self.run_audit()["outcome"], "PASS")

    def test_session_identifier_fails(self):
        identifier = "01a11ba7" + "-8580-7730-be51-445e3e2f5174"
        self.add(data=identifier.encode())
        self.assertIn("retained-session-id", self.rules(self.run_audit()))

    def test_reviewed_gateway_is_scoped_to_exact_path_and_value(self):
        gateway = str(audit_module.ipaddress.IPv4Address(0x0A000202))
        self.add("hosted/linux/aios_agent/inference.py", gateway.encode())
        result = self.run_audit()
        self.assertEqual(result["outcome"], "PASS")
        self.assertEqual(result["reviewed_literal_exceptions"][0]["occurrences"], 1)
        self.rows.clear()
        self.add(data=gateway.encode())
        self.assertIn("private-ipv4-literal", self.rules(self.run_audit()))

    def test_new_private_literal_in_reviewed_file_still_fails(self):
        other = str(audit_module.ipaddress.IPv4Address(0xC0A81F01))
        self.add("hosted/linux/aios_agent/inference.py", other.encode())
        self.assertIn("private-ipv4-literal", self.rules(self.run_audit()))

    def test_synthetic_credential_url_exception_is_not_global(self):
        example = "https://" + "user:secret@" + "example.com/"
        self.add("tools/hosted/tests/test_hosted_console.py", example.encode())
        self.assertEqual(self.run_audit()["outcome"], "PASS")
        self.rows.clear()
        self.add(data=example.encode())
        self.assertIn("credential-url", self.rules(self.run_audit()))

    def test_new_credential_url_in_reviewed_test_still_fails(self):
        example = "https://" + "user:real-secret@" + "production.invalid/"
        self.add("tools/hosted/tests/test_hosted_console.py", example.encode())
        self.assertIn("credential-url", self.rules(self.run_audit()))

    def test_payload_in_explicit_public_inventory_fails_even_when_ignored(self):
        self.add("build/model.gguf", b"payload")
        self.assertIn("forbidden-publication-path", self.rules(self.run_audit()))

    @unittest.skipUnless(shutil.which("git"), "Git is required for the tracked-payload integration proof")
    def test_git_inventory_keeps_force_tracked_ignored_payload_in_scope(self):
        self.add()
        self.manifest()
        (self.root / ".gitignore").write_text("build/\n", encoding="utf-8")
        payload = self.root / "build/model.gguf"
        payload.parent.mkdir()
        payload.write_bytes(b"forbidden fixture payload")
        subprocess.run(["git", "init", "--quiet", str(self.root)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "add", "--force", "build/model.gguf"], check=True, capture_output=True)
        result = audit_module.audit(self.root)
        self.assertEqual(result["inventory_mode"], "git-tracked-and-unignored-untracked")
        self.assertIn({"path": "build/model.gguf", "rule": "forbidden-publication-path"}, result["findings"])

    def test_executable_renamed_as_source_fails(self):
        self.add(data=b"MZ renamed executable")
        self.assertIn("executable-payload", self.rules(self.run_audit()))

    def test_traversal_cannot_escape_root(self):
        self.add()
        self.rows[0]["destination_path"] = "../outside.md"
        self.assertIn("invalid-relative-path", self.rules(self.run_audit()))

    def test_missing_imported_file_is_not_silently_skipped(self):
        target = self.add()
        target.unlink()
        self.assertIn("missing-source-file", self.rules(self.run_audit()))

    def test_duplicate_manifest_path_fails(self):
        self.add()
        self.rows.append(dict(self.rows[0]))
        self.assertIn("manifest-duplicate-path", self.rules(self.run_audit()))

    def test_default_export_hash_mismatch_fails(self):
        target = self.add()
        target.write_text("Changed documentation", encoding="utf-8")
        self.assertIn("export-hash-mismatch", self.rules(self.run_audit()))

    def test_explicit_metadata_refresh_preserves_source_identity(self):
        target = self.add()
        original_hash = self.rows[0]["source_sha256"]
        target.write_text("Public-facing documentation", encoding="utf-8")
        result = self.run_audit(refresh_reason="Review public documentation")
        self.assertEqual(result["outcome"], "PASS")
        self.assertEqual(result["refreshed_metadata_files"], 1)
        saved = json.loads((self.root / audit_module.DEFAULT_MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(saved["files"][0]["source_sha256"], original_hash)
        self.assertNotEqual(saved["files"][0]["exported_sha256"], original_hash)
        self.assertTrue(saved["files"][0]["public_text_adjusted"])
        self.assertEqual(len(saved["export_refreshes"]), 1)

    def test_code_drift_cannot_be_accepted_as_metadata_refresh(self):
        target = self.add("runtime.py", b"x = 1\n")
        target.write_text("x = 2\n", encoding="utf-8")
        self.assertIn("export-hash-mismatch", self.rules(self.run_audit(refresh_reason="Review documentation")))

    def test_only_root_git_metadata_is_refreshable_and_keeps_original_hashes(self):
        for path in (".gitignore", ".gitattributes"):
            with self.subTest(path=path):
                self.rows.clear()
                target = self.add(path, b"# original metadata\n")
                original_hash = self.rows[0]["source_sha256"]
                target.write_bytes(b"# reviewed publication metadata\n")
                result = self.run_audit(refresh_reason="Preserve public checkout bytes")
                self.assertEqual(result["outcome"], "PASS")
                saved = json.loads((self.root / audit_module.DEFAULT_MANIFEST).read_text(encoding="utf-8"))
                self.assertEqual(saved["files"][0]["source_sha256"], original_hash)
                self.assertNotEqual(saved["files"][0]["exported_sha256"], original_hash)
        self.rows.clear()
        nested = self.add("hosted/.gitattributes", b"# original metadata\n")
        nested.write_bytes(b"# new metadata\n")
        self.assertIn("export-hash-mismatch", self.rules(self.run_audit(refresh_reason="Preserve public checkout bytes")))

    def test_failed_scan_does_not_write_refresh_or_overwrite_old_manifest(self):
        target = self.add()
        token = "gh" + "p_" + "Z" * 36
        target.write_text(token, encoding="utf-8")
        original = self.manifest().read_bytes()
        result = audit_module.audit(self.root, paths=["README.md"], refresh_reason="Review documentation")
        self.assertEqual(result["outcome"], "FAIL")
        self.assertEqual((self.root / audit_module.DEFAULT_MANIFEST).read_bytes(), original)

    def test_duplicate_json_key_fails(self):
        self.add()
        target = self.manifest()
        target.write_text('{"schema_version": 1, "schema_version": 1, "files": []}', encoding="utf-8")
        result = audit_module.audit(self.root, paths=["README.md"])
        self.assertIn("duplicate-json-key", self.rules(result))


if __name__ == "__main__":
    unittest.main()
