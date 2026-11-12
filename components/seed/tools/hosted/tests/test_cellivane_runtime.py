"""Runtime/Seed boundary and lifecycle failures without model execution."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "hosted/experimental"))
from cellivane_runtime import NativeRuntime, MurphyPlan, RuntimeFault, RuntimeSeedEngine
from cellivane_seed.core import SeedEngine, BackendFailure, EngineUnavailable, InvalidRequest


READY = {"kind": "ready", "protocol": 1, "threads": 4, "context_tokens": 512, "gpu_layers": 0}


class Worker:
    def __init__(self):
        self.commands, self.count = [], 0
        self.change = lambda value: value

    def __call__(self, command):
        self.commands.append(copy.deepcopy(command))
        if command["op"] == "shutdown":
            return {"kind": "stopped", "id": command["id"], "model_disposed": True}
        self.count += 1
        return self.change({"kind": "result", "id": command["id"], "text": "OK", "tokens": [10],
                "prompt_tokens": 9, "completion_tokens": 1, "finish_reason": "stop",
                "context_id": self.count, "sampler_id": self.count,
                "context_disposed": True, "sampler_disposed": True,
                "prefill_s": .01, "decode_s": .02, "elapsed_s": .03})


def payload():
    return {"model": "cellivane-runtime-target", "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 8, "temperature": 0, "stream": False}


class RuntimeTests(unittest.TestCase):
    def make(self, mode="none"):
        worker = Worker()
        runtime = NativeRuntime(worker, dict(READY), plan=MurphyPlan(mode=mode))
        return worker, runtime

    def test_prepare_is_required_and_once_only(self):
        worker, runtime = self.make()
        with self.assertRaises(RuntimeFault): runtime(payload())
        self.assertEqual([], worker.commands)
        runtime.prepare()
        with self.assertRaises(RuntimeFault): runtime.prepare()

    def test_murphy_discards_warm_context_before_user_generation(self):
        worker, runtime = self.make("murphy")
        prepared = runtime.prepare()
        self.assertEqual(1, prepared["warmup"]["payload"]["max_tokens"])
        self.assertEqual(1, prepared["warmup"]["response"]["context_id"])
        runtime(payload())
        self.assertEqual(2, runtime.last["response"]["context_id"])
        self.assertTrue(runtime.last["response"]["context_disposed"])
        self.assertEqual(2, len(worker.commands))

    def test_invalid_output_poisons_and_cannot_dispatch_again(self):
        for key, value in (("context_disposed", False), ("id", 17), ("context_id", 0),
                           ("completion_tokens", 2), ("decode_s", float("nan")), ("finish_reason", "length")):
            with self.subTest(key=key):
                worker, runtime = self.make()
                runtime.prepare()
                worker.change = lambda result: {**result, key: value}
                with self.assertRaises(RuntimeFault): runtime(payload())
                self.assertEqual("POISONED", runtime.state)
                with self.assertRaises(RuntimeFault): runtime(payload())
                self.assertEqual(1, len(worker.commands))

    def test_input_rejected_before_worker_and_runtime_remains_ready(self):
        worker, runtime = self.make()
        runtime.prepare()
        for key, value in (("max_tokens", 65), ("max_tokens", True), ("stream", True),
                           ("messages", [{"role": "system", "content": "no user"}]),
                           ("messages", [{"role": "user", "content": "bad\rinput"}])):
            request = payload(); request[key] = value
            with self.assertRaises(ValueError): runtime(request)
        self.assertEqual([], worker.commands)
        self.assertEqual("READY", runtime.state)

    def test_native_limit_is_a_seed_client_error_before_dispatch(self):
        worker, runtime = self.make()
        runtime.prepare()
        seed = RuntimeSeedEngine(runtime, model=runtime.model, identity="fixture-runtime",
                                 cache_entries=0, cache_bytes=0)
        request = payload(); request["max_tokens"] = 65
        with self.assertRaises(InvalidRequest): seed.complete(request)
        self.assertEqual(0, seed.status()["backend_calls"])
        self.assertEqual(1, seed.status()["rejected"])
        self.assertEqual([], worker.commands)
        self.assertEqual("READY", runtime.state)
        seed.close()

    def test_boolean_shutdown_id_cannot_acknowledge_request_one(self):
        worker, runtime = self.make()
        runtime._exchange = lambda command: {"kind": "stopped", "id": True, "model_disposed": True}
        with self.assertRaises(RuntimeFault): runtime.shutdown()
        self.assertEqual("POISONED", runtime.state)

    def test_poisoned_native_runtime_blocks_seed_health_and_later_admission(self):
        worker, runtime = self.make()
        runtime.prepare()
        seed = RuntimeSeedEngine(runtime, model=runtime.model, identity="fixture-runtime", cache_entries=0)
        worker.change = lambda result: {**result, "context_disposed": False}
        with self.assertRaises(BackendFailure): seed.complete(payload())
        self.assertTrue(seed.status()["poisoned"])
        self.assertEqual("POISONED", runtime.state)
        with self.assertRaises(EngineUnavailable): seed.complete(payload())
        self.assertEqual(1, seed.status()["backend_calls"])
        self.assertEqual(1, len(worker.commands))
        seed.close()

    def test_seed_generation_is_computed_each_time(self):
        worker, runtime = self.make()
        runtime.prepare()
        seed = SeedEngine(runtime, model=runtime.model, identity="fixture-runtime", cache_entries=0, cache_bytes=0)
        first, second = seed.complete(payload()), seed.complete(payload())
        self.assertEqual("computed", first["cellivane"]["execution"])
        self.assertEqual(first["choices"], second["choices"])
        self.assertEqual(2, len(worker.commands))
        self.assertEqual(2, seed.status()["backend_calls"])
        seed.close()

    def test_existing_seed_contract_rejects_length_and_thinking_without_rewrite(self):
        for field, value in (("finish_reason", "length"), ("text", "<think>x</think>OK")):
            worker, runtime = self.make()
            runtime.prepare()
            worker.change = lambda result: {**result, field: value,
                **({"tokens": [10] * 8, "completion_tokens": 8} if field == "finish_reason" else {})}
            seed = SeedEngine(runtime, model=runtime.model, identity="fixture-runtime", cache_entries=0)
            with self.assertRaises(BackendFailure): seed.complete(payload())
            self.assertEqual(value, runtime.last["response"][field])
            seed.close()

    def test_shutdown_ack_closes_and_blocks_reuse(self):
        worker, runtime = self.make()
        runtime.prepare()
        runtime(payload())
        self.assertTrue(runtime.shutdown()["model_disposed"])
        self.assertEqual("CLOSED", runtime.state)
        with self.assertRaises(RuntimeFault): runtime(payload())
        self.assertEqual(2, len(worker.commands))

    def test_profile_is_exact_and_not_arbitrary_cpu_budget(self):
        for kwargs in ({"threads": True}, {"context_tokens": 1024}, {"mode": "gpu"}):
            with self.assertRaises(ValueError): MurphyPlan(**kwargs)
        self.assertFalse(MurphyPlan().record()["custom_weight_repack"])
        for invalid in (False, 0, ""):
            with self.assertRaises(ValueError): NativeRuntime(Worker(), dict(READY), plan=invalid)


if __name__ == "__main__": unittest.main()
