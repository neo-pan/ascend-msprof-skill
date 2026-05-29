#!/usr/bin/env python3
"""Aggregate Ascend simulator source-line and instruction hotspots."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

from ascend_profile_utils import analysis_dir, find_files, first_present, read_csv_rows, read_json, to_float

VALUE_ALIASES = ["time", "duration", "cycles", "cycle", "cost"]
LINE_ALIASES = ["line", "line no", "lineno", "source line"]
FILE_ALIASES = ["file", "source", "filename", "path"]
INSTR_ALIASES = ["instruction", "instr", "opcode", "asm"]


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
    out = out_dir / "simulator_hotspots.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
