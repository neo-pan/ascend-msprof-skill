"""Target attribution from declared context and sourced profiler observations."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from ._profile_target import TargetText, normalize_target_name, target_name_match_rule
from .application_timing import TimingEvidence
from .coverage_types import ProfileCoverage
from .evidence_types import ArtifactPath, EvidenceFact, SourceRef
from .operator_evidence import OperatorEvidence


class ExpectedTarget(EvidenceFact):
    names: Annotated[tuple[TargetText, ...], Field(strict=False, min_length=1)]
    artifact: ArtifactPath
    field_ref: str
    counts: dict[str, Annotated[int, Field(ge=1)]] | None = None
    inferred: bool = False
    explicit_target: bool = False

    @model_validator(mode="after")
    def consistent_declaration(self) -> ExpectedTarget:
        if self.explicit_target and (self.inferred or self.counts is None):
            raise ValueError("explicit target requires declared counts, not inference")
        if self.counts is not None and set(self.counts) != {normalize_target_name(name) for name in self.names}:
            raise ValueError("expected names and counts disagree")
        return self


class IdentityObservation(EvidenceFact):
    group: Literal["op_summary", "op_basic_info", "task_time"]
    name: str
    artifact: ArtifactPath
    field_ref: str
    count: int | None = Field(default=None, ge=1)
    status: Literal["match", "mismatch"] | None = None
    match_rule: Literal["exact", "known_suffix", "unmatched"] | None = None


def identity_match_rule(expected: ExpectedTarget, name: str) -> str:
    rules = {target_name_match_rule(item, name) for item in expected.names}
    return "exact" if "exact" in rules else "known_suffix" if "known_suffix" in rules else "unmatched"


def identity_state(expected: ExpectedTarget | None, observed: tuple[IdentityObservation, ...]) -> tuple[str, str]:
    if expected is None:
        return ("unverified", "low") if observed else ("missing", "blocked")
    if not observed:
        return "missing_observed", "blocked"
    matches = [item for item in observed if item.status == "match"]
    if len(matches) != len(observed):
        return ("partial_mismatch" if matches else "mismatch"), "blocked"
    names = {normalize_target_name(item.name) for item in observed}
    confidence = "high" if all(item.match_rule == "exact" for item in observed) and len(names) <= 1 else "medium"
    return "match", confidence


class IdentityEvidence(EvidenceFact):
    status: Literal["missing", "unverified", "missing_observed", "match", "partial_mismatch", "mismatch"]
    expected: ExpectedTarget | None
    observed: Annotated[tuple[IdentityObservation, ...], Field(strict=False)]
    confidence: Literal["high", "medium", "low", "blocked"]

    @model_validator(mode="after")
    def consistent_identity(self) -> IdentityEvidence:
        for item in self.observed:
            rule = identity_match_rule(self.expected, item.name) if self.expected is not None else None
            status = ("match" if rule != "unmatched" else "mismatch") if rule is not None else None
            if item.match_rule != rule or item.status != status:
                raise ValueError("identity observation disagrees with expected target")
        if (self.status, self.confidence) != identity_state(self.expected, self.observed):
            raise ValueError("identity status/confidence disagrees with observations")
        return self


class TargetIdentity(IdentityEvidence):
    segments: dict[str, IdentityEvidence] = Field(default_factory=dict)

    @model_validator(mode="after")
    def consistent_primary(self) -> TargetIdentity:
        if self.segments:
            if self.expected is None or not self.expected.explicit_target or "op" not in self.segments:
                raise ValueError("segment identity requires a declared target and op segment")
            primary = self.segments["op"]
            if (self.status, self.confidence, self.observed) != (primary.status, primary.confidence, primary.observed):
                raise ValueError("primary identity disagrees with op segment")
        return self


def _identity(expected: ExpectedTarget | None, records: list[dict]) -> IdentityEvidence:
    observations = []
    for record in records:
        if expected is not None:
            rule = identity_match_rule(expected, record["name"])
            record = {**record, "match_rule": rule, "status": "match" if rule != "unmatched" else "mismatch"}
        observations.append(IdentityObservation.model_validate(record))
    observed = tuple(observations)
    status, confidence = identity_state(expected, observed)
    return IdentityEvidence(status=status, expected=expected, observed=observed, confidence=confidence)


def build_target_identity(headlines: dict[str, TimingEvidence | OperatorEvidence], coverage: ProfileCoverage | None,
                          expected: ExpectedTarget | None, *, segment_sources: dict[str, SourceRef]) -> TargetIdentity:
    if expected is not None and expected.explicit_target:
        if coverage is None:
            raise ValueError("declared target identity requires coverage")
        if expected.counts != coverage.expected_counts:
            raise ValueError("declared identity counts disagree with program coverage")
        segments = {}
        for name, segment in coverage.segments.items():
            # An unbound follow-up has no declared expectation. The primary op
            # identity still records the intended program when collection failed.
            segment_expected = expected if name == "op" else None
            if segment.expected_counts:
                source = segment_sources.get(name)
                segment_expected = ExpectedTarget(
                    names=tuple(segment.expected_display_names.get(key) or key for key in segment.expected_counts),
                    counts=dict(segment.expected_counts), artifact=source.artifact if source else expected.artifact,
                    field_ref=source.field if source else expected.field_ref, explicit_target=True,
                )
            records = [{"group": "op_summary" if name == "app" else "op_basic_info", "name": item.name,
                        "artifact": item.artifacts[0], "field_ref": f"profile_coverage.segments.{name}.observed_names", "count": item.count}
                       for item in segment.observed_names]
            segments[name] = _identity(segment_expected, records)
        primary = segments["op"]
        return TargetIdentity(status=primary.status, expected=expected, observed=primary.observed,
                              confidence=primary.confidence, segments=segments)
    records = []
    for group in ("op_basic_info", "op_summary", "task_time"):
        item = headlines.get(group)
        if isinstance(item, OperatorEvidence):
            for artifact in item.artifacts:
                for metadata in artifact.metadata:
                    if metadata.metric == "name":
                        records.append({"group": group, "name": metadata.value, "artifact": artifact.artifact,
                                        "field_ref": f"headlines.{group}.artifacts.metadata; record={metadata.source.record}; column={metadata.source.column}"})
        elif isinstance(item, TimingEvidence):
            for artifact in item.artifacts:
                for observation in artifact.observations:
                    if observation.name and observation.name.lower() != "n/a":
                        records.append({"group": group, "name": observation.name, "artifact": artifact.artifact,
                                        "field_ref": f"headlines.{group}.artifacts.observations.name"})
    identity = _identity(expected, records)
    return TargetIdentity(status=identity.status, expected=expected, observed=identity.observed, confidence=identity.confidence)


def target_identity_warnings(identity: TargetIdentity) -> list[str]:
    if identity.expected is None:
        return []
    expected_names = ", ".join(identity.expected.names)
    if identity.status in {"mismatch", "partial_mismatch"}:
        mismatched_names = ", ".join(item.name for item in identity.observed if item.status != "match")
        return [f"target identity {identity.status}: expected {expected_names}; observed {mismatched_names or 'none'}"]
    if identity.status == "missing_observed":
        return [f"target identity missing observed profiler operator: expected {expected_names}"]
    return []
