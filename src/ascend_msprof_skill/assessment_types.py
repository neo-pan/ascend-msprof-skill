"""Validated natural-performance assessment outputs and shared state rules."""
from __future__ import annotations

from typing import Annotated, Literal
import json

from pydantic import Field, FiniteFloat, JsonValue, model_validator

from .benchmark_types import (BenchmarkCitation, BenchmarkMeasurement, same_condition,
                              natural_record_issues)
from .evidence_types import EvidenceFact


class PerformanceCheck(EvidenceFact):
    id: str
    status: Literal['missing', 'invalid', 'conflict', 'mismatch', 'match', 'not_applicable']
    reason_code: str
    baseline: JsonValue = None
    candidate: JsonValue = None
    sources: Annotated[tuple[BenchmarkCitation, ...], Field(strict=False)] = ()


def eligibility_status(checks: tuple[PerformanceCheck, ...]) -> str:
    statuses = {check.status for check in checks}
    return 'blocked' if statuses & {'invalid', 'conflict', 'mismatch'} else 'incomplete' if 'missing' in statuses else 'eligible'


def eligibility_reasons(checks: tuple[PerformanceCheck, ...]) -> tuple[str, ...]:
    return tuple(f'{check.id}: {check.reason_code}' for check in checks if check.status not in {'match', 'not_applicable'})


class PerformanceEligibility(EvidenceFact):
    status: Literal['eligible', 'incomplete', 'blocked']
    checks: Annotated[tuple[PerformanceCheck, ...], Field(strict=False)]
    reasons: Annotated[tuple[str, ...], Field(strict=False)]

    @model_validator(mode='after')
    def derived_status(self) -> PerformanceEligibility:
        if self.status != eligibility_status(self.checks) or self.reasons != eligibility_reasons(self.checks):
            raise ValueError('eligibility disagrees with recorded checks')
        return self


class PerformanceObservation(EvidenceFact):
    delta_ms: FiniteFloat
    speedup_pct: FiniteFloat
    direction: Literal['faster', 'slower', 'equal']
    statistic: Literal['mean', 'median']
    sources: Annotated[tuple[BenchmarkCitation, ...], Field(strict=False)]


class PerformanceComparison(EvidenceFact):
    status: Literal['not_applicable', 'not_comparable', 'observed_only']
    observation: PerformanceObservation | None


class PerformanceMeasurements(EvidenceFact):
    baseline: BenchmarkMeasurement | None
    candidate: BenchmarkMeasurement


class PerformanceAssessment(EvidenceFact):
    contract_version: Literal['2.0'] = '2.0'
    mode: Literal['single_run', 'comparison']
    eligibility: PerformanceEligibility
    measurements: PerformanceMeasurements
    comparison: PerformanceComparison
    limitations: Annotated[tuple[str, ...], Field(strict=False)]

    @model_validator(mode='after')
    def consistent_comparison(self) -> PerformanceAssessment:
        paired = self.measurements.baseline is not None
        expected = performance_condition_checks(self.measurements)
        condition_ids = {check.id for check in expected}
        recorded = tuple(check for check in self.eligibility.checks if check.id in condition_ids)
        remaining: dict[str, list[PerformanceCheck]] = {}
        for check in recorded:
            remaining.setdefault(check.id, []).append(check)
        if len(recorded) != len(expected):
            raise ValueError('performance condition checks disagree with measured records')
        # Invalid records can repeat tensor names. Keep every condition so an
        # already-blocked record can still produce its complete diagnostic view.
        for check in expected:
            candidates = remaining.get(check.id, [])
            match = next((i for i, item in enumerate(candidates) if same_condition(item, check)), None)
            if match is None:
                raise ValueError('performance condition checks disagree with measured records')
            candidates.pop(match)
        if self.eligibility.status == 'eligible':
            records = [item.record for item in (self.measurements.baseline, self.measurements.candidate) if item is not None]
            if any(record is None or not record.complete or natural_record_issues(record)
                   for record in records):
                raise ValueError('eligible performance requires complete valid natural records')
            if paired and not same_condition(records[0].comparison_conditions(), records[1].comparison_conditions()):
                raise ValueError('eligible comparison requires matching declared conditions')
        if self.mode != ('comparison' if paired else 'single_run'):
            raise ValueError('performance mode disagrees with measurements')
        status = 'not_applicable' if not paired else 'observed_only' if self.eligibility.status == 'eligible' else 'not_comparable'
        if self.comparison.status != status or (self.comparison.observation is not None) != (status == 'observed_only'):
            raise ValueError('comparison disagrees with eligibility')
        observation = self.comparison.observation
        if observation is not None:
            a, b = self.measurements.baseline.record, self.measurements.candidate.record
            if a is None or b is None or a.measurement is None or b.measurement is None:
                raise ValueError('comparison requires point estimates')
            av, bv = a.measurement.value_ms, b.measurement.value_ms
            if av is None or bv is None:
                raise ValueError('comparison requires valid point estimates')
            delta = bv - av
            if (observation.delta_ms != delta or observation.speedup_pct != (av - bv) / av * 100
                    or observation.direction != ('faster' if delta < 0 else 'slower' if delta > 0 else 'equal')
                    or observation.statistic != b.measurement.statistic or a.measurement.statistic != b.measurement.statistic):
                raise ValueError('performance observation disagrees with measured values')
            sources = tuple(BenchmarkCitation(artifact=source.artifact, sha256=source.sha256,
                                field_ref='assessment.measurement', role=role)
                            for role, measurement in (('baseline', self.measurements.baseline), ('candidate', self.measurements.candidate))
                            for source in measurement.sources)
            if observation.sources != sources:
                raise ValueError('performance observation sources disagree with measured snapshots')
        return self


