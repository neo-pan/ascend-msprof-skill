"""Build analysis artifacts from Ascend msprof / msprof op output."""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .application_timing import TimingEvidence, normalize_timing, select_primary
from .collection_receipts import CollectionReceipts, load_collection_receipts
from .collection_context import load_analysis_context
from .summary_types import (Summary, SummaryFacts, RawArtifactIndex, MeasurementQuality, SelectedMetricScope, StdoutSection,
                            StdoutSections, build_frequency_measurement_quality)
from .coverage_types import build_profile_coverage
from .identity_types import build_target_identity, target_identity_warnings
from .operator_evidence import OperatorEvidence, normalize_operator, select_operator_primary
from .metric_scope_policy import APP_TIMING_ARTIFACTS
from ._profiler_segments import segment_for_relpath, metric_scope_for_segment

from ._evidence_artifacts import (
    recognized_group_files,
    FILE_GROUPS,
    build_raw_artifact_index,
    bind_segment_targets,
)
from ._evidence_relations import build_evidence_relations
from ._evidence_readiness import build_evidence_readiness, build_next_collection_actions
from ._evidence_signals import (
    build_analysis_dimensions,
)
from ._evidence_text_summary import write_text_summary
from ._profiler_segments import (
    performance_summary_segment,
    stdout_profile_output_segment,
)
from .ascend_profile_utils import (
    analysis_dir,
    rel,
    write_json,
)
from .metric_scope_policy import (
    command_metric_scope,
    is_msprof_op_command,
    normalize_metric_scope,
)
from .simulator_hotspot_model import collect_simulator_model
from .simulator_types import SimulatorModel


ANALYSIS_SCHEMA_VERSION = "5.1"

OCCUPANCY_SECTION_NAME = "Occupancy Summary Report"
OCCUPANCY_SECTION_START_RE = re.compile(r"^.*\[INFO\]\s+Occupancy Summary Report:\s*$")
ROOFLINE_SECTION_NAME = "RoofLine Summary Report"
ROOFLINE_SECTION_START_RE = re.compile(r"^.*\[INFO\]\s+RoofLine Summary Report:\s*$")
PERFORMANCE_SECTION_NAME = "Performance Summary Report"
PERFORMANCE_SECTION_START_RE = re.compile(r"^.*\[INFO\]\s+Performance Summary Report:\s*$")
REPORT_SECTION_HEADER_RE = re.compile(r"^.*\[INFO\]\s+\S.* Report:\s*$")
CANN_INFO_HEADER_RE = re.compile(r"^.*\[(?:INFO|WARN|ERROR)\]\s+\S.*:\s*$")
OCCUPANCY_MESSAGE_RE = re.compile(r"^\s*(?P<ordinal>[0-9]+)\)\s+(?P<message>.+\S)\s*$")
AUXILIARY_STDOUT_MARKERS = ["help", "export", "validation", "malformed"]


def is_auxiliary_stdout_log(path: Path) -> bool:
    stem = path.stem.lower()
    return any(marker in stem for marker in AUXILIARY_STDOUT_MARKERS)


def selected_profiler_stdout_paths(run_dir: Path, preferred_patterns: list[str] | None = None) -> list[Path]:
    logs_dir = run_dir / "logs"
    if not logs_dir.exists():
        return []
    if preferred_patterns is None:
        preferred_patterns = ["msprof_occupancy*.stdout"]

    paths = [path for path in logs_dir.glob("*.stdout") if path.is_file()]
    paths_by_name = {path.name: path for path in paths}
    selected: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path | None) -> None:
        if path is None or path in seen or is_auxiliary_stdout_log(path):
            return
        selected.append(path)
        seen.add(path)

    for pattern in preferred_patterns:
        for path in sorted(logs_dir.glob(pattern)):
            add(path)
    add(paths_by_name.get("msprof_default.stdout"))
    add(paths_by_name.get("command_msprof.stdout"))
    for path in sorted(logs_dir.glob("msprof*.stdout")):
        add(path)
    return selected


def selected_roofline_stdout_paths(run_dir: Path) -> list[Path]:
    return selected_profiler_stdout_paths(run_dir, ["msprof_roofline*.stdout"])


