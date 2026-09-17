"""Read-only facts derived from an analyzed Ascend profiling run."""
from __future__ import annotations

from .caller_context import CallerContext, JitDebug, CorrectnessMaximum, load_caller_context, normalize_caller_context
from .simulator_types import SimulatorModel
from .provenance_types import Provenance, Sourced, CannVersion, OutputSegment, ProfileOutputSegments, load_provenance
from ._evidence_signals import build_simulator_dimension, simulator_row_signal
from ._evidence_relations import build_evidence_relations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from ._profiler_segments import command_profile_output_segment
from .collection_receipts import CollectionReceipts, load_collection_receipts
from .benchmark_evidence import BenchmarkEvidence, load_benchmark, digest_bytes, source_ref
from .benchmark_types import BenchmarkRecord
from .assessment_types import (ComparisonHeadline, HeadlineIssue, WorkloadCheck, AssociationCheck,
    InspectionTarget, RawIndexView, cann_version_component, WORKLOAD_FIELDS, WorkloadObservation,
    select_workload_value, workload_check_status, workload_values_match, association_check_status,
    benchmark_association_values)
from .ascend_profile_utils import normalized_key, to_float
from .readiness_types import CollectionAction, EvidenceReadiness
from .analysis_types import AnalysisDimension, EvidenceRelation
from .metric_scope_policy import APP_TIMING_ARTIFACTS, command_metric_scope, is_msprof_op_command, metric_scope_policy, warning_group


HEADLINE_GROUPS: tuple[tuple[str, str], ...] = (
    ("op_summary", "Operator duration observations"),
    ("op_statistic", "Operator type statistics"),
    ("task_time", "Task duration observations"),
    ("api_statistic", "Host/runtime API statistics"),
    ("op_basic_info", "Operator metadata"),
    ("pipe_utilization", "Pipe observations"),
    ("arithmetic_utilization", "Arithmetic utilization signal"),
    ("l2_cache", "L2 cache hit-rate signal"),
    ("memory", "Memory observations"),
    ("resource_conflict", "Conflict observations"),
)

TARGET_HEADLINE_ORDER: tuple[str, ...] = (
    "op_basic_info",
    "op_summary",
    "op_statistic",
    "task_time",
)
_REPORT_CORRELATION_GROUPS: tuple[tuple[str, str], ...] = (
    ("App top operator", "op_summary"),
    ("App top task", "task_time"),
    ("Op metadata", "op_basic_info"),
    ("Op pipe signal", "pipe_utilization"),
)
FEEDBACK_WORKLOAD_COMPARABILITY_FIELDS = WORKLOAD_FIELDS
MATERIAL_EVIDENCE_FAMILIES = {
    "app_timing",
    "operator_metadata",
    "pipe_utilization",
    "arithmetic_utilization",
    "memory_cache",
    "resource_conflict",
    "simulator_source_pipeline",
}
PROFILE_CONTEXT_ARTIFACT = "analysis/profile_context.json"
TILELANG_CONTEXT_ARTIFACT = "analysis/tilelang_context.json"
REQUIRED_STEM_FAMILY = {
    "PipeUtilization": "pipe_utilization",
    "ArithmeticUtilization": "arithmetic_utilization",
    "Memory": "memory",
    "MemoryL0": "memory",
    "MemoryUB": "memory",
    "L2Cache": "l2_cache",
    "ResourceConflictRatio": "resource_conflict",
}


from .operator_evidence import OperatorEvidence, OperatorArtifact, select_operator_primary, operator_metric_kind
from .evidence_types import SourceRef
from .summary_types import (Summary, RawArtifactIndex, MeasurementQuality, load_summary,
                            validate_summary_index, validate_receipt_admission, validate_receipt_dimensions)
from .coverage_types import ProfileCoverage
from .identity_types import TargetIdentity
from .application_timing import TimingEvidence, observation_field_ref, partition_declared_subject, timing_groups
from .artifact_reader import read_json as read_evidence_json


class RunEvidenceError(RuntimeError):
    """Raised when required analyzed evidence is absent or unreadable."""


@dataclass(frozen=True)
class MetricScopeFact:
    value: str
    artifact: str
    field_ref: str


@dataclass(frozen=True)
class HeadlineFact:
    group: str
    label: str | None
    name: Any
    value: Any
    field: Any
    field_kind: Any
    artifact: str
    segment: Any
    metric_scope: Any
    field_ref: str
    raw_value_field_ref: str | None
    source: SourceRef | None = None

    @property
    def signal(self) -> str:
        if self.field:
            return f"{self.name or 'n/a'} / {self.field}"
        return str(self.name or "n/a")

    @property
    def correlation_field_ref(self) -> str:
        if self.group in {*APP_TIMING_ARTIFACTS, "op_basic_info", "pipe_utilization", "arithmetic_utilization", "memory", "l2_cache", "resource_conflict"}:
            return self.field_ref
        refs = [self.field_ref]
        if self.raw_value_field_ref:
            refs = [f"headlines.{self.group}.value", self.raw_value_field_ref]
            if self.field:
                refs.append(f"headlines.{self.group}.field={self.field}")
            if self.field_kind:
                refs.append(f"headlines.{self.group}.field_kind={self.field_kind}")
        return "; ".join(refs)


@dataclass(frozen=True)
class LaunchMetadataFact:
    artifact: str
    fields: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class RawArtifactFact:
    index: int | None
    artifact: str | None
    group: str | None
    parser: str | None
    segment: str | None
    metric_scope: str | None
    status: str | None
    row_count: int | None
    columns: tuple[str, ...]
    warnings: tuple[str, ...]
    canonical_stem: str | None = None
    launch_key: str | None = None
    target_name: str | None = None
    normalized_target_name: str | None = None


@dataclass(frozen=True)
class RawArtifactSummary:
    present: bool
    schema_version: str | None
    artifact_count: int
    parsed_count: int
    status_counts: dict[str, int]
    group_counts: dict[str, int]
    segment_counts: dict[str, int]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class SummarySignalFact:
    group: str | None
    artifact: Any
    field: Any
    field_ref: Any
    segment: Any = None
    metric_scope: Any = None


@dataclass(frozen=True)
class FeedbackDesignEvidenceFact:
    source: str
    artifact: Any
    role: str
    field: Any = None
    field_ref: Any = None
    segment: Any = None
    metric_scope: Any = None
    target_scope: Any = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "artifact": self.artifact,
            "field": self.field,
            "field_ref": self.field_ref,
            "role": self.role,
            "segment": self.segment,
            "metric_scope": self.metric_scope,
            "target_scope": self.target_scope,
        }


@dataclass(frozen=True)
class FeedbackDesignQuestionFact:
    question_id: str
    evidence_family: str
    question: str
    available_evidence: tuple[FeedbackDesignEvidenceFact, ...]
    missing_evidence: tuple[FeedbackDesignEvidenceFact, ...]
    blocked_by: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, Any]:
        return {
            "id": self.question_id,
            "evidence_family": self.evidence_family,
            "question": self.question,
            "available_evidence": [item.as_payload() for item in self.available_evidence],
            "missing_evidence": [item.as_payload() for item in self.missing_evidence],
            "blocked_by": list(self.blocked_by),
        }