def performance_condition_checks(measurements: PerformanceMeasurements) -> tuple[PerformanceCheck, ...]:
    """Project only declared record conditions; external issues remain recorded facts."""
    from pydantic import BaseModel
    baseline, candidate = measurements.baseline, measurements.candidate
    if baseline is None or baseline.record is None or candidate.record is None:
        return ()
    checks = []

    def json_value(value):
        if isinstance(value, BaseModel):
            return value.model_dump(mode='json')
        if isinstance(value, tuple):
            return [json_value(item) for item in value]
        return value

    def compare(field, a, b):
        if isinstance(a, BaseModel) and type(a) is type(b):
            for key in type(a).model_fields:
                compare(f'{field}.{key}', getattr(a, key), getattr(b, key))
            return
        if isinstance(a, tuple) and isinstance(b, tuple) and len(a) == len(b):
            for i, (left, right) in enumerate(zip(a, b)):
                selector = f'name={left.name}' if field in {'inputs', 'outputs'} and left.name == right.name else str(i)
                compare(f'{field}[{selector}]', left, right)
            return
        av, bv = json_value(a), json_value(b)
        status = 'missing' if av is None or bv is None else 'match' if same_condition(a, b) else 'mismatch'
        checks.append(PerformanceCheck(id=field, status=status, reason_code=f'condition_{status}', baseline=av, candidate=bv,
            sources=tuple(BenchmarkCitation(artifact=source.artifact, sha256=source.sha256,
                            field_ref=f'assessment.{field}', role=role)
                          for role, measurement in (('baseline', baseline), ('candidate', candidate))
                          for source in measurement.sources)))

    left, right = baseline.record.comparison_conditions(), candidate.record.comparison_conditions()
    for field in left:
        compare(field, left[field], right[field])
    return tuple(checks)


from .benchmark_types import BenchmarkSource, Subject
from .coverage_types import TargetScope
from .evidence_types import SourceRef
from .identity_types import IdentityEvidence, TargetIdentity
from .provenance_types import OutputSegment, ProfileOutputSegments
from .readiness_types import CollectionAction, ReadinessLevel
from .simulator_types import SourceContext
from .summary_types import MeasurementQuality

Role = Literal['baseline', 'candidate']
Strings = Annotated[tuple[str, ...], Field(strict=False)]


class EvidenceCitation(EvidenceFact):
    artifact: str | None = None
    field_ref: str | None = None
    field: str | None = None
    role: str | None = None
    source: str | None = None
    evidence_role: str | None = None
    sha256: str | None = None
    segment: str | None = None
    metric_scope: str | None = None
    target_scope: TargetScope | None = None


