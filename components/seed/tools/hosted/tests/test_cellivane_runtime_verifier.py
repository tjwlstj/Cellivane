"""Synthetic raw-protocol attacks; no runtime/producer import or model run."""
from __future__ import annotations

import ast
import copy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
import zipfile

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
MODULE = importlib.util.spec_from_file_location("independent_runtime_verifier", TOOLS / "verify_cellivane_runtime.py")
v = importlib.util.module_from_spec(MODULE)
MODULE.loader.exec_module(v)


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def record(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": sha256(raw).hexdigest()}


class ProtocolFixture:
    def __init__(self, root, mode="none"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.phase = {"mode": mode, "ready": {"kind": "ready", "protocol": 1,
            "engine_commit": "d81235049384534c167caea52b85a694f6103d14", "threads": 4,
            "context_tokens": 512, "gpu_layers": 0, "model_load_s": .1, "template_mode": "qwen3-nonthinking"}, "warmup": None, "requests": [], "files": {}}
        self.sent, self.received = [], [copy.deepcopy(self.phase["ready"])]
        prompts = [("warmup", "Reply briefly. /no_think", 1)] if mode == "murphy" else []
        prompts += [("first", "Reply with only OK.", 64), ("second", "Reply with only 15.", 64)]
        for index, (case, prompt, maximum) in enumerate(prompts, 1):
            command = {"id": index, "op": "generate", "messages": [{"role": "user", "content": prompt}], "max_tokens": maximum}
            response = {"kind": "result", "id": index, "text": "x" if maximum == 1 else "OK",
                "tokens": [11] if maximum == 1 else [11, 12], "prompt_tokens": 16,
                "completion_tokens": 1 if maximum == 1 else 2, "finish_reason": "length" if maximum == 1 else "stop",
                "prefill_s": .01, "decode_s": .005, "elapsed_s": .02, "context_id": index,
                "sampler_id": index, "context_disposed": True, "sampler_disposed": True, "peak_working_set_bytes": 1024,
                "rendered_prompt_sha256": sha256(prompt.encode()).hexdigest()}
            self.sent.append(command)
            self.received.append(response)
            row = {"payload": copy.deepcopy(command), "response": copy.deepcopy(response), "wall_s": .03}
            if case == "warmup":
                self.phase["warmup"] = row
            else:
                row.update(case=case, seed_response={})
                self.phase["requests"].append(row)
        self.sent.append({"id": len(prompts) + 1, "op": "shutdown"})
        self.received.append({"kind": "stopped", "id": len(prompts) + 1, "model_disposed": True, "peak_working_set_bytes": 1024})
        self.phase["shutdown"] = copy.deepcopy(self.received[-1])
        self.reseal()

    def reseal(self, update_objects=True):
        if update_objects:
            self.phase["ready"] = copy.deepcopy(self.received[0])
            items = ([self.phase["warmup"]] if self.phase["mode"] == "murphy" else []) + self.phase["requests"]
            for index, item in enumerate(items):
                item["payload"] = copy.deepcopy(self.sent[index])
                item["response"] = copy.deepcopy(self.received[index + 1])
            self.phase["shutdown"] = copy.deepcopy(self.received[-1])
        for name, rows in (("stdin", self.sent), ("stdout", self.received)):
            path = self.root / (name + ".jsonl")
            path.write_bytes(b"".join(encode(row) + b"\n" for row in rows))
            self.phase["files"][name] = record(path)
        path = self.root / "stderr.log"
        if not path.exists():
            path.write_bytes(b"synthetic fixture; not a native engine execution\n")
        self.phase["files"]["stderr"] = record(path)


class SyntheticAssets:
    """Physical fake ZIP/DLL/header evidence; none is executable/model content."""
    def __init__(self, root):
        root = Path(root)
        directory, downloads = root / "backend", root / "downloads"
        directory.mkdir(parents=True)
        downloads.mkdir()
        names = ("llama-server.exe", "llama.dll", "ggml.dll", "ggml-base.dll", "libomp.dll", "ggml-cpu-x64.dll", "LICENSE-LLVM-OpenMP")
        members = {name: b"SYNTHETIC STATIC FIXTURE " + name.encode() for name in names}
        members["padding.dat"] = b""
        archive = downloads / "llama-b11429-bin-win-cpu-x64.zip"
        with zipfile.ZipFile(archive, "w") as package:
            for name, raw in members.items():
                package.writestr(name, raw)
        members["padding.dat"] = b"\0" * (19398918 - archive.stat().st_size)
        with zipfile.ZipFile(archive, "w") as package:
            for name, raw in members.items():
                package.writestr(name, raw)
                (directory / name).write_bytes(raw)
        self.archive_sha = sha256(archive.read_bytes()).hexdigest()
        hashes = {name: sha256(raw).hexdigest() for name, raw in members.items()}
        binaries = {name: value for name, value in hashes.items() if Path(name).suffix in (".exe", ".dll")}
        self.identity = v.digest({"backend": "llama.cpp", "commit": v.ENGINE_COMMIT,
            "archive_sha256": self.archive_sha, "binary_sha256": binaries})
        (directory / "cellivane-assets.json").write_bytes(b'{"synthetic":true}')
        self.engine = {"schema_version": 1, "backend": "llama.cpp", "stable_release": "v0.6.0", "release_tag": "b11429",
            "source_commit": v.ENGINE_COMMIT, "archive_bytes": 19398918, "archive_sha256": self.archive_sha,
            "release_id": 403936548, "asset_id": 613152134, "asset_name": archive.name,
            "asset_url": "https://github.com/ggml-org/llama.cpp/releases/download/b11429/" + archive.name,
            "stable_pointer_sha256": "5677c5a4561fad44f2a58fc14187dd9cde253874584e958b37094c723ea8e8a5",
            "directory": str(directory), "server": str(directory / "llama-server.exe"), "member_sha256": hashes,
            "binary_sha256": binaries, "binary_tree_sha256": v.digest(binaries), "engine_identity": self.identity}
        self.model = root / "synthetic.gguf"
        self.model.write_bytes(b"SYNTHETIC NOT A MODEL")
        self.inputs, self.input_pins = [], {}
        for name in v.INPUT_PINS:
            path = root / "inputs" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"SYNTHETIC NOT A HEADER " + name.encode())
            item = {**record(path), "relative_path": name,
                "url": "https://raw.githubusercontent.com/ggml-org/llama.cpp/" + v.ENGINE_COMMIT + "/" + name}
            if name == "vendor/nlohmann/LICENSE.MIT":
                item["url"] = "https://raw.githubusercontent.com/nlohmann/json/55f93686c01528224f448c19128836e7df245f72/LICENSE.MIT"
            self.inputs.append(item)
            self.input_pins[name] = item["sha256"]


class FullFixture:
    def __init__(self, root, assets):
        self.root = Path(root) / str(uuid4())
        self.root.mkdir()
        self.path = self.root / "summary.json"
        source_root = Path(root) / "synthetic-source"
        rows = []
        for name in sorted(v.SOURCE_PATHS):
            path = source_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = b"# SYNTHETIC SOURCE NOT EXECUTED " + name.encode()
            path.write_bytes(raw)
            snapshot = "source-snapshot/" + name
            target = self.root / snapshot
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            rows.append({"path": name, "bytes": len(raw), "sha256": sha256(raw).hexdigest(), "snapshot": snapshot})
        self.hashes = {row["path"]: row["sha256"] for row in rows}
        worker = self.root / "build/cellivane-runtime-worker.exe"
        worker.parent.mkdir()
        worker.write_bytes(b"SYNTHETIC NOT AN EXECUTABLE")
        sealed = worker.parent / "engine-cpu"
        sealed.mkdir()
        libraries = []
        for name in assets.engine["member_sha256"]:
            if name in ("padding.dat", "llama-server.exe"):
                continue
            path = sealed / name
            path.write_bytes((Path(assets.engine["directory"]) / name).read_bytes())
            libraries.append({**record(path), "relative_path": name})
        build_log = worker.parent / "build.log"
        build_log.write_bytes(b"SYNTHETIC successful compilation fixture\n")
        inputs_root = Path(assets.inputs[0]["path"]).parents[1]
        self.build = {"schema_version": 1, "artifact_family": "cellivane-native-worker-build-v1", "outcome": "COMPILED",
            "runtime_tested": False, "model_run": False, "observed_at_utc": "2026-10-15T00:00:00+00:00",
            "engine_commit": v.ENGINE_COMMIT, "engine_tag": "b11429", "engine_archive_sha256": assets.archive_sha,
            "upstream_repository": "https://github.com/ggml-org/llama.cpp",
            "source": {"path": str(source_root / "native/cellivane_runtime/worker.cpp"), "sha256": self.hashes["native/cellivane_runtime/worker.cpp"]},
            "builder": {"path": str(source_root / "tools/hosted/build_cellivane_runtime.py"), "sha256": self.hashes["tools/hosted/build_cellivane_runtime.py"]},
            "inputs": copy.deepcopy(assets.inputs), "engine_directory": str(sealed), "engine_files": libraries,
            "compiler_environment": str(Path(root) / "vcvars64.bat"), "exit_code": 0,
            "build_log": {"path": str(build_log), "sha256": record(build_log)["sha256"]}, "executable": record(worker),
            "scope": "Windows x64 CPU compilation only; no model qualification, paging, GPU, shared KV, or MTP"}
        self.build["compiler_arguments"] = ["cl.exe", "/nologo", "/std:c++17", "/EHsc", "/O2", "/W4", "/MT", "/utf-8", "/DUNICODE",
            "/D_UNICODE", "/D_WIN32_WINNT=0x0A00", "/I" + str(inputs_root / "include"), "/I" + str(inputs_root / "ggml/include"),
            "/I" + str(inputs_root / "vendor/nlohmann"), self.build["source"]["path"], "/Fe:" + str(worker),
            "/Fo:" + str(worker.parent / "worker.obj"), "/link", "Psapi.lib", "Bcrypt.lib", "/DYNAMICBASE", "/NXCOMPAT"]
        self.build_path = worker.parent / "build-receipt.json"
        self.summary = {"schema_version": 1, "scope": "runtime-murphy-cpu-smoke", "run_id": self.root.name,
            "created_at_utc": "2026-10-15T00:00:00+00:00", "outcome": "COMPLETED", "error": None,
            "config": {"alias": v.ALIAS, "target_profile": "0.6b", "context_tokens": 512, "threads": 4, "batch": 128,
                "max_tokens": 64, "warmup_max_tokens": 1, "rounds": 2, "mode_order": list(v.MODE_ORDER), "no_result_cache": True, "placement": "cpu"},
            "model": record(assets.model), "worker": record(worker), "engine": copy.deepcopy(assets.engine),
            "native_engine_directory": str(sealed), "native_engine_files": copy.deepcopy(libraries),
            "source": {"root": str(source_root), "files": rows, "scope": "declared-source-family-not-loader-attestation"},
            "phases": [], "results_scope": {"quality_verified": False, "speedup_guaranteed": False, "weight_repacked": False,
                "native_mtp": False, "os_memory_limit_enforced": False, "gpu_tested": False}}
        identity = v.digest({"engine_identity": assets.identity, "worker_sha256": record(worker)["sha256"],
            "model_sha256": record(assets.model)["sha256"], "config": self.summary["config"]})
        self.protocols = []
        for index, mode in enumerate(v.MODE_ORDER):
            directory = self.root / f"phase-{index:02d}-{mode}"
            fixture = ProtocolFixture(directory, mode)
            self.protocols.append(fixture)
            phase = fixture.phase
            offset = 1 if mode == "murphy" else 0
            for item_index, (case, prompt) in enumerate(v.CASES):
                fixture.sent[item_index + offset]["messages"][0]["content"] = prompt
                fixture.received[item_index + offset + 1]["rendered_prompt_sha256"] = sha256(prompt.encode()).hexdigest()
                phase["requests"][item_index]["case"] = case
            fixture.reseal()
            artifact_state = {"model_sha256": record(assets.model)["sha256"], "worker_sha256": record(worker)["sha256"],
                "engine_identity": assets.identity, "sealed_engine_sha256": v.digest({row["relative_path"]: row["sha256"] for row in libraries})}
            phase.update(index=index, memory={"source": "GlobalMemoryStatusEx", "available_bytes": 16 * 1024**3, "total_bytes": 32 * 1024**3},
                budget={"required_bytes": record(assets.model)["bytes"] + 2 * 1024**3 + 512 * 1024**2,
                    "headroom_bytes": 4 * 1024**3, "scope": "declared-preflight-not-os-enforced"},
                before=copy.deepcopy(artifact_state), after=copy.deepcopy(artifact_state), source_unchanged=True, error=None,
                command=[str(worker), "--engine-dir", str(sealed), "--model", str(assets.model), "--threads", "4", "--context", "512", "--batch", "128"],
                preparation={"load_wall_s": .2, "warmup_wall_s": .04 if mode == "murphy" else .001,
                    "preparation_s": .24 if mode == "murphy" else .201}, seed_identity=identity,
                cleanup={**dict.fromkeys(("job_assigned", "job_terminated", "job_closed", "job_cleanup_confirmed", "process_exited",
                    "created_suspended", "assigned_before_resume", "primary_thread_closed", "process_handle_closed"), True),
                    "job_active_processes": 0, "returncode": 0, "job_error": None, "error": None})
            for ordinal, row in enumerate(phase["requests"], 1):
                native = row["response"]
                inference = {"model": v.ALIAS, "messages": row["payload"]["messages"], "max_tokens": 64, "temperature": 0, "stream": False}
                key = v.digest({"identity": identity, "inference": inference})
                row["seed_response"] = {"id": str(uuid4()), "object": "chat.completion", "created": 1792022400, "model": v.ALIAS,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": native["text"]}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": native["prompt_tokens"], "completion_tokens": native["completion_tokens"],
                        "total_tokens": native["prompt_tokens"] + native["completion_tokens"]},
                    "cellivane": {"engine": "seed", "version": "0.1.0", "execution": "computed", "key": key, "backend_calls": ordinal}}
            phase["seed_status"] = {"engine": "seed", "version": "0.1.0", "model": v.ALIAS, "identity": identity,
                "closed": False, "poisoned": False, "slots": 1, "active": 0, "inflight": 0, "waiters": 0,
                "max_waiters": 8, "cache_entries": 0, "cache_bytes": 0, "cache_entries_limit": 0, "cache_bytes_limit": 0,
                "backend_calls": 2, "computed": 2, "cache_hits": 0, "coalesced": 0, "failures": 0, "rejected": 0, "timeouts": 0, "event_seq": 4}
            self.summary["phases"].append(phase)
            self.audit(phase, directory)
        self.reseal()

    def audit(self, phase, directory):
        session = directory / "audit/seed-runs" / str(uuid4())
        session.mkdir(parents=True)
        events = []
        for ordinal, row in enumerate(phase["requests"], 1):
            answer = row["seed_response"]
            normalized = {name: answer[name] for name in ("model", "choices", "usage")}
            for finished in (False, True):
                events.append({"seq": len(events) + 1, "kind": "finish" if finished else "start", "key": answer["cellivane"]["key"],
                    "execution": "computed", "reason": None, "response_sha256": v.digest(normalized) if finished else None,
                    "active": 0 if finished else 1, "waiters": 0, "backend_calls": ordinal, "computed": ordinal if finished else ordinal - 1,
                    "cache_hits": 0, "coalesced": 0, "failures": 0, "rejected": 0, "timeouts": 0, "cache_entries": 0, "cache_bytes": 0})
        events.append({"seq": 5, "kind": "close", "key": None, "execution": None, "reason": "engine-closed", "response_sha256": None,
            "active": 0, "waiters": 0, "backend_calls": 2, "computed": 2, "cache_hits": 0, "coalesced": 0, "failures": 0,
            "rejected": 0, "timeouts": 0, "cache_entries": 0, "cache_bytes": 0})
        previous = None
        for index, event in enumerate(events, 1):
            row = {"seq": index, "previous_sha256": previous, "kind": "scheduler", "value": event}
            raw = encode(row)
            (session / f"{index:06d}.json").write_bytes(raw)
            previous = sha256(raw).hexdigest()

    def reseal(self):
        self.build_path.write_bytes(encode(self.build))
        self.summary["build_receipt"] = record(self.build_path)
        for phase in self.summary["phases"]:
            path = self.root / f"phase-{phase['index']:02d}-{phase['mode']}" / "phase.json"
            path.write_bytes(encode(phase))
        self.path.write_bytes(encode(self.summary))


class RuntimeProtocolReplayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.f = ProtocolFixture(self.directory.name)

    def test_none_and_murphy_have_distinct_warmup_and_reset_counts(self):
        self.assertEqual(v.protocol(self.f.phase), 2)
        murphy = ProtocolFixture(Path(self.directory.name) / "murphy", "murphy")
        self.assertEqual(v.protocol(murphy.phase), 3)
        self.assertEqual(murphy.phase["warmup"]["response"]["finish_reason"], "length")

    def test_resealed_context_or_sampler_reuse_is_rejected(self):
        original = copy.deepcopy(self.f.received[2])
        for field, value in (("context_id", 1), ("sampler_id", 1), ("context_disposed", False), ("sampler_disposed", False), ("context_id", True)):
            with self.subTest(field=field, value=value):
                self.f.received[2] = {**original, field: value}
                self.f.reseal()
                with self.assertRaisesRegex(ValueError, "context-or-sampler"):
                    v.protocol(self.f.phase)

    def test_warmup_sampler_destruction_is_required_before_measured_generation(self):
        f = ProtocolFixture(Path(self.directory.name) / "murphy", "murphy")
        f.received[1]["sampler_disposed"] = False
        f.reseal()
        with self.assertRaisesRegex(ValueError, "context-or-sampler"):
            v.protocol(f.phase)

    def test_resealed_id_swap_and_duplicate_command_id_are_rejected(self):
        self.f.sent[1]["id"] = self.f.sent[0]["id"]
        self.f.received[2]["id"] = self.f.sent[0]["id"]
        self.f.reseal()
        with self.assertRaisesRegex(ValueError, "duplicate-request-id"):
            v.protocol(self.f.phase)

    def test_stdout_object_cannot_replace_recorded_response(self):
        self.f.received[1]["text"] = "changed"
        self.f.reseal(update_objects=False)
        with self.assertRaisesRegex(ValueError, "raw-wire-join"):
            v.protocol(self.f.phase)

    def test_missing_ready_or_stopped_is_not_completed(self):
        for index in (0, -1):
            with self.subTest(index=index):
                saved = self.f.received.pop(index)
                self.f.reseal(update_objects=False)
                with self.assertRaisesRegex(ValueError, "protocol-message-count"):
                    v.protocol(self.f.phase)
                self.f.received.insert(index if index >= 0 else len(self.f.received), saved)

    def test_length_or_thinking_is_not_a_measured_answer(self):
        original = copy.deepcopy(self.f.received[1])
        for changes in ({"finish_reason": "length", "tokens": list(range(64)), "completion_tokens": 64},
                {"text": "<think>secret</think>OK"}):
            with self.subTest(changes=changes):
                self.f.received[1] = {**original, **changes}
                self.f.reseal()
                with self.assertRaisesRegex(ValueError, "measured-answer"):
                    v.protocol(self.f.phase)

    def test_resealed_token_count_or_bool_token_cannot_pass(self):
        original = copy.deepcopy(self.f.received[1])
        for changes in ({"completion_tokens": 1}, {"tokens": [True, 12]}, {"prompt_tokens": True},
                {"prompt_tokens": 500}):
            with self.subTest(changes=changes):
                self.f.received[1] = {**original, **changes}
                self.f.reseal()
                with self.assertRaisesRegex(ValueError, "token-accounting"):
                    v.protocol(self.f.phase)

    def test_model_free_ack_cannot_be_resealed_false_or_wrong_id(self):
        original = copy.deepcopy(self.f.received[-1])
        for changes in ({"model_disposed": False}, {"id": True}, {"id": 1234}):
            with self.subTest(changes=changes):
                self.f.received[-1] = {**original, **changes}
                self.f.reseal()
                with self.assertRaisesRegex(ValueError, "model-disposal"):
                    v.protocol(self.f.phase)

    def test_forged_faster_timing_is_rejected_after_resealing(self):
        self.f.received[1]["elapsed_s"] = .001
        self.f.reseal()
        with self.assertRaisesRegex(ValueError, "result-timing"):
            v.protocol(self.f.phase)
        self.f.received[1]["elapsed_s"] = .02
        self.f.reseal()
        self.f.phase["requests"][0]["wall_s"] = .001
        with self.assertRaisesRegex(ValueError, "wall-scope"):
            v.protocol(self.f.phase)

    def test_raw_duplicate_nonfinite_blank_and_truncated_lines_fail(self):
        for raw in (b'{"kind":"ready","kind":"other"}\n', b'{"x":NaN}\n', b'{"x":1e999}\n',
                b'{}\n\n', b'{}', b'[]\n'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    v.json_lines(raw)

    def test_fixed_cpu_commit_profile_is_not_declaration_only(self):
        original = copy.deepcopy(self.f.received[0])
        for changes in ({"engine_commit": "f" * 40}, {"threads": True}, {"context_tokens": 1024}, {"gpu_layers": False}):
            with self.subTest(changes=changes):
                self.f.received[0] = {**original, **changes}
                self.f.reseal()
                with self.assertRaisesRegex(ValueError, "ready-pinned"):
                    v.protocol(self.f.phase)

    def test_request_unknown_fields_and_wrong_sampling_cap_fail(self):
        self.f.sent[0]["temperature"] = 0
        self.f.reseal()
        with self.assertRaisesRegex(ValueError, "generate-command-fields"):
            v.protocol(self.f.phase)
        del self.f.sent[0]["temperature"]
        self.f.sent[0]["max_tokens"] = True
        self.f.reseal()
        with self.assertRaisesRegex(ValueError, "generate-command-settings"):
            v.protocol(self.f.phase)

    def test_imports_do_not_admit_runtime_or_producer_validation(self):
        tree = ast.parse((TOOLS / "verify_cellivane_runtime.py").read_text(encoding="utf-8"))
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        self.assertFalse(any(name and (name.startswith("cellivane_") or name.startswith("hosted")) for name in imports))


class RuntimeFullReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.asset_directory = tempfile.TemporaryDirectory()
        cls.assets = SyntheticAssets(cls.asset_directory.name)

    @classmethod
    def tearDownClass(cls):
        cls.asset_directory.cleanup()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        model = record(self.assets.model)
        for target, field, value in ((v.spec, "ARCHIVE_SHA", self.assets.archive_sha),
                (v, "MODEL_SHA", model["sha256"]), (v, "MODEL_BYTES", model["bytes"]),
                (v, "INPUT_PINS", self.assets.input_pins)):
            context = patch.object(target, field, value)
            context.start()
            self.addCleanup(context.stop)
        self.f = FullFixture(self.directory.name, self.assets)

    def replay(self):
        self.f.reseal()
        return v.replay(self.f.path)

    def rewrite_audit(self, change):
        directory = self.f.root / "phase-00-none/audit/seed-runs"
        session = next(directory.iterdir())
        records = [json.loads(path.read_bytes()) for path in sorted(session.iterdir())]
        change(records)
        previous = None
        for index, item in enumerate(records, 1):
            item["seq"], item["previous_sha256"] = index, previous
            raw = encode(item)
            (session / f"{index:06d}.json").write_bytes(raw)
            previous = sha256(raw).hexdigest()

    def test_full_physical_synthetic_gold_path_and_optional_source_root(self):
        verdict = self.replay()
        self.assertEqual(verdict["verdict"], "PASS")
        self.assertEqual(verdict["source_files_checked"], 26)
        self.assertEqual(verdict["runtime_generations"], 10)
        self.assertEqual(verdict["measured_responses"], 8)
        self.assertEqual(verdict["discarded_warmups"], 2)
        self.assertTrue(all(value is False for value in verdict["claims"].values()))
        self.assertEqual(v.replay(self.f.path, self.f.summary["source"]["root"]), verdict)

    def test_source_critical_omission_and_snapshot_reseal_cannot_pass(self):
        row = self.f.summary["source"]["files"].pop()
        with self.assertRaisesRegex(ValueError, "source-family-count"):
            self.replay()
        self.f.summary["source"]["files"].append(row)
        critical = next(row for row in self.f.summary["source"]["files"] if row["path"].endswith("runtime/murphy.py"))
        (self.f.root / critical["snapshot"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "source-snapshot-changed"):
            self.replay()

    def test_build_source_digest_must_join_recorded_snapshot(self):
        self.f.build["source"]["sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "build-source-snapshot"):
            self.replay()

    def test_resealed_build_input_pin_and_worker_identity_fail(self):
        original = self.f.build["inputs"][0]["sha256"]
        self.f.build["inputs"][0]["sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "build-input-pin"):
            self.replay()
        self.f.build["inputs"][0]["sha256"] = original
        self.f.build["executable"]["bytes"] += 1
        with self.assertRaisesRegex(ValueError, "build-worker-join"):
            self.replay()

    def test_sealed_runtime_dll_substitution_and_extra_backend_fail(self):
        path = Path(self.f.build["engine_files"][0]["path"])
        original = path.read_bytes()
        path.write_bytes(b"changed library")
        with self.assertRaisesRegex(ValueError, "artifact-bytes-changed"):
            self.replay()
        path.write_bytes(original)
        (path.parent / "ggml-cuda.dll").write_bytes(b"UNEXPECTED SYNTHETIC GPU LIBRARY")
        with self.assertRaisesRegex(ValueError, "build-engine-extra"):
            self.replay()

    def test_unsealed_release_directory_in_command_is_rejected(self):
        self.f.summary["phases"][0]["command"][2] = self.f.summary["engine"]["directory"]
        with self.assertRaisesRegex(ValueError, "worker-command"):
            self.replay()

    def test_resealed_seed_key_execution_usage_and_id_reuse_fail(self):
        row = self.f.summary["phases"][0]["requests"][0]
        original = copy.deepcopy(row["seed_response"])
        changes = (("key", "0" * 64), ("execution", "cache"), ("backend_calls", True))
        for field, value in changes:
            with self.subTest(field=field):
                row["seed_response"] = copy.deepcopy(original)
                row["seed_response"]["cellivane"][field] = value
                with self.assertRaisesRegex(ValueError, "seed-no-cache-key"):
                    self.replay()
        row["seed_response"] = copy.deepcopy(original)
        row["seed_response"]["usage"]["completion_tokens"] = True
        with self.assertRaisesRegex(ValueError, "seed-native-answer"):
            self.replay()
        row["seed_response"] = original
        other = self.f.summary["phases"][1]["requests"][0]["seed_response"]
        other["id"] = original["id"]
        with self.assertRaisesRegex(ValueError, "seed-response-id"):
            self.replay()

    def test_forged_scheduler_finish_digest_is_rejected_after_chain_reseal(self):
        self.rewrite_audit(lambda rows: rows[1]["value"].update(response_sha256="f" * 64))
        with self.assertRaisesRegex(ValueError, "scheduler-raw-chain"):
            self.replay()

    def test_raw_audit_missing_close_or_noncanonical_json_fail(self):
        session = next((self.f.root / "phase-00-none/audit/seed-runs").iterdir())
        last = session / "000005.json"
        original = last.read_bytes()
        last.unlink()
        with self.assertRaisesRegex(ValueError, "audit-bound"):
            self.replay()
        last.write_bytes(original + b"\n")
        with self.assertRaisesRegex(ValueError, "audit-chain"):
            self.replay()

    def test_resealed_cleanup_claims_and_nonzero_exit_fail(self):
        cleanup = self.f.summary["phases"][0]["cleanup"]
        original = copy.deepcopy(cleanup)
        for field, value in (("job_cleanup_confirmed", False), ("assigned_before_resume", False),
                ("returncode", 2), ("returncode", False), ("job_active_processes", True)):
            with self.subTest(field=field, value=value):
                cleanup.clear()
                cleanup.update(original)
                cleanup[field] = value
                with self.assertRaisesRegex(ValueError, "cleanup-unconfirmed"):
                    self.replay()

    def test_declared_ram_budget_cannot_drop_workspace_or_claim_more_ram(self):
        phase = self.f.summary["phases"][0]
        original = copy.deepcopy(phase["budget"])
        phase["budget"]["required_bytes"] -= 512 * 1024**2
        with self.assertRaisesRegex(ValueError, "ram-budget-fit"):
            self.replay()
        phase["budget"] = original
        phase["memory"]["available_bytes"] = original["required_bytes"] + original["headroom_bytes"] - 1
        with self.assertRaisesRegex(ValueError, "ram-budget-fit"):
            self.replay()

    def test_resealed_fatal_stderr_cannot_pass_with_good_stdout(self):
        fixture = self.f.protocols[0]
        path = fixture.root / "stderr.log"
        path.write_bytes(b"fatal error: allocation failed\n")
        fixture.phase["files"]["stderr"] = record(path)
        with self.assertRaisesRegex(ValueError, "stderr-fatal"):
            self.replay()

    def test_resealed_rendered_prompt_change_across_phases_is_rejected(self):
        fixture = self.f.protocols[2]
        fixture.received[2]["rendered_prompt_sha256"] = "f" * 64
        fixture.reseal()
        with self.assertRaisesRegex(ValueError, "rendered-prompt-changed"):
            self.replay()

    def test_failed_partial_wrong_order_and_unsupported_quality_claim_fail(self):
        summary = self.f.summary
        summary["outcome"] = "FAILED"
        with self.assertRaisesRegex(ValueError, "summary-not-completed"):
            self.replay()
        summary["outcome"] = "COMPLETED"
        summary["results_scope"]["quality_verified"] = True
        with self.assertRaisesRegex(ValueError, "unsupported-result-claim"):
            self.replay()
        summary["results_scope"]["quality_verified"] = False
        summary["phases"].pop()
        with self.assertRaisesRegex(ValueError, "phase-count"):
            self.replay()

    def test_physical_phase_json_must_equal_summary_phase(self):
        path = self.f.root / "phase-00-none/phase.json"
        row = json.loads(path.read_bytes())
        row["error"] = "synthetic recorded failure"
        path.write_bytes(encode(row))
        with self.assertRaisesRegex(ValueError, "phase-file-summary"):
            v.replay(self.f.path)


if __name__ == "__main__":
    unittest.main()
