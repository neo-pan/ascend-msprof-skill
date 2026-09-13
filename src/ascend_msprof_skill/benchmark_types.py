"""Natural measurement structure and partial normalized facts, without I/O."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, FiniteFloat, JsonValue, model_validator

from .evidence_types import ArtifactPath, EvidenceFact


def nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError('expected nonempty text')
    return value


def zoned_timestamp(value: str) -> str:
    if datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is None:
        raise ValueError('timestamp requires a timezone')
    return value


Text = Annotated[str, AfterValidator(nonblank)]
Timestamp = Annotated[Text, AfterValidator(zoned_timestamp)]
Count = Annotated[int, Field(ge=0)]
PositiveCount = Annotated[int, Field(gt=0)]
Duration = Annotated[FiniteFloat, Field(gt=0)]
Shape = Annotated[tuple[PositiveCount, ...], Field(strict=False)]
Stride = Annotated[tuple[Count, ...], Field(strict=False)]
Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class BenchmarkSource(EvidenceFact):
    artifact: ArtifactPath
    sha256: Digest
    entrypoints: Annotated[tuple[Text, ...], Field(strict=False, min_length=1)]


class BenchmarkCitation(EvidenceFact):
    artifact: ArtifactPath
    sha256: Digest | None = None
    field_ref: str
    role: Literal['baseline', 'candidate'] | None = None


class BenchmarkIssue(EvidenceFact):
    id: str
    status: Literal['missing', 'invalid', 'mismatch', 'conflict']
    reason_code: str
    value: JsonValue = None
    sources: Annotated[tuple[BenchmarkCitation, ...], Field(strict=False)]


class Producer(EvidenceFact):
    name: Text
    version: Text


class Implementation(EvidenceFact):
    id: Text | None
    source: Text | None


class Subject(EvidenceFact):
    scope: Text | None
    implementation: Implementation | None
    build: dict[str, JsonValue] | None


class Workload(EvidenceFact):
    id: Text
    shape: Shape
    dtype: Text
    case_count: PositiveCount
    parameters: dict[str, JsonValue]


class Tensor(EvidenceFact):
    name: Text
    dtype: Text
    shape: Shape
    stride: Stride
    layout: Text
    offset: Count

    @model_validator(mode='after')
    def aligned_rank(self) -> Tensor:
        if len(self.shape) != len(self.stride):
            raise ValueError('stride_rank_mismatch')
        return self


Tensors = Annotated[tuple[Tensor, ...], Field(strict=False, min_length=1)]


class DigestIdentity(EvidenceFact):
    kind: Literal['digest']
    sha256: Digest


class GeneratorIdentity(EvidenceFact):
    kind: Literal['generator']
    name: Text
    version: Text
    parameters: dict[str, JsonValue]
    seed: Count


InputIdentity = Annotated[DigestIdentity | GeneratorIdentity, Field(discriminator='kind')]


class Reference(EvidenceFact):
    id: Text
    version: Text


class Correctness(EvidenceFact):
    status: Literal['pass', 'fail', 'error']
    subject_id: Text
    reference: Reference
    method: Text
    tolerances: dict[str, Annotated[FiniteFloat, Field(ge=0)]]
    case_count: PositiveCount


class Protocol(EvidenceFact):
    natural: bool
    timer: Producer
    scope: Text
    synchronization: Text
    warmup: Count
    cache_policy: Text
    reuse_policy: Text
    concurrency: Text
    sample_unit: Text
    calls_per_sample: PositiveCount
    normalization: Text
    independence: Text
    execution_order: Text


class Device(EvidenceFact):
    model: Text
    id: Text
    count: PositiveCount


class Environment(EvidenceFact):
    device: Device
    driver_version: Text
    runtimes: dict[Text, Text]
    control_policy: dict[str, JsonValue]
    source: Text

    @model_validator(mode='after')
    def cann_recorded(self) -> Environment:
        if 'cann' not in self.runtimes:
            raise ValueError('environment runtimes require cann')
        return self


class Measurement(EvidenceFact):
    # Preserve a valid point estimate even when its other declared fields fail.
    value_ms: Duration | None
    statistic: Literal['mean', 'median'] | None
    sample_count: PositiveCount | None


class Failure(EvidenceFact):
    stage: Literal['compile', 'correctness', 'timing'] | None
    message: Text | None


class BenchmarkRecord(EvidenceFact):
    contract_version: Text | None
    measurement_id: Text | None
    producer: Producer | None
    collected_at: Timestamp | None
    subject: Subject | None
    workload: Workload | None
    inputs: Tensors | None
    outputs: Tensors | None
    input_identity: InputIdentity | None
    correctness: Correctness | None
    protocol: Protocol | None
    environment: Environment | None
    measurement: Measurement | None
    failure: Failure | None

    @property
    def subject_id(self) -> str | None:
        return self.subject.implementation.id if self.subject and self.subject.implementation else None


    @property
    def complete(self) -> bool:
        return (all(getattr(self, field) is not None for field in type(self).model_fields if field != 'failure')
                and self.subject.scope is not None and self.subject.build is not None
                and self.subject.implementation is not None and self.subject.implementation.id is not None
                and self.subject.implementation.source is not None
                and all(getattr(self.measurement, field) is not None for field in Measurement.model_fields))

    def comparison_conditions(self) -> dict[str, object]:
        correctness, environment = self.correctness, self.environment
        return {
            'subject.scope': self.subject.scope if self.subject else None,
            'workload': self.workload, 'inputs': self.inputs, 'outputs': self.outputs,
            'input_identity': self.input_identity,
            **{f'correctness.{key}': getattr(correctness, key) if correctness else None
               for key in ('reference', 'method', 'tolerances', 'case_count')},
            'protocol': self.protocol,
            **{f'environment.{key}': getattr(environment, key) if environment else None
               for key in ('device', 'driver_version', 'runtimes', 'control_policy')},
            'measurement.statistic': self.measurement.statistic if self.measurement else None,
        }


def correctness_record_issues(record: BenchmarkRecord) -> tuple[BenchmarkIssue, ...]:
    """Fact-only correctness policy; callers attach the original source citations."""
    issues = []
    def add(field, status, reason, value):
        issues.append(BenchmarkIssue(id=field, status=status, reason_code=reason, value=value, sources=()))
    correctness = record.correctness
    if correctness is not None:
        if correctness.status != 'pass':
            add('correctness.status', 'invalid', 'correctness_failed', correctness.status)
        if correctness.case_count != 1:
            add('correctness.case_count', 'invalid', 'only_single_case_supported', correctness.case_count)
        if record.subject_id is not None and record.subject_id != correctness.subject_id:
            add('correctness.subject_id', 'mismatch', 'correctness_subject_mismatch', correctness.subject_id)
    if record.failure is not None and record.failure.stage != 'timing':
        add('failure', 'invalid', 'measurement_stage_failed', record.failure.model_dump(mode='json'))
    return tuple(issues)


def natural_record_issues(record: BenchmarkRecord) -> tuple[BenchmarkIssue, ...]:
    """Scientific applicability of partial records, independent of structural validity."""
    issues = []
    def add(field, reason, value):
        issues.append(BenchmarkIssue(id=field, status='invalid', reason_code=reason, value=value, sources=()))
    for field in ('inputs', 'outputs'):
        tensors = getattr(record, field)
        if tensors is not None:
            names = [tensor.name for tensor in tensors]
            for i, name in enumerate(names):
                if name in names[:i]:
                    add(f'{field}[{i}].name', 'duplicate_tensor_name', name)
    if record.contract_version is not None and record.contract_version != '1.0':
        add('contract_version', 'unsupported_contract', record.contract_version)
    if record.workload is not None and record.workload.case_count != 1:
        add('workload.case_count', 'only_single_case_supported', record.workload.case_count)
    if record.protocol is not None and not record.protocol.natural:
        add('protocol.natural', 'natural_measurement_required', False)
    issues.extend(correctness_record_issues(record))
    if record.failure is not None and record.failure.stage == 'timing':
        add('failure', 'measurement_stage_failed', record.failure.model_dump(mode='json'))
    return tuple(issues)


def same_condition(a: object, b: object) -> bool:
    """Compare declared JSON types and values, retaining explicit numeric types."""
    if type(a) is not type(b):
        return False
    if isinstance(a, BaseModel):
        return all(same_condition(getattr(a, key), getattr(b, key)) for key in type(a).model_fields)
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same_condition(a[key], b[key]) for key in a)
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(same_condition(left, right) for left, right in zip(a, b))
    return a == b


class BenchmarkRegistration(EvidenceFact):
    schema_version: Literal['2.0']
    imports: Annotated[tuple[BenchmarkSource, ...], Field(strict=False)]


class BenchmarkContext(BenchmarkRegistration):
    schema_version: Literal['2.0'] = '2.0'
    measurement: BenchmarkRecord | None
    issues: Annotated[tuple[BenchmarkIssue, ...], Field(strict=False)]


class BenchmarkMeasurement(EvidenceFact):
    record: BenchmarkRecord | None
    conflicting_records: Annotated[tuple[BenchmarkRecord, ...], Field(strict=False)]
    sources: Annotated[tuple[BenchmarkCitation, ...], Field(strict=False)]
    authority: Literal['caller_provided'] = 'caller_provided'

    @model_validator(mode='after')
    def sourced_records(self) -> BenchmarkMeasurement:
        if (self.record is not None or self.conflicting_records) and not self.sources:
            raise ValueError('normalized measurements require snapshot citations')
        if any(source.sha256 is None or source.field_ref != 'assessment' or source.role is not None for source in self.sources):
            raise ValueError('measurement sources require an assessment snapshot and digest')
        if self.conflicting_records and (len(self.conflicting_records) < 2 or self.record is not None):
            raise ValueError('conflicting measurements cannot select a record')
        return self
