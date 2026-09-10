"""Headline and signal derivation for Evidence Model analysis."""
from __future__ import annotations

import csv
from pathlib import Path

from ._evidence_artifacts import (
    annotate_source_metadata,
    metric_scope_for_segment,
    performance_summary_segment,
    recognized_group_files,
)
from ._profiler_segments import segment_receipt_allows_evidence
from .ascend_profile_utils import (
    find_files,
    first_present,
    normalized_key,
    read_csv_rows,
    read_json,
    rel,
    to_float,
    top_numeric_row,
)
from .metric_scope_policy import APP_TIMING_ARTIFACTS


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
TIMING_GROUPS = ["op_summary", "task_time", "op_statistic", "api_statistic", "op_basic_info"]
OP_METRIC_GROUPS = ["pipe_utilization", "arithmetic_utilization", "memory", "l2_cache", "resource_conflict"]
READINESS_LEVEL_ORDER = {
    "insufficient": 0,
    "triage_only": 1,
    "directional": 2,
    "actionable_experiment": 3,
}
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

# Exact field vocabulary from the documented, fixture-covered op layouts.
# This only gates comparison; selection still retains unknown raw values.
COMPARABLE_OP_FIELDS = {
    **{group: set(fields) for group, fields in RAW_VALUE_FIELD_CANDIDATES.items()},
    "pipe_utilization": {
        *(f"aic_{pipe}_ratio" for pipe in ("cube", "scalar", "mte1", "mte2", "mte3", "fixpipe")),
        *(f"aiv_{pipe}_ratio" for pipe in ("vec", "scalar", "mte2", "mte3")),
        "Utilization(%)",  # legacy synthetic fixture
    },
    "arithmetic_utilization": {
        "aic_cube_ratio", "aic_cube_fp16_ratio", "aic_cube_int8_ratio",
        *(f"aiv_vec{suffix}_ratio" for suffix in ("", "_fp32", "_fp16", "_int32", "_int16", "_misc")),
        "Utilization(%)",
    },
    "resource_conflict": {
        *(f"{core}_{pipe}_wait_ratio" for core, pipes in (("aic", ("cube", "mte1", "mte2", "mte3")), ("aiv", ("vec", "mte1", "mte2", "mte3"))) for pipe in pipes),
        *(f"aiv_vec_{kind}_cflt_ratio" for kind in ("total", "bankgroup", "bank", "resc", "mte")),
        "Ratio(%)",
    },
    "l2_cache": set(L2_CACHE_TOTAL_HIT_RATE_FIELDS),
    "memory": {
        *(f"{route}_{suffix}" for route in ("GM_to_L1", "L0C_to_L1", "L0C_to_GM", "GM_to_UB", "UB_to_GM") for suffix in ("datas(KB)", "bw_usage_rate(%)")),
        "L1_to_GM_datas(KB)(estimate)", "L1_to_GM_bw_usage_rate(%)(estimate)",
        "read_main_memory_datas(KB)", "write_main_memory_datas(KB)",
        *(f"{core}_{memory}_{direction}_bw(GB/s)" for core, memories in (("aic", ("l1", "main_mem", "l0a", "l0b")), ("aiv", ("main_mem",))) for memory in memories for direction in ("read", "write")),
        "aiv_ub_to_gm_bw(GB/s)", "aiv_gm_to_ub_bw(GB/s)",
        *(f"aic_l0c_{direction}_bw_cube(GB/s)" for direction in ("read", "write")),
        *(f"aiv_ub_{direction}_bw_{pipe}(GB/s)" for direction in ("read", "write") for pipe in ("vector", "scalar")),
        "Usage Rate(%)", "GM Read Bandwidth(GB/s)",
    },
}


def headline_schema_issues(group: str, item: dict) -> list[dict]:
    row = item.get("first_row" if group == "op_basic_info" else "raw_row") or {}
    issues = [
        {"reason": "unsupported unit layout", "source": {"artifact": item.get("file"), "field": str(field)}}
        for field in row if str(field).strip().lower() in {"unit", "units"}
    ]
    field = item.get("field")
    if field and group in COMPARABLE_OP_FIELDS and field not in COMPARABLE_OP_FIELDS[group]:
        issues.append({"reason": "unsupported metric field", "source": {"artifact": item.get("file"), "field": field}})
    return issues


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


def headline_for_group(
    run_dir: Path,
    group: str,
    patterns: list[str],
    selected_scope: dict | None,
    prefer_primary_op: bool = False,
    preferred_segment: str | None = None,
) -> dict | None:
    files = [
        path
        for path in recognized_group_files(run_dir, group, patterns)
        if segment_receipt_allows_evidence(
            run_dir,
            annotate_source_metadata(
                {},
                rel(path, run_dir),
                group,
                selected_scope,
            )["segment"],
        )
    ]
    if not files:
        return None
    readable_files = []
    for path in files:
        try:
            read_csv_rows(path)
        except (OSError, UnicodeError, csv.Error):
            continue
        readable_files.append(path)
    files = readable_files
    if not files:
        return None
    if preferred_segment is not None:
        preferred_files = [
            path
            for path in files
            if annotate_source_metadata({}, rel(path, run_dir), group, selected_scope)["segment"]
            == preferred_segment
        ]
        if preferred_files:
            files = preferred_files
    if prefer_primary_op and (group in OP_METRIC_GROUPS or group == "op_basic_info"):
        files.sort(
            key=lambda path: (
                0 if annotate_source_metadata({}, rel(path, run_dir), group, selected_scope)["segment"] == "op" else 1,
                rel(path, run_dir),
            )
        )
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


def first_app_timing_signal(dimensions: list[dict]) -> dict | None:
    return first_signal_with_value(dimensions, list(APP_TIMING_ARTIFACTS))


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
        segment = performance_summary_segment(message_source)
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
