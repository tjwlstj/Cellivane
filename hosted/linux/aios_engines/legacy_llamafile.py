"""The pinned llamafile ChatML protocol and legacy receipt-v3 validator.

This adapter has no process or network ownership. The existing worker retains
the connected-socket/backend binding and the Task owner retains cancellation.
Ordinary engine replies cannot supply or synthesize that execution evidence.
"""
from __future__ import annotations

import hashlib
from datetime import datetime

from .contracts import EngineSpec

RECEIPT_KEYS = {"schema_version", "request_id", "started_at", "purpose", "model_id", "model_sha256",
                "backend_sha256", "provenance_sha256", "request_body", "request_sha256", "response_body",
                "response_sha256", "content", "tokens_predicted", "elapsed_ns", "outcome", "error",
                "backend_execution", "user_prompt", "space_context"}


class LegacyLlamafileAdapter:
    """Preserve the existing pinned wire bytes, errors, and receipt semantics."""

    spec = EngineSpec("legacy-llamafile", "completion-chatml", "pinned-contract")

    @staticmethod
    def serialize(prompt: str, *, warmup: bool = False, space_context: dict | None = None) -> bytes:
        from aios_agent import inference
        if type(prompt) is not str or not prompt.strip() or len(prompt.encode("utf-8")) > 4096 or any(ord(c) < 32 and c not in "\n\t" for c in prompt):
            raise ValueError("prompt-invalid")
        if space_context is not None:
            from aios_agent.space import prompt_with_context
            if warmup:
                raise ValueError("space-invalid")
            text = ("<|im_start|>system\n" + inference.SPACE_SYSTEM + "<|im_end|>\n<|im_start|>user\n"
                    + prompt_with_context(prompt, space_context)
                    + " /no_think<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n")
            return inference.encoded({"prompt": text, "n_predict": inference.CONTEXT_RESPONSE_TOKENS, "temperature": 0.0,
                                      "seed": 1, "cache_prompt": False, "stream": False})
        # Explicit ChatML formatting belongs only to the pinned Qwen3 protocol.
        # Model text remains output and grants no command or resource authority.
        text = ("<|im_start|>system\nYou are the AIOS MAIN assistant. Answer briefly. "
                "Describe only the provided facts; you cannot execute commands. /no_think<|im_end|>\n"
                "<|im_start|>user\n" + prompt + " /no_think<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n")
        return inference.encoded({"prompt": text, "n_predict": 8 if warmup else 64, "temperature": 0.0,
                                  "seed": 1, "cache_prompt": False, "stream": False})

    @staticmethod
    def validate_response(config: dict, body: bytes, raw: bytes, *, token_limit: int,
                          context_required: bool = False) -> dict:
        """Validate the worker's reply without adding echo or execution facts."""
        from aios_agent import inference
        payload = inference.parse(raw)
        if context_required and (payload.get("truncated") is not False
                or payload.get("prompt") != inference.parse(body)["prompt"]):
            raise ValueError("backend-prompt-integrity")
        content, tokens = payload.get("content"), payload.get("tokens_predicted")
        if (type(content) is not str or not content.strip() or type(tokens) is not int or not 1 <= tokens <= token_limit
                or payload.get("model") != config["model_id"]):
            raise ValueError("empty-or-invalid-completion")
        return payload

    @staticmethod
    def validate_worker_result(stdout, stderr, returncode, *, config, body, token_limit,
                               backend_descriptor=None, backend_capture_kind="live", space_context=None):
        """Repeat response checks at the existing supervising boundary."""
        from aios_agent import inference
        if returncode != 0 or stderr:
            raise ValueError("backend-worker-failed")
        output = inference.parse(stdout, maximum=inference.MAX_WORKER_OUTPUT)
        if set(output) != {"response_body", "content", "tokens_predicted", "backend_execution"}:
            raise ValueError("backend-worker-schema")
        if backend_descriptor is not None and (type(output["backend_execution"]) is not dict
                or output["backend_execution"].get("descriptor") != backend_descriptor
                or output["backend_execution"].get("capture_kind") != backend_capture_kind):
            raise ValueError("backend-worker-execution")
        if backend_descriptor is None and output["backend_execution"] is not None:
            raise ValueError("backend-worker-execution")
        raw = output["response_body"].encode("utf-8")
        parsed = inference.parse(raw)
        if space_context is not None and (parsed.get("truncated") is not False
                or parsed.get("prompt") != inference.parse(body)["prompt"]):
            raise ValueError("backend-prompt-integrity")
        if (parsed.get("content") != output["content"] or parsed.get("tokens_predicted") != output["tokens_predicted"]
                or parsed.get("model") != config["model_id"]
                or type(output["tokens_predicted"]) is not int or not 1 <= output["tokens_predicted"] <= token_limit
                or type(output["content"]) is not str or not output["content"].strip()):
            raise ValueError("backend-worker-response")
        return {**output, "response_sha256": inference.digest(raw), "outcome": "OK"}

    @staticmethod
    def validate_receipt(receipt: dict, *, row: dict, config: dict) -> None:
        """Validate legacy-v3 joins; this is not a normalized engine envelope."""
        from aios_agent import inference

        def require(condition, reason):
            if not condition:
                raise ValueError("request-" + reason)

        def same(left, right):
            return inference.encoded(left) == inference.encoded(right)

        require(type(receipt) is dict and set(receipt) == RECEIPT_KEYS and type(receipt.get("schema_version")) is int
                and receipt["schema_version"] == 3, "receipt-schema")
        require(type(receipt["started_at"]) is str, "receipt-time")
        try:
            stamp = datetime.fromisoformat(receipt["started_at"])
        except ValueError as exc:
            raise ValueError("request-receipt-time") from exc
        require(stamp.tzinfo is not None, "receipt-time")
        require(type(receipt["elapsed_ns"]) is int and 0 <= receipt["elapsed_ns"] < 1 << 63, "clock")
        expected = {"request_id": row["request_id"], "purpose": "user",
                    **{key: config[key] for key in
                       ("model_id", "model_sha256", "backend_sha256", "provenance_sha256")},
                    **{key: row[key] for key in
                       ("request_body", "request_sha256", "user_prompt", "space_context")}}
        require(all(key in receipt and same(receipt[key], value) for key, value in expected.items()),
                "receipt-join")
        require(receipt.get("outcome") in ("OK", "ERROR"), "receipt-outcome")
        if receipt["outcome"] == "OK":
            raw = receipt.get("response_body")
            require(type(raw) is str and receipt.get("error") is None, "receipt-response")
            payload = inference.parse(raw.encode("utf-8"))
            request = inference.parse(row["request_body"].encode("utf-8"))
            require(receipt.get("response_sha256") == hashlib.sha256(raw.encode("utf-8")).hexdigest()
                    and payload.get("prompt") == request["prompt"] and payload.get("truncated") is False
                    and payload.get("model") == config["model_id"]
                    and type(receipt.get("content")) is str and bool(receipt["content"].strip())
                    and payload.get("content") == receipt["content"]
                    and type(receipt.get("tokens_predicted")) is int
                    and 1 <= receipt["tokens_predicted"] <= inference.CONTEXT_RESPONSE_TOKENS
                    and type(payload.get("tokens_predicted")) is int
                    and payload["tokens_predicted"] == receipt["tokens_predicted"], "receipt-response")
            execution = receipt.get("backend_execution")
            require(type(execution) is dict
                    and set(execution) == {"schema_version", "descriptor", "capture_kind", "before", "send", "after"}
                    and type(execution["schema_version"]) is int and execution["schema_version"] == 1
                    and execution["capture_kind"] == row["backend_expected"]["capture_kind"]
                    and all(type(execution[key]) is dict for key in ("before", "send", "after"))
                    and same(execution["descriptor"], row["backend_expected"]["descriptor"]), "receipt-backend")
        else:
            require(receipt.get("error") in ("backend-failed", "backend-timeout")
                    and all(receipt.get(key) is None for key in
                            ("response_body", "response_sha256", "content", "backend_execution"))
                    and type(receipt.get("tokens_predicted")) is int
                    and receipt["tokens_predicted"] == 0, "receipt-error")
