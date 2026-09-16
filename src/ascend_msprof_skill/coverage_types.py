"""Recorded launch coverage and its pure consistency rules."""
from __future__ import annotations

from typing import Annotated, Literal, Iterable, TYPE_CHECKING
from pathlib import PurePosixPath as Path

from pydantic import Field, FiniteFloat, model_validator

from .ascend_profile_utils import to_float
from ._profile_target import TargetSelection, match_expected_names, match_expected_name, normalize_target_name, expected_counts, expected_display_names
from .operator_evidence import OPERATOR_GROUPS

if TYPE_CHECKING:
    from .summary_types import IndexedArtifact
from .evidence_types import ArtifactPath, EvidenceFact, ArtifactRecord

Count = Annotated[int, Field(ge=0)]
PositiveCount = Annotated[int, Field(ge=1)]
Completeness = Literal["complete", "incomplete", "unverified"]


def completeness(complete: bool | None) -> str:
    return "unverified" if complete is None else "complete" if complete else "incomplete"


def metric_complete(launch_complete: bool | None, missing_counts: Iterable[int]) -> bool | None:
    return None if launch_complete is None else launch_complete and not any(missing_counts)


def coverage_identity_status(launch_complete: bool | None, observed_total: int) -> str:
    return "not_applicable" if launch_complete is None else "match" if launch_complete else "missing_observed" if not observed_total else "mismatch"


def count_differences(expected: dict[str, int], observed: dict[str, int]) -> tuple[dict[str, int], dict[str, int]]:
    missing = {name: count - observed.get(name, 0) for name, count in expected.items() if observed.get(name, 0) < count}
    over = {name: observed[name] - count for name, count in expected.items() if observed.get(name, 0) > count}
    return missing, over


def count_complete(expected_total: int | None, expected: dict[str, int], observed: dict[str, int],
                   authority_complete: bool, extra: dict[str, int]) -> bool | None:
    if expected_total is None:
        return None
    missing, over = count_differences(expected, observed)
    return authority_complete and not missing and not over and not extra and sum(observed.values()) == expected_total


def declared_launches_present(segment: "SegmentCoverage") -> bool:
    """Expected launch counts are present. Unmatched extras do not clear this."""
    return bool(
        segment.expected_total is not None
        and segment.authority_complete
        and not segment.missing_counts
        and not segment.over_counts
    )


class TargetScope(EvidenceFact):
    kind: Literal["observed_run", "complete_program", "focused_subset"]
    kernel_selector: str | None = None
    expected_counts: dict[str, PositiveCount] = Field(default_factory=dict)
    expected_total: PositiveCount | None = None

    @model_validator(mode="after")
    def consistent_target(self) -> TargetScope:
        if self.kind == "observed_run":
            if self.kernel_selector is not None or self.expected_counts or self.expected_total is not None:
                raise ValueError("observed-run scope cannot declare expected launches")
        elif not self.kernel_selector or not self.expected_counts or self.expected_total != sum(self.expected_counts.values()):
            raise ValueError("declared scope requires selector and consistent expected launches")
        return self


class CoverageIdentity(EvidenceFact):
    status: Literal["not_applicable", "match", "missing_observed", "mismatch"]


class ObservedLaunchName(EvidenceFact):
    name: str
    normalized_name: str
    count: PositiveCount
    match_rule: Literal["unmatched", "exact", "known_suffix"]
    expected_normalized_name: str | None
    artifacts: Annotated[tuple[ArtifactPath, ...], Field(strict=False, min_length=1)]


class TargetMetricCoverage(EvidenceFact):
    expected: PositiveCount
    covered: Count
    missing: Count

    @model_validator(mode="after")
    def consistent_missing(self) -> TargetMetricCoverage:
        if self.missing != max(0, self.expected - self.covered):
            raise ValueError("missing metric launches disagree with counts")
        return self


