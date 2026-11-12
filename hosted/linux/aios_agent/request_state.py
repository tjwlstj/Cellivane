"""One daemon-owned question record with adapter-specific result validation.

This module performs no I/O and grants no authority. Its caller must durably
save admission before dispatch, authenticate the owner, observe the owned
worker, and supply the exact backend stop result. Worker exit, backend stop,
and a verified model answer are deliberately separate facts.
"""
from __future__ import annotations

import copy
import hashlib
from aios_backend import IDENTITY_KEYS
from aios_backend.protocol import validate_identity, validate_reply
from aios_management.binding import validate_source
from aios_resources.backend import validate_descriptor
from aios_service.lifecycle import is_uuid
from . import inference, space

from aios_engines.legacy_llamafile import LegacyLlamafileAdapter, RECEIPT_KEYS


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError("request-" + reason)


def same(left, right) -> bool:
    return inference.encoded(left) == inference.encoded(right)


def tick(value: int) -> None:
    require(type(value) is int and 0 <= value < 1 << 63, "clock")


class RequestState:
    """Single-writer state; snapshots and repeated reads never mutate it."""

    def __init__(self, *, request_id: str, owner: dict, config: dict, source: dict,
                 management: dict, space_context: dict, prompt: str,
                 backend_expected: dict, accepted_ns: int):
        require(is_uuid(request_id), "id")
        tick(accepted_ns)
        validate_identity(owner)
        inference.validate_config(config)
        validate_source(source)
        space.validate_packet(space_context, source_record=source,
                              management_snapshot=management, now_ns=accepted_ns)
        require(source["model_ready"] is True and source["lifecycle_state"] == "active"
                and management["binding_current"] is True, "target-not-ready")
        validate_reply(backend_expected, "status")
        require(backend_expected["outcome"] == "OK" and backend_expected["state"] == "RUNNING",
                "backend-not-ready")
        descriptor = backend_expected["descriptor"]
        validate_descriptor(descriptor, config)
        require(owner["host_boot_id"] == source["host_boot_id"] == descriptor["host_boot_id"]
                and owner["uid"] == backend_expected["service_record"]["supervisor_identity"]["uid"],
                "owner-boundary")
        require(source["model_sha256"] == config["model_sha256"], "model-mismatch")
        body = inference.request_body(prompt, space_context=space_context).decode("utf-8")
        self._config = copy.deepcopy(config)
        self._row = copy.deepcopy({
            "schema_version": 1, "request_id": request_id, "owner": owner,
            "source_before": source, "management_before": management,
            "backend_expected": backend_expected, "space_context": space_context,
            "user_prompt": prompt, "request_body": body,
            "request_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "revision": 1, "phase": "ACCEPTED", "model_outcome": None,
            "accepted_ns": accepted_ns, "updated_ns": accepted_ns,
            "started_ns": None, "cancel_requested_ns": None, "finished_ns": None,
            "worker_process_id": None, "worker_exit_code": None,
            "inference_receipt": None, "backend_stop": None,
            "backend_stopped_ns": None, "not_started_reason": None,
        })

    def snapshot(self) -> dict:
        return copy.deepcopy(self._row)

    @property
    def terminal(self) -> bool:
        return self._row["phase"] == "FINISHED"

    def check_owner(self, observed_owner: dict) -> None:
        validate_identity(observed_owner)
        require(same(observed_owner, self._row["owner"]), "owner-mismatch")

    def _time(self, now_ns: int) -> None:
        tick(now_ns)
        require(now_ns >= self._row["updated_ns"], "clock-regression")

    def _update(self, now_ns: int, **fields) -> None:
        self._time(now_ns)
        self._row.update(copy.deepcopy(fields), updated_ns=now_ns,
                         revision=self._row["revision"] + 1)

    def mark_running(self, worker_pid: int, *, now_ns: int) -> None:
        require(self._row["phase"] == "ACCEPTED", "dispatch-state")
        require(type(worker_pid) is int and 0 < worker_pid < 1 << 63, "worker-identity")
        backend = self._row["backend_expected"]["service_record"]
        require(worker_pid not in (self._row["owner"]["process_id"], self._row["source_before"]["process_id"],
                backend["supervisor_identity"]["process_id"], backend["child_identity"]["process_id"]),
                "worker-identity")
        self._update(now_ns, phase="RUNNING", worker_process_id=worker_pid, started_ns=now_ns)

    def request_cancel(self, owner: dict, *, now_ns: int) -> str:
        self.check_owner(owner)
        self._time(now_ns)
        if self.terminal and self._row["model_outcome"] != "UNKNOWN":
            return "ALREADY_TERMINAL"
        if self._row["cancel_requested_ns"] is not None:
            return "ALREADY_REQUESTED"
        # A failed/timed-out worker does not prove that its HTTP request stopped
        # in the model backend. Permit one explicit fenced backend stop after
        # UNKNOWN without changing the already recorded worker outcome.
        self._update(now_ns, phase="FINISHED" if self.terminal else "CANCEL_REQUESTED",
                     cancel_requested_ns=now_ns)
        return "ACCEPTED"

    def finish_without_dispatch(self, reason: str, *, now_ns: int) -> None:
        require(not self.terminal and self._row["worker_process_id"] is None, "dispatch-state")
        require(reason in ("cancel-before-dispatch", "dispatch-failed"), "not-started-reason")
        require(reason != "cancel-before-dispatch" or self._row["cancel_requested_ns"] is not None,
                "cancel-not-requested")
        self._update(now_ns, phase="FINISHED", model_outcome="NOT_STARTED",
                     finished_ns=now_ns, not_started_reason=reason)

    def _check_receipt(self, receipt: dict) -> None:
        LegacyLlamafileAdapter.validate_receipt(receipt, row=self._row, config=self._config)

    def record_worker_exit(self, worker_pid: int, return_code: int, *,
                           receipt: dict | None, now_ns: int) -> bool:
        self._time(now_ns)
        require(type(worker_pid) is int and worker_pid == self._row["worker_process_id"], "worker-identity")
        require(type(return_code) is int and -(1 << 31) <= return_code < 1 << 32, "worker-exit")
        if receipt is not None:
            self._check_receipt(receipt)
            require(return_code == 0 or receipt["outcome"] != "OK", "worker-exit")
        if self.terminal:
            require(self._row["worker_exit_code"] == return_code
                    and same(self._row["inference_receipt"], receipt), "terminal-rewrite")
            return False
        require(self._row["phase"] in ("RUNNING", "CANCEL_REQUESTED"), "worker-state")
        self._update(now_ns, phase="FINISHED", finished_ns=now_ns, worker_exit_code=return_code,
                     inference_receipt=receipt,
                     model_outcome="ANSWERED" if receipt is not None and receipt["outcome"] == "OK" else "UNKNOWN")
        return True

    def record_backend_stop(self, stopped: dict, *, now_ns: int) -> bool:
        self._time(now_ns)
        require(self._row["cancel_requested_ns"] is not None, "cancel-not-requested")
        validate_reply(stopped, "stop")
        require(stopped["outcome"] == "OK" and stopped["state"] == "STOPPED"
                and type(stopped["service_record"]) is dict, "backend-stop-unconfirmed")
        expected = self._row["backend_expected"]["service_record"]
        record = stopped["service_record"]
        frozen_keys = (*IDENTITY_KEYS, "supervisor_identity", "child_identity",
                       "backend_source_instance", "config_sha256", "profile", "source_only")
        require(all(same(record[key], expected[key]) for key in frozen_keys), "backend-stop-mismatch")
        if self._row["backend_stop"] is not None:
            require(same(self._row["backend_stop"], stopped), "backend-stop-rewrite")
            return False
        # This observation does not change the model outcome, including a
        # response that arrived while cancellation raced with completion.
        self._update(now_ns, backend_stop=stopped, backend_stopped_ns=now_ns)
        return True
