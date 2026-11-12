"""Bounded profiles and an advisory selection policy for one 8B experiment.

This module performs no I/O, allocation, engine execution or attestation.  The
caller must authenticate reports, their source/host identity, ABC/CBA execution
order, cleanup and observations before using a selection.  A forecast is an
admission estimate, not a reservation, measured peak or proof that a model fits.
The old placement and soak contracts are deliberately unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
from statistics import median


MODEL_BYTES = 5_027_783_488
MODEL_SHA256 = "d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785"
BASELINE_SUMMARY_SHA256 = "bc92e826895eef371028a64f101408776f741aa16d04736e1b85b8a11366cd7f"
BASELINE_SIZE_VRAM_BYTES = 3_100_597_288
_GIB = 1024 ** 3
_PROFILE_SETTINGS = {"reference": (21, 4), "gpu29": (29, 4), "gpu29-threads8": (29, 8)}
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_CASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_IDENTITY_KEYS = frozenset(("model_sha256", "backend_tree_sha256", "corpus_sha256", "source_sha256"))


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _same_record(actual, expected):
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(_same_record(actual[key], item) for key, item in expected.items())
    if type(expected) is list:
        return len(actual) == len(expected) and all(_same_record(left, right) for left, right in zip(actual, expected))
    return actual == expected


@dataclass(frozen=True, slots=True)
class EfficiencyProfile:
    name: str
    num_gpu: int
    num_thread: int
    context_tokens: int = 2048
    slots: int = 1
    temperature: int = 0
    flash_attention: str = "auto"
    kv_cache_type: str = "f16"

    def __post_init__(self):
        self.validate()

    def validate(self):
        if type(self) is not EfficiencyProfile:
            raise ValueError("efficiency-profile-type")
        if type(self.name) is not str or self.name not in _PROFILE_SETTINGS:
            raise ValueError("efficiency-profile-name")
        for name, expected in (("num_gpu", _PROFILE_SETTINGS[self.name][0]),
                               ("num_thread", _PROFILE_SETTINGS[self.name][1]),
                               ("context_tokens", 2048), ("slots", 1), ("temperature", 0)):
            if type(getattr(self, name)) is not int or getattr(self, name) != expected:
                raise ValueError("efficiency-profile-" + name)
        if type(self.flash_attention) is not str or self.flash_attention != "auto":
            raise ValueError("efficiency-profile-flash-attention")
        if type(self.kv_cache_type) is not str or self.kv_cache_type != "f16":
            raise ValueError("efficiency-profile-kv-cache-type")

    @property
    def ollama_options(self):
        self.validate()
        return {"num_gpu": self.num_gpu, "num_thread": self.num_thread,
                "num_ctx": self.context_tokens, "temperature": self.temperature}

    @property
    def environment(self):
        self.validate()
        return {"OLLAMA_KV_CACHE_TYPE": "f16"}

    @property
    def unset_environment(self):
        self.validate()
        return ("OLLAMA_FLASH_ATTENTION",)

    def record(self):
        self.validate()
        return {"schema_version": 1, "name": self.name, "backend": "ollama",
                "num_gpu": self.num_gpu, "num_thread": self.num_thread,
                "context_tokens": self.context_tokens, "slots": self.slots,
                "temperature": self.temperature, "flash_attention": self.flash_attention,
                "kv_cache_type": self.kv_cache_type, "ollama_options": self.ollama_options,
                "environment": self.environment, "unset_environment": list(self.unset_environment),
                "model_bytes": MODEL_BYTES, "model_sha256": MODEL_SHA256,
                "scope": "fixed-8b-requested-efficiency-profile-only"}

    @property
    def identity_sha256(self):
        return sha256(_encoded(self.record())).hexdigest()


REFERENCE = EfficiencyProfile("reference", 21, 4)
GPU29 = EfficiencyProfile("gpu29", 29, 4)
GPU29_THREADS8 = EfficiencyProfile("gpu29-threads8", 29, 8)
PROFILES = (REFERENCE, GPU29, GPU29_THREADS8)


def get_profile(name):
    if type(name) is not str:
        raise ValueError("efficiency-profile-name")
    for profile in PROFILES:
        if name == profile.name:
            return profile
    raise ValueError("efficiency-profile-name")


def _bytes(value, name):
    if type(value) is not int or not 0 <= value < 2 ** 63:
        raise ValueError("efficiency-" + name)
    return value


def admission_forecast(profile, *, model_bytes, available_ram_bytes, free_vram_bytes):
    """Compare fresh available bytes with a pinned, advisory baseline forecast.

    The baseline /api/ps value was observed at 21/37 layers.  Added layer memory
    is only an estimate from the entire quantized file and a 1.15 multiplier;
    layers and their KV allocations need not be uniform.  Failed admission does
    not silently reduce layers or choose a different profile.
    """
    if type(profile) is not EfficiencyProfile:
        raise ValueError("efficiency-profile-type")
    profile.validate()
    if type(model_bytes) is not int or model_bytes != MODEL_BYTES:
        raise ValueError("efficiency-model-bytes")
    available = _bytes(available_ram_bytes, "available-ram-bytes")
    free = _bytes(free_vram_bytes, "free-vram-bytes")
    numerator = max(0, profile.num_gpu - 21) * model_bytes * 115
    incremental = (numerator + 37 * 100 - 1) // (37 * 100)
    forecast = BASELINE_SIZE_VRAM_BYTES + incremental + 256 * 1024 ** 2
    required_ram = model_bytes + 7 * _GIB
    required_vram = forecast + _GIB
    reasons = []
    if available < required_ram:
        reasons.append("insufficient-available-ram")
    if free < required_vram:
        reasons.append("insufficient-free-vram")
    return {"schema_version": 1, "profile_sha256": profile.identity_sha256,
            "model_bytes": model_bytes, "baseline_summary_sha256": BASELINE_SUMMARY_SHA256,
            "reference_layers": 21, "total_layers": 37,
            "reference_size_vram_bytes": BASELINE_SIZE_VRAM_BYTES,
            "incremental_layer_estimate_bytes": incremental,
            "layer_estimate_safety_factor": 1.15, "runtime_allowance_bytes": 256 * 1024 ** 2,
            "ram_overhead_bytes": 7 * _GIB, "vram_headroom_bytes": _GIB,
            "ram_required_bytes": required_ram, "vram_forecast_bytes": forecast,
            "vram_required_free_bytes": required_vram,
            "available_ram_bytes": available, "free_vram_bytes": free,
            "admitted": not reasons, "reasons": reasons,
            "scope": "baseline-observation-derived-advisory-not-reservation-or-fit-proof"}


def _seconds(value):
    if type(value) not in (int, float) or not 0 < value <= 3600 or not math.isfinite(value):
        raise ValueError("efficiency-sample-wall-seconds")
    return float(value)


def _percentile95(values):
    """Linear interpolation at (n-1)*.95, shared across all compared samples."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * .95
    lower = math.floor(position)
    return ordered[lower] + (ordered[math.ceil(position)] - ordered[lower]) * (position - lower)


