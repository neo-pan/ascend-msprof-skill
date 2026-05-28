#!/usr/bin/env python3
"""Generate an evidence-cited REPORT.md from Ascend profiling analysis."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


HEADLINE_GROUPS = [
    ("op_summary", "Top operator duration"),
    ("op_statistic", "Top operator type aggregate"),
    ("task_time", "Top task duration"),
    ("api_statistic", "Top host/runtime API time"),
    ("op_basic_info", "Operator metadata"),
    ("pipe_utilization", "Dominant pipe signal"),
    ("arithmetic_utilization", "Arithmetic utilization signal"),
    ("memory", "Top memory signal"),
    ("resource_conflict", "Top conflict signal"),
]

ANALYSIS_SECTIONS = [
    ("Duration And Calls", ["op_summary", "op_statistic", "task_time", "api_statistic"]),
    ("Pipe Utilization", ["pipe_utilization", "arithmetic_utilization"]),
    ("Memory Movement", ["memory"]),
    ("Conflicts", ["resource_conflict"]),
    ("Tiling And Core Balance", ["op_basic_info"]),
]


def load_or_create_summary(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "analysis" / "summary.json"
    if not summary_path.exists():
        analyzer = Path(__file__).with_name("analyze_msprof_outputs.py")
        subprocess.run(
            [sys.executable, str(analyzer), "--run-dir", str(run_dir)],
            check=True,
            text=True,
        )
    with summary_path.open(encoding="utf-8") as f:
        return json.load(f)


def fmt_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, (int, float)):
        return f"{float(value):.6g}"
    return str(value)


def md_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def target_name(summary: dict[str, Any]) -> str:
    headlines = summary.get("headlines", {})
    for group in ["op_basic_info", "op_summary", "op_statistic", "task_time"]:
        item = headlines.get(group) or {}
        name = item.get("name")
        if name:
            return str(name)
    return "Ascend profiling run"


def field_reference(group: str, item: dict[str, Any]) -> str:
    refs = [f"headlines.{group}.value"]
    if item.get("field"):
        refs.append(f"headlines.{group}.field={item['field']}")
    if item.get("field_kind"):
        refs.append(f"headlines.{group}.field_kind={item['field_kind']}")
    return "; ".join(refs)


def headline_rows(summary: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    rows = []
    headlines = summary.get("headlines", {})
    for group, label in HEADLINE_GROUPS:
        item = headlines.get(group)
        if not item:
            continue
        name = item.get("name") or "n/a"
        field = item.get("field")
        signal = f"{name} / {field}" if field else str(name)
        source = f"`{item.get('file', 'missing')}`; `{field_reference(group, item)}`"
        rows.append((label, signal, fmt_value(item.get("value")), source))
    return rows


def diagnosis_rows(summary: dict[str, Any]) -> list[tuple[str, str, str]]:
    rows = []
    headlines = summary.get("headlines", {})
    for group, label in [
        ("op_summary", "Highest application-level operator duration"),
        ("task_time", "Highest device task duration"),
        ("pipe_utilization", "Highest pipe utilization signal"),
        ("memory", "Highest memory signal"),
        ("resource_conflict", "Highest resource conflict signal"),
    ]:
        item = headlines.get(group)
        if not item:
            continue
        name = item.get("name") or "n/a"
        value = fmt_value(item.get("value"))
        evidence = f"`{item.get('file', 'missing')}`; `{field_reference(group, item)}`"
        impact = "Use this sourced signal to choose the next focused inspection step."
        rows.append((f"{label}: {name} = {value}", evidence, impact))
    if rows:
        return rows
    return [(
        "No headline diagnosis generated",
        "`analysis/summary.json`; `headlines`",
        "Required profiler artifacts were missing.",
    )]


def first_existing_analysis(run_dir: Path, names: list[str]) -> list[str]:
    out = []
    for name in names:
        path = run_dir / "analysis" / name
        if path.exists():
            out.append(f"`analysis/{name}`")
    return out


def section_lines(summary: dict[str, Any], title: str, groups: list[str]) -> list[str]:
    lines = [f"### {title}", ""]
    headlines = summary.get("headlines", {})
    added = False
    for group in groups:
        item = headlines.get(group)
        if not item:
            continue
        name = item.get("name") or "n/a"
        value = fmt_value(item.get("value"))
        field = item.get("field")
        field_text = f" field `{field}`" if field else ""
        lines.append(
            f"- `{group}`: `{name}`{field_text} = `{value}` from "
            f"`{item.get('file', 'missing')}`; evidence `{field_reference(group, item)}`."
        )
        added = True
    if not added:
        lines.append("- No sourced headline available in `analysis/summary.json`.")
    lines.append("")
    return lines


def caveats(summary: dict[str, Any], run_dir: Path) -> list[str]:
    out = []
    for warning in summary.get("warnings", []):
        out.append(f"Analyzer warning: {warning}")
    for name in ["timeline.txt", "simulator_hotspots.txt"]:
        if not (run_dir / "analysis" / name).exists():
            out.append(f"Optional analysis artifact missing: analysis/{name}")
    return out


def build_report(summary: dict[str, Any], run_dir: Path) -> str:
    target = target_name(summary)
    rows = headline_rows(summary)
    diag_rows = diagnosis_rows(summary)
    analysis_artifacts = first_existing_analysis(
        run_dir,
        ["summary.json", "key_metrics.txt", "timeline.txt", "simulator_hotspots.txt"],
    )
    caveat_lines = caveats(summary, run_dir)
    if rows:
        one_line = f"**One-line read:** Review `{rows[0][0]}` first because it is the highest available sourced headline."
    else:
        one_line = "**One-line read:** No sourced headline is available yet."

    lines = [
        f"# {target} Ascend Profiling Report",
        "",
        "**Target:** Ascend 910B",
        "**CANN / driver / firmware:** not recorded by this helper",
        "**Profile date:** not recorded by this helper",
        f"**Run directory:** `{run_dir.name}`",
        "",
        "## 0. Setup",
        "",
        f"- Harness/application: not recorded; inspect `{run_dir.name}` run notes if present.",
        "- Workload shape and dtype: not recorded by this helper.",
        "- Tiling path and blockDim: see `OpBasicInfo.csv` when present.",
        "- Commands: see reproduction section.",
        f"- Raw artifacts: `{run_dir.name}/reports/`",
        f"- Analysis artifacts: {', '.join(analysis_artifacts) if analysis_artifacts else 'none found'}",
        "",
        "## 1. Headline Numbers",
        "",
        "| Metric | Signal | Value | Source |",
        "|---|---|---:|---|",
    ]
    for metric, signal, value, source in rows:
        lines.append(f"| {md_escape(metric)} | {md_escape(signal)} | {md_escape(value)} | {source} |")
    if not rows:
        lines.append("| No headline available | n/a | n/a | `analysis/summary.json`; `headlines` |")
    lines.extend(["", one_line, ""])

    lines.append("## 2. Analysis")
    lines.append("")
    for title, groups in ANALYSIS_SECTIONS:
        lines.extend(section_lines(summary, title, groups))
    lines.extend(["### Simulator Hotspots", ""])
    if (run_dir / "analysis" / "simulator_hotspots.txt").exists():
        lines.append("- Simulator hotspot summary is available at `analysis/simulator_hotspots.txt`.")
    else:
        lines.append("- No simulator hotspot summary is available; this is optional for non-simulator runs.")
    lines.append("")

    lines.extend([
        "## 3. Diagnosis",
        "",
        "| Finding | Evidence | Impact |",
        "|---|---|---|",
    ])
    for finding, evidence, impact in diag_rows:
        lines.append(f"| {md_escape(finding)} | {evidence} | {md_escape(impact)} |")

    lines.extend([
        "",
        "## 4. Optimization Directions",
        "",
    ])
    for idx, (finding, evidence, _impact) in enumerate(diag_rows[:3], start=1):
        lines.append(f"{idx}. Inspect {md_escape(finding)} using {evidence} before changing kernel code.")
    if not diag_rows:
        lines.append("1. Collect the missing profiler artifacts before changing kernel code.")

    lines.extend([
        "",
        "## 5. Confidence And Caveats",
        "",
        "- Confidence is limited to artifacts summarized in `analysis/summary.json`.",
    ])
    if caveat_lines:
        for caveat in caveat_lines:
            lines.append(f"- {md_escape(caveat)}")
    else:
        lines.append("- No missing optional analysis artifacts were detected.")

    lines.extend([
        "",
        "## 6. Reproduction",
        "",
        "```bash",
        "python3 helpers/analyze_msprof_outputs.py --run-dir <run-dir>",
        "python3 helpers/generate_report.py --run-dir <run-dir>",
        "```",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    args = ap.parse_args()

    run_dir = args.run_dir.resolve()
    summary = load_or_create_summary(run_dir)
    out = run_dir / "REPORT.md"
    out.write_text(build_report(summary, run_dir), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