@dataclass(frozen=True)
class FeedbackEvidenceFacts:
    evidence: "RunEvidence"

    @property
    def summary_present(self) -> bool:
        return self.evidence.summary_present()

    @property
    def raw_artifact_index_present(self) -> bool:
        return self.evidence.raw_artifact_index() is not None

    @property
    def provenance_present(self) -> bool:
        return self.evidence.provenance() is not None

    @property
    def tilelang_context_present(self) -> bool:
        return self.evidence.tilelang_context() is not None

    @property
    def candidate_context_present(self) -> bool:
        return bool(self.evidence.candidate_context().context_sources)

    @property
    def simulator_present(self) -> bool:
        model = self.evidence.simulator_hotspots()
        return model is not None and bool(model.inputs)


    def readiness_level(self) -> str | None:
        return self.evidence.readiness_level()

    def readiness_at_least(self, minimum: str, order: dict[str, int]) -> bool:
        level = self.readiness_level()
        rank = order.get(level) if isinstance(level, str) else None
        return rank is not None and rank >= order[minimum]

    def material_evidence_families(self) -> list[str]:
        return self.evidence.material_evidence_families()

    def combined_pending_collection_actions(self) -> tuple[CollectionAction, ...]:
        return self.evidence.combined_pending_collection_actions()

    def parsed_artifact_count(self) -> int:
        return self.evidence.parsed_raw_artifact_counts()[0]

    def raw_inventory_present(self) -> bool:
        return self.parsed_artifact_count() > 0

    def profiler_evidence_present(self) -> bool:
        return self.summary_present and self.raw_inventory_present()


    def raw_artifacts_by_group(self, groups: set[str]) -> list[RawArtifactFact]:
        return self.evidence.parsed_raw_artifacts_by_group(groups)

    def parsed_required_artifacts(
        self,
        groups: set[str],
        required_artifacts: list[str],
    ) -> tuple[list[RawArtifactFact], list[str], set[str]]:
        return self.evidence.parsed_required_artifacts(groups, required_artifacts)

    def _parsed_covered_artifacts(
        self,
        groups: set[str],
        required_artifacts: list[str],
    ) -> list[RawArtifactFact]:
        return self.evidence._parsed_covered_artifacts(groups, required_artifacts)

    def _parsed_scoped_artifacts(
        self,
        groups: set[str],
        required_artifacts: list[str],
    ) -> list[RawArtifactFact]:
        return self.evidence._parsed_scoped_artifacts(groups, required_artifacts)

    def raw_group_present(self, groups: set[str]) -> bool:
        return self.evidence.raw_group_present(groups)

    def summary_signal_records(
        self,
        groups: set[str],
        *,
        limit: int = 3,
        allowed_artifact_keys: set[str] | None = None,
    ) -> list[SummarySignalFact]:
        return self.evidence.summary_signal_records(groups, limit=limit, allowed_artifact_keys=allowed_artifact_keys)

    def metric_scope_value(self) -> Any:
        scope = self.evidence.metric_scope()
        return scope.value if scope is not None else None

    def workload_value(self, field: str) -> Any:
        return self.evidence.candidate_context().workload.get(field)

    def workload_present(self) -> bool:
        return bool(self.evidence.candidate_context().workload)

    def compiled_value(self) -> bool | None:
        return self.evidence.candidate_context().correctness.compiled

    def correctness_passed(self) -> bool | None:
        return self.evidence.candidate_context().correctness.passed

    def benchmark_error(self) -> Any:
        error = self.evidence.candidate_context().correctness.error
        if error in (None, "", [], {}):
            return None
        return error

    def runtime_mean_ms(self) -> float | None:
        return self.evidence.candidate_context().runtime.mean_ms

    def runtime_value_ms(self) -> float | None:
        return self.evidence.candidate_context().runtime.value_ms

    def runtime_statistic(self) -> str | None:
        return self.evidence.candidate_context().runtime.statistic

    def runtime_authority(self) -> Any:
        return self.evidence.candidate_context().runtime.authority

    def runtime_latency_source(self) -> Any:
        return self.evidence.candidate_context().runtime.latency_source

    def runtime_evidence_field_ref(self) -> str | None:
        source = self.evidence.candidate_context().context_sources.get("runtime.value_ms")
        return source.field_ref if source is not None else None

    def payload_sha256(self) -> Any:
        return self.evidence.candidate_context().payload.sha256

    def jit_config(self) -> Any:
        return self.evidence.candidate_context().jit.config

    def jit_debug_found(self) -> bool:
        debug = self.evidence.candidate_context().jit.debug
        return debug is not None and debug.found is True

    def collection_action_ids(self) -> list[str]:
        return [
            item.id for item in self.combined_pending_collection_actions()
            if item.necessity == "blocking"
        ]

    def family_question(
        self,
        question_id: str,
        evidence_family: str,
        question: str,
        groups: set[str],
        *,
        source: str,
        required_artifacts: list[str],
    ) -> FeedbackDesignQuestionFact:
        present_artifacts, missing_artifacts, allowed_artifact_keys = self.parsed_required_artifacts(groups, required_artifacts)
        missing_stems = {Path(artifact).stem for artifact in missing_artifacts}
        parsed_scoped_artifacts = [
            fact
            for fact in self._parsed_scoped_artifacts(groups, missing_artifacts)
            if (fact.canonical_stem or _canonical_operator_stem(fact.artifact)) in missing_stems
        ]
        scoped_artifacts = [
            fact
            for fact in self._parsed_covered_artifacts(groups, missing_artifacts)
            if (fact.canonical_stem or _canonical_operator_stem(fact.artifact)) in missing_stems
        ]
        scoped_stems = {
            fact.canonical_stem or _canonical_operator_stem(fact.artifact)
            for fact in scoped_artifacts
        }
        parsed_scoped_stems = {
            fact.canonical_stem or _canonical_operator_stem(fact.artifact)
            for fact in parsed_scoped_artifacts
        }
        covered_scope_keys = {
            (fact.segment, fact.canonical_stem or _canonical_operator_stem(fact.artifact))
            for fact in scoped_artifacts
        }
        incomplete_scoped_artifacts = [
            fact
            for fact in parsed_scoped_artifacts
            if (fact.segment, fact.canonical_stem or _canonical_operator_stem(fact.artifact))
            not in covered_scope_keys
        ]
        available = [
            *_summary_signal_feedback_evidence(
                self,
                groups,
                source=source,
                role=f"{evidence_family} summary signal",
                allowed_artifact_keys=allowed_artifact_keys,
            ),
            *_raw_artifact_feedback_evidence(
                present_artifacts,
                facts=self,
                source=source,
                role=f"{evidence_family} raw artifact",
            ),
            *_raw_artifact_feedback_evidence(
                scoped_artifacts,
                facts=self,
                source=source,
                role=f"{evidence_family} scope-local raw artifact",
            ),
        ]
        missing = _raw_artifact_feedback_evidence(
            incomplete_scoped_artifacts,
            facts=self,
            source=source,
            role="scope-local artifact is parsed but its metric-family coverage is incomplete",
        )
        blocked = []
        if missing_artifacts:
            complete_scope = self.evidence._complete_program_target_scope()
            blocked.append(
                f"missing complete-program {evidence_family} profiler coverage"
                if complete_scope is not None and parsed_scoped_artifacts
                else f"missing {evidence_family} profiler evidence"
            )
            for artifact in missing_artifacts:
                stem = Path(artifact).stem
                if stem in parsed_scoped_stems and stem not in scoped_stems:
                    continue
                scope_gap = complete_scope is not None and stem in scoped_stems
                missing.append(
                    _missing_feedback_evidence(
                        source=source,
                        artifact=artifact,
                        role=(
                            f"complete-program {artifact} coverage is missing"
                            if scope_gap
                            else f"{evidence_family} artifact is missing"
                        ),
                        target_scope=complete_scope if scope_gap else None,
                    )
                )
        return _feedback_question(
            question_id,
            evidence_family,
            question,
            available,
            missing,
            blocked,
        )

    def opbasic_workload_question(self, *, source: str) -> FeedbackDesignQuestionFact:
        available = [
            *_summary_signal_feedback_evidence(
                self,
                {"op_basic_info", "task_time"},
                source=source,
                role="work distribution summary signal",
            ),
            *_raw_group_feedback_evidence(self, {"op_basic_info"}, source=source, role="work distribution raw artifact"),
        ]
        missing = []
        blocked = []
        if not self.raw_group_present({"op_basic_info"}):
            blocked.append("missing opbasic_workload profiler evidence")
            missing.append(
                _missing_feedback_evidence(source=source, artifact="OpBasicInfo.csv", role="opbasic_workload artifact is missing")
            )
        if self.workload_present():
            for field in FEEDBACK_WORKLOAD_COMPARABILITY_FIELDS:
                if self.workload_value(field) is None:
                    blocked.append("missing workload context")
                    missing.append(
                        _missing_feedback_evidence(
                            source=source,
                            artifact=TILELANG_CONTEXT_ARTIFACT,
                            field=field,
                            field_ref=f"benchmark.workload.{field}",
                            role="workload context field is missing",
                        )
                    )
                else:
                    available.append(self.evidence.context_feedback_evidence(source, f"workload.{field}", "workload context"))
        else:
            blocked.append("missing workload context")
            missing.append(
                _missing_feedback_evidence(
                    source=source,
                    artifact=TILELANG_CONTEXT_ARTIFACT,
                    field="workload",
                    field_ref="benchmark.workload",
                    role="workload context is missing",
                )
            )
        return _feedback_question(
            "opbasic_workload",
            "opbasic_workload",
            "Which operator launch metadata and workload context are recorded?",
            available,
            missing,
            blocked,
        )

    def generated_context_records(
        self,
        *,
        source: str,
    ) -> tuple[list[FeedbackDesignEvidenceFact], list[FeedbackDesignEvidenceFact], list[str]]:
        available = []
        missing = []
        blocked = []
        if self.jit_debug_found():
            available.append(
                FeedbackDesignEvidenceFact(
                    source=source,
                    artifact=TILELANG_CONTEXT_ARTIFACT,
                    field="jit_debug",
                    field_ref="jit_debug",
                    role="generated TileLang source context",
                )
            )
        else:
            blocked.append("missing generated context")
            missing.append(
                _missing_feedback_evidence(
                    source=source,
                    artifact=TILELANG_CONTEXT_ARTIFACT,
                    field="jit_debug",
                    field_ref="jit_debug",
                    role="generated TileLang source context is missing",
                )
            )
        if self.simulator_present:
            available.append(
                FeedbackDesignEvidenceFact(
                    source=source,
                    artifact="analysis/simulator_hotspots.json",
                    field="simulator_hotspot_model_schema_version",
                    field_ref="simulator_hotspot_model_schema_version",
                    role="optional source inspection context",
                )
            )
        if self.raw_inventory_present():
            available.append(
                FeedbackDesignEvidenceFact(
                    source=source,
                    artifact="analysis/raw_artifact_index.json",
                    field="artifacts",
                    field_ref="artifacts[status=parsed]",
                    role="on-device evidence required before source inspection",
                )
            )
        else:
            blocked.append("missing on-device profiler evidence")
            missing.append(
                _missing_feedback_evidence(
                    source=source,
                    artifact="analysis/raw_artifact_index.json",
                    field="artifacts",
                    field_ref="artifacts[status=parsed]",
                    role="on-device evidence is required before source inspection",
                )
            )
        return available, missing, blocked

    def generated_context_question(self, *, source: str) -> FeedbackDesignQuestionFact:
        available, missing, blocked = self.generated_context_records(source=source)
        return _feedback_question(
            "generated_context",
            "generated_context",
            "Which generated source and simulator context can be associated with the on-device evidence?",
            available,
            missing,
            blocked,
        )


@dataclass(frozen=True)
class CandidatePayloadFact:
    present: bool
    artifact: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None


@dataclass(frozen=True)
class CandidateJitFact:
    config: JsonValue
    debug: JitDebug | None


@dataclass(frozen=True)
class CandidateCorrectnessFact:
    compiled: bool | None
    passed: bool | None
    error: JsonValue
    maxima: tuple[CorrectnessMaximum, ...]
    source: str | None


@dataclass(frozen=True)
class CandidateRuntimeFact:
    value_ms: float | None
    statistic: str | None
    mean_ms: float | None
    samples_ms: tuple[float, ...]
    authority: str | None
    latency_source: str | None
    runtime: JsonValue
    runtime_stats: JsonValue
    ref_runtime: JsonValue
    source: str | None


@dataclass(frozen=True)
class CandidateContextFacts:
    workload: dict[str, Any]
    workload_evidence: dict[str, list[dict[str, Any]]]
    payload: CandidatePayloadFact
    jit: CandidateJitFact
    correctness: CandidateCorrectnessFact
    runtime: CandidateRuntimeFact
    context_sources: dict[str, "CandidateContextSourceFact"]


@dataclass(frozen=True)
class CandidateContextSourceFact:
    artifact: str
    field_ref: str
    evidence_role: str

    def as_summary(self) -> dict[str, str]:
        return {
            "artifact": self.artifact,
            "field_ref": self.field_ref,
            "evidence_role": self.evidence_role,
        }


@dataclass(frozen=True)
class CompatibilityValueFact:
    value: str | OutputSegment | ProfileOutputSegments | None
    source: SourceRef | None
    status: str | None = None


@dataclass(frozen=True)
class CompatibilityFacts:
    cann_version: CompatibilityValueFact
    hardware_summary: CompatibilityValueFact
    profile_command: CompatibilityValueFact
    metric_scope: CompatibilityValueFact
    profile_output_segments: CompatibilityValueFact
    cann_version_evidence: tuple[CompatibilityValueFact, ...] = ()


@dataclass(frozen=True)
class ComparisonRunDescriptor:
    role: str
    label: str
    run_dir: str
    artifacts: dict[str, str | None]


@dataclass(frozen=True)
class ComparisonRoleFacts:
    descriptor: ComparisonRunDescriptor
    compatibility: CompatibilityFacts
    headline_groups: frozenset[str]
    headline_records: dict[str, tuple[ComparisonHeadline, ...]]
    policy_evidence: "RunEvidence"

    def headline_record(self, group: str) -> ComparisonHeadline:
        records = self.headline_records.get(group, ())
        return records[0] if len(records) == 1 else ComparisonHeadline()


@dataclass(frozen=True)
class ComparisonFacts:
    baseline: ComparisonRoleFacts
    candidate: ComparisonRoleFacts


    def headline_groups(self, order: tuple[str, ...]) -> list[str]:
        names = self.baseline.headline_groups | self.candidate.headline_groups
        ordered = [name for name in order if name in names]
        ordered.extend(sorted(names - set(ordered)))
        return ordered


@dataclass(frozen=True)
class ReportTableRowFact:
    label: str
    value: Any
    artifact: str
    field_ref: str


@dataclass(frozen=True)
class ReportSetupFacts:
    application_text: str
    workload_text: str


@dataclass(frozen=True)
class ReportSetupMetadataFacts:
    hardware_text: str
    cann_text: str
    profile_date_text: str
    profile_command_text: str
    profile_output_line: str
    collection_plan_line: str | None
    metric_scope: MetricScopeFact | None
    launch_metadata: LaunchMetadataFact | None


@dataclass(frozen=True)
class ReportSimulatorHotspotFacts:
    structured_model_present: bool
    markdown_summary_present: bool


@dataclass(frozen=True)
class ReportFacts:
    setup_metadata: ReportSetupMetadataFacts
    setup_context: ReportSetupFacts
    headline_rows: tuple[tuple[str, str, Any, str], ...]
    primary_headline: HeadlineFact | None
    diagnosis_headlines: tuple[tuple[str, HeadlineFact], ...]
    analysis_artifacts: tuple[str, ...]
    caveats: tuple[str, ...]
    profile_context_rows: tuple[ReportTableRowFact, ...]
    tilelang_context_rows: tuple[ReportTableRowFact, ...]
    analysis_dimensions: tuple[AnalysisDimension, ...]
    evidence_readiness: EvidenceReadiness | None
    evidence_relations: tuple[EvidenceRelation, ...]
    correlation_headlines: tuple[tuple[str, HeadlineFact], ...]
    section_headlines: tuple[tuple[str, tuple[HeadlineFact, ...]], ...]
    pending_collection_actions: tuple[CollectionAction, ...]
    simulator_hotspots: ReportSimulatorHotspotFacts


