"""Model-free resource/admission tests; no tensor backend is started."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cellivane_seed_soak as soak
from cellivane_bridge.runtime import load_config


def observation():
    return {"memory": {"available_bytes": 18 * soak.GiB, "total_bytes": 32 * soak.GiB},
            "gpu": {"free_bytes": 5 * soak.GiB, "temperature_c": 40}}


class SoakAdmissionTests(unittest.TestCase):
    def test_pinned_8b_native_layer_receipt_is_accepted_and_stale_total_fails(self):
        # Minimal native receipt from the hash-pinned Qwen3-8B warmup: 36 blocks + output.
        raw = "load_tensors: offloaded 19/37 layers to GPU\nload_tensors: CUDA0 model buffer size = 2484.51 MiB\n"
        place = soak.comparison.observe_placement(raw)
        soak.require_placement(place, 19, soak.MODELS["8b-q4"]["layers"])
        with self.assertRaises(RuntimeError): soak.require_placement(place, 19, 33)
        with self.assertRaises(RuntimeError): soak.require_placement(place, 20, 37)

    def test_soak_bridge_configuration_is_accepted_by_real_bridge_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            config, engines = soak.bridge_configuration(Path(folder), 18991, 18992, "fixture:latest")
            path = Path(folder) / "bridge.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            checked, parsed = load_config(path)
            self.assertEqual(checked, config)
            self.assertEqual([e.record() for e in parsed], [e.record() for e in engines])
            self.assertEqual(checked["deadline_s"], 180)

    def test_plan_keeps_gpu_and_host_headroom_and_partial_layers(self):
        model = soak.MODELS["8b-q4"]
        plan = soak.plan_for(model, observation())
        self.assertLess(plan["layers"], model["layers"])
        self.assertGreater(plan["layers"], 0)
        self.assertEqual(plan["ram_required_bytes"], model["bytes"] + 7 * soak.GiB)
        self.assertIn("not-reservation", plan["scope"])

    def test_insufficient_ram_or_vram_has_no_cpu_fallback(self):
        for resource in ("memory", "gpu"):
            value = observation()
            value[resource]["available_bytes" if resource == "memory" else "free_bytes"] = soak.GiB
            with self.assertRaises(ValueError): soak.plan_for(soak.MODELS["8b-q4"], value)

    def test_resource_guard_boundary_and_thermal_limit(self):
        value = observation()
        value["memory"]["available_bytes"] = soak.GUARDS["minimum_ram_free_bytes"]
        value["gpu"]["free_bytes"] = soak.GUARDS["minimum_vram_free_bytes"]
        value["gpu"]["temperature_c"] = 84
        self.assertIsNone(soak.guard_failure(value))
        value["gpu"]["temperature_c"] = 85
        self.assertEqual(soak.guard_failure(value), "gpu-temperature")
        value["memory"]["available_bytes"] -= 1
        self.assertEqual(soak.guard_failure(value), "ram-headroom")

    def test_129_tokens_is_rejected_before_seed_backend_call(self):
        calls = []
        seed = soak.SoakSeed(lambda request: calls.append(request), model="fixture", identity="fixture", cache_entries=0)
        with self.assertRaises(soak.InvalidRequest):
            seed.complete({"model": "fixture", "messages": [{"role": "user", "content": "fixture"}], "max_tokens": 129})
        self.assertEqual(calls, [])
        self.assertEqual(seed.status()["backend_calls"], 0)
        seed.close()

    @unittest.skipUnless(os.name == "nt", "Windows-owned-process launcher boundary")
    def test_failed_preflight_preserves_failed_record_without_native_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wrong = root / "wrong.gguf"
            wrong.write_bytes(b"synthetic wrong model")
            with patch.object(soak.lab, "OwnedProcess") as native, redirect_stdout(io.StringIO()):
                status = soak.main(["--mode", "smoke", "--model", "8b-q4", "--model-file", str(wrong),
                    "--asset-root", str(root / "assets"), "--storage-root", str(root)])
            self.assertEqual(status, 1)
            native.assert_not_called()
            report = json.loads(next(root.glob("soak-runs/*/soak.json")).read_text(encoding="utf-8"))
            self.assertEqual(report["acceptance"], "FAIL")
            self.assertIn("soak-model-artifact-pin", report["error"])

    def test_sampler_persists_exact_resource_wire_and_detects_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            observed = observation()
            observed["gpu"]["temperature_c"] = 85
            wire = {"observation": observed, "gpu_raw": {"stdout": "synthetic model-free resource evidence"}}
            sampler = soak.Sampler(Path(folder) / "resources.jsonl")
            try:
                with patch.object(soak.resources, "observe_with_evidence", return_value=wire):
                    sampler.sample()
                self.assertTrue(sampler.guard.is_set())
                self.assertEqual(sampler.reason, "gpu-temperature")
                row = json.loads(sampler.path.read_text(encoding="utf-8"))
                self.assertEqual(row["gpu_raw"], wire["gpu_raw"])
            finally:
                sampler.close()


if __name__ == "__main__":
    unittest.main()
