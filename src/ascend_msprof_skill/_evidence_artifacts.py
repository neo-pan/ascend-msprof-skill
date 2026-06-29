"""Raw artifact inventory helpers for Ascend msprof analysis."""
from __future__ import annotations

import csv
from pathlib import Path

from .ascend_profile_utils import find_files, read_json, rel, summarize_csv


RAW_ARTIFACT_INDEX_SCHEMA_VERSION = "1.0"
APP_FILE_GROUPS = {"op_summary", "op_statistic", "task_time", "api_statistic"}
FOLLOWUP_METRIC_SCOPES = {
    "collect_default_metric_followup": "Default",
}
OP_PERFORMANCE_STDOUT_PREFIXES = ("msprof_op", "command_msprof_op")
OP_PERFORMANCE_FALLBACK_STDOUTS = {"msprof_default.stdout", "command_msprof.stdout"}
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
SIMULATOR_PATTERNS = ["core*_code_exe.csv", "core*_instr_exe.csv", "trace.json"]
APP_TIMELINE_PATTERNS = ["msprof_*.json"]
UNPARSED_BINARY_PATTERNS = ["visualize_data.bin", "DeviceProf*.bin", "duration.bin"]


def segment_for_relpath(rel_path: str, group: str | None = None) -> str:
    parts = Path(rel_path).parts
    if "simulator" in parts:
        return "simulator"
    if "followups" in parts:
        index = parts.index("followups")
        if index + 1 < len(parts):
            return f"followup:{parts[index + 1]}"
        return "unknown"
    if len(parts) >= 2 and parts[0] == "reports" and parts[1] == "app":
        return "app"
    if len(parts) >= 2 and parts[0] == "reports" and parts[1] == "op":
        return "op"
    if any(part.startswith("PROF_") for part in parts):
        return "app"
    if any(part.startswith("OPPROF_") for part in parts):
        return "op"
    if group in APP_FILE_GROUPS:
        return "app"
    return "unknown"


def metric_scope_for_segment(segment: str, selected_scope: dict | None) -> str | None:
    if segment == "op" and isinstance(selected_scope, dict):
        value = selected_scope.get("value")
        return str(value) if value else None
    if segment.startswith("followup:"):
        action_id = segment.split(":", 1)[1]
        return FOLLOWUP_METRIC_SCOPES.get(action_id)
    return None


def annotate_source_metadata(item: dict, rel_path: str, group: str | None, selected_scope: dict | None) -> dict:
    segment = segment_for_relpath(rel_path, group)
    item["segment"] = segment
    item["metric_scope"] = metric_scope_for_segment(segment, selected_scope)
    return item


def collect_group(run_dir: Path, group: str, patterns: list[str], selected_scope: dict | None) -> list[dict]:
    records = []
    for path in find_files(run_dir, patterns):
        rec = summarize_csv(path)
        rec["group"] = group
        annotate_source_metadata(rec, rel(path, run_dir), group, selected_scope)
        records.append(rec)
    return records


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


def raw_csv_artifact_record(
    path: Path,
    run_dir: Path,
    group: str,
    selected_scope: dict | None,
    segment: str | None = None,
) -> dict:
    rel_path = rel(path, run_dir)
    artifact_segment = segment or segment_for_relpath(rel_path, group)
    record = empty_raw_artifact_record(
        rel_path,
        group,
        "csv",
        artifact_segment,
        metric_scope_for_segment(artifact_segment, selected_scope),
    )
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            record["columns"] = list(reader.fieldnames or (list(rows[0].keys()) if rows else []))
            record["row_count"] = len(rows)
            record["sample_rows"] = rows[:5]
            record["status"] = "parsed" if rows else "empty"
    except (OSError, UnicodeError, csv.Error) as exc:
        record["status"] = "invalid"
        record["warnings"].append(f"invalid csv {rel_path}: {exc}")
    return record


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
    selected_scope: dict | None,
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
    record["sample_rows"] = events[:5]
    record["status"] = "parsed" if events else "empty"
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


def raw_binary_artifact_record(path: Path, run_dir: Path, selected_scope: dict | None) -> dict:
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


def app_timeline_segment(rel_path: str) -> str:
    parts = Path(rel_path).parts
    if len(parts) >= 2 and parts[0] == "reports" and parts[1] == "app":
        return "app"
    if any(part.startswith("PROF_") for part in parts):
        return "app"
    return segment_for_relpath(rel_path, "app_timeline")


def performance_summary_segment(source: object, selected_scope: dict | None) -> str:
    name = Path(str(source)).name
    if name.startswith(OP_PERFORMANCE_STDOUT_PREFIXES):
        return "op"
    if name in OP_PERFORMANCE_FALLBACK_STDOUTS and isinstance(selected_scope, dict):
        return "op"
    return "unknown"


def stdout_raw_artifact_records(summary: dict, selected_scope: dict | None) -> list[dict]:
    out = []
    sections = summary.get("stdout_sections", {})
    if not isinstance(sections, dict):
        return out
    for section_name, group in [
        ("occupancy_summary", "stdout_occupancy_summary"),
        ("roofline_summary", "stdout_roofline_summary"),
        ("performance_summary", "stdout_performance_summary"),
    ]:
        section = sections.get(section_name)
        if not isinstance(section, dict):
            continue
        source = str(section.get("source") or "unknown")
        messages = [message for message in section.get("messages", []) if isinstance(message, dict)]
        if section_name == "performance_summary":
            segment = performance_summary_segment(source, selected_scope)
        else:
            segment = "unknown"
        record = empty_raw_artifact_record(
            source,
            group,
            "stdout",
            segment,
            metric_scope_for_segment(segment, selected_scope),
        )
        record["row_count"] = len(messages)
        record["sample_rows"] = messages[:5]
        record["status"] = "parsed" if messages else "empty"
        out.append(record)
    return out


def build_raw_artifact_index(run_dir: Path, summary: dict, selected_scope: dict | None) -> dict:
    artifacts = []
    for group, patterns in FILE_GROUPS.items():
        for path in find_files(run_dir, patterns):
            artifacts.append(raw_csv_artifact_record(path, run_dir, group, selected_scope))
    for path in find_files(run_dir, APP_TIMELINE_PATTERNS):
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
    for path in find_files(run_dir, SIMULATOR_PATTERNS):
        if path.suffix.lower() == ".json":
            artifacts.append(
                raw_json_artifact_record(
                    path,
                    run_dir,
                    "simulator_trace",
                    selected_scope,
                    segment="simulator",
                )
            )
        elif path.suffix.lower() == ".csv":
            artifacts.append(
                raw_csv_artifact_record(
                    path,
                    run_dir,
                    "simulator_csv",
                    selected_scope,
                    segment="simulator",
                )
            )
    for path in find_files(run_dir, UNPARSED_BINARY_PATTERNS):
        artifacts.append(raw_binary_artifact_record(path, run_dir, selected_scope))
    artifacts.extend(stdout_raw_artifact_records(summary, selected_scope))
    artifacts.sort(key=lambda item: (str(item.get("artifact")), str(item.get("group")), str(item.get("parser"))))
    warnings = [
        warning
        for artifact in artifacts
        for warning in artifact.get("warnings", [])
    ]
    return {
        "raw_artifact_index_schema_version": RAW_ARTIFACT_INDEX_SCHEMA_VERSION,
        "artifacts": artifacts,
        "warnings": warnings,
    }
