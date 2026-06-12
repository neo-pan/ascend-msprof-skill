#!/usr/bin/env python3
"""Extract key summaries from Ascend msprof / msprof op output."""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from .ascend_profile_utils import (
    analysis_dir,
    find_files,
    first_present,
    normalized_key,
    read_csv_rows,
    read_json,
    rel,
    summarize_csv,
    to_float,
    top_numeric_row,
    write_json,
)
from .metric_scope_policy import (
    APP_TIMING_ARTIFACTS,
    APP_TIMING_CONTRACT,
    command_metric_scope,
    is_msprof_op_command,
    metric_scope_policy,
    missing_artifact_labels,
    normalize_metric_scope,
    warning_group,
)
from .simulator_hotspot_model import write_simulator_hotspot_model


ANALYSIS_SCHEMA_VERSION = "1.3"
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

DURATION_ALIASES = ["task duration", "task time", "duration", "execution time", "total time", "time"]
COUNT_ALIASES = ["count", "calls", "call count", "op count"]
NAME_ALIASES = ["op name", "operator name", "kernel name", "kernel_name", "task name", "api name", "sub block id", "sub_block_id", "op type", "name"]
OP_BASIC_TILING_ALIASES = ["block dim", "mix block dim", "blockdim", "mixblockdim"]
UTIL_ALIASES = ["utilization", "ratio", "rate", "usage"]
UTIL_EXCLUDE_ALIASES = ["hit_rate", "miss_rate", "usage_rate"]
MEMORY_USAGE_ALIASES = ["usage rate"]
MEMORY_BANDWIDTH_ALIASES = ["bw", "bandwidth"]
MEMORY_USAGE_EXCLUDE_ALIASES: list[str] = []
MEMORY_BANDWIDTH_EXCLUDE_ALIASES = ["usage rate"]
MEMORY_VOLUME_ALIASES = ["datas", "bytes"]
MEMORY_VOLUME_EXCLUDE_ALIASES: list[str] = []
METRIC_LABEL_ALIASES = ["metric"]
METRIC_VALUE_ALIASES = ["value"]
L2_CACHE_TOTAL_HIT_RATE_FIELDS = ["aic_total_hit_rate(%)", "aiv_total_hit_rate(%)"]
RAW_VALUE_FIELD_CANDIDATES = {
    "op_summary": ["Task Duration(us)", "task_duration(us)", "duration(us)", "total time(us)"],
    "op_statistic": ["Total Time(us)", "Avg Time(us)", "Max Time(us)", "Min Time(us)"],
    "task_time": ["task_time(us)", "Task Duration(us)", "task duration(us)"],
    "api_statistic": ["Time(us)", "Avg(us)", "Max(us)", "Min(us)"],
    "op_basic_info": ["Task Duration(us)", "task duration(us)"],
}
DIMENSION_GROUPS = [
    (
        "hot_path_dispatch",
        "Hot Path And Dispatch",
        ["op_summary", "op_statistic", "task_time", "api_statistic"],
    ),
    (
        "pipe_arithmetic_mix",
        "Pipe And Arithmetic Mix",
        ["pipe_utilization", "arithmetic_utilization"],
    ),
    (
        "memory_cache_movement",
        "Memory And Cache Movement",
        ["memory", "l2_cache"],
    ),
    (
        "resource_conflict",
        "Resource And UB Conflict",
        ["resource_conflict"],
    ),
    (
        "tiling_core_balance",
        "Tiling And Core Balance",
        ["op_basic_info", "task_time"],
    ),
]
SIMULATOR_PATTERNS = ["core*_code_exe.csv", "core*_instr_exe.csv", "trace.json"]
APP_TIMELINE_PATTERNS = ["msprof_*.json"]
UNPARSED_BINARY_PATTERNS = ["visualize_data.bin", "DeviceProf*.bin", "duration.bin"]
TIMING_GROUPS = ["op_summary", "task_time", "op_statistic", "api_statistic", "op_basic_info"]
OP_METRIC_GROUPS = ["pipe_utilization", "arithmetic_utilization", "memory", "l2_cache", "resource_conflict"]
READINESS_LEVEL_ORDER = {
    "insufficient": 0,
    "triage_only": 1,
    "directional": 2,
    "actionable_experiment": 3,
}
TARGET_NAME_FIELDS = [
    "expected_kernel_names",
    "expected_op_names",
    "target_kernel_names",
    "target_op_names",
    "expected_kernel_name",
    "expected_op_name",
    "target_kernel_name",
    "target_op_name",
]
TILELANG_CONTEXT_FIELDS = {
    "task_framework",
    "task_language",
    "framework",
    "language",
}
TILELANG_DEFAULT_EXPECTED_KERNEL = "main_kernel"
TARGET_NAME_SUFFIXES = ("mixaic", "aic", "aiv", "cube", "vector")
ON_DEVICE_CORROBORATION_GROUPS = [
    "op_summary",
    "task_time",
    "pipe_utilization",
    "arithmetic_utilization",
    "memory",
    "l2_cache",
    "resource_conflict",
]
SIMULATOR_CSV_VALUE_ALIASES = ["running_time", "cycles", "call_count"]
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


def selected_metric_scope(run_dir: Path) -> dict | None:
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
            policy = metric_scope_policy(normalized)
            out = {
                "value": normalized,
                "artifact": f"logs/{name}",
                "field_ref": "--aic-metrics",
                "known": policy is not None,
            }
            if policy:
                out["policy"] = policy.as_dict()
            return out
    return None


def normalize_target_name(value: object) -> str:
    return normalized_key(str(value))


def target_name_matches(expected: str, observed: str) -> bool:
    expected_norm = normalize_target_name(expected)
    observed_norm = normalize_target_name(observed)
    if not expected_norm or not observed_norm:
        return False
    if expected_norm == observed_norm:
        return True
    if not observed_norm.startswith(expected_norm):
        return False
    suffix = observed_norm[len(expected_norm):]
    return suffix in TARGET_NAME_SUFFIXES


def target_names_from_value(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "", [])]
    return []


def first_target_names(value: object, field_path: list[str]) -> tuple[list[str], str | None]:
    if isinstance(value, dict):
        for field in TARGET_NAME_FIELDS:
            item = value.get(field)
            names = target_names_from_value(item)
            if names:
                return names, ".".join([*field_path, field])
        for key in ["target", "kernel", "operator", "metadata", "jit_config", "profile_harness", "benchmark"]:
            item = value.get(key)
            found, ref = first_target_names(item, [*field_path, key])
            if found:
                return found, ref
    return [], None