class MetricCoverage(EvidenceFact):
    required_stems: Annotated[tuple[str, ...], Field(strict=False)]
    covered_launches: Count
    expected_launches: PositiveCount | None
    covered_by_target: dict[str, PositiveCount]
    by_target: dict[str, TargetMetricCoverage]
    complete: bool | None
    completeness: Completeness

    @model_validator(mode="after")
    def consistent_counts(self) -> MetricCoverage:
        if self.covered_launches != sum(self.covered_by_target.values()):
            raise ValueError("metric covered total disagrees with target counts")
        expected = sum(item.expected for item in self.by_target.values()) if self.expected_launches is not None else None
        if self.expected_launches != expected or (expected is None and self.by_target):
            raise ValueError("metric expected total disagrees with target counts")
        if any(item.covered != self.covered_by_target.get(name, 0) for name, item in self.by_target.items()):
            raise ValueError("metric per-target covered counts disagree")
        if self.completeness != completeness(self.complete):
            raise ValueError("metric completeness disagrees with status")
        return self


class SegmentCoverage(EvidenceFact):
    counting_authority: str
    authority_complete: bool
    expected_total: PositiveCount | None
    expected_counts: dict[str, PositiveCount]
    expected_display_names: dict[str, str]
    observed_total: Count
    observed_counts: dict[str, PositiveCount]
    observed_names: Annotated[tuple[ObservedLaunchName, ...], Field(strict=False)]
    missing_counts: dict[str, PositiveCount]
    over_counts: dict[str, PositiveCount]
    extra_counts: dict[str, PositiveCount]
    count_complete: bool | None
    completeness: Completeness
    duration_total_us: FiniteFloat | None
    duration_by_target_us: dict[str, FiniteFloat | None]
    artifacts: Annotated[tuple[ArtifactPath, ...], Field(strict=False)]
    ambiguities: Annotated[tuple[str, ...], Field(strict=False)]
    metric_coverage: dict[str, MetricCoverage] = Field(default_factory=dict)
    target_scope: TargetScope
    target_identity: CoverageIdentity

    @model_validator(mode="after")
    def consistent_coverage(self) -> SegmentCoverage:
        explicit = self.expected_total is not None
        if self.expected_total != (sum(self.expected_counts.values()) if explicit else None):
            raise ValueError("expected launch total disagrees with counts")
        if set(self.expected_display_names) != set(self.expected_counts):
            raise ValueError("expected display names disagree with target counts")
        if self.observed_total != sum(self.observed_counts.values()):
            raise ValueError("observed launch total disagrees with counts")
        observed: dict[str, int] = {}
        extra: dict[str, int] = {}
        for item in self.observed_names:
            if (item.expected_normalized_name, item.match_rule) != match_expected_names(self.expected_display_names, item.name):
                raise ValueError("observed name match disagrees with declared target")
            if item.normalized_name != (normalize_target_name(item.name) or "missing_name"):
                raise ValueError("observed normalized name disagrees with recorded name")
            key = item.expected_normalized_name or item.normalized_name
            observed[key] = observed.get(key, 0) + item.count
            if explicit and item.expected_normalized_name is None:
                extra[item.normalized_name] = extra.get(item.normalized_name, 0) + item.count
            if not set(item.artifacts) <= set(self.artifacts):
                raise ValueError("observed name source is outside segment inventory")
        if observed != self.observed_counts or extra != self.extra_counts:
            raise ValueError("observed/extra counts disagree with recorded names")
        if (self.missing_counts, self.over_counts) != count_differences(self.expected_counts, self.observed_counts):
            raise ValueError("missing/over counts disagree with launches")
        complete = count_complete(self.expected_total, self.expected_counts, self.observed_counts,
                                  self.authority_complete, self.extra_counts)
        if self.count_complete != complete or self.completeness != completeness(complete):
            raise ValueError("launch completeness disagrees with authority and counts")
        if set(self.duration_by_target_us) != set(self.observed_counts):
            raise ValueError("duration target keys disagree with observed launches")
        durations = tuple(self.duration_by_target_us.values())
        total = to_float(sum(durations)) if all(value is not None for value in durations) else None
        if self.duration_total_us != total:
            raise ValueError("duration total disagrees with per-target durations")
        if self.expected_counts != self.target_scope.expected_counts or self.expected_total != self.target_scope.expected_total:
            raise ValueError("segment expected launches disagree with target scope")
        identity = coverage_identity_status(complete, self.observed_total)
        if self.target_identity.status != identity:
            raise ValueError("coverage identity disagrees with launch counts")
        for metric in self.metric_coverage.values():
            if metric.expected_launches != self.expected_total or {name: item.expected for name, item in metric.by_target.items()} != self.expected_counts:
                raise ValueError("metric expected launches disagree with segment")
            if any(count > self.observed_counts.get(name, 0) for name, count in metric.covered_by_target.items()):
                raise ValueError("metric coverage exceeds observed launches")
            expected_complete = metric_complete(complete, (item.missing for item in metric.by_target.values()))
            if metric.complete != expected_complete:
                raise ValueError("metric completeness disagrees with segment authority")
        return self


