"""Estimate a session cost from two fixed calibration rounds.

This module performs no I/O or execution and does not authenticate calibration
evidence. The caller must validate identity, source, host profile, age and output
agreement before calling choose(). Missing or inapplicable calibration uses an
explicit baseline reason. Estimates do not guarantee latency or residency.
"""
from __future__ import annotations

import math


_MODES = frozenset(("none", "murphy"))
_MODE_KEYS = frozenset(("preparation_s", "request_wall_s"))
_BASELINE_REASONS = frozenset((
    "no-calibration",
    "identity-mismatch",
    "host-profile-mismatch",
    "source-mismatch",
    "calibration-expired",
    "output-mismatch",
    "legacy-no-host",
))


def _count(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 1024:
        raise ValueError("murphy-expected-requests")
    return value


def _seconds(value, *, positive: bool) -> float:
    if (type(value) not in (int, float) or not 0 <= value <= 3600
            or (positive and value == 0) or not math.isfinite(value)):
        raise ValueError("murphy-calibration-seconds")
    return float(value)


def _mode(record: dict, count: int) -> dict:
    if type(record) is not dict or record.keys() != _MODE_KEYS:
        raise ValueError("murphy-calibration-mode")
    preparation = _seconds(record["preparation_s"], positive=False)
    requests = record["request_wall_s"]
    if type(requests) is not list or len(requests) != 2:
        raise ValueError("murphy-calibration-requests")
    mean = sum(_seconds(value, positive=True) for value in requests) / 2
    return {"preparation_s": preparation, "mean_request_s": mean,
            "estimated_session_s": preparation + count * mean}


def _record(count: int, *, eligible: bool, selected: str, reason: str, rounds: list) -> dict:
    return {"schema_version": 1, "policy": "murphy-session-cost-v1", "expected_requests": count,
            "margin_percent": 5, "eligible": eligible, "selected_mode": selected, "reason": reason,
            "rounds": rounds, "scope": "fixed-calibration-corpus-cost-estimate"}


def choose(rounds: list, expected_requests: int) -> dict:
    """Select Murphy only if both rounds meet the 5% session saving margin."""
    count = _count(expected_requests)
    if type(rounds) is not list or len(rounds) != 2:
        raise ValueError("murphy-calibration-rounds")
    observations = []
    for index, record in enumerate(rounds):
        if type(record) is not dict or record.keys() != _MODES:
            raise ValueError("murphy-calibration-round")
        none = _mode(record["none"], count)
        murphy = _mode(record["murphy"], count)
        baseline_cost, murphy_cost = none["estimated_session_s"], murphy["estimated_session_s"]
        qualifies = murphy_cost <= baseline_cost * .95 and murphy_cost < baseline_cost
        observations.append({"index": index, "none": none, "murphy": murphy, "qualifies": qualifies})
    selected = all(item["qualifies"] for item in observations)
    return _record(count, eligible=True, selected="murphy" if selected else "none",
                   reason="consistent-session-savings" if selected else "insufficient-consistent-savings",
                   rounds=observations)


def baseline(expected_requests: int, reason: str) -> dict:
    """Return a fresh explicit no-calibration selection; never infer a reason."""
    count = _count(expected_requests)
    if type(reason) is not str or reason not in _BASELINE_REASONS:
        raise ValueError("murphy-baseline-reason")
    return _record(count, eligible=False, selected="none", reason=reason, rounds=[])
