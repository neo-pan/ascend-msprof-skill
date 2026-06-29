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
        summary: dict[str, Any],
        raw_artifact_index: dict[str, Any] | None,
        provenance: dict[str, Any] | None,
        tilelang_context: dict[str, Any] | None,
        profile_context: dict[str, Any] | None,
        warnings: list[str] | None = None,
    ) -> None:
        self.run_dir = Path(run_dir)
        self._summary = summary
        self._raw_artifact_index = raw_artifact_index
        self._provenance = provenance
        self._tilelang_context = tilelang_context
        self._profile_context = profile_context
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
        warnings: list[str] | None = None,
    ) -> "RunEvidence":
        return cls(
            Path(run_dir),
            summary,
            raw_artifact_index,
            provenance,
            tilelang_context,
            profile_context,
            warnings,
        )

    def warnings(self) -> list[str]:
        return list(self._warnings)

    def summary(self) -> dict[str, Any]:
        return self._summary

    def provenance(self) -> dict[str, Any] | None:
        return self._provenance

    def tilelang_context(self) -> dict[str, Any] | None:
        return self._tilelang_context

    def profile_context(self) -> dict[str, Any] | None:
        return self._profile_context

    def artifact_presence(self) -> dict[str, str | None]:
        return {
            "summary": "analysis/summary.json",
            "raw_artifact_index": "analysis/raw_artifact_index.json" if self._raw_artifact_index else None,
            "provenance": "analysis/provenance.json" if self._provenance else None,
            "tilelang_context": "analysis/tilelang_context.json" if self._tilelang_context else None,
            "profile_context": "analysis/profile_context.json" if self._profile_context else None,
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

    def headline_rows(self) -> list[tuple[str, str, Any, str]]:
        rows = []
        for fact in self.headline_records():
            label = fact.label or fact.group
            source = f"`{fact.artifact}`; `{fact.field_ref}`"
            rows.append((label, fact.signal, fact.value, source))
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

    def pending_collection_actions(self) -> list[dict[str, Any]]:
        actions = self._summary.get("next_collection_actions")
        if not isinstance(actions, list):
            return []
        return [action for action in actions if isinstance(action, dict)]

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


def _load_optional_json_object(run_dir: Path, name: str, warnings: list[str]) -> dict[str, Any] | None:
    path = run_dir / "analysis" / name
    if not path.exists():
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
