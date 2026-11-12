"""Pinned build-input safety and model-free native protocol boundaries.

The optional executable tests never load a DLL or a model. They cannot qualify
a backend, answer, memory residency, or the native generation loop.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "build_cellivane_runtime.py"
SPEC = importlib.util.spec_from_file_location("cellivane_runtime_builder", MODULE_PATH)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class BuildInputTests(unittest.TestCase):
    def test_cached_tamper_rejected_without_network_or_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "header.h").write_bytes(b"tampered")
            with mock.patch.dict(builder.INPUT_HASHES, {"header.h": hashlib.sha256(b"valid").hexdigest()}, clear=True), \
                 mock.patch("urllib.request.urlopen") as network:
                with self.assertRaises(ValueError):
                    builder.input_files(root, download=True)
            network.assert_not_called()
            self.assertEqual((root / "header.h").read_bytes(), b"tampered")

    def test_missing_offline_input_is_not_downloaded(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.dict(builder.INPUT_HASHES, {"header.h": "a" * 64}, clear=True), \
             mock.patch("urllib.request.urlopen") as network:
            with self.assertRaises(ValueError):
                builder.input_files(Path(directory))
            network.assert_not_called()

    def test_download_hash_failure_does_not_publish_partial_input(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"hostile replacement"
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.dict(builder.INPUT_HASHES, {"header.h": hashlib.sha256(b"valid").hexdigest()}, clear=True), \
             mock.patch.dict(builder.INPUT_URLS, {"header.h": "https://raw.githubusercontent.com/example/pin/header.h"}, clear=True), \
             mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(ValueError):
                builder.input_files(Path(directory), download=True)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_sealed_bundle_ignores_unpinned_gpu_dll(self):
        valid = b"fixed cpu dll"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "source", root / "target"
            source.mkdir()
            (source / "cpu.dll").write_bytes(valid)
            (source / "gpu.dll").write_bytes(b"must not copy")
            with mock.patch.dict(builder.DLL_HASHES, {"cpu.dll": hashlib.sha256(valid).hexdigest()}, clear=True):
                records = builder.sealed_engine(source, target)
            self.assertEqual([p.name for p in target.iterdir()], ["cpu.dll"])
            self.assertEqual(records[0]["sha256"], hashlib.sha256(valid).hexdigest())

    def test_tampered_dll_fails_before_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "cpu.dll").write_bytes(b"changed")
            with mock.patch.dict(builder.DLL_HASHES, {"cpu.dll": hashlib.sha256(b"expected").hexdigest()}, clear=True):
                with self.assertRaises(ValueError):
                    builder.sealed_engine(source, root / "target")
            self.assertFalse((root / "target/cpu.dll").exists())

    def test_batch_path_rejects_expansion_and_command_metacharacters(self):
        for value in ["percent%PATH%", "a&b", "a|b", "a>b", "a^b", "a!b", 'a"b', "a\nb"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                builder.batch_path(Path(value))

    def test_build_pin_is_full_commit_and_cpu_only(self):
        self.assertEqual(len(builder.ENGINE_COMMIT), 40)
        self.assertTrue(all("cuda" not in name and "vulkan" not in name and "rpc" not in name for name in builder.DLL_HASHES))
        self.assertTrue(all(len(value) == 64 and int(value, 16) >= 0 for value in builder.INPUT_HASHES.values()))
        self.assertTrue(all(builder.ENGINE_COMMIT in url or "55f93686c01528224f448c19128836e7df245f72" in url for url in builder.INPUT_URLS.values()))


EXE = os.environ.get("CELLIVANE_RUNTIME_SELFTEST_EXE")


@unittest.skipUnless(os.name == "nt" and EXE, "Windows model-free worker path is supplied explicitly")
class NativeProtocolTests(unittest.TestCase):
    def run_worker(self, payload: bytes, extra=()):
        process = subprocess.run([EXE, "--protocol-selftest", *extra], input=payload,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
        lines = process.stdout.decode("utf-8", errors="strict").splitlines()
        values = [json.loads(line) for line in lines]
        self.assertLessEqual(len(values), 2)
        self.assertNotIn(b"D:\\", process.stdout)
        return process, values

    def rejected(self, payload, code=None):
        process, values = self.run_worker(payload)
        self.assertEqual(process.returncode, 2)
        self.assertEqual(values[0]["template_mode"], "protocol-selftest")
        self.assertEqual(set(values[-1]), {"kind", "id", "error"})
        self.assertEqual(values[-1]["kind"], "error")
        if code is not None:
            self.assertEqual(values[-1]["error"], code)
        self.assertNotIn("result", [value["kind"] for value in values])

    def test_shutdown_is_model_free_and_clean(self):
        process, values = self.run_worker(b'{"id":7,"op":"shutdown"}\n')
        self.assertEqual(process.returncode, 0)
        self.assertEqual(set(values[0]), {"kind", "protocol", "engine_commit", "threads", "context_tokens", "gpu_layers", "model_load_s", "template_mode"})
        self.assertEqual(values[0]["model_load_s"], 0)
        self.assertEqual(values[0]["gpu_layers"], 0)
        self.assertEqual(values[1]["kind"], "stopped")
        self.assertTrue(values[1]["model_disposed"])
        self.assertTrue(values[1]["peak_working_set_bytes"] is None or type(values[1]["peak_working_set_bytes"]) is int)

    def test_valid_generate_never_runs_in_selftest(self):
        self.rejected(b'{"id":1,"op":"generate","messages":[{"role":"user","content":"hello"}],"max_tokens":64}\n', "selftest-no-generation")

    def test_duplicate_top_level_key(self):
        self.rejected(b'{"id":1,"id":2,"op":"shutdown"}\n', "json-duplicate-key")

    def test_duplicate_nested_key(self):
        self.rejected(b'{"id":1,"op":"generate","max_tokens":1,"messages":[{"role":"user","content":"x","content":"y"}]}\n', "json-duplicate-key")

    def test_nonfinite_and_float_id_rejected(self):
        for value in ["NaN", "Infinity", "1e999", "1.0", "true", "-1", "9223372036854775808"]:
            with self.subTest(value=value):
                self.rejected(('{"id":' + value + ',"op":"shutdown"}\n').encode())

    def test_output_count_bool_and_out_of_bounds(self):
        for count in [True, 0, 65, 1.5]:
            with self.subTest(count=count):
                self.rejected(json.dumps({"id": 1, "op": "generate", "messages": [{"role": "user", "content": "hi"}], "max_tokens": count}).encode() + b"\n", "max-tokens")

    def test_unknown_command_and_message_keys(self):
        self.rejected(b'{"id":1,"op":"shutdown","extra":null}\n', "shutdown-shape")
        self.rejected(b'{"id":1,"op":"generate","messages":[{"role":"user","content":"hi","tools":[]}],"max_tokens":1}\n', "message-shape")

    def test_content_control_and_missing_user(self):
        for content in ["a\x00b", "a\rb"]:
            with self.subTest(content=repr(content)):
                self.rejected(json.dumps({"id": 1, "op": "generate", "messages": [{"role": "user", "content": content}], "max_tokens": 1}).encode() + b"\n", "message-control")
        self.rejected(b'{"id":1,"op":"generate","messages":[{"role":"system","content":"hello"}],"max_tokens":1}\n', "user-required")

    def test_message_aggregate_byte_limit(self):
        data = {"id": 1, "op": "generate", "messages": [{"role": "user", "content": "x" * 16385}], "max_tokens": 1}
        self.rejected(json.dumps(data).encode() + b"\n", "messages-bytes")

    def test_message_count_limit(self):
        data = {"id": 1, "op": "generate", "messages": [{"role": "user", "content": "x"}] * 33, "max_tokens": 1}
        self.rejected(json.dumps(data).encode() + b"\n", "messages-count")

    def test_invalid_utf8_and_line_limit(self):
        self.rejected(b'{"id":1,"op":"shutdown","x":"\xff"}\n', "input-invalid-utf8")
        self.rejected(b"x" * 65537 + b"\n", "line-too-large")

    def test_trailing_json_deep_nesting_and_truncated_line(self):
        self.rejected(b'{"id":1,"op":"shutdown"} {}\n', "invalid-json")
        self.rejected(b"[" * 18 + b"0" + b"]" * 18 + b"\n", "json-depth")
        self.rejected(b'{"id":1,"op":"shutdown"}', "truncated-line")

    def test_eof_requires_shutdown_ack(self):
        self.rejected(b"", "shutdown-required")

    def test_bad_argument_has_no_ready(self):
        for args in [("--threads", "0"), ("--context", "127"), ("--batch", "513"), ("--threads", "true")]:
            with self.subTest(args=args):
                process, values = self.run_worker(b"", args)
                self.assertEqual(process.returncode, 2)
                self.assertEqual(len(values), 1)
                self.assertEqual(values[0]["error"], "argument-range")


if __name__ == "__main__":
    unittest.main()