def select_coverage_segments(segments: dict[str, SegmentCoverage]) -> dict[str, str | None]:
    families = tuple(METRIC_FAMILY_STEMS)
    order = sorted((name for name in segments if name != "app"), key=lambda name: (name != "op", name))
    return {family: next((name for name in order
                          if segments[name].target_scope.kind == "complete_program" and segments[name].count_complete
                          and family in segments[name].metric_coverage and segments[name].metric_coverage[family].complete), None)
            for family in families}


class ProfileCoverage(EvidenceFact):
    schema_version: Literal["1.1"]
    explicit_target: bool
    kernel_selector: str | None
    expected_total: PositiveCount | None
    expected_counts: dict[str, PositiveCount]
    segments: dict[str, SegmentCoverage]
    selected_segments_by_family: dict[str, str | None]
    measurement_boundary: str

    @model_validator(mode="after")
    def consistent_program(self) -> ProfileCoverage:
        scope = TargetScope(kind="complete_program" if self.explicit_target else "observed_run",
                            kernel_selector=self.kernel_selector, expected_counts=self.expected_counts,
                            expected_total=self.expected_total)
        if "app" not in self.segments or "op" not in self.segments:
            raise ValueError("coverage must record app and op segments")
        for name, segment in self.segments.items():
            if name == "app" or segment.target_scope.kind == "complete_program":
                if segment.expected_counts != scope.expected_counts or segment.target_scope.kernel_selector != scope.kernel_selector:
                    raise ValueError("complete-program segment differs from declared target")
            if segment.target_scope.kind == "focused_subset" and any(count > scope.expected_counts.get(key, 0) for key, count in segment.expected_counts.items()):
                raise ValueError("focused segment exceeds declared program target")
        if self.selected_segments_by_family != select_coverage_segments(self.segments):
            raise ValueError("selected coverage segments disagree with complete-program coverage")
        return self


def validate_coverage_facts(coverage: ProfileCoverage, app_artifacts: tuple[ArtifactRecord, ...],
                            indexed_artifacts: tuple[IndexedArtifact, ...] | None, excluded_segments: set[str]) -> None:
    """Verify recorded coverage using the same derivation as analyze, without I/O.

    The declared target is input context. Counts and metric coverage must agree
    with normalized profiler observations even if internally consistent alone.
    """
    def target_for(segment: SegmentCoverage) -> TargetSelection | None:
        if segment.target_scope.kind == "observed_run":
            return None
        return TargetSelection(kernel_selector=segment.target_scope.kernel_selector,
            expected_launches=[{"name": segment.expected_display_names[name], "count": count}
                               for name, count in segment.expected_counts.items()])

    target = target_for(coverage.segments["app"])
    if indexed_artifacts is None:
        app = _app_coverage(tuple(item for item in app_artifacts if item.segment == "app"), target)
        _attach_segment_target_metadata(app, target, target)
        if coverage.segments["app"] != SegmentCoverage.model_validate(app):
            raise ValueError("application coverage disagrees with normalized timing observations")
        return
    segment_targets = {name: segment_target for name, segment in coverage.segments.items()
                       if name != "app" and (segment_target := target_for(segment)) is not None}
    expected = build_profile_coverage(indexed_artifacts, target_for(coverage.segments["app"]),
                                     app_artifacts=app_artifacts, segment_targets=segment_targets,
                                     excluded_segments=excluded_segments)
    if expected.segments != coverage.segments:
        raise ValueError("profile coverage disagrees with normalized profiler observations")


