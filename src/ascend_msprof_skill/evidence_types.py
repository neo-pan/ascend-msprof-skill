"""Validated facts shared by profiler readers and evidence consumers (no I/O)."""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from .ascend_profile_utils import to_float


class EvidenceFact(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, allow_inf_nan=False)


def normalized_artifact_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value:
        raise ValueError("artifact must be a normalized run-relative path")
    return value


ArtifactPath = Annotated[str, AfterValidator(normalized_artifact_path)]


class SourceRef(EvidenceFact):
    artifact: ArtifactPath
    field: str | None = None
    record: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)


class ParseIssue(EvidenceFact):
    code: str
    source: SourceRef
    reason: str
    impact: Literal["decode", "structure", "metric", "scope"]


class MetricObservation(EvidenceFact):
    metric: str
    value: FiniteFloat
    unit: str
    statistic: Literal["duration", "total", "average", "minimum", "maximum", "ratio", "percentage", "bandwidth", "volume", "estimated_volume", "frequency"]
    name: str | None
    scope: Annotated[tuple[Annotated[tuple[str, str], Field(strict=False)], ...], Field(strict=False)] = ()
    source: SourceRef
    raw_token: str
    aliases: Annotated[tuple[SourceRef, ...], Field(strict=False)] = ()

    @model_validator(mode="after")
    def token_matches_value(self) -> MetricObservation:
        if to_float(self.raw_token) != self.value:
            raise ValueError("raw_token and normalized value disagree")
        return self


class LaunchCount(EvidenceFact):
    name: str
    count: int = Field(ge=1)
    duration_us: FiniteFloat | None


def csv_status(row_count: int, issues: tuple[ParseIssue, ...]) -> str:
    if any(issue.impact in {"decode", "structure"} for issue in issues):
        return "invalid"
    return "parsed" if row_count else "empty"


class ArtifactRecord(EvidenceFact):
    artifact: ArtifactPath
    group: str
    parser: Literal["csv"] = "csv"
    segment: str
    metric_scope: str | None
    status: Literal["parsed", "empty", "invalid"]
    columns: Annotated[tuple[str, ...], Field(strict=False)]
    row_count: int = Field(ge=0)
    # Raw samples are uninterpreted payloads, never used to reconstruct metrics.
    sample_rows: Annotated[tuple[dict[str, str], ...], Field(strict=False)]
    issues: Annotated[tuple[ParseIssue, ...], Field(strict=False)]
    observations: Annotated[tuple[MetricObservation, ...], Field(strict=False)]
    launch_counts: Annotated[tuple[LaunchCount, ...], Field(strict=False)] = ()

    @model_validator(mode="after")
    def consistent_artifact(self) -> ArtifactRecord:
        if self.status != csv_status(self.row_count, self.issues):
            raise ValueError("persisted CSV status disagrees with decode facts")
        if not self.row_count and self.observations:
            raise ValueError("artifact without rows cannot contain observations")
        for observation in self.observations:
            for source in (observation.source, *observation.aliases):
                if source.artifact != self.artifact or source.field not in self.columns:
                    raise ValueError("observation source is outside this artifact")
                if source.record is None or source.record < 2 or source.record != observation.source.record:
                    raise ValueError("observation and aliases require the same CSV data record")
                if source.column is None or self.columns[source.column - 1:source.column] != (source.field,):
                    raise ValueError("observation source column disagrees with header")
        if sum(item.count for item in self.launch_counts) > self.row_count:
            raise ValueError("launch counts exceed records")
        if self.group == "op_summary" and self.status == "parsed" and sum(item.count for item in self.launch_counts) != self.row_count:
            raise ValueError("parsed op_summary launch counts must cover every record")
        return self

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(f"{issue.source.artifact}: {issue.reason}" for issue in self.issues)
