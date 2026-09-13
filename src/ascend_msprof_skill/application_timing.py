"""Application timing facts: explicit CANN fields, sources and selection rules."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .artifact_reader import read_csv
from .ascend_profile_utils import to_float
from .analysis_types import EvidenceSignal
from .evidence_types import ArtifactRecord, EvidenceFact, LaunchCount, MetricObservation, ParseIssue, SourceRef
from .metric_scope_policy import APP_TIMING_ARTIFACTS


# CANN field sources: reference-sources.yaml and application-timing-chain-20260912.
# Each tuple is one statistic's confirmed spellings, never a mix of Total/Avg/etc.
TIMING_FIELDS = {
    "op_summary": {"duration": ("Task Duration(us)", "task_duration(us)", "Duration(us)")},
    "task_time": {"duration": ("task_time(us)", "Task Duration(us)", "Duration(us)")},
    "op_statistic": {
        "total": ("Total Time(us)",), "average": ("Avg Time(us)",),
        "maximum": ("Max Time(us)",), "minimum": ("Min Time(us)",),
    },
    "api_statistic": {
        "total": ("Time(us)", "Duration(us)"), "average": ("Avg(us)",),
        "maximum": ("Max(us)",), "minimum": ("Min(us)",),
    },
}
NAME_FIELDS = {
    "op_summary": ("Op Name", "Operator Name", "kernel_name", "Task Name", "Name"),
    "task_time": ("kernel_name", "Task Name", "Op Name", "Name"),
    "op_statistic": ("OP Type",),
    "api_statistic": ("API Name", "Name"),
}
SCOPE_FIELDS = ("Device_id", "Device ID", "Model ID", "Stream ID", "stream_id", "Core Type", "Level")


def _positions(columns: tuple[str, ...], names: tuple[str, ...]) -> list[int]:
    spellings = {name.lower() for name in names}
    return [index for index, column in enumerate(columns) if column.lower() in spellings]


class PrimarySelection(EvidenceFact):
    candidates: Annotated[tuple[SourceRef, ...], Field(strict=False)]
    selected: SourceRef | None
    reason: Literal["selected", "no_valid_observation", "multiple_scopes", "multiple_observations"]


def select_primary(artifacts: tuple[ArtifactRecord, ...]) -> PrimarySelection:
    candidates = [item.source for artifact in artifacts for item in artifact.observations]
    scopes = {(artifact.artifact, item.scope) for artifact in artifacts for item in artifact.observations}
    return PrimarySelection(candidates=tuple(candidates),
        selected=candidates[0] if len(candidates) == 1 else None,
        reason="selected" if len(candidates) == 1 else ("multiple_scopes" if len(scopes) > 1 else "multiple_observations") if candidates else "no_valid_observation")


class TimingEvidence(EvidenceFact):
    group: Literal["op_summary", "task_time", "op_statistic", "api_statistic"]
    artifacts: Annotated[tuple[ArtifactRecord, ...], Field(strict=False)]
    primary: PrimarySelection

    @model_validator(mode="after")
    def consistent_selection(self) -> TimingEvidence:
        if any(item.group != self.group for item in self.artifacts):
            raise ValueError("artifact group differs from timing group")
        if len({item.artifact for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("duplicate artifact in timing evidence")
        for artifact in self.artifacts:
            keys = [(item.statistic, item.scope) for item in artifact.observations]
            if len(set(keys)) != len(keys):
                raise ValueError("duplicate representative statistic within one scope")
            for observation in artifact.observations:
                names = TIMING_FIELDS[self.group].get(observation.statistic, ())
                if observation.unit != "us" or observation.metric != self.group:
                    raise ValueError("timing metric or unit disagrees with group")
                if any(source.field.lower() not in {name.lower() for name in names}
                       for source in (observation.source, *observation.aliases)):
                    raise ValueError("timing field disagrees with statistic")
        if self.primary != select_primary(self.artifacts):
            raise ValueError("persisted timing selection disagrees with observations")
        return self

    @property
    def observation(self) -> MetricObservation | None:
        return next((item for artifact in self.artifacts for item in artifact.observations
                     if item.source == self.primary.selected), None)

    @property
    def available(self) -> bool:
        return any(artifact.observations for artifact in self.artifacts)

    @property
    def unique_scope(self) -> bool:
        return len({(artifact.artifact, item.scope)
                    for artifact in self.artifacts for item in artifact.observations}) == 1


def normalize_timing(path: Path, artifact: str, group: str, segment: str, metric_scope: str | None) -> ArtifactRecord:
    best: dict[tuple, MetricObservation] = {}
    issues: list[ParseIssue] = []
    counts: dict[str, tuple[int, float | None]] = {}

    def consume(columns: tuple[str, ...], cells: tuple[str, ...], ordinal: int) -> None:
        name_positions = next((positions for field in NAME_FIELDS[group]
                               if (positions := _positions(columns, (field,)))), [])
        name = cells[name_positions[0]] if name_positions else None
        if len({cells[index] for index in name_positions}) > 1:
            index = name_positions[0]
            issues.append(ParseIssue(code="alias_conflict", source=SourceRef(
                artifact=artifact, field=columns[index], record=ordinal, column=index + 1),
                reason="equivalent name columns disagree", impact="scope"))
            name = None
        scope = tuple((columns[index], cells[index]) for index in _positions(columns, SCOPE_FIELDS))
        duration = None
        unit_positions = _positions(columns, ("unit", "units"))
        if unit_positions:
            index = unit_positions[0]
            issues.append(ParseIssue(code="unsupported_unit_layout", source=SourceRef(artifact=artifact,
                field=columns[index], record=ordinal, column=index + 1),
                reason="separate unit column is outside the supported timing layout", impact="metric"))
        for statistic, aliases in TIMING_FIELDS[group].items():
            positions = _positions(columns, aliases)
            if not positions or unit_positions:
                continue
            refs = tuple(SourceRef(artifact=artifact, field=columns[index], record=ordinal, column=index + 1)
                         for index in positions)
            values = [to_float(cells[index]) for index in positions]
            if len({columns[index] for index in positions}) != len(positions):
                # The reader records duplicate headers. Do not reinterpret their values.
                continue
            if len(set(values)) > 1:
                issues.append(ParseIssue(code="alias_conflict", source=refs[0],
                    reason="synonymous timing columns disagree: " + ", ".join(columns[i] for i in positions), impact="metric"))
                continue
            value = values[0]
            if value is None:
                issues.append(ParseIssue(code="invalid_number", source=refs[0], reason="timing cell is not a finite decimal number", impact="metric"))
                continue
            observation = MetricObservation(metric=group, value=value, unit="us", statistic=statistic,
                name=name, scope=scope, source=refs[0], raw_token=cells[positions[0]], aliases=refs[1:])
            key = (statistic, scope)
            if key not in best or value > best[key].value:
                best[key] = observation
            if statistic == "duration":
                duration = value
        if group == "op_summary":
            key = name or ""
            count, total = counts.get(key, (0, 0.0))
            if duration is None:
                total = None
            elif total is not None:
                total = to_float(total + duration)
                if total is None:
                    issues.append(ParseIssue(code="aggregate_overflow", source=observation.source,
                        reason=f"duration aggregate for {key!r} exceeds finite numeric range", impact="metric"))
            counts[key] = (count + 1, total)

    decoded = read_csv(path, artifact, consume)
    if decoded.columns and not any(_positions(decoded.columns, fields) for fields in TIMING_FIELDS[group].values()):
        issues.append(ParseIssue(code="unsupported_fields", source=SourceRef(artifact=artifact, record=1),
            reason="no recognized timing column with a known unit", impact="metric"))
    totals = [total for _, total in counts.values() if total is not None]
    if totals and to_float(sum(totals)) is None:
        issues.append(ParseIssue(code="aggregate_overflow", source=next(iter(best.values())).source,
            reason="duration aggregate across launch names exceeds finite numeric range", impact="metric"))
    return ArtifactRecord(artifact=artifact, group=group, segment=segment, metric_scope=metric_scope,
        status=decoded.status, columns=decoded.columns, row_count=decoded.row_count, sample_rows=decoded.sample_rows,
        issues=(*decoded.issues, *issues), observations=tuple(best.values()),
        launch_counts=tuple(LaunchCount(name=name, count=count, duration_us=total) for name, (count, total) in counts.items()))


def timing_groups(headlines: dict, *, unique_scope: bool = False) -> tuple[str, ...]:
    return tuple(group for group in APP_TIMING_ARTIFACTS
                 if isinstance(item := headlines.get(group), TimingEvidence)
                 and (item.unique_scope if unique_scope else item.available))


def observation_field_ref(group: str, item: MetricObservation) -> str:
    return (f"headlines.{group}.artifacts.observations.value; "
            f"record={item.source.record}; column={item.source.column}; field={item.source.field}; "
            f"statistic={item.statistic}; unit={item.unit}; metric={item.metric}; "
            "aggregation=maximum_observed_cell" +
            "".join(f"; {key}={value}" for key, value in item.scope))


def timing_signals(evidence: TimingEvidence) -> list[EvidenceSignal]:
    return [EvidenceSignal.model_validate({"group": evidence.group, "signal": f"{item.name or 'n/a'} / {item.source.field}",
             "artifact": artifact.artifact, "field": item.source.field,
             "field_ref": observation_field_ref(evidence.group, item), "value": item.value,
             "kind": f"timing_{item.statistic}", "row_count": artifact.row_count,
             "segment": artifact.segment, "metric_scope": artifact.metric_scope})
            for artifact in evidence.artifacts for item in artifact.observations]
