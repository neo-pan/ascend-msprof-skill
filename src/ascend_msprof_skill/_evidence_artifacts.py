"""Raw artifact inventory helpers for Ascend msprof analysis."""
from __future__ import annotations
from .collection_context import HarnessWorkflow, FollowupExecution

from .simulator_types import SimulatorInput

from .summary_types import StdoutSection, RawArtifactIndex

from pathlib import Path

from pydantic import ConfigDict, JsonValue, TypeAdapter, ValidationError

from .coverage_types import segment_target_scope
from .evidence_types import ArtifactRecord
from .operator_evidence import OperatorArtifact
from .metric_scope_policy import APP_TIMING_ARTIFACTS

from ._profiler_segments import (
    DEFAULT_FOLLOWUP_ACTION_ID,
    operator_launch_metadata,
    app_timeline_segment,
    focused_followup_action_id,
    followup_segment,
    is_supported_followup_action_id,
    metric_scope_for_segment,
    performance_summary_segment,
    segment_for_relpath,
    stdout_profile_output_segment,
)
from ._profile_target import (
    expected_counts,
    match_expected_name,
    TargetSelection,
    normalize_target_name,
    validate_target_subset,
)
from .ascend_profile_utils import find_files, read_json, rel
from ._operator_csv_names import STEMS_BY_GROUP, operator_group_for_stem, parse_operator_csv_name


RAW_ARTIFACT_INDEX_SCHEMA_VERSION = "1.1"
_RAW_JSON_VALUE = TypeAdapter(JsonValue, config=ConfigDict(strict=True, allow_inf_nan=False))
FILE_GROUPS = {
    "op_summary": ["op_summary_*.csv"],
    "op_statistic": ["op_statistic_*.csv"],
    "task_time": ["task_time_*.csv"],
    "api_statistic": ["api_statistic_*.csv"],
    "op_basic_info": ["OpBasicInfo.csv"],
    "pipe_utilization": ["PipeUtilization.csv"],
    "arithmetic_utilization": ["ArithmeticUtilization.csv"],
    "l2_cache": ["L2Cache.csv"],
    "memory": ["Memory.csv", "MemoryL0.csv", "MemoryUB.csv"],
    "resource_conflict": ["ResourceConflictRatio.csv"],
}

APP_TIMELINE_PATTERNS = ["msprof_*.json"]
UNPARSED_BINARY_PATTERNS = ["visualize_data.bin", "DeviceProf*.bin", "duration.bin"]
OPERATOR_FILE_STEMS = STEMS_BY_GROUP


def operator_file_stem(path: Path, group: str) -> str | None:
    parsed = parse_operator_csv_name(path.name)
    if parsed is None or operator_group_for_stem(parsed.stem) != group:
        return None
    if not any(part.startswith("OPPROF_") for part in path.parts):
        return None
    return parsed.stem


def recognized_group_files(run_dir: Path, group: str, patterns: list[str] | None = None) -> list[Path]:
    if group not in OPERATOR_FILE_STEMS:
        return find_files(run_dir, patterns or FILE_GROUPS.get(group, []))
    reports = run_dir / "reports"
    if not reports.exists():
        return []
    return sorted(
        path
        for path in reports.rglob("*.csv")
        if path.is_file() and operator_file_stem(path, group) is not None
    )


def empty_raw_artifact_record(
    artifact: str,
    group: str,
    parser: str,
    segment: str,
    metric_scope: str | None,
) -> dict:
    return {
        "artifact": artifact,
        "group": group,
        "parser": parser,
        "segment": segment,
        "metric_scope": metric_scope,
        "status": "empty",
        "columns": [],
        "row_count": 0,
        "sample_rows": [],
        "warnings": [],
    }


def propagate_operator_launch_identity(artifacts: list[dict]) -> None:
    by_launch: dict[str, list[dict]] = {}
    for item in artifacts:
        launch_key = item.get("launch_key")
        if launch_key:
            by_launch.setdefault(str(launch_key), []).append(item)
    for records in by_launch.values():
        basic = [item for item in records if item.get("group") == "op_basic_info"]
        valid = [
            item
            for item in basic
            if item.get("status") == "parsed"
            and item.get("row_count") == 1
            and item.get("normalized_target_name")
        ]
        if len(basic) != 1 or len(valid) != 1:
            continue
        identity = valid[0]
        for item in records:
            item["target_name"] = identity.get("target_name")
            item["normalized_target_name"] = identity["normalized_target_name"]


def json_event_rows(data: object) -> list:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ["traceEvents", "events", "data"]:
        events = data.get(key)
        if isinstance(events, list):
            return events
    return []