def selected_performance_stdout_paths(run_dir: Path) -> list[Path]:
    return selected_profiler_stdout_paths(run_dir, ["msprof_op*.stdout"])


def selected_metric_scope(run_dir: Path) -> SelectedMetricScope | None:
    for name in ["command_msprof_op.txt", "command_msprof.txt"]:
        path = run_dir / "logs" / name
        if not path.exists():
            continue
        command = path.read_text(encoding="utf-8", errors="replace")
        if name == "command_msprof.txt" and not is_msprof_op_command(command):
            continue
        scope = command_metric_scope(command)
        if scope:
            normalized = normalize_metric_scope(scope)
            return SelectedMetricScope(value=normalized, artifact=f"logs/{name}", field_ref="--aic-metrics")
    return None


def _stdout_ordinal(token: str, source: str, section: str, line: int,
                    warnings: list[str] | None) -> int | None:
    try:
        return int(token)
    except ValueError:
        if warnings is not None:
            warnings.append(f'invalid stdout {source}:{line} ({section}.ordinal): integer token cannot be represented')
        return None


def parse_occupancy_summary_text(text: str, source: str, *, warnings: list[str] | None = None) -> StdoutSection | None:
    messages = []
    in_section = False
    for line_number, line in enumerate(text.splitlines(), 1):
        if not in_section:
            if OCCUPANCY_SECTION_START_RE.match(line):
                in_section = True
            continue
        if REPORT_SECTION_HEADER_RE.match(line):
            break
        match = OCCUPANCY_MESSAGE_RE.match(line)
        if match:
            ordinal = _stdout_ordinal(match.group('ordinal'), source, OCCUPANCY_SECTION_NAME, line_number, warnings)
            if ordinal is None:
                continue
            messages.append(
                {
                    "ordinal": ordinal,
                    "message": match.group("message"),
                }
            )
    if not messages:
        return None
    return StdoutSection(source=source, section=OCCUPANCY_SECTION_NAME, messages=messages)


def parse_occupancy_summary_stdout(run_dir: Path) -> StdoutSection | None:
    selected, _ = _parse_stdout_sections(
        run_dir,
        selected_profiler_stdout_paths(run_dir),
        parse_occupancy_summary_text,
        stdout_profile_output_segment,
        load_collection_receipts(run_dir),
    )
    return selected


def parse_roofline_summary_text(text: str, source: str, *, warnings: list[str] | None = None) -> StdoutSection | None:
    messages = []
    in_section = False
    for line in text.splitlines():
        if not in_section:
            if ROOFLINE_SECTION_START_RE.match(line):
                in_section = True
            continue
        if REPORT_SECTION_HEADER_RE.match(line):
            break
        message = line.strip()
        if message:
            messages.append({"message": message})
    if not messages:
        return None
    return StdoutSection(source=source, section=ROOFLINE_SECTION_NAME, messages=messages)


def parse_roofline_summary_stdout(run_dir: Path) -> StdoutSection | None:
    selected, _ = _parse_stdout_sections(
        run_dir,
        selected_roofline_stdout_paths(run_dir),
        parse_roofline_summary_text,
        stdout_profile_output_segment,
        load_collection_receipts(run_dir),
    )
    return selected


def parse_performance_summary_text(text: str, source: str, *, warnings: list[str] | None = None) -> StdoutSection | None:
    messages = []
    in_section = False
    for line_number, line in enumerate(text.splitlines(), 1):
        if not in_section:
            if PERFORMANCE_SECTION_START_RE.match(line):
                in_section = True
            continue
        if REPORT_SECTION_HEADER_RE.match(line) or CANN_INFO_HEADER_RE.match(line):
            break
        match = OCCUPANCY_MESSAGE_RE.match(line)
        if match:
            ordinal = _stdout_ordinal(match.group('ordinal'), source, PERFORMANCE_SECTION_NAME, line_number, warnings)
            if ordinal is None:
                continue
            messages.append(
                {
                    "ordinal": ordinal,
                    "message": match.group("message"),
                }
            )
    if not messages:
        return None
    return StdoutSection(source=source, section=PERFORMANCE_SECTION_NAME, messages=messages)


