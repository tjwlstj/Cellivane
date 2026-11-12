#!/usr/bin/env python3
"""Bounded public-source checks, not a complete secret or legal audit.

Checks current Git publication candidates (or a pre-Git source tree), common
credential forms, personal Windows home paths, private IPv4 literals, retained
Codex-style time-based session IDs, forbidden payload paths, and export hashes.
Findings contain paths and rule names only, never the matched source text.
Original source hashes are immutable. Explicit metadata refreshes update only
export hashes for Markdown and root Git metadata, with a recorded reason.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


DEFAULT_MANIFEST = "docs/provenance/source-snapshot.json"
MAX_SOURCE_BYTES = 16 * 1024 * 1024
LOCAL_DIRECTORIES = {".git", ".venv", ".cellivane", ".toolchain", "build", "__pycache__", "node_modules"}
PAYLOAD_DIRECTORIES = LOCAL_DIRECTORIES - {".git"} | {"weights", "cache"}
PAYLOAD_SUFFIXES = {
    ".o", ".pyc", ".pyo", ".bin", ".iso", ".img", ".qcow2", ".vhd", ".vhdx",
    ".gguf", ".safetensors", ".onnx", ".pt", ".pth", ".exe", ".dll", ".pyd",
    ".zip", ".7z", ".whl", ".tar", ".gz", ".xz", ".bz2",
}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SECRET_PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
    ("openai-project-key", re.compile(r"\bsk-proj-[A-Za-z0-9_-]{15,}\b")),
    ("aws-access-key", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    ("credential-url", re.compile(r"https?://[^\s/:@]+:[^\s/@]{6,}@[A-Za-z0-9.-]+(?::[0-9]+)?", re.IGNORECASE)),
)
HOME_PATH = re.compile(r"\b[A-Za-z]:[\\/]+Users[\\/]+([^\\/\s\"'`<>]+)", re.IGNORECASE)
SYNTHETIC_HOME_NAMES = {"user", "username", "public", "default", "example", "test", "testuser"}
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
# RFC1918 network integers keep the scanner's own source free of address literals.
PRIVATE_NETWORKS = tuple(ipaddress.IPv4Network(n) for n in ((0x0A000000, 8), (0xAC100000, 12), (0xC0A80000, 16)))
SESSION_ID = re.compile(r"\b01[0-9a-f]{6}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.IGNORECASE)
# Exact path/rule/literal exceptions reviewed in the imported source. The QEMU
# user-network gateway is a protocol constant, and the tests reject this source
# or an arbitrary private host. Other literals in these files still fail.
_QEMU_GATEWAY = str(ipaddress.IPv4Address(0x0A000202))
REVIEWED_LITERALS = {
    (path, "private-ipv4-literal"): {_QEMU_GATEWAY}
    for path in (
        "hosted/linux/aios_agent/inference.py", "tools/hosted/verify_agent.py",
        "tools/hosted/tests/test_hosted_backend_runtime.py",
        "tools/hosted/tests/test_hosted_image_runtime.py",
        "tools/hosted/tests/test_hosted_image_verifier.py",
    )
}
REVIEWED_LITERALS[("tools/hosted/tests/test_hosted_ollama_verifier.py", "private-ipv4-literal")] = {str(ipaddress.IPv4Address(0x0A000001))}
REVIEWED_LITERALS[("tools/hosted/tests/test_hosted_console.py", "credential-url")] = {"https://" + "user:secret@" + "example.com"}


class AuditError(ValueError):
    """A bounded rule failure; messages never include source bytes."""


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AuditError("duplicate-json-key")
        result[key] = value
    return result


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def relative_path(value) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise AuditError("invalid-relative-path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise AuditError("invalid-relative-path")
    return value


def checked_file(root: Path, relative: str) -> Path:
    relative_path(relative)
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise AuditError("symlink-source")
        if current.exists():
            attrs = getattr(current.lstat(), "st_file_attributes", 0)
            if attrs & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT, also catches junctions.
                raise AuditError("reparse-source")
    if not current.is_file():
        raise AuditError("missing-source-file")
    if current.stat().st_size > MAX_SOURCE_BYTES:
        raise AuditError("source-size-limit")
    return current


def forbidden_path(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    if any(p in PAYLOAD_DIRECTORIES or p.startswith("__NO_COMMIT__") for p in parts):
        return True
    if any(p == ".git" for p in parts):
        return True
    name = parts[-1].lower()
    if name in {".env", "credentials", "hosts.yml"} or (name.startswith(".env.") and not name.endswith((".example", ".sample"))):
        return True
    return PurePosixPath(name).suffix in PAYLOAD_SUFFIXES


def text_findings(text: str, relative: str = "", reviewed_counts=None) -> set[str]:
    def reviewed(rule, value):
        key = (relative, rule)
        if value not in REVIEWED_LITERALS.get(key, set()):
            return False
        if reviewed_counts is not None:
            reviewed_counts[key] = reviewed_counts.get(key, 0) + 1
        return True
    findings = set()
    for name, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            if not reviewed(name, match.group()):
                findings.add(name)
    if any(match.group(1).lower() not in SYNTHETIC_HOME_NAMES for match in HOME_PATH.finditer(text)):
        findings.add("personal-windows-home")
    for match in IPV4.finditer(text):
        try:
            address = ipaddress.ip_address(match.group())
        except ValueError:
            continue
        if any(address in network for network in PRIVATE_NETWORKS):
            if not reviewed("private-ipv4-literal", match.group()):
                findings.add("private-ipv4-literal")
    if SESSION_ID.search(text):
        findings.add("retained-session-id")
    return findings


def publication_paths(root: Path) -> tuple[list[str], str]:
    if (root / ".git").exists():
        def git_paths(*args):
            try:
                result = subprocess.run(["git", "-C", str(root), "ls-files", "-z", *args],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise AuditError("git-inventory-unavailable") from exc
            if result.returncode:
                raise AuditError("git-inventory-failed")
            try:
                return result.stdout.decode("utf-8").rstrip("\0").split("\0") if result.stdout else []
            except UnicodeDecodeError as exc:
                raise AuditError("git-inventory-encoding") from exc
        # Tracked forbidden files must be checked even if .gitignore excludes them.
        paths = set(git_paths("--cached")) | set(git_paths("--others", "--exclude-standard"))
        return sorted(paths), "git-tracked-and-unignored-untracked"
    paths = []
    for base, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in LOCAL_DIRECTORIES and not d.startswith("__NO_COMMIT__"))
        for name in sorted(names):
            if name != ".git":
                paths.append((Path(base) / name).relative_to(root).as_posix())
    return sorted(paths), "pre-git-source-tree-local-generated-directories-excluded"


def read_manifest(root: Path, manifest_path: str) -> dict:
    try:
        manifest = json.loads(checked_file(root, manifest_path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError("manifest-unreadable-or-invalid-json") from exc
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise AuditError("manifest-schema")
    if not isinstance(manifest.get("files"), list) or not manifest["files"]:
        raise AuditError("manifest-empty-files")
    seen = set()
    required = {"component", "source_path", "destination_path", "source_bytes", "source_sha256", "reference_commit",
                "snapshot_uncommitted_content_possible", "exported_sha256", "exported_bytes", "public_text_adjusted"}
    for row in manifest["files"]:
        if not isinstance(row, dict) or set(row) != required:
            raise AuditError("manifest-file-fields")
        path = relative_path(row["destination_path"])
        relative_path(row["source_path"])
        if path in seen:
            raise AuditError("manifest-duplicate-path")
        seen.add(path)
        for name in ("source_sha256", "exported_sha256"):
            if not isinstance(row[name], str) or not SHA256.fullmatch(row[name]):
                raise AuditError("manifest-sha256")
        for name in ("source_bytes", "exported_bytes"):
            if type(row[name]) is not int or row[name] < 0:
                raise AuditError("manifest-byte-count")
        if type(row["public_text_adjusted"]) is not bool or type(row["snapshot_uncommitted_content_possible"]) is not bool:
            raise AuditError("manifest-boolean")
        if row["public_text_adjusted"] != (row["source_sha256"] != row["exported_sha256"]):
            raise AuditError("manifest-adjustment-flag")
    return manifest


def audit(root: Path, manifest_path: str = DEFAULT_MANIFEST, *, paths=None, refresh_reason=None) -> dict:
    root = root.resolve()
    findings = []
    def finding(path, rule):
        findings.append({"path": path, "rule": rule})
    try:
        manifest = read_manifest(root, manifest_path)
        selected, mode = publication_paths(root) if paths is None else (sorted(set(paths)), "explicit-test-inventory")
        selected = [relative_path(path) for path in selected]
    except (AuditError, OSError) as exc:
        return {"outcome": "FAIL", "scope": __doc__.splitlines()[0], "findings": [{"path": manifest_path, "rule": str(exc) if isinstance(exc, AuditError) else "inventory-read-error"}]}
    imported = {row["destination_path"]: row for row in manifest["files"]}
    selected_set = set(selected)
    content = {}
    binary_images = 0
    reviewed_counts = {}
    for path in selected:
        if forbidden_path(path):
            finding(path, "forbidden-publication-path")
            continue
        try:
            data = checked_file(root, path).read_bytes()
        except (AuditError, OSError) as exc:
            finding(path, str(exc) if isinstance(exc, AuditError) else "source-read-error")
            continue
        content[path] = data
        if data.startswith((b"MZ", b"\x7fELF")):
            finding(path, "executable-payload")
            continue
        if PurePosixPath(path).suffix.lower() == ".png":
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                finding(path, "invalid-png-signature")
            binary_images += 1
            continue
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            finding(path, "non-utf8-source")
            continue
        if "\0" in text:
            finding(path, "binary-in-text-source")
            continue
        for rule in sorted(text_findings(text, path, reviewed_counts)):
            finding(path, rule)
    changes = []
    for path, row in imported.items():
        if path not in selected_set:
            finding(path, "manifest-source-not-publication-candidate")
            continue
        if path not in content:
            continue
        data = content[path]
        current_hash = digest(data)
        if current_hash == row["exported_sha256"] and len(data) == row["exported_bytes"]:
            continue
        metadata = PurePosixPath(path).suffix.lower() == ".md" or path in {".gitignore", ".gitattributes"}
        if refresh_reason and metadata:
            changes.append({"path": path, "old_exported_sha256": row["exported_sha256"], "new_exported_sha256": current_hash})
            row["exported_sha256"] = current_hash
            row["exported_bytes"] = len(data)
            row["public_text_adjusted"] = current_hash != row["source_sha256"]
        else:
            finding(path, "export-hash-mismatch")
    if refresh_reason:
        if not isinstance(refresh_reason, str) or not 1 <= len(refresh_reason.strip()) <= 500 or text_findings(refresh_reason):
            finding(manifest_path, "invalid-refresh-reason")
        if not findings and changes:
            refreshes = manifest.setdefault("export_refreshes", [])
            if not isinstance(refreshes, list):
                finding(manifest_path, "invalid-refresh-history")
            else:
                refreshes.append({"at_utc": datetime.now(timezone.utc).isoformat(), "reason": refresh_reason.strip(), "files": changes})
                destination = checked_file(root, manifest_path)
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=destination.parent, delete=False) as stream:
                        temporary = Path(stream.name)
                        json.dump(manifest, stream, ensure_ascii=False, indent=2)
                        stream.write("\n")
                    os.replace(temporary, destination)
                except OSError:
                    finding(manifest_path, "refresh-write-failed")
                finally:
                    if temporary is not None and temporary.exists():
                        temporary.unlink()
    return {
        "outcome": "FAIL" if findings else "PASS",
        "scope": __doc__.splitlines()[0],
        "inventory_mode": mode,
        "publication_candidate_files": len(selected),
        "imported_manifest_files": len(imported),
        "additional_authored_files": len(selected_set - set(imported)),
        "allowed_png_files": binary_images,
        "reviewed_literal_exceptions": [{"path": path, "rule": rule, "occurrences": count}
                                        for (path, rule), count in sorted(reviewed_counts.items())],
        "refreshed_metadata_files": len(changes) if refresh_reason and not findings else 0,
        "findings": findings,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable verdict, never source matches.")
    parser.add_argument("--refresh-export-hashes", action="store_true", help="Refresh Markdown/root .gitignore/.gitattributes export hashes only; preserve source hashes.")
    parser.add_argument("--reason", help="Required explanation for an explicit metadata export refresh.")
    args = parser.parse_args(argv)
    if args.refresh_export_hashes != bool(args.reason):
        parser.error("--refresh-export-hashes and --reason must be used together")
    result = audit(args.root, args.manifest, refresh_reason=args.reason if args.refresh_export_hashes else None)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("[PUBLIC-AUDIT] " + result["outcome"] + " scope=bounded-current-source")
        for item in result["findings"]:
            print(f"{item['path']}: {item['rule']}")
        print("Does not audit Git history, image contents, all secret forms, or legal compatibility.")
    return 0 if result["outcome"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
