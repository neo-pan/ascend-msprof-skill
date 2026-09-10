"""Read-only facts derived from an analyzed Ascend profiling run."""
from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._profiler_segments import segment_receipt_allows_evidence
from .ascend_profile_utils import normalized_key
from .metric_scope_policy import command_metric_scope, is_msprof_op_command, metric_scope_policy, warning_group


HEADLINE_GROUPS: tuple[tuple[str, str], ...] = (
    ("op_summary", "Top operator duration"),
    ("op_statistic", "Top operator type aggregate"),
    ("task_time", "Top task duration"),
    ("api_statistic", "Top host/runtime API time"),
    ("op_basic_info", "Operator metadata"),
    ("pipe_utilization", "Dominant pipe signal"),
    ("arithmetic_utilization", "Arithmetic utilization signal"),
    ("l2_cache", "L2 cache hit-rate signal"),
    ("memory", "Top memory signal"),
    ("resource_conflict", "Top conflict signal"),
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
FEEDBACK_WORKLOAD_COMPARABILITY_FIELDS: tuple[str, ...] = ("id", "shape", "dtype", "case_count")
FEEDBACK_READINESS_LEVEL_ORDER = {
    "insufficient": 0,
    "triage_only": 1,
    "directional": 2,
    "actionable_experiment": 3,
    "comparison_ready": 4,
}
FEEDBACK_MIN_COMPARISON_READINESS_LEVEL = "directional"

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

    @property
    def signal(self) -> str:
        if self.field:
            return f"{self.name or 'n/a'} / {self.field}"
        return str(self.name or "n/a")

    @property
    def correlation_field_ref(self) -> str:
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
    metric_scope: Any
    status: str | None
    row_count: Any
    columns: tuple[Any, ...]
    warnings: tuple[Any, ...]
    canonical_stem: str | None = None
    launch_key: str | None = None
    target_name: str | None = None
    normalized_target_name: str | None = None


@dataclass(frozen=True)
class RawArtifactSummary:
    present: bool
    schema_version: Any
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
    related_design_variables: tuple[str, ...]
    available_evidence: tuple[FeedbackDesignEvidenceFact, ...]
    missing_evidence: tuple[FeedbackDesignEvidenceFact, ...]
    next_experiment: str
    blocked_by: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, Any]:
        return {
            "id": self.question_id,
            "evidence_family": self.evidence_family,
            "question": self.question,
            "related_design_variables": list(self.related_design_variables),
            "available_evidence": [item.as_payload() for item in self.available_evidence],
            "missing_evidence": [item.as_payload() for item in self.missing_evidence],
            "next_experiment": self.next_experiment,
            "blocked_by": list(self.blocked_by),
        }


@dataclass(frozen=True)
class FeedbackDesignFeedbackFacts:
    questions: tuple[FeedbackDesignQuestionFact, ...]
    contract_blockers: tuple[str, ...]

    @property
    def status(self) -> str:
        if self.contract_blockers:
            return "blocked"
        if not self.questions:
            return "blocked"
        if any(question.blocked_by for question in self.questions):
            return "incomplete"
        if any(question.missing_evidence for question in self.questions):
            return "incomplete"
        return "ready"

    def as_payload(self) -> dict[str, Any]:
        return {
            "contract_version": "1.1",
            "status": self.status,
            "questions": [question.as_payload() for question in self.questions],
        }


@dataclass(frozen=True)
class FeedbackCompatibilityFacts:
    workload: tuple[dict[str, Any], ...]
    runtime: tuple[dict[str, Any], ...]
    profiler: tuple[dict[str, Any], ...]
    evidence_readiness: tuple[dict[str, Any], ...]
    lineage: tuple[dict[str, Any], ...]

    @property
    def blocking_items(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            item
            for item in [*self.workload, *self.runtime, *self.profiler, *self.evidence_readiness]
            if item["status"] != "match"
        )

    @property
    def can_compare(self) -> bool:
        return not self.blocking_items

    @property
    def blocking_reasons(self) -> tuple[str, ...]:
        return tuple(f"{item['id']} {item['status']}" for item in self.blocking_items)

    def as_payload(self) -> dict[str, Any]:
        return {
            "can_compare": self.can_compare,
            "workload": [dict(item) for item in self.workload],
            "runtime": [dict(item) for item in self.runtime],
            "profiler": [dict(item) for item in self.profiler],
            "evidence_readiness": [dict(item) for item in self.evidence_readiness],
            "lineage": [dict(item) for item in self.lineage],
            "blocking_reasons": list(self.blocking_reasons),
        }


