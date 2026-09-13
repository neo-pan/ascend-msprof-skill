"""Sourced analysis projections shared by derivation and rendering (no I/O)."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, model_validator

from .evidence_types import ArtifactPath, EvidenceFact


class EvidenceSignal(EvidenceFact):
    group: str
    signal: str
    artifact: ArtifactPath
    field: str
    field_ref: str
    value: int | FiniteFloat | str | None
    kind: str
    segment: str
    metric_scope: str | None
    row_count: int | None = Field(default=None, ge=0)
    evidence_id: str | None = None
    unit: str | None = None
    statistic: str | None = None
    metadata_field: str | None = None
    metadata_value: str | int | None = None
    tiling_field: str | None = None
    tiling_value: str | int | None = None
    tiling_field_ref: str | None = None

    @model_validator(mode="after")
    def metadata_projection(self) -> EvidenceSignal:
        if (self.metadata_field is not None) != (self.metadata_value is not None):
            raise ValueError("metadata field and value must be recorded together")
        if any(item is not None for item in (self.tiling_field, self.tiling_value, self.tiling_field_ref)):
            if (self.tiling_field, self.tiling_value, self.tiling_field_ref) != (
                    self.metadata_field, self.metadata_value, self.field_ref):
                raise ValueError("tiling projection disagrees with metadata")
        return self


class AnalysisDimension(EvidenceFact):
    id: str
    title: str
    status: Literal["available", "insufficient"]
    signals: Annotated[tuple[EvidenceSignal, ...], Field(strict=False)]
    evidence_refs: Annotated[tuple[str, ...], Field(strict=False)]
    model_artifact: ArtifactPath | None = None

    @model_validator(mode="after")
    def signal_projection(self) -> AnalysisDimension:
        if self.status != ("available" if self.signals else "insufficient"):
            raise ValueError("dimension status disagrees with its recorded signals")
        if self.evidence_refs != tuple(f"{item.artifact}; {item.field_ref}" for item in self.signals):
            raise ValueError("dimension references disagree with its recorded signals")
        return self


class RelationEvidence(EvidenceFact):
    evidence_id: str
    artifact: ArtifactPath
    field: str
    field_ref: str
    signal: str
    value: int | FiniteFloat | str | None
    segment: str | None = None
    metric_scope: str | None = None


class SourceContextRef(EvidenceFact):
    artifact: ArtifactPath
    field_ref: str
    role: str
    signal: str | None = None
    value: int | FiniteFloat | str | None = None


class EvidenceRelation(EvidenceFact):
    id: str
    kind: str
    target: str
    confidence: Literal["high", "medium", "low"]
    role: str
    evidence: Annotated[tuple[RelationEvidence, ...], Field(strict=False, min_length=2)]
    allowed_interpretation: str
    blocked_interpretation: str
    source_context_refs: Annotated[tuple[SourceContextRef, ...], Field(strict=False)] = ()

    @model_validator(mode="after")
    def distinct_evidence(self) -> EvidenceRelation:
        if len({item.evidence_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("relation evidence ids must be unique")
        return self
