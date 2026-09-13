"""Collection requirements and profiling readiness facts (no I/O)."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .analysis_types import RelationEvidence
from .evidence_types import ArtifactPath, EvidenceFact


class CollectionTargetScope(EvidenceFact):
    kind: Literal["observed_run", "complete_program"]
    kernel_selector: str | None = None
    expected_launches: dict[str, Annotated[int, Field(ge=1)]] | None = None
    expected_total: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def declared_counts(self) -> CollectionTargetScope:
        if self.kind == "observed_run":
            if any(item is not None for item in (self.kernel_selector, self.expected_launches, self.expected_total)):
                raise ValueError("observed-run collection has no declared launch authority")
        elif (not self.kernel_selector or not self.expected_launches
              or self.expected_total != sum(self.expected_launches.values())):
            raise ValueError("complete-program collection requires consistent declared counts")
        return self


class CollectionCost(EvidenceFact):
    estimated_launches: int | None = Field(ge=0)
    metric_scopes: Annotated[tuple[str, ...], Field(strict=False)]
    segments: int = Field(ge=1)


class CollectionAction(EvidenceFact):
    id: str = Field(min_length=1)
    reason: str
    recommended_aic_metrics: Annotated[tuple[str, ...], Field(strict=False)]
    required_artifacts: Annotated[tuple[str, ...], Field(strict=False)]
    evidence: Annotated[tuple[RelationEvidence, ...], Field(strict=False)] = ()
    confidence: Literal["high", "medium", "low"]
    necessity: Literal["blocking", "question_required", "optional"]
    unlocks_claims: Annotated[tuple[str, ...], Field(strict=False)]
    target_scope: CollectionTargetScope
    estimated_cost: CollectionCost

    @model_validator(mode="after")
    def consistent_collection(self) -> CollectionAction:
        if self.estimated_cost.metric_scopes != self.recommended_aic_metrics:
            raise ValueError("estimated collection scopes disagree with requested metrics")
        if (self.target_scope.kind == "complete_program"
                and self.estimated_cost.estimated_launches != self.target_scope.expected_total):
            raise ValueError("estimated launches disagree with declared collection target")
        return self


class ReadinessSegment(EvidenceFact):
    segment: str
    metric_scope: str | None
    status: Literal["ready", "partial", "missing_required_artifacts", "not_applicable",
                    "ambiguous_timing", "no_usable_timing", "incomplete_target_coverage"]
    missing_required_artifacts: Annotated[tuple[str, ...], Field(strict=False)] = ()
    count_complete: bool | None = None
    metric_family_completeness: dict[str, bool | None] | None = None

    @model_validator(mode="after")
    def declared_coverage(self) -> ReadinessSegment:
        if self.metric_family_completeness is not None:
            if self.status != ("ready" if self.count_complete else "incomplete_target_coverage"):
                raise ValueError("readiness segment status disagrees with target count coverage")
            if self.missing_required_artifacts:
                raise ValueError("declared readiness requires per-family coverage")
        elif self.count_complete is not None:
            raise ValueError("declared count coverage requires per-family coverage")
        return self


class UnparsedBinary(EvidenceFact):
    artifact: ArtifactPath
    segment: str
    known_role: str | None
    diagnosis_role: Literal["not_used"]


ReadinessLevel = Literal["available", "partial", "insufficient"]


class EvidenceReadiness(EvidenceFact):
    schema_version: Literal["2.0"]
    level: ReadinessLevel
    reasons: Annotated[tuple[str, ...], Field(strict=False)]
    available_evidence_families: Annotated[tuple[str, ...], Field(strict=False)]
    missing_evidence_families: Annotated[tuple[str, ...], Field(strict=False)]
    allowed_claims: Annotated[tuple[str, ...], Field(strict=False)]
    blocked_claims: Annotated[tuple[str, ...], Field(strict=False)]
    recommended_followups: Annotated[tuple[CollectionAction, ...], Field(strict=False)]
    segments: Annotated[tuple[ReadinessSegment, ...], Field(strict=False)]
    unparsed_binary_artifacts: Annotated[tuple[UnparsedBinary, ...], Field(strict=False)]

    @model_validator(mode="after")
    def distinct_scopes(self) -> EvidenceReadiness:
        if len({item.segment for item in self.segments}) != len(self.segments):
            raise ValueError("readiness segments must be unique")
        if len({item.id for item in self.recommended_followups}) != len(self.recommended_followups):
            raise ValueError("readiness followups must have unique action ids")
        return self
