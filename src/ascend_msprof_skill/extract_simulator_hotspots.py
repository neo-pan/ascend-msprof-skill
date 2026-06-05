#!/usr/bin/env python3
"""Aggregate Ascend simulator source-line and instruction hotspots."""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from .ascend_profile_utils import analysis_dir, write_json
from .simulator_hotspot_model import build_simulator_hotspot_model


def input_records(model: dict, kind: str) -> list[dict]:
    return [item for item in model.get("inputs", []) if item.get("kind") == kind]


def parser_errors(model: dict, needle: str) -> list[str]:
    return [warning for warning in model.get("warnings", []) if needle in str(warning)]


def source_label(row: dict) -> str:
    source_file = row.get("source_file")
    line = row.get("line")
    if source_file and line:
        return f"{source_file}:{line}"
    if line:
        return f"{row.get('artifact', 'unknown')}:{line}"
    if row.get("code"):
        return str(row["code"])
    return str(row.get("artifact", "unknown"))


def instruction_markdown_rows(model: dict) -> list[tuple[float, str]]:
    totals: dict[str, float] = defaultdict(float)
    for row in model.get("instructions", []):
        instr = str(row.get("instr") or "<unknown>")
        value = row.get("value")
        if isinstance(value, (int, float)):
            totals[instr] += float(value)
    return sorted(((value, instr) for instr, value in totals.items()), reverse=True)


def render_markdown(model: dict, top: int) -> str:
    lines = ["# Simulator Hotspots", ""]

    code_inputs = input_records(model, "code_execution_csv")
    lines.append("## Source Lines")
    if not code_inputs:
        lines.append("No core*_code_exe.csv files found.")
    else:
        source_lines = model.get("source_lines", [])
        if not source_lines:
            lines.append("No source-line rows with numeric timing fields found.")
        for row in source_lines[:top]:
            value = row.get("value")
            value_text = f"{value:g}" if isinstance(value, (int, float)) else str(value)
            lines.append(f"- {value_text}: {source_label(row)}")

    instr_inputs = input_records(model, "instruction_execution_csv")
    lines.append("")
    lines.append("## Instructions")
    if not instr_inputs:
        lines.append("No core*_instr_exe.csv files found.")
    else:
        for value, instr in instruction_markdown_rows(model)[:top]:
            lines.append(f"- {value:g}: {instr}")

    trace_inputs = input_records(model, "trace_json")
    lines.append("")
    lines.append("## Trace Pipeline Context")
    if not trace_inputs:
        lines.append("No trace.json files found.")
    else:
        units = sorted(
            {
                str(item.get("display_time_unit"))
                for item in trace_inputs
                if item.get("display_time_unit")
            }
        )
        if units:
            lines.append(f"- displayTimeUnit: {', '.join(units)}")
        for error in parser_errors(model, "invalid simulator trace"):
            lines.append(f"- ERROR: {error}")
        pipeline_events = model.get("pipeline_events", [])
        if not pipeline_events:
            lines.append("No trace events with explicit duration fields found.")
        else:
            lines.append("")
            lines.append("| Duration | Events | Pipe |")
            lines.append("|---:|---:|---|")
            for row in pipeline_events[:top]:
                duration = row.get("duration")
                duration_text = f"{duration:g}" if isinstance(duration, (int, float)) else str(duration)
                lines.append(f"| {duration_text} | {row.get('event_count')} | {row.get('tid')} |")

        lines.append("")
        lines.append("## Trace Flow Categories")
        flow_categories = model.get("flow_categories", [])
        if not flow_categories:
            lines.append("No trace flow category events found.")
        else:
            lines.append("| Events | Category |")
            lines.append("|---:|---|")
            for row in flow_categories[:top]:
                lines.append(f"| {row.get('count')} | {row.get('category')} |")

    lines.append("")
    lines.append("## Synchronization Event Context")
    sync_rows = model.get("sync_events", [])
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
            sources = "; ".join(row.get("sources") or [])
            lines.append(
                "| {instruction} | {trace_events:g} | {csv_rows:g} | {csv_call_count:g} | {csv_cycles:g} | {csv_running_time:g} | {sources} |".format(
                    instruction=row.get("instruction"),
                    trace_events=row.get("trace_events", 0),
                    csv_rows=row.get("csv_rows", 0),
                    csv_call_count=row.get("csv_call_count", 0),
                    csv_cycles=row.get("csv_cycles", 0),
                    csv_running_time=row.get("csv_running_time(us)", 0),
                    sources=sources,
                )
            )

    lines.append("")
    lines.append("## MTE Throughput Context")
    if not trace_inputs:
        lines.append("No trace.json files found.")
    else:
        for error in parser_errors(model, "invalid simulator trace"):
            lines.append(f"- ERROR: {error}")
        throughput_rows = model.get("mte_throughput", [])
        if not throughput_rows:
            lines.append(
                "No MTE Throughput counter events with numeric throughput(MB/s) values found in selected trace.json files."
            )
        else:
            lines.append("| Channel | Max throughput(MB/s) | Avg throughput(MB/s) | Samples | Source |")
            lines.append("|---|---:|---:|---:|---|")
            for row in throughput_rows[:top]:
                lines.append(
                    "| {channel} | {max:g} | {avg:g} | {samples} | {source} |".format(
                        channel=row.get("channel"),
                        max=row.get("max", 0),
                        avg=row.get("avg", 0),
                        samples=row.get("samples", 0),
                        source=row.get("artifact"),
                    )
                )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args(argv)

    run_dir = args.run_dir.resolve()
    out_dir = analysis_dir(run_dir)
    model = build_simulator_hotspot_model(run_dir)
    json_out = out_dir / "simulator_hotspots.json"
    text_out = out_dir / "simulator_hotspots.txt"
    write_json(json_out, model)
    text_out.write_text(render_markdown(model, args.top), encoding="utf-8")
    print(f"wrote {json_out}")
    print(f"wrote {text_out}")


if __name__ == "__main__":
    main()