def raw_json_artifact_record(
    path: Path,
    run_dir: Path,
    group: str,
    selected_scope: str | None,
    segment: str | None = None,
) -> dict:
    rel_path = rel(path, run_dir)
    artifact_segment = segment or segment_for_relpath(rel_path, group)
    record = empty_raw_artifact_record(
        rel_path,
        group,
        "json",
        artifact_segment,
        metric_scope_for_segment(artifact_segment, selected_scope),
    )
    try:
        events = json_event_rows(read_json(path))
    except (OSError, ValueError) as exc:
        record["status"] = "invalid"
        record["warnings"].append(f"invalid json {rel_path}: {exc}")
        return record
    record["row_count"] = len(events)
    record["status"] = "parsed" if events else "empty"
    for index, event in enumerate(events):
        try:
            _RAW_JSON_VALUE.validate_python(event)
        except ValidationError as exc:
            record["status"] = "invalid"
            record["warnings"].append(f"invalid json {rel_path}: event[{index}]: {exc}")
            continue
        if len(record["sample_rows"]) < 5:
            record["sample_rows"].append(event)
    return record


def unparsed_binary_role(path: Path) -> str:
    name = path.name
    if name == "visualize_data.bin":
        if "simulator" in path.parts:
            return "simulator visualization artifact"
        return "MindStudio visualization artifact"
    if name.startswith("DeviceProf") and name.endswith(".bin"):
        return "internal device profiling dump"
    if name == "duration.bin":
        return "internal raw duration dump"
    if name == "aicore_binary.o":
        return "kernel object binary"
    return "unparsed binary profiler artifact"


def raw_binary_artifact_record(path: Path, run_dir: Path, selected_scope: str | None) -> dict:
    rel_path = rel(path, run_dir)
    artifact_segment = segment_for_relpath(rel_path, "unparsed_profiler_binary")
    record = empty_raw_artifact_record(
        rel_path,
        "unparsed_profiler_binary",
        "none",
        artifact_segment,
        metric_scope_for_segment(artifact_segment, selected_scope),
    )
    record["status"] = "unparsed"
    record["size_bytes"] = path.stat().st_size
    record["known_role"] = unparsed_binary_role(path)
    record["diagnosis_role"] = "not_used"
    record["notes"] = "Preserved profiler artifact; not parsed and not used for diagnosis."
    return record

def stdout_raw_artifact_records(sections: dict[str, list[StdoutSection]], selected_scope: str | None) -> list[dict]:
    out = []
    for section_name, group in [
        ("occupancy_summary", "stdout_occupancy_summary"),
        ("roofline_summary", "stdout_roofline_summary"),
        ("performance_summary", "stdout_performance_summary"),
    ]:
        for section in sections.get(section_name, ()):
            source = section.source
            messages = section.messages
            if section_name == "performance_summary":
                segment = performance_summary_segment(source)
            else:
                segment = stdout_profile_output_segment(Path(source)) or "unknown"
            record = empty_raw_artifact_record(
                source,
                group,
                "stdout",
                segment,
                metric_scope_for_segment(segment, selected_scope),
            )
            record["row_count"] = len(messages)
            record["sample_rows"] = [item.model_dump(mode="json", exclude_unset=True) for item in messages[:5]]
            record["status"] = "parsed" if messages else "empty"
            out.append(record)
    return out