class CompatibilitySide(EvidenceFact):
    value: str | OutputSegment | ProfileOutputSegments | None
    source: SourceRef | None
    status: Literal['recorded', 'conflict'] | None = None

    @model_validator(mode='after')
    def conflict_has_no_selected_value(self) -> CompatibilitySide:
        if self.status == 'conflict' and self.value is not None:
            raise ValueError('conflicting evidence cannot select a value')
        return self


def cann_version_component(source: SourceRef | None) -> str | None:
    field = source.field if source else None
    if field in {'toolkit_running_version', 'runtime_running_version', 'compiler_running_version', 'opp_running_version'}:
        return field.removesuffix('_running_version')
    if field == 'version' and source.artifact.endswith('/toolkit_install.info'):
        return 'toolkit'
    return None


def compatibility_check_status(name: str, a: CompatibilitySide, b: CompatibilitySide) -> str:
    if 'conflict' in (a.status, b.status):
        return 'conflict'
    if a.value is None or b.value is None:
        return 'missing'
    if name == 'cann_version':
        a_component, b_component = cann_version_component(a.source), cann_version_component(b.source)
        if a_component is None or b_component is None:
            return 'missing'
        if a_component != b_component:
            return 'component_mismatch'
    return 'match' if a.value == b.value else 'mismatch'


class CompatibilityCheck(EvidenceFact):
    id: str
    title: str
    status: Literal['match', 'missing', 'mismatch', 'conflict', 'component_mismatch']
    a: CompatibilitySide
    b: CompatibilitySide

    @model_validator(mode='after')
    def derived_status(self) -> CompatibilityCheck:
        if self.status != compatibility_check_status(self.id, self.a, self.b):
            raise ValueError('compatibility check disagrees with recorded values and sources')
        return self


def compatibility_status(checks: tuple[CompatibilityCheck, ...]) -> str:
    if not checks:
        return 'not_applicable'
    statuses = {check.status for check in checks}
    if statuses & {'mismatch', 'conflict', 'component_mismatch'}:
        return 'warning'
    return 'incomplete' if 'missing' in statuses else 'compatible'


class Compatibility(EvidenceFact):
    status: Literal['not_applicable', 'warning', 'incomplete', 'compatible']
    checks: Annotated[tuple[CompatibilityCheck, ...], Field(strict=False)]

    @model_validator(mode='after')
    def checked_status(self) -> Compatibility:
        if self.status != compatibility_status(self.checks):
            raise ValueError('compatibility status disagrees with its checks')
        return self


class WorkloadObservation(EvidenceFact):
    value: JsonValue
    source: EvidenceCitation


WORKLOAD_FIELDS = ('id', 'shape', 'dtype', 'case_count')
PROFILER_COMPARISON_CHECKS = ('cann_version', 'hardware_summary')


def workload_values_match(a: object, b: object) -> bool:
    return json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(b, sort_keys=True, allow_nan=False)


def select_workload_value(observations: tuple[WorkloadObservation, ...]) -> tuple[JsonValue, str]:
    values = [item.value for item in observations if item.value not in (None, '', [], {})]
    if not values:
        return None, 'missing'
    if any(not workload_values_match(values[0], value) for value in values[1:]):
        return None, 'conflict'
    return values[0], 'recorded'


def workload_check_status(a: tuple[JsonValue, str], b: tuple[JsonValue, str]) -> str:
    if 'conflict' in (a[1], b[1]):
        return 'conflict'
    if a[0] is None or b[0] is None:
        return 'missing'
    return 'match' if workload_values_match(a[0], b[0]) else 'mismatch'


class WorkloadCheck(EvidenceFact):
    id: str
    status: Literal['match', 'missing', 'mismatch', 'conflict']
    a: JsonValue
    b: JsonValue
    sources: dict[Literal['a', 'b'], Annotated[tuple[WorkloadObservation, ...], Field(strict=False)]]

    @model_validator(mode='after')
    def selected_facts(self) -> WorkloadCheck:
        if set(self.sources) != {'a', 'b'}:
            raise ValueError('workload check requires observations for both sides')
        a, b = (select_workload_value(self.sources[side]) for side in ('a', 'b'))
        if (not workload_values_match(self.a, a[0]) or not workload_values_match(self.b, b[0])
                or self.status != workload_check_status(a, b)):
            raise ValueError('workload check disagrees with selected observations')
        return self


