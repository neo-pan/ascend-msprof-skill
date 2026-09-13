"""Persistent evidence envelopes and their structural invariants (no I/O)."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, JsonValue, model_validator

from .readiness_types import CollectionAction, EvidenceReadiness
from .analysis_types import AnalysisDimension, EvidenceRelation
from .coverage_types import ProfileCoverage, validate_coverage_facts
from .identity_types import TargetIdentity, build_target_identity
from .evidence_types import ArtifactPath, EvidenceFact
from .collection_receipts import CollectionReceipts
from .collection_context import AnalysisContext
from ._profile_target import expected_counts
from ._profiler_segments import stdout_profile_output_segment, operator_launch_metadata
from pathlib import Path
from ._profile_target import normalize_target_name
from .application_timing import TimingEvidence
from .operator_evidence import OperatorArtifact, OperatorEvidence, OPERATOR_GROUPS
from .metric_scope_policy import APP_TIMING_ARTIFACTS, normalize_metric_scope


class SelectedMetricScope(EvidenceFact):
    value: str = Field(min_length=1)
    artifact: ArtifactPath
    field_ref: Literal["--aic-metrics"] = "--aic-metrics"

    @model_validator(mode="after")
    def normalized_scope(self) -> SelectedMetricScope:
        if normalize_metric_scope(self.value) != self.value:
            raise ValueError("metric scope must use its normalized command spelling")
        return self


class StdoutMessage(EvidenceFact):
    message: str = Field(min_length=1)
    ordinal: int | None = Field(default=None, ge=0)


class StdoutSection(EvidenceFact):
    source: ArtifactPath
    section: Literal["Occupancy Summary Report", "RoofLine Summary Report", "Performance Summary Report"]
    messages: Annotated[tuple[StdoutMessage, ...], Field(strict=False, min_length=1)]

    @model_validator(mode="after")
    def section_ordinals(self) -> StdoutSection:
        numbered = self.section != "RoofLine Summary Report"
        if any((message.ordinal is not None) != numbered for message in self.messages):
            raise ValueError("stdout message ordinal disagrees with section format")
        return self


class StdoutSections(EvidenceFact):
    occupancy_summary: StdoutSection | None = None
    roofline_summary: StdoutSection | None = None
    performance_summary: StdoutSection | None = None

    @model_validator(mode="after")
    def section_names(self) -> StdoutSections:
        for key, name in (("occupancy_summary", "Occupancy Summary Report"),
                          ("roofline_summary", "RoofLine Summary Report"),
                          ("performance_summary", "Performance Summary Report")):
            item = getattr(self, key)
            if item is not None and item.section != name:
                raise ValueError("stdout section name disagrees with summary key")
        return self


class IndexedArtifact(EvidenceFact):
    artifact: ArtifactPath
    group: str
    parser: Literal["csv", "json", "stdout", "none"]
    segment: str
    metric_scope: str | None
    status: Literal["parsed", "empty", "invalid", "unparsed"]
    columns: Annotated[tuple[str, ...], Field(strict=False)]
    row_count: int = Field(ge=0)
    # Samples retain raw JSON/CSV/text payloads and never establish metric facts.
    sample_rows: Annotated[tuple[JsonValue, ...], Field(strict=False)]
    warnings: Annotated[tuple[str, ...], Field(strict=False)]
    canonical_stem: str | None = None
    opprof_root: ArtifactPath | None = None
    kernel_directory: str | None = None
    launch_directory: str | None = None
    launch_ordinal: str | None = None
    launch_key: str | None = None
    target_name: str | None = None
    normalized_target_name: str | None = None
    duration_us: FiniteFloat | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    known_role: str | None = None
    diagnosis_role: Literal["not_used"] | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def consistent_inventory(self) -> IndexedArtifact:
        if self.status == "parsed" and self.row_count == 0:
            raise ValueError("parsed artifact must contain records")
        if self.status == "empty" and self.row_count != 0:
            raise ValueError("empty artifact cannot contain records")
        if len(self.sample_rows) > min(5, self.row_count):
            raise ValueError("samples exceed the bounded recorded inventory")
        if (self.parser == "none") != (self.status == "unparsed"):
            raise ValueError("unparsed artifacts require parser=none")
        if self.canonical_stem is not None:
            layout = operator_launch_metadata(self.artifact, self.segment)
            for field in ('opprof_root', 'kernel_directory', 'launch_directory'):
                if getattr(self, field) != layout.get(field):
                    raise ValueError('operator layout disagrees with artifact path')
            ordinal = layout.get('launch_ordinal', 'flat' if self.launch_key is not None else None)
            if self.launch_ordinal != ordinal:
                raise ValueError('launch ordinal disagrees with recorded layout')
            if 'launch_key' in layout and self.launch_key != layout['launch_key']:
                raise ValueError('nested launch key disagrees with artifact path')
        if self.normalized_target_name is not None:
            if not self.target_name or normalize_target_name(self.target_name) != self.normalized_target_name:
                raise ValueError("normalized target name disagrees with recorded name")
        return self


class RawArtifactIndex(EvidenceFact):
    raw_artifact_index_schema_version: Literal["1.1"]
    artifacts: Annotated[tuple[IndexedArtifact, ...], Field(strict=False)]
    warnings: Annotated[tuple[str, ...], Field(strict=False)]

    @model_validator(mode="after")
    def unique_inventory(self) -> RawArtifactIndex:
        keys = [(item.artifact, item.group, item.parser) for item in self.artifacts]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate raw artifact inventory entry")
        return self


class FrequencyObservation(EvidenceFact):
    artifact: ArtifactPath
    launch_key: str | None
    current_frequency_mhz: FiniteFloat | None
    rated_frequency_mhz: FiniteFloat | None
    current_frequency_field_ref: str | None
    rated_frequency_field_ref: str | None

    @model_validator(mode="after")
    def sourced_values(self) -> FrequencyObservation:
        if self.current_frequency_mhz is None and self.rated_frequency_mhz is None:
            raise ValueError("frequency observation requires a recorded value")
        for value, source in ((self.current_frequency_mhz, self.current_frequency_field_ref),
                              (self.rated_frequency_mhz, self.rated_frequency_field_ref)):
            if (value is not None) != bool(source):
                raise ValueError("frequency value and source must be present together")
        return self


def frequency_statistics(observations: tuple[FrequencyObservation, ...]) -> dict:
    current = tuple(sorted({item.current_frequency_mhz for item in observations
                            if item.current_frequency_mhz is not None}))
    rated = tuple(sorted({item.rated_frequency_mhz for item in observations
                          if item.rated_frequency_mhz is not None}))
    return {
        "launch_count": len(observations),
        "current_frequencies_mhz": current,
        "rated_frequencies_mhz": rated,
        "below_rated_launch_count": sum(item.current_frequency_mhz < item.rated_frequency_mhz
                                       for item in observations
                                       if item.current_frequency_mhz is not None and item.rated_frequency_mhz is not None),
        "mixed_frequency": len(current) > 1,
    }


class FrequencyGroup(EvidenceFact):
    segment: str
    target: str
    launch_count: int = Field(ge=1)
    current_frequencies_mhz: Annotated[tuple[FiniteFloat, ...], Field(strict=False)]
    rated_frequencies_mhz: Annotated[tuple[FiniteFloat, ...], Field(strict=False)]
    below_rated_launch_count: int = Field(ge=0)
    mixed_frequency: bool
    observations: Annotated[tuple[FrequencyObservation, ...], Field(strict=False)]

    @model_validator(mode="after")
    def consistent_statistics(self) -> FrequencyGroup:
        if len({item.artifact for item in self.observations}) != len(self.observations):
            raise ValueError("duplicate artifact in frequency group")
        for field, expected in frequency_statistics(self.observations).items():
            if getattr(self, field) != expected:
                raise ValueError(f"frequency {field} disagrees with observations")
        return self


def frequency_warnings(groups: tuple[FrequencyGroup, ...]) -> tuple[str, ...]:
    return tuple(
        "measurement quality: frequency variation observed for "
        f"segment={item.segment} target={item.target}; below_rated_launch_count={item.below_rated_launch_count}, "
        f"mixed_frequency={str(item.mixed_frequency).lower()}"
        for item in groups if item.below_rated_launch_count or item.mixed_frequency
    )


class FrequencyQuality(EvidenceFact):
    status: Literal["observed", "not_available"]
    groups: Annotated[tuple[FrequencyGroup, ...], Field(strict=False)]
    warnings: Annotated[tuple[str, ...], Field(strict=False)]
    evidence_role: Literal["measurement_quality_context_only"] = "measurement_quality_context_only"

    @model_validator(mode="after")
    def consistent_quality(self) -> FrequencyQuality:
        keys = [(item.segment, item.target) for item in self.groups]
        if keys != sorted(set(keys)):
            raise ValueError("frequency groups must be unique and sorted by segment/target")
        if self.status != ("observed" if self.groups else "not_available"):
            raise ValueError("frequency status disagrees with observations")
        if self.warnings != frequency_warnings(self.groups):
            raise ValueError("frequency warnings disagree with observations")
        return self


class MeasurementQuality(EvidenceFact):
    frequency: FrequencyQuality


class SummaryFacts(EvidenceFact):
    """Inputs established before deriving analysis projections."""
    headlines: dict[str, TimingEvidence | OperatorEvidence]
    stdout_sections: StdoutSections
    metric_scope: SelectedMetricScope | None
    collection_receipts: CollectionReceipts
    analysis_context: AnalysisContext
    profile_coverage: ProfileCoverage
    target_identity: TargetIdentity
    measurement_quality: MeasurementQuality
    warnings: Annotated[tuple[str, ...], Field(strict=False)]

    @model_validator(mode="after")
    def consistent_facts(self) -> SummaryFacts:
        validate_receipt_admission(self, self.collection_receipts)
        if self.target_identity.expected != self.analysis_context.expected_target:
            raise ValueError("target identity disagrees with consumed context")
        declared = self.analysis_context.declared_target
        target = declared.target if declared is not None else None
        if (self.profile_coverage.kernel_selector != (target.kernel_selector if target is not None else None)
                or self.profile_coverage.expected_counts != expected_counts(target)):
            raise ValueError("coverage target disagrees with consumed context")
        validate_context_binding(self, self.collection_receipts.excluded_segments)
        if set(self.headlines) != {*APP_TIMING_ARTIFACTS, *OPERATOR_GROUPS}:
            raise ValueError("summary must contain every normalized headline group")
        for group, headline in self.headlines.items():
            if group != headline.group:
                raise ValueError("headline key and group disagree")
        if self.target_identity != build_target_identity(self.headlines, self.profile_coverage, self.target_identity.expected,
                                                         segment_sources=self.analysis_context.segment_target_sources):
            raise ValueError("target identity disagrees with normalized profiler observations")
        basic = self.headlines.get("op_basic_info")
        artifacts = {item.artifact: item for item in basic.artifacts} if basic is not None else {}
        expected_paths = {path for path, artifact in artifacts.items()
                          if frequency_observation(artifact, None) is not None}
        observed_paths = []
        for group in self.measurement_quality.frequency.groups:
            for observation in group.observations:
                artifact = artifacts.get(observation.artifact)
                if (artifact is None or artifact.segment != group.segment
                        or frequency_observation(artifact, observation.launch_key) != observation):
                    raise ValueError("frequency quality disagrees with admitted operator observations")
                observed_paths.append(observation.artifact)
        if set(observed_paths) != expected_paths or len(observed_paths) != len(expected_paths):
            raise ValueError("frequency inventory disagrees with admitted operator observations")
        return self


class Summary(SummaryFacts):
    analysis_schema_version: Literal["5.0"]
    analysis_dimensions: Annotated[tuple[AnalysisDimension, ...], Field(strict=False)]
    evidence_relations: Annotated[tuple[EvidenceRelation, ...], Field(strict=False)]
    next_collection_actions: Annotated[tuple[CollectionAction, ...], Field(strict=False)]
    evidence_readiness: EvidenceReadiness

    @model_validator(mode="after")
    def consistent_analysis(self) -> Summary:
        from ._evidence_signals import build_profiler_dimensions
        from ._evidence_readiness import validate_readiness_state
        from ._evidence_relations import validate_relation_facts
        if sum(item.id == "source_pipeline_context" for item in self.analysis_dimensions) != 1:
            raise ValueError("summary requires exactly one source pipeline context dimension")
        validate_receipt_dimensions(self.analysis_dimensions, self.collection_receipts)
        dimensions = tuple(item for item in self.analysis_dimensions if item.id != "source_pipeline_context")
        if dimensions != build_profiler_dimensions(self.headlines):
            raise ValueError("analysis dimensions disagree with normalized profiler observations")
        validate_readiness_state(self)
        validate_relation_facts(self)
        return self


def load_summary(payload: object) -> Summary:
    return Summary.model_validate(payload)


def validate_receipt_admission(summary: SummaryFacts, receipts: CollectionReceipts) -> None:
    for group in summary.headlines.values():
        if any(not receipts.allows(item.segment) for item in group.artifacts):
            raise ValueError("headline artifacts are excluded by collection receipts")
    for name in StdoutSections.model_fields:
        section = getattr(summary.stdout_sections, name)
        if section is not None:
            segment = stdout_profile_output_segment(Path(section.source))
            if segment is not None and not receipts.allows(segment):
                raise ValueError("stdout section is excluded by collection receipts")


def validate_receipt_dimensions(dimensions: tuple[AnalysisDimension, ...], receipts: CollectionReceipts) -> None:
    if not receipts.allows("simulator") and any(
            item.signals for item in dimensions if item.id == "source_pipeline_context"):
        raise ValueError("simulator signals are excluded by collection receipts")


def validate_context_binding(summary: SummaryFacts, excluded_segments: set[str]) -> None:
    from ._evidence_artifacts import bind_segment_targets
    from .coverage_types import TargetScope, segment_target_scope
    declared = summary.analysis_context.declared_target
    target = declared.target if declared is not None else None
    bound = bind_segment_targets(summary.analysis_context.workflow,
        set(summary.profile_coverage.segments) - {"app"}, target, excluded_segments)
    for segment, coverage in summary.profile_coverage.segments.items():
        expected = segment_target_scope(target if segment == "app" else bound.get(segment), target)
        if coverage.target_scope != TargetScope.model_validate(expected):
            raise ValueError("segment target scope disagrees with consumed context and receipts")


def validate_summary_index(summary: Summary, index: RawArtifactIndex | None, excluded_segments: set[str]) -> None:
    """Cross-check the recorded run-relative inventory; do not reopen raw files."""
    from .operator_evidence import OperatorEvidence, OPERATOR_GROUPS
    normalized_groups = (*APP_TIMING_ARTIFACTS, *OPERATOR_GROUPS)
    validate_context_binding(summary, excluded_segments)
    timings = [item for item in summary.headlines.values() if isinstance(item, (TimingEvidence, OperatorEvidence))]
    if index is None:
        coverage = summary.profile_coverage
        app = summary.headlines.get("op_summary")
        if coverage is not None:
            validate_coverage_facts(coverage, app.artifacts if app is not None else (), None, excluded_segments)
        return
    records = tuple(item for item in index.artifacts if item.segment not in excluded_segments)
    from ._evidence_readiness import validate_readiness_inventory
    validate_readiness_inventory(summary, RawArtifactIndex(
        raw_artifact_index_schema_version=index.raw_artifact_index_schema_version,
        artifacts=records, warnings=index.warnings))
    sections = summary.stdout_sections
    for key in StdoutSections.model_fields:
        section = getattr(sections, key)
        if section is None:
            continue
        indexed = next((item for item in records
                        if item.group == f"stdout_{key}" and item.artifact == section.source), None)
        if (indexed is None or indexed.parser != "stdout" or indexed.status != "parsed"
                or indexed.row_count != len(section.messages)
                or indexed.sample_rows != tuple(message.model_dump(mode="json", exclude_unset=True)
                                                for message in section.messages[:5])):
            raise ValueError("stdout section disagrees with admitted raw inventory")
    admitted_groups = {item.group for item in records if item.group in normalized_groups}
    if admitted_groups - {item.group for item in timings}:
        raise ValueError("admitted raw timing groups are missing from summary")
    for timing in timings:
        indexed = [item for item in records if item.group == timing.group]
        if sorted(item.artifact for item in indexed) != sorted(item.artifact for item in timing.artifacts):
            raise ValueError(f"{timing.group} artifacts disagree between summary and raw index")
        by_path = {item.artifact: item for item in indexed}
        for artifact in timing.artifacts:
            item = by_path[artifact.artifact]
            for field in ("group", "parser", "segment", "metric_scope", "status", "row_count", "columns"):
                if getattr(item, field) != getattr(artifact, field):
                    raise ValueError(f"{artifact.artifact}: raw index {field} disagrees with summary")
            if isinstance(artifact, OperatorArtifact) and artifact.group == "op_basic_info":
                if item.target_name != artifact.launch_name:
                    raise ValueError(f"{artifact.artifact}: indexed launch name disagrees with operator metadata")
                if artifact.status == "parsed" and artifact.row_count == 1:
                    duration = artifact.launch_counts[0].duration_us if artifact.launch_counts else None
                    if item.duration_us != duration:
                        raise ValueError(f"{artifact.artifact}: indexed duration disagrees with operator observations")
    basic = summary.headlines.get("op_basic_info")
    expected = build_frequency_measurement_quality(records, basic.artifacts if basic is not None else ())
    if summary.measurement_quality.frequency != expected:
        raise ValueError("frequency quality disagrees with admitted operator observations")
    coverage = summary.profile_coverage
    app = summary.headlines.get("op_summary")
    if coverage is not None:
        validate_coverage_facts(coverage, app.artifacts if app is not None else (), index.artifacts, excluded_segments)


def frequency_observation(artifact: OperatorArtifact, launch_key: str | None) -> FrequencyObservation | None:
    if artifact.status != "parsed" or artifact.row_count != 1:
        return None
    by_metric = {observation.metric.lower(): observation for observation in artifact.observations}
    current = by_metric.get("current freq")
    rated = by_metric.get("rated freq")
    if current is None and rated is None:
        return None

    def field_ref(observation):
        return (f"headlines.op_basic_info.artifacts.observations; record={observation.source.record}; "
                f"column={observation.source.column}; field={observation.source.field}") if observation else None

    return FrequencyObservation(
        artifact=artifact.artifact, launch_key=launch_key,
        current_frequency_mhz=current.value if current else None,
        rated_frequency_mhz=rated.value if rated else None,
        current_frequency_field_ref=field_ref(current), rated_frequency_field_ref=field_ref(rated),
    )


def build_frequency_measurement_quality(indexed_artifacts: tuple[IndexedArtifact, ...], basic_artifacts: tuple[OperatorArtifact, ...]) -> FrequencyQuality:
    grouped: dict[tuple[str, str], list[FrequencyObservation]] = {}
    indexed = {item.artifact: item for item in indexed_artifacts}
    for artifact in basic_artifacts:
        item = indexed.get(artifact.artifact)
        if item is None:
            continue
        observation = frequency_observation(artifact, item.launch_key)
        if observation is None:
            continue
        target = item.normalized_target_name or artifact.launch_name or "unknown"
        grouped.setdefault((artifact.segment, target), []).append(observation)

    groups = tuple(FrequencyGroup(segment=segment, target=target, observations=tuple(observations),
                                  **frequency_statistics(tuple(observations)))
                   for (segment, target), observations in sorted(grouped.items()))
    return FrequencyQuality(status="observed" if groups else "not_available",
                            groups=groups, warnings=frequency_warnings(groups))
