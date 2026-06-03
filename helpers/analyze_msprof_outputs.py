#!/usr/bin/env python3
"""Extract key summaries from Ascend msprof / msprof op output."""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from ascend_profile_utils import (
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
from metric_scope_policy import (
    command_metric_scope,
    is_msprof_op_command,
    metric_scope_policy,
    missing_artifact_labels,
    normalize_metric_scope,
    warning_group,
)


ANALYSIS_SCHEMA_VERSION = "1.1"
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
TIMING_GROUPS = ["op_summary", "task_time", "op_statistic", "api_statistic", "op_basic_info"]
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


def load_orchestrator(run_dir: Path) -> dict | None:
    path = run_dir / "analysis" / "tilelang_benchmark_profile_run.json"
    if not path.exists():
        return None
    try:
        data = read_json(path)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def selected_metric_scope(run_dir: Path) -> dict | None:
    orchestrator = load_orchestrator(run_dir)
    if orchestrator:
        profiles = orchestrator.get("profiles", {})
        if isinstance(profiles, dict) and profiles.get("op_pipe") is False:
            return None
        commands = orchestrator.get("commands", {})
        scope = command_metric_scope(commands.get("msprof_op") if isinstance(commands, dict) else None)
        if scope:
            normalized = normalize_metric_scope(scope)
            policy = metric_scope_policy(normalized)
            out = {
                "value": normalized,
                "artifact": "analysis/tilelang_benchmark_profile_run.json",
                "field_ref": "commands.msprof_op --aic-metrics",
                "known": policy is not None,
            }
            if policy:
                out["policy"] = policy.as_dict()
            return out
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


def collect_group(run_dir: Path, group: str, patterns: list[str]) -> list[dict]:
    records = []
    for path in find_files(run_dir, patterns):
        rec = summarize_csv(path)
        rec["group"] = group
        records.append(rec)
    return records


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


def headline_for_group(run_dir: Path, group: str, patterns: list[str]) -> dict | None:
    files = find_files(run_dir, patterns)
    if not files:
        return None
    if group == "memory":
        return memory_headline(run_dir, files)
    if group == "l2_cache":
        return l2_cache_headline(run_dir, files)
    path = files[0]
    rows = read_csv_rows(path)
    if group in {"op_summary", "op_statistic", "task_time", "api_statistic"}:
        row, value = top_numeric_row(rows, DURATION_ALIASES)
        return {
            "file": rel(path, run_dir),
            "name": first_present(row or {}, NAME_ALIASES),
            "value": value,
            "field_kind": "duration_or_time",
            "raw_row": row,
        }
    if group in {"pipe_utilization", "arithmetic_utilization", "resource_conflict"}:
        row, field, value = top_field_cell(rows, UTIL_ALIASES, UTIL_EXCLUDE_ALIASES)
        return {
            "file": rel(path, run_dir),
            "name": first_present(row or {}, NAME_ALIASES + ["pipe", "resource", "metric"]),
            "value": value,
            "field": field,
            "field_kind": "utilization_or_ratio",
            "raw_row": row,
        }
    if group == "op_basic_info":
        first_row = rows[0] if rows else {}
        field, value = op_basic_field(first_row)
        tiling_field, tiling_value = op_basic_tiling_field(first_row)
        return {
            "file": rel(path, run_dir),
            "row_count": len(rows),
            "name": first_present(first_row, NAME_ALIASES),
            "value": value,
            "field": field,
            "tiling_field": tiling_field,
            "tiling_value": tiling_value,
            "field_kind": "basic_info",
            "first_row": first_row,
        }
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
            }
    return simulator_fallback_signal(path, run_dir)


def simulator_signal(path: Path, run_dir: Path, warnings: list[str]) -> dict:
    if path.suffix.lower() == ".json":
        return simulator_trace_signal(path, run_dir, warnings)
    if path.suffix.lower() == ".csv":
        return simulator_csv_signal(path, run_dir, warnings)
    return simulator_fallback_signal(path, run_dir)


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

    parsed_simulator_signals = []
    fallback_simulator_signals = []
    for path in find_files(run_dir, SIMULATOR_PATTERNS):
        signal = simulator_signal(path, run_dir, summary.setdefault("warnings", []))
        if signal.get("value") is None:
            fallback_simulator_signals.append(signal)
        else:
            parsed_simulator_signals.append(signal)
    simulator_signals = parsed_simulator_signals + fallback_simulator_signals
    dimensions.append(
        {
            "id": "source_pipeline_context",
            "title": "Source And Pipeline Context",
            "status": "available" if simulator_signals else "insufficient",
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
            }
        )
    return signals


def performance_summary_signals(summary: dict) -> list[dict]:
    section = summary.get("stdout_sections", {}).get("performance_summary")
    if not isinstance(section, dict):
        return []
    signals = []
    source = section.get("source", "missing")
    for index, message in enumerate(section.get("messages", [])):
        if not isinstance(message, dict):
            continue
        ordinal = message.get("ordinal")
        if ordinal is not None:
            message_ref = f"stdout_sections.performance_summary.messages[ordinal={ordinal}].message"
        else:
            message_ref = f"stdout_sections.performance_summary.messages[{index}].message"
        signals.append(
            {
                "group": "performance_summary",
                "signal": f"Performance Summary {ordinal}" if ordinal is not None else "Performance Summary",
                "artifact": message.get("source") or source,
                "field": "message",
                "field_ref": (
                    "stdout_sections.performance_summary.messages[].message; "
                    f"{message_ref}"
                ),
                "value": message.get("message"),
                "kind": "stdout_message",
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


def build_optimization_directions(summary: dict) -> list[dict]:
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
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    args = ap.parse_args()

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
        records = collect_group(run_dir, group, patterns)
        summary["files"][group] = records
        summary["headlines"][group] = headline_for_group(run_dir, group, patterns)
        if not records:
            summary["warnings"].append(f"missing {group}: {patterns}")
    summary["analysis_dimensions"] = build_analysis_dimensions(run_dir, summary)
    summary["optimization_directions"] = build_optimization_directions(summary)
    summary["next_collection_actions"] = build_next_collection_actions(summary)

    json_summary = dict(summary)
    json_summary.pop("run_dir_path")
    write_json(out_dir / "summary.json", json_summary)
    write_text_summary(out_dir / "key_metrics.txt", summary)
    print(f"wrote {out_dir / 'summary.json'}")
    print(f"wrote {out_dir / 'key_metrics.txt'}")


if __name__ == "__main__":
    main()
