#!/usr/bin/env python3
"""Aggregate Ascend simulator source-line and instruction hotspots."""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from ascend_profile_utils import analysis_dir, find_files, first_present, read_csv_rows, to_float

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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    run_dir = args.run_dir.resolve()
    code_files = find_files(run_dir, ["core*_code_exe.csv"])
    instr_files = find_files(run_dir, ["core*_instr_exe.csv"])
    out_dir = analysis_dir(run_dir)
    lines = ["# Simulator Hotspots", ""]
    lines.append("## Source Lines")
    if not code_files:
        lines.append("No core*_code_exe.csv files found.")
    else:
        for value, file_, line in aggregate_code(code_files)[:args.top]:
            lines.append(f"- {value:g}: {file_}:{line}")
    lines.append("")
    lines.append("## Instructions")
    if not instr_files:
        lines.append("No core*_instr_exe.csv files found.")
    else:
        for value, instr in aggregate_instr(instr_files)[:args.top]:
            lines.append(f"- {value:g}: {instr}")
    out = out_dir / "simulator_hotspots.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