def context_mentions_tilelang(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in TILELANG_CONTEXT_FIELDS and "tilelang" in str(item).lower():
                return True
            if context_mentions_tilelang(item):
                return True
    elif isinstance(value, list):
        return any(context_mentions_tilelang(item) for item in value)
    return False


def expected_target_from_context(run_dir: Path) -> dict | None:
    tilelang_default: dict | None = None
    for name in ["profile_context.json", "tilelang_context.json"]:
        path = run_dir / "analysis" / name
        if not path.is_file():
            continue
        try:
            payload = read_json(path)
        except (OSError, ValueError):
            continue
        targets, field_ref = first_target_names(payload, [])
        if targets:
            return {
                "names": targets,
                "artifact": f"analysis/{name}",
                "field_ref": field_ref,
            }
        if tilelang_default is None and context_mentions_tilelang(payload):
            tilelang_default = {
                "names": [TILELANG_DEFAULT_EXPECTED_KERNEL],
                "artifact": f"analysis/{name}",
                "field_ref": "inferred:tilelang_default_kernel",
                "inferred": True,
            }
    return tilelang_default


def observed_target_records(summary: dict) -> list[dict]:
    records = []
    for group in ["op_basic_info", "op_summary", "op_statistic", "task_time"]:
        item = (summary.get("headlines") or {}).get(group)
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if name in (None, "", "n/a"):
            continue
        records.append(
            {
                "group": group,
                "name": str(name),
                "artifact": item.get("file"),
                "field_ref": f"headlines.{group}.name",
            }
        )
    return records


def build_target_identity(run_dir: Path, summary: dict) -> dict:
    expected = expected_target_from_context(run_dir)
    observed = observed_target_records(summary)
    if expected is None:
        status = "unverified" if observed else "missing"
    elif not observed:
        status = "missing_observed"
    else:
        expected_names = [str(name) for name in expected.get("names", [])]
        for item in observed:
            item["status"] = (
                "match"
                if any(target_name_matches(expected_name, str(item["name"])) for expected_name in expected_names)
                else "mismatch"
            )
        mismatches = [item for item in observed if item.get("status") == "mismatch"]
        if not mismatches:
            status = "match"
        elif len(mismatches) == len(observed):
            status = "mismatch"
        else:
            status = "partial_mismatch"
    return {
        "status": status,
        "expected": expected,
        "observed": observed,
    }


def target_identity_warnings(identity: dict) -> list[str]:
    expected = identity.get("expected")
    if not isinstance(expected, dict):
        return []
    expected_names = ", ".join(str(item) for item in expected.get("names", []))
    if identity.get("status") in {"mismatch", "partial_mismatch"}:
        mismatched_names = ", ".join(
            str(item.get("name")) for item in identity.get("observed", []) if item.get("status") != "match"
        )
        return [f"target identity {identity.get('status')}: expected {expected_names}; observed {mismatched_names or 'none'}"]
    if identity.get("status") == "missing_observed":
        return [f"target identity missing observed profiler operator: expected {expected_names}"]
    return []


def parse_occupancy_summary_text(text: str, source: str) -> dict | None:
    messages = []
    in_section = False
    for line in text.splitlines():
        if not in_section:
            if OCCUPANCY_SECTION_START_RE.match(line):
                in_section = True
            continue
        if REPORT_SECTION_HEADER_RE.match(line):
            break
        match = OCCUPANCY_MESSAGE_RE.match(line)
        if match:
            messages.append(
                {
                    "ordinal": int(match.group("ordinal")),
                    "message": match.group("message"),
                }
            )
    if not messages:
        return None
    return {
        "source": source,
        "section": OCCUPANCY_SECTION_NAME,
        "messages": messages,
    }


def parse_occupancy_summary_stdout(run_dir: Path) -> dict | None:
    for path in selected_profiler_stdout_paths(run_dir):
        section = parse_occupancy_summary_text(
            path.read_text(encoding="utf-8", errors="replace"),
            rel(path, run_dir),
        )
        if section:
            return section
    return None


def parse_roofline_summary_text(text: str, source: str) -> dict | None:
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
    return {
        "source": source,
        "section": ROOFLINE_SECTION_NAME,
        "messages": messages,
    }


def parse_roofline_summary_stdout(run_dir: Path) -> dict | None:
    for path in selected_roofline_stdout_paths(run_dir):
        section = parse_roofline_summary_text(
            path.read_text(encoding="utf-8", errors="replace"),
            rel(path, run_dir),
        )
        if section:
            return section
    return None


def parse_performance_summary_text(text: str, source: str) -> dict | None:
    messages = []
    in_section = False
    for line in text.splitlines():
        if not in_section:
            if PERFORMANCE_SECTION_START_RE.match(line):
                in_section = True
            continue
        if REPORT_SECTION_HEADER_RE.match(line) or CANN_INFO_HEADER_RE.match(line):
            break
        match = OCCUPANCY_MESSAGE_RE.match(line)
        if match:
            messages.append(
                {
                    "ordinal": int(match.group("ordinal")),
                    "message": match.group("message"),
                    "source": source,
                }
            )
    if not messages:
        return None
    return {
        "source": source,
        "section": PERFORMANCE_SECTION_NAME,
        "messages": messages,
    }


def parse_performance_summary_stdout(run_dir: Path) -> dict | None:
    for path in selected_performance_stdout_paths(run_dir):
        section = parse_performance_summary_text(
            path.read_text(encoding="utf-8", errors="replace"),
            rel(path, run_dir),
        )
        if section:
            return section
    return None


def md_table_cell(value: object) -> str:
    return "" if value is None else str(value).replace("|", "\\|").replace("\n", " ")


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


def memory_headline(run_dir: Path, files: list[Path]) -> dict:
    best_path = None
    best_row = None
    best_field = None
    best_value = None
    best_kind = None
    for aliases, exclude_aliases, field_kind in [
        (MEMORY_USAGE_ALIASES, MEMORY_USAGE_EXCLUDE_ALIASES, "memory_usage_rate"),
        (MEMORY_BANDWIDTH_ALIASES, MEMORY_BANDWIDTH_EXCLUDE_ALIASES, "memory_bandwidth"),
        (MEMORY_VOLUME_ALIASES, MEMORY_VOLUME_EXCLUDE_ALIASES, "memory_volume"),
    ]:
        best_path = None
        best_row = None
        best_field = None
        best_value = None
        for path in files:
            rows = read_csv_rows(path)
            row, field, value = top_field_cell(rows, aliases, exclude_aliases)
            if value is None:
                row, field, value = top_memory_metric_row(rows, aliases, exclude_aliases)
            if value is None:
                continue
            if best_value is None or value > best_value:
                best_path = path
                best_row = row
                best_field = field
                best_value = value
                best_kind = field_kind
        if best_value is not None:
            break
    return {
        "file": rel(best_path, run_dir) if best_path else rel(files[0], run_dir),
        "name": first_present(best_row or {}, NAME_ALIASES + ["memory", "sub block id", "sub_block_id"], "metric" if best_field else None),
        "value": best_value,
        "field": best_field,
        "field_kind": best_kind or "memory_value_or_rate",
        "raw_row": best_row,
    }


def field_matches(field: str, aliases: list[str], exclude_aliases: list[str]) -> bool:
    normalized_field = normalized_key(field)
    includes = [normalized_key(alias) for alias in aliases]
    excludes = [normalized_key(alias) for alias in exclude_aliases]
    return any(alias and alias in normalized_field for alias in includes) and not any(
        alias and alias in normalized_field for alias in excludes
    )


def top_field_cell(rows: list[dict[str, str]], aliases: list[str], exclude_aliases: list[str]) -> tuple[dict[str, str] | None, str | None, float | None]:
    best_row = None
    best_field = None
    best_value = None
    for row in rows:
        for field, raw_value in row.items():
            if not field_matches(str(field), aliases, exclude_aliases):
                continue
            value = to_float(raw_value)
            if value is None:
                continue
            if best_value is None or value > best_value:
                best_row = row
                best_field = str(field)
                best_value = value
    return best_row, best_field, best_value


def top_memory_metric_row(rows: list[dict[str, str]], aliases: list[str], exclude_aliases: list[str]) -> tuple[dict[str, str] | None, str | None, float | None]:
    best_row = None
    best_field = None
    best_value = None
    for row in rows:
        metric = str(first_present(row, METRIC_LABEL_ALIASES, ""))
        if not field_matches(metric, aliases, exclude_aliases):
            continue
        value_field = first_present(row, METRIC_VALUE_ALIASES)
        value = to_float(value_field)
        if value is None:
            continue
        if best_value is None or value > best_value:
            best_row = row
            best_field = metric
            best_value = value
    return best_row, best_field, best_value


def op_basic_field(first_row: dict[str, str]) -> tuple[str | None, float | None]:
    duration_value = to_float(first_present(first_row, DURATION_ALIASES))
    duration_field = raw_field_for_alias(first_row, DURATION_ALIASES)
    if duration_value is not None and duration_field:
        return duration_field, duration_value
    return None, None


def op_basic_tiling_field(first_row: dict[str, str]) -> tuple[str | None, float | None]:
    tiling_field = raw_field_for_alias(first_row, OP_BASIC_TILING_ALIASES)
    if not tiling_field:
        return None, None
    return tiling_field, to_float(first_row.get(tiling_field))


def raw_field_for_alias(row: dict[str, str], aliases: list[str]) -> str | None:
    lowered = {str(key).strip().lower(): str(key) for key in row}
    normalized = {normalized_key(str(key)): str(key) for key in row}
    for alias in aliases:
        field = lowered.get(alias.strip().lower())
        if field:
            return field
        field = normalized.get(normalized_key(alias))
        if field:
            return field
    for alias in aliases:
        normalized_alias = normalized_key(alias)
        for key, field in normalized.items():
            if normalized_alias and normalized_alias in key:
                return field
    return None


def l2_cache_headline(run_dir: Path, files: list[Path]) -> dict:
    best_path = None
    best_row = None
    best_field = None
    best_value = None
    for path in files:
        for row in read_csv_rows(path):
            for field in L2_CACHE_TOTAL_HIT_RATE_FIELDS:
                value = to_float(row.get(field))
                if value is None:
                    continue
                if best_value is None or value > best_value:
                    best_path = path
                    best_row = row
                    best_field = field
                    best_value = value
    return {
        "file": rel(best_path, run_dir) if best_path else rel(files[0], run_dir),
        "name": first_present(best_row or {}, ["sub_block_id", "sub block id"], "n/a"),
        "value": best_value,
        "field": best_field,
        "field_kind": "l2_cache_hit_rate",
        "raw_row": best_row,
    }


def headline_for_group(run_dir: Path, group: str, patterns: list[str], selected_scope: dict | None) -> dict | None:
    files = find_files(run_dir, patterns)
    if not files:
        return None
    if group == "memory":
        item = memory_headline(run_dir, files)
        return annotate_source_metadata(item, item.get("file", ""), group, selected_scope)
    if group == "l2_cache":
        item = l2_cache_headline(run_dir, files)
        return annotate_source_metadata(item, item.get("file", ""), group, selected_scope)
    path = files[0]
    rows = read_csv_rows(path)
    if group in {"op_summary", "op_statistic", "task_time", "api_statistic"}:
        row, value = top_numeric_row(rows, DURATION_ALIASES)
        return annotate_source_metadata({
            "file": rel(path, run_dir),
            "name": first_present(row or {}, NAME_ALIASES),
            "value": value,
            "field_kind": "duration_or_time",
            "raw_row": row,
        }, rel(path, run_dir), group, selected_scope)
    if group in {"pipe_utilization", "arithmetic_utilization", "resource_conflict"}:
        row, field, value = top_field_cell(rows, UTIL_ALIASES, UTIL_EXCLUDE_ALIASES)
        return annotate_source_metadata({
            "file": rel(path, run_dir),
            "name": first_present(row or {}, NAME_ALIASES + ["pipe", "resource", "metric"]),
            "value": value,
            "field": field,
            "field_kind": "utilization_or_ratio",
            "raw_row": row,
        }, rel(path, run_dir), group, selected_scope)
    if group == "op_basic_info":
        first_row = rows[0] if rows else {}
        field, value = op_basic_field(first_row)
        tiling_field, tiling_value = op_basic_tiling_field(first_row)
        return annotate_source_metadata({
            "file": rel(path, run_dir),
            "row_count": len(rows),
            "name": first_present(first_row, NAME_ALIASES),
            "value": value,
            "field": field,
            "tiling_field": tiling_field,
            "tiling_value": tiling_value,
            "field_kind": "basic_info",
            "first_row": first_row,
        }, rel(path, run_dir), group, selected_scope)
    return None


def raw_value_field_name(group: str, item: dict) -> str | None:
    row_key = "first_row" if group == "op_basic_info" else "raw_row"
    raw_row = item.get(row_key) or {}
    if not isinstance(raw_row, dict):
        return None
    lowered = {str(key).strip().lower(): str(key) for key in raw_row}
    normalized = {normalized_key(str(key)): str(key) for key in raw_row}
    if item.get("field"):
        field = lowered.get(str(item["field"]).strip().lower())
        if field:
            return field
        field = normalized.get(normalized_key(str(item["field"])))
        if field:
            return field
    if group == "op_basic_info":
        return None
    candidates = list(RAW_VALUE_FIELD_CANDIDATES.get(group, []))
    if group in TIMING_GROUPS:
        candidates.extend(DURATION_ALIASES)
    for candidate in candidates:
        field = lowered.get(candidate.strip().lower())
        if field:
            return field
        normalized_candidate = normalized_key(candidate)
        field = normalized.get(normalized_candidate)
        if field:
            return field
    for candidate in candidates:
        normalized_candidate = normalized_key(candidate)
        for key, field in normalized.items():
            if normalized_candidate and normalized_candidate in key:
                return field
    value_field = normalized.get(normalized_key("value"))
    if value_field and (item.get("value") is None or to_float(raw_row.get(value_field)) == to_float(item.get("value"))):
        return value_field
    return None


def signal_field_ref(group: str, item: dict) -> str:
    refs = [f"headlines.{group}.value"]
    raw_field = raw_value_field_name(group, item)
    if raw_field:
        row_key = "first_row" if group == "op_basic_info" else "raw_row"
        refs.append(f"headlines.{group}.{row_key}.{raw_field}")
    if item.get("field"):
        refs.append(f"headlines.{group}.field={item['field']}")
    if item.get("field_kind"):
        refs.append(f"headlines.{group}.field_kind={item['field_kind']}")
    return "; ".join(refs)


def signal_from_headline(group: str, item: dict) -> dict:
    field = raw_value_field_name(group, item)
    signal_name = item.get("name") or "n/a"
    if item.get("field"):
        signal_name = f"{signal_name} / {item['field']}"
    signal = {
        "group": group,
        "signal": signal_name,
        "artifact": item.get("file", "missing"),
        "field": field,
        "field_ref": signal_field_ref(group, item),
        "value": item.get("value"),
        "kind": item.get("field_kind"),
        "row_count": item.get("row_count"),
        "segment": item.get("segment", "unknown"),
        "metric_scope": item.get("metric_scope"),
    }
    if group == "op_basic_info" and item.get("tiling_field"):
        tiling_field = item["tiling_field"]
        signal["tiling_field"] = tiling_field
        signal["tiling_value"] = item.get("tiling_value")
        signal["tiling_field_ref"] = (
            f"headlines.op_basic_info.tiling_value; "
            f"headlines.op_basic_info.first_row.{tiling_field}; "
            f"headlines.op_basic_info.tiling_field={tiling_field}; "
            "headlines.op_basic_info.field_kind=basic_info"
        )
    return signal


def simulator_fallback_signal(path: Path, run_dir: Path) -> dict:
    return {
        "group": "simulator",
        "signal": path.name,
        "artifact": rel(path, run_dir),
        "field": "file",
        "field_ref": "analysis_dimensions.source_pipeline_context.signals.artifact",
        "value": None,
        "kind": "simulator_artifact",
        "segment": "simulator",
        "metric_scope": None,
    }


def simulator_csv_signal(path: Path, run_dir: Path, warnings: list[str]) -> dict:
    best_by_alias: dict[str, tuple[dict[str, str], str, float]] = {}
    has_rows = False
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                has_rows = True
                for alias in SIMULATOR_CSV_VALUE_ALIASES:
                    _, field, value = top_field_cell([row], [alias], [])
                    if value is None or not field:
                        continue
                    best = best_by_alias.get(alias)
                    if best is None or value > best[2]:
                        best_by_alias[alias] = (row, field, value)
    except (OSError, UnicodeError, csv.Error) as exc:
        warnings.append(f"invalid simulator csv {rel(path, run_dir)}: {exc}")
        return simulator_fallback_signal(path, run_dir)
    if not has_rows:
        return simulator_fallback_signal(path, run_dir)
    for alias in SIMULATOR_CSV_VALUE_ALIASES:
        best = best_by_alias.get(alias)
        if best is None:
            continue
        row, field, value = best
        name = first_present(row or {}, ["instr", "code", "pipe", "name"], path.name)
        return {
            "group": "simulator",
            "signal": str(name),
            "artifact": rel(path, run_dir),
            "field": field,
            "field_ref": (
                f"analysis_dimensions.source_pipeline_context.signals.field={field}; "
                "analysis_dimensions.source_pipeline_context.signals.value"
            ),
            "value": value,
            "kind": "simulator_csv",
            "segment": "simulator",
            "metric_scope": None,
        }
    return simulator_fallback_signal(path, run_dir)


def simulator_trace_signal(path: Path, run_dir: Path, warnings: list[str]) -> dict:
    try:
        data = read_json(path)
    except (OSError, ValueError) as exc:
        warnings.append(f"invalid simulator trace {rel(path, run_dir)}: {exc}")
        return simulator_fallback_signal(path, run_dir)
    if isinstance(data, dict):
        events = data.get("traceEvents", [])
    elif isinstance(data, list):
        events = data
    else:
        events = []
    if not isinstance(events, list):
        return simulator_fallback_signal(path, run_dir)
    best_duration_event = None
    best_duration_value = None
    for event in events:
        if not isinstance(event, dict):
            continue
        value = to_float(event.get("dur"))
        if value is None:
            continue
        if best_duration_value is None or value > best_duration_value:
            best_duration_event = event
            best_duration_value = value
    if best_duration_event is not None:
        name = best_duration_event.get("name") or path.name
        return {
            "group": "simulator",
            "signal": str(name),
            "artifact": rel(path, run_dir),
            "field": "traceEvents[].dur",
            "field_ref": (
                "analysis_dimensions.source_pipeline_context.signals.field=traceEvents[].dur; "
                "analysis_dimensions.source_pipeline_context.signals.value"
            ),
            "value": best_duration_value,
            "kind": "simulator_trace",
            "segment": "simulator",
            "metric_scope": None,
        }
    for field in ["ph", "tid", "cat"]:
        for event in events:
            if not isinstance(event, dict) or field not in event:
                continue
            value = event.get(field)
            if value is None:
                continue
            name = event.get("name") or path.name
            return {
                "group": "simulator",
                "signal": str(name),
                "artifact": rel(path, run_dir),
                "field": f"traceEvents[].{field}",
                "field_ref": (
                    f"analysis_dimensions.source_pipeline_context.signals.field=traceEvents[].{field}; "
                    "analysis_dimensions.source_pipeline_context.signals.value"
                ),
                "value": value,
                "kind": "simulator_trace",
                "segment": "simulator",
                "metric_scope": None,
            }
    return simulator_fallback_signal(path, run_dir)


def simulator_signal(path: Path, run_dir: Path, warnings: list[str]) -> dict:
    if path.suffix.lower() == ".json":
        return simulator_trace_signal(path, run_dir, warnings)
    if path.suffix.lower() == ".csv":
        return simulator_csv_signal(path, run_dir, warnings)
    return simulator_fallback_signal(path, run_dir)


def simulator_model_signal(row: dict, signal: str, field: str, value: object, kind: str) -> dict:
    artifact = str(row.get("artifact") or "analysis/simulator_hotspots.json")
    field_ref = (
        f"analysis/simulator_hotspots.json:{row.get('evidence_id', kind)}; "
        f"{row.get('field_ref') or field}; "
        f"analysis_dimensions.source_pipeline_context.signals.field={field}; "
        "analysis_dimensions.source_pipeline_context.signals.value"
    )
    return {
        "group": "simulator",
        "signal": signal,
        "artifact": artifact,
        "field": field,
        "field_ref": field_ref,
        "value": value,
        "kind": kind,
        "evidence_id": row.get("evidence_id"),
        "segment": "simulator",
        "metric_scope": None,
    }


def simulator_signals_from_model(model: dict) -> list[dict]:
    signals = []

    for row in model.get("instructions", [])[:1]:
        field = str(row.get("field") or "running_time(us)")
        value = row.get("value")
        signals.append(
            simulator_model_signal(
                row,
                str(row.get("instr") or "instruction"),
                field,
                value,
                "simulator_instruction",
            )
        )

    for row in model.get("source_lines", [])[:1]:
        field = str(row.get("field") or "running_time(us)")
        value = row.get("value")
        signal_name = row.get("code") or row.get("source_file") or row.get("artifact") or "source line"
        if row.get("source_file") and row.get("line"):
            signal_name = f"{row.get('source_file')}:{row.get('line')}"
        elif row.get("line"):
            signal_name = f"{row.get('artifact', 'source line')}:{row.get('line')}"
        signals.append(simulator_model_signal(row, str(signal_name), field, value, "simulator_source_line"))

    for row in model.get("pipeline_events", [])[:1]:
        signal_name = row.get("max_event_name") or row.get("tid") or "pipeline event"
        signals.append(
            simulator_model_signal(
                row,
                str(signal_name),
                "traceEvents[].dur",
                row.get("value"),
                "simulator_trace",
            )
        )

    for row in model.get("flow_categories", [])[:1]:
        signals.append(
            simulator_model_signal(
                row,
                str(row.get("category") or "flow"),
                "traceEvents[].cat",
                row.get("value"),
                "simulator_flow",
            )
        )

    for row in model.get("sync_events", [])[:2]:
        sources = row.get("sources") or []
        signal = simulator_model_signal(
            row,
            str(row.get("instruction") or "sync event"),
            str(row.get("field") or "traceEvents[].name; instr"),
            row.get("value"),
            "simulator_sync_event",
        )
        if sources:
            signal["artifact"] = "; ".join(str(source) for source in sources)
        signals.append(signal)

    for row in model.get("mte_throughput", [])[:2]:
        signals.append(
            simulator_model_signal(
                row,
                str(row.get("channel") or "MTE Throughput"),
                str(row.get("field") or "throughput(MB/s)"),
                row.get("value"),
                "simulator_mte_throughput",
            )
        )

    seen: set[tuple[str, str, str]] = set()
    deduped = []
    for signal in signals:
        key = (str(signal.get("artifact")), str(signal.get("field")), str(signal.get("signal")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(signal)
    return deduped


def simulator_fallback_signals_from_model(run_dir: Path, model: dict) -> list[dict]:
    signals = []
    input_artifacts = [str(item.get("artifact")) for item in model.get("inputs", []) if item.get("artifact")]
    for artifact in input_artifacts:
        path = run_dir / artifact
        if path.exists():
            signals.append(simulator_signal(path, run_dir, []))
    return signals


def build_analysis_dimensions(run_dir: Path, summary: dict) -> list[dict]:
    headlines = summary.get("headlines", {})
    dimensions: list[dict] = []
    for dimension_id, title, groups in DIMENSION_GROUPS:
        signals = []
        for group in groups:
            item = headlines.get(group)
            if isinstance(item, dict):
                signals.append(signal_from_headline(group, item))
        dimensions.append(
            {
                "id": dimension_id,
                "title": title,
                "status": "available" if signals else "insufficient",
                "signals": signals,
                "evidence_refs": [f"{signal['artifact']}; {signal['field_ref']}" for signal in signals],
            }
        )

    model = summary.get("_simulator_hotspot_model") if isinstance(summary.get("_simulator_hotspot_model"), dict) else {}
    simulator_signals = simulator_signals_from_model(model)
    if not simulator_signals:
        simulator_signals = simulator_fallback_signals_from_model(run_dir, model)
    dimensions.append(
        {
            "id": "source_pipeline_context",
            "title": "Source And Pipeline Context",
            "status": "available" if simulator_signals else "insufficient",
            "model_artifact": "analysis/simulator_hotspots.json",
            "signals": simulator_signals,
            "evidence_refs": [f"{signal['artifact']}; {signal['field_ref']}" for signal in simulator_signals],
        }
    )
    return dimensions


def first_signal(dimensions: list[dict], groups: list[str]) -> dict | None:
    for group in groups:
        for dimension in dimensions:
            for signal in dimension.get("signals", []):
                if signal.get("group") == group:
                    return signal
    return None


def first_signal_with_value(dimensions: list[dict], groups: list[str]) -> dict | None:
    for group in groups:
        for dimension in dimensions:
            for signal in dimension.get("signals", []):
                if signal.get("group") == group and signal.get("value") is not None:
                    return signal
    return None


def first_timing_signal(dimensions: list[dict]) -> dict | None:
    return first_signal_with_value(dimensions, TIMING_GROUPS)


def signals_with_values_for_groups(dimensions: list[dict], groups: list[str]) -> list[dict]:
    out = []
    for group in groups:
        signal = first_signal_with_value(dimensions, [group])
        if signal:
            out.append(signal)
    return out


def independent_on_device_signal(dimensions: list[dict]) -> dict | None:
    return first_signal_with_value(dimensions, ON_DEVICE_CORROBORATION_GROUPS)


def op_basic_tiling_signal(signal: dict | None) -> dict | None:
    if not signal:
        return None
    tiling_field = signal.get("tiling_field")
    if not tiling_field:
        return None
    tiling_value = signal.get("tiling_value")
    if tiling_value is None:
        return None
    signal_name = str(signal.get("signal") or "n/a").split(" / ", 1)[0]
    return {
        "group": "op_basic_info",
        "signal": f"{signal_name} / {tiling_field}",
        "artifact": signal.get("artifact"),
        "field": tiling_field,
        "field_ref": signal.get("tiling_field_ref"),
        "value": tiling_value,
        "kind": signal.get("kind"),
        "segment": signal.get("segment", "unknown"),
        "metric_scope": signal.get("metric_scope"),
    }


def op_basic_launch_metadata_signals(summary: dict) -> list[dict]:
    item = summary.get("headlines", {}).get("op_basic_info")
    if not isinstance(item, dict):
        return []
    artifact = item.get("file")
    first_row = item.get("first_row") or {}
    if not isinstance(first_row, dict):
        return []
    signals = []
    for field_name in ["Block Dim", "Mix Block Dim"]:
        field = raw_field_for_alias(first_row, [field_name])
        if not field:
            continue
        value = to_float(first_row.get(field))
        if value is None:
            continue
        name = item.get("name") or "n/a"
        signals.append(
            {
                "group": "op_basic_info",
                "signal": f"{name} / {field}",
                "artifact": artifact,
                "field": field,
                "field_ref": (
                    f"headlines.op_basic_info.first_row.{field}; "
                    f"headlines.op_basic_info.launch_metadata.{field}; "
                    "headlines.op_basic_info.field_kind=basic_info"
                ),
                "value": value,
                "kind": "launch_metadata",
                "segment": item.get("segment", "unknown"),
                "metric_scope": item.get("metric_scope"),
            }
        )
    return signals


def performance_summary_segment(source: object, selected_scope: dict | None) -> str:
    name = Path(str(source)).name
    if name.startswith(OP_PERFORMANCE_STDOUT_PREFIXES):
        return "op"
    if name in OP_PERFORMANCE_FALLBACK_STDOUTS and isinstance(selected_scope, dict):
        return "op"
    return "unknown"


def performance_summary_signals(summary: dict) -> list[dict]:
    section = summary.get("stdout_sections", {}).get("performance_summary")
    if not isinstance(section, dict):
        return []
    signals = []
    source = section.get("source", "missing")
    selected_scope = summary.get("metric_scope")
    for index, message in enumerate(section.get("messages", [])):
        if not isinstance(message, dict):
            continue
        message_source = message.get("source") or source
        segment = performance_summary_segment(message_source, selected_scope)
        ordinal = message.get("ordinal")
        if ordinal is not None:
            message_ref = f"stdout_sections.performance_summary.messages[ordinal={ordinal}].message"
        else:
            message_ref = f"stdout_sections.performance_summary.messages[{index}].message"
        signals.append(
            {
                "group": "performance_summary",
                "signal": f"Performance Summary {ordinal}" if ordinal is not None else "Performance Summary",
                "artifact": message_source,
                "field": "message",
                "field_ref": (
                    "stdout_sections.performance_summary.messages[].message; "
                    f"{message_ref}"
                ),
                "value": message.get("message"),
                "kind": "stdout_message",
                "segment": segment,
                "metric_scope": metric_scope_for_segment(segment, selected_scope),
            }
        )
    return signals


def evidence_id(signal: dict, index: int) -> str:
    group = normalized_key(str(signal.get("group") or "signal")) or "signal"
    field = normalized_key(str(signal.get("field") or signal.get("kind") or "value")) or "value"
    return f"ev_{index:02d}_{group}_{field}"


def direction_evidence(signals: list[dict]) -> list[dict]:
    out = []
    seen: set[tuple[str, str]] = set()
    for signal in signals:
        key = (str(signal.get("artifact")), str(signal.get("field_ref")))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "evidence_id": evidence_id(signal, len(out) + 1),
                "artifact": signal.get("artifact"),
                "field": signal.get("field"),
                "field_ref": signal.get("field_ref"),
                "signal": signal.get("signal"),
                "value": signal.get("value"),
                "segment": signal.get("segment", "unknown"),
                "metric_scope": signal.get("metric_scope"),
            }
        )
    return out


def direction(
    direction_id: str,
    title: str,
    action: str,
    signals: list[dict],
    score: tuple[int, int, int],
    confidence: str,
    effort: str,
    impact_basis: str,
) -> dict:
    evidence = direction_evidence(signals)
    return {
        "id": direction_id,
        "title": title,
        "action": action,
        "evidence": evidence,
        "requires_artifacts": sorted(
            {
                str(item.get("artifact"))
                for item in evidence
                if item.get("artifact") not in (None, "", "missing")
            }
        ),
        "missing_artifacts": [],
        "confidence": confidence,
        "effort": effort,
        "impact_basis": impact_basis,
        "score": list(score),
    }


EXPERIMENT_HINTS = {
    "focus_hot_path": {
        "inspect_code_area": (
            "Profiled operator, task, or host/runtime path named by the timing evidence."
        ),
        "next_experiment": (
            "Collect the missing operator-level metric family before changing kernel code, "
            "or isolate the hot operator with a standalone harness."
        ),
        "expected_profiler_change": (
            "A useful follow-up should preserve the same hot target while adding pipe, "
            "arithmetic, memory/cache, conflict, or simulator evidence."
        ),
        "recollect_artifacts": [
            "op_summary_*.csv",
            "task_time_*.csv",
            "OpBasicInfo.csv",
            "PipeUtilization.csv",
        ],
        "caveats": [
            "Timing-only evidence ranks what to inspect next; it does not justify a concrete kernel change.",
        ],
    },
    "inspect_pipe_arithmetic_mix": {
        "inspect_code_area": (
            "Compute loop, vector/cube/scalar work split, epilogue, and instruction mix around the timed kernel path."
        ),
        "next_experiment": (
            "Change one compute-path or pipe-balance variable at a time, keeping workload and launch metadata fixed."
        ),
        "expected_profiler_change": (
            "If the experiment is useful, duration should decrease and the relevant "
            "PipeUtilization.csv / ArithmeticUtilization.csv ratio or time fields should move consistently "
            "with the intended path."
        ),
        "recollect_artifacts": [
            "task_time_*.csv",
            "op_summary_*.csv",
            "PipeUtilization.csv",
            "ArithmeticUtilization.csv",
            "OpBasicInfo.csv",
        ],
        "caveats": [
            "This is an experiment hint, not a code-change instruction.",
        ],
    },
    "inspect_pipe_utilization_advisory": {
        "inspect_code_area": (
            "Launch metadata, blockDim/mix blockDim, and pipe usage around the timed kernel path."
        ),
        "next_experiment": (
            "Validate the stdout message against CSV evidence, then change one launch or path-mix "
            "variable at a time only if the CSV evidence stays aligned."
        ),
        "expected_profiler_change": (
            "If the experiment is useful, duration and the cited pipe CSV fields should improve; "
            "stdout wording alone is not enough."
        ),
        "recollect_artifacts": [
            "task_time_*.csv",
            "op_summary_*.csv",
            "PipeUtilization.csv",
            "OpBasicInfo.csv",
            "profiler stdout log",
        ],
        "caveats": [
            "Treat stdout performance-summary messages as corroborating context, not an independent diagnosis source.",
            "This is an experiment hint, not a code-change instruction.",
        ],
    },
    "inspect_memory_movement": {
        "inspect_code_area": (
            "DataCopy granularity, GM/UB movement, UB/L0 buffering, tile reuse, queue depth, "
            "and double-buffering around the timed path."
        ),
        "next_experiment": (
            "Change one memory-movement variable at a time, such as tile shape, copy granularity, "
            "buffering strategy, or reuse pattern."
        ),
        "expected_profiler_change": (
            "If the experiment is useful, duration should decrease and memory/cache fields should move "
            "consistently with pipe/MTE evidence."
        ),
        "recollect_artifacts": [
            "task_time_*.csv",
            "op_summary_*.csv",
            "PipeUtilization.csv",
            "Memory.csv",
            "MemoryL0.csv",
            "MemoryUB.csv",
            "L2Cache.csv",
            "OpBasicInfo.csv",
        ],
        "caveats": [
            "This is an experiment hint, not a code-change instruction.",
        ],
    },
    "inspect_resource_conflict": {
        "inspect_code_area": (
            "UB layout, alignment, queue schedule, resource sharing, and synchronization/control path "
            "near the timed kernel path."
        ),
        "next_experiment": (
            "Change one layout, alignment, queue, or schedule variable at a time and compare conflict "
            "ratios with timing."
        ),
        "expected_profiler_change": (
            "If the experiment is useful, duration should decrease and ResourceConflictRatio.csv fields "
            "should improve without regressing pipe or memory evidence."
        ),
        "recollect_artifacts": [
            "task_time_*.csv",
            "op_summary_*.csv",
            "ResourceConflictRatio.csv",
            "PipeUtilization.csv",
            "ArithmeticUtilization.csv",
            "OpBasicInfo.csv",
        ],
        "caveats": [
            "This is an experiment hint, not a code-change instruction.",
        ],
    },
    "inspect_tiling_core_balance": {
        "inspect_code_area": (
            "Tiling calculation, blockDim/mix blockDim, tail handling, per-core workload partitioning, "
            "and shape specialization."
        ),
        "next_experiment": (
            "Change one tiling or work-distribution variable at a time while keeping the same workload "
            "and correctness contract."
        ),
        "expected_profiler_change": (
            "If the experiment is useful, duration should decrease and simulator per-core/source context "
            "or task timing should show a more favorable distribution for the same target."
        ),
        "recollect_artifacts": [
            "task_time_*.csv",
            "op_summary_*.csv",
            "OpBasicInfo.csv",
            "trace.json",
            "core*_code_exe.csv",
            "core*_instr_exe.csv",
        ],
        "caveats": [
            "This is an experiment hint, not a code-change instruction.",
        ],
    },
}


def base_recollect_artifacts(direction_id: str, summary: dict) -> list[str]:
    template = EXPERIMENT_HINTS.get(direction_id)
    if not template:
        return []
    artifacts = list(template.get("recollect_artifacts") or [])
    if direction_id == "focus_hot_path":
        for action in summary.get("next_collection_actions") or []:
            if isinstance(action, dict):
                artifacts.extend(str(item) for item in action.get("required_artifacts") or [])
    out = []
    seen = set()
    for artifact in artifacts:
        if artifact in seen:
            continue
        seen.add(artifact)
        out.append(artifact)
    return out


def experiment_caveats(direction_id: str) -> list[str]:
    template = EXPERIMENT_HINTS.get(direction_id)
    if not template:
        return []
    return list(template.get("caveats") or [])


def evidence_text(evidence_items: list[dict]) -> str:
    return repr(evidence_items).lower()


def has_timing_evidence(evidence_items: list[dict]) -> bool:
    text = evidence_text(evidence_items)
    return any(
        token in text
        for token in [
            "opsummary",
            "opstatistic",
            "tasktime",
            "task duration",
            "duration_or_time",
        ]
    )


def has_relevant_source_context_evidence(direction_id: str, evidence_items: list[dict]) -> bool:
    text = evidence_text(evidence_items)
    if direction_id == "inspect_pipe_arithmetic_mix":
        return "pipeutilization" in text and "arithmeticutilization" in text
    if direction_id == "inspect_pipe_utilization_advisory":
        return "pipeutilization" in text
    if direction_id == "inspect_memory_movement":
        return "pipeutilization" in text and any(token in text for token in ["memory", "l2cache"])
    if direction_id == "inspect_resource_conflict":
        return "resourceconflict" in text
    if direction_id == "inspect_tiling_core_balance":
        return "opbasicinfo" in text and "simulator" in text
    return False


SOURCE_CONTEXT_ORDER = {
    "inspect_pipe_arithmetic_mix": ["instructions", "pipeline_events", "source_lines"],
    "inspect_pipe_utilization_advisory": ["instructions", "pipeline_events", "source_lines"],
    "inspect_memory_movement": ["source_lines", "instructions", "pipeline_events"],
    "inspect_resource_conflict": ["source_lines", "instructions", "pipeline_events"],
    "inspect_tiling_core_balance": ["source_lines", "pipeline_events", "instructions"],
}


SOURCE_CONTEXT_ROLES = {
    "source_lines": "source-line inspection context",
    "instructions": "instruction inspection context",
    "pipeline_events": "pipeline inspection context",
}


def source_context_signal(row: dict) -> object:
    for key in ["signal", "evidence_id", "max_event_name", "source_file", "instruction"]:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def source_context_value(row: dict) -> object:
    for key in ["value", "duration", "running_time(us)", "running_time", "max_duration"]:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def source_context_hints(summary: dict, direction_id: str, evidence_items: list[dict], limit: int = 3) -> list[dict]:
    if not has_timing_evidence(evidence_items):
        return []
    if not has_relevant_source_context_evidence(direction_id, evidence_items):
        return []
    model = summary.get("_simulator_hotspot_model")
    if not isinstance(model, dict):
        return []
    out = []
    for group in SOURCE_CONTEXT_ORDER.get(direction_id, []):
        rows = model.get(group)
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            item = {
                "artifact": "analysis/simulator_hotspots.json",
                "field_ref": f"{group}[{index}]",
                "role": SOURCE_CONTEXT_ROLES[group],
            }
            signal = source_context_signal(row)
            if signal not in (None, ""):
                item["signal"] = signal
            value = source_context_value(row)
            if value not in (None, ""):
                item["value"] = value
            out.append(item)
            if len(out) >= limit:
                return out
    return out


def experiment_hint_for_direction(direction_id: str, summary: dict, evidence_items: list[dict]) -> dict | None:
    template = EXPERIMENT_HINTS.get(direction_id)
    if not template or not evidence_items:
        return None
    hint = {
        "inspect_code_area": template["inspect_code_area"],
        "next_experiment": template["next_experiment"],
        "expected_profiler_change": template["expected_profiler_change"],
        "recollect_artifacts": base_recollect_artifacts(direction_id, summary),
        "caveats": experiment_caveats(direction_id),
    }
    source_context = source_context_hints(summary, direction_id, evidence_items)
    if source_context:
        hint["source_context"] = source_context
    return hint


def build_optimization_directions(summary: dict) -> list[dict]:
    target_identity = summary.get("target_identity")
    if isinstance(target_identity, dict) and target_identity.get("status") in {
        "mismatch",
        "partial_mismatch",
        "missing_observed",
    }:
        return []

    dimensions = summary.get("analysis_dimensions", [])
    timing = first_timing_signal(dimensions)
    pipe = first_signal_with_value(dimensions, ["pipe_utilization"])
    arithmetic = first_signal_with_value(dimensions, ["arithmetic_utilization"])
    memory = first_signal_with_value(dimensions, ["memory"])
    l2_cache = first_signal_with_value(dimensions, ["l2_cache"])
    memory_or_cache = memory or l2_cache
    conflict = first_signal_with_value(dimensions, ["resource_conflict"])
    op_basic = first_signal(dimensions, ["op_basic_info"])
    simulator = first_signal_with_value(dimensions, ["simulator"])
    on_device_corroboration = independent_on_device_signal(dimensions)
    performance_messages = performance_summary_signals(summary)

    if not timing:
        return []

    directions = [
        direction(
            "focus_hot_path",
            "Focus Hot Path Inspection",
            "Use the top timing evidence to choose the next profiling target before changing kernel code.",
            [timing],
            (10, 0, 0),
            "low",
            "low",
            "Timing evidence is available without enough corroborating metric families for a concrete code direction.",
        )
    ]

    pipe_arithmetic = signals_with_values_for_groups(dimensions, ["pipe_utilization", "arithmetic_utilization"])
    if pipe and arithmetic:
        directions.append(
            direction(
                "inspect_pipe_arithmetic_mix",
                "Inspect Pipe And Arithmetic Mix",
                "Inspect whether the dominant pipe and arithmetic mix match the intended Ascend C execution path before changing tiling or compute code.",
                [timing, *pipe_arithmetic],
                (70, len(pipe_arithmetic), 1),
                "medium",
                "medium",
                "Timing evidence is corroborated by PipeUtilization and ArithmeticUtilization signals.",
            )
        )

    if pipe and performance_messages:
        launch_metadata = op_basic_launch_metadata_signals(summary)
        directions.append(
            direction(
                "inspect_pipe_utilization_advisory",
                "Inspect Pipe Utilization Advisory",
                "Inspect CANN performance summary messages with PipeUtilization.csv and launch metadata before changing kernel code.",
                [timing, pipe, *performance_messages, *launch_metadata],
                (68, 1 + len(performance_messages), 1),
                "medium",
                "medium",
                "Timing evidence is corroborated by PipeUtilization.csv and CANN performance summary stdout messages.",
            )
        )

    memory_signals = signals_with_values_for_groups(dimensions, ["pipe_utilization", "memory", "l2_cache"])
    if pipe and memory_or_cache:
        directions.append(
            direction(
                "inspect_memory_movement",
                "Inspect Memory And Data Movement",
                "Inspect GM/UB/L0 movement and DataCopy feeding around the timed path before changing buffering or tile reuse.",
                [timing, *memory_signals],
                (65, len(memory_signals), 1),
                "medium",
                "medium",
                "Timing evidence is corroborated by pipe and memory/cache movement signals.",
            )
        )

    conflict_signals = signals_with_values_for_groups(
        dimensions,
        ["resource_conflict", "pipe_utilization", "arithmetic_utilization", "simulator"],
    )
    if conflict and (pipe or arithmetic or simulator):
        conflict_impact_basis = (
            "Timing evidence is corroborated by ResourceConflictRatio and another operator-level metric family."
            if pipe or arithmetic
            else "Timing evidence is corroborated by ResourceConflictRatio and simulator source/pipeline context."
        )
        directions.append(
            direction(
                "inspect_resource_conflict",
                "Inspect UB Or Resource Conflict",
                "Inspect UB layout, queue schedule, and conflicting resource usage around the timed path before changing kernel structure.",
                [timing, *conflict_signals],
                (60, len(conflict_signals), 1),
                "medium",
                "medium",
                conflict_impact_basis,
            )
        )

    tiling_signal = op_basic_tiling_signal(op_basic)
    balance_signals = [signal for signal in [tiling_signal, on_device_corroboration, simulator] if signal]
    if tiling_signal and simulator and on_device_corroboration:
        directions.append(
            direction(
                "inspect_tiling_core_balance",
                "Inspect Tiling And Core Balance",
                "Inspect blockDim, per-core simulator timing, and workload shape before changing work distribution.",
                [timing, *balance_signals],
                (55, len(balance_signals), 1),
                "medium",
                "high",
                "Timing evidence is corroborated by operator metadata and simulator context.",
            )
        )

    directions.sort(key=lambda item: (-item["score"][0], -item["score"][1], -item["score"][2], item["id"]))
    for index, item in enumerate(directions[:3], start=1):
        item["rank"] = index
        item.pop("score", None)
        hint = experiment_hint_for_direction(item["id"], summary, item.get("evidence") or [])
        if hint:
            item["experiment_hint"] = hint
    return directions[:3]


def missing_groups_from_warnings(summary: dict) -> set[str]:
    groups = set()
    for warning in summary.get("warnings", []):
        group = warning_group(str(warning))
        if group:
            groups.add(group)
    return groups


def scope_evidence(scope: dict) -> list[dict]:
    return [
        {
            "evidence_id": "ev_01_metric_scope",
            "artifact": scope.get("artifact"),
            "field": scope.get("field_ref"),
            "field_ref": scope.get("field_ref"),
            "signal": f"--aic-metrics={scope.get('value')}",
            "value": scope.get("value"),
        }
    ]


def missing_warning_evidence(summary: dict, groups: list[str], start_index: int = 2) -> list[dict]:
    evidence = []
    warnings = [str(warning) for warning in summary.get("warnings", [])]
    for group in groups:
        prefix = f"missing {group}:"
        warning = next((item for item in warnings if item.startswith(prefix)), None)
        if not warning:
            continue
        evidence.append(
            {
                "evidence_id": f"ev_{start_index + len(evidence):02d}_missing_{normalized_key(group)}",
                "artifact": "analysis/summary.json",
                "field": "warnings",
                "field_ref": f"warnings[] startswith {prefix}",
                "signal": warning,
                "value": None,
            }
        )
    return evidence


def missing_stdout_evidence(summary: dict, sections: tuple[str, ...], start_index: int = 2) -> list[dict]:
    evidence = []
    stdout_sections = summary.get("stdout_sections", {})
    if not isinstance(stdout_sections, dict):
        stdout_sections = {}
    for section in sections:
        if stdout_sections.get(section):
            continue
        evidence.append(
            {
                "evidence_id": f"ev_{start_index + len(evidence):02d}_missing_{normalized_key(section)}",
                "artifact": "analysis/summary.json",
                "field": f"stdout_sections.{section}",
                "field_ref": f"stdout_sections.{section}",
                "signal": f"missing stdout section {section}",
                "value": None,
            }
        )
    return evidence


def collect_action(
    action_id: str,
    reason: str,
    recommended_aic_metrics: list[str],
    required_groups: list[str],
    evidence: list[dict],
    confidence: str,
) -> dict:
    return {
        "id": action_id,
        "reason": reason,
        "recommended_aic_metrics": recommended_aic_metrics,
        "required_artifacts": missing_artifact_labels(required_groups),
        "evidence": evidence,
        "confidence": confidence,
    }


def build_next_collection_actions(summary: dict) -> list[dict]:
    scope = summary.get("metric_scope")
    if not isinstance(scope, dict):
        return []
    policy = metric_scope_policy(scope.get("value"))
    if not policy:
        return []

    missing_groups = missing_groups_from_warnings(summary)
    actions = []
    required_missing = [group for group in policy.required_artifacts if group in missing_groups]
    required_stdout_missing = []
    if policy.scope in {"Occupancy", "Roofline"}:
        required_stdout_missing = [
            section
            for section in policy.stdout_sections
            if not summary.get("stdout_sections", {}).get(section)
        ]
    if required_missing or required_stdout_missing:
        action_groups = list(required_missing) + list(required_stdout_missing)
        evidence = scope_evidence(scope)
        evidence.extend(missing_warning_evidence(summary, list(required_missing), len(evidence) + 1))
        evidence.extend(missing_stdout_evidence(summary, tuple(required_stdout_missing), len(evidence) + 1))
        actions.append(
            collect_action(
                f"recollect_{normalized_key(policy.scope)}",
                f"Selected {policy.scope} scope is missing expected evidence; recollect before relying on this scope.",
                [policy.scope],
                action_groups,
                evidence,
                "medium",
            )
        )

    if policy.scope == "PipeUtilization":
        optional_followup_groups = [
            group
            for group in ["arithmetic_utilization", "memory", "resource_conflict"]
            if group in missing_groups
        ]
        if optional_followup_groups:
            evidence = scope_evidence(scope)
            evidence.extend(missing_warning_evidence(summary, optional_followup_groups, len(evidence) + 1))
            actions.append(
                collect_action(
                    "collect_default_metric_followup",
                    (
                        "PipeUtilization-only evidence leaves arithmetic, memory, or conflict "
                        "families uncollected; use this as optional follow-up before code-change hypotheses."
                    ),
                    ["Default"],
                    optional_followup_groups,
                    evidence,
                    "low",
                )
            )

    return actions


def has_headline(summary: dict, group: str) -> bool:
    return isinstance((summary.get("headlines") or {}).get(group), dict)


def parsed_artifact_groups(raw_artifact_index: dict) -> set[str]:
    groups = set()
    for item in raw_artifact_index.get("artifacts", []):
        if not isinstance(item, dict):
            continue
        if item.get("status") != "parsed":
            continue
        group = item.get("group")
        if group:
            groups.add(str(group))
    return groups


def available_evidence_families(summary: dict, raw_artifact_index: dict) -> list[str]:
    parsed_groups = parsed_artifact_groups(raw_artifact_index)
    out = []
    if any(has_headline(summary, group) for group in APP_TIMING_ARTIFACTS):
        out.append("app_timing")
    if has_headline(summary, "op_basic_info"):
        out.append("operator_metadata")
    if has_headline(summary, "pipe_utilization"):
        out.append("pipe_utilization")
    if has_headline(summary, "arithmetic_utilization"):
        out.append("arithmetic_utilization")
    if has_headline(summary, "memory") or has_headline(summary, "l2_cache"):
        out.append("memory_cache")
    if has_headline(summary, "resource_conflict"):
        out.append("resource_conflict")
    if "simulator_trace" in parsed_groups or "simulator_csv" in parsed_groups:
        out.append("simulator_source_pipeline")
    stdout_sections = summary.get("stdout_sections") or {}
    if isinstance(stdout_sections.get("occupancy_summary"), dict):
        out.append("stdout_occupancy_summary")
    if isinstance(stdout_sections.get("roofline_summary"), dict):
        out.append("stdout_roofline_summary")
    if isinstance(stdout_sections.get("performance_summary"), dict):
        out.append("stdout_performance_summary")
    return out


def workload_context_available(run_dir: Path) -> bool:
    for name in ["profile_context.json", "tilelang_context.json"]:
        path = run_dir / "analysis" / name
        if not path.is_file():
            continue
        try:
            payload = read_json(path)
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and payload:
            return True
    return False


def readiness_segment_status(missing_required: list[str], present_required: list[str], present_optional: list[str]) -> str:
    if missing_required and (present_required or present_optional):
        return "partial"
    if missing_required:
        return "missing_required_artifacts"
    return "ready"


def readiness_stage_for_app(summary: dict) -> dict:
    required = list(APP_TIMING_ARTIFACTS)
    present_required = [group for group in required if has_headline(summary, group)]
    missing_required = [] if present_required else required
    return {
        "segment": "app",
        "metric_scope": APP_TIMING_CONTRACT["scope"],
        "status": "ready" if present_required else "missing_required_artifacts",
        "missing_required_artifacts": missing_artifact_labels(missing_required),
    }


def segment_artifacts(raw_artifact_index: dict, segment: str) -> list[dict]:
    return [
        item
        for item in raw_artifact_index.get("artifacts", [])
        if isinstance(item, dict) and item.get("segment") == segment
    ]


def readiness_stage_for_scope(
    raw_artifact_index: dict,
    segment: str,
    scope_value: str | None,
) -> dict:
    policy = metric_scope_policy(scope_value)
    artifacts = segment_artifacts(raw_artifact_index, segment)
    groups_present = {
        str(item.get("group"))
        for item in artifacts
        if item.get("status") == "parsed" and item.get("group")
    }
    if not policy:
        return {
            "segment": segment,
            "metric_scope": scope_value,
            "status": "not_applicable",
            "missing_required_artifacts": [],
        }

    present_required = [group for group in policy.required_artifacts if group in groups_present]
    missing_required = [group for group in policy.required_artifacts if group not in groups_present]
    present_optional = [group for group in policy.optional_artifacts if group in groups_present]
    return {
        "segment": segment,
        "metric_scope": policy.scope,
        "status": readiness_segment_status(missing_required, present_required, present_optional),
        "missing_required_artifacts": missing_artifact_labels(missing_required),
    }


def known_scope_segments(summary: dict, raw_artifact_index: dict) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    selected = summary.get("metric_scope")
    if isinstance(selected, dict) and selected.get("value"):
        out.append(("op", str(selected["value"])))
    for item in raw_artifact_index.get("artifacts", []):
        if not isinstance(item, dict):
            continue
        segment = str(item.get("segment") or "")
        scope = item.get("metric_scope")
        if segment.startswith("followup:") and scope:
            pair = (segment, str(scope))
            if pair not in out:
                out.append(pair)
    if not out and any(has_headline(summary, group) for group in ["op_basic_info", *OP_METRIC_GROUPS]):
        out.append(("op", None))
    return out


def readiness_level(families: list[str], target_status: str, has_workload_context: bool) -> str:
    has_timing = "app_timing" in families
    metric_families = {
        "pipe_utilization",
        "arithmetic_utilization",
        "memory_cache",
        "resource_conflict",
    }
    has_metric = any(family in families for family in metric_families)
    has_source = "simulator_source_pipeline" in families
    if not has_timing:
        return "triage_only" if has_metric else "insufficient"
    if not has_metric:
        return "triage_only"
    if target_status in {"mismatch", "partial_mismatch", "missing_observed"}:
        return "triage_only"
    if has_source or has_workload_context:
        return "actionable_experiment"
    return "directional"


def readiness_reasons(families: list[str], target_status: str, has_workload_context: bool) -> list[str]:
    reasons = []
    if "app_timing" in families:
        reasons.append("Parser-visible application timing evidence is present.")
    else:
        reasons.append("Parser-visible application timing evidence is missing.")
    if any(family in families for family in ["pipe_utilization", "arithmetic_utilization", "memory_cache", "resource_conflict"]):
        reasons.append("At least one parser-visible operator metric family is present.")
    else:
        reasons.append("No parser-visible operator metric family is present.")
    if "simulator_source_pipeline" in families:
        reasons.append("Simulator source or pipeline context is present as raw context.")
    elif has_workload_context:
        reasons.append("Workload or shape context is recorded in analysis context.")
    if target_status in {"mismatch", "partial_mismatch", "missing_observed"}:
        reasons.append(f"Target identity status is {target_status}; optimization claims are limited.")
    return reasons


def missing_evidence_families(families: list[str], has_workload_context: bool) -> list[str]:
    required = ["app_timing", "operator_metric", "source_or_workload_context"]
    missing = []
    if "app_timing" not in families:
        missing.append("app_timing")
    if not any(family in families for family in ["pipe_utilization", "arithmetic_utilization", "memory_cache", "resource_conflict"]):
        missing.append("operator_metric")
    if "simulator_source_pipeline" not in families and not has_workload_context:
        missing.append("source_or_workload_context")
    return [item for item in required if item in missing]


def claim_lists(level: str, families: list[str]) -> tuple[list[str], list[str]]:
    allowed = []
    blocked = []
    if "app_timing" in families:
        allowed.append("rank application-level hot path")
    else:
        blocked.append("rank hot path without parser-visible timing")
    if "pipe_utilization" in families:
        allowed.append("rank first AI Core pipe inspection direction")
    if "arithmetic_utilization" in families:
        allowed.append("inspect arithmetic utilization direction")
    if "memory_cache" in families:
        allowed.append("inspect memory/cache movement direction")
    if "resource_conflict" in families:
        allowed.append("inspect resource conflict direction")
    if READINESS_LEVEL_ORDER.get(level, 0) < READINESS_LEVEL_ORDER["actionable_experiment"]:
        blocked.append("propose focused kernel code experiment without stronger context")
    if "simulator_source_pipeline" not in families:
        blocked.append("source-line or instruction attribution without simulator/source artifacts")
    return allowed, blocked


def readiness_followups(summary: dict, missing_families: list[str]) -> list[dict]:
    existing = summary.get("next_collection_actions")
    if isinstance(existing, list) and existing:
        return existing
    out = []
    if "app_timing" in missing_families:
        out.append(
            {
                "id": "collect_app_timing",
                "reason": "Collect application-level msprof timing so the hot path is known.",
                "recommended_aic_metrics": [],
                "required_artifacts": list(APP_TIMING_CONTRACT["required_artifacts"]),
                "confidence": "medium",
            }
        )
    if "operator_metric" in missing_families:
        out.append(
            {
                "id": "collect_pipe_utilization",
                "reason": "Collect operator-level PipeUtilization as the minimal AI Core metric family.",
                "recommended_aic_metrics": ["PipeUtilization"],
                "required_artifacts": missing_artifact_labels(("op_basic_info", "pipe_utilization")),
                "confidence": "medium",
            }
        )
    if "source_or_workload_context" in missing_families:
        out.append(
            {
                "id": "collect_source_or_context",
                "reason": "Add simulator/source context or record strong workload/shape context before focused code experiments.",
                "recommended_aic_metrics": ["PipeUtilization"],
                "required_artifacts": ["trace.json or core*_code_exe.csv/core*_instr_exe.csv"],
                "confidence": "low",
            }
        )
    return out[:2]


def build_evidence_readiness(run_dir: Path, summary: dict, raw_artifact_index: dict) -> dict:
    families = available_evidence_families(summary, raw_artifact_index)
    target_status = str((summary.get("target_identity") or {}).get("status") or "unknown")
    has_context = workload_context_available(run_dir)
    level = readiness_level(families, target_status, has_context)
    missing_families = missing_evidence_families(families, has_context)
    allowed, blocked = claim_lists(level, families)
    stages = [readiness_stage_for_app(summary)]
    for segment, scope in known_scope_segments(summary, raw_artifact_index):
        stages.append(readiness_stage_for_scope(raw_artifact_index, segment, scope))
    unparsed = [
        {
            "artifact": item.get("artifact"),
            "segment": item.get("segment"),
            "known_role": item.get("known_role"),
            "diagnosis_role": item.get("diagnosis_role"),
        }
        for item in raw_artifact_index.get("artifacts", [])
        if isinstance(item, dict) and item.get("group") == "unparsed_profiler_binary"
    ]
    return {
        "schema_version": "1.0",
        "level": level,
        "reasons": readiness_reasons(families, target_status, has_context),
        "available_evidence_families": families,
        "missing_evidence_families": missing_families,
        "allowed_claims": allowed,
        "blocked_claims": blocked,
        "recommended_followups": readiness_followups(summary, missing_families),
        "segments": stages,
        "unparsed_binary_artifacts": unparsed,
    }


def write_text_summary(out_path: Path, summary: dict) -> None:
    lines = ["# Ascend msprof Key Metrics", ""]
    for group, item in summary["headlines"].items():
        if item is None:
            lines.append(f"- {group}: missing")
            continue
        value = item.get("value")
        value_text = "n/a" if value is None else f"{value:g}"
        name = item.get("name") or "n/a"
        field = item.get("field")
        field_text = f" {field}" if field else ""
        lines.append(f"- {group}: {name}{field_text} = {value_text} ({item.get('file')})")
    lines.append("")
    lines.append("## Files")
    for group, records in summary["files"].items():
        lines.append(f"- {group}: {len(records)} file(s)")
        for rec in records:
            lines.append(f"  - {rel(Path(rec['path']), summary['run_dir_path'])}: {rec['row_count']} row(s)")
    occupancy = summary.get("stdout_sections", {}).get("occupancy_summary")
    if occupancy:
        lines.append("")
        lines.append("## Occupancy Summary")
        lines.append("")
        lines.append("| Ordinal | Message | Source |")
        lines.append("|---:|---|---|")
        source = occupancy.get("source", "missing")
        for message in occupancy.get("messages", []):
            lines.append(
                f"| {md_table_cell(message.get('ordinal'))} | "
                f"{md_table_cell(message.get('message'))} | "
                f"{md_table_cell(source)} |"
            )
    roofline = summary.get("stdout_sections", {}).get("roofline_summary")
    if roofline:
        lines.append("")
        lines.append("## RoofLine Summary")
        lines.append("")
        lines.append("| Message | Source |")
        lines.append("|---|---|")
        source = roofline.get("source", "missing")
        for message in roofline.get("messages", []):
            lines.append(
                f"| {md_table_cell(message.get('message'))} | "
                f"{md_table_cell(source)} |"
            )
    performance = summary.get("stdout_sections", {}).get("performance_summary")
    if performance:
        lines.append("")
        lines.append("## CANN Performance Summary")
        lines.append("")
        lines.append("| Ordinal | Message | Source |")
        lines.append("|---:|---|---|")
        source = performance.get("source", "missing")
        for message in performance.get("messages", []):
            lines.append(
                f"| {md_table_cell(message.get('ordinal'))} | "
                f"{md_table_cell(message.get('message'))} | "
                f"{md_table_cell(message.get('source') or source)} |"
            )
    dimensions = summary.get("analysis_dimensions") or []
    if dimensions:
        lines.append("")
        lines.append("## Analysis Dimensions")
        for dimension in dimensions:
            status = dimension.get("status", "insufficient")
            lines.append(f"- {dimension.get('title')}: {status}")
            for signal in dimension.get("signals", [])[:5]:
                value = signal.get("value")
                value_text = "n/a" if value is None else f"{float(value):g}" if isinstance(value, (int, float)) else str(value)
                lines.append(
                    f"  - {signal.get('signal')} = {value_text} "
                    f"({signal.get('artifact')}; {signal.get('field_ref')})"
                )
    directions = summary.get("optimization_directions") or []
    if directions:
        lines.append("")
        lines.append("## Optimization Directions")
        for item in directions:
            lines.append(
                f"- {item.get('rank')}. {item.get('id')}: "
                f"{item.get('title')}: {item.get('impact_basis')}"
            )
    next_actions = summary.get("next_collection_actions") or []
    if next_actions:
        lines.append("")
        lines.append("## Next Collection Actions")
        for item in next_actions:
            metrics = ", ".join(item.get("recommended_aic_metrics") or [])
            artifacts = ", ".join(item.get("required_artifacts") or [])
            lines.append(f"- {item.get('id')}: collect {metrics}; required artifacts: {artifacts}")
    readiness = summary.get("evidence_readiness")
    if isinstance(readiness, dict):
        lines.append("")
        lines.append("## Evidence Readiness")
        lines.append(f"- level: {readiness.get('level', 'insufficient')}")
        available = ", ".join(readiness.get("available_evidence_families") or []) or "none"
        missing = ", ".join(readiness.get("missing_evidence_families") or []) or "none"
        lines.append(f"- available evidence families: {available}")
        lines.append(f"- missing evidence families: {missing}")
        followups = readiness.get("recommended_followups") or []
        if followups:
            lines.append(f"- next minimal action: {followups[0].get('id')}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    args = ap.parse_args(argv)

    run_dir = args.run_dir.resolve()
    out_dir = analysis_dir(run_dir)
    summary = {
        "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
        "run_dir": str(run_dir),
        "run_dir_path": run_dir,
        "files": {},
        "headlines": {},
        "stdout_sections": {
            "occupancy_summary": parse_occupancy_summary_stdout(run_dir),
            "roofline_summary": parse_roofline_summary_stdout(run_dir),
            "performance_summary": parse_performance_summary_stdout(run_dir),
        },
        "warnings": [],
    }
    metric_scope = selected_metric_scope(run_dir)
    if metric_scope:
        summary["metric_scope"] = metric_scope
    for group, patterns in FILE_GROUPS.items():
        records = collect_group(run_dir, group, patterns, metric_scope)
        summary["files"][group] = records
        summary["headlines"][group] = headline_for_group(run_dir, group, patterns, metric_scope)
        if not records:
            summary["warnings"].append(f"missing {group}: {patterns}")
    summary["target_identity"] = build_target_identity(run_dir, summary)
    summary["warnings"].extend(target_identity_warnings(summary["target_identity"]))
    simulator_model = write_simulator_hotspot_model(run_dir)
    summary["_simulator_hotspot_model"] = simulator_model
    for warning in simulator_model.get("warnings", []):
        if str(warning).startswith("invalid simulator"):
            summary["warnings"].append(str(warning))
    summary["analysis_dimensions"] = build_analysis_dimensions(run_dir, summary)
    summary["next_collection_actions"] = build_next_collection_actions(summary)
    summary["optimization_directions"] = build_optimization_directions(summary)
    raw_artifact_index = build_raw_artifact_index(run_dir, summary, metric_scope)
    summary["evidence_readiness"] = build_evidence_readiness(run_dir, summary, raw_artifact_index)

    json_summary = dict(summary)
    json_summary.pop("run_dir_path")
    json_summary.pop("_simulator_hotspot_model", None)
    write_json(out_dir / "summary.json", json_summary)
    write_json(out_dir / "raw_artifact_index.json", raw_artifact_index)
    write_text_summary(out_dir / "key_metrics.txt", summary)
    print(f"wrote {out_dir / 'summary.json'}")
    print(f"wrote {out_dir / 'raw_artifact_index.json'}")
    print(f"wrote {out_dir / 'key_metrics.txt'}")


if __name__ == "__main__":
    main()
