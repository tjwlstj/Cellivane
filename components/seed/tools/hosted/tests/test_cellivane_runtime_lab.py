"""Exercise the lab's real finally path using model-free dependency doubles.

The JSON files are synthetic cleanup fixtures, never native execution evidence.
No worker, HTTP server, model, compiler, or process is started by these tests.
"""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("synthetic_runtime_lab", TOOLS / "cellivane_runtime_lab.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


class RuntimeLabCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.order = []
        self.ready = {"kind": "ready", "protocol": 1, "engine_commit": lab.assets.COMMIT,
            "threads": 4, "context_tokens": 512, "gpu_layers": 0, "model_load_s": .01,
            "template_mode": "qwen3-nonthinking"}
        self.cleanup = {"job_assigned": True, "job_terminated": True, "job_active_processes": 0,
            "job_closed": True, "job_cleanup_confirmed": True, "job_error": None,
            "process_exited": True, "returncode": 0, "error": None,
            "created_suspended": True, "assigned_before_resume": True,
            "primary_thread_closed": True, "process_handle_closed": True}
        self.transport = Mock(ready=self.ready, load_wall_s=.02, cleanup=copy.deepcopy(self.cleanup))
        self.transport.close.side_effect = lambda: self.order.append("transport-close")
        self.runtime = Mock()
        self.runtime.prepare.return_value = {"warmup": None, "wall_s": .001}
        self.runtime.shutdown.side_effect = self.shutdown
        self.seed = Mock()
        self.seed.complete.side_effect = self.complete
        self.seed.status.return_value = {"synthetic": True, "backend_calls": 2, "computed": 2}
        self.seed.close.side_effect = lambda: self.order.append("seed-close")
        self.artifact = {"model_sha256": "1" * 64, "worker_sha256": "2" * 64,
            "engine_identity": "3" * 64, "sealed_engine_sha256": "4" * 64}
        self.artifact_calls = 0
        self.summary = {"model": {"path": str(self.root / "unused-model.gguf"), "bytes": 20, "sha256": "1" * 64},
            "worker": {"path": str(self.root / "unused-worker.exe"), "bytes": 20, "sha256": "2" * 64},
            "engine": {"engine_identity": "3" * 64}, "native_engine_directory": str(self.root / "unused-engine"),
            "native_engine_files": [], "source": {"files": []}, "config": lab.configuration(2)}

    def shutdown(self):
        self.order.append("runtime-shutdown")
        return {"kind": "stopped", "id": 3, "model_disposed": True}

    def complete(self, payload):
        self.runtime.last = {"payload": {"id": len(self.order) + 1, "op": "generate",
            "messages": payload["messages"], "max_tokens": 64},
            "response": {"text": "SYNTHETIC FIXTURE", "finish_reason": "stop"}, "wall_s": .01}
        return {"synthetic": True, "model": lab.ALIAS}

    def make_transport(self, command, directory):
        # Preserve real artifact hashing and phase.json persistence while
        # replacing the only native process constructor with a strict double.
        self.order.append("transport-created")
        for name in ("stdin.jsonl", "stdout.jsonl", "stderr.log"):
            (directory / name).write_bytes(b"SYNTHETIC MODEL-FREE FIXTURE\n")
        return self.transport

    def artifact_state(self, *args):
        self.artifact_calls += 1
        self.order.append("artifact-before" if self.artifact_calls == 1 else "artifact-after")
        return copy.deepcopy(self.artifact)

    def run_phase(self, artifact_state=None):
        with patch.object(lab, "memory_snapshot", return_value={"source": "synthetic",
                "available_bytes": 16 * 1024**3, "total_bytes": 32 * 1024**3}), \
                patch.object(lab, "artifact_state", side_effect=artifact_state or self.artifact_state), \
                patch.object(lab, "NativeTransport", side_effect=self.make_transport) as create_transport, \
                patch.object(lab, "NativeRuntime", return_value=self.runtime) as create_runtime, \
                patch.object(lab, "RuntimeSeedEngine", return_value=self.seed), \
                patch.object(lab, "Audit") as create_audit, \
                patch.object(lab, "SeedHTTPServer") as create_server, \
                contextlib.redirect_stdout(io.StringIO()):
            result = lab.phase(self.root, 0, "none", self.summary)
        create_transport.assert_called_once()
        create_runtime.assert_called_once()
        create_audit.assert_called_once()
        create_server.assert_not_called()
        self.runtime.prepare.assert_called_once()
        self.assertEqual(self.seed.complete.call_count, 2)
        self.seed.close.assert_called_once()
        self.runtime.shutdown.assert_called_once()
        self.transport.close.assert_called_once()
        persisted = json.loads((self.root / "phase-00-none/phase.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted, result)
        self.assertEqual(persisted["cleanup"], self.cleanup)
        self.assertEqual(set(persisted["files"]), {"stdin", "stdout", "stderr"})
        self.assertEqual(persisted["requests"][0]["response"]["text"], "SYNTHETIC FIXTURE")
        self.assertLess(self.order.index("runtime-shutdown"), self.order.index("transport-close"))
        return persisted

    def test_seed_close_audit_failure_still_shuts_down_and_cleans_owned_transport(self):
        def close_failure():
            self.order.append("seed-close")
            raise OSError("synthetic audit persistence failure")
        self.seed.close.side_effect = close_failure
        result = self.run_phase()
        self.assertEqual(result["error"], "seed-close:OSError:synthetic audit persistence failure")
        self.assertEqual(result["cleanup_errors"], [result["error"]])
        self.assertTrue(result["shutdown"]["model_disposed"])
        self.assertLess(self.order.index("seed-close"), self.order.index("runtime-shutdown"))
        self.assertEqual(result["after"], self.artifact)

    def test_shutdown_error_still_cleans_transport_and_preserves_failed_phase(self):
        def shutdown_failure():
            self.order.append("runtime-shutdown")
            raise RuntimeError("synthetic shutdown response lost")
        self.runtime.shutdown.side_effect = shutdown_failure
        result = self.run_phase()
        self.assertEqual(result["error"], "runtime-shutdown:RuntimeError:synthetic shutdown response lost")
        self.assertIsNone(result["shutdown"])
        self.assertEqual(result["cleanup_errors"], [result["error"]])
        self.assertTrue(result["cleanup"]["job_cleanup_confirmed"])
        self.assertEqual(result["after"], self.artifact)

    def test_after_artifact_hash_error_is_persisted_after_native_cleanup(self):
        def hash_failure(*args):
            value = self.artifact_state(*args)
            if self.artifact_calls == 2:
                raise OSError("synthetic model became unreadable")
            return value
        result = self.run_phase(hash_failure)
        self.assertEqual(result["error"], "after-artifact-hashes:OSError:synthetic model became unreadable")
        self.assertEqual(result["cleanup_errors"], [result["error"]])
        self.assertIsNone(result["after"])
        self.assertTrue(result["shutdown"]["model_disposed"])
        self.assertTrue(result["source_unchanged"])
        self.assertLess(self.order.index("transport-close"), self.order.index("artifact-after"))


if __name__ == "__main__":
    unittest.main()
