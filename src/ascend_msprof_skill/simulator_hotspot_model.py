"""Build a structured, raw simulator hotspot model from Ascend artifacts."""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .ascend_profile_utils import find_files, first_present, read_json, rel, to_float, write_json


SIMULATOR_HOTSPOT_MODEL_SCHEMA_VERSION = "1.0"
SIMULATOR_PATTERNS = ["core*_code_exe.csv", "core*_instr_exe.csv", "trace.json"]
CODE_PATTERNS = ["core*_code_exe.csv"]
INSTR_PATTERNS = ["core*_instr_exe.csv"]
TRACE_PATTERNS = ["trace.json"]

VALUE_ALIASES = ["running_time(us)", "running_time", "running time(us)", "time", "duration", "cycles", "cycle", "cost", "call_count", "call count", "calls"]
LINE_ALIASES = ["line", "line no", "lineno", "source line"]
FILE_ALIASES = ["file", "source", "filename", "path"]
CODE_ALIASES = ["code", "source code", "source_line"]
INSTR_ALIASES = ["instruction", "instr", "opcode", "asm"]
PIPE_ALIASES = ["pipe", "pipeline"]
CALL_COUNT_ALIASES = ["call_count", "call count", "calls"]
CYCLES_ALIASES = ["cycles", "cycle"]
RUNNING_TIME_ALIASES = ["running_time(us)", "running time(us)", "running_time", "running time"]
SYNC_EVENT_INSTRUCTIONS = ["SET_FLAG", "WAIT_FLAG"]
SYNC_EVENT_PHASES = {"B", "E"}
MTE_THROUGHPUT_CHANNELS = [
    "GM_TO_L1",
    "GM_TO_TOTAL",
    "GM_TO_UB",
    "L1_TO_GM",
    "TOTAL_TO_GM",
    "UB_TO_GM",
]
MTE_THROUGHPUT_FIELD = "throughput(MB/s)"


def collect_trace_events(obj: Any) -> list:
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        events = obj.get("traceEvents")
        if isinstance(events, list):
            return events
    return []


def is_aggregate_trace_artifact(artifact: str) -> bool:
    return Path(artifact).parent.name == "simulator"


def select_trace_objects(trace_objects: list[tuple[str, Any, list]]) -> list[tuple[str, Any, list]]:
    aggregate = [item for item in trace_objects if is_aggregate_trace_artifact(item[0])]
    return aggregate or trace_objects


def raw_field_for_alias(row: dict[str, Any], aliases: list[str]) -> str | None:
    lowered = {str(key).strip().lower(): str(key) for key in row}
    for alias in aliases:
        field = lowered.get(alias.strip().lower())
        if field:
            return field
    normalized = {
        "".join(ch for ch in str(key).strip().lower() if ch.isalnum()): str(key)
        for key in row
    }
    for alias in aliases:
        normalized_alias = "".join(ch for ch in alias.strip().lower() if ch.isalnum())
        field = normalized.get(normalized_alias)
        if field:
            return field
    for alias in aliases:
        normalized_alias = "".join(ch for ch in alias.strip().lower() if ch.isalnum())
        for key, field in normalized.items():
            if normalized_alias and normalized_alias in key:
                return field
    return None


def numeric_alias_value(row: dict[str, Any], aliases: list[str]) -> tuple[str | None, float | None]:
    field = raw_field_for_alias(row, aliases)
    if not field:
        return None, None
    return field, to_float(row.get(field))


def preferred_numeric_value(row: dict[str, Any]) -> tuple[str | None, float | None]:
    for aliases in [RUNNING_TIME_ALIASES, CYCLES_ALIASES, CALL_COUNT_ALIASES, VALUE_ALIASES]:
        field, value = numeric_alias_value(row, aliases)
        if field and value is not None:
            return field, value
    return None, None


def split_source_location(value: Any) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    text = str(value).strip()
    if not text:
        return None, None
    source, sep, line = text.rpartition(":")
    if sep and source and line.isdigit():
        return source, line
    return None, None


def safe_csv_rows(path: Path, run_dir: Path) -> tuple[list[dict[str, str]], list[str], str, list[str]]:
    warnings: list[str] = []
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            columns = list(reader.fieldnames or (list(rows[0].keys()) if rows else []))
    except (OSError, UnicodeError, csv.Error) as exc:
        warnings.append(f"invalid simulator csv {rel(path, run_dir)}: {exc}")
        return [], [], "invalid", warnings
    status = "parsed" if rows else "empty"
    return rows, columns, status, warnings


