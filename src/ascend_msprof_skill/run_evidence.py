"""Read-only facts derived from an analyzed Ascend profiling run."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
        summary: dict[str, Any],
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
                        warnings=("raw artifact entry is not a JSON object",),
                    )
                )
                continue
            warnings = item.get("warnings")
            rows.append(
                RawArtifactFact(
                    artifact=_str_or_none(item.get("artifact")),
                    group=_str_or_none(item.get("group")),
                    parser=_str_or_none(item.get("parser")),
                    segment=_str_or_none(item.get("segment")),
                    metric_scope=item.get("metric_scope"),
                    status=_str_or_none(item.get("status")),
                    row_count=item.get("row_count"),
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
