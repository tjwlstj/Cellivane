"""Pinned protocol regression fixtures; these tests do not execute a model."""
from __future__ import annotations

import copy
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "hosted/linux"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from aios_agent import inference
from aios_engines.legacy_llamafile import LegacyLlamafileAdapter, RECEIPT_KEYS
from test_hosted_console import agent
import test_hosted_request_state as request_fixture


class LegacyAdapterTests(unittest.TestCase):
    def test_pre_extraction_request_byte_goldens(self):
        # Digests/lengths captured from the unmodified 7d475248 inference.py.
        # The context fixture fixes observation, model, and management identity.
        context = agent("space", bound=True)["space_context"]
        cases = ((False, None, "29bb7818d95996277970ad544b28191b2b1b83834fc5d9aa484f1163bc5708b0", 335),
                 (True, None, "0dda62b272eeedf44eb9b620f88f6895ca07a900311731477edb8b9829ca73f5", 334),
                 (False, context, "6d2dae932066c080c95df00ddbd0d805bfbf79e1c21f310b04d4594af18e6b0d", 1659))
        for warmup, space_context, digest, length in cases:
            with self.subTest(warmup=warmup, context=space_context is not None):
                body = LegacyLlamafileAdapter.serialize("hello", warmup=warmup, space_context=space_context)
                self.assertEqual(len(body), length)
                self.assertEqual(hashlib.sha256(body).hexdigest(), digest)
                self.assertEqual(inference.request_body("hello", warmup=warmup, space_context=space_context), body)

    def test_token_limits_and_existing_prompt_error_names(self):
        self.assertEqual(inference.parse(LegacyLlamafileAdapter.serialize("hello"))["n_predict"], 64)
        self.assertEqual(inference.parse(LegacyLlamafileAdapter.serialize("hello", warmup=True))["n_predict"], 8)
        context = agent("space", bound=True)["space_context"]
        self.assertEqual(inference.parse(LegacyLlamafileAdapter.serialize("hello", space_context=context))["n_predict"], 192)
        for prompt in ("", " ", "x\x00y", "한" * 1366, None):
            with self.subTest(prompt=repr(prompt)[:20]), self.assertRaisesRegex(ValueError, "^prompt-invalid$"):
                LegacyLlamafileAdapter.serialize(prompt)
        with self.assertRaisesRegex(ValueError, "^space-invalid$"):
            LegacyLlamafileAdapter.serialize("hello", warmup=True, space_context=context)

    def test_worker_validation_keeps_context_echo_and_invalid_completion_reasons(self):
        body = LegacyLlamafileAdapter.serialize("hello")
        request = inference.parse(body)
        config = {"model_id": "fixture-model"}
        reply = {"model": config["model_id"], "content": "fixture answer", "tokens_predicted": 3,
                 "prompt": request["prompt"], "truncated": False}
        validated = LegacyLlamafileAdapter.validate_response(config, body, inference.encoded(reply),
            token_limit=192, context_required=True)
        self.assertEqual(validated, reply)
        for changed in ({key: value for key, value in reply.items() if key != "prompt"},
                        {**reply, "prompt": "changed"}, {**reply, "truncated": 0}):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "^backend-prompt-integrity$"):
                LegacyLlamafileAdapter.validate_response(config, body, inference.encoded(changed),
                    token_limit=192, context_required=True)
        for changed in ({**reply, "content": " "}, {**reply, "tokens_predicted": True},
                        {**reply, "tokens_predicted": 193}, {**reply, "model": "other"}):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "^empty-or-invalid-completion$"):
                LegacyLlamafileAdapter.validate_response(config, body, inference.encoded(changed), token_limit=192)

    def test_supervisor_validation_preserves_exact_worker_fields_and_execution_join(self):
        body = LegacyLlamafileAdapter.serialize("hello")
        reply = {"model": "fixture-model", "content": "fixture answer", "tokens_predicted": 3}
        raw = inference.encoded(reply).decode()
        output = {"response_body": raw, "content": reply["content"], "tokens_predicted": 3,
                  "backend_execution": None}
        kwargs = {"config": {"model_id": "fixture-model"}, "body": body, "token_limit": 64}
        validated = LegacyLlamafileAdapter.validate_worker_result(inference.encoded(output), b"", 0, **kwargs)
        self.assertEqual(validated["outcome"], "OK")
        self.assertEqual(validated["response_sha256"], hashlib.sha256(raw.encode()).hexdigest())
        self.assertIsNone(validated["backend_execution"])
        self.assertEqual(inference._validated_worker_result(inference.encoded(output), b"", 0, **kwargs), validated)
        for changed, reason in (({**output, "extra": None}, "backend-worker-schema"),
                                ({**output, "content": "forged"}, "backend-worker-response"),
                                ({**output, "backend_execution": {}}, "backend-worker-execution")):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, "^" + reason + "$"):
                LegacyLlamafileAdapter.validate_worker_result(inference.encoded(changed), b"", 0, **kwargs)
        for stderr, code in ((b"diagnostic", 0), (b"", 1)):
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, "^backend-worker-failed$"):
                LegacyLlamafileAdapter.validate_worker_result(inference.encoded(output), stderr, code, **kwargs)

    def test_legacy_receipt_v3_rejects_response_and_management_evidence_synthesis(self):
        fixture = request_fixture.RequestStateTests()
        fixture.setUp()
        receipt = fixture.answer()
        row = fixture.state.snapshot()
        self.assertEqual(set(receipt), RECEIPT_KEYS)
        self.assertIsNone(LegacyLlamafileAdapter.validate_receipt(receipt, row=row, config=fixture.config))
        changed_response = inference.parse(receipt["response_body"].encode())
        del changed_response["prompt"]
        no_echo = copy.deepcopy(receipt)
        no_echo["response_body"] = inference.encoded(changed_response).decode()
        no_echo["response_sha256"] = inference.digest(no_echo["response_body"].encode())
        for changed, reason in ((no_echo, "request-receipt-response"),
                                ({**receipt, "schema_version": 1}, "request-receipt-schema"),
                                ({**receipt, "backend_execution": None}, "request-receipt-backend"),
                                ({**receipt, "model_sha256": "0" * 64}, "request-receipt-join")):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, "^" + reason + "$"):
                LegacyLlamafileAdapter.validate_receipt(changed, row=row, config=fixture.config)

    def test_legacy_error_receipt_keeps_timeout_separate_from_success(self):
        fixture = request_fixture.RequestStateTests()
        fixture.setUp()
        receipt = fixture.answer()
        row = fixture.state.snapshot()
        for error in ("backend-failed", "backend-timeout"):
            changed = {**receipt, "outcome": "ERROR", "error": error, "tokens_predicted": 0,
                       **{key: None for key in ("response_body", "response_sha256", "content", "backend_execution")}}
            with self.subTest(error=error):
                LegacyLlamafileAdapter.validate_receipt(changed, row=row, config=fixture.config)
                with self.assertRaisesRegex(ValueError, "^request-receipt-error$"):
                    LegacyLlamafileAdapter.validate_receipt({**changed, "content": "invented"}, row=row, config=fixture.config)


if __name__ == "__main__":
    unittest.main()
