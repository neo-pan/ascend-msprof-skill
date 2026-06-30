"""Read-only facts derived from an analyzed Ascend profiling run."""
from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .metric_scope_policy import metric_scope_policy, warning_group


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
    artifact: str | None
    group: str | None
    parser: str | None
    segment: str | None
    metric_scope: Any
    status: str | None
    row_count: Any
    columns: tuple[Any, ...]
    warnings: tuple[Any, ...]


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
    def simulator_present(self) -> bool:
        return isinstance(self.evidence.simulator_hotspots(), dict)

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
    mean_ms: float | None
    runtime: Any
    runtime_stats: Any
    ref_runtime: Any
    speedup: Any
    source: str | None

    def as_summary(self) -> dict[str, Any]:
        return {
            "mean_ms": self.mean_ms,
            "runtime": self.runtime,
            "runtime_stats": self.runtime_stats,
            "ref_runtime": self.ref_runtime,
            "speedup": self.speedup,
            "source": self.source,
        }


@dataclass(frozen=True)
class CandidateContextFacts:
    workload: dict[str, Any]
    payload: CandidatePayloadFact
    jit: CandidateJitFact
    correctness: CandidateCorrectnessFact
    runtime: CandidateRuntimeFact


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


@dataclass(frozen=True)
class CompatibilityFacts:
    cann_version: CompatibilityValueFact
    hardware_summary: CompatibilityValueFact
    profile_command: CompatibilityValueFact
    metric_scope: CompatibilityValueFact
    profile_output_segments: CompatibilityValueFact


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

    def warnings(self) -> list[str]:
        return list(self._warnings)

    def feedback_facts(self) -> FeedbackEvidenceFacts:
        return FeedbackEvidenceFacts(self)

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
        return {
            "present": True,
            "name": fact.name,
            "value": fact.value,
            "field": fact.field,
            "field_kind": fact.field_kind,
            "artifact": fact.artifact,
            "segment": fact.segment,
            "metric_scope": fact.metric_scope,
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
                    artifact=_str_or_none(item.get("artifact")),
                    group=_str_or_none(item.get("group")),
                    parser=_str_or_none(item.get("parser")),
                    segment=_str_or_none(item.get("segment")),
                    metric_scope=item.get("metric_scope"),
                    status=_str_or_none(item.get("status")),
                    row_count=item.get("row_count"),
                    columns=tuple(columns) if isinstance(columns, list) else (),
                    warnings=tuple(warnings if isinstance(warnings, list) else []),
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
        parsed = [fact for fact in self.raw_artifacts() if fact.status == "parsed"]
        group_counts = Counter(fact.group or "unknown" for fact in parsed)
        segment_counts = Counter(fact.segment or "unknown" for fact in parsed)
        return len(parsed), dict(sorted(group_counts.items())), dict(sorted(segment_counts.items()))

    def parsed_raw_artifacts_by_group(self, groups: set[str]) -> list[RawArtifactFact]:
        return [
            fact
            for fact in self.raw_artifacts()
            if fact.status == "parsed" and str(fact.group or "") in groups
        ]

    def parsed_required_artifacts(
        self,
        groups: set[str],
        required_artifacts: list[str],
    ) -> tuple[list[RawArtifactFact], list[str], set[str]]:
        required_by_name = {Path(artifact).name: artifact for artifact in required_artifacts}
        present_by_name: dict[str, RawArtifactFact] = {}
        allowed_keys: set[str] = set()
        for fact in self.parsed_raw_artifacts_by_group(groups):
            artifact = fact.artifact
            artifact_name = Path(str(artifact)).name if artifact not in (None, "") else ""
            if artifact_name not in required_by_name:
                continue
            present_by_name.setdefault(artifact_name, fact)
            allowed_keys.update(_artifact_match_keys(artifact))
        present = [present_by_name[name] for name in required_by_name if name in present_by_name]
        missing = [artifact for artifact in required_artifacts if Path(artifact).name not in present_by_name]
        return present, missing, allowed_keys

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
            "evidence_present": self._summary_present and parsed_count > 0,
        }

    def summary_evidence(self) -> dict[str, Any]:
        return {
            "summary_warnings": self.summary_warnings(),
            "next_collection_actions": self.next_collection_actions(),
            "pending_collection_actions": self.combined_pending_collection_actions(),
            "evidence_readiness": self.readiness_status(),
            "raw_artifact_index": self.raw_artifact_index_summary(),
        }

    def candidate_context(self) -> CandidateContextFacts:
        context = self._tilelang_context
        workload = _context_value(context, ["benchmark", "workload"])
        payload = _context_value(context, ["sources", "payload"])
        jit_debug = _context_value(context, ["jit_debug"])
        runtime_stats = _context_value(context, ["benchmark", "candidate", "runtime_stats"])
        runtime = _context_value(context, ["benchmark", "candidate", "runtime"])
        mean_ms = _try_float(_context_value(context, ["benchmark", "candidate", "runtime_stats", "mean_ms"]))
        if mean_ms is None:
            mean_ms = _try_float(runtime)
        error = _context_value(context, ["benchmark", "candidate", "error"])
        if error in (None, "", [], {}):
            error = None

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
            payload=CandidatePayloadFact(
                present=isinstance(payload, dict),
                artifact=payload.get("artifact") if isinstance(payload, dict) else None,
                sha256=payload.get("sha256") if isinstance(payload, dict) else None,
                size_bytes=payload.get("size_bytes") if isinstance(payload, dict) else None,
            ),
            jit=CandidateJitFact(
                config=_context_value(context, ["benchmark", "jit_config"]),
                debug=debug,
            ),
            correctness=CandidateCorrectnessFact(
                compiled=_compiled_value(context),
                passed=_correctness_passed(context),
                error=error,
                maxima=_context_value(context, ["benchmark", "correctness", "maxima"]) or [],
                source="analysis/tilelang_context.json" if context else None,
            ),
            runtime=CandidateRuntimeFact(
                mean_ms=mean_ms,
                runtime=runtime,
                runtime_stats=runtime_stats,
                ref_runtime=_context_value(context, ["benchmark", "candidate", "ref_runtime"]),
                speedup=_context_value(context, ["benchmark", "candidate", "speedup"]),
                source="analysis/tilelang_context.json" if context else None,
            ),
        )

    def comparison_benchmark(self) -> BenchmarkComparisonFacts:
        context = self._tilelang_context
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
            ComparisonFieldFact("candidate.runtime", "Candidate runtime", candidate.runtime.runtime, 0),
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
            present=isinstance(context, dict),
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
        rows = [
            _report_row(
                "Workload id",
                candidate.workload.get("id"),
                TILELANG_CONTEXT_ARTIFACT,
                "benchmark.workload.id",
            ),
            _report_row(
                "Shape",
                candidate.workload.get("shape"),
                TILELANG_CONTEXT_ARTIFACT,
                "benchmark.workload.shape",
            ),
            _report_row(
                "Dtype",
                candidate.workload.get("dtype"),
                TILELANG_CONTEXT_ARTIFACT,
                "benchmark.workload.dtype",
            ),
            _report_row(
                "Case count",
                candidate.workload.get("case_count"),
                TILELANG_CONTEXT_ARTIFACT,
                "benchmark.workload.case_count",
            ),
            _report_row(
                "Compiled",
                candidate.correctness.compiled,
                TILELANG_CONTEXT_ARTIFACT,
                "benchmark.candidate.compiled",
            ),
            _report_row(
                "Candidate runtime",
                candidate.runtime.runtime,
                TILELANG_CONTEXT_ARTIFACT,
                "benchmark.candidate.runtime",
            ),
            _report_row(
                "Runtime stats",
                candidate.runtime.runtime_stats,
                TILELANG_CONTEXT_ARTIFACT,
                "benchmark.candidate.runtime_stats",
            ),
            _report_row(
                "Reference runtime",
                candidate.runtime.ref_runtime,
                TILELANG_CONTEXT_ARTIFACT,
                "benchmark.candidate.ref_runtime",
            ),
            _report_row(
                "Speedup",
                candidate.runtime.speedup,
                TILELANG_CONTEXT_ARTIFACT,
                "benchmark.candidate.speedup",
            ),
            _report_row(
                "Correctness maxima",
                _report_maxima_text(candidate.correctness.maxima),
                TILELANG_CONTEXT_ARTIFACT,
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
                _report_row("JIT config", candidate.jit.config, TILELANG_CONTEXT_ARTIFACT, "benchmark.jit_config")
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
