#!/usr/bin/env python3
"""Aggregate Ascend simulator source-line and instruction hotspots."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

from ascend_profile_utils import analysis_dir, find_files, first_present, read_csv_rows, read_json, rel, to_float

VALUE_ALIASES = ["time", "duration", "cycles", "cycle", "cost"]
LINE_ALIASES = ["line", "line no", "lineno", "source line"]
FILE_ALIASES = ["file", "source", "filename", "path"]
INSTR_ALIASES = ["instruction", "instr", "opcode", "asm"]
SYNC_EVENT_INSTRUCTIONS = ["SET_FLAG", "WAIT_FLAG"]
SYNC_EVENT_PHASES = {"B", "E"}
SYNC_CALL_COUNT_ALIASES = ["call_count", "call count", "calls"]
SYNC_CYCLES_ALIASES = ["cycles", "cycle"]
SYNC_RUNNING_TIME_ALIASES = ["running_time(us)", "running time(us)", "running_time", "running time"]
MTE_THROUGHPUT_CHANNELS = [
    "GM_TO_L1",
    "GM_TO_TOTAL",
    "GM_TO_UB",
    "L1_TO_GM",
    "TOTAL_TO_GM",
    "UB_TO_GM",
]
MTE_THROUGHPUT_FIELD = "throughput(MB/s)"


def aggregate_code(paths: list[Path]):
    out = defaultdict(float)
    for path in paths:
        for row in read_csv_rows(path):
            value = to_float(first_present(row, VALUE_ALIASES))
            if value is None:
                continue
            file_ = first_present(row, FILE_ALIASES, path.name)
            line = first_present(row, LINE_ALIASES, "?")
            out[(str(file_), str(line))] += value
    return sorted(((v, f, ln) for (f, ln), v in out.items()), reverse=True)


def aggregate_instr(paths: list[Path]):
    out = defaultdict(float)
    for path in paths:
        for row in read_csv_rows(path):
            value = to_float(first_present(row, VALUE_ALIASES))
            if value is None:
                continue
            instr = first_present(row, INSTR_ALIASES, "<unknown>")
            out[str(instr)] += value
    return sorted(((v, instr) for instr, v in out.items()), reverse=True)


def collect_trace_events(obj):
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        events = obj.get("traceEvents")
        if isinstance(events, list):
            return events
    return []


def select_trace_files(paths: list[Path]) -> list[Path]:
    aggregate = [path for path in paths if path.parent.name == "simulator"]
    return aggregate or paths


def select_aggregate_trace_files(paths: list[Path]) -> list[Path]:
    return [path for path in paths if path.parent.name == "simulator"]


def aggregate_trace(paths: list[Path]):
    pipe_duration = defaultdict(float)
    pipe_count = Counter()
    flow_count = Counter()
    units = set()
    errors = []
    for path in select_trace_files(paths):
        try:
            obj = read_json(path)
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        if isinstance(obj, dict) and obj.get("displayTimeUnit"):
            units.add(str(obj["displayTimeUnit"]))
        for event in collect_trace_events(obj):
            if not isinstance(event, dict):
                continue
            if event.get("ph") == "X":
                dur = to_float(event.get("dur"))
                pipe = event.get("tid")
                if dur is not None and pipe:
                    pipe = str(pipe)
                    pipe_duration[pipe] += dur
                    pipe_count[pipe] += 1
            cat = event.get("cat")
            if event.get("name") == "flow" and cat:
                flow_count[str(cat)] += 1
    pipe_rows = sorted(
        ((duration, pipe_count[pipe], pipe) for pipe, duration in pipe_duration.items()),
        reverse=True,
    )
    return pipe_rows, flow_count.most_common(), sorted(units), errors


def empty_sync_event_row() -> dict[str, object]:
    return {
        "trace_events": 0,
        "csv_rows": 0,
        "csv_call_count": 0.0,
        "csv_cycles": 0.0,
        "csv_running_time": 0.0,
        "sources": set(),
    }


def aggregate_sync_events(trace_paths: list[Path], instr_paths: list[Path], run_dir: Path):
    rows = {instruction: empty_sync_event_row() for instruction in SYNC_EVENT_INSTRUCTIONS}
    errors = []
    for path in select_aggregate_trace_files(trace_paths):
        try:
            obj = read_json(path)
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        source = rel(path, run_dir)
        for event in collect_trace_events(obj):
            if not isinstance(event, dict):
                continue
            name = event.get("name")
            if name not in rows or event.get("ph") not in SYNC_EVENT_PHASES:
                continue
            rows[str(name)]["trace_events"] += 1
            rows[str(name)]["sources"].add(source)

    for path in instr_paths:
        source = rel(path, run_dir)
        for row in read_csv_rows(path):
            instr = first_present(row, INSTR_ALIASES)
            if instr not in rows:
                continue
            out = rows[str(instr)]
            out["csv_rows"] += 1
            out["sources"].add(source)
            for field, aliases in [
                ("csv_call_count", SYNC_CALL_COUNT_ALIASES),
                ("csv_cycles", SYNC_CYCLES_ALIASES),
                ("csv_running_time", SYNC_RUNNING_TIME_ALIASES),
            ]:
                value = to_float(first_present(row, aliases))
                if value is not None:
                    out[field] += value

    observed = []
    for instruction in SYNC_EVENT_INSTRUCTIONS:
        row = rows[instruction]
        if row["trace_events"] or row["csv_rows"]:
            observed.append(
                {
                    "instruction": instruction,
                    "trace_events": row["trace_events"],
                    "csv_rows": row["csv_rows"],
                    "csv_call_count": row["csv_call_count"],
                    "csv_cycles": row["csv_cycles"],
                    "csv_running_time": row["csv_running_time"],
                    "sources": "; ".join(sorted(row["sources"])),
                }
            )
    return observed, errors


def aggregate_mte_throughput(paths: list[Path], run_dir: Path):
    rows = []
    errors = []
    for path in select_trace_files(paths):
        try:
            obj = read_json(path)
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        values = defaultdict(list)
        for event in collect_trace_events(obj):
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
        source = rel(path, run_dir)
        for channel in MTE_THROUGHPUT_CHANNELS:
            samples = values[channel]
            if samples:
                rows.append(
                    {
                        "channel": channel,
                        "max": max(samples),
                        "avg": sum(samples) / len(samples),
                        "samples": len(samples),
                        "source": source,
                    }
                )
    return sorted(
        rows,
        key=lambda row: (row["max"], row["avg"], row["samples"], row["channel"]),
        reverse=True,
    ), errors


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    run_dir = args.run_dir.resolve()
    code_files = find_files(run_dir, ["core*_code_exe.csv"])
    instr_files = find_files(run_dir, ["core*_instr_exe.csv"])
    trace_files = find_files(run_dir, ["trace.json"])
    out_dir = analysis_dir(run_dir)
    lines = ["# Simulator Hotspots", ""]
    lines.append("## Source Lines")
    if not code_files:
        lines.append("No core*_code_exe.csv files found.")
    else:
        code_rows = aggregate_code(code_files)
        if not code_rows:
            lines.append("No source-line rows with numeric timing fields found.")
        for value, file_, line in code_rows[:args.top]:
            lines.append(f"- {value:g}: {file_}:{line}")
    lines.append("")
    lines.append("## Instructions")
    if not instr_files:
        lines.append("No core*_instr_exe.csv files found.")
    else:
        for value, instr in aggregate_instr(instr_files)[:args.top]:
            lines.append(f"- {value:g}: {instr}")
    lines.append("")
    lines.append("## Trace Pipeline Context")
    if not trace_files:
        lines.append("No trace.json files found.")
    else:
        pipe_rows, flow_rows, units, errors = aggregate_trace(trace_files)
        if units:
            lines.append(f"- displayTimeUnit: {', '.join(units)}")
        for error in errors:
            lines.append(f"- ERROR: {error}")
        if not pipe_rows:
            lines.append("No trace events with explicit duration fields found.")
        else:
            lines.append("")
            lines.append("| Duration | Events | Pipe |")
            lines.append("|---:|---:|---|")
            for duration, count, pipe in pipe_rows[:args.top]:
                lines.append(f"| {duration:g} | {count} | {pipe} |")
        lines.append("")
        lines.append("## Trace Flow Categories")
        if not flow_rows:
            lines.append("No trace flow category events found.")
        else:
            lines.append("| Events | Category |")
            lines.append("|---:|---|")
            for category, count in flow_rows[:args.top]:
                lines.append(f"| {count} | {category} |")
    lines.append("")
    lines.append("## Synchronization Event Context")
    sync_rows, sync_errors = aggregate_sync_events(trace_files, instr_files, run_dir)
    for error in sync_errors:
        lines.append(f"- ERROR: {error}")
    if not sync_rows:
        lines.append(
            "No SET_FLAG/WAIT_FLAG synchronization events found in selected simulator trace.json or core*_instr_exe.csv files."
        )
    else:
        lines.append(
            "| Instruction | Trace events | CSV rows | CSV call_count | CSV cycles | CSV running_time(us) | Sources |"
        )
        lines.append("|---|---:|---:|---:|---:|---:|---|")
        for row in sync_rows:
            lines.append(
                "| {instruction} | {trace_events:g} | {csv_rows:g} | {csv_call_count:g} | {csv_cycles:g} | {csv_running_time:g} | {sources} |".format(
                    **row
                )
            )
    lines.append("")
    lines.append("## MTE Throughput Context")
    if not trace_files:
        lines.append("No trace.json files found.")
    else:
        throughput_rows, throughput_errors = aggregate_mte_throughput(trace_files, run_dir)
        for error in throughput_errors:
            lines.append(f"- ERROR: {error}")
        if not throughput_rows:
            lines.append(
                "No MTE Throughput counter events with numeric throughput(MB/s) values found in selected trace.json files."
            )
        else:
            lines.append("| Channel | Max throughput(MB/s) | Avg throughput(MB/s) | Samples | Source |")
            lines.append("|---|---:|---:|---:|---|")
            for row in throughput_rows[:args.top]:
                lines.append(
                    "| {channel} | {max:g} | {avg:g} | {samples} | {source} |".format(**row)
                )
    out = out_dir / "simulator_hotspots.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