def safe_trace_events(path: Path, run_dir: Path) -> tuple[Any, list, str, list[str]]:
    warnings: list[str] = []
    try:
        obj = read_json(path)
    except (OSError, ValueError) as exc:
        warnings.append(f"invalid simulator trace {rel(path, run_dir)}: {exc}")
        return None, [], "invalid", warnings
    events = collect_trace_events(obj)
    return obj, events, "parsed" if events else "empty", warnings


def csv_input_record(path: Path, run_dir: Path, kind: str) -> tuple[dict[str, Any], list[dict[str, str]], list[str]]:
    rows, columns, status, warnings = safe_csv_rows(path, run_dir)
    return (
        {
            "artifact": rel(path, run_dir),
            "kind": kind,
            "parser_status": status,
            "row_count": len(rows),
            "columns": columns,
            "warnings": warnings,
        },
        rows,
        warnings,
    )


def trace_input_record(path: Path, run_dir: Path) -> tuple[dict[str, Any], Any, list, list[str]]:
    obj, events, status, warnings = safe_trace_events(path, run_dir)
    record: dict[str, Any] = {
        "artifact": rel(path, run_dir),
        "kind": "trace_json",
        "parser_status": status,
        "event_count": len(events),
        "warnings": warnings,
    }
    if isinstance(obj, dict) and obj.get("displayTimeUnit"):
        record["display_time_unit"] = str(obj.get("displayTimeUnit"))
    return record, obj, events, warnings


def make_evidence_id(prefix: str, index: int) -> str:
    return f"{prefix}.{index:04d}"


def build_source_lines(code_rows_by_artifact: list[tuple[str, list[dict[str, str]]]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str | None, str | None, str | None], dict[str, Any]] = {}
    for artifact, csv_rows in code_rows_by_artifact:
        for row in csv_rows:
            field, value = preferred_numeric_value(row)
            if field is None or value is None:
                continue
            line = first_present(row, LINE_ALIASES)
            source_file = first_present(row, FILE_ALIASES)
            code = first_present(row, CODE_ALIASES)
            if (not source_file or not line) and code:
                parsed_source_file, parsed_line = split_source_location(code)
                source_file = source_file or parsed_source_file
                line = line or parsed_line
            key_label = str(source_file or artifact)
            key = (key_label, str(line) if line is not None else None, str(code) if code is not None else None, field)
            entry = grouped.setdefault(
                key,
                {
                    "artifact": artifact,
                    "artifacts": set(),
                    "field": field,
                    "field_refs": set(),
                    "value": 0.0,
                    "source_file": source_file,
                    "line": line,
                    "code": code,
                    "call_count": 0.0,
                    "cycles": 0.0,
                    "running_time(us)": 0.0,
                    "row_count": 0,
                },
            )
            entry["artifacts"].add(artifact)
            entry["field_refs"].add(f"{artifact}:{field}")
            entry["value"] += value
            entry["row_count"] += 1
            for out_field, aliases in [
                ("call_count", CALL_COUNT_ALIASES),
                ("cycles", CYCLES_ALIASES),
                ("running_time(us)", RUNNING_TIME_ALIASES),
            ]:
                numeric_value = to_float(first_present(row, aliases))
                if numeric_value is not None:
                    entry[out_field] += numeric_value
    rows = []
    for entry in grouped.values():
        artifacts = sorted(entry.pop("artifacts"))
        field_refs = sorted(entry.pop("field_refs"))
        entry["artifact"] = "; ".join(artifacts)
        entry["field_ref"] = "; ".join(field_refs)
        rows.append(entry)
    rows.sort(key=lambda item: (item["value"], str(item.get("artifact")), str(item.get("code"))), reverse=True)
    for index, entry in enumerate(rows, start=1):
        entry["rank"] = index
        entry["evidence_id"] = make_evidence_id("sim.src", index)
    return rows


