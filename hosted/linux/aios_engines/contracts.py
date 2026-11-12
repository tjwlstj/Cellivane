"""Deployment-scoped adapter declarations; these records grant no stop authority."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import UUID


def _text(value):
    return type(value) is str and 0 < len(value) <= 128 and all(c.isprintable() for c in value)


def _uuid(value):
    try:
        parsed = UUID(value)
        return type(value) is str and str(parsed) == value and parsed.int != 0
    except (ValueError, TypeError, AttributeError):
        return False


@dataclass(frozen=True)
class EngineSpec:
    adapter_kind: str
    wire_protocol: str
    evidence_kind: str
    contract_version: int = 1

    def __post_init__(self):
        if (not all(_text(v) for v in (self.adapter_kind, self.wire_protocol))
                or self.evidence_kind not in ('pinned-contract', 'fixture', 'protocol-contract')
                or type(self.contract_version) is not int or self.contract_version != 1):
            raise ValueError('engine-spec')


@dataclass(frozen=True)
class Deployment:
    engine: EngineSpec
    model_id: str
    service_id: str
    instance_id: str
    start_generation: int
    ownership: str = 'attached'

    def __post_init__(self):
        if (type(self.engine) is not EngineSpec or not _text(self.model_id)
                or not _uuid(self.service_id) or not _uuid(self.instance_id)
                or type(self.start_generation) is not int or not 1 <= self.start_generation < 1 << 63
                or self.ownership not in ('managed', 'attached')):
            raise ValueError('engine-deployment')

    def snapshot(self):
        return asdict(self)

    @classmethod
    def from_record(cls, record):
        if type(record) is not dict or set(record) != set(cls.__dataclass_fields__):
            raise ValueError('engine-deployment')
        engine = record['engine']
        if type(engine) is not dict or set(engine) != set(EngineSpec.__dataclass_fields__):
            raise ValueError('engine-spec')
        return cls(**{**record, 'engine': EngineSpec(**engine)})


@dataclass(frozen=True)
class CapabilityReport:
    deployment: Deployment
    text_completion: bool | None
    messages: bool | None
    streaming: bool | None
    usage: bool | None
    request_cancel: bool | None
    evidence_kind: str = 'fixture'
    contract_version: int = 1

    def __post_init__(self):
        if (type(self.deployment) is not Deployment
                or any(v is not None and type(v) is not bool for v in
                       (self.text_completion, self.messages, self.streaming, self.usage, self.request_cancel))
                or self.evidence_kind != self.deployment.engine.evidence_kind
                or type(self.contract_version) is not int or self.contract_version != 1):
            raise ValueError('engine-capability-report')

    def snapshot(self):
        return asdict(self)

    @classmethod
    def from_record(cls, record):
        if type(record) is not dict or set(record) != set(cls.__dataclass_fields__):
            raise ValueError('engine-capability-report')
        return cls(**{**record, 'deployment': Deployment.from_record(record['deployment'])})


def require_capabilities(deployment, report, *required):
    if type(deployment) is not Deployment or type(report) is not CapabilityReport or report.deployment != deployment:
        raise ValueError('engine-capability-binding')
    for name in required:
        if name not in ('text_completion', 'messages', 'streaming', 'usage', 'request_cancel'):
            raise ValueError('engine-capability-name')
        support = getattr(report, name)
        if support is not True:
            raise ValueError('engine-capability-' + name + ('-unknown' if support is None else '-unsupported'))
