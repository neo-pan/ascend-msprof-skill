"""Caller-owned natural measurements: normalization and offline evidence reading."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal, TypeVar

from pydantic import ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

from .artifact_reader import decode_json, read_json
from .benchmark_types import (BenchmarkCitation, BenchmarkContext, BenchmarkIssue, BenchmarkMeasurement,
    BenchmarkRecord, BenchmarkRegistration, BenchmarkSource, Correctness, Duration, Environment, Failure, Implementation,
    InputIdentity, Measurement, PositiveCount, Producer, Protocol, Subject, Tensors, Text, Timestamp, Workload,
    natural_record_issues)
from .evidence_types import EvidenceFact

ARTIFACT = 'analysis/benchmark_context.json'
_STRICT = ConfigDict(strict=True, allow_inf_nan=False)
_TEXT = TypeAdapter(Text, config=_STRICT)
_TIMESTAMP = TypeAdapter(Timestamp, config=_STRICT)
_RAW_OBJECT = TypeAdapter(dict[str, object], config=_STRICT)
_OBJECT = TypeAdapter(dict[str, JsonValue], config=_STRICT)
_DURATION = TypeAdapter(Duration, config=_STRICT)
_STATISTIC = TypeAdapter(Literal['mean', 'median'], config=_STRICT)
_FAILURE_STAGE = TypeAdapter(Literal['compile', 'correctness', 'timing'], config=_STRICT)
_COUNT = TypeAdapter(PositiveCount, config=_STRICT)
_TENSORS = TypeAdapter(Tensors, config=_STRICT)
_IDENTITY = TypeAdapter(InputIdentity)
_JSON = TypeAdapter(JsonValue, config=_STRICT)
T = TypeVar('T')


def digest_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def semantic_key(record: BenchmarkRecord) -> str:
    return json.dumps(record.model_dump(mode='json'), sort_keys=True, separators=(',', ':'), allow_nan=False)


def source_ref(source: BenchmarkSource, field: str = '') -> BenchmarkCitation:
    return BenchmarkCitation(artifact=source.artifact, sha256=source.sha256,
                             field_ref='assessment' + (f'.{field}' if field else ''))


def issue(field: str, status: str, reason: str, source: BenchmarkSource | None = None,
          value: JsonValue = None) -> BenchmarkIssue:
    citation = source_ref(source, field) if source else BenchmarkCitation(artifact=ARTIFACT, field_ref=field)
    return BenchmarkIssue(id=field, status=status, reason_code=reason, value=value, sources=(citation,))


def _location(prefix: str, parts: tuple) -> str:
    for part in parts:
        prefix += f'[{part}]' if isinstance(part, int) else ('.' if prefix else '') + part
    return prefix


def _component(adapter: TypeAdapter[T] | type[T], value: object, field: str,
               source: BenchmarkSource, issues: list[BenchmarkIssue]) -> T | None:
    if value is None:
        issues.append(issue(field, 'missing', 'required_field_missing', source))
        return None
    try:
        # Raw caller extensions stay in the snapshot. Normalized model loading
        # uses the model's extra=forbid default instead of this projection.
        return (adapter.validate_python(value, extra='ignore') if isinstance(adapter, TypeAdapter)
                else adapter.model_validate(value, extra='ignore'))
    except ValidationError as exc:
        for error in exc.errors(include_url=False):
            parts = error['loc']
            if field == 'input_identity' and parts and parts[0] in {'digest', 'generator'}:
                parts = parts[1:]
            location = _location(field, parts)
            missing = error['type'] == 'missing' or error.get('input', 0) is None
            reason = 'required_field_missing' if missing else 'invalid_value'
            if 'tolerances' in location and not missing:
                reason = 'invalid_tolerance'
            if 'stride_rank_mismatch' in error['msg']:
                reason = 'stride_rank_mismatch'
            raw = error.get('input')
            try:
                raw = _JSON.validate_python(raw)
            except ValidationError:
                raw = None  # The original token remains in its cited snapshot.
            issues.append(issue(location, 'missing' if missing else 'invalid', reason, source, raw))
        return None


def _object(value: object, field: str, source: BenchmarkSource, issues: list[BenchmarkIssue]) -> dict | None:
    return _component(_RAW_OBJECT, value, field, source, issues)


def validate_measurement(value: object, source: BenchmarkSource) -> tuple[BenchmarkRecord | None, list[BenchmarkIssue]]:
    """Normalize independent components; samples stay solely in the raw snapshot."""
    issues: list[BenchmarkIssue] = []
    data = _object(value, '', source, issues)
    if data is None:
        return None, issues
    values = {name: _component(adapter, data.get(name), name, source, issues) for name, adapter in (
        ('contract_version', _TEXT), ('measurement_id', _TEXT), ('producer', Producer),
        ('collected_at', _TIMESTAMP), ('workload', Workload), ('inputs', _TENSORS), ('outputs', _TENSORS),
        ('input_identity', _IDENTITY), ('correctness', Correctness), ('protocol', Protocol), ('environment', Environment))}
    subject = _object(data.get('subject'), 'subject', source, issues)
    values['subject'] = None
    if subject is not None:
        implementation = _object(subject.get('implementation'), 'subject.implementation', source, issues)
        impl = None if implementation is None else Implementation(**{
            key: _component(_TEXT, implementation.get(key), f'subject.implementation.{key}', source, issues)
            for key in ('id', 'source')})
        values['subject'] = Subject(implementation=impl,
            scope=_component(_TEXT, subject.get('scope'), 'subject.scope', source, issues),
            build=_component(_OBJECT, subject.get('build'), 'subject.build', source, issues))
    measurement = _object(data.get('measurement'), 'measurement', source, issues)
    values['measurement'] = None if measurement is None else Measurement(**{
        key: _component(adapter, measurement.get(key), f'measurement.{key}', source, issues)
        for key, adapter in (('value_ms', _DURATION), ('statistic', _STATISTIC), ('sample_count', _COUNT))})
    values['failure'] = None
    if 'failure' in data:
        failure = _object(data['failure'], 'failure', source, issues)
        if failure is not None:
            values['failure'] = Failure(
                stage=_component(_FAILURE_STAGE, failure.get('stage'), 'failure.stage', source, issues),
                message=_component(_TEXT, failure.get('message'), 'failure.message', source, issues))
    record = BenchmarkRecord(**values)
    issues.extend(issue(item.id, item.status, item.reason_code, source, item.value)
                  for item in natural_record_issues(record))
    record = record.model_copy(update={field: tuple(sorted(getattr(record, field), key=lambda item: item.name))
                                      for field in ('inputs', 'outputs') if getattr(record, field) is not None})
    return record, issues


class BenchmarkEvidence(EvidenceFact):
    record: BenchmarkRecord | None = None
    records: Annotated[tuple[BenchmarkRecord, ...], Field(strict=False)] = ()
    sources: Annotated[tuple[BenchmarkSource, ...], Field(strict=False)] = ()
    issues: Annotated[tuple[BenchmarkIssue, ...], Field(strict=False)] = ()

    def correctness(self) -> tuple[bool, list[BenchmarkIssue]]:
        if self.record is None or not self.sources:
            return False, list(self.issues)
        relevant = ('correctness', 'subject.implementation.id')
        issues = [item for item in self.issues if item.id in {'', 'imports', 'contract_version', 'subject', 'subject.implementation'}
                  or any(item.id == prefix or item.id.startswith(prefix + '.') for prefix in relevant)
                  or (item.id.startswith('failure') and (self.record.failure is None or self.record.failure.stage != 'timing'))]
        return not issues, issues

    def as_context(self) -> BenchmarkContext:
        return BenchmarkContext(imports=self.sources, measurement=self.record if not self.issues else None, issues=self.issues)

    def as_measurement(self) -> BenchmarkMeasurement:
        return BenchmarkMeasurement(record=self.record, conflicting_records=self.records if len(self.records) > 1 else (),
                                    sources=tuple(source_ref(source) for source in self.sources))


def read_imports(run_dir: Path, imports: tuple[BenchmarkSource, ...], *,
                 new_snapshot: tuple[str, bytes, object] | None = None) -> BenchmarkEvidence:
    records: dict[str, BenchmarkRecord] = {}
    issues = []
    if not imports:
        issues.append(issue('imports', 'missing', 'benchmark_import_missing'))
    for source in imports:
        path = run_dir / source.artifact
        try:
            path.resolve().relative_to(run_dir.resolve())
            fresh = new_snapshot is not None and new_snapshot[0] == source.artifact
            raw = new_snapshot[1] if fresh else path.read_bytes()
            if digest_bytes(raw) != source.sha256:
                issues.append(issue('', 'conflict', 'source_digest_mismatch', source))
                continue
            data = new_snapshot[2] if fresh else decode_json(raw)
        except (OSError, ValueError) as exc:
            issues.append(issue('', 'invalid', 'source_unreadable', source, str(exc)))
            continue
        record, validation = validate_measurement(data.get('assessment') if isinstance(data, dict) else data, source)
        issues.extend(validation)
        if record is not None:
            records[semantic_key(record)] = record
    unique = tuple(records.values())
    if len(unique) > 1:
        issues.append(BenchmarkIssue(id='measurement', status='conflict', reason_code='conflicting_measurements',
            value=[record.model_dump(mode='json') for record in unique], sources=tuple(source_ref(source) for source in imports)))
    return BenchmarkEvidence(record=unique[0] if len(unique) == 1 else None, records=unique, sources=imports, issues=tuple(issues))


def load_registration(path: Path) -> BenchmarkRegistration:
    data = read_json(path)
    # The cache is a derived display; only registration authorizes raw replay.
    if isinstance(data, dict):
        data = {key: data[key] for key in BenchmarkRegistration.model_fields if key in data}
    return BenchmarkRegistration.model_validate(data)


def load_benchmark(run_dir: Path) -> BenchmarkEvidence:
    path = run_dir / ARTIFACT
    if not path.exists():
        return BenchmarkEvidence(issues=(issue('', 'missing', 'benchmark_context_missing'),))
    try:
        context = load_registration(path)
    except (OSError, ValueError) as exc:
        return BenchmarkEvidence(issues=(issue('', 'invalid', 'benchmark_context_invalid', value=str(exc)),))
    return read_imports(run_dir, context.imports)