class RunEvidence:
    """Small interface over analysis artifacts for one run directory."""

    def __init__(
        self,
        run_dir: Path,
        summary: Summary | dict[str, Any] | None,
        raw_artifact_index: RawArtifactIndex | dict[str, Any] | None,
        provenance: Provenance | dict[str, Any] | None,
        tilelang_context: CallerContext | dict[str, Any] | None,
        profile_context: CallerContext | dict[str, Any] | None,
        simulator_hotspots: SimulatorModel | dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        *,
        collection_receipts: CollectionReceipts | None = None,
    ) -> None:
        self.run_dir = Path(run_dir)
        self._summary_present = summary is not None
        try:
            self._summary = load_summary(summary) if summary is not None else None
        except (ValueError, KeyError, TypeError) as exc:
            raise RunEvidenceError(f"invalid analysis/summary.json: {exc}; regenerate derived evidence with ascend-msprof analyze --run-dir <run>") from exc
        load_warnings = list(warnings or [])
        try:
            self._raw_artifact_index = RawArtifactIndex.model_validate(raw_artifact_index) if raw_artifact_index is not None else None
        except ValueError as exc:
            raise RunEvidenceError(f"invalid analysis/raw_artifact_index.json: {exc}") from exc
        try:
            self._provenance = Provenance.model_validate(provenance) if provenance is not None else None
        except ValueError as exc:
            raise RunEvidenceError(f"invalid analysis/provenance.json: {exc}") from exc
        self._tilelang_context = _caller_input(tilelang_context, TILELANG_CONTEXT_ARTIFACT)
        self._profile_context = _caller_input(profile_context, PROFILE_CONTEXT_ARTIFACT)
        for context in (self._tilelang_context, self._profile_context):
            if context is not None:
                load_warnings.extend(f"{issue.source.artifact}: {issue.source.field}: {issue.reason}"
                                     for issue in context.issues)
        try:
            self._simulator_hotspots = SimulatorModel.model_validate(simulator_hotspots) if simulator_hotspots is not None else None
        except ValueError as exc:
            raise RunEvidenceError(f"invalid analysis/simulator_hotspots.json: {exc}") from exc
        self._warnings = tuple(load_warnings)
        self.benchmark = BenchmarkEvidence()
        self.source_artifacts: dict[str, Any] = {}
        self.segment_commands: dict[str, CompatibilityValueFact] = {}
        self._collection_receipts = (collection_receipts if collection_receipts is not None
                                     else load_collection_receipts(self.run_dir))
        self._warnings += tuple(f"{item.artifact}: {item.issue.reason}"
                                for item in self._collection_receipts.records if item.issue is not None)
        try:
            if (self._simulator_hotspots is not None and self._simulator_hotspots.inputs
                    and not self._collection_receipts.allows("simulator")):
                raise ValueError('simulator inputs are excluded by collection receipts')
            if self._summary_present:
                validate_receipt_admission(self._summary, self._collection_receipts)
                validate_receipt_dimensions(self._summary.analysis_dimensions, self._collection_receipts)
                validate_summary_index(self._summary, self._raw_artifact_index,
                                      self._collection_receipts.excluded_segments)
                if self._simulator_hotspots is not None:
                    dimension = next(d for d in self._summary.analysis_dimensions if d.id == 'source_pipeline_context')
                    if dimension != build_simulator_dimension(self._simulator_hotspots):
                        raise ValueError('simulator dimension disagrees with normalized simulator facts')
                    if self._summary.evidence_relations != build_evidence_relations(
                            self._summary, self._summary.analysis_dimensions, self._simulator_hotspots):
                        raise ValueError('simulator relation references disagree with normalized simulator facts')
                    if self._raw_artifact_index is not None:
                        admitted = {item.artifact: item for item in self._raw_artifact_index.artifacts
                                    if item.group in {'simulator_csv', 'simulator_trace'}
                                    and self._collection_receipts.allows(item.segment)}
                        if set(admitted) != {item.artifact for item in self._simulator_hotspots.inputs}:
                            raise ValueError('simulator inputs disagree with admitted raw inventory')
                        for item in self._simulator_hotspots.inputs:
                            indexed = admitted[item.artifact]
                            if (indexed.status, indexed.row_count, indexed.columns, indexed.sample_rows) != (
                                    item.parser_status, item.row_count, item.columns, item.sample_rows):
                                raise ValueError('simulator input facts disagree with raw inventory')
        except (ValueError, KeyError, TypeError) as exc:
            raise RunEvidenceError(f"invalid analysis/summary.json and raw index composition: {exc}") from exc
        if self._raw_artifact_index is None and any(isinstance(item, (TimingEvidence, OperatorEvidence)) and item.artifacts
                                             for item in self._headlines().values()):
            self._warnings += ("raw_artifact_index unavailable; timing artifact inventory consistency cannot be checked",)

    @classmethod
    def load(cls, run_dir: Path) -> "RunEvidence":
        run_dir = Path(run_dir)
        summary = _load_required_json_object(run_dir / "analysis" / "summary.json")
        warnings: list[str] = []
        raw_artifact_index = _load_raw_artifact_index(run_dir, warnings)
        provenance = _load_optional_provenance(run_dir, warnings)
        tilelang_context = load_caller_context(run_dir, TILELANG_CONTEXT_ARTIFACT, warnings)
        profile_context = load_caller_context(run_dir, PROFILE_CONTEXT_ARTIFACT, warnings)
        return cls(
            run_dir,
            summary,
            raw_artifact_index,
            provenance,
            tilelang_context,
            profile_context,
            _load_simulator_model(run_dir),
            warnings,
        )

    @classmethod
    def load_assessment(cls, run_dir: Path) -> "RunEvidence":
        """Load best-effort evidence for candidate summary output."""

        run_dir = Path(run_dir)
        if not run_dir.is_dir():
            raise RunEvidenceError(f"run directory not found: {run_dir}")
        warnings: list[str] = []
        summary = _load_candidate_summary_json(run_dir, warnings)
        receipts = load_collection_receipts(run_dir)
        try:
            raw_artifact_index = _load_raw_artifact_index(run_dir, warnings, warn_missing=False)
        except RunEvidenceError as exc:
            warnings.append(str(exc))
            raw_artifact_index = None
            # A damaged present index cannot authorize a summary whose inventory
            # consistency was not checked. Natural measurements load independently.
            summary = None
        provenance = _load_optional_provenance(run_dir, warnings, warn_missing=False)
        tilelang_context = load_caller_context(run_dir, TILELANG_CONTEXT_ARTIFACT, warnings, warn_missing=False)
        profile_context = load_caller_context(run_dir, PROFILE_CONTEXT_ARTIFACT, warnings, warn_missing=False)
        try:
            simulator_hotspots = _load_simulator_model(run_dir)
        except RunEvidenceError as exc:
            warnings.append(str(exc))
            simulator_hotspots = None
            summary = None
        try:
            evidence = cls(
                run_dir,
                summary,
                raw_artifact_index,
                provenance,
                tilelang_context,
                profile_context,
                simulator_hotspots,
                warnings,
                collection_receipts=receipts,
            )
        except RunEvidenceError as exc:
            warnings.append(str(exc))
            evidence = cls(run_dir, None, raw_artifact_index, provenance, tilelang_context,
                           profile_context, None, warnings, collection_receipts=receipts)

        warnings[:] = evidence.warnings()
        evidence.benchmark = load_benchmark(run_dir)
        from .generate_provenance import read_command, redact_text, selected_msprof_command_paths
        from ._profiler_segments import followup_action_from_command_path, followup_segment
        for path in selected_msprof_command_paths(run_dir / "logs"):
            action = followup_action_from_command_path(path)
            segment = followup_segment(action) if action else command_profile_output_segment(path)
            if segment:
                try:
                    value = redact_text(read_command(path))
                    evidence.segment_commands[segment] = CompatibilityValueFact(
                        value or None, SourceRef(artifact=path.relative_to(run_dir).as_posix(), field="command"))
                except OSError as exc:
                    warnings.append(f"{path.name}: {exc}")
        for key, artifact in evidence.artifact_presence().items():
            if artifact:
                try:
                    evidence.source_artifacts[key] = {"artifact": artifact, "sha256": digest_bytes((run_dir / artifact).read_bytes())}
                except OSError as exc:
                    warnings.append(f"{artifact}: {exc}")
        evidence._warnings = tuple(warnings)
        return evidence

    @classmethod
    def from_loaded(
        cls,
        run_dir: Path,
        summary: Summary | dict[str, Any] | None,
        *,
        raw_artifact_index: RawArtifactIndex | dict[str, Any] | None = None,
        provenance: Provenance | dict[str, Any] | None = None,
        tilelang_context: CallerContext | dict[str, Any] | None = None,
        profile_context: CallerContext | dict[str, Any] | None = None,
        simulator_hotspots: SimulatorModel | dict[str, Any] | None = None,
        warnings: list[str] | None = None,
    ) -> "RunEvidence":
        return cls(
            Path(run_dir),
            summary,
            raw_artifact_index,
            provenance,
            tilelang_context,
            profile_context,
            simulator_hotspots,
            warnings,
        )

    @classmethod
    def load_report(cls, run_dir: Path, summary: Summary | dict[str, Any]) -> "RunEvidence":
        run_dir = Path(run_dir)
        warnings: list[str] = []
        evidence = cls(
            run_dir,
            summary,
            _load_raw_artifact_index(run_dir, warnings, warn_missing=False),
            _load_optional_provenance(run_dir, warnings, warn_missing=False),
            load_caller_context(run_dir, TILELANG_CONTEXT_ARTIFACT, warnings, warn_missing=False),
            load_caller_context(run_dir, PROFILE_CONTEXT_ARTIFACT, warnings, warn_missing=False),
            _load_simulator_model(run_dir),
            warnings,
        )
        evidence.benchmark = load_benchmark(run_dir)
        return evidence

    @classmethod
    def from_report_inputs(
        cls,
        run_dir: Path,
        summary: Summary | dict[str, Any],
        *,
        provenance: Provenance | dict[str, Any] | None = None,
        tilelang_context: CallerContext | dict[str, Any] | None = None,
        profile_context: CallerContext | dict[str, Any] | None = None,
    ) -> "RunEvidence":
        run_dir = Path(run_dir)
        warnings: list[str] = []
        evidence = cls(
            run_dir,
            summary,
            _load_raw_artifact_index(run_dir, warnings, warn_missing=False),
            provenance,
            tilelang_context,
            profile_context,
            _load_simulator_model(run_dir),
            warnings,
        )
        evidence.benchmark = load_benchmark(run_dir)
        return evidence

    def warnings(self) -> list[str]:
        return list(self._warnings)

    def feedback_facts(self) -> FeedbackEvidenceFacts:
        return FeedbackEvidenceFacts(self)

    def summary(self) -> Summary | None:
        return self._summary

    def _headlines(self) -> dict[str, TimingEvidence | OperatorEvidence]:
        return self._summary.headlines if self._summary is not None else {}

    def summary_present(self) -> bool:
        return self._summary_present

    def provenance(self) -> Provenance | None:
        return self._provenance

    def tilelang_context(self) -> CallerContext | None:
        return self._tilelang_context

    def profile_context(self) -> CallerContext | None:
        return self._profile_context

    def simulator_hotspots(self) -> SimulatorModel | None:
        return self._simulator_hotspots

    def raw_artifact_index(self) -> RawArtifactIndex | None:
        return self._raw_artifact_index

    def artifact_presence(self) -> dict[str, str | None]:
        return {
            "summary": "analysis/summary.json" if self._summary_present else None,
            "raw_artifact_index": "analysis/raw_artifact_index.json" if self._raw_artifact_index else None,
            "provenance": "analysis/provenance.json" if self._provenance else None,
            "tilelang_context": "analysis/tilelang_context.json" if self._tilelang_context else None,
            "profile_context": "analysis/profile_context.json" if self._profile_context else None,
            "simulator_hotspots": "analysis/simulator_hotspots.json" if self._simulator_hotspots else None,
        }

    def target_name(self) -> str:
        headlines = self._headlines()
        for group in TARGET_HEADLINE_ORDER:
            item = headlines.get(group)
            if isinstance(item, TimingEvidence):
                if item.observation and item.observation.name:
                    return item.observation.name
            elif isinstance(item, OperatorEvidence):
                names = {artifact.launch_name for artifact in item.artifacts if artifact.launch_name}
                if len(names) == 1:
                    return next(iter(names))
        return "Ascend profiling run"

    def metric_scope(self) -> MetricScopeFact | None:
        scope = (self._summary.metric_scope if self._summary is not None else None)
        if scope is None:
            return None
        return MetricScopeFact(
            value=scope.value,
            artifact=scope.artifact,
            field_ref=scope.field_ref,
        )

    def comparison_metric_scope(self) -> tuple[Any, dict[str, Any] | None]:
        scope = self.metric_scope()
        if scope is None:
            return None, None
        return scope.value, {"artifact": scope.artifact, "field": scope.field_ref}

    def headline_records(self) -> list[HeadlineFact]:
        rows: list[HeadlineFact] = []
        headlines = self._headlines()
        for group, label in HEADLINE_GROUPS:
            if group in APP_TIMING_ARTIFACTS:
                rows.extend(self.timing_headline_records(group, label))
                continue
            rows.extend(self.operator_headline_records(group, label))
        return rows

    def operator_headline_records(self, group: str, label: str | None = None) -> list[HeadlineFact]:
        evidence = self._headlines().get(group)
        if not isinstance(evidence, OperatorEvidence):
            return []
        artifacts = self._operator_artifacts(evidence)
        rows = []
        for artifact in artifacts:
            if not artifact.observations and artifact.metadata:
                source = artifact.metadata[0].source
                field_ref = f"headlines.{group}.artifacts.metadata; record={source.record}; column={source.column}; field={source.field}"
                rows.append(HeadlineFact(group=group, label=label, name=artifact.launch_name, value=None,
                    field=None, field_kind="basic_info", artifact=artifact.artifact, segment=artifact.segment,
                    metric_scope=artifact.metric_scope, field_ref=field_ref, raw_value_field_ref=None))
            for item in artifact.observations:
                field_ref = observation_field_ref(group, item)
                rows.append(HeadlineFact(group=group, label=label, name=item.name, value=item.value,
                    field=item.metric, field_kind=operator_metric_kind(group, item), artifact=artifact.artifact,
                    segment=artifact.segment, metric_scope=artifact.metric_scope, field_ref=field_ref, raw_value_field_ref=field_ref, source=item.source))
        return rows

    def headline_record(self, group: str, label: str | None = None) -> HeadlineFact | None:
        headlines = self._headlines()
        item = headlines.get(group)
        if isinstance(item, TimingEvidence):
            return next((fact for fact in self.timing_headline_records(group, label)
                         if item.observation is not None and fact.source == item.observation.source), None)
        if isinstance(item, OperatorEvidence):
            artifacts = self._operator_artifacts(item)
            primary = select_operator_primary(artifacts)
            if primary.selected is None:
                records = self.operator_headline_records(group, label)
                return records[0] if len(records) == 1 and records[0].value is None else None
            return next((fact for fact in self.operator_headline_records(group, label)
                         if fact.source == primary.selected), None)
        return None

    def _operator_artifacts(self, evidence: OperatorEvidence) -> tuple[OperatorArtifact, ...]:
        coverage = self.profile_coverage()
        selected = coverage.selected_segments_by_family.get(evidence.group) if coverage is not None else None
        if selected:
            return tuple(item for item in evidence.artifacts if item.segment == selected)
        return evidence.artifacts

    def timing_headline_records(self, group: str, label: str | None = None) -> list[HeadlineFact]:
        item = self._headlines().get(group)
        if not isinstance(item, TimingEvidence):
            return []
        return [HeadlineFact(group=group, label=label, name=observation.name, value=observation.value,
                field=observation.source.field, field_kind=f"timing_{observation.statistic}",
                artifact=artifact.artifact, segment=artifact.segment, metric_scope=artifact.metric_scope,
                field_ref=observation_field_ref(group, observation),
                raw_value_field_ref=observation_field_ref(group, observation), source=observation.source)
                for artifact in item.artifacts for observation in artifact.observations]

    def comparison_observations(self, group: str) -> tuple[ComparisonHeadline, ...]:
        records = (self.timing_headline_records(group) if group in APP_TIMING_ARTIFACTS
                   else self.operator_headline_records(group))
        return tuple(self.comparison_headline_record(group, fact) for fact in records
                     if fact.value is not None and fact.field_kind != "frequency")

    def comparison_headline_record(self, group: str, fact: HeadlineFact | None = None) -> ComparisonHeadline:
        fact = fact or self.headline_record(group)
        if fact is None:
            return ComparisonHeadline()
        evidence = self._headlines()[group]
        artifacts = self._operator_artifacts(evidence) if isinstance(evidence, OperatorEvidence) else evidence.artifacts
        observation = next((item for artifact in artifacts for item in artifact.observations
                            if item.source == fact.source), None)
        row = dict(observation.scope) if observation else {}
        schema_issues = [HeadlineIssue(reason=issue.reason, source=issue.source)
                         for artifact in artifacts for issue in artifact.issues]
        identity = self.target_identity()
        if identity is not None and identity.segments:
            identity = identity.segments.get(fact.segment)
        return ComparisonHeadline(**{
            "present": True,
            "name": fact.name,
            "value": fact.value,
            "field": fact.field,
            "field_kind": fact.field_kind,
            "artifact": fact.artifact,
            "segment": fact.segment,
            "metric_scope": fact.metric_scope,
            "field_ref": fact.field_ref,
            "unit": observation.unit if observation else None,
            "statistic": observation.statistic if observation else None,
            "aggregation": "maximum_observed_cell",
            "scope": dict(observation.scope) if observation else {},
            "schema_issues": schema_issues,
            "target_identity": identity,
            "block_scope": {
                normalized_key(key): value
                for key, value in row.items()
                if normalized_key(key) in {"blockid", "subblockid"}
            } if row else None,
        })

    def headline_group_names(self) -> set[str]:
        headlines = self._headlines()
        return {str(name) for name in headlines}

    def headline_rows(self) -> list[tuple[str, str, Any, str]]:
        rows = []
        for fact in self.headline_records():
            label = fact.label or fact.group
            source = f"`{fact.artifact}`; `{fact.field_ref}`"
            rows.append((label, fact.signal, fact.value, source))
        return rows

    def ambiguous_timing(self) -> bool:
        return any(isinstance(item, TimingEvidence) and item.available and not item.unique_scope
                   for item in self._headlines().values())

    def ambiguous_operator_groups(self) -> tuple[str, ...]:
        return tuple(group for group, item in self._headlines().items()
                     if isinstance(item, OperatorEvidence)
                     and select_operator_primary(self._operator_artifacts(item)).reason == "multiple_scopes")

    def primary_headline(self) -> HeadlineFact | None:
        """The caller selects the report's main observation from its question."""
        return None

    def launch_metadata(self) -> LaunchMetadataFact | None:
        evidence = self._headlines().get("op_basic_info")
        if not isinstance(evidence, OperatorEvidence):
            return None
        artifacts = self._operator_artifacts(evidence)
        if len(artifacts) != 1:
            return None
        artifact = artifacts[0]
        fields = [(item.source.field, item.value) for item in artifact.metadata
                  if item.metric in {"op_type", "block_dim", "mix_block_dim"}]
        fields.extend((item.source.field, item.value) for item in artifact.observations if item.statistic == "frequency")
        return LaunchMetadataFact(artifact=artifact.artifact, fields=tuple(fields)) if fields else None

    def diagnosis_headlines(self) -> list[tuple[str, HeadlineFact]]:
        rows = [(label, fact) for group, label in HEADLINE_GROUPS if group in APP_TIMING_ARTIFACTS
                for fact in self.timing_headline_records(group, label)]
        declared, extras = partition_declared_subject(
            rows, self.profile_coverage(), name=lambda pair: pair[1].name)
        return list(declared) + list(extras)

    def section_headlines(self, groups: list[str] | tuple[str, ...]) -> list[HeadlineFact]:
        rows = []
        for group in groups:
            if group in APP_TIMING_ARTIFACTS:
                rows.extend(self.timing_headline_records(group))
            else:
                rows.extend(self.operator_headline_records(group))
        if any(group in APP_TIMING_ARTIFACTS for group in groups):
            declared, extras = partition_declared_subject(rows, self.profile_coverage())
            return list(declared) + list(extras)
        return rows

    def correlation_headlines(self, groups: list[tuple[str, str]] | tuple[tuple[str, str], ...]) -> list[tuple[str, HeadlineFact]]:
        rows = []
        for label, group in groups:
            facts = self.section_headlines([group])
            if not facts:
                return []
            rows.extend((label, fact) for fact in facts)
        return rows

    def analysis_dimensions(self) -> tuple[AnalysisDimension, ...]:
        return (self._summary.analysis_dimensions if self._summary is not None else ())

    def evidence_relations(self) -> tuple[EvidenceRelation, ...]:
        return (self._summary.evidence_relations if self._summary is not None else ())

    def evidence_readiness(self) -> EvidenceReadiness | None:
        return (self._summary.evidence_readiness if self._summary is not None else None)


    def readiness_level(self) -> str | None:
        readiness = self.evidence_readiness()
        return readiness.level if readiness is not None else None

    def readiness_followups(self) -> tuple[CollectionAction, ...]:
        readiness = self.evidence_readiness()
        return readiness.recommended_followups if readiness is not None else ()

    def material_evidence_families(self) -> list[str]:
        readiness = self.evidence_readiness()
        families = readiness.available_evidence_families if readiness else ()
        return sorted(set(families) & MATERIAL_EVIDENCE_FAMILIES)

    def pending_collection_actions(self) -> tuple[CollectionAction, ...]:
        return self.next_collection_actions()

    def combined_pending_collection_actions(self) -> tuple[CollectionAction, ...]:
        actions = []
        seen: set[str] = set()
        for item in (*self.next_collection_actions(), *self.readiness_followups()):
            if item.id in seen:
                continue
            seen.add(item.id)
            actions.append(item)
        return tuple(actions)

    def next_collection_actions(self) -> tuple[CollectionAction, ...]:
        return (self._summary.next_collection_actions if self._summary is not None else ())

    def summary_warnings(self) -> list[Any]:
        warnings = (self._summary.warnings if self._summary is not None else None)
        return list(warnings) if warnings is not None else []

    def raw_artifacts(self) -> list[RawArtifactFact]:
        if self._raw_artifact_index is None:
            return []
        return [RawArtifactFact(
            index=index, artifact=item.artifact, group=item.group, parser=item.parser,
            segment=item.segment, metric_scope=item.metric_scope, status=item.status,
            row_count=item.row_count, columns=item.columns, warnings=item.warnings,
            canonical_stem=item.canonical_stem, launch_key=item.launch_key,
            target_name=item.target_name, normalized_target_name=item.normalized_target_name,
        ) for index, item in enumerate(self._raw_artifact_index.artifacts)]

    def raw_artifact_summary(self) -> RawArtifactSummary:
        if self._raw_artifact_index is None:
            return RawArtifactSummary(
                present=False,
                schema_version=None,
                artifact_count=0,
                parsed_count=0,
                status_counts={},
                group_counts={},
                segment_counts={},
                warnings=(),
            )
        artifacts = self.raw_artifacts()
        status_counts = Counter(fact.status or "unknown" for fact in artifacts)
        group_counts = Counter(fact.group or "unknown" for fact in artifacts)
        segment_counts = Counter(fact.segment or "unknown" for fact in artifacts)
        warnings = []
        warnings.extend(self._raw_artifact_index.warnings)
        for fact in artifacts:
            warnings.extend(str(item) for item in fact.warnings)
        return RawArtifactSummary(
            present=True,
            schema_version=self._raw_artifact_index.raw_artifact_index_schema_version,
            artifact_count=len(artifacts),
            parsed_count=status_counts.get("parsed", 0),
            status_counts=dict(sorted(status_counts.items())),
            group_counts=dict(sorted(group_counts.items())),
            segment_counts=dict(sorted(segment_counts.items())),
            warnings=tuple(warnings),
        )

    def raw_artifact_index_view(self) -> RawIndexView:
        if self._raw_artifact_index is None:
            return RawIndexView(present=False)
        artifacts = self.raw_artifacts()
        group_counts = Counter(fact.group or "unknown" for fact in artifacts)
        status_counts = Counter(fact.status or "unknown" for fact in artifacts)
        segment_counts = Counter(fact.segment or "unknown" for fact in artifacts)
        raw_warnings = self._raw_artifact_index.warnings
        return RawIndexView(
            present=True,
            schema_version=self._raw_artifact_index.raw_artifact_index_schema_version,
            artifact_count=len(artifacts), group_counts=dict(sorted(group_counts.items())),
            status_counts=dict(sorted(status_counts.items())), segment_counts=dict(sorted(segment_counts.items())),
            warnings=raw_warnings,
        )


    def parsed_raw_artifact_counts(self) -> tuple[int, dict[str, int], dict[str, int]]:
        parsed = [fact for fact in self._evidence_artifacts() if fact.status == "parsed"]
        group_counts = Counter(fact.group or "unknown" for fact in parsed)
        segment_counts = Counter(fact.segment or "unknown" for fact in parsed)
        return len(parsed), dict(sorted(group_counts.items())), dict(sorted(segment_counts.items()))

    def parsed_raw_artifacts_by_group(self, groups: set[str]) -> list[RawArtifactFact]:
        return [
            fact
            for fact in self._evidence_artifacts()
            if fact.status == "parsed" and str(fact.group or "") in groups
        ]

    def _evidence_artifacts(self) -> list[RawArtifactFact]:
        return [
            fact
            for fact in self.raw_artifacts()
            if fact.segment is None
            or self._collection_receipts.allows(fact.segment)
        ]

    def parsed_required_artifacts(
        self,
        groups: set[str],
        required_artifacts: list[str],
    ) -> tuple[list[RawArtifactFact], list[str], set[str]]:
        required_by_stem = {Path(artifact).stem: artifact for artifact in required_artifacts}
        present_by_stem: dict[str, RawArtifactFact] = {}
        allowed_keys: set[str] = set()
        coverage = self.profile_coverage()
        selected = coverage.selected_segments_by_family if coverage is not None else {}
        explicit_target = coverage is not None and coverage.explicit_target
        for fact in self.parsed_raw_artifacts_by_group(groups):
            canonical_stem = fact.canonical_stem or _canonical_operator_stem(fact.artifact)
            if canonical_stem not in required_by_stem:
                continue
            family = REQUIRED_STEM_FAMILY.get(canonical_stem)
            selected_segment = selected.get(family) if family else None
            if explicit_target and selected_segment is None:
                continue
            if selected_segment is not None and fact.segment != selected_segment:
                continue
            present_by_stem.setdefault(canonical_stem, fact)
            allowed_keys.update(_artifact_match_keys(fact.artifact))
        present = [present_by_stem[stem] for stem in required_by_stem if stem in present_by_stem]
        missing = [artifact for stem, artifact in required_by_stem.items() if stem not in present_by_stem]
        return present, missing, allowed_keys

    def _parsed_covered_artifacts(
        self,
        groups: set[str],
        required_artifacts: list[str],
    ) -> list[RawArtifactFact]:
        coverage = self.profile_coverage()
        if coverage is None or not coverage.explicit_target:
            return []
        segments = coverage.segments
        present = []
        for fact in self._parsed_scoped_artifacts(groups, required_artifacts):
            canonical_stem = fact.canonical_stem or _canonical_operator_stem(fact.artifact)
            family = REQUIRED_STEM_FAMILY.get(canonical_stem or "")
            segment = segments.get(fact.segment) if fact.segment else None
            family_coverage = segment.metric_coverage.get(family) if segment is not None else None
            if (
                segment is None
                or segment.count_complete is not True
                or family_coverage is None
                or family_coverage.complete is not True
            ):
                continue
            present.append(fact)
        return present

    def _parsed_scoped_artifacts(
        self,
        groups: set[str],
        required_artifacts: list[str],
    ) -> list[RawArtifactFact]:
        coverage = self.profile_coverage()
        if coverage is None or not coverage.explicit_target:
            return []
        segments = coverage.segments
        required_stems = {Path(artifact).stem for artifact in required_artifacts}
        present: dict[tuple[str, str], RawArtifactFact] = {}
        for fact in self.parsed_raw_artifacts_by_group(groups):
            canonical_stem = fact.canonical_stem or _canonical_operator_stem(fact.artifact)
            segment = segments.get(fact.segment) if fact.segment else None
            target_scope = segment.target_scope if segment is not None else None
            if (
                canonical_stem not in required_stems
                or target_scope is None
                or target_scope.kind != "focused_subset"
            ):
                continue
            present.setdefault((str(fact.segment), canonical_stem), fact)
        return list(present.values())

    def _complete_program_target_scope(self) -> dict[str, Any] | None:
        coverage = self.profile_coverage()
        if coverage is None or not coverage.explicit_target:
            return None
        return {
            "kind": "complete_program",
            "kernel_selector": coverage.kernel_selector,
            "expected_counts": coverage.expected_counts or {},
            "expected_total": coverage.expected_total,
        }

    def target_identity(self) -> TargetIdentity | None:
        return (self._summary.target_identity if self._summary is not None else None)

    def profile_coverage(self) -> ProfileCoverage | None:
        return (self._summary.profile_coverage if self._summary is not None else None)

    def target_scope_for_segment(self, segment: str | None) -> dict[str, Any] | None:
        coverage = self.profile_coverage()
        item = coverage.segments.get(segment) if coverage is not None and segment else None
        return item.target_scope.model_dump(mode="json", exclude_unset=True) if item is not None else None

    def raw_group_present(self, groups: set[str]) -> bool:
        return bool(self.parsed_raw_artifacts_by_group(groups))

    def summary_signal_records(
        self,
        groups: set[str],
        *,
        limit: int = 3,
        allowed_artifact_keys: set[str] | None = None,
    ) -> list[SummarySignalFact]:
        out: list[SummarySignalFact] = []
        for dimension in self.analysis_dimensions():
            for signal in dimension.signals:
                if signal.group not in groups:
                    continue
                if not _artifact_matches_keys(signal.artifact, allowed_artifact_keys):
                    continue
                out.append(
                    SummarySignalFact(
                        group=_str_or_none(signal.group),
                        artifact=signal.artifact,
                        field=signal.field,
                        field_ref=signal.field_ref,
                        segment=signal.segment,
                        metric_scope=signal.metric_scope,
                    )
                )
                if len(out) >= limit:
                    return out
        return out

    def measurement_quality(self) -> MeasurementQuality | None:
        return (self._summary.measurement_quality if self._summary is not None else None)


    @staticmethod
    def comparison_facts(
        baseline: "RunEvidence",
        candidate: "RunEvidence",
    ) -> ComparisonFacts:
        return ComparisonFacts(
            baseline=baseline.comparison_role_facts("baseline"),
            candidate=candidate.comparison_role_facts("candidate"),
        )

    def comparison_role_facts(self, role: str) -> ComparisonRoleFacts:
        headline_groups = self.headline_group_names()
        return ComparisonRoleFacts(
            descriptor=ComparisonRunDescriptor(
                role=role,
                label=self.run_dir.name,
                run_dir=_run_display(self.run_dir),
                artifacts=self._comparison_artifact_presence(),
            ),
            compatibility=self.comparison_compatibility(),
            headline_groups=frozenset(headline_groups),
            headline_records={
                group: self.comparison_observations(group)
                for group in headline_groups
            },
            policy_evidence=self,
        )


    def _comparison_artifact_presence(self) -> dict[str, str | None]:
        presence = self.artifact_presence()
        return {
            "summary": presence["summary"],
            "provenance": presence["provenance"],
            "tilelang_context": presence["tilelang_context"],
            "raw_artifact_index": presence["raw_artifact_index"],
        }


    def inspection_targets(self, limit: int = 3) -> tuple[InspectionTarget, ...]:
        simulator = self._simulator_hotspots
        if simulator is None:
            return ()
        out = []
        for group, kind in (('source_lines', 'source_line'), ('instructions', 'instruction'), ('pipeline_events', 'pipeline_event')):
            for index, row in enumerate(getattr(simulator, group)[:limit]):
                signal = simulator_row_signal(group, index, row)
                target = {'source': 'simulator_hotspots', 'kind': kind, 'id': f'sim.{group}.{index + 1:04d}',
                          'rank': index + 1, 'artifact': row.artifact,
                          'field': signal.field if signal else None, 'field_ref': signal.field_ref if signal else None,
                          'value': signal.value if signal else None,
                          'source_file': row.source_file if group == 'source_lines' else None,
                          'line': row.line if group == 'source_lines' else None,
                          'instruction': row.instr if group == 'instructions' else None}
                if group == 'source_lines':
                    target['source_context'] = row.source_context
                out.append(InspectionTarget(**target))
        return tuple(out)

    def benchmark_subject_checks(self) -> list[AssociationCheck]:
        subject = benchmark_association_values(self.benchmark.record)['benchmark_subject']
        checks = []
        for context, artifact, field in (
            (self._tilelang_context.sources.payload if self._tilelang_context else None, TILELANG_CONTEXT_ARTIFACT, "sources.payload.sha256"),
            (self._profile_context.sources.application if self._profile_context else None, PROFILE_CONTEXT_ARTIFACT, "sources.application.sha256"),
        ):
            value = context.sha256 if context else None
            if value is not None:
                checks.append(AssociationCheck(**{"id": "benchmark_subject", "status": association_check_status("benchmark_subject", subject, value, ()),
                               "benchmark": subject, "profiler": value,
                               "sources": [{"artifact": artifact, "field_ref": field},
                                           *[source_ref(source).model_dump(mode="json", exclude_none=True) for source in self.benchmark.sources]]}))
        # A TileLang payload and its launch harness are different objects. A match
        # to either recorded implementation establishes the subject link.
        return checks

    def linked_benchmark(self) -> BenchmarkRecord | None:
        return self.benchmark.record if any(c.status == "match" for c in self.benchmark_subject_checks()) else None

    def candidate_context(self) -> CandidateContextFacts:
        sources: dict[str, CandidateContextSourceFact] = {}
        tile, profile = self._tilelang_context, self._profile_context
        tile_role = "tilelang_benchmark_context"
        profile_role = "caller_context_not_profiler_evidence"
        raw_role = "caller_owned_acceptance_context_not_profiler_evidence"
        benchmark_contexts = [(context, role) for context, role in ((tile, tile_role), (profile, profile_role)) if context is not None]

        def select(key: str, candidates: list[tuple[Any, str, str, str]]) -> Any:
            for value, artifact, field, role in candidates:
                if _has_context_value(value):
                    sources[key] = CandidateContextSourceFact(artifact, field, role)
                    return value
            return None

        workload = {}
        workload_evidence: dict[str, list[dict[str, Any]]] = {}
        workload_candidates = [(context.workload("benchmark.workload"), role) for context, role in benchmark_contexts]
        if profile is not None:
            workload_candidates.append((profile.workload("verify_context.raw.workload"), raw_role))
        linked = self.linked_benchmark()
        for field in FEEDBACK_WORKLOAD_COMPARABILITY_FIELDS:
            candidates = []
            for item, role in workload_candidates:
                if item is not None:
                    original = item.id_field if field == "id" else field
                    candidates.append((getattr(item, field), item.source.artifact, f"{item.source.field}.{original}", role))
            if profile is not None:
                if field == "case_count":
                    candidates.append((profile.verification.case_count, PROFILE_CONTEXT_ARTIFACT,
                                       "verify_context.raw.correctness.receipt.case_count", raw_role))
                harness = profile.workload("profile_harness.workload")
                if harness is not None:
                    candidates.append((getattr(harness, field), PROFILE_CONTEXT_ARTIFACT,
                                       f"profile_harness.workload.{field}", "profile_manifest"))
            if linked is not None and linked.workload is not None and self.benchmark.sources:
                value = getattr(linked.workload, field)
                if field == "shape":
                    value = list(value)
                candidates.append((value, self.benchmark.sources[0].artifact,
                                   f"assessment.workload.{field}", "linked_benchmark_workload"))
            observations = []
            for value, artifact, source_field, role in candidates:
                if _has_context_value(value):
                    source = CandidateContextSourceFact(artifact, source_field, role)
                    observations.append({"value": value, "source": source.as_summary()})
                    sources.setdefault(f"workload.{field}", source)
            workload_evidence[field] = observations
            value, status = select_workload_value(tuple(WorkloadObservation.model_validate(item) for item in observations))
            if status == 'recorded':
                workload[field] = value

        payload = tile.sources.payload if tile else None
        if payload is not None:
            sources["payload"] = CandidateContextSourceFact(TILELANG_CONTEXT_ARTIFACT, "sources.payload", tile_role)
        jit_config = select("jit.config", [(context.benchmark.jit_config, context.artifact, "benchmark.jit_config", role)
                                           for context, role in benchmark_contexts])
        compiled_candidates = [(context.benchmark.compiled, context.artifact, "benchmark.candidate.compiled", role)
                               for context, role in benchmark_contexts]
        error_candidates = [(context.benchmark.error, context.artifact, "benchmark.candidate.error", role)
                            for context, role in benchmark_contexts]
        passed_candidates = [(context.benchmark.passed, role) for context, role in benchmark_contexts]
        runtime_candidates = [(context.benchmark.runtime, role) for context, role in benchmark_contexts]
        if profile is not None:
            compiled_candidates.append((profile.verification.compiled, PROFILE_CONTEXT_ARTIFACT, "verify_context.raw.candidate.compiled", raw_role))
            error_candidates.append((profile.verification.error, PROFILE_CONTEXT_ARTIFACT, "verify_context.raw.candidate.error", raw_role))
            passed_candidates.append((profile.verification.passed, raw_role))
            runtime_candidates.append((profile.verification.runtime, raw_role))
        compiled = select("correctness.compiled", compiled_candidates)
        passed = None
        for item, role in passed_candidates:
            if item is not None:
                passed = item.value
                sources["correctness.passed"] = CandidateContextSourceFact(item.source.artifact, item.source.field, role)
                break
        maxima = select("correctness.maxima", [(context.benchmark.maxima, context.artifact, "benchmark.correctness.maxima", role)
                                               for context, role in benchmark_contexts if context.benchmark.maxima]) or ()
        error = select("correctness.error", error_candidates)
        runtime = CandidateRuntimeFact(None, None, None, (), None, None, None, None, None, None)
        for item, role in runtime_candidates:
            if item is not None:
                runtime = CandidateRuntimeFact(item.value_ms, item.statistic, item.mean_ms, item.samples_ms,
                    item.authority, item.latency_source, item.runtime, item.runtime_stats, item.ref_runtime, item.source)
                sources.update({key: CandidateContextSourceFact(ref.artifact, ref.field, role) for key, ref in item.citations.items()})
                break
        passed_source = sources.get("correctness.passed")
        return CandidateContextFacts(workload=workload, workload_evidence=workload_evidence,
            payload=CandidatePayloadFact(present=payload is not None, artifact=payload.artifact if payload else None,
                                         sha256=payload.sha256 if payload else None, size_bytes=payload.size_bytes if payload else None),
            jit=CandidateJitFact(config=jit_config, debug=tile.jit_debug if tile else None),
            correctness=CandidateCorrectnessFact(compiled=compiled, passed=passed, error=error, maxima=maxima,
                                                 source=passed_source.artifact if passed_source else None),
            runtime=runtime, context_sources=sources)

    @staticmethod
    def workload_checks(baseline: "RunEvidence", candidate: "RunEvidence") -> tuple[WorkloadCheck, ...]:
        a_context, b_context = baseline.candidate_context(), candidate.candidate_context()
        checks = []
        for field in FEEDBACK_WORKLOAD_COMPARABILITY_FIELDS:
            sources = {side: tuple(WorkloadObservation.model_validate(item) for item in context.workload_evidence[field])
                       for side, context in (('a', a_context), ('b', b_context))}
            a, b = (select_workload_value(sources[side]) for side in ('a', 'b'))
            checks.append(WorkloadCheck(id=f'workload.{field}', status=workload_check_status(a, b),
                                        a=a[0], b=b[0], sources=sources))
        return tuple(checks)

    def context_feedback_evidence(self, source: str, key: str, role: str) -> FeedbackDesignEvidenceFact:
        citation = self.candidate_context().context_sources.get(key)
        if citation is None:
            return FeedbackDesignEvidenceFact(source=source, artifact=TILELANG_CONTEXT_ARTIFACT, role=role)
        return FeedbackDesignEvidenceFact(
            source=source,
            artifact=citation.artifact,
            field=citation.field_ref.split(".")[-1],
            field_ref=citation.field_ref,
            role=role,
        )

    def comparison_compatibility(self) -> CompatibilityFacts:
        provenance = self._provenance
        hardware = provenance.hardware if provenance is not None else None
        scope = self.metric_scope()
        return CompatibilityFacts(
            cann_version=_compatibility_value(provenance.cann_version if provenance else None),
            cann_version_evidence=_cann_version_evidence(provenance.cann_version if provenance else None),
            hardware_summary=_compatibility_value(hardware.summary if hardware else None),
            profile_command=_compatibility_value(provenance.profile_command if provenance else None),
            metric_scope=CompatibilityValueFact(
                value=scope.value if scope is not None else None,
                source=SourceRef(artifact=scope.artifact, field=scope.field_ref) if scope is not None else None,
            ),
            profile_output_segments=CompatibilityValueFact(
                value=provenance.profile_output_segments if provenance else None,
                source=SourceRef(artifact="analysis/provenance.json", field="profile_output_segments")
                if self._provenance
                else None,
            ),
        )

    def report_profile_context_rows(self) -> tuple[ReportTableRowFact, ...]:
        context = self._profile_context
        if context is None:
            return ()
        rows: list[ReportTableRowFact] = []
        for label, item, field in (("Harness manifest", context.sources.profile_harness_manifest, "profile_harness_manifest"),
                                   ("Application", context.sources.application, "application")):
            if item is not None:
                rows.extend((_report_row(label, item.artifact, PROFILE_CONTEXT_ARTIFACT, f"sources.{field}.artifact"),
                             _report_row(f"{label} sha256", item.sha256, PROFILE_CONTEXT_ARTIFACT, f"sources.{field}.sha256")))
        for index, item in enumerate(context.sources.implementation):
            rows.extend((
                _report_row(
                    f"Implementation[{index}]",
                    item.artifact,
                    PROFILE_CONTEXT_ARTIFACT,
                    f"sources.implementation[{index}].artifact",
                ),
                _report_row(
                    f"Implementation[{index}] sha256",
                    item.sha256,
                    PROFILE_CONTEXT_ARTIFACT,
                    f"sources.implementation[{index}].sha256",
                ),
            ))
        if _has_report_value(context.harness_workload):
            rows.append(_report_row("Harness workload", context.harness_workload, PROFILE_CONTEXT_ARTIFACT, "profile_harness.workload"))
        if _has_report_value(context.harness_jit_config):
            rows.append(_report_row("Harness JIT config", context.harness_jit_config, PROFILE_CONTEXT_ARTIFACT, "profile_harness.jit_config"))
        if context.sources.verify_json is not None:
            workload = context.workload("benchmark.workload")
            benchmark = context.benchmark
            runtime = benchmark.runtime
            fields = [
                ("Verify JSON", context.sources.verify_json.artifact, "sources.verify_json.artifact"),
                ("Workload id", workload.id if workload else None, "benchmark.workload.id"),
                ("Shape", workload.shape if workload else None, "benchmark.workload.shape"),
                ("Dtype", workload.dtype if workload else None, "benchmark.workload.dtype"),
                ("Case count", workload.case_count if workload else None, "benchmark.workload.case_count"),
                ("Compiled", benchmark.compiled, "benchmark.candidate.compiled"),
                ("Candidate runtime", runtime.runtime if runtime else None, "benchmark.candidate.runtime"),
                ("Runtime stats", runtime.runtime_stats if runtime else None, "benchmark.candidate.runtime_stats"),
                ("Reference runtime", runtime.ref_runtime if runtime else None, "benchmark.candidate.ref_runtime"),
                ("Correctness maxima", _report_maxima_text(benchmark.maxima), "benchmark.correctness.maxima"),
            ]
            rows.extend(_report_row(label, value, PROFILE_CONTEXT_ARTIFACT, field) for label, value, field in fields)
        return tuple(rows)

    def report_tilelang_context_rows(self) -> tuple[ReportTableRowFact, ...]:
        context = self._tilelang_context
        if not context:
            return ()

        candidate = self.candidate_context()

        def sourced_row(label: str, value: Any, source_key: str, fallback_field_ref: str) -> ReportTableRowFact:
            source = candidate.context_sources.get(source_key)
            if source is not None:
                return _report_row(label, value, source.artifact, source.field_ref)
            return _report_row(label, value, TILELANG_CONTEXT_ARTIFACT, fallback_field_ref)

        rows = [
            sourced_row(
                "Workload id",
                candidate.workload.get("id"),
                "workload.id",
                "benchmark.workload.id",
            ),
            sourced_row(
                "Shape",
                candidate.workload.get("shape"),
                "workload.shape",
                "benchmark.workload.shape",
            ),
            sourced_row(
                "Dtype",
                candidate.workload.get("dtype"),
                "workload.dtype",
                "benchmark.workload.dtype",
            ),
            sourced_row(
                "Case count",
                candidate.workload.get("case_count"),
                "workload.case_count",
                "benchmark.workload.case_count",
            ),
            sourced_row(
                "Compiled",
                candidate.correctness.compiled,
                "correctness.compiled",
                "benchmark.candidate.compiled",
            ),
            sourced_row(
                "Candidate runtime",
                candidate.runtime.runtime,
                "runtime.runtime",
                "benchmark.candidate.runtime",
            ),
            sourced_row(
                "Runtime stats",
                candidate.runtime.runtime_stats,
                "runtime.runtime_stats",
                "benchmark.candidate.runtime_stats",
            ),
            sourced_row(
                "Reference runtime",
                candidate.runtime.ref_runtime,
                "runtime.ref_runtime",
                "benchmark.candidate.ref_runtime",
            ),
            sourced_row(
                "Correctness maxima",
                _report_maxima_text(candidate.correctness.maxima),
                "correctness.maxima",
                "benchmark.correctness.maxima",
            ),
        ]
        if candidate.payload.present:
            rows.append(
                _report_row(
                    "Payload source",
                    candidate.payload.artifact,
                    TILELANG_CONTEXT_ARTIFACT,
                    "sources.payload.artifact",
                )
            )
            rows.append(
                _report_row(
                    "Payload sha256",
                    candidate.payload.sha256,
                    TILELANG_CONTEXT_ARTIFACT,
                    "sources.payload.sha256",
                )
            )
        if _has_report_value(candidate.jit.config):
            rows.append(
                sourced_row("JIT config", candidate.jit.config, "jit.config", "benchmark.jit_config")
            )
        jit_debug = candidate.jit.debug
        if jit_debug is not None:
            if jit_debug.found is True:
                preview = ", ".join(item.artifact for item in jit_debug.artifacts[:5] if item.artifact is not None)
                if len(jit_debug.artifacts) > 5:
                    preview = f"{preview}, ..."
                value = f"{jit_debug.artifact_count} files"
                if preview:
                    value = f"{value}: {preview}"
            else:
                value = "not found" if jit_debug.found is False else "availability not recorded"
            rows.append(_report_row("JIT debug artifacts", value, TILELANG_CONTEXT_ARTIFACT, "jit_debug.artifacts"))
        return tuple(rows)

    def report_setup_context(self) -> ReportSetupFacts:
        return ReportSetupFacts(
            application_text=self._report_application_text(),
            workload_text=self._report_workload_text(),
        )

    def report_setup_metadata(self) -> ReportSetupMetadataFacts:
        provenance = self._provenance
        hardware = provenance.hardware if provenance else None
        return ReportSetupMetadataFacts(
            hardware_text=_report_sourced_text(hardware.summary if hardware else None, "Ascend 910B"),
            cann_text=_report_sourced_text(
                provenance.cann_version if provenance else None,
                "not recorded by this helper",
            ),
            profile_date_text=_report_sourced_text(
                provenance.profile_date if provenance else None,
                "not recorded by this helper",
            ),
            profile_command_text=_report_sourced_text(
                provenance.profile_command if provenance else None,
                "see reproduction section",
            ),
            profile_output_line=_report_profile_outputs_setup_line(provenance),
            collection_plan_line=_report_collection_plan_setup_line(provenance),
            metric_scope=self._report_metric_scope(),
            launch_metadata=self.launch_metadata(),
        )

    def report_facts(
        self,
        analysis_artifact_names: tuple[str, ...] | list[str],
        optional_analysis_artifacts: tuple[str, ...] | list[str],
        section_groups: tuple[tuple[str, list[str]], ...] | list[tuple[str, list[str]]],
        *,
        op_profile_enabled: bool = True,
    ) -> ReportFacts:
        setup_metadata = self.report_setup_metadata()
        metric_scope = setup_metadata.metric_scope
        return ReportFacts(
            setup_metadata=setup_metadata,
            setup_context=self.report_setup_context(),
            headline_rows=tuple(self.headline_rows()),
            primary_headline=self.primary_headline(),
            diagnosis_headlines=tuple(self.diagnosis_headlines()),
            analysis_artifacts=tuple(self._report_analysis_artifacts(analysis_artifact_names)),
            caveats=tuple(
                self.report_caveats(
                    optional_analysis_artifacts,
                    op_profile_enabled=op_profile_enabled,
                    op_metric_scope_value=metric_scope.value if metric_scope else None,
                )
            ),
            profile_context_rows=self.report_profile_context_rows(),
            tilelang_context_rows=self.report_tilelang_context_rows(),
            analysis_dimensions=tuple(self.analysis_dimensions()),
            evidence_readiness=self.evidence_readiness(),
            evidence_relations=tuple(self.evidence_relations()),
            correlation_headlines=tuple(self.correlation_headlines(_REPORT_CORRELATION_GROUPS)),
            section_headlines=tuple(
                (title, tuple(self.section_headlines(groups)))
                for title, groups in section_groups
            ),
            pending_collection_actions=tuple(self.pending_collection_actions()),
            simulator_hotspots=self.report_simulator_hotspots(),
        )

    def report_simulator_hotspots(self) -> ReportSimulatorHotspotFacts:
        return ReportSimulatorHotspotFacts(
            structured_model_present=(self.run_dir / "analysis" / "simulator_hotspots.json").exists(),
            markdown_summary_present=(self.run_dir / "analysis" / "simulator_hotspots.txt").exists(),
        )

    def _report_analysis_artifacts(self, names: tuple[str, ...] | list[str]) -> list[str]:
        out = []
        for name in names:
            if (self.run_dir / "analysis" / name).exists():
                out.append(f"`analysis/{name}`")
        presence = self.artifact_presence()
        if presence["provenance"]:
            out.append("`analysis/provenance.json`")
        if presence["tilelang_context"]:
            out.append("`analysis/tilelang_context.json`")
        if presence["profile_context"]:
            out.append("`analysis/profile_context.json`")
        return out

    def report_caveats(
        self,
        optional_analysis_artifacts: tuple[str, ...] | list[str],
        *,
        op_profile_enabled: bool = True,
        op_metric_scope_value: str | None = None,
    ) -> list[str]:
        out = []
        policy = metric_scope_policy(op_metric_scope_value)
        warnings = (self._summary.warnings if self._summary is not None else None)
        for warning in warnings or ():
            warning_text = str(warning)
            if not op_profile_enabled and warning_text.startswith(
                (
                    "missing op_basic_info:",
                    "missing pipe_utilization:",
                    "missing arithmetic_utilization:",
                    "missing l2_cache:",
                    "missing memory:",
                    "missing resource_conflict:",
                )
            ):
                continue
            group = warning_group(warning_text)
            if policy and policy.suppress_optional_missing_caveats and group in policy.optional_artifacts:
                continue
            if (
                policy
                and policy.suppress_optional_missing_caveats
                and group
                and group not in policy.required_artifacts
                and group not in policy.optional_artifacts
                and group
                in {
                    "pipe_utilization",
                    "arithmetic_utilization",
                    "l2_cache",
                    "memory",
                    "resource_conflict",
                }
            ):
                continue
            out.append(f"Analyzer warning: {warning}")
        for name in optional_analysis_artifacts:
            if not (self.run_dir / "analysis" / name).exists():
                out.append(f"Optional analysis artifact missing: analysis/{name}")
        out.extend(f"Provenance warning: {warning}" for warning in (self._provenance.warnings if self._provenance else ()))
        out.extend(_report_warning_caveats("TileLang context warning", self._tilelang_context))
        out.extend(_report_warning_caveats("Profile context warning", self._profile_context))
        return out

    def _report_application_text(self) -> str:
        context = self._profile_context
        if context is not None:
            manifest, application = context.sources.profile_harness_manifest, context.sources.application
            if manifest is not None and manifest.artifact:
                return (
                    f"profile harness manifest `{manifest.artifact}` and application "
                    f"`{application.artifact if application and application.artifact else 'not recorded'}` "
                    "(source: `analysis/profile_context.json`; `sources.profile_harness_manifest.artifact`, "
                    "`sources.application.artifact`)."
                )
            if application is not None and application.artifact:
                return (f"application `{application.artifact}` "
                        "(source: `analysis/profile_context.json`; `sources.application.artifact`).")
            return "recorded in `analysis/profile_context.json`."
        return self._report_tilelang_payload_text()

    def _report_workload_text(self) -> str:
        context = self._profile_context
        if context is None:
            return self._report_tilelang_setup_shape()
        workload = context.workload("benchmark.workload")
        if workload is not None:
            shape = _report_fmt_compact(workload.shape)
            dtype = _report_fmt_compact(workload.dtype)
            case_count = _report_fmt_compact(workload.case_count)
            return (f"{shape}, dtype {dtype}, cases {case_count} "
                    "(context only; source: `analysis/profile_context.json`; `benchmark.workload`).")
        if _has_report_value(context.harness_workload):
            return (f"{_report_fmt_compact(context.harness_workload)} "
                    "(context only; source: `analysis/profile_context.json`; `profile_harness.workload`).")
        return "not recorded by this helper."

    def _report_tilelang_setup_shape(self) -> str:
        context = self._tilelang_context
        if not context:
            return "not recorded by this helper."
        workload = self.candidate_context().workload
        shape = _report_fmt_compact(workload.get("shape"))
        dtype = _report_fmt_compact(workload.get("dtype"))
        case_count = _report_fmt_compact(workload.get("case_count"))
        return (
            f"{shape}, dtype {dtype}, cases {case_count} "
            "(source: `analysis/tilelang_context.json`; `benchmark.workload`)."
        )

    def _report_tilelang_payload_text(self) -> str:
        context = self._tilelang_context
        if not context:
            return "not recorded; inspect run notes if present."
        payload = self.candidate_context().payload
        if payload.artifact:
            return (
                f"TileLang payload `{payload.artifact}` "
                "(source: `analysis/tilelang_context.json`; `sources.payload.artifact`)."
            )
        return "TileLang payload recorded in `analysis/tilelang_context.json`."

    def _report_metric_scope(self) -> MetricScopeFact | None:
        for name in ["command_msprof_op.txt", "command_msprof.txt"]:
            path = self.run_dir / "logs" / name
            if not path.exists():
                continue
            command = path.read_text(encoding="utf-8", errors="replace")
            if name == "command_msprof.txt" and not is_msprof_op_command(command):
                continue
            scope = command_metric_scope(command)
            if scope:
                return MetricScopeFact(
                    value=scope,
                    artifact=f"logs/{name}",
                    field_ref="--aic-metrics",
                )
        return self.metric_scope()