def _identity(value):
    if type(value) is not dict or value.keys() != _IDENTITY_KEYS:
        raise ValueError("efficiency-report-identity")
    if any(type(item) is not str or _HEX.fullmatch(item) is None for item in value.values()):
        raise ValueError("efficiency-report-identity-digest")
    if value["model_sha256"] != MODEL_SHA256:
        raise ValueError("efficiency-report-model-identity")
    return dict(value)


def _round(value, index):
    if type(value) is not dict or value.keys() != {"index", "samples"}:
        raise ValueError("efficiency-report-round")
    if type(value["index"]) is not int or value["index"] != index:
        raise ValueError("efficiency-report-round-index")
    if type(value["samples"]) is not list or len(value["samples"]) != 56:
        raise ValueError("efficiency-report-sample-count")
    samples = {}
    for row in value["samples"]:
        if type(row) is not dict or row.keys() != {"case_id", "repeat", "wall_s", "text_sha256"}:
            raise ValueError("efficiency-report-sample")
        if type(row["case_id"]) is not str or _CASE.fullmatch(row["case_id"]) is None:
            raise ValueError("efficiency-report-case-id")
        if type(row["repeat"]) is not int or not 0 <= row["repeat"] <= 3:
            raise ValueError("efficiency-report-repeat")
        key = (row["case_id"], row["repeat"])
        if key in samples:
            raise ValueError("efficiency-report-duplicate-sample")
        digest = row["text_sha256"]
        if type(digest) is not str or _HEX.fullmatch(digest) is None:
            raise ValueError("efficiency-report-text-digest")
        samples[key] = (_seconds(row["wall_s"]), digest)
    cases = {key[0] for key in samples}
    if len(cases) != 14 or samples.keys() != {(case, repeat) for case in cases for repeat in range(4)}:
        raise ValueError("efficiency-report-case-repeat-grid")
    return samples


