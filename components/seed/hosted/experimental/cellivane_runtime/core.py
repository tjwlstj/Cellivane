"""Bounded runtime policy. Native worker owns model/context and libllama calls.

Every generation has a fresh context and sampler. No saved KV, retry, streaming,
weight paging or result memoization lives here. An invalid worker reply poisons
this runtime; a caller must close its owned worker instead of reusing it.
"""
from __future__ import annotations

import json
import math
import threading
import time
from uuid import uuid4

from cellivane_seed.core import EngineUnavailable, InvalidRequest, SeedEngine

from .murphy import MurphyPlan


class RuntimeFault(RuntimeError):
    pass


def _finite_seconds(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _messages(value):
    if type(value) is not list or not 1 <= len(value) <= 32:
        raise ValueError("runtime-messages")
    for message in value:
        if (type(message) is not dict or set(message) != {"role", "content"}
                or type(message["role"]) is not str or message["role"] not in ("system", "user", "assistant")
                or type(message["content"]) is not str or not message["content"].strip()
                or any(ord(c) < 32 and c not in "\n\t" for c in message["content"])):
            raise ValueError("runtime-message")
    if not any(m["role"] == "user" for m in value):
        raise ValueError("runtime-user-required")
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 16 * 1024:
        raise ValueError("runtime-input-bytes")
    return json.loads(json.dumps(value, ensure_ascii=False))


class NativeRuntime:
    def __init__(self, exchange, ready, *, model="cellivane-runtime-target", plan=None):
        self.plan = MurphyPlan() if plan is None else plan
        if type(self.plan) is not MurphyPlan or not callable(exchange):
            raise ValueError("runtime-construction")
        if (type(ready) is not dict or ready.get("kind") != "ready" or ready.get("protocol") != 1
                or type(ready.get("protocol")) is not int or ready.get("threads") != self.plan.threads
                or type(ready.get("threads")) is not int or type(ready.get("context_tokens")) is not int
                or ready.get("context_tokens") != self.plan.context_tokens or ready.get("gpu_layers") != 0
                or type(ready.get("gpu_layers")) is not int):
            raise RuntimeFault("runtime-ready-profile")
        self._exchange, self.ready, self.model = exchange, ready, model
        self.state, self._sequence, self._generations = "LOADED", 0, 0
        self._lock = threading.Lock()
        self.last = None
        self.preparation = None

    def _generate(self, messages, max_tokens):
        copied = _messages(messages)
        if type(max_tokens) is not int or not 1 <= max_tokens <= self.plan.max_tokens:
            raise ValueError("runtime-max-tokens")
        self._sequence += 1
        command = {"id": self._sequence, "op": "generate", "messages": copied, "max_tokens": max_tokens}
        started = time.perf_counter()
        try:
            reply = self._exchange(command)
            if (type(reply) is not dict or reply.get("kind") != "result" or reply.get("id") != command["id"]
                    or type(reply.get("id")) is not int or type(reply.get("text")) is not str
                    or len(reply["text"].encode("utf-8")) > 256 * 1024
                    or reply.get("context_disposed") is not True or reply.get("sampler_disposed") is not True
                    or reply.get("context_id") != self._generations + 1 or reply.get("sampler_id") != self._generations + 1
                    or type(reply.get("context_id")) is not int or type(reply.get("sampler_id")) is not int):
                raise RuntimeFault("runtime-generation-binding")
            tokens = reply.get("tokens")
            if (type(tokens) is not list or not 1 <= len(tokens) <= max_tokens
                    or any(type(t) is not int or t < 0 for t in tokens)
                    or type(reply.get("prompt_tokens")) is not int or reply["prompt_tokens"] < 1
                    or type(reply.get("completion_tokens")) is not int or reply["completion_tokens"] != len(tokens)
                    or reply["prompt_tokens"] + max_tokens > self.plan.context_tokens
                    or reply.get("finish_reason") not in ("stop", "length")
                    or (reply.get("finish_reason") == "length" and len(tokens) != max_tokens)
                    or any(not _finite_seconds(reply.get(k)) for k in ("prefill_s", "decode_s", "elapsed_s"))):
                raise RuntimeFault("runtime-generation-fields")
            self._generations += 1
            self.last = {"payload": command, "response": reply, "wall_s": time.perf_counter() - started}
            return self.last
        except BaseException:
            self.state = "POISONED"
            raise

    def prepare(self):
        with self._lock:
            if self.state != "LOADED":
                raise RuntimeFault("runtime-prepare-state")
            self.state = "PREPARING"
            started = time.perf_counter()
            warmup = None
            if self.plan.mode == "murphy":
                warmup = self._generate([{"role": "user", "content": "Reply briefly. /no_think"}], 1)
            self.preparation = {"plan": self.plan.record(), "warmup": warmup,
                                "wall_s": time.perf_counter() - started,
                                "context_reused": False, "sampler_reused": False}
            self.state = "READY"
            return self.preparation

    def __call__(self, payload):
        with self._lock:
            if self.state != "READY":
                raise RuntimeFault("runtime-not-ready")
            if (type(payload) is not dict or set(payload) != {"model", "messages", "max_tokens", "temperature", "stream"}
                    or payload["model"] != self.model or payload["stream"] is not False
                    or type(payload["temperature"]) not in (int, float) or payload["temperature"] != 0):
                raise ValueError("runtime-request")
            result = self._generate(payload["messages"], payload["max_tokens"])["response"]
            # Preserve length/thinking output. Seed's existing strict validator
            # decides whether this answer satisfies its plain completion subset.
            return {"id": str(uuid4()), "object": "chat.completion", "created": int(time.time()), "model": self.model,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": result["text"]},
                                 "finish_reason": result["finish_reason"]}],
                    "usage": {"prompt_tokens": result["prompt_tokens"], "completion_tokens": result["completion_tokens"],
                              "total_tokens": result["prompt_tokens"] + result["completion_tokens"]}}

    def shutdown(self):
        with self._lock:
            if self.state == "CLOSED":
                raise RuntimeFault("runtime-already-closed")
            self._sequence += 1
            command = {"id": self._sequence, "op": "shutdown"}
            try:
                reply = self._exchange(command)
                if (type(reply) is not dict or reply.get("kind") != "stopped" or type(reply.get("id")) is not int
                        or reply.get("id") != command["id"]
                        or reply.get("model_disposed") is not True):
                    raise RuntimeFault("runtime-shutdown-ack")
                self.state = "CLOSED"
                return reply
            except BaseException:
                self.state = "POISONED"
                raise


class RuntimeSeedEngine(SeedEngine):
    """Apply the native profile before Seed counts or dispatches a request.

    Seed's general callable contract allows 512 output tokens; this CPU worker
    allows 64. Unsupported native input is a client error, not a failed model
    call. Other Seed admission, result and audit behavior stays shared.
    """
    def __init__(self, runtime, **kwargs):
        if type(runtime) is not NativeRuntime:
            raise ValueError("runtime-seed-backend")
        self._runtime = runtime
        super().__init__(runtime, **kwargs)

    def _request(self, payload):
        if self._runtime.state != "READY":
            raise EngineUnavailable("runtime-unavailable")
        normalized, key = super()._request(payload)
        if normalized["max_tokens"] > self._runtime.plan.max_tokens:
            raise InvalidRequest("request-runtime-max-tokens")
        try:
            _messages(normalized["messages"])
        except ValueError as exc:
            raise InvalidRequest("request-runtime-messages") from exc
        return normalized, key

    def status(self):
        status = super().status()
        # Health must not advertise admission when the retained native worker
        # has failed or its model has been released. Keep Seed's healthy shape.
        if self._runtime.state != "READY":
            status["poisoned"] = True
        return status