def parse_performance_summary_stdout(run_dir: Path) -> StdoutSection | None:
    selected, _ = _parse_stdout_sections(
        run_dir,
        selected_performance_stdout_paths(run_dir),
        parse_performance_summary_text,
        performance_summary_segment,
        load_collection_receipts(run_dir),
    )
    return selected


def _parse_stdout_sections(
    run_dir: Path,
    paths: list[Path],
    parse_text: Callable[..., StdoutSection | None],
    segment_for_path: Callable[[Path], str | None],
    receipts: CollectionReceipts,
    *,
    warnings: list[str] | None = None,
) -> tuple[StdoutSection | None, list[StdoutSection]]:
    selected = None
    parsed = []
    for path in paths:
        section = parse_text(
            path.read_text(encoding="utf-8", errors="replace"),
            rel(path, run_dir),
            warnings=warnings,
        )
        if section is None:
            continue
        parsed.append(section)
        segment = segment_for_path(path)
        if selected is None and (
            segment is None or receipts.allows(segment)
        ):
            selected = section
    return selected, parsed


@dataclass(frozen=True)
class EvidenceModelArtifacts:
    summary_path: Path
    raw_artifact_index_path: Path
    key_metrics_path: Path
    summary: Summary
    raw_artifact_index: RawArtifactIndex
    simulator_model: SimulatorModel


def build_evidence_model(run_dir: Path) -> tuple[Summary, RawArtifactIndex, SimulatorModel]:
    run_dir = run_dir.resolve()
    receipts = load_collection_receipts(run_dir)
    context = load_analysis_context(run_dir)
    metric_scope = selected_metric_scope(run_dir)
    warnings: list[str] = []
    occupancy_summary, raw_occupancy_sections = _parse_stdout_sections(
        run_dir,
        selected_profiler_stdout_paths(run_dir),
        parse_occupancy_summary_text,
        stdout_profile_output_segment,
        receipts,
        warnings=warnings,
    )
    roofline_summary, raw_roofline_sections = _parse_stdout_sections(
        run_dir,
        selected_roofline_stdout_paths(run_dir),
        parse_roofline_summary_text,
        stdout_profile_output_segment,
        receipts,
        warnings=warnings,
    )
    performance_summary, raw_performance_sections = _parse_stdout_sections(
        run_dir,
        selected_performance_stdout_paths(run_dir),
        parse_performance_summary_text,
        performance_summary_segment,
        receipts,
        warnings=warnings,
    )
    headlines: dict[str, TimingEvidence | OperatorEvidence] = {}
    stdout_sections = StdoutSections(occupancy_summary=occupancy_summary, roofline_summary=roofline_summary,
                                     performance_summary=performance_summary)
    declared_target = context.declared_target
    target = declared_target.target if declared_target is not None else None
    csv_records = {}
    for group, patterns in FILE_GROUPS.items():
        records = []
        normalize = normalize_timing if group in APP_TIMING_ARTIFACTS else normalize_operator
        for path in recognized_group_files(run_dir, group):
            artifact = rel(path, run_dir)
            segment = segment_for_relpath(artifact, group)
            records.append(normalize(path, artifact, group, segment, metric_scope_for_segment(segment, metric_scope.value if metric_scope else None)))
        csv_records[group] = tuple(records)
        admitted = tuple(item for item in records if receipts.allows(item.segment))
        if group in APP_TIMING_ARTIFACTS:
            headlines[group] = TimingEvidence(group=group, artifacts=admitted, primary=select_primary(admitted))
        else:
            headlines[group] = OperatorEvidence(group=group, artifacts=admitted, primary=select_operator_primary(admitted))
        warnings.extend(warning for item in admitted for warning in item.warnings)
        if not admitted:
            warnings.append(f"missing {group}: {patterns}")
    operator_segments = {item.segment for group, records in csv_records.items()
                         if group not in APP_TIMING_ARTIFACTS for item in records} | {"op"}
    segment_targets = bind_segment_targets(context.workflow, operator_segments, target, receipts.excluded_segments)
    simulator_model, simulator_inputs = collect_simulator_model(run_dir, receipts)
    raw_artifact_index = build_raw_artifact_index(
        run_dir,
        metric_scope.value if metric_scope else None,
        csv_records=csv_records,
        simulator_inputs=simulator_inputs,
        target=target,
        segment_targets=segment_targets,
        stdout_sections={
            "occupancy_summary": raw_occupancy_sections,
            "roofline_summary": raw_roofline_sections,
            "performance_summary": raw_performance_sections,
        },
    )
    artifact_segments = {item.segment for item in raw_artifact_index.artifacts}
    excluded_segments = artifact_segments & receipts.excluded_segments
    evidence_artifact_index = RawArtifactIndex(
        raw_artifact_index_schema_version=raw_artifact_index.raw_artifact_index_schema_version,
        artifacts=tuple(item for item in raw_artifact_index.artifacts if item.segment not in excluded_segments),
        warnings=raw_artifact_index.warnings,
    )
    warnings.extend(
        f"{segment} result receipt is not succeeded; raw artifacts are excluded from derived evidence"
        for segment in sorted(excluded_segments)
    )
    warnings.extend(f"{item.artifact}: {item.issue.reason}" for item in receipts.records if item.issue is not None)
    profile_coverage = build_profile_coverage(
        raw_artifact_index.artifacts,
        target,
        app_artifacts=csv_records["op_summary"],
        segment_targets=segment_targets,
        excluded_segments=excluded_segments,
    )
    expected = context.expected_target
    target_identity = build_target_identity(headlines, profile_coverage, expected,
                                            segment_sources=context.segment_target_sources)
    warnings.extend(target_identity_warnings(target_identity))
    warnings.extend(f"{item.source.artifact}: {item.reason}" for item in context.issues)
    write_json(analysis_dir(run_dir) / "simulator_hotspots.json", simulator_model.model_dump(mode="json"))
    for warning in simulator_model.warnings:
        if str(warning).startswith("invalid simulator"):
            warnings.append(str(warning))
    frequency_quality = build_frequency_measurement_quality(evidence_artifact_index.artifacts, csv_records["op_basic_info"])
    warnings.extend(frequency_quality.warnings)
    facts = SummaryFacts(headlines=headlines, stdout_sections=stdout_sections, metric_scope=metric_scope,
                         collection_receipts=receipts, analysis_context=context,
                         profile_coverage=profile_coverage, target_identity=target_identity,
                         measurement_quality=MeasurementQuality(frequency=frequency_quality), warnings=warnings)
    dimensions = build_analysis_dimensions(facts, simulator_model)
    actions = build_next_collection_actions(facts)
    relations = build_evidence_relations(facts, dimensions, simulator_model)
    readiness = build_evidence_readiness(facts, evidence_artifact_index, actions=actions,
        simulator_signals=next(item.signals for item in dimensions if item.id == "source_pipeline_context"))
    summary = Summary(analysis_schema_version=ANALYSIS_SCHEMA_VERSION,
                      **{name: getattr(facts, name) for name in SummaryFacts.model_fields},
                      analysis_dimensions=dimensions, next_collection_actions=actions,
                      evidence_relations=relations, evidence_readiness=readiness)
    return summary, raw_artifact_index, simulator_model