def build_raw_artifact_index(
    run_dir: Path,
    selected_scope: str | None,
    *,
    stdout_sections: dict[str, list[StdoutSection]],
    csv_records: dict[str, tuple[ArtifactRecord, ...]],
    simulator_inputs: tuple[SimulatorInput, ...],
    target: TargetSelection | None,
    segment_targets: dict[str, TargetSelection],
) -> RawArtifactIndex:
    artifacts = []
    for group, patterns in FILE_GROUPS.items():
        for item in csv_records[group]:
            record = {"artifact": item.artifact, "group": group, "parser": "csv", "segment": item.segment,
                "metric_scope": item.metric_scope, "status": item.status, "columns": list(item.columns),
                "row_count": item.row_count, "sample_rows": list(item.sample_rows), "warnings": list(item.warnings)}
            if isinstance(item, OperatorArtifact):
                path = run_dir / item.artifact
                record["canonical_stem"] = operator_file_stem(path, group)
                record.update(operator_launch_metadata(rel(path, run_dir), item.segment))
                if item.launch_name:
                    record["target_name"] = item.launch_name
                    record["normalized_target_name"] = normalize_target_name(item.launch_name)
                if item.group == "op_basic_info" and item.status == "parsed" and item.row_count == 1:
                    record["duration_us"] = item.launch_counts[0].duration_us if item.launch_counts else None
            artifacts.append(record)
    for path in find_files(run_dir, APP_TIMELINE_PATTERNS):
        if path.name.endswith(".result.json"):
            continue
        rel_path = rel(path, run_dir)
        artifacts.append(
            raw_json_artifact_record(
                path,
                run_dir,
                "app_timeline",
                selected_scope,
                segment=app_timeline_segment(rel_path),
            )
        )
    for item in simulator_inputs:
        artifacts.append({'artifact': item.artifact,
            'group': 'simulator_trace' if item.kind == 'trace_json' else 'simulator_csv',
            'parser': 'json' if item.kind == 'trace_json' else 'csv', 'segment': 'simulator', 'metric_scope': None,
            'status': item.parser_status, 'columns': item.columns, 'row_count': item.row_count,
            'sample_rows': item.sample_rows, 'warnings': item.warnings})
    for path in find_files(run_dir, UNPARSED_BINARY_PATTERNS):
        artifacts.append(raw_binary_artifact_record(path, run_dir, selected_scope))
    artifacts.extend(stdout_raw_artifact_records(stdout_sections, selected_scope))
    propagate_operator_launch_identity(artifacts)
    artifacts.sort(key=lambda item: (str(item.get("artifact")), str(item.get("group")), str(item.get("parser"))))
    warnings = [
        warning
        for artifact in artifacts
        for warning in artifact.get("warnings", [])
    ]
    index = {
        "raw_artifact_index_schema_version": RAW_ARTIFACT_INDEX_SCHEMA_VERSION,
        "artifacts": artifacts,
        "warnings": warnings,
    }
    _normalize_flat_single_launch_identity(index, target, segment_targets)
    return RawArtifactIndex.model_validate(index)


def bind_segment_targets(
    workflow: HarnessWorkflow | None,
    operator_segments: set[str],
    program_target: TargetSelection | None,
    excluded_segments: set[str],
) -> dict[str, TargetSelection]:
    targets = {"op": program_target} if program_target is not None and "op" not in excluded_segments else {}
    latest_executions: dict[str, FollowupExecution] = {}
    for item in workflow.executions if workflow is not None else ():
        latest_executions[followup_segment(item.segment_id)] = item
    canonical_segment = followup_segment(DEFAULT_FOLLOWUP_ACTION_ID)
    if (program_target is not None and canonical_segment in operator_segments
            and canonical_segment not in latest_executions and canonical_segment not in excluded_segments):
        targets[canonical_segment] = program_target
    for segment, item in latest_executions.items():
        if item.status != "succeeded" or segment in excluded_segments:
            continue
        normalized = item.target_selection
        if normalized is not None:
            validate_target_subset(program_target, normalized)
        if segment == canonical_segment:
            if program_target is not None and (normalized is None or (
                    normalized.kernel_selector == program_target.kernel_selector
                    and expected_counts(normalized) == expected_counts(program_target))):
                targets[segment] = program_target
        elif normalized is not None and segment == followup_segment(focused_followup_action_id(normalized)):
            targets[segment] = normalized
    return targets


def _normalize_flat_single_launch_identity(
    raw_artifact_index: dict,
    program_target: TargetSelection | None,
    segment_targets: dict[str, TargetSelection],
) -> None:
    artifacts = raw_artifact_index.get("artifacts", [])
    if not isinstance(artifacts, list):
        return
    for segment, segment_target in segment_targets.items():
        target_scope = segment_target_scope(segment_target, program_target)
        if target_scope.get("kind") not in {"focused_subset", "complete_program"} or target_scope.get("expected_total") != 1:
            continue
        records = [
            item
            for item in artifacts
            if isinstance(item, dict)
            and item.get("segment") == segment
            and item.get("group") in OPERATOR_FILE_STEMS
        ]
        roots = {str(item.get("opprof_root")) for item in records if item.get("opprof_root")}
        if len(roots) != 1 or any(item.get("launch_key") for item in records):
            continue
        root = next(iter(roots))
        if any(Path(str(item.get("artifact") or "")).parent.as_posix() != root for item in records):
            continue
        basic = [item for item in records if item.get("group") == "op_basic_info"]
        if len(basic) != 1:
            continue
        identity = basic[0]
        if (
            identity.get("status") != "parsed"
            or identity.get("row_count") != 1
            or not identity.get("target_name")
        ):
            continue
        matched, match_rule = match_expected_name(segment_target, identity.get("target_name"))
        if matched is None or match_rule not in {"exact", "known_suffix"}:
            continue
        launch_key = f"{segment}|{root}"
        for item in records:
            item["launch_key"] = launch_key
            item["launch_ordinal"] = "flat"
        propagate_operator_launch_identity(records)