class HeadlineIssue(EvidenceFact):
    reason: str
    source: SourceRef


class ComparisonHeadline(EvidenceFact):
    present: bool = False
    name: str | None = None
    value: FiniteFloat | None = None
    field: str | None = None
    field_kind: str | None = None
    artifact: str | None = None
    segment: str | None = None
    metric_scope: str | None = None
    field_ref: str | None = None
    unit: str | None = None
    statistic: str | None = None
    aggregation: str | None = None
    scope: dict[str, str] = Field(default_factory=dict)
    schema_issues: Annotated[tuple[HeadlineIssue, ...], Field(strict=False)] = ()
    target_identity: TargetIdentity | IdentityEvidence | None = None
    block_scope: dict[str, str] | None = None


def headline_comparison_reasons(a_item: ComparisonHeadline, b_item: ComparisonHeadline) -> list[str]:
    reasons = list(dict.fromkeys(issue.reason for item in (a_item, b_item) for issue in item.schema_issues))
    for key in ("field", "field_kind", "name", "segment", "metric_scope", "unit", "statistic", "aggregation"):
        a_value, b_value = getattr(a_item, key), getattr(b_item, key)
        if a_value in (None, "") or b_value in (None, ""):
            reasons.append(f"{key} missing")
        elif a_value != b_value:
            reasons.append(f"{key} mismatch")
    comparable_scopes = [{key: value for key, value in item.scope.items() if key.lower() != "pid"}
                         for item in (a_item, b_item)]
    if comparable_scopes[0] != comparable_scopes[1]:
        reasons.append("scope mismatch")
    a_scope, b_scope = a_item.block_scope, b_item.block_scope
    if any(scope is None or any(value in (None, "") for value in scope.values()) for scope in (a_scope, b_scope)):
        reasons.append("block_scope missing")
    elif a_scope != b_scope:
        reasons.append("block_scope mismatch")
    identities = (a_item.target_identity, b_item.target_identity)
    if any(identity is None or identity.status != "match" for identity in identities):
        reasons.append("target unverified")
    targets = [identity.expected.names if identity is not None and identity.expected is not None else () for identity in identities]
    if any(len(names) != 1 for names in targets):
        reasons.append("target ambiguous")
    elif targets[0] != targets[1]:
        reasons.append("target mismatch")
    if a_item.value is None or b_item.value is None:
        reasons.append("finite numeric value missing")
    return reasons


class HeadlineComparison(EvidenceFact):
    group: str
    status: Literal['observed', 'unassessed', 'missing', 'not_comparable', 'same', 'changed']
    a: ComparisonHeadline | None = None
    b: ComparisonHeadline | None = None
    candidate: ComparisonHeadline | None = None
    comparison_reasons: Strings = ()
    checks: Annotated[tuple[CompatibilityCheck, ...], Field(strict=False)] = ()
    delta: FiniteFloat | None = None
    delta_pct: FiniteFloat | None = None
    numeric: bool = False

    @model_validator(mode='after')
    def numerical_observation(self) -> HeadlineComparison:
        if (self.status in {'same', 'changed'}) != self.numeric:
            raise ValueError('same/changed status requires a numeric comparison')
        if self.status in {'observed', 'unassessed'}:
            if (self.a is not None or self.b is not None or self.checks
                    or self.status == 'observed' and self.comparison_reasons):
                raise ValueError('single-run observation cannot contain paired comparison state')
            if self.status == 'unassessed':
                if (self.candidate is None or not self.candidate.present or self.candidate.value is None
                        or not self.comparison_reasons
                        or self.comparison_reasons != tuple(headline_comparison_reasons(self.candidate, self.candidate))):
                    raise ValueError('unassessed observation requires a located value and its context gaps')
        else:
            if self.candidate is not None or self.a is None or self.b is None:
                raise ValueError('comparison requires paired headline records')
            present = self.a.present and self.b.present
            if (self.status == 'missing') != (not present):
                raise ValueError('missing status disagrees with headline presence')
            if self.status in {'missing', 'not_comparable'} and not self.comparison_reasons:
                raise ValueError('unavailable comparison requires recorded reasons')
        if self.numeric:
            if (self.a is None or self.b is None or not self.a.present or not self.b.present
                    or headline_comparison_reasons(self.a, self.b) or self.comparison_reasons
                    or segment_check_blockers(self.checks, self.a.segment)):
                raise ValueError('numeric comparison requires admitted paired values')
            delta = self.b.value - self.a.value
            percentage = None if self.a.value == 0 else delta / abs(self.a.value) * 100
            if self.delta != delta or self.delta_pct != percentage or self.status != ('same' if delta == 0 else 'changed'):
                raise ValueError('headline deltas disagree with paired values')
        elif self.delta is not None or self.delta_pct is not None:
            raise ValueError('unavailable numeric comparison cannot retain deltas')
        if self.status == 'observed' and (self.candidate is None or not self.candidate.present
                or headline_comparison_reasons(self.candidate, self.candidate)):
            raise ValueError('single-run observation requires an admitted candidate value')
        return self