METRIC_FAMILY_STEMS = {
    "pipe_utilization": ("PipeUtilization",),
    "arithmetic_utilization": ("ArithmeticUtilization",),
    "l2_cache": ("L2Cache",),
    "memory": ("Memory", "MemoryL0", "MemoryUB"),
    "resource_conflict": ("ResourceConflictRatio",),
}


def _app_tree(record: dict) -> str | None:
    artifact = Path(str(record.get("artifact") or ""))
    parts = artifact.parts
    for index, part in enumerate(parts):
        if part.startswith("PROF_"):
            return Path(*parts[: index + 1]).as_posix()
    return None


def _coverage_counts(
    observations: list[dict],
    target: TargetSelection | None,
    *,
    authority: str,
    authority_complete: bool,
    artifacts: list[str],
    ambiguities: list[str],
) -> dict:
    expected = expected_counts(target)
    display_names = expected_display_names(target)
    observed_counts: dict[str, int] = {}
    duration_by_target: dict[str, float | None] = {}
    observed_names: dict[str, dict] = {}
    extra_counts: dict[str, int] = {}
    for observation in observations:
        raw_name = str(observation.get("name") or "")
        observed_norm = normalize_target_name(raw_name) or "missing_name"
        matched, rule = match_expected_name(target, raw_name)
        key = matched or observed_norm
        observed_counts[key] = observed_counts.get(key, 0) + observation.get("count", 1)
        duration = observation.get("duration_us")
        previous = duration_by_target.get(key, 0.0)
        duration_by_target[key] = (
            to_float(previous + duration)
            if previous is not None and isinstance(duration, (int, float)) else None
        )
        name_record = observed_names.setdefault(
            observed_norm,
            {
                "name": raw_name or "missing",
                "normalized_name": observed_norm,
                "count": 0,
                "match_rule": rule,
                "expected_normalized_name": matched,
                "artifacts": [],
            },
        )
        name_record["count"] += observation.get("count", 1)
        artifact = observation.get("artifact")
        if artifact and artifact not in name_record["artifacts"]:
            name_record["artifacts"].append(artifact)
        if target is not None and matched is None:
            extra_counts[observed_norm] = extra_counts.get(observed_norm, 0) + observation.get("count", 1)

    missing_counts, over_counts = count_differences(expected, observed_counts)
    explicit = target is not None
    complete = count_complete(sum(expected.values()) if explicit else None, expected,
                                          observed_counts, authority_complete, extra_counts)
    return {
        "counting_authority": authority,
        "authority_complete": authority_complete,
        "expected_total": sum(expected.values()) if explicit else None,
        "expected_counts": expected,
        "expected_display_names": display_names,
        "observed_total": sum(observed_counts.values()),
        "observed_counts": observed_counts,
        "observed_names": sorted(observed_names.values(), key=lambda item: item["normalized_name"]),
        "missing_counts": missing_counts,
        "over_counts": over_counts,
        "extra_counts": extra_counts,
        "count_complete": complete,
        "completeness": completeness(complete),
        "duration_total_us": (
            to_float(sum(duration_by_target.values()))
            if all(value is not None for value in duration_by_target.values()) else None
        ),
        "duration_by_target_us": duration_by_target,
        "artifacts": sorted(set(artifacts)),
        "ambiguities": ambiguities,
    }