def write_evidence_model(run_dir: Path) -> EvidenceModelArtifacts:
    run_dir = run_dir.resolve()
    out_dir = analysis_dir(run_dir)
    summary, raw_artifact_index, simulator_model = build_evidence_model(run_dir)
    summary_path = out_dir / "summary.json"
    raw_artifact_index_path = out_dir / "raw_artifact_index.json"
    key_metrics_path = out_dir / "key_metrics.txt"
    write_json(summary_path, summary.model_dump(mode="json", exclude_unset=True))
    write_json(raw_artifact_index_path, raw_artifact_index.model_dump(mode="json", exclude_unset=True))
    write_text_summary(key_metrics_path, summary)
    return EvidenceModelArtifacts(
        summary_path=summary_path,
        raw_artifact_index_path=raw_artifact_index_path,
        key_metrics_path=key_metrics_path,
        summary=summary,
        raw_artifact_index=raw_artifact_index,
        simulator_model=simulator_model,
    )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    args = ap.parse_args(argv)

    artifacts = write_evidence_model(args.run_dir.resolve())
    print(f"wrote {artifacts.summary_path}")
    print(f"wrote {artifacts.raw_artifact_index_path}")
    print(f"wrote {artifacts.key_metrics_path}")


if __name__ == "__main__":
    main()