class EvidenceQuestion(EvidenceFact):
    id: str
    evidence_family: str
    question: str
    available_evidence: Annotated[tuple[EvidenceCitation, ...], Field(strict=False)]
    missing_evidence: Annotated[tuple[EvidenceCitation, ...], Field(strict=False)]
    blocked_by: Strings
    status: Literal['blocked', 'missing', 'available']

    @model_validator(mode='after')
    def question_status(self) -> EvidenceQuestion:
        expected = 'blocked' if self.blocked_by else 'missing' if self.missing_evidence else 'available'
        if self.status != expected:
            raise ValueError('question status disagrees with its evidence and blockers')
        return self


class MechanismFinding(EvidenceFact):
    kind: Literal['metric_observation'] = 'metric_observation'
    evidence_level: Literal['descriptive'] = 'descriptive'
    group: str
    delta: FiniteFloat | None = None
    delta_pct: FiniteFloat | None = None
    evidence: Annotated[tuple[EvidenceCitation, ...], Field(strict=False)]


class AssociationCheck(EvidenceFact):
    id: str
    status: Literal['match', 'missing', 'mismatch', 'conflict']
    benchmark: JsonValue
    profiler: JsonValue
    sources: Annotated[tuple[EvidenceCitation | WorkloadObservation, ...], Field(strict=False)]

    @model_validator(mode='after')
    def selected_facts(self) -> AssociationCheck:
        if self.status != association_check_status(self.id, self.benchmark, self.profiler, self.sources):
            raise ValueError('association check disagrees with recorded facts')
        return self


def association_check_status(name: str, benchmark: JsonValue, profiler: JsonValue,
                             sources: tuple[EvidenceCitation | WorkloadObservation, ...]) -> str:
    selected = (profiler, 'recorded' if profiler is not None else 'missing')
    if name.startswith('benchmark_workload.'):
        selected = select_workload_value(tuple(item for item in sources if isinstance(item, WorkloadObservation)))
        if not workload_values_match(profiler, selected[0]):
            raise ValueError('association workload disagrees with selected observations')
    return workload_check_status((benchmark, 'recorded' if benchmark is not None else 'missing'), selected)


def benchmark_association_status(checks: tuple[AssociationCheck, ...]) -> str:
    subject_linked = any(check.id == 'benchmark_subject' and check.status == 'match' for check in checks)
    workload = tuple(check for check in checks if check.id.startswith('benchmark_workload'))
    workload_failed = any(check.status != 'match' for check in workload)
    required = tuple(f'benchmark_workload.{field}' for field in WORKLOAD_FIELDS)
    if subject_linked and not workload_failed and not required_check_blockers(workload, required):
        return 'linked'
    return 'blocked' if workload_failed or any(check.status == 'mismatch' for check in checks) else 'missing'


class BenchmarkAssociation(EvidenceFact):
    role: Role
    status: Literal['linked', 'blocked', 'missing']
    checks: Annotated[tuple[AssociationCheck, ...], Field(strict=False)]
    limitation: str | None

    @model_validator(mode='after')
    def association_status(self) -> BenchmarkAssociation:
        if self.status != benchmark_association_status(self.checks):
            raise ValueError('benchmark association disagrees with subject and workload checks')
        return self