def _app_coverage(records: tuple[ArtifactRecord, ...], target: TargetSelection | None) -> dict:
    trees = {_app_tree({"artifact": item.artifact}) for item in records}
    ambiguities = []
    if None in trees:
        ambiguities.append("app op_summary is not inside a recorded PROF_* tree")
    resolved_trees = trees - {None}
    if len(resolved_trees) != 1:
        ambiguities.append(f"expected one app PROF_* tree, observed {len(resolved_trees)}")
    if len(records) != 1:
        ambiguities.append(f"expected one app op_summary, observed {len(records)}")
    authority_complete = len(resolved_trees) == 1 and len(records) == 1 and not ambiguities
    observations = []
    if authority_complete:
        record = records[0]
        if record.status != "parsed" or any(not count.name for count in record.launch_counts):
            ambiguities.append("authoritative app op_summary did not parse to reliable non-empty launch rows")
            authority_complete = False
        else:
            observations = [{"name": item.name, "count": item.count, "duration_us": item.duration_us,
                             "artifact": record.artifact} for item in record.launch_counts]
    return _coverage_counts(observations, target,
        authority="one parsed row per launch from the single recorded app op_summary_*.csv; Calls ignored",
        authority_complete=authority_complete, artifacts=[item.artifact for item in records], ambiguities=ambiguities)


def _operator_coverage(
    indexed_artifacts: tuple[IndexedArtifact, ...],
    target: TargetSelection | None,
    segment: str,
) -> dict:
    records = [
        item
        for item in indexed_artifacts
        if item.segment == segment
        and item.group in OPERATOR_GROUPS
    ]
    roots = {str(item.opprof_root) for item in records if item.opprof_root}
    keys: dict[str, list[IndexedArtifact]] = {}
    unkeyed = [item for item in records if not item.launch_key]
    for item in records:
        key = item.launch_key
        if key:
            keys.setdefault(str(key), []).append(item)
    ambiguities: list[str] = []
    if len(roots) != 1:
        ambiguities.append(f"expected one OPPROF root for {segment}, observed {len(roots)}")
    if unkeyed:
        ambiguities.append(f"{len(unkeyed)} operator artifacts do not have a supported kernel/launch path")
    observations: list[dict] = []
    launch_family_complete: dict[str, dict[str, bool]] = {}
    for key, key_records in sorted(keys.items()):
        basic = [item for item in key_records if item.group == "op_basic_info"]
        valid_basic = [
            item
            for item in basic
            if item.status == "parsed" and item.row_count == 1
        ]
        if len(basic) != 1 or len(valid_basic) != 1:
            ambiguities.append(
                f"launch key {key} requires one parsed one-row OpBasicInfo; observed {len(basic)} files and {len(valid_basic)} valid"
            )
            continue
        basic_record = valid_basic[0]
        name = basic_record.target_name
        if not name:
            ambiguities.append(f"launch key {key} OpBasicInfo has no reliable launch identity")
            continue
        observation = {
            "name": name,
            "duration_us": basic_record.duration_us,
            "artifact": basic_record.artifact,
            "launch_key": key,
        }
        observations.append(observation)
        family_status: dict[str, bool] = {}
        for family, stems in METRIC_FAMILY_STEMS.items():
            stem_complete = []
            for stem in stems:
                matches = [item for item in key_records if item.canonical_stem == stem]
                stem_complete.append(
                    len(matches) == 1
                    and matches[0].status == "parsed"
                    and int(matches[0].row_count or 0) > 0
                )
            family_status[family] = all(stem_complete)
        launch_family_complete[key] = family_status

    authority_complete = bool(keys) and len(roots) == 1 and not unkeyed and not any(
        "OpBasicInfo" in item for item in ambiguities
    )
    coverage = _coverage_counts(
        observations,
        target,
        authority=(
            "one parsed one-row OpBasicInfo per supported launch key: nested "
            "(segment, OPPROF root, kernel directory, launch directory) or "
            "verified flat single-launch (segment, OPPROF root)"
        ),
        authority_complete=authority_complete,
        artifacts=[str(item.artifact) for item in records if item.artifact],
        ambiguities=ambiguities,
    )
    expected = expected_counts(target)
    metric_coverage: dict[str, dict] = {}
    for family in METRIC_FAMILY_STEMS:
        covered_by_target: dict[str, int] = {}
        covered_total = 0
        for observation in observations:
            if not launch_family_complete.get(str(observation["launch_key"]), {}).get(family):
                continue
            covered_total += 1
            matched, _ = match_expected_name(target, observation.get("name"))
            key = matched or normalize_target_name(observation.get("name")) or "missing_name"
            covered_by_target[key] = covered_by_target.get(key, 0) + 1
        by_target = {
            name: {
                "expected": count,
                "covered": covered_by_target.get(name, 0),
                "missing": max(0, count - covered_by_target.get(name, 0)),
            }
            for name, count in expected.items()
        }
        complete = metric_complete(coverage["count_complete"], (item["missing"] for item in by_target.values()))
        metric_coverage[family] = {
            "required_stems": list(METRIC_FAMILY_STEMS[family]),
            "covered_launches": covered_total,
            "expected_launches": sum(expected.values()) if target is not None else None,
            "covered_by_target": covered_by_target,
            "by_target": by_target,
            "complete": complete,
            "completeness": completeness(complete),
        }
    coverage["metric_coverage"] = metric_coverage
    return coverage


