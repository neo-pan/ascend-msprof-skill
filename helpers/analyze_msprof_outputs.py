#!/usr/bin/env python3
"""Extract key summaries from Ascend msprof / msprof op output."""
from __future__ import annotations

import argparse
from pathlib import Path

from ascend_profile_utils import (
    analysis_dir,
    find_files,
    first_present,
    read_csv_rows,
    rel,
    summarize_csv,
    to_float,
    top_numeric_cell,
    top_numeric_row,
    write_json,
)


FILE_GROUPS = {
    "op_summary": ["op_summary_*.csv"],
    "op_statistic": ["op_statistic_*.csv"],
    "task_time": ["task_time_*.csv"],
    "api_statistic": ["api_statistic_*.csv"],
    "op_basic_info": ["OpBasicInfo.csv"],
    "pipe_utilization": ["PipeUtilization.csv"],
    "arithmetic_utilization": ["ArithmeticUtilization.csv"],
    "memory": ["Memory.csv", "MemoryL0.csv", "MemoryUB.csv"],
    "resource_conflict": ["ResourceConflictRatio.csv"],
}

DURATION_ALIASES = ["task duration", "task time", "duration", "execution time", "total time", "time"]
COUNT_ALIASES = ["count", "calls", "call count", "op count"]
NAME_ALIASES = ["op name", "operator name", "kernel name", "kernel_name", "task name", "api name", "sub block id", "sub_block_id", "op type", "name"]
UTIL_ALIASES = ["utilization", "ratio", "rate", "usage"]
MEMORY_ALIASES = ["usage rate", "bw", "bandwidth", "datas", "bytes"]


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
    for path in files:
        row, field, value = top_numeric_cell(read_csv_rows(path), MEMORY_ALIASES)
        if value is None:
            continue
        if best_value is None or value > best_value:
            best_path = path
            best_row = row
            best_field = field
            best_value = value
    return {
        "file": rel(best_path, run_dir) if best_path else rel(files[0], run_dir),
        "name": first_present(best_row or {}, NAME_ALIASES + ["memory", "sub block id", "sub_block_id"]),
        "value": best_value,
        "field": best_field,
        "field_kind": "memory_value_or_rate",
        "raw_row": best_row,
    }


def headline_for_group(run_dir: Path, group: str, patterns: list[str]) -> dict | None:
    files = find_files(run_dir, patterns)
    if not files:
        return None
    if group == "memory":
        return memory_headline(run_dir, files)
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
        row, value = top_numeric_row(rows, UTIL_ALIASES)
        return {
            "file": rel(path, run_dir),
            "name": first_present(row or {}, NAME_ALIASES + ["pipe", "resource", "metric"]),
            "value": value,
            "field_kind": "utilization_or_ratio",
            "raw_row": row,
        }
    if group == "op_basic_info":
        first_row = rows[0] if rows else {}
        return {
            "file": rel(path, run_dir),
            "row_count": len(rows),
            "name": first_present(first_row, NAME_ALIASES),
            "value": to_float(first_present(first_row, DURATION_ALIASES)),
            "field_kind": "basic_info",
            "first_row": first_row,
        }
    return None


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
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    args = ap.parse_args()

    run_dir = args.run_dir.resolve()
    out_dir = analysis_dir(run_dir)
    summary = {
        "run_dir": str(run_dir),
        "run_dir_path": run_dir,
        "files": {},
        "headlines": {},
        "warnings": [],
    }
    for group, patterns in FILE_GROUPS.items():
        records = collect_group(run_dir, group, patterns)
        summary["files"][group] = records
        summary["headlines"][group] = headline_for_group(run_dir, group, patterns)
        if not records:
            summary["warnings"].append(f"missing {group}: {patterns}")

    json_summary = dict(summary)
    json_summary.pop("run_dir_path")
    write_json(out_dir / "summary.json", json_summary)
    write_text_summary(out_dir / "key_metrics.txt", summary)
    print(f"wrote {out_dir / 'summary.json'}")
    print(f"wrote {out_dir / 'key_metrics.txt'}")


if __name__ == "__main__":
    main()