class ReadinessView(EvidenceFact):
    present: bool
    level: ReadinessLevel | None
    available_evidence_families: Strings
    missing_evidence_families: Strings
    material_evidence_families: Strings
    recommended_followups: Annotated[tuple[CollectionAction, ...], Field(strict=False)]


class RawIndexView(EvidenceFact):
    present: bool
    schema_version: str | None = None
    artifact_count: int = Field(default=0, ge=0)
    group_counts: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    status_counts: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    segment_counts: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    warnings: Strings = ()


class MechanismEvidence(EvidenceFact):
    summary_warnings: Strings
    next_collection_actions: Annotated[tuple[CollectionAction, ...], Field(strict=False)]
    pending_collection_actions: Annotated[tuple[CollectionAction, ...], Field(strict=False)]
    evidence_readiness: ReadinessView
    measurement_quality: MeasurementQuality | None
    raw_artifact_index: RawIndexView
    parsed_artifact_count: int = Field(ge=0)
    evidence_present: bool
    inputs_present: bool


class RoleAction(CollectionAction):
    role: Role


class MechanismAssessment(EvidenceFact):
    contract_version: Literal['3.1'] = '3.1'
    mode: Literal['single_run', 'comparison']
    coverage: Literal['missing', 'available', 'blocked', 'partial']
    compatibility: Compatibility
    workload_checks: Annotated[tuple[WorkloadCheck, ...], Field(strict=False)]
    headlines: Annotated[tuple[HeadlineComparison, ...], Field(strict=False)]
    questions: Annotated[tuple[EvidenceQuestion, ...], Field(strict=False)]
    findings: Annotated[tuple[MechanismFinding, ...], Field(strict=False)]
    benchmark_association: Annotated[tuple[BenchmarkAssociation, ...], Field(strict=False)]
    evidence: dict[Role, MechanismEvidence]
    pending_actions: Annotated[tuple[RoleAction, ...], Field(strict=False)]
    limitations: Strings

    @model_validator(mode='after')
    def scoped_composition(self) -> MechanismAssessment:
        roles = {'candidate', 'baseline'} if self.mode == 'comparison' else {'candidate'}
        if (set(self.evidence) != roles or {item.role for item in self.benchmark_association} != roles
                or len(self.benchmark_association) != len(roles)
                or any(item.role not in roles for item in self.pending_actions)):
            raise ValueError('mechanism roles disagree with assessment mode')
        if any(row.numeric for row in self.headlines) and mechanism_common_blockers(self.workload_checks, self.compatibility, require_complete=True):
            raise ValueError('numeric mechanism comparison conflicts with workload or profiler checks')
        if self.coverage != mechanism_coverage(self.evidence, self.questions, self.workload_checks, self.compatibility, self.findings):
            raise ValueError('mechanism coverage disagrees with evidence availability')
        if self.findings != mechanism_findings(self.headlines):
            raise ValueError('mechanism findings disagree with headline observations')
        return self
        if any((row.status in {'observed', 'unassessed'}) != (self.mode == 'single_run') for row in self.headlines):
            raise ValueError('headline form disagrees with assessment mode')


def required_check_blockers(checks, required: tuple[str, ...]) -> list[str]:
    ids = [check.id for check in checks]
    return [f'{key} {"missing" if ids.count(key) == 0 else "duplicate"}' for key in required if ids.count(key) != 1]


def segment_check_blockers(checks: tuple[CompatibilityCheck, ...], segment: str | None) -> list[str]:
    required = (f'segment.{segment}.output', f'segment.{segment}.command')
    return [*required_check_blockers(checks, required),
            *(f'{check.id} {check.status}' for check in checks if check.status != 'match')]


def mechanism_common_blockers(workload_checks: tuple[WorkloadCheck, ...], compatibility: Compatibility,
                              *, require_complete: bool = False) -> list[str]:
    return ([f'{check.id} {check.status}' for check in workload_checks if check.status != 'match']
            + [f'profiler.{check.id} {check.status}' for check in compatibility.checks
               if check.id in PROFILER_COMPARISON_CHECKS and check.status != 'match']
            + (required_check_blockers(workload_checks, tuple(f'workload.{field}' for field in WORKLOAD_FIELDS))
               + [f'profiler.{reason}' for reason in required_check_blockers(compatibility.checks, PROFILER_COMPARISON_CHECKS)]
               if require_complete else []))