def segment_target_scope(segment_target: TargetSelection | None, program_target: TargetSelection | None) -> dict:
    if segment_target is None:
        return {"kind": "observed_run"}
    complete_program = (
        program_target is not None
        and segment_target.kernel_selector == program_target.kernel_selector
        and expected_counts(segment_target) == expected_counts(program_target)
    )
    return {
        "kind": "complete_program" if complete_program else "focused_subset",
        "kernel_selector": segment_target.kernel_selector,
        "expected_counts": expected_counts(segment_target),
        "expected_total": sum(expected_counts(segment_target).values()),
    }


def _attach_segment_target_metadata(coverage: dict, segment_target: TargetSelection | None, program_target: TargetSelection | None) -> None:
    coverage["target_scope"] = segment_target_scope(segment_target, program_target)
    coverage["target_identity"] = {"status": coverage_identity_status(coverage["count_complete"], coverage["observed_total"])}


def build_profile_coverage(indexed_artifacts: tuple[IndexedArtifact, ...], target: TargetSelection | None, *,
                           app_artifacts: tuple[ArtifactRecord, ...],
                           segment_targets: dict[str, TargetSelection], excluded_segments: set[str]) -> ProfileCoverage:
    operator_segments = sorted(
        {
            str(item.segment)
            for item in indexed_artifacts
            if (item.segment == "op" or str(item.segment or "").startswith("followup:"))
            and item.group in OPERATOR_GROUPS
        },
        key=lambda item: (item != "op", item),
    )
    if "op" not in operator_segments:
        operator_segments.insert(0, "op")
    admitted_artifacts = tuple(item for item in indexed_artifacts if item.segment not in excluded_segments)
    app_coverage = _app_coverage(
        tuple(item for item in app_artifacts
              if item.segment == "app" and item.segment not in excluded_segments), target)
    _attach_segment_target_metadata(app_coverage, target, target)
    segments = {"app": SegmentCoverage.model_validate(app_coverage)}
    for segment in operator_segments:
        segment_target = segment_targets.get(segment)
        coverage = _operator_coverage(
            admitted_artifacts,
            segment_target,
            segment,
        )
        _attach_segment_target_metadata(coverage, segment_target, target)
        segments[segment] = SegmentCoverage.model_validate(coverage)

    selected = select_coverage_segments(segments)
    expected = expected_counts(target)
    return ProfileCoverage.model_validate({
        "schema_version": "1.1",
        "explicit_target": target is not None,
        "kernel_selector": target.kernel_selector if target else None,
        "expected_total": sum(expected.values()) if target is not None else None,
        "expected_counts": expected,
        "segments": segments,
        "selected_segments_by_family": selected,
        "measurement_boundary": (
            "Application and operator segments are separate profiler measurements; their duration totals must not be compared as a direct performance delta."
        ),
    })