def _report(value):
    if type(value) is not dict or value.keys() != {"profile", "identity", "outcome", "resource_guard_passed", "rounds"}:
        raise ValueError("efficiency-report")
    profile_record = value["profile"]
    if type(profile_record) is not dict or type(profile_record.get("name")) is not str:
        raise ValueError("efficiency-report-profile")
    profile = get_profile(profile_record["name"])
    # Strict types also distinguish True from 1 and tuples from JSON arrays.
    if not _same_record(profile_record, profile.record()):
        raise ValueError("efficiency-report-profile-binding")
    identity = _identity(value["identity"])
    if type(value["outcome"]) is not str or value["outcome"] not in ("PASS", "FAIL"):
        raise ValueError("efficiency-report-outcome")
    if type(value["resource_guard_passed"]) is not bool:
        raise ValueError("efficiency-report-resource-guard")
    rows = value["rounds"]
    if type(rows) is not list or (len(rows) != 2 and not (value["outcome"] == "FAIL" and rows == [])):
        raise ValueError("efficiency-report-round-count")
    rounds = [_round(row, index) for index, row in enumerate(rows)]
    if len(rounds) == 2 and rounds[0].keys() != rounds[1].keys():
        raise ValueError("efficiency-report-round-case-binding")
    return profile, identity, value["outcome"] == "PASS" and value["resource_guard_passed"], rounds


def _metrics(samples):
    values = [sample[0] for sample in samples.values()]
    cases = sorted({key[0] for key in samples})
    return {"p50_s": median(values), "p95_s": _percentile95(values),
            "case_p50_s": {case: median(sample[0] for key, sample in samples.items() if key[0] == case)
                           for case in cases}}


def _ratio(numerator, denominator):
    value = numerator / denominator
    if not math.isfinite(value):
        raise ValueError("efficiency-nonfinite-ratio")
    return value


def _comparison(reference, candidate, *, index):
    ref = _metrics(reference)
    other = _metrics(candidate)
    cases = [{"case_id": case, "reference_p50_s": ref["case_p50_s"][case],
              "candidate_p50_s": other["case_p50_s"][case],
              "latency_ratio": _ratio(other["case_p50_s"][case], ref["case_p50_s"][case]),
              "speedup_ratio": _ratio(ref["case_p50_s"][case], other["case_p50_s"][case])}
             for case in ref["case_p50_s"]]
    speeds = sorted(row["speedup_ratio"] for row in cases)
    # Avoid overflowing the sum of two individually finite extreme ratios.
    speedup = speeds[6] + (speeds[7] - speeds[6]) / 2
    no_case_regression = all(row["latency_ratio"] <= 1.10 for row in cases)
    p50_gain = other["p50_s"] <= ref["p50_s"] * .95
    balanced_gain = speedup >= 1.05
    return {"index": index, "reference_p50_s": ref["p50_s"], "candidate_p50_s": other["p50_s"],
            "reference_p95_s": ref["p95_s"], "candidate_p95_s": other["p95_s"],
            "p50_latency_ratio": _ratio(other["p50_s"], ref["p50_s"]),
            "p95_latency_ratio": _ratio(other["p95_s"], ref["p95_s"]),
            "median_case_speedup_ratio": speedup, "p50_gain_passed": p50_gain,
            "balanced_case_gain_passed": balanced_gain, "case_regression_guard_passed": no_case_regression,
            "qualifies": p50_gain and balanced_gain and no_case_regression, "cases": cases}