def mechanism_coverage(evidence: dict[str, MechanismEvidence], questions: tuple[EvidenceQuestion, ...],
                       workload_checks: tuple[WorkloadCheck, ...], compatibility: Compatibility,
                       findings: tuple[MechanismFinding, ...]) -> str:
    if not any(item.inputs_present for item in evidence.values()):
        return 'missing'
    if questions and all(question.status == 'available' for question in questions):
        return 'available'
    return 'blocked' if mechanism_common_blockers(workload_checks, compatibility) and not findings else 'partial'


def mechanism_findings(headlines: tuple[HeadlineComparison, ...]) -> tuple[MechanismFinding, ...]:
    findings = []
    for row in headlines:
        if row.numeric:
            findings.append(MechanismFinding(group=row.group, delta=row.delta, delta_pct=row.delta_pct,
                evidence=tuple(EvidenceCitation(artifact=item.artifact, field_ref=item.field_ref or item.field, role=role)
                               for role, item in (('baseline', row.a), ('candidate', row.b)))))
        elif row.status == 'observed':
            findings.append(MechanismFinding(group=row.group,
                evidence=(EvidenceCitation(artifact=row.candidate.artifact, field_ref=row.candidate.field_ref or row.candidate.field),)))
    return tuple(findings)


class RunAssessment(EvidenceFact):
    performance_assessment: PerformanceAssessment
    mechanism_assessment: MechanismAssessment

    @model_validator(mode='after')
    def shared_mode(self) -> RunAssessment:
        if self.performance_assessment.mode != self.mechanism_assessment.mode:
            raise ValueError('assessment blocks require the same run mode')
        return self


class RunDescriptor(EvidenceFact):
    role: Role
    label: str
    run_dir: str
    artifacts: dict[str, str | None]


class SourceArtifact(EvidenceFact):
    artifact: str
    sha256: str


class RunSources(EvidenceFact):
    summary: SourceArtifact | None = None
    raw_artifact_index: SourceArtifact | None = None
    provenance: SourceArtifact | None = None
    tilelang_context: SourceArtifact | None = None
    profile_context: SourceArtifact | None = None
    simulator_hotspots: SourceArtifact | None = None
    benchmark: Annotated[tuple[BenchmarkSource, ...], Field(strict=False)]


class PayloadView(EvidenceFact):
    present: bool
    artifact: str | None = None
    sha256: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)


class Lineage(EvidenceFact):
    subject: Subject | None
    payload: PayloadView
    jit_config: JsonValue


class AssessmentMetadata(EvidenceFact):
    runs: dict[Role, RunDescriptor]
    source_artifacts: dict[Role, RunSources]
    lineage: dict[Role, Lineage]
    warnings: Strings


class InspectionTarget(EvidenceFact):
    source: Literal['simulator_hotspots']
    kind: Literal['source_line', 'instruction', 'pipeline_event']
    id: str
    rank: int = Field(ge=1)
    artifact: str
    field: str | None
    field_ref: str | None
    value: FiniteFloat | None
    source_file: str | None
    line: int | None
    instruction: str | None
    source_context: SourceContext | None = None


class AssessmentResult(AssessmentMetadata, RunAssessment):
    @model_validator(mode='after')
    def metadata_roles(self) -> AssessmentResult:
        roles = set(self.mechanism_assessment.evidence)
        if any(set(group) != roles for group in (self.runs, self.source_artifacts, self.lineage)):
            raise ValueError('output metadata roles disagree with assessed runs')
        if any(role != descriptor.role for role, descriptor in self.runs.items()):
            raise ValueError('run descriptor role disagrees with its key')
        return self


class CandidateSummary(AssessmentResult):
    candidate_summary_schema_version: Literal['4.1'] = '4.1'
    inspection_targets: Annotated[tuple[InspectionTarget, ...], Field(strict=False)]


class ComparisonSummary(AssessmentResult):
    comparison_schema_version: Literal['4.1'] = '4.1'