def build_instruction_rows(instr_rows_by_artifact: list[tuple[str, list[dict[str, str]]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for artifact, csv_rows in instr_rows_by_artifact:
        for row in csv_rows:
            field, value = preferred_numeric_value(row)
            if field is None or value is None:
                continue
            instr = first_present(row, INSTR_ALIASES, "<unknown>")
            entry = {
                "artifact": artifact,
                "field": field,
                "field_ref": f"{artifact}:{field}",
                "value": value,
                "instr": instr,
                "pipe": first_present(row, PIPE_ALIASES),
                "call_count": to_float(first_present(row, CALL_COUNT_ALIASES)),
                "cycles": to_float(first_present(row, CYCLES_ALIASES)),
                "running_time(us)": to_float(first_present(row, RUNNING_TIME_ALIASES)),
            }
            rows.append(entry)
    rows.sort(key=lambda item: (item["value"], str(item.get("artifact")), str(item.get("instr"))), reverse=True)
    for index, entry in enumerate(rows, start=1):
        entry["rank"] = index
        entry["evidence_id"] = make_evidence_id("sim.instr", index)
    return rows


def build_pipeline_events(trace_objects: list[tuple[str, Any, list]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    for artifact, obj, events in trace_objects:
        display_time_unit = str(obj.get("displayTimeUnit")) if isinstance(obj, dict) and obj.get("displayTimeUnit") else None
        for event in events:
            if not isinstance(event, dict) or event.get("ph") != "X":
                continue
            duration = to_float(event.get("dur"))
            tid = event.get("tid") or event.get("name")
            if duration is None or tid is None:
                continue
            key = (artifact, str(tid), display_time_unit)
            entry = grouped.setdefault(
                key,
                {
                    "artifact": artifact,
                    "field": "traceEvents[].dur",
                    "field_ref": f"{artifact}:traceEvents[].dur",
                    "tid": str(tid),
                    "display_time_unit": display_time_unit,
                    "duration": 0.0,
                    "event_count": 0,
                    "max_duration": None,
                    "max_event_name": None,
                },
            )
            entry["duration"] += duration
            entry["event_count"] += 1
            if entry["max_duration"] is None or duration > entry["max_duration"]:
                entry["max_duration"] = duration
                entry["max_event_name"] = event.get("name")
    rows = sorted(
        grouped.values(),
        key=lambda item: (item["duration"], item["event_count"], str(item["tid"])),
        reverse=True,
    )
    for index, entry in enumerate(rows, start=1):
        entry["rank"] = index
        entry["evidence_id"] = make_evidence_id("sim.pipe", index)
        entry["value"] = entry["duration"]
    return rows


def build_flow_categories(trace_objects: list[tuple[str, Any, list]]) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str]] = Counter()
    for artifact, _obj, events in trace_objects:
        for event in events:
            if not isinstance(event, dict):
                continue
            if event.get("name") == "flow" and event.get("cat"):
                counts[(artifact, str(event.get("cat")))] += 1
    rows = [
        {
            "artifact": artifact,
            "field": "traceEvents[].cat",
            "field_ref": f"{artifact}:traceEvents[].cat",
            "category": category,
            "count": count,
            "value": count,
        }
        for (artifact, category), count in counts.items()
    ]
    rows.sort(key=lambda item: (item["count"], item["category"]), reverse=True)
    for index, entry in enumerate(rows, start=1):
        entry["rank"] = index
        entry["evidence_id"] = make_evidence_id("sim.flow", index)
    return rows


def empty_sync_event_row() -> dict[str, Any]:
    return {
        "trace_events": 0,
        "csv_rows": 0,
        "csv_call_count": 0.0,
        "csv_cycles": 0.0,
        "csv_running_time(us)": 0.0,
        "sources": set(),
    }


def build_sync_events(
    trace_objects: list[tuple[str, Any, list]],
    instr_rows_by_artifact: list[tuple[str, list[dict[str, str]]]],
) -> list[dict[str, Any]]:
    rows = {instruction: empty_sync_event_row() for instruction in SYNC_EVENT_INSTRUCTIONS}
    for artifact, _obj, events in trace_objects:
        for event in events:
            if not isinstance(event, dict):
                continue
            name = event.get("name")
            if name not in rows or event.get("ph") not in SYNC_EVENT_PHASES:
                continue
            rows[str(name)]["trace_events"] += 1
            rows[str(name)]["sources"].add(artifact)

    for artifact, csv_rows in instr_rows_by_artifact:
        for row in csv_rows:
            instr = first_present(row, INSTR_ALIASES)
            if instr not in rows:
                continue
            out = rows[str(instr)]
            out["csv_rows"] += 1
            out["sources"].add(artifact)
            value = to_float(first_present(row, CALL_COUNT_ALIASES))
            if value is not None:
                out["csv_call_count"] += value
            value = to_float(first_present(row, CYCLES_ALIASES))
            if value is not None:
                out["csv_cycles"] += value
            value = to_float(first_present(row, RUNNING_TIME_ALIASES))
            if value is not None:
                out["csv_running_time(us)"] += value

    observed = []
    for instruction in SYNC_EVENT_INSTRUCTIONS:
        row = rows[instruction]
        if row["trace_events"] or row["csv_rows"]:
            observed.append(
                {
                    "evidence_id": make_evidence_id("sim.sync", len(observed) + 1),
                    "instruction": instruction,
                    "trace_events": row["trace_events"],
                    "csv_rows": row["csv_rows"],
                    "csv_call_count": row["csv_call_count"],
                    "csv_cycles": row["csv_cycles"],
                    "csv_running_time(us)": row["csv_running_time(us)"],
                    "sources": sorted(row["sources"]),
                    "field": "traceEvents[].name; instr",
                    "field_ref": "traceEvents[].name=SET_FLAG/WAIT_FLAG; core*_instr_exe.csv:instr",
                    "value": row["trace_events"] + row["csv_rows"],
                }
            )
    return observed


def build_mte_throughput(trace_objects: list[tuple[str, Any, list]]) -> list[dict[str, Any]]:
    rows = []
    for artifact, _obj, events in trace_objects:
        values: dict[str, list[float]] = defaultdict(list)
        for event in events:
            if not isinstance(event, dict):
                continue
            if event.get("pid") != "MTE Throughput" or event.get("ph") != "C":
                continue
            channel = event.get("name")
            if channel not in MTE_THROUGHPUT_CHANNELS:
                continue
            args = event.get("args")
            if not isinstance(args, dict):
                continue
            value = to_float(args.get(MTE_THROUGHPUT_FIELD))
            if value is None:
                continue
            values[str(channel)].append(value)
        for channel in MTE_THROUGHPUT_CHANNELS:
            samples = values[channel]
            if samples:
                rows.append(
                    {
                        "artifact": artifact,
                        "field": MTE_THROUGHPUT_FIELD,
                        "field_ref": f"{artifact}:traceEvents[].args.{MTE_THROUGHPUT_FIELD}",
                        "channel": channel,
                        "max": max(samples),
                        "avg": sum(samples) / len(samples),
                        "samples": len(samples),
                        "value": max(samples),
                    }
                )
    rows.sort(key=lambda item: (item["max"], item["avg"], item["samples"], item["channel"]), reverse=True)
    for index, entry in enumerate(rows, start=1):
        entry["rank"] = index
        entry["evidence_id"] = make_evidence_id("sim.mte", index)
    return rows


def build_simulator_hotspot_model(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    code_files = find_files(run_dir, CODE_PATTERNS)
    instr_files = find_files(run_dir, INSTR_PATTERNS)
    trace_files = find_files(run_dir, TRACE_PATTERNS)
    inputs: list[dict[str, Any]] = []
    warnings: list[str] = []
    code_rows_by_artifact: list[tuple[str, list[dict[str, str]]]] = []
    instr_rows_by_artifact: list[tuple[str, list[dict[str, str]]]] = []
    trace_objects: list[tuple[str, Any, list]] = []

    for path in code_files:
        record, rows, record_warnings = csv_input_record(path, run_dir, "code_execution_csv")
        inputs.append(record)
        warnings.extend(record_warnings)
        if record["parser_status"] == "parsed":
            code_rows_by_artifact.append((record["artifact"], rows))

    for path in instr_files:
        record, rows, record_warnings = csv_input_record(path, run_dir, "instruction_execution_csv")
        inputs.append(record)
        warnings.extend(record_warnings)
        if record["parser_status"] == "parsed":
            instr_rows_by_artifact.append((record["artifact"], rows))

    for path in trace_files:
        record, obj, events, record_warnings = trace_input_record(path, run_dir)
        inputs.append(record)
        warnings.extend(record_warnings)
        if record["parser_status"] == "parsed":
            trace_objects.append((record["artifact"], obj, events))
    selected_trace_objects = select_trace_objects(trace_objects)

    if not code_files:
        warnings.append("No core*_code_exe.csv files found.")
    if not instr_files:
        warnings.append("No core*_instr_exe.csv files found.")
    if not trace_files:
        warnings.append("No trace.json files found.")

    return {
        "simulator_hotspot_model_schema_version": SIMULATOR_HOTSPOT_MODEL_SCHEMA_VERSION,
        "inputs": inputs,
        "source_lines": build_source_lines(code_rows_by_artifact),
        "instructions": build_instruction_rows(instr_rows_by_artifact),
        "pipeline_events": build_pipeline_events(selected_trace_objects),
        "flow_categories": build_flow_categories(selected_trace_objects),
        "sync_events": build_sync_events(selected_trace_objects, instr_rows_by_artifact),
        "mte_throughput": build_mte_throughput(selected_trace_objects),
        "warnings": warnings,
    }


def write_simulator_hotspot_model(run_dir: Path) -> dict[str, Any]:
    model = build_simulator_hotspot_model(run_dir)
    out_dir = run_dir / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "simulator_hotspots.json", model)
    return model
