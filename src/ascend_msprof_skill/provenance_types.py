"""Typed sourced provenance and collection environment facts."""
from __future__ import annotations

from typing import Annotated, Generic, Literal, TypeVar
from pathlib import Path
from pydantic import Field, model_validator

from .evidence_types import ArtifactPath, EvidenceFact, SourceRef

T = TypeVar("T")


class Sourced(EvidenceFact, Generic[T]):
    value: T
    source: SourceRef


class CannVersion(Sourced[str | None]):
    status: Literal["recorded", "conflict"]
    evidence: Annotated[tuple[Sourced[str], ...], Field(strict=False)]
    conflicts: Annotated[tuple[Sourced[str] | Sourced[bool], ...], Field(strict=False)] = ()

    @model_validator(mode="after")
    def consistent_version(self) -> CannVersion:
        values = {item.value for item in self.evidence}
        string_conflicts = tuple(item for item in self.conflicts if isinstance(item.value, str))
        root_conflicts = tuple(item for item in self.conflicts if isinstance(item.value, bool))
        if string_conflicts != (self.evidence if len(values) > 1 else ()):
            raise ValueError("version conflicts disagree with recorded component evidence")
        if any(item.value is not True or item.source != SourceRef(
                artifact="logs/msprof_environment.json", field="mixed_roots") for item in root_conflicts) or len(root_conflicts) > 1:
            raise ValueError("environment conflict requires the sourced mixed_roots flag")
        if self.conflicts:
            if (self.status != "conflict" or self.value is not None or self.source != SourceRef(
                    artifact="analysis/provenance.json", field="cann_version.conflicts")):
                raise ValueError("conflicting version sources cannot select a version")
        elif (self.status != "recorded" or not self.evidence or self.value != self.evidence[0].value
              or self.source != self.evidence[0].source):
            raise ValueError("recorded version must select its first consistent source")
        return self


class HardwareDevice(EvidenceFact):
    npu: Sourced[str]
    name: Sourced[str]
    health: Sourced[str]


class HardwareContext(EvidenceFact):
    summary: Sourced[str]
    devices: Annotated[tuple[HardwareDevice, ...], Field(strict=False)] = ()

    @model_validator(mode="after")
    def summary_matches_devices(self) -> HardwareContext:
        if self.devices and self.summary.value != hardware_summary(self.devices):
            raise ValueError("hardware summary disagrees with recorded devices")
        return self


def hardware_summary(devices: tuple[HardwareDevice, ...]) -> str:
    names = ", ".join(sorted({item.name.value for item in devices}))
    health = ", ".join(sorted({item.health.value for item in devices}))
    return f"{len(devices)} x {names}; health {health}"


class EnvironmentContext(EvidenceFact):
    selected: dict[str, Sourced[str]]
    omitted_keys: Sourced[Annotated[tuple[str, ...], Field(strict=False)]]


class OutputSegment(EvidenceFact):
    output: Sourced[str] | None = None
    resolved_output: Sourced[str] | None = None
    status: Sourced[str] | None = None


class ProfileOutputSegments(EvidenceFact):
    app: OutputSegment | None = None
    op: OutputSegment | None = None
    simulator: OutputSegment | None = None
    followups: dict[str, OutputSegment] = Field(default_factory=dict)


class CollectionPlanSegment(EvidenceFact):
    segment_id: str


class CollectionPlanContext(EvidenceFact):
    preset_id: str
    source: str | None = None
    segments: Annotated[tuple[CollectionPlanSegment, ...], Field(strict=False)]


class Provenance(EvidenceFact):
    schema_version: Literal[2]
    sources: Annotated[tuple[ArtifactPath, ...], Field(strict=False)] = ()
    warnings: Annotated[tuple[str, ...], Field(strict=False)] = ()
    cann_components: dict[str, Sourced[str]] = Field(default_factory=dict)
    cann_version: CannVersion | None = None
    hardware: HardwareContext | None = None
    profile_command: Sourced[str] | None = None
    profile_date: Sourced[str | int] | None = None
    profile_output: Sourced[str] | None = None
    profile_outputs: Annotated[tuple[Sourced[str], ...], Field(strict=False)] = ()
    profile_output_segments: ProfileOutputSegments | None = None
    profiler_status: Annotated[tuple[Sourced[str], ...], Field(strict=False)] = ()
    environment: EnvironmentContext | None = None
    collection_plan: CollectionPlanContext | None = None


class ToolkitSnapshot(EvidenceFact):
    path: str
    artifact: ArtifactPath
    preserved: bool = False


class CannEnvironment(EvidenceFact):
    msprof: str | None
    toolkit_root: str | None
    environment_roots: dict[str, str]
    mixed_roots: bool
    snapshots: Annotated[tuple[ToolkitSnapshot, ...], Field(strict=False)]


def load_provenance(run_dir: Path) -> Provenance | None:
    from .artifact_reader import read_json
    try:
        payload = read_json(run_dir / "analysis/provenance.json")
    except FileNotFoundError:
        return None
    return Provenance.model_validate(payload)
