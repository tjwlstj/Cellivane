"""Murphy v1: explicit CPU preparation, not weight transformation or autotuning."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class MurphyPlan:
    mode: str = "murphy"
    threads: int = 4
    context_tokens: int = 512
    batch: int = 128
    max_tokens: int = 64

    def __post_init__(self):
        if type(self.mode) is not str or self.mode not in ("none", "murphy"):
            raise ValueError("murphy-mode")
        for name, expected in (("threads", 4), ("context_tokens", 512), ("batch", 128), ("max_tokens", 64)):
            if type(getattr(self, name)) is not int or getattr(self, name) != expected:
                raise ValueError("murphy-fixed-cpu-profile:" + name)

    def record(self):
        self.__post_init__()
        return {"schema_version": 1, "mode": self.mode, "threads": self.threads,
                "context_tokens": self.context_tokens, "batch": self.batch, "max_tokens": self.max_tokens,
                "placement": "cpu", "warmup_max_tokens": 1 if self.mode == "murphy" else 0,
                "weight_values_changed": False, "custom_weight_repack": False,
                "automatic_plan_selection": False, "native_mtp": False,
                "scope": "fixed-cpu-preparation-not-residency-control"}
