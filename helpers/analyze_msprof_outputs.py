#!/usr/bin/env python3
"""Extract key summaries from Ascend msprof / msprof op output."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from ascend_profile_utils import (
    analysis_dir,
    find_files,
    first_present,
    normalized_key,
    read_csv_rows,
    rel,
    summarize_csv,
    to_float,
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
    "l2_cache": ["L2Cache.csv"],
    "memory": ["Memory.csv", "MemoryL0.csv", "MemoryUB.csv"],
    "resource_conflict": ["ResourceConflictRatio.csv"],
}

DURATION_ALIASES = ["task duration", "task time", "duration", "execution time", "total time", "time"]
COUNT_ALIASES = ["count", "calls", "call count", "op count"]
NAME_ALIASES = ["op name", "operator name", "kernel name", "kernel_name", "task name", "api name", "sub block id", "sub_block_id", "op type", "name"]
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
OCCUPANCY_SECTION_NAME = "Occupancy Summary Report"
OCCUPANCY_SECTION_START_RE = re.compile(r"^.*\[INFO\]\s+Occupancy Summary Report:\s*$")
REPORT_SECTION_HEADER_RE = re.compile(r"^.*\[INFO\]\s+\S.* Report:\s*$")
OCCUPANCY_MESSAGE_RE = re.compile(r"^\s*(?P<ordinal>[0-9]+)\)\s+(?P<message>.+\S)\s*$")
AUXILIARY_STDOUT_MARKERS = ["help", "export", "validation"]


def is_auxiliary_stdout_log(path: Path) -> bool:
    stem = path.stem.lower()
    return any(marker in stem for marker in AUXILIARY_STDOUT_MARKERS)


def selected_profiler_stdout_paths(run_dir: Path) -> list[Path]:
    logs_dir = run_dir / "logs"
    if not logs_dir.exists():
        return []

    paths = [path for path in logs_dir.glob("*.stdout") if path.is_file()]
    paths_by_name = {path.name: path for path in paths}
    selected: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path | None) -> None:
        if path is None or path in seen or is_auxiliary_stdout_log(path):
            return
        selected.append(path)
        seen.add(path)

    for path in sorted(logs_dir.glob("msprof_occupancy*.stdout")):
        add(path)
    add(paths_by_name.get("msprof_default.stdout"))
    add(paths_by_name.get("command_msprof.stdout"))
    for path in sorted(logs_dir.glob("msprof*.stdout")):
        add(path)
    return selected


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
        "stdout_sections": {
            "occupancy_summary": parse_occupancy_summary_stdout(run_dir),
        },
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