def choose_profile(candidate_reports, reference=REFERENCE):
    """Recompute a conservative choice from two complete 14x4 rounds/profile.

    Each round and their aggregate need a >=5% overall median latency reduction
    and median case speedup >=1.05.  No case median may regress by >10%; aggregate
    p95 may regress by at most 5%.  Text digests must match the reference at every
    case/repeat in both rounds.  A failed reference cannot qualify any choice.
    Reports and returned records are detached; no caller container is retained.
    """
    if type(reference) is not EfficiencyProfile or reference.record() != REFERENCE.record():
        raise ValueError("efficiency-reference-profile")
    if type(candidate_reports) is not list or len(candidate_reports) != len(PROFILES):
        raise ValueError("efficiency-report-count")
    reports = {}
    for raw in candidate_reports:
        profile, identity, passed, rounds = _report(raw)
        if profile.name in reports:
            raise ValueError("efficiency-duplicate-profile")
        reports[profile.name] = (identity, passed, rounds)
    ref_identity, ref_passed, ref_rounds = reports[reference.name]
    for identity, _passed, rounds in reports.values():
        if identity != ref_identity:
            raise ValueError("efficiency-report-identity-mismatch")
        if rounds and ref_rounds and rounds[0].keys() != ref_rounds[0].keys():
            raise ValueError("efficiency-report-case-binding")
    comparisons = []
    for profile in PROFILES[1:]:
        _identity_value, passed, rounds = reports[profile.name]
        reasons = []
        if not ref_passed:
            reasons.append("reference-not-qualified")
        if not passed:
            reasons.append("candidate-not-qualified")
        if not ref_rounds or not rounds:
            reasons.append("incomplete-rounds")
        metrics = []
        overall = None
        if ref_rounds and rounds:
            parity = all(ref_rounds[index][key][1] == row[1]
                         for index, round_samples in enumerate(rounds) for key, row in round_samples.items())
            if not parity:
                reasons.append("output-mismatch")
            metrics = [_comparison(ref_rounds[index], row, index=index) for index, row in enumerate(rounds)]
            merged_ref = {(index, *key): row for index, rows in enumerate(ref_rounds) for key, row in rows.items()}
            merged = {(index, *key): row for index, rows in enumerate(rounds) for key, row in rows.items()}
            # Preserve case grouping while giving repeated rounds distinct keys.
            merged_ref = {(key[1], key[0] * 4 + key[2]): row for key, row in merged_ref.items()}
            merged = {(key[1], key[0] * 4 + key[2]): row for key, row in merged.items()}
            overall = _comparison(merged_ref, merged, index="overall")
            if not all(row["qualifies"] for row in metrics) or not overall["qualifies"]:
                reasons.append("insufficient-balanced-p50-gain-or-case-regression")
            if overall["candidate_p95_s"] > overall["reference_p95_s"] * 1.05:
                reasons.append("p95-regression")
        comparisons.append({"profile": profile.record(), "qualifies": not reasons,
                            "reasons": reasons, "rounds": metrics, "overall": overall})
    qualified = [row for row in comparisons if row["qualifies"]]
    winner = min(qualified, key=lambda row: row["overall"]["candidate_p50_s"]) if qualified else None
    selected = winner["profile"] if winner else reference.record()
    return {"schema_version": 1, "policy": "efficiency-balanced-v1", "eligible": ref_passed,
            "selected_profile": selected, "reason": "measured-balanced-gain" if winner else
            "no-consistent-gain" if ref_passed else "reference-not-qualified",
            "identity": dict(ref_identity), "comparisons": comparisons,
            "scope": "measured-selection-for-this-model-backend-host-only"}