def _load_required_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RunEvidenceError(f"missing {path}; run ascend-msprof analyze first")
    try:
        value = read_evidence_json(path)
    except (OSError, ValueError) as exc:
        raise RunEvidenceError(f"invalid {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RunEvidenceError(f"{path} is not a JSON object")
    return value


def _run_display(path: Path) -> str:
    if path.is_absolute():
        return f"<abs-path>/{path.name}"
    return path.as_posix()


def _load_candidate_summary_json(run_dir: Path, warnings: list[str]) -> dict[str, Any] | None:
    path = run_dir / "analysis" / "summary.json"
    if not path.exists():
        warnings.append("missing analysis/summary.json")
        return None
    try:
        value = read_evidence_json(path)
        if not isinstance(value, dict):
            raise ValueError("normalized summary must be a JSON object")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        warnings.append(f"invalid analysis/summary.json: {exc}")
        return None
    return value


def _load_raw_artifact_index(
    run_dir: Path, warnings: list[str], *, warn_missing: bool = True,
) -> RawArtifactIndex | None:
    path = run_dir / "analysis" / "raw_artifact_index.json"
    try:
        payload = read_evidence_json(path)
    except FileNotFoundError:
        if warn_missing:
            warnings.append("missing analysis/raw_artifact_index.json")
        return None
    except (OSError, ValueError) as exc:
        raise RunEvidenceError(f"invalid analysis/raw_artifact_index.json: {exc}") from exc
    try:
        return RawArtifactIndex.model_validate(payload)
    except ValueError as exc:
        raise RunEvidenceError(f"invalid analysis/raw_artifact_index.json: {exc}") from exc


def _load_simulator_model(run_dir: Path) -> SimulatorModel | None:
    try:
        payload = read_evidence_json(run_dir / 'analysis/simulator_hotspots.json')
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise RunEvidenceError(f'invalid analysis/simulator_hotspots.json: {exc}') from exc
    try:
        return SimulatorModel.model_validate(payload)
    except ValueError as exc:
        raise RunEvidenceError(f'invalid analysis/simulator_hotspots.json: {exc}') from exc


def _load_optional_provenance(run_dir: Path, warnings: list[str], *, warn_missing: bool = True) -> Provenance | None:
    try:
        model = load_provenance(run_dir)
    except (OSError, ValueError) as exc:
        warnings.append(f"invalid analysis/provenance.json: {exc}")
        return None
    if model is None and warn_missing:
        warnings.append("missing analysis/provenance.json")
    return model


def _caller_input(value: CallerContext | dict[str, Any] | None, artifact: str) -> CallerContext | None:
    if value is None:
        return None
    if isinstance(value, CallerContext):
        if value.artifact != artifact:
            raise RunEvidenceError(f"caller context belongs to {value.artifact}, expected {artifact}")
        return value
    if not isinstance(value, dict):
        raise RunEvidenceError(f"invalid {artifact}: expected a JSON object")
    return normalize_caller_context(value, artifact)


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _has_context_value(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _feedback_values_match(a_value: Any, b_value: Any) -> bool:
    return workload_values_match(a_value, b_value)


def _feedback_question(
    question_id: str,
    evidence_family: str,
    question: str,
    available_evidence: list[FeedbackDesignEvidenceFact],
    missing_evidence: list[FeedbackDesignEvidenceFact],
    blocked_by: list[str] | None = None,
) -> FeedbackDesignQuestionFact:
    return FeedbackDesignQuestionFact(
        question_id=question_id,
        evidence_family=evidence_family,
        question=question,
        available_evidence=tuple(available_evidence),
        missing_evidence=tuple(missing_evidence),
        blocked_by=tuple(blocked_by or []),
    )


def _missing_feedback_evidence(
    *,
    source: str,
    artifact: str,
    role: str,
    field: str | None = None,
    field_ref: str | None = None,
    segment: str | None = None,
    metric_scope: Any = None,
    target_scope: Any = None,
) -> FeedbackDesignEvidenceFact:
    return FeedbackDesignEvidenceFact(
        source=source,
        artifact=artifact,
        field=field,
        field_ref=field_ref,
        role=role,
        segment=segment,
        metric_scope=metric_scope,
        target_scope=target_scope,
    )


def _context_feedback_evidence(source: str, field_ref: str, role: str) -> FeedbackDesignEvidenceFact:
    return FeedbackDesignEvidenceFact(
        source=source,
        artifact=TILELANG_CONTEXT_ARTIFACT,
        field=field_ref.split(".")[-1],
        field_ref=field_ref,
        role=role,
    )


def _artifact_field_from_fact(fact: RawArtifactFact) -> Any:
    return fact.columns[0] if fact.columns else None


def _artifact_name_from_fact(fact: RawArtifactFact) -> str:
    return Path(str(fact.artifact or "")).name


def _canonical_operator_stem(artifact: Any) -> str | None:
    name = Path(str(artifact or "")).name
    for stem in REQUIRED_STEM_FAMILY:
        if name == f"{stem}.csv":
            return stem
        prefix = f"{stem}_"
        suffix = name[len(prefix) : -4] if name.startswith(prefix) and name.endswith(".csv") else ""
        if len(suffix) == 17 and suffix.isdigit():
            return stem
    return None


def _summary_signal_feedback_evidence(
    facts: FeedbackEvidenceFacts,
    groups: set[str],
    *,
    source: str,
    role: str,
    limit: int = 3,
    allowed_artifact_keys: set[str] | None = None,
) -> list[FeedbackDesignEvidenceFact]:
    return [
        FeedbackDesignEvidenceFact(
            source=source,
            artifact=signal.artifact,
            field=signal.field,
            field_ref=signal.field_ref,
            role=role,
            segment=signal.segment,
            metric_scope=signal.metric_scope,
            target_scope=facts.evidence.target_scope_for_segment(signal.segment),
        )
        for signal in facts.summary_signal_records(groups, limit=limit, allowed_artifact_keys=allowed_artifact_keys)
    ]


def _raw_group_feedback_evidence(
    facts: FeedbackEvidenceFacts,
    groups: set[str],
    *,
    source: str,
    role: str,
    limit: int = 3,
) -> list[FeedbackDesignEvidenceFact]:
    out = []
    for fact in facts.raw_artifacts_by_group(groups)[:limit]:
        out.append(
            FeedbackDesignEvidenceFact(
                source=source,
                artifact=fact.artifact,
                field=_artifact_field_from_fact(fact),
                field_ref=f"raw_artifact_index.artifacts[group={fact.group}]",
                role=role,
                segment=fact.segment,
                metric_scope=fact.metric_scope,
                target_scope=facts.evidence.target_scope_for_segment(fact.segment),
            )
        )
    return out


def _raw_artifact_feedback_evidence(
    artifacts: list[RawArtifactFact],
    *,
    facts: FeedbackEvidenceFacts,
    source: str,
    role: str,
) -> list[FeedbackDesignEvidenceFact]:
    out = []
    for fact in artifacts:
        out.append(
            FeedbackDesignEvidenceFact(
                source=source,
                artifact=fact.artifact,
                field=_artifact_field_from_fact(fact),
                field_ref=(
                    f"artifacts[{fact.index}]"
                    if fact.index is not None
                    else f"artifacts[artifact={_artifact_name_from_fact(fact)}]"
                ),
                role=role,
                segment=fact.segment,
                metric_scope=fact.metric_scope,
                target_scope=facts.evidence.target_scope_for_segment(fact.segment),
            )
        )
    return out


def _prefix_feedback_blockers(source: str, blockers: list[str] | tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(f"{source}: {blocker}" for blocker in blockers))


def _report_row(label: str, value: Any, artifact: str, field_ref: str) -> ReportTableRowFact:
    return ReportTableRowFact(
        label=label,
        value=value,
        artifact=artifact,
        field_ref=field_ref,
    )


def _has_report_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def _report_fmt_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{float(value):.6g}"
    return str(value)


def _report_fmt_compact(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _report_fmt_value(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ": "))
    return str(value)


def _report_maxima_text(maxima: tuple[CorrectnessMaximum, ...]) -> str:
    return ", ".join(f"{item.field}={_report_fmt_value(item.value)}" for item in maxima) or "none recorded"


def _report_warning_caveats(prefix: str, context: CallerContext | None) -> list[str]:
    return [f"{prefix}: {warning}" for warning in context.warnings] if context else []


def _report_sourced_text(item: Sourced[str] | Sourced[str | int] | CannVersion | None, fallback: str) -> str:
    if item is None:
        return fallback
    text = _report_fmt_value(item.value)
    field = f"; `{item.source.field}`" if item.source.field else ""
    return f"{text} (source: `{item.source.artifact}`{field})"


def _report_profile_outputs_text(provenance: Provenance | None) -> str:
    if provenance is None:
        return "not recorded"
    if provenance.profile_outputs:
        return ", ".join(_report_sourced_text(item, "not recorded") for item in provenance.profile_outputs)
    return _report_sourced_text(provenance.profile_output, "not recorded")


def _report_profile_output_segments_text(provenance: Provenance | None) -> str | None:
    if provenance is None or provenance.profile_output_segments is None:
        return None
    segments = provenance.profile_output_segments
    rendered = []
    for name, segment in (("app", segments.app), ("op", segments.op), ("simulator", segments.simulator),
                          *((f"followups.{name}", item) for name, item in sorted(segments.followups.items()))):
        if segment is not None:
            parts = _report_profile_output_segment_parts(segment)
            if parts:
                rendered.append(f"{name}: {', '.join(parts)}")
    return "; ".join(rendered) or None


def _report_profile_output_segment_parts(segment: OutputSegment) -> list[str]:
    parts = []
    if segment.output is not None:
        parts.append(_report_sourced_text(segment.output, "not recorded"))
    if segment.resolved_output is not None:
        parts.append(f"resolved {_report_sourced_text(segment.resolved_output, 'not recorded')}")
    return parts


def _report_profile_outputs_setup_line(provenance: Provenance | None) -> str:
    segmented = _report_profile_output_segments_text(provenance)
    if segmented:
        return f"- Profile outputs: {segmented}"
    return f"- Profile output: {_report_profile_outputs_text(provenance)}"


def _report_collection_plan_setup_line(provenance: Provenance | None) -> str | None:
    if provenance is None or provenance.collection_plan is None:
        return None
    plan = provenance.collection_plan
    segments = [segment.segment_id for segment in plan.segments]
    segment_text = f"; segments: {', '.join(segments)}" if segments else ""
    source_text = f"; source: {plan.source}" if plan.source else ""
    return f"- Collection plan: {_report_md_escape(plan.preset_id)}{segment_text}{source_text}"


def _report_md_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _compatibility_value(item: Sourced[str] | CannVersion | None) -> CompatibilityValueFact:
    return CompatibilityValueFact(item.value if item else None, item.source if item else None,
                                  item.status if isinstance(item, CannVersion) else None)


def _cann_version_evidence(item: CannVersion | None) -> tuple[CompatibilityValueFact, ...]:
    return tuple(_compatibility_value(entry) for entry in item.evidence) if item else ()


def select_cann_versions(
    a: CompatibilityFacts, b: CompatibilityFacts,
) -> tuple[CompatibilityValueFact, CompatibilityValueFact]:
    """Select a shared recorded component, preserving version values and conflicts."""
    a_version, b_version = a.cann_version, b.cann_version
    if "conflict" in (a_version.status, b_version.status):
        return a_version, b_version

    def sources(facts: CompatibilityFacts) -> dict[str, SourceRef | None]:
        result = {}
        for fact in (facts.cann_version, *facts.cann_version_evidence):
            component = cann_version_component(fact.source)
            if component and _feedback_values_match(fact.value, facts.cann_version.value):
                result.setdefault(component, fact.source)
        return result

    a_sources, b_sources = sources(a), sources(b)
    for component in ("toolkit", "runtime", "compiler", "opp"):
        if component in a_sources and component in b_sources:
            return (
                CompatibilityValueFact(a_version.value, a_sources[component], a_version.status),
                CompatibilityValueFact(b_version.value, b_sources[component], b_version.status),
            )
    return a_version, b_version


def _artifact_match_keys(artifact: Any) -> set[str]:
    if artifact in (None, ""):
        return set()
    artifact_text = str(artifact)
    return {artifact_text, Path(artifact_text).name}


def _artifact_matches_keys(artifact: Any, allowed_keys: set[str] | None) -> bool:
    if allowed_keys is None:
        return True
    return bool(_artifact_match_keys(artifact) & allowed_keys)