@dataclass(frozen=True)
class FeedbackSingleRunVerdictFacts:
    decision: str
    policy: str
    reasons: tuple[str, ...]

    def as_payload(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "policy": self.policy,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class FeedbackComparisonVerdictFacts:
    decision: str
    policy: str
    min_speedup_pct: float
    compatibility: FeedbackCompatibilityFacts
    baseline_mean_ms: float | None
    candidate_mean_ms: float | None
    baseline_runtime_ms: float | None
    candidate_runtime_ms: float | None
    baseline_runtime_statistic: str | None
    candidate_runtime_statistic: str | None
    runtime_delta_ms: float | None
    candidate_speedup_pct: float | None
    reasons: tuple[str, ...]

    def as_payload(self) -> dict[str, Any]:
        compatibility = self.compatibility.as_payload()
        return {
            "decision": self.decision,
            "policy": self.policy,
            "min_speedup_pct": self.min_speedup_pct,
            "can_compare": compatibility["can_compare"],
            "compatibility": compatibility,
            "baseline_mean_ms": self.baseline_mean_ms,
            "candidate_mean_ms": self.candidate_mean_ms,
            "baseline_runtime_ms": self.baseline_runtime_ms,
            "candidate_runtime_ms": self.candidate_runtime_ms,
            "baseline_runtime_statistic": self.baseline_runtime_statistic,
            "candidate_runtime_statistic": self.candidate_runtime_statistic,
            "runtime_delta_ms": self.runtime_delta_ms,
            "candidate_speedup_pct": self.candidate_speedup_pct,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class FeedbackEvidenceFacts:
    evidence: "RunEvidence"

    @property
    def summary_present(self) -> bool:
        return self.evidence.summary_present()

    @property
    def raw_artifact_index_present(self) -> bool:
        return isinstance(self.evidence.raw_artifact_index(), dict)

    @property
    def provenance_present(self) -> bool:
        return isinstance(self.evidence.provenance(), dict)

    @property
    def tilelang_context_present(self) -> bool:
        return isinstance(self.evidence.tilelang_context(), dict)

    @property
    def candidate_context_present(self) -> bool:
        return bool(self.evidence.candidate_context().context_sources)

    @property
    def simulator_present(self) -> bool:
        model = self.evidence.simulator_hotspots()
        return isinstance(model, dict) and bool(model.get("inputs"))

    def readiness_status(self) -> dict[str, Any]:
        return self.evidence.readiness_status()

    def readiness_level(self) -> str | None:
        return self.evidence.readiness_level()

    def readiness_at_least(self, minimum: str, order: dict[str, int]) -> bool:
        level = self.readiness_level()
        rank = order.get(level) if isinstance(level, str) else None
        return rank is not None and rank >= order[minimum]

    def material_evidence_families(self) -> list[str]:
        return self.evidence.material_evidence_families()

    def combined_pending_collection_actions(self) -> list[dict[str, Any]]:
        return self.evidence.combined_pending_collection_actions()

    def parsed_artifact_count(self) -> int:
        return self.evidence.parsed_raw_artifact_counts()[0]

    def raw_inventory_present(self) -> bool:
        return self.parsed_artifact_count() > 0

    def profiler_evidence_present(self) -> bool:
        return self.summary_present and self.raw_inventory_present()

    def profiler_evidence_status(self) -> dict[str, Any]:
        return self.evidence.profiler_evidence_status()

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

    def provenance_value(self, path: list[str]) -> Any:
        return _sourced_value(_context_value(self.evidence.provenance(), path))

    def provenance_payload_value(self, path: list[str]) -> Any:
        return _provenance_payload_value(_context_value(self.evidence.provenance(), path))

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

    def benchmark_reject_reasons(self, label: str = "candidate") -> list[str]:
        reasons = []
        if self.compiled_value() is False:
            reasons.append(f"{label} compiled=false")
        if self.correctness_passed() is False:
            reasons.append(f"{label} correctness failed")
        if self.benchmark_error() is not None:
            reasons.append(f"{label} benchmark error present")
        return reasons

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
        return isinstance(debug, dict) and debug.get("found") is True

    def collection_action_ids(self) -> list[str]:
        return [
            str(item.get("id") or "unknown")
            for item in self.combined_pending_collection_actions()
            if isinstance(item, dict) and item.get("necessity", "blocking") == "blocking"
        ]

    def single_run_contract_blockers(self) -> list[str]:
        blockers = []
        if self.compiled_value() is False:
            blockers.append("compile stage did not produce a runnable candidate")
        if self.correctness_passed() is False:
            blockers.append("correctness did not pass")
        if not self.summary_present:
            blockers.append("missing analysis/summary.json")
        if not self.candidate_context_present:
            blockers.append("missing canonical candidate context")
        if not self.raw_artifact_index_present:
            blockers.append("missing analysis/raw_artifact_index.json")
        elif not self.raw_inventory_present():
            blockers.append("missing parsed on-device profiler evidence")
        return blockers

    def candidate_comparability_question(
        self,
        *,
        source: str,
        blocked_by: list[str] | None = None,
    ) -> FeedbackDesignQuestionFact:
        available: list[FeedbackDesignEvidenceFact] = []
        missing: list[FeedbackDesignEvidenceFact] = []
        for field in FEEDBACK_WORKLOAD_COMPARABILITY_FIELDS:
            if self.workload_value(field) is None:
                missing.append(
                    _missing_feedback_evidence(
                        source=source,
                        artifact=TILELANG_CONTEXT_ARTIFACT,
                        field=field,
                        field_ref=f"benchmark.workload.{field}",
                        role="workload comparability field is missing",
                    )
                )
            else:
                available.append(self.evidence.context_feedback_evidence(source, f"workload.{field}", "workload comparability field"))
        if self.correctness_passed() is True:
            available.append(self.evidence.context_feedback_evidence(source, "correctness.passed", "correctness pass record"))
        else:
            missing.append(
                _missing_feedback_evidence(
                    source=source,
                    artifact=TILELANG_CONTEXT_ARTIFACT,
                    field="raw",
                    field_ref="benchmark.correctness.raw",
                    role="correctness pass record is missing",
                )
            )
        field_ref = self.runtime_evidence_field_ref()
        if field_ref is not None:
            available.append(self.evidence.context_feedback_evidence(source, "runtime.value_ms", "runtime evidence"))
        else:
            missing.append(
                _missing_feedback_evidence(
                    source=source,
                    artifact=TILELANG_CONTEXT_ARTIFACT,
                    field="mean_ms",
                    field_ref="benchmark.candidate.runtime_stats.mean_ms",
                    role="runtime evidence is missing",
                )
            )
        if self.provenance_present:
            for field_ref, role in [
                ("cann_version", "CANN version evidence"),
                ("hardware.summary", "hardware summary evidence"),
                ("profile_output_segments", "profile output segment evidence"),
            ]:
                value = self.provenance_value(field_ref.split("."))
                if value is not None:
                    available.append(
                        FeedbackDesignEvidenceFact(
                            source=source,
                            artifact="analysis/provenance.json",
                            field=field_ref.split(".")[-1],
                            field_ref=field_ref,
                            role=role,
                        )
                    )
                else:
                    missing.append(
                        _missing_feedback_evidence(
                            source=source,
                            artifact="analysis/provenance.json",
                            field=field_ref.split(".")[-1],
                            field_ref=field_ref,
                            role=f"{role} is missing",
                        )
                    )
        else:
            missing.append(
                _missing_feedback_evidence(
                    source=source,
                    artifact="analysis/provenance.json",
                    role="provenance evidence is missing",
                )
            )
        if self.summary_present:
            available.append(
                FeedbackDesignEvidenceFact(
                    source=source,
                    artifact="analysis/summary.json",
                    field="analysis_schema_version",
                    field_ref="analysis_schema_version",
                    role="analysis summary evidence",
                )
            )
        else:
            missing.append(
                _missing_feedback_evidence(
                    source=source,
                    artifact="analysis/summary.json",
                    field="analysis_schema_version",
                    field_ref="analysis_schema_version",
                    role="analysis summary evidence is missing",
                )
            )
        if self.raw_inventory_present():
            available.append(
                FeedbackDesignEvidenceFact(
                    source=source,
                    artifact="analysis/raw_artifact_index.json",
                    field="artifacts",
                    field_ref="artifacts[status=parsed]",
                    role="parsed raw artifact inventory",
                )
            )
        else:
            missing.append(
                _missing_feedback_evidence(
                    source=source,
                    artifact="analysis/raw_artifact_index.json",
                    field="artifacts",
                    field_ref="artifacts[status=parsed]",
                    role="parsed raw artifact inventory is missing",
                )
            )
        return _feedback_question(
            "candidate_comparability",
            "candidate_comparability",
            "Is the candidate evidence complete enough to compare one changed design variable against the baseline?",
            ("workload", "correctness", "provenance", "metric_scope", "raw_artifact_inventory"),
            available,
            missing,
            "Collect or align the missing workload, correctness, provenance, metric-scope, and raw-artifact evidence before comparing the design variable.",
            blocked_by,
        )

    def family_question(
        self,
        question_id: str,
        evidence_family: str,
        question: str,
        related_design_variables: tuple[str, ...],
        groups: set[str],
        *,
        source: str,
        required_artifacts: list[str],
        next_experiment: str,
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
            related_design_variables,
            available,
            missing,
            next_experiment,
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
            "Should the next inspection compare work distribution and launch shape context against the intended TileLang design variable?",
            ("work_distribution", "block_dim", "shape_specialization", "tail_work"),
            available,
            missing,
            "Collect OpBasicInfo.csv with matching TileLang workload context, then compare block/work-distribution fields against the intended design variable.",
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
            "Can the generated TileLang context guide source inspection after on-device evidence is available?",
            ("generated_source_context", "jit_configuration", "source_inspection_context"),
            available,
            missing,
            "Pair the generated TileLang source context with parsed on-device profiler artifacts before using it to guide source inspection.",
            blocked,
        )


@dataclass(frozen=True)
class CandidatePayloadFact:
    present: bool
    artifact: Any = None
    sha256: Any = None
    size_bytes: Any = None

    def as_summary(self) -> dict[str, Any]:
        if not self.present:
            return {"present": False}
        return {
            "present": True,
            "artifact": self.artifact,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class CandidateJitFact:
    config: Any
    debug: dict[str, Any] | None

    def as_summary(self) -> dict[str, Any]:
        return {"config": self.config, "debug": self.debug}


@dataclass(frozen=True)
class CandidateCorrectnessFact:
    compiled: bool | None
    passed: bool | None
    error: Any
    maxima: Any
    source: str | None

    def as_summary(self) -> dict[str, Any]:
        return {
            "compiled": self.compiled,
            "passed": self.passed,
            "error": self.error,
            "maxima": self.maxima,
            "source": self.source,
        }


@dataclass(frozen=True)
class CandidateRuntimeFact:
    value_ms: float | None
    statistic: str | None
    mean_ms: float | None
    samples_ms: tuple[float, ...]
    authority: Any
    latency_source: Any
    runtime: Any
    runtime_stats: Any
    ref_runtime: Any
    speedup: Any
    source: str | None

    def as_summary(self) -> dict[str, Any]:
        return {
            "value_ms": self.value_ms,
            "statistic": self.statistic,
            "mean_ms": self.mean_ms,
            "samples_ms": list(self.samples_ms),
            "authority": self.authority,
            "latency_source": self.latency_source,
            "runtime": self.runtime,
            "runtime_stats": self.runtime_stats,
            "ref_runtime": self.ref_runtime,
            "speedup": self.speedup,
            "source": self.source,
        }


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
class CandidateSummaryRunFacts:
    label: str
    run_dir: str
    artifacts: dict[str, str | None]
    workload: dict[str, Any]
    workload_evidence: dict[str, list[dict[str, Any]]]
    payload: CandidatePayloadFact
    jit: CandidateJitFact
    correctness: CandidateCorrectnessFact
    runtime: CandidateRuntimeFact
    profiler_evidence: dict[str, Any]
    context_sources: dict[str, CandidateContextSourceFact]

    def as_summary(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "run_dir": self.run_dir,
            "artifacts": self.artifacts,
            "workload": self.workload,
            "workload_evidence": self.workload_evidence,
            "payload": self.payload.as_summary(),
            "jit": self.jit.as_summary(),
            "correctness": self.correctness.as_summary(),
            "runtime": self.runtime.as_summary(),
            "profiler_evidence": self.profiler_evidence,
            "context_sources": {
                key: source.as_summary() for key, source in sorted(self.context_sources.items())
            },
        }


@dataclass(frozen=True)
class CandidateSummaryFacts:
    run: CandidateSummaryRunFacts
    inspection_targets: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]

    def inspection_target_summaries(self) -> list[dict[str, Any]]:
        return [dict(target) for target in self.inspection_targets]

    def warnings_list(self) -> list[str]:
        return list(self.warnings)


@dataclass(frozen=True)
class ComparisonFieldFact:
    id: str
    title: str
    value: Any
    order: int = 0


@dataclass(frozen=True)
class BenchmarkComparisonFacts:
    present: bool
    workload: tuple[ComparisonFieldFact, ...]
    runtime: tuple[ComparisonFieldFact, ...]
    correctness: tuple[ComparisonFieldFact, ...]
    payload: ComparisonFieldFact
    jit_config: ComparisonFieldFact


@dataclass(frozen=True)
class CompatibilityValueFact:
    value: Any
    source: dict[str, Any] | None
    status: str | None = None


@dataclass(frozen=True)
class CompatibilityFacts:
    cann_version: CompatibilityValueFact
    hardware_summary: CompatibilityValueFact
    profile_command: CompatibilityValueFact
    metric_scope: CompatibilityValueFact
    profile_output_segments: CompatibilityValueFact


@dataclass(frozen=True)
class ComparisonRunDescriptor:
    role: str
    label: str
    run_dir: str
    artifacts: dict[str, str | None]

    def as_summary(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "label": self.label,
            "run_dir": self.run_dir,
            "artifacts": self.artifacts,
        }


@dataclass(frozen=True)
class ComparisonRoleFacts:
    descriptor: ComparisonRunDescriptor
    compatibility: CompatibilityFacts
    benchmark: BenchmarkComparisonFacts
    headline_groups: frozenset[str]
    headline_records: dict[str, dict[str, Any]]
    evidence_status: dict[str, Any]
    warnings: tuple[str, ...]
    policy_evidence: "RunEvidence"

    def headline_record(self, group: str) -> dict[str, Any]:
        return self.headline_records.get(group, {"present": False})


@dataclass(frozen=True)
class ComparisonFacts:
    baseline: ComparisonRoleFacts
    candidate: ComparisonRoleFacts

    def run_summaries(self) -> dict[str, dict[str, Any]]:
        return {
            "a": self.baseline.descriptor.as_summary(),
            "b": self.candidate.descriptor.as_summary(),
        }

    def evidence_summaries(self) -> dict[str, dict[str, Any]]:
        return {
            "a": self.baseline.evidence_status,
            "b": self.candidate.evidence_status,
        }

    def labeled_warnings(self) -> list[str]:
        return [
            *(f"a: {warning}" for warning in self.baseline.warnings),
            *(f"b: {warning}" for warning in self.candidate.warnings),
        ]

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
    diagnosis_headlines: tuple[tuple[str, HeadlineFact], ...]
    analysis_artifacts: tuple[str, ...]
    caveats: tuple[str, ...]
    profile_context_rows: tuple[ReportTableRowFact, ...]
    tilelang_context_rows: tuple[ReportTableRowFact, ...]
    analysis_dimensions: tuple[dict[str, Any], ...]
    evidence_readiness: dict[str, Any]
    evidence_relations: tuple[dict[str, Any], ...]
    correlation_headlines: tuple[tuple[str, HeadlineFact], ...]
    section_headlines: tuple[tuple[str, tuple[HeadlineFact, ...]], ...]
    pending_collection_actions: tuple[dict[str, Any], ...]
    simulator_hotspots: ReportSimulatorHotspotFacts


class RunEvidence:
    """Small interface over analysis artifacts for one run directory."""

    def __init__(
        self,
        run_dir: Path,
        summary: dict[str, Any] | None,
        raw_artifact_index: dict[str, Any] | None,
        provenance: dict[str, Any] | None,
        tilelang_context: dict[str, Any] | None,
        profile_context: dict[str, Any] | None,
        simulator_hotspots: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        self.run_dir = Path(run_dir)
        self._summary_present = isinstance(summary, dict)
        self._summary = summary if isinstance(summary, dict) else {}
        self._raw_artifact_index = raw_artifact_index
        self._provenance = provenance
        self._tilelang_context = tilelang_context
        self._profile_context = profile_context
        self._simulator_hotspots = simulator_hotspots
        self._warnings = tuple(warnings or [])

    @classmethod
    def load(cls, run_dir: Path) -> "RunEvidence":
        run_dir = Path(run_dir)
        summary = _load_required_json_object(run_dir / "analysis" / "summary.json")
        warnings: list[str] = []
        raw_artifact_index = _load_optional_json_object(run_dir, "raw_artifact_index.json", warnings)
        provenance = _load_optional_json_object(run_dir, "provenance.json", warnings)
        tilelang_context = _load_optional_json_object(run_dir, "tilelang_context.json", warnings)
        profile_context = _load_optional_json_object(run_dir, "profile_context.json", warnings)
        return cls(
            run_dir,
            summary,
            raw_artifact_index,
            provenance,
            tilelang_context,
            profile_context,
            None,
            warnings,
        )

    @classmethod
    def load_candidate_summary(cls, run_dir: Path) -> "RunEvidence":
        """Load best-effort evidence for candidate summary output."""

        run_dir = Path(run_dir)
        warnings: list[str] = []
        summary = _load_candidate_summary_json(run_dir, warnings)
        raw_artifact_index = _load_optional_json_object(run_dir, "raw_artifact_index.json", warnings, warn_missing=False)
        provenance = _load_optional_json_object(run_dir, "provenance.json", warnings, warn_missing=False)
        tilelang_context = _load_optional_json_object(run_dir, "tilelang_context.json", warnings, warn_missing=False)
        profile_context = _load_optional_json_object(run_dir, "profile_context.json", warnings, warn_missing=False)
        simulator_hotspots = _load_optional_json_object(run_dir, "simulator_hotspots.json", warnings, warn_missing=False)
        return cls(
            run_dir,
            summary,
            raw_artifact_index,
            provenance,
            tilelang_context,
            profile_context,
            simulator_hotspots,
            warnings,
        )

    @classmethod
    def from_loaded(
        cls,
        run_dir: Path,
        summary: dict[str, Any] | None,
        *,
        raw_artifact_index: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        tilelang_context: dict[str, Any] | None = None,
        profile_context: dict[str, Any] | None = None,
        simulator_hotspots: dict[str, Any] | None = None,
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
    def load_report(cls, run_dir: Path, summary: dict[str, Any]) -> "RunEvidence":
        run_dir = Path(run_dir)
        warnings: list[str] = []
        return cls(
            run_dir,
            summary,
            _load_optional_json_object(run_dir, "raw_artifact_index.json", warnings, warn_missing=False),
            _load_optional_json_object(run_dir, "provenance.json", warnings, warn_missing=False),
            _load_optional_json_object(run_dir, "tilelang_context.json", warnings, warn_missing=False),
            _load_optional_json_object(run_dir, "profile_context.json", warnings, warn_missing=False),
            _load_optional_json_object(run_dir, "simulator_hotspots.json", warnings, warn_missing=False),
            warnings,
        )

    @classmethod
    def from_report_inputs(
        cls,
        run_dir: Path,
        summary: dict[str, Any],
        *,
        provenance: dict[str, Any] | None = None,
        tilelang_context: dict[str, Any] | None = None,
        profile_context: dict[str, Any] | None = None,
    ) -> "RunEvidence":
        run_dir = Path(run_dir)
        warnings: list[str] = []
        return cls(
            run_dir,
            summary,
            _load_optional_json_object(run_dir, "raw_artifact_index.json", warnings, warn_missing=False),
            provenance,
            tilelang_context,
            profile_context,
            _load_optional_json_object(run_dir, "simulator_hotspots.json", warnings, warn_missing=False),
            warnings,
        )

    def warnings(self) -> list[str]:
        return list(self._warnings)

    def feedback_facts(self) -> FeedbackEvidenceFacts:
        return FeedbackEvidenceFacts(self)

    def single_run_design_feedback_facts(self, *, source: str = "run") -> FeedbackDesignFeedbackFacts:
        facts = self.feedback_facts()
        contract_blockers = facts.single_run_contract_blockers()
        compiled = facts.compiled_value()
        passed = facts.correctness_passed()
        hard_blocked = compiled is False or passed is False
        if hard_blocked:
            available: list[FeedbackDesignEvidenceFact] = []
            missing = [
                _missing_feedback_evidence(
                    source=source,
                    artifact=TILELANG_CONTEXT_ARTIFACT,
                    field="raw",
                    field_ref="benchmark.correctness.raw",
                    role="correctness pass is required before profiler design questions",
                ),
                _missing_feedback_evidence(
                    source=source,
                    artifact="analysis/raw_artifact_index.json",
                    field="artifacts",
                    field_ref="artifacts[status=parsed]",
                    role="parsed profiler evidence is required after correctness passes",
                ),
            ]
            if compiled is not None:
                available.append(_context_feedback_evidence(source, "benchmark.candidate.compiled", "compile status"))
            else:
                missing.insert(
                    0,
                    _missing_feedback_evidence(
                        source=source,
                        artifact=TILELANG_CONTEXT_ARTIFACT,
                        field="compiled",
                        field_ref="benchmark.candidate.compiled",
                        role="compile status is missing",
                    ),
                )
            return FeedbackDesignFeedbackFacts(
                questions=(
                    _feedback_question(
                        "missing_evidence",
                        "missing_evidence",
                        "Which required candidate evidence is missing before design feedback can be asked?",
                        ("compile_status", "correctness", "profiler_evidence"),
                        available,
                        missing,
                        "Fix compile or correctness collection first, then collect on-device profiler evidence for the same workload.",
                        contract_blockers,
                    ),
                ),
                contract_blockers=tuple(contract_blockers),
            )

        questions = [
            facts.candidate_comparability_question(source=source),
            facts.family_question(
                "memory_cache",
                "memory_cache",
                "Should the next inspection compare memory movement or cache context for the changed design variable?",
                ("memory_movement", "cache_context", "metric_scope"),
                {"memory", "l2_cache"},
                source=source,
                required_artifacts=["Memory.csv", "MemoryL0.csv", "MemoryUB.csv", "L2Cache.csv"],
                next_experiment="Collect the Default metric follow-up artifacts containing Memory.csv, MemoryL0.csv, MemoryUB.csv, and L2Cache.csv for the same workload.",
            ),
            facts.family_question(
                "pipe_arithmetic",
                "pipe_arithmetic",
                "Should the next inspection compare Cube, Vector, Scalar, or MTE path mix against the intended generated code?",
                ("pipe_mix", "arithmetic_mix", "generated_code_path"),
                {"pipe_utilization", "arithmetic_utilization"},
                source=source,
                required_artifacts=["PipeUtilization.csv", "ArithmeticUtilization.csv"],
                next_experiment="Collect PipeUtilization.csv and ArithmeticUtilization.csv for the same workload before comparing path mix.",
            ),
            facts.opbasic_workload_question(source=source),
        ]
        if facts.jit_debug_found() or facts.simulator_present:
            questions.append(facts.generated_context_question(source=source))
        return FeedbackDesignFeedbackFacts(tuple(questions), tuple(contract_blockers))

    @staticmethod
    def comparison_design_feedback_facts(
        baseline: "RunEvidence",
        candidate: "RunEvidence",
        compatibility: dict[str, Any] | None,
    ) -> FeedbackDesignFeedbackFacts:
        a_facts = baseline.feedback_facts()
        b_facts = candidate.feedback_facts()
        contract_blockers = _comparison_contract_blockers(compatibility, a_facts, b_facts)
        questions: list[FeedbackDesignQuestionFact] = [
            _comparison_candidate_comparability_question(a_facts, b_facts, contract_blockers)
        ]
        if not contract_blockers:
            questions.extend(
                [
                    _comparison_family_question(
                        "memory_cache",
                        "memory_cache",
                        "Should the next inspection compare memory movement or cache context between the two runs for the changed design variable?",
                        ("memory_movement", "cache_context", "metric_scope"),
                        a_facts,
                        b_facts,
                        {"memory", "l2_cache"},
                        required_artifacts=["Memory.csv", "MemoryL0.csv", "MemoryUB.csv", "L2Cache.csv"],
                        next_experiment="Collect matching memory/cache follow-up artifacts for both runs, then compare the cited fields under the same metric scope.",
                    ),
                    _comparison_family_question(
                        "pipe_arithmetic",
                        "pipe_arithmetic",
                        "Should the next inspection compare Cube, Vector, Scalar, or MTE path mix between the two runs?",
                        ("pipe_mix", "arithmetic_mix", "generated_code_path"),
                        a_facts,
                        b_facts,
                        {"pipe_utilization", "arithmetic_utilization"},
                        required_artifacts=["PipeUtilization.csv", "ArithmeticUtilization.csv"],
                        next_experiment="Collect matching pipe and arithmetic utilization artifacts for both runs before comparing path mix.",
                    ),
                    _comparison_opbasic_workload_question(a_facts, b_facts),
                ]
            )
            if a_facts.jit_debug_found() or b_facts.jit_debug_found():
                questions.append(_comparison_pipeline_expression_question(a_facts, b_facts))
                questions.append(_comparison_generated_context_question(a_facts, b_facts))
        return FeedbackDesignFeedbackFacts(tuple(questions), tuple(contract_blockers))

    def single_run_feedback_verdict(self) -> FeedbackSingleRunVerdictFacts:
        facts = self.feedback_facts()
        reject_reasons = facts.benchmark_reject_reasons()
        if reject_reasons:
            return FeedbackSingleRunVerdictFacts("reject", "single_run_v1", tuple(reject_reasons))

        reasons = []
        if not facts.summary_present:
            reasons.append("missing analysis/summary.json")
        if not facts.workload_present():
            reasons.append("candidate workload context is missing")
        if facts.correctness_passed() is not True:
            reasons.append("correctness pass is not recorded")
        if facts.runtime_value_ms() is None:
            reasons.append("candidate runtime is missing")
        if not facts.profiler_evidence_present():
            reasons.append("profiler evidence is missing")
        if facts.summary_present:
            if not facts.readiness_status()["present"]:
                reasons.append("evidence readiness is missing")
            elif not facts.readiness_at_least(FEEDBACK_MIN_COMPARISON_READINESS_LEVEL, FEEDBACK_READINESS_LEVEL_ORDER):
                reasons.append(
                    "evidence readiness level "
                    f"{facts.readiness_level() or 'unknown'} is below {FEEDBACK_MIN_COMPARISON_READINESS_LEVEL}"
                )
        action_ids = facts.collection_action_ids()
        if action_ids:
            reasons.append("pending collection actions: " + ", ".join(action_ids))

        if reasons:
            return FeedbackSingleRunVerdictFacts("inconclusive", "single_run_v1", tuple(reasons))
        return FeedbackSingleRunVerdictFacts(
            "keep",
            "single_run_v1",
            (
                "correctness passed, runtime is present, profiler evidence is directional or better, "
                "and no required collection action is pending",
            ),
        )

    @staticmethod
    def feedback_verdict_compatibility(
        baseline: "RunEvidence",
        candidate: "RunEvidence",
    ) -> FeedbackCompatibilityFacts:
        a_facts = baseline.feedback_facts()
        b_facts = candidate.feedback_facts()
        workload_checks = RunEvidence.workload_checks(baseline, candidate)
        runtime_checks = (
            _compatibility_item("runtime.statistic", a_facts.runtime_statistic(), b_facts.runtime_statistic()),
            _optional_compatibility_item("runtime.authority", a_facts.runtime_authority(), b_facts.runtime_authority()),
            _optional_compatibility_item(
                "runtime.latency_source",
                a_facts.runtime_latency_source(),
                b_facts.runtime_latency_source(),
            ),
        )
        profiler_checks = (
            _compatibility_item(
                "cann_version",
                a_facts.provenance_value(["cann_version"]),
                b_facts.provenance_value(["cann_version"]),
            ),
            _compatibility_item(
                "hardware_summary",
                a_facts.provenance_value(["hardware", "summary"]),
                b_facts.provenance_value(["hardware", "summary"]),
            ),
            _optional_compatibility_item(
                "profile_command",
                a_facts.provenance_value(["profile_command"]),
                b_facts.provenance_value(["profile_command"]),
            ),
            _compatibility_item("metric_scope", a_facts.metric_scope_value(), b_facts.metric_scope_value()),
            _compatibility_item(
                "profile_output_segments",
                a_facts.provenance_payload_value(["profile_output_segments"]),
                b_facts.provenance_payload_value(["profile_output_segments"]),
            ),
        )
        if any(run.comparison_compatibility().cann_version.status == "conflict" for run in (baseline, candidate)):
            profiler_checks[0]["status"] = "conflict"
        readiness_checks = (
            _readiness_level_compatibility_item(a_facts, b_facts),
            _readiness_family_compatibility_item(a_facts, b_facts),
            _readiness_followup_compatibility_item(a_facts, b_facts),
        )
        lineage = (
            _compatibility_item("payload.sha256", a_facts.payload_sha256(), b_facts.payload_sha256()),
            _compatibility_item("jit_config", a_facts.jit_config(), b_facts.jit_config()),
        )
        return FeedbackCompatibilityFacts(workload_checks, runtime_checks, profiler_checks, readiness_checks, lineage)

    @staticmethod
    def comparison_feedback_verdict(
        baseline: "RunEvidence",
        candidate: "RunEvidence",
        *,
        min_speedup_pct: float = 1.0,
    ) -> FeedbackComparisonVerdictFacts:
        min_speedup_pct = _normalize_feedback_min_speedup_pct(min_speedup_pct)
        compatibility = RunEvidence.feedback_verdict_compatibility(baseline, candidate)
        a_facts = baseline.feedback_facts()
        b_facts = candidate.feedback_facts()
        baseline_ms = a_facts.runtime_value_ms()
        candidate_ms = b_facts.runtime_value_ms()
        baseline_statistic = a_facts.runtime_statistic()
        candidate_statistic = b_facts.runtime_statistic()
        common_statistic = baseline_statistic if baseline_statistic == candidate_statistic else None
        runtime_label = (
            "selected"
            if common_statistic in {None, "", "unspecified"}
            else " ".join(str(common_statistic).replace("_", " ").split())
        )
        runtime_label = runtime_label or "selected"
        speedup_pct = None
        delta_ms = None
        if baseline_ms is not None and candidate_ms is not None:
            delta_ms = candidate_ms - baseline_ms
            if baseline_ms != 0:
                speedup_pct = (baseline_ms - candidate_ms) / abs(baseline_ms) * 100.0

        reject_reasons = [
            *a_facts.benchmark_reject_reasons("baseline"),
            *b_facts.benchmark_reject_reasons("candidate"),
        ]
        if reject_reasons:
            decision = "reject"
            reasons = reject_reasons
        elif not compatibility.can_compare:
            decision = "inconclusive"
            reasons = ["incompatible runs: " + ", ".join(compatibility.blocking_reasons)]
        elif not a_facts.profiler_evidence_present() or not b_facts.profiler_evidence_present():
            decision = "inconclusive"
            reasons = ["profiler evidence is missing"]
        elif a_facts.correctness_passed() is not True or b_facts.correctness_passed() is not True:
            decision = "inconclusive"
            reasons = ["baseline and candidate correctness passes are not both recorded"]
        elif baseline_ms is None or candidate_ms is None or speedup_pct is None:
            decision = "inconclusive"
            reasons = ["comparable runtime is missing"]
        elif speedup_pct >= min_speedup_pct:
            decision = "promote"
            reasons = [f"candidate {runtime_label} runtime improves by {speedup_pct:.6g}%"]
        elif speedup_pct <= -min_speedup_pct:
            decision = "reject"
            reasons = [f"candidate {runtime_label} runtime regresses by {-speedup_pct:.6g}%"]
        else:
            decision = "inconclusive"
            reasons = [f"runtime change is inside +/-{min_speedup_pct:.6g}% threshold"]

        return FeedbackComparisonVerdictFacts(
            decision=decision,
            policy="baseline_v1",
            min_speedup_pct=min_speedup_pct,
            compatibility=compatibility,
            baseline_mean_ms=a_facts.runtime_mean_ms(),
            candidate_mean_ms=b_facts.runtime_mean_ms(),
            baseline_runtime_ms=baseline_ms,
            candidate_runtime_ms=candidate_ms,
            baseline_runtime_statistic=a_facts.runtime_statistic(),
            candidate_runtime_statistic=b_facts.runtime_statistic(),
            runtime_delta_ms=delta_ms,
            candidate_speedup_pct=speedup_pct,
            reasons=tuple(reasons),
        )

    def summary(self) -> dict[str, Any]:
        return self._summary

    def summary_present(self) -> bool:
        return self._summary_present

    def provenance(self) -> dict[str, Any] | None:
        return self._provenance

    def tilelang_context(self) -> dict[str, Any] | None:
        return self._tilelang_context

    def profile_context(self) -> dict[str, Any] | None:
        return self._profile_context

    def simulator_hotspots(self) -> dict[str, Any] | None:
        return self._simulator_hotspots

    def raw_artifact_index(self) -> dict[str, Any] | None:
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
        headlines = self._summary.get("headlines")
        if not isinstance(headlines, dict):
            return "Ascend profiling run"
        for group in TARGET_HEADLINE_ORDER:
            item = headlines.get(group)
            if isinstance(item, dict) and item.get("name"):
                return str(item["name"])
        return "Ascend profiling run"

    def metric_scope(self) -> MetricScopeFact | None:
        scope = self._summary.get("metric_scope")
        if not isinstance(scope, dict) or not scope.get("value"):
            return None
        return MetricScopeFact(
            value=str(scope.get("value")),
            artifact=str(scope.get("artifact") or "analysis/summary.json"),
            field_ref=str(scope.get("field_ref") or "metric_scope.value"),
        )

    def comparison_metric_scope(self) -> tuple[Any, dict[str, Any] | None]:
        scope = self.metric_scope()
        if scope is None:
            return None, None
        return scope.value, {"artifact": scope.artifact, "field": scope.field_ref}

    def headline_records(self) -> list[HeadlineFact]:
        rows: list[HeadlineFact] = []
        headlines = self._summary.get("headlines")
        if not isinstance(headlines, dict):
            return rows
        for group, label in HEADLINE_GROUPS:
            fact = self.headline_record(group, label)
            if fact is not None:
                rows.append(fact)
        return rows

    def headline_record(self, group: str, label: str | None = None) -> HeadlineFact | None:
        headlines = self._summary.get("headlines")
        if not isinstance(headlines, dict):
            return None
        item = headlines.get(group)
        if not isinstance(item, dict):
            return None
        return HeadlineFact(
            group=group,
            label=label,
            name=item.get("name"),
            value=item.get("value"),
            field=item.get("field"),
            field_kind=item.get("field_kind"),
            artifact=str(item.get("file") or "missing"),
            segment=item.get("segment"),
            metric_scope=item.get("metric_scope"),
            field_ref=headline_field_reference(group, item),
            raw_value_field_ref=raw_value_field_reference(group, item),
        )

    def comparison_headline_record(self, group: str) -> dict[str, Any]:
        fact = self.headline_record(group)
        if fact is None:
            return {"present": False}
        item = self._headline_item(group) or {}
        row = _dict_or_empty(item.get("first_row" if group == "op_basic_info" else "raw_row"))
        identity = _dict_or_empty(self._summary.get("target_identity"))
        if "segments" in identity:
            identity = _dict_or_empty(_dict_or_empty(identity["segments"]).get(fact.segment))
        return {
            "present": True,
            "name": fact.name,
            "value": fact.value,
            "field": fact.field,
            "field_kind": fact.field_kind,
            "artifact": fact.artifact,
            "segment": fact.segment,
            "metric_scope": fact.metric_scope,
            "target_identity": identity,
            "block_scope": {
                normalized_key(key): value
                for key, value in row.items()
                if normalized_key(key) in {"blockid", "subblockid"}
            } if row else None,
        }

    def headline_group_names(self) -> set[str]:
        headlines = self._summary.get("headlines")
        if not isinstance(headlines, dict):
            return set()
        return {str(name) for name in headlines}

    def headline_rows(self) -> list[tuple[str, str, Any, str]]:
        rows = []
        for fact in self.headline_records():
            label = fact.label or fact.group
            source = f"`{fact.artifact}`; `{fact.field_ref}`"
            rows.append((label, fact.signal, fact.value, source))
        return rows

    def launch_metadata(self) -> LaunchMetadataFact | None:
        item = self._headline_item("op_basic_info")
        if item is None:
            return None
        row = item.get("first_row")
        if not isinstance(row, dict) or not row:
            return None
        normalized = {str(key).strip().lower(): str(key) for key in row}
        fields = []
        for wanted in ("Op Type", "Block Dim", "Mix Block Dim", "Current Freq", "Rated Freq"):
            field = normalized.get(wanted.strip().lower())
            if not field:
                continue
            value = row.get(field)
            if value in (None, ""):
                continue
            fields.append((field, value))
        if not fields:
            return None
        return LaunchMetadataFact(
            artifact=str(item.get("file") or "missing"),
            fields=tuple(fields),
        )

    def diagnosis_headlines(self) -> list[tuple[str, HeadlineFact]]:
        rows = []
        for group, label in (
            ("op_summary", "Highest application-level operator duration"),
            ("task_time", "Highest device task duration"),
        ):
            fact = self.headline_record(group)
            if fact is not None:
                rows.append((label, fact))
        return rows

    def section_headlines(self, groups: list[str] | tuple[str, ...]) -> list[HeadlineFact]:
        rows = []
        for group in groups:
            fact = self.headline_record(group)
            if fact is not None:
                rows.append(fact)
        return rows

    def correlation_headlines(self, groups: list[tuple[str, str]] | tuple[tuple[str, str], ...]) -> list[tuple[str, HeadlineFact]]:
        rows = []
        for label, group in groups:
            fact = self.headline_record(group)
            if fact is None:
                return []
            rows.append((label, fact))
        return rows

    def analysis_dimensions(self) -> list[dict[str, Any]]:
        dimensions = self._summary.get("analysis_dimensions")
        if not isinstance(dimensions, list):
            return []
        return [item for item in dimensions if isinstance(item, dict)]

    def evidence_relations(self) -> list[dict[str, Any]]:
        relations = self._summary.get("evidence_relations")
        if not isinstance(relations, list):
            return []
        return [item for item in relations if isinstance(item, dict)]

    def evidence_readiness(self) -> dict[str, Any]:
        readiness = self._summary.get("evidence_readiness")
        return readiness if isinstance(readiness, dict) else {}

    def readiness_status(self) -> dict[str, Any]:
        readiness = self.evidence_readiness()
        followups = self.readiness_followups()
        return {
            "present": bool(readiness),
            "level": self.readiness_level(),
            "available_evidence_families": self.readiness_list("available_evidence_families"),
            "missing_evidence_families": self.readiness_list("missing_evidence_families"),
            "material_evidence_families": self.material_evidence_families(),
            "recommended_followups": followups,
        }

    def readiness_level(self) -> str | None:
        level = self.evidence_readiness().get("level")
        return level if isinstance(level, str) else None

    def readiness_list(self, key: str) -> list[Any]:
        value = self.evidence_readiness().get(key)
        return value if isinstance(value, list) else []

    def readiness_followups(self) -> list[dict[str, Any]]:
        return [item for item in self.readiness_list("recommended_followups") if isinstance(item, dict)]

    def material_evidence_families(self) -> list[str]:
        families = self.readiness_list("available_evidence_families")
        material = {str(item) for item in families if str(item) in MATERIAL_EVIDENCE_FAMILIES}
        return sorted(material)

    def pending_collection_actions(self) -> list[dict[str, Any]]:
        return self.next_collection_actions()

    def combined_pending_collection_actions(self) -> list[dict[str, Any]]:
        actions = []
        seen: set[str] = set()
        for item in [*self.next_collection_actions(), *self.readiness_followups()]:
            action_id = str(item.get("id") or "unknown")
            if action_id in seen:
                continue
            seen.add(action_id)
            actions.append(item)
        return actions

    def next_collection_actions(self) -> list[dict[str, Any]]:
        actions = self._summary.get("next_collection_actions")
        if not isinstance(actions, list):
            return []
        return [action for action in actions if isinstance(action, dict)]

    def summary_warnings(self) -> list[Any]:
        warnings = self._summary.get("warnings")
        return warnings if isinstance(warnings, list) else []

    def optimization_direction_count(self) -> int:
        directions = self._summary.get("optimization_directions")
        return len(directions) if isinstance(directions, list) else 0

    def raw_artifacts(self) -> list[RawArtifactFact]:
        if not isinstance(self._raw_artifact_index, dict):
            return []
        artifacts = self._raw_artifact_index.get("artifacts")
        if not isinstance(artifacts, list):
            return []
        rows: list[RawArtifactFact] = []
        for item in artifacts:
            if not isinstance(item, dict):
                rows.append(
                    RawArtifactFact(
                        index=None,
                        artifact=None,
                        group=None,
                        parser=None,
                        segment=None,
                        metric_scope=None,
                        status="malformed",
                        row_count=None,
                        columns=(),
                        warnings=("raw artifact entry is not a JSON object",),
                    )
                )
                continue
            warnings = item.get("warnings")
            columns = item.get("columns")
            rows.append(
                RawArtifactFact(
                    index=len(rows),
                    artifact=_str_or_none(item.get("artifact")),
                    group=_str_or_none(item.get("group")),
                    parser=_str_or_none(item.get("parser")),
                    segment=_str_or_none(item.get("segment")),
                    metric_scope=item.get("metric_scope"),
                    status=_str_or_none(item.get("status")),
                    row_count=item.get("row_count"),
                    columns=tuple(columns) if isinstance(columns, list) else (),
                    warnings=tuple(warnings if isinstance(warnings, list) else []),
                    canonical_stem=_str_or_none(item.get("canonical_stem")),
                    launch_key=_str_or_none(item.get("launch_key")),
                    target_name=_str_or_none(item.get("target_name")),
                    normalized_target_name=_str_or_none(item.get("normalized_target_name")),
                )
            )
        return rows

    def raw_artifact_summary(self) -> RawArtifactSummary:
        if not isinstance(self._raw_artifact_index, dict):
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
        raw_warnings = self._raw_artifact_index.get("warnings")
        if isinstance(raw_warnings, list):
            warnings.extend(str(item) for item in raw_warnings)
        for fact in artifacts:
            warnings.extend(str(item) for item in fact.warnings)
        return RawArtifactSummary(
            present=True,
            schema_version=self._raw_artifact_index.get("raw_artifact_index_schema_version"),
            artifact_count=len(artifacts),
            parsed_count=status_counts.get("parsed", 0),
            status_counts=dict(sorted(status_counts.items())),
            group_counts=dict(sorted(group_counts.items())),
            segment_counts=dict(sorted(segment_counts.items())),
            warnings=tuple(warnings),
        )

    def raw_artifact_index_summary(self) -> dict[str, Any]:
        if not isinstance(self._raw_artifact_index, dict):
            return {"present": False}
        artifacts = self.raw_artifacts()
        group_counts = Counter(fact.group or "unknown" for fact in artifacts)
        status_counts = Counter(fact.status or "unknown" for fact in artifacts)
        segment_counts = Counter(fact.segment or "unknown" for fact in artifacts)
        raw_warnings = self._raw_artifact_index.get("warnings")
        return {
            "present": True,
            "schema_version": self._raw_artifact_index.get("raw_artifact_index_schema_version"),
            "artifact_count": len(artifacts),
            "group_counts": dict(sorted(group_counts.items())),
            "status_counts": dict(sorted(status_counts.items())),
            "segment_counts": dict(sorted(segment_counts.items())),
            "warnings": raw_warnings if isinstance(raw_warnings, list) else [],
        }

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
            or segment_receipt_allows_evidence(self.run_dir, fact.segment)
        ]

    def parsed_required_artifacts(
        self,
        groups: set[str],
        required_artifacts: list[str],
    ) -> tuple[list[RawArtifactFact], list[str], set[str]]:
        required_by_stem = {Path(artifact).stem: artifact for artifact in required_artifacts}
        present_by_stem: dict[str, RawArtifactFact] = {}
        allowed_keys: set[str] = set()
        coverage = self._summary.get("profile_coverage") if isinstance(self._summary, dict) else None
        selected = coverage.get("selected_segments_by_family") if isinstance(coverage, dict) else None
        explicit_target = bool(coverage.get("explicit_target")) if isinstance(coverage, dict) else False
        for fact in self.parsed_raw_artifacts_by_group(groups):
            canonical_stem = fact.canonical_stem or _canonical_operator_stem(fact.artifact)
            if canonical_stem not in required_by_stem:
                continue
            family = REQUIRED_STEM_FAMILY.get(canonical_stem)
            selected_segment = selected.get(family) if isinstance(selected, dict) and family else None
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
        coverage = self._summary.get("profile_coverage") if isinstance(self._summary, dict) else None
        if not isinstance(coverage, dict) or not coverage.get("explicit_target"):
            return []
        segments = coverage.get("segments")
        if not isinstance(segments, dict):
            return []
        present = []
        for fact in self._parsed_scoped_artifacts(groups, required_artifacts):
            canonical_stem = fact.canonical_stem or _canonical_operator_stem(fact.artifact)
            family = REQUIRED_STEM_FAMILY.get(canonical_stem or "")
            segment = segments.get(fact.segment) if fact.segment else None
            family_coverage = (segment.get("metric_coverage") or {}).get(family) if isinstance(segment, dict) else None
            if (
                not isinstance(segment, dict)
                or segment.get("count_complete") is not True
                or not isinstance(family_coverage, dict)
                or family_coverage.get("complete") is not True
            ):
                continue
            present.append(fact)
        return present

    def _parsed_scoped_artifacts(
        self,
        groups: set[str],
        required_artifacts: list[str],
    ) -> list[RawArtifactFact]:
        coverage = self._summary.get("profile_coverage") if isinstance(self._summary, dict) else None
        if not isinstance(coverage, dict) or not coverage.get("explicit_target"):
            return []
        segments = coverage.get("segments")
        if not isinstance(segments, dict):
            return []
        required_stems = {Path(artifact).stem for artifact in required_artifacts}
        present: dict[tuple[str, str], RawArtifactFact] = {}
        for fact in self.parsed_raw_artifacts_by_group(groups):
            canonical_stem = fact.canonical_stem or _canonical_operator_stem(fact.artifact)
            segment = segments.get(fact.segment) if fact.segment else None
            target_scope = segment.get("target_scope") if isinstance(segment, dict) else None
            if (
                canonical_stem not in required_stems
                or not isinstance(target_scope, dict)
                or target_scope.get("kind") != "focused_subset"
            ):
                continue
            present.setdefault((str(fact.segment), canonical_stem), fact)
        return list(present.values())

    def _complete_program_target_scope(self) -> dict[str, Any] | None:
        coverage = self._summary.get("profile_coverage") if isinstance(self._summary, dict) else None
        if not isinstance(coverage, dict) or not coverage.get("explicit_target"):
            return None
        return {
            "kind": "complete_program",
            "kernel_selector": coverage.get("kernel_selector"),
            "expected_counts": coverage.get("expected_counts") or {},
            "expected_total": coverage.get("expected_total"),
        }

    def target_scope_for_segment(self, segment: str | None) -> dict[str, Any] | None:
        coverage = self._summary.get("profile_coverage")
        segments = coverage.get("segments") if isinstance(coverage, dict) else None
        item = segments.get(segment) if isinstance(segments, dict) and segment else None
        scope = item.get("target_scope") if isinstance(item, dict) else None
        if isinstance(scope, dict):
            return scope
        if isinstance(coverage, dict) and coverage.get("explicit_target") and segment:
            return {"kind": "complete_program"}
        return None

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
            signals = dimension.get("signals")
            if not isinstance(signals, list):
                continue
            for signal in signals:
                if not isinstance(signal, dict) or str(signal.get("group") or "") not in groups:
                    continue
                if not _artifact_matches_keys(signal.get("artifact"), allowed_artifact_keys):
                    continue
                out.append(
                    SummarySignalFact(
                        group=_str_or_none(signal.get("group")),
                        artifact=signal.get("artifact"),
                        field=signal.get("field"),
                        field_ref=signal.get("field_ref"),
                        segment=signal.get("segment"),
                        metric_scope=signal.get("metric_scope"),
                    )
                )
                if len(out) >= limit:
                    return out
        for group in sorted(groups):
            item = self._headline_item(group)
            if item is None:
                continue
            artifact = item.get("file") or "analysis/summary.json"
            if not _artifact_matches_keys(artifact, allowed_artifact_keys):
                continue
            out.append(
                SummarySignalFact(
                    group=group,
                    artifact=artifact,
                    field=item.get("field"),
                    field_ref=item.get("field_ref") or f"headlines.{group}",
                    segment=item.get("segment"),
                    metric_scope=item.get("metric_scope"),
                )
            )
            if len(out) >= limit:
                return out
        return out

    def profiler_evidence_status(self) -> dict[str, Any]:
        parsed_count, group_counts, segment_counts = self.parsed_raw_artifact_counts()
        return {
            "summary_present": self._summary_present,
            "raw_artifact_index_present": isinstance(self._raw_artifact_index, dict),
            "parsed_artifact_count": parsed_count,
            "parsed_group_counts": group_counts,
            "parsed_segment_counts": segment_counts,
            "headline_groups": sorted(self.headline_group_names()),
            "optimization_direction_count": self.optimization_direction_count(),
            "next_collection_actions": self.next_collection_actions(),
            "pending_collection_actions": self.combined_pending_collection_actions(),
            "evidence_readiness": self.readiness_status(),
            "measurement_quality": self._summary.get("measurement_quality") or {},
            "evidence_present": self._summary_present and parsed_count > 0,
        }

    def summary_evidence(self) -> dict[str, Any]:
        return {
            "summary_warnings": self.summary_warnings(),
            "next_collection_actions": self.next_collection_actions(),
            "pending_collection_actions": self.combined_pending_collection_actions(),
            "evidence_readiness": self.readiness_status(),
            "measurement_quality": self._summary.get("measurement_quality") or {},
            "raw_artifact_index": self.raw_artifact_index_summary(),
        }

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
            benchmark=self.comparison_benchmark(),
            headline_groups=frozenset(headline_groups),
            headline_records={
                group: self.comparison_headline_record(group)
                for group in headline_groups
            },
            evidence_status=self.summary_evidence(),
            warnings=tuple(self.comparison_warnings()),
            policy_evidence=self,
        )

    def comparison_warnings(self) -> list[str]:
        return [
            warning
            for warning in self.warnings()
            if "analysis/profile_context.json" not in warning
        ]

    def _comparison_artifact_presence(self) -> dict[str, str | None]:
        presence = self.artifact_presence()
        return {
            "summary": presence["summary"],
            "provenance": presence["provenance"],
            "tilelang_context": presence["tilelang_context"],
            "raw_artifact_index": presence["raw_artifact_index"],
        }

    def candidate_summary_facts(self) -> CandidateSummaryFacts:
        candidate = self.candidate_context()
        return CandidateSummaryFacts(
            run=CandidateSummaryRunFacts(
                label=self.run_dir.name,
                run_dir=_run_display(self.run_dir),
                artifacts=self._candidate_summary_artifact_presence(),
                workload=candidate.workload,
                workload_evidence=candidate.workload_evidence,
                payload=candidate.payload,
                jit=candidate.jit,
                correctness=candidate.correctness,
                runtime=candidate.runtime,
                profiler_evidence=self.profiler_evidence_status(),
                context_sources=candidate.context_sources,
            ),
            inspection_targets=tuple(
                [*self._candidate_direction_targets(), *self._candidate_simulator_targets()]
            ),
            warnings=tuple(self._warnings),
        )

    def _candidate_summary_artifact_presence(self) -> dict[str, str | None]:
        presence = self.artifact_presence()
        return {
            "summary": presence["summary"],
            "provenance": presence["provenance"],
            "tilelang_context": presence["tilelang_context"],
            "raw_artifact_index": presence["raw_artifact_index"],
            "simulator_hotspots": presence["simulator_hotspots"],
        }

    def _candidate_direction_targets(self) -> list[dict[str, Any]]:
        directions = self._summary.get("optimization_directions")
        if not isinstance(directions, list):
            return []
        out = []
        for item in directions:
            if not isinstance(item, dict):
                continue
            target = {
                "source": "optimization_directions",
                "id": item.get("id"),
                "rank": item.get("rank"),
                "title": item.get("title"),
                "action": item.get("action"),
                "impact_basis": item.get("impact_basis"),
                "confidence": item.get("confidence"),
                "effort": item.get("effort"),
                "evidence": item.get("evidence") if isinstance(item.get("evidence"), list) else [],
            }
            if isinstance(item.get("experiment_hint"), dict):
                target["experiment_hint"] = item["experiment_hint"]
            out.append(target)
        return out

    def _candidate_simulator_targets(self, limit: int = 3) -> list[dict[str, Any]]:
        simulator = self._simulator_hotspots
        if not isinstance(simulator, dict):
            return []
        out = []
        for key, kind in [
            ("source_lines", "source_line"),
            ("instructions", "instruction"),
            ("pipeline_events", "pipeline_event"),
        ]:
            rows = simulator.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows[:limit]:
                if not isinstance(row, dict):
                    continue
                evidence_id = row.get("evidence_id") or f"simulator.{kind}.{len(out) + 1}"
                target = {
                    "source": "simulator_hotspots",
                    "kind": kind,
                    "id": evidence_id,
                    "rank": row.get("rank"),
                    "artifact": row.get("artifact"),
                    "field": row.get("field"),
                    "field_ref": row.get("field_ref"),
                    "value": row.get("value") if row.get("value") is not None else row.get("duration"),
                    "source_file": row.get("source_file"),
                    "line": row.get("line"),
                    "instruction": row.get("instr") or row.get("instruction"),
                }
                if kind == "source_line" and isinstance(row.get("source_context"), dict):
                    target["source_context"] = row.get("source_context")
                out.append(target)
        return out

    def candidate_context(self) -> CandidateContextFacts:
        sources: dict[str, CandidateContextSourceFact] = {}

        def select(key: str, candidates: list[tuple[dict[str, Any] | None, list[str], str, str]]) -> Any:
            for context, path, artifact, role in candidates:
                value = _context_value(context, path)
                if _has_context_value(value):
                    sources[key] = CandidateContextSourceFact(artifact, ".".join(path), role)
                    return value
            return None

        tile = self._tilelang_context
        profile = self._profile_context
        tile_role = "tilelang_benchmark_context"
        profile_role = "caller_context_not_profiler_evidence"
        raw_role = "caller_owned_acceptance_context_not_profiler_evidence"
        workload: dict[str, Any] = {}
        raw_workload = ["verify_context", "raw", "workload"]
        workload_evidence: dict[str, list[dict[str, Any]]] = {}
        for field in FEEDBACK_WORKLOAD_COMPARABILITY_FIELDS:
            raw_path = [*raw_workload, field]
            if field == "id":
                raw_path = [*raw_workload, "task_name"]
            candidates = [
                    (tile, ["benchmark", "workload", field], TILELANG_CONTEXT_ARTIFACT, tile_role),
                    (profile, ["benchmark", "workload", field], PROFILE_CONTEXT_ARTIFACT, profile_role),
                    (profile, raw_path, PROFILE_CONTEXT_ARTIFACT, raw_role),
                ]
            if field == "case_count":
                candidates.append((profile, ["verify_context", "raw", "correctness", "receipt", "case_count"], PROFILE_CONTEXT_ARTIFACT, raw_role))
            observations = []
            for context, path, artifact, role in candidates:
                value = _context_value(context, path)
                if _has_context_value(value):
                    source = CandidateContextSourceFact(artifact, ".".join(path), role)
                    observations.append({"value": value, "source": source.as_summary()})
                    sources.setdefault(f"workload.{field}", source)
            workload_evidence[field] = observations
            if observations and all(_feedback_values_match(observations[0]["value"], item["value"]) for item in observations):
                workload[field] = observations[0]["value"]

        payload = _context_value(tile, ["sources", "payload"])
        if isinstance(payload, dict):
            sources["payload"] = CandidateContextSourceFact(TILELANG_CONTEXT_ARTIFACT, "sources.payload", tile_role)
        jit_debug = _context_value(tile, ["jit_debug"])
        jit_config = select(
            "jit.config",
            [
                (tile, ["benchmark", "jit_config"], TILELANG_CONTEXT_ARTIFACT, tile_role),
                (profile, ["benchmark", "jit_config"], PROFILE_CONTEXT_ARTIFACT, profile_role),
            ],
        )

        compiled = select(
            "correctness.compiled",
            [
                (tile, ["benchmark", "candidate", "compiled"], TILELANG_CONTEXT_ARTIFACT, tile_role),
                (profile, ["benchmark", "candidate", "compiled"], PROFILE_CONTEXT_ARTIFACT, profile_role),
                (profile, ["verify_context", "raw", "candidate", "compiled"], PROFILE_CONTEXT_ARTIFACT, raw_role),
            ],
        )
        passed, passed_source = _select_candidate_correctness(tile, profile)
        if passed_source is not None:
            sources["correctness.passed"] = passed_source
        maxima = select(
            "correctness.maxima",
            [
                (tile, ["benchmark", "correctness", "maxima"], TILELANG_CONTEXT_ARTIFACT, tile_role),
                (profile, ["benchmark", "correctness", "maxima"], PROFILE_CONTEXT_ARTIFACT, profile_role),
            ],
        ) or []
        error = select(
            "correctness.error",
            [
                (tile, ["benchmark", "candidate", "error"], TILELANG_CONTEXT_ARTIFACT, tile_role),
                (profile, ["benchmark", "candidate", "error"], PROFILE_CONTEXT_ARTIFACT, profile_role),
                (profile, ["verify_context", "raw", "candidate", "error"], PROFILE_CONTEXT_ARTIFACT, raw_role),
            ],
        )
        if error in (None, "", [], {}):
            error = None

        runtime_fact, runtime_sources = _select_candidate_runtime(tile, profile)
        sources.update(runtime_sources)

        debug: dict[str, Any] | None
        if isinstance(jit_debug, dict):
            debug = {
                "found": jit_debug.get("found"),
                "provided": jit_debug.get("provided"),
                "artifact_count": jit_debug.get("artifact_count", len(jit_debug.get("artifacts") or [])),
                "artifacts": jit_debug.get("artifacts") or [],
            }
        else:
            debug = None

        return CandidateContextFacts(
            workload=workload if isinstance(workload, dict) else {},
            workload_evidence=workload_evidence,
            payload=CandidatePayloadFact(
                present=isinstance(payload, dict),
                artifact=payload.get("artifact") if isinstance(payload, dict) else None,
                sha256=payload.get("sha256") if isinstance(payload, dict) else None,
                size_bytes=payload.get("size_bytes") if isinstance(payload, dict) else None,
            ),
            jit=CandidateJitFact(
                config=jit_config,
                debug=debug,
            ),
            correctness=CandidateCorrectnessFact(
                compiled=compiled if isinstance(compiled, bool) else None,
                passed=passed,
                error=error,
                maxima=maxima,
                source=passed_source.artifact if passed_source is not None else None,
            ),
            runtime=runtime_fact,
            context_sources=sources,
        )

    @staticmethod
    def workload_checks(baseline: "RunEvidence", candidate: "RunEvidence") -> tuple[dict[str, Any], ...]:
        a_context, b_context = baseline.candidate_context(), candidate.candidate_context()
        checks = []
        for field in FEEDBACK_WORKLOAD_COMPARABILITY_FIELDS:
            check = _compatibility_item(f"workload.{field}", a_context.workload.get(field), b_context.workload.get(field))
            check["sources"] = {"a": a_context.workload_evidence[field], "b": b_context.workload_evidence[field]}
            if any(context.workload_evidence[field] and field not in context.workload for context in (a_context, b_context)):
                check["status"] = "conflict"
            checks.append(check)
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

    def comparison_benchmark(self) -> BenchmarkComparisonFacts:
        candidate = self.candidate_context()
        runtime_stats = (
            candidate.runtime.runtime_stats
            if isinstance(candidate.runtime.runtime_stats, dict)
            else {}
        )
        maxima_by_field = _maxima_by_field(candidate.correctness.maxima)
        workload = tuple(
            ComparisonFieldFact(
                id=f"workload.{field}",
                title=f"Workload {field}",
                value=candidate.workload.get(field),
                order=order,
            )
            for order, field in enumerate(["id", "shape", "dtype", "case_count"])
        )
        runtime = (
            ComparisonFieldFact("candidate.runtime.value_ms", "Selected runtime ms", candidate.runtime.value_ms, 0),
            ComparisonFieldFact("candidate.runtime.statistic", "Runtime statistic", candidate.runtime.statistic, 1),
            ComparisonFieldFact("candidate.runtime.authority", "Runtime authority", candidate.runtime.authority, 2),
            ComparisonFieldFact("candidate.runtime", "Candidate runtime", candidate.runtime.runtime, 3),
            ComparisonFieldFact("candidate.ref_runtime", "Reference runtime", candidate.runtime.ref_runtime, 1),
            ComparisonFieldFact("candidate.speedup", "Speedup", candidate.runtime.speedup, 2),
            *(
                ComparisonFieldFact(
                    id=f"candidate.runtime_stats.{field}",
                    title=f"Runtime stat {field}",
                    value=runtime_stats.get(field),
                    order=1000,
                )
                for field in sorted(runtime_stats)
            ),
        )
        correctness = (
            ComparisonFieldFact("correctness.passed", "Correctness passed", candidate.correctness.passed, 0),
            *(
                ComparisonFieldFact(
                    id=f"correctness.maxima.{field}",
                    title=f"Correctness maximum {field}",
                    value=maxima_by_field.get(field),
                    order=1000,
                )
                for field in sorted(maxima_by_field)
            ),
        )
        return BenchmarkComparisonFacts(
            present=bool(candidate.context_sources),
            workload=workload,
            runtime=runtime,
            correctness=correctness,
            payload=ComparisonFieldFact(
                "payload.sha256",
                "Payload sha256",
                candidate.payload.sha256,
            ),
            jit_config=ComparisonFieldFact(
                "jit_config",
                "JIT config",
                candidate.jit.config,
            ),
        )

    def comparison_compatibility(self) -> CompatibilityFacts:
        provenance = self._provenance if isinstance(self._provenance, dict) else {}
        hardware = provenance.get("hardware")
        hardware = hardware if isinstance(hardware, dict) else {}
        scope = self.metric_scope()
        return CompatibilityFacts(
            cann_version=_compatibility_value(provenance.get("cann_version")),
            hardware_summary=_compatibility_value(hardware.get("summary")),
            profile_command=_compatibility_value(provenance.get("profile_command")),
            metric_scope=CompatibilityValueFact(
                value=scope.value if scope is not None else None,
                source={"artifact": scope.artifact, "field": scope.field_ref} if scope is not None else None,
            ),
            profile_output_segments=CompatibilityValueFact(
                value=provenance.get("profile_output_segments"),
                source={"artifact": "analysis/provenance.json", "field": "profile_output_segments"}
                if self._provenance
                else None,
            ),
        )

    def report_profile_context_rows(self) -> tuple[ReportTableRowFact, ...]:
        context = self._profile_context
        if not context:
            return ()

        profile_harness = _dict_or_empty(context.get("profile_harness"))
        benchmark = _dict_or_empty(context.get("benchmark"))
        workload = _dict_or_empty(benchmark.get("workload"))
        candidate = _dict_or_empty(benchmark.get("candidate"))
        correctness = _dict_or_empty(benchmark.get("correctness"))
        sources = _dict_or_empty(context.get("sources"))
        rows: list[ReportTableRowFact] = []

        manifest_source = sources.get("profile_harness_manifest")
        if isinstance(manifest_source, dict):
            rows.extend(
                [
                    _report_row(
                        "Harness manifest",
                        manifest_source.get("artifact"),
                        PROFILE_CONTEXT_ARTIFACT,
                        "sources.profile_harness_manifest.artifact",
                    ),
                    _report_row(
                        "Harness manifest sha256",
                        manifest_source.get("sha256"),
                        PROFILE_CONTEXT_ARTIFACT,
                        "sources.profile_harness_manifest.sha256",
                    ),
                ]
            )
        application_source = sources.get("application")
        if isinstance(application_source, dict):
            rows.extend(
                [
                    _report_row(
                        "Application",
                        application_source.get("artifact"),
                        PROFILE_CONTEXT_ARTIFACT,
                        "sources.application.artifact",
                    ),
                    _report_row(
                        "Application sha256",
                        application_source.get("sha256"),
                        PROFILE_CONTEXT_ARTIFACT,
                        "sources.application.sha256",
                    ),
                ]
            )

        harness_workload = profile_harness.get("workload")
        if _has_report_value(harness_workload):
            rows.append(
                _report_row("Harness workload", harness_workload, PROFILE_CONTEXT_ARTIFACT, "profile_harness.workload")
            )
        jit_config = profile_harness.get("jit_config")
        if _has_report_value(jit_config):
            rows.append(
                _report_row("Harness JIT config", jit_config, PROFILE_CONTEXT_ARTIFACT, "profile_harness.jit_config")
            )

        verify_json = sources.get("verify_json")
        if isinstance(verify_json, dict) and verify_json:
            rows.extend(
                [
                    _report_row(
                        "Verify JSON",
                        verify_json.get("artifact"),
                        PROFILE_CONTEXT_ARTIFACT,
                        "sources.verify_json.artifact",
                    ),
                    _report_row("Workload id", workload.get("id"), PROFILE_CONTEXT_ARTIFACT, "benchmark.workload.id"),
                    _report_row("Shape", workload.get("shape"), PROFILE_CONTEXT_ARTIFACT, "benchmark.workload.shape"),
                    _report_row("Dtype", workload.get("dtype"), PROFILE_CONTEXT_ARTIFACT, "benchmark.workload.dtype"),
                    _report_row(
                        "Case count",
                        workload.get("case_count"),
                        PROFILE_CONTEXT_ARTIFACT,
                        "benchmark.workload.case_count",
                    ),
                    _report_row(
                        "Compiled",
                        candidate.get("compiled"),
                        PROFILE_CONTEXT_ARTIFACT,
                        "benchmark.candidate.compiled",
                    ),
                    _report_row(
                        "Candidate runtime",
                        candidate.get("runtime"),
                        PROFILE_CONTEXT_ARTIFACT,
                        "benchmark.candidate.runtime",
                    ),
                    _report_row(
                        "Runtime stats",
                        candidate.get("runtime_stats"),
                        PROFILE_CONTEXT_ARTIFACT,
                        "benchmark.candidate.runtime_stats",
                    ),
                    _report_row(
                        "Reference runtime",
                        candidate.get("ref_runtime"),
                        PROFILE_CONTEXT_ARTIFACT,
                        "benchmark.candidate.ref_runtime",
                    ),
                    _report_row(
                        "Speedup",
                        candidate.get("speedup"),
                        PROFILE_CONTEXT_ARTIFACT,
                        "benchmark.candidate.speedup",
                    ),
                    _report_row(
                        "Correctness maxima",
                        _report_maxima_text(correctness.get("maxima")),
                        PROFILE_CONTEXT_ARTIFACT,
                        "benchmark.correctness.maxima",
                    ),
                ]
            )
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
                "Speedup",
                candidate.runtime.speedup,
                "runtime.speedup",
                "benchmark.candidate.speedup",
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
        if jit_debug:
            artifacts = jit_debug.get("artifacts") or []
            if jit_debug.get("found"):
                preview = ", ".join(str(item.get("artifact")) for item in artifacts[:5] if isinstance(item, dict))
                if len(artifacts) > 5:
                    preview = f"{preview}, ..."
                value = f"{jit_debug.get('artifact_count', len(artifacts))} files"
                if preview:
                    value = f"{value}: {preview}"
            else:
                value = "not found"
            rows.append(_report_row("JIT debug artifacts", value, TILELANG_CONTEXT_ARTIFACT, "jit_debug.artifacts"))
        return tuple(rows)

    def report_setup_context(self) -> ReportSetupFacts:
        return ReportSetupFacts(
            application_text=self._report_application_text(),
            workload_text=self._report_workload_text(),
        )

    def report_setup_metadata(self) -> ReportSetupMetadataFacts:
        provenance = self._provenance if isinstance(self._provenance, dict) else None
        hardware = _dict_or_empty(provenance.get("hardware") if provenance else None)
        return ReportSetupMetadataFacts(
            hardware_text=_report_sourced_text(hardware.get("summary"), "Ascend 910B"),
            cann_text=_report_sourced_text(
                provenance.get("cann_version") if provenance else None,
                "not recorded by this helper",
            ),
            profile_date_text=_report_sourced_text(
                provenance.get("profile_date") if provenance else None,
                "not recorded by this helper",
            ),
            profile_command_text=_report_sourced_text(
                provenance.get("profile_command") if provenance else None,
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
        warnings = self._summary.get("warnings")
        for warning in warnings if isinstance(warnings, list) else []:
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
        out.extend(_report_warning_caveats("Provenance warning", self._provenance))
        out.extend(_report_warning_caveats("TileLang context warning", self._tilelang_context))
        out.extend(_report_warning_caveats("Profile context warning", self._profile_context))
        return out

    def _report_application_text(self) -> str:
        context = self._profile_context
        if context:
            sources = _dict_or_empty(context.get("sources"))
            manifest = sources.get("profile_harness_manifest")
            application = _dict_or_empty(sources.get("application"))
            if isinstance(manifest, dict) and manifest.get("artifact"):
                return (
                    f"profile harness manifest `{manifest.get('artifact')}` and application "
                    f"`{application.get('artifact', 'not recorded')}` "
                    "(source: `analysis/profile_context.json`; `sources.profile_harness_manifest.artifact`, "
                    "`sources.application.artifact`)."
                )
            if application.get("artifact"):
                return (
                    f"application `{application.get('artifact')}` "
                    "(source: `analysis/profile_context.json`; `sources.application.artifact`)."
                )
            return "recorded in `analysis/profile_context.json`."
        return self._report_tilelang_payload_text()

    def _report_workload_text(self) -> str:
        context = self._profile_context
        if not context:
            return self._report_tilelang_setup_shape()
        benchmark_workload = _dict_or_empty(_context_value(context, ["benchmark", "workload"]))
        if benchmark_workload:
            shape = _report_fmt_compact(benchmark_workload.get("shape"))
            dtype = _report_fmt_compact(benchmark_workload.get("dtype"))
            case_count = _report_fmt_compact(benchmark_workload.get("case_count"))
            return (
                f"{shape}, dtype {dtype}, cases {case_count} "
                "(context only; source: `analysis/profile_context.json`; `benchmark.workload`)."
            )
        harness_workload = _context_value(context, ["profile_harness", "workload"])
        if _has_report_value(harness_workload):
            return (
                f"{_report_fmt_compact(harness_workload)} "
                "(context only; source: `analysis/profile_context.json`; `profile_harness.workload`)."
            )
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

    def _headline_item(self, group: str) -> dict[str, Any] | None:
        headlines = self._summary.get("headlines")
        if not isinstance(headlines, dict):
            return None
        item = headlines.get(group)
        return item if isinstance(item, dict) else None


def _load_required_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RunEvidenceError(f"missing {path}; run ascend-msprof analyze first")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
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
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        warnings.append(f"invalid analysis/summary.json: {exc}")
        return None
    if not isinstance(value, dict):
        warnings.append("analysis/summary.json is not a JSON object")
        return None
    return value


def _load_optional_json_object(
    run_dir: Path,
    name: str,
    warnings: list[str],
    *,
    warn_missing: bool = True,
) -> dict[str, Any] | None:
    path = run_dir / "analysis" / name
    if not path.exists():
        if warn_missing:
            warnings.append(f"missing analysis/{name}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        warnings.append(f"invalid analysis/{name}: {exc}")
        return None
    if not isinstance(value, dict):
        warnings.append(f"analysis/{name} is not a JSON object")
        return None
    return value


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _context_value(context: dict[str, Any] | None, path: list[str]) -> Any:
    value: Any = context
    for part in path:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _has_context_value(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _candidate_source(artifact: str, field_ref: str, role: str) -> CandidateContextSourceFact:
    return CandidateContextSourceFact(artifact=artifact, field_ref=field_ref, evidence_role=role)


def _explicit_correctness_value(
    context: dict[str, Any] | None,
    path: list[str],
    *,
    artifact: str,
    role: str,
) -> tuple[bool | None, CandidateContextSourceFact | None]:
    raw = _context_value(context, path)
    if isinstance(raw, bool):
        return raw, _candidate_source(artifact, ".".join(path), role)
    if not isinstance(raw, dict):
        return None, None
    for key in ["passed", "correctness_ok", "tolerance_passed"]:
        value = raw.get(key)
        if isinstance(value, bool):
            return value, _candidate_source(artifact, ".".join([*path, key]), role)
    return None, None


def _select_candidate_correctness(
    tile: dict[str, Any] | None,
    profile: dict[str, Any] | None,
) -> tuple[bool | None, CandidateContextSourceFact | None]:
    candidates = [
        (tile, ["benchmark", "correctness", "raw"], TILELANG_CONTEXT_ARTIFACT, "tilelang_benchmark_context"),
        (profile, ["benchmark", "correctness", "raw"], PROFILE_CONTEXT_ARTIFACT, "caller_context_not_profiler_evidence"),
        (
            profile,
            ["verify_context", "raw", "correctness"],
            PROFILE_CONTEXT_ARTIFACT,
            "caller_owned_acceptance_context_not_profiler_evidence",
        ),
    ]
    for context, path, artifact, role in candidates:
        value, source = _explicit_correctness_value(context, path, artifact=artifact, role=role)
        if source is not None:
            return value, source
    return None, None


def _finite_samples(value: Any) -> tuple[float, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(number for item in value if (number := _try_float(item)) is not None)


def _runtime_from_benchmark_context(
    context: dict[str, Any] | None,
    *,
    artifact: str,
    role: str,
) -> tuple[CandidateRuntimeFact | None, dict[str, CandidateContextSourceFact]]:
    stats = _context_value(context, ["benchmark", "candidate", "runtime_stats"])
    stats_dict = stats if isinstance(stats, dict) else {}
    value_ms = _try_float(stats_dict.get("value_ms"))
    statistic = stats_dict.get("statistic")
    statistic_field = "statistic"
    if not _has_context_value(statistic):
        statistic = stats_dict.get("aggregation")
        statistic_field = "aggregation"
    value_field_ref = "benchmark.candidate.runtime_stats.value_ms"
    statistic_field_ref = f"benchmark.candidate.runtime_stats.{statistic_field}"
    mean_ms = _try_float(stats_dict.get("mean_ms"))
    if value_ms is None and mean_ms is not None:
        value_ms = mean_ms
        statistic = "mean"
        value_field_ref = "benchmark.candidate.runtime_stats.mean_ms"
        statistic_field_ref = value_field_ref
    runtime = _context_value(context, ["benchmark", "candidate", "runtime"])
    if value_ms is None:
        value_ms = _try_float(runtime)
        if value_ms is not None:
            statistic = str(statistic or "legacy_runtime")
            value_field_ref = "benchmark.candidate.runtime"
            if statistic == "legacy_runtime":
                statistic_field_ref = value_field_ref
            if statistic in {"mean", "legacy_runtime"}:
                mean_ms = value_ms
    if value_ms is None:
        return None, {}
    statistic_text = str(statistic or "unspecified")
    if statistic_text == "unspecified":
        statistic_field_ref = value_field_ref
    if statistic_text != "mean" and statistic_text != "legacy_runtime":
        mean_ms = None
    samples = _finite_samples(stats_dict.get("samples_ms"))
    fact = CandidateRuntimeFact(
        value_ms=value_ms,
        statistic=statistic_text,
        mean_ms=mean_ms,
        samples_ms=samples,
        authority=stats_dict.get("authority"),
        latency_source=stats_dict.get("latency_source"),
        runtime=runtime,
        runtime_stats=stats,
        ref_runtime=_context_value(context, ["benchmark", "candidate", "ref_runtime"]),
        speedup=_context_value(context, ["benchmark", "candidate", "speedup"]),
        source=artifact,
    )
    sources = {
        "runtime.value_ms": _candidate_source(artifact, value_field_ref, role),
        "runtime.statistic": _candidate_source(artifact, statistic_field_ref, role),
    }
    raw_fields = {
        "runtime.runtime": (runtime, "benchmark.candidate.runtime"),
        "runtime.runtime_stats": (stats, "benchmark.candidate.runtime_stats"),
        "runtime.ref_runtime": (fact.ref_runtime, "benchmark.candidate.ref_runtime"),
        "runtime.speedup": (fact.speedup, "benchmark.candidate.speedup"),
    }
    for key, (value, field_ref) in raw_fields.items():
        if _has_context_value(value):
            sources[key] = _candidate_source(artifact, field_ref, role)
    for key in ["samples_ms", "authority", "latency_source"]:
        if key in stats_dict:
            sources[f"runtime.{key}"] = _candidate_source(
                artifact,
                f"benchmark.candidate.runtime_stats.{key}",
                role,
            )
    return fact, sources


def _select_candidate_runtime(
    tile: dict[str, Any] | None,
    profile: dict[str, Any] | None,
) -> tuple[CandidateRuntimeFact, dict[str, CandidateContextSourceFact]]:
    for context, artifact, role in [
        (tile, TILELANG_CONTEXT_ARTIFACT, "tilelang_benchmark_context"),
        (profile, PROFILE_CONTEXT_ARTIFACT, "caller_context_not_profiler_evidence"),
    ]:
        fact, sources = _runtime_from_benchmark_context(context, artifact=artifact, role=role)
        if fact is not None:
            return fact, sources

    official = _context_value(profile, ["verify_context", "raw", "official_timing"])
    if isinstance(official, dict):
        value_ms = _try_float(official.get("latency_ms"))
        if value_ms is not None:
            statistic = str(official.get("aggregation") or "unspecified")
            mean_ms = value_ms if statistic == "mean" else None
            official_prefix = "verify_context.raw.official_timing"
            statistic_field = "aggregation" if "aggregation" in official else "latency_ms"
            sources = {
                "runtime.value_ms": _candidate_source(
                    PROFILE_CONTEXT_ARTIFACT,
                    f"{official_prefix}.latency_ms",
                    "caller_owned_acceptance_context_not_profiler_evidence",
                ),
                "runtime.statistic": _candidate_source(
                    PROFILE_CONTEXT_ARTIFACT,
                    f"{official_prefix}.{statistic_field}",
                    "caller_owned_acceptance_context_not_profiler_evidence",
                ),
                "runtime.runtime": _candidate_source(
                    PROFILE_CONTEXT_ARTIFACT,
                    f"{official_prefix}.latency_ms",
                    "caller_owned_acceptance_context_not_profiler_evidence",
                ),
                "runtime.runtime_stats": _candidate_source(
                    PROFILE_CONTEXT_ARTIFACT,
                    official_prefix,
                    "caller_owned_acceptance_context_not_profiler_evidence",
                ),
            }
            for key in ["samples_ms", "authority", "latency_source"]:
                if key in official:
                    sources[f"runtime.{key}"] = _candidate_source(
                        PROFILE_CONTEXT_ARTIFACT,
                        f"{official_prefix}.{key}",
                        "caller_owned_acceptance_context_not_profiler_evidence",
                    )
            return (
                CandidateRuntimeFact(
                    value_ms=value_ms,
                    statistic=statistic,
                    mean_ms=mean_ms,
                    samples_ms=_finite_samples(official.get("samples_ms")),
                    authority=official.get("authority"),
                    latency_source=official.get("latency_source"),
                    runtime=value_ms,
                    runtime_stats={
                        "value_ms": value_ms,
                        "statistic": statistic,
                        "samples_ms": official.get("samples_ms"),
                        "authority": official.get("authority"),
                        "latency_source": official.get("latency_source"),
                    },
                    ref_runtime=None,
                    speedup=None,
                    source=PROFILE_CONTEXT_ARTIFACT,
                ),
                sources,
            )

    return (
        CandidateRuntimeFact(
            value_ms=None,
            statistic=None,
            mean_ms=None,
            samples_ms=(),
            authority=None,
            latency_source=None,
            runtime=None,
            runtime_stats=None,
            ref_runtime=None,
            speedup=None,
            source=None,
        ),
        {},
    )


def _try_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _feedback_sanitize_json_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, int):
        return value
    if isinstance(value, list):
        return [_feedback_sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _feedback_sanitize_json_value(item) for key, item in value.items()}
    return value


def _feedback_json_equal_value(value: Any) -> str:
    return json.dumps(_feedback_sanitize_json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _feedback_values_match(a_value: Any, b_value: Any) -> bool:
    return _feedback_json_equal_value(a_value) == _feedback_json_equal_value(b_value)


def _normalize_feedback_min_speedup_pct(value: float) -> float:
    threshold = _try_float(value)
    if threshold is None or threshold < 0:
        raise ValueError("--min-speedup-pct must be a finite non-negative number")
    return threshold


def _feedback_question(
    question_id: str,
    evidence_family: str,
    question: str,
    related_design_variables: tuple[str, ...],
    available_evidence: list[FeedbackDesignEvidenceFact],
    missing_evidence: list[FeedbackDesignEvidenceFact],
    next_experiment: str,
    blocked_by: list[str] | None = None,
) -> FeedbackDesignQuestionFact:
    return FeedbackDesignQuestionFact(
        question_id=question_id,
        evidence_family=evidence_family,
        question=question,
        related_design_variables=related_design_variables,
        available_evidence=tuple(available_evidence),
        missing_evidence=tuple(missing_evidence),
        next_experiment=next_experiment,
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


def _comparison_candidate_comparability_question(
    a_facts: FeedbackEvidenceFacts,
    b_facts: FeedbackEvidenceFacts,
    contract_blockers: list[str],
) -> FeedbackDesignQuestionFact:
    a_question = a_facts.candidate_comparability_question(source="a")
    b_question = b_facts.candidate_comparability_question(source="b")
    return _feedback_question(
        "candidate_comparability",
        "candidate_comparability",
        "Are both runs complete enough to compare one changed design variable under the same workload and profiler scope?",
        ("workload", "correctness", "provenance", "metric_scope", "raw_artifact_inventory"),
        [*a_question.available_evidence, *b_question.available_evidence],
        [*a_question.missing_evidence, *b_question.missing_evidence],
        "Collect or align the missing evidence on the named branch before comparing the design variable.",
        contract_blockers,
    )


def _comparison_family_question(
    question_id: str,
    evidence_family: str,
    question: str,
    related_design_variables: tuple[str, ...],
    a_facts: FeedbackEvidenceFacts,
    b_facts: FeedbackEvidenceFacts,
    groups: set[str],
    *,
    required_artifacts: list[str],
    next_experiment: str,
) -> FeedbackDesignQuestionFact:
    a_question = a_facts.family_question(
        question_id,
        evidence_family,
        question,
        related_design_variables,
        groups,
        source="a",
        required_artifacts=required_artifacts,
        next_experiment=next_experiment,
    )
    b_question = b_facts.family_question(
        question_id,
        evidence_family,
        question,
        related_design_variables,
        groups,
        source="b",
        required_artifacts=required_artifacts,
        next_experiment=next_experiment,
    )
    return _feedback_question(
        question_id,
        evidence_family,
        question,
        related_design_variables,
        [*a_question.available_evidence, *b_question.available_evidence],
        [*a_question.missing_evidence, *b_question.missing_evidence],
        next_experiment,
        [*_prefix_feedback_blockers("a", a_question.blocked_by), *_prefix_feedback_blockers("b", b_question.blocked_by)],
    )


def _comparison_opbasic_workload_question(
    a_facts: FeedbackEvidenceFacts,
    b_facts: FeedbackEvidenceFacts,
) -> FeedbackDesignQuestionFact:
    question = "Should the next inspection compare work distribution and launch shape context between the two runs?"
    next_experiment = "Collect OpBasicInfo.csv and complete workload context for both runs before comparing work distribution."
    a_question = a_facts.opbasic_workload_question(source="a")
    b_question = b_facts.opbasic_workload_question(source="b")
    return _feedback_question(
        "opbasic_workload",
        "opbasic_workload",
        question,
        ("work_distribution", "block_dim", "shape_specialization", "tail_work"),
        [*a_question.available_evidence, *b_question.available_evidence],
        [*a_question.missing_evidence, *b_question.missing_evidence],
        next_experiment,
        [*_prefix_feedback_blockers("a", a_question.blocked_by), *_prefix_feedback_blockers("b", b_question.blocked_by)],
    )


def _comparison_generated_context_question(
    a_facts: FeedbackEvidenceFacts,
    b_facts: FeedbackEvidenceFacts,
) -> FeedbackDesignQuestionFact:
    a_available, a_missing, a_blocked = a_facts.generated_context_records(source="a")
    b_available, b_missing, b_blocked = b_facts.generated_context_records(source="b")
    return _feedback_question(
        "generated_context",
        "generated_context",
        "Can both generated TileLang contexts guide source inspection after on-device evidence is available?",
        ("generated_source_context", "jit_configuration", "source_inspection_context"),
        [*a_available, *b_available],
        [*a_missing, *b_missing],
        "Pair generated TileLang source context from both runs with parsed on-device profiler artifacts before using it to guide source inspection.",
        [*_prefix_feedback_blockers("a", a_blocked), *_prefix_feedback_blockers("b", b_blocked)],
    )


def _comparison_pipeline_expression_question(
    a_facts: FeedbackEvidenceFacts,
    b_facts: FeedbackEvidenceFacts,
) -> FeedbackDesignQuestionFact:
    a_available, a_missing, a_blocked = a_facts.generated_context_records(source="a")
    b_available, b_missing, b_blocked = b_facts.generated_context_records(source="b")
    return _feedback_question(
        "pipeline_expression",
        "pipeline_expression",
        "Does correctness-passing on-device evidence exist to compare the intended pipeline-stage expression between the two generated contexts?",
        ("pipeline_stage_expression", "generated_source_context", "correctness", "on_device_evidence"),
        [*a_available, *b_available],
        [*a_missing, *b_missing],
        "Keep compile-blocked evidence separate, then compare only correctness-passing on-device runs with matching workload and profiler scope.",
        [*_prefix_feedback_blockers("a", a_blocked), *_prefix_feedback_blockers("b", b_blocked)],
    )


def _comparison_contract_blockers(
    compatibility: dict[str, Any] | None,
    a_facts: FeedbackEvidenceFacts,
    b_facts: FeedbackEvidenceFacts,
) -> list[str]:
    blockers = []
    if a_facts.compiled_value() is False:
        blockers.append("baseline compile stage did not produce a runnable candidate")
    if b_facts.compiled_value() is False:
        blockers.append("candidate compile stage did not produce a runnable candidate")
    if a_facts.correctness_passed() is False:
        blockers.append("baseline correctness did not pass")
    if b_facts.correctness_passed() is False:
        blockers.append("candidate correctness did not pass")
    if isinstance(compatibility, dict) and compatibility.get("can_compare") is False:
        blockers.extend(str(reason) for reason in compatibility.get("blocking_reasons") or ["incompatible runs"])
    for label, facts in [
        ("baseline", a_facts),
        ("candidate", b_facts),
    ]:
        if not facts.summary_present:
            blockers.append(f"{label} missing analysis/summary.json")
        if not facts.raw_artifact_index_present:
            blockers.append(f"{label} missing analysis/raw_artifact_index.json")
        elif not facts.raw_inventory_present():
            blockers.append(f"{label} missing parsed on-device profiler evidence")
    return blockers


def _compatibility_item(item_id: str, a_value: Any, b_value: Any) -> dict[str, Any]:
    if a_value is None or b_value is None:
        status = "missing"
    elif _feedback_values_match(a_value, b_value):
        status = "match"
    else:
        status = "mismatch"
    return {"id": item_id, "status": status, "a": a_value, "b": b_value}


def _optional_compatibility_item(item_id: str, a_value: Any, b_value: Any) -> dict[str, Any]:
    if a_value is None and b_value is None:
        return {"id": item_id, "status": "match", "a": a_value, "b": b_value}
    return _compatibility_item(item_id, a_value, b_value)


def _readiness_level_compatibility_item(
    a_facts: FeedbackEvidenceFacts,
    b_facts: FeedbackEvidenceFacts,
) -> dict[str, Any]:
    a_level = a_facts.readiness_level()
    b_level = b_facts.readiness_level()
    if a_level is None or b_level is None:
        status = "missing"
    elif not a_facts.readiness_at_least(FEEDBACK_MIN_COMPARISON_READINESS_LEVEL, FEEDBACK_READINESS_LEVEL_ORDER) or not b_facts.readiness_at_least(
        FEEDBACK_MIN_COMPARISON_READINESS_LEVEL, FEEDBACK_READINESS_LEVEL_ORDER
    ):
        status = "insufficient"
    else:
        status = "match"
    return {"id": "evidence_readiness.level", "status": status, "a": a_level, "b": b_level}


def _readiness_family_compatibility_item(
    a_facts: FeedbackEvidenceFacts,
    b_facts: FeedbackEvidenceFacts,
) -> dict[str, Any]:
    a_families = a_facts.material_evidence_families()
    b_families = b_facts.material_evidence_families()
    if not a_families or not b_families:
        status = "missing"
    elif _feedback_values_match(a_families, b_families):
        status = "match"
    else:
        status = "mismatch"
    return {"id": "evidence_readiness.material_families", "status": status, "a": a_families, "b": b_families}


def _readiness_followup_compatibility_item(
    a_facts: FeedbackEvidenceFacts,
    b_facts: FeedbackEvidenceFacts,
) -> dict[str, Any]:
    a_actions = a_facts.collection_action_ids()
    b_actions = b_facts.collection_action_ids()
    status = "match" if not a_actions and not b_actions else "pending"
    return {"id": "evidence_readiness.pending_followups", "status": status, "a": a_actions, "b": b_actions}


def _correctness_passed(context: dict[str, Any] | None) -> bool | None:
    raw = _context_value(context, ["benchmark", "correctness", "raw"])
    if isinstance(raw, dict):
        passed = raw.get("passed")
        return passed if isinstance(passed, bool) else None
    return raw if isinstance(raw, bool) else None


def _compiled_value(context: dict[str, Any] | None) -> bool | None:
    compiled = _context_value(context, ["benchmark", "candidate", "compiled"])
    return compiled if isinstance(compiled, bool) else None


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


def _report_maxima_text(maxima: Any) -> str:
    if isinstance(maxima, list) and maxima:
        return ", ".join(
            f"{item.get('field')}={_report_fmt_value(item.get('value'))}"
            for item in maxima
            if isinstance(item, dict)
        )
    return "none recorded"


def _report_warning_caveats(prefix: str, context: dict[str, Any] | None) -> list[str]:
    if not context:
        return []
    warnings = context.get("warnings")
    return [f"{prefix}: {warning}" for warning in warnings] if isinstance(warnings, list) else []


def _report_sourced_text(item: Any, fallback: str) -> str:
    if not item:
        return fallback
    value = _sourced_value(item)
    source = item.get("source") if isinstance(item, dict) else {}
    source = source if isinstance(source, dict) else {}
    artifact = source.get("artifact")
    field = source.get("field")
    text = _report_fmt_value(value)
    if artifact and field:
        return f"{text} (source: `{artifact}`; `{field}`)"
    if artifact:
        return f"{text} (source: `{artifact}`)"
    return text


def _report_profile_outputs_text(provenance: dict[str, Any] | None) -> str:
    if not provenance:
        return "not recorded"
    outputs = provenance.get("profile_outputs")
    if isinstance(outputs, list) and outputs:
        return ", ".join(_report_sourced_text(item, "not recorded") for item in outputs)
    return _report_sourced_text(provenance.get("profile_output"), "not recorded")


def _report_profile_output_segments_text(provenance: dict[str, Any] | None) -> str | None:
    if not provenance:
        return None
    segments = provenance.get("profile_output_segments")
    if not isinstance(segments, dict):
        return None
    rendered = []
    for name in ["app", "op"]:
        segment = segments.get(name)
        if not isinstance(segment, dict):
            continue
        parts = _report_profile_output_segment_parts(segment)
        if parts:
            rendered.append(f"{name}: {', '.join(parts)}")
    followups = segments.get("followups")
    if isinstance(followups, dict):
        for action_id in sorted(followups):
            segment = followups.get(action_id)
            if not isinstance(segment, dict):
                continue
            parts = _report_profile_output_segment_parts(segment)
            if parts:
                rendered.append(f"followups.{action_id}: {', '.join(parts)}")
    if not rendered:
        return None
    return "; ".join(rendered)


def _report_profile_output_segment_parts(segment: dict[str, Any]) -> list[str]:
    parts = []
    output = segment.get("output")
    if isinstance(output, dict):
        parts.append(_report_sourced_text(output, "not recorded"))
    resolved_output = segment.get("resolved_output")
    if isinstance(resolved_output, dict):
        parts.append(f"resolved {_report_sourced_text(resolved_output, 'not recorded')}")
    return parts


def _report_profile_outputs_setup_line(provenance: dict[str, Any] | None) -> str:
    segmented = _report_profile_output_segments_text(provenance)
    if segmented:
        return f"- Profile outputs: {segmented}"
    return f"- Profile output: {_report_profile_outputs_text(provenance)}"


def _report_collection_plan_setup_line(provenance: dict[str, Any] | None) -> str | None:
    if not provenance:
        return None
    plan = provenance.get("collection_plan")
    if not isinstance(plan, dict):
        return None
    preset_id = plan.get("preset_id")
    if not preset_id:
        return None
    segments = [
        str(segment["segment_id"])
        for segment in plan.get("segments", [])
        if isinstance(segment, dict) and segment.get("segment_id")
    ]
    segment_text = f"; segments: {', '.join(segments)}" if segments else ""
    source_text = f"; source: {plan['source']}" if plan.get("source") else ""
    return f"- Collection plan: {_report_md_escape(preset_id)}{segment_text}{source_text}"


def _report_md_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _maxima_by_field(maxima: Any) -> dict[str, Any]:
    if not isinstance(maxima, list):
        return {}
    result = {}
    for item in maxima:
        if isinstance(item, dict) and item.get("field"):
            result[str(item["field"])] = item.get("value")
    return result


def _sourced_value(item: Any) -> Any:
    if isinstance(item, dict) and "value" in item:
        return item.get("value")
    return item


def _source_ref(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    source = item.get("source")
    if isinstance(source, dict):
        return {
            "artifact": source.get("artifact"),
            "field": source.get("field") or source.get("field_ref"),
        }
    return None


def _compatibility_value(item: Any) -> CompatibilityValueFact:
    return CompatibilityValueFact(
        value=_sourced_value(item),
        source=_source_ref(item),
        status=item.get("status") if isinstance(item, dict) else None,
    )


def _provenance_payload_value(item: Any) -> Any:
    item = _sourced_value(item)
    if isinstance(item, dict):
        return {key: _provenance_payload_value(value) for key, value in item.items() if key != "source"}
    if isinstance(item, list):
        return [_provenance_payload_value(value) for value in item]
    return item


def _artifact_match_keys(artifact: Any) -> set[str]:
    if artifact in (None, ""):
        return set()
    artifact_text = str(artifact)
    return {artifact_text, Path(artifact_text).name}


def _artifact_matches_keys(artifact: Any, allowed_keys: set[str] | None) -> bool:
    if allowed_keys is None:
        return True
    return bool(_artifact_match_keys(artifact) & allowed_keys)


def headline_field_reference(group: str, item: dict[str, Any]) -> str:
    refs = [f"headlines.{group}.value"]
    if item.get("field"):
        refs.append(f"headlines.{group}.field={item['field']}")
    if item.get("field_kind"):
        refs.append(f"headlines.{group}.field_kind={item['field_kind']}")
    return "; ".join(refs)


def raw_value_field_reference(group: str, item: dict[str, Any]) -> str | None:
    raw_row_key = "first_row" if group == "op_basic_info" else "raw_row"
    field = item.get("field")
    if field:
        raw_row = item.get(raw_row_key) or {}
        if isinstance(raw_row, dict) and field in raw_row:
            return f"headlines.{group}.{raw_row_key}.{field}"
        if isinstance(raw_row, dict):
            fallback = _fallback_raw_value_field(raw_row)
            if fallback:
                return f"headlines.{group}.{raw_row_key}.{fallback}"
        return None

    raw_row = item.get(raw_row_key) or {}
    if not isinstance(raw_row, dict):
        return None
    normalized = {str(key).strip().lower(): str(key) for key in raw_row}
    for candidate in _raw_value_field_candidates(group):
        resolved = normalized.get(candidate.strip().lower())
        if resolved:
            return f"headlines.{group}.{raw_row_key}.{resolved}"
    return None


def correlation_field_reference(group: str, item: dict[str, Any]) -> str:
    refs = [f"headlines.{group}.value"]
    raw_ref = raw_value_field_reference(group, item)
    if raw_ref:
        refs.append(raw_ref)
    if item.get("field"):
        refs.append(f"headlines.{group}.field={item['field']}")
    if item.get("field_kind"):
        refs.append(f"headlines.{group}.field_kind={item['field_kind']}")
    return "; ".join(refs)


def _raw_value_field_candidates(group: str) -> tuple[str, ...]:
    candidates: dict[str, tuple[str, ...]] = {
        "op_summary": ("Task Duration(us)", "task_duration(us)", "duration(us)", "total time(us)"),
        "task_time": ("task_time(us)", "Task Duration(us)", "task duration(us)"),
        "op_basic_info": ("Task Duration(us)", "task duration(us)"),
    }
    return candidates.get(group, ())


def _fallback_raw_value_field(raw_row: dict[Any, Any]) -> str | None:
    normalized = {str(key).strip().lower(): str(key) for key in raw_row}
    for candidate in ("Value", "value"):
        field = normalized.get(candidate.strip().lower())
        if field:
            return field
    return None
