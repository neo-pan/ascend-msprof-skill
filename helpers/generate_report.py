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
    ("l2_cache", "L2 cache hit-rate signal"),
    ("memory", "Top memory signal"),
    ("resource_conflict", "Top conflict signal"),
]

ANALYSIS_SECTIONS = [
    ("Duration And Calls", ["op_summary", "op_statistic", "task_time", "api_statistic"]),
    ("Pipe Utilization", ["pipe_utilization", "arithmetic_utilization"]),
    ("L2 Cache", ["l2_cache"]),
    ("Memory Movement", ["memory"]),
    ("Conflicts", ["resource_conflict"]),
    ("Tiling And Core Balance", ["op_basic_info"]),
]

ANALYSIS_ARTIFACTS = ["summary.json", "key_metrics.txt", "timeline.txt", "simulator_hotspots.txt"]
OPTIONAL_ANALYSIS_ARTIFACTS = ["timeline.txt", "simulator_hotspots.txt"]
CORRELATION_GROUPS = [
    ("App top operator", "op_summary"),
    ("App top task", "task_time"),
    ("Op metadata", "op_basic_info"),
    ("Op pipe signal", "pipe_utilization"),
]
RAW_VALUE_FIELD_CANDIDATES = {
    "op_summary": ["Task Duration(us)", "task_duration(us)", "duration(us)", "total time(us)"],
    "task_time": ["task_time(us)", "Task Duration(us)", "task duration(us)"],
    "op_basic_info": ["Task Duration(us)", "task duration(us)"],
}


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


def load_provenance(run_dir: Path) -> dict[str, Any] | None:
    provenance_path = run_dir / "analysis" / "provenance.json"
    if not provenance_path.exists():
        return None
    with provenance_path.open(encoding="utf-8") as f:
        return json.load(f)


def load_tilelang_context(run_dir: Path) -> dict[str, Any] | None:
    context_path = run_dir / "analysis" / "tilelang_context.json"
    if not context_path.exists():
        return None
    with context_path.open(encoding="utf-8") as f:
        return json.load(f)


def load_tilelang_benchmark_profile_run(run_dir: Path) -> dict[str, Any] | None:
    workflow_path = run_dir / "analysis" / "tilelang_benchmark_profile_run.json"
    if not workflow_path.exists():
        return None
    with workflow_path.open(encoding="utf-8") as f:
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


def fmt_compact(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, (int, float)):
        return fmt_value(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ": "))
    return str(value)


def display_run_dir(run_dir: Path) -> str:
    for index in range(len(run_dir.parts) - 1, -1, -1):
        if run_dir.parts[index] == "profile":
            return Path(*run_dir.parts[index:]).as_posix()
    return run_dir.name


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


def raw_value_field_reference(group: str, item: dict[str, Any]) -> str | None:
    raw_row_key = "first_row" if group == "op_basic_info" else "raw_row"
    if item.get("field"):
        raw_row = item.get(raw_row_key) or {}
        if isinstance(raw_row, dict) and item["field"] in raw_row:
            return f"headlines.{group}.{raw_row_key}.{item['field']}"
        return None

    raw_row = item.get(raw_row_key) or {}
    if not isinstance(raw_row, dict):
        return None
    normalized = {str(key).strip().lower(): str(key) for key in raw_row}
    for candidate in RAW_VALUE_FIELD_CANDIDATES.get(group, []):
        field = normalized.get(candidate.strip().lower())
        if field:
            return f"headlines.{group}.{raw_row_key}.{field}"
    return None


def correlation_field_reference(group: str, item: dict[str, Any]) -> str:
    refs = [f"headlines.{group}.value"]
    raw_ref = raw_value_field_reference(group, item)
    if raw_ref:
        refs.append(raw_ref)
    if item.get("field"):
        refs.append(f"headlines.{group}.field={item['field']}")
    if item.get("field_kind"):
        refs.append(f"headlines.{group}.field_kind={item['field_kind']}")
    return "; ".join(refs)


def sourced_value_text(item: dict[str, Any] | None, fallback: str) -> str:
    if not item:
        return fallback
    value = item.get("value")
    source = item.get("source") or {}
    artifact = source.get("artifact")
    field = source.get("field")
    text = fmt_value(value)
    if artifact and field:
        return f"{text} (source: `{artifact}`; `{field}`)"
    if artifact:
        return f"{text} (source: `{artifact}`)"
    return text


def profile_outputs_text(provenance: dict[str, Any] | None) -> str:
    if not provenance:
        return "not recorded"
    outputs = provenance.get("profile_outputs")
    if isinstance(outputs, list) and outputs:
        return ", ".join(sourced_value_text(item if isinstance(item, dict) else None, "not recorded") for item in outputs)
    return sourced_value_text(provenance.get("profile_output"), "not recorded")


def profile_output_segments_text(provenance: dict[str, Any] | None) -> str | None:
    if not provenance:
        return None
    segments = provenance.get("profile_output_segments")
    if not isinstance(segments, dict):
        return None
    rendered = []
    for name in ["app", "op"]:
        segment = segments.get(name)
        if not isinstance(segment, dict):
            continue
        parts = []
        output = segment.get("output")
        if isinstance(output, dict):
            parts.append(sourced_value_text(output, "not recorded"))
        resolved_output = segment.get("resolved_output")
        if isinstance(resolved_output, dict):
            parts.append(f"resolved {sourced_value_text(resolved_output, 'not recorded')}")
        if parts:
            rendered.append(f"{name}: {', '.join(parts)}")
    if not rendered:
        return None
    return "; ".join(rendered)


def profile_outputs_setup_line(provenance: dict[str, Any] | None) -> str:
    segmented = profile_output_segments_text(provenance)
    if segmented:
        return f"- Profile outputs: {segmented}"
    return f"- Profile output: {profile_outputs_text(provenance)}"


def provenance_caveats(provenance: dict[str, Any] | None) -> list[str]:
    if not provenance:
        return []
    return [f"Provenance warning: {warning}" for warning in provenance.get("warnings", [])]


def tilelang_caveats(tilelang_context: dict[str, Any] | None) -> list[str]:
    if not tilelang_context:
        return []
    return [f"TileLang context warning: {warning}" for warning in tilelang_context.get("warnings", [])]


def orchestrator_caveats(orchestrator: dict[str, Any] | None) -> list[str]:
    if not orchestrator:
        return []
    return [f"TileLang benchmark orchestrator warning: {warning}" for warning in orchestrator.get("warnings", [])]


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
    ]:
        item = headlines.get(group)
        if not item:
            continue
        name = item.get("name") or "n/a"
        value = fmt_value(item.get("value"))
        evidence = f"`{item.get('file', 'missing')}`; `{field_reference(group, item)}`"
        impact = "Use this sourced signal to choose the next focused inspection step."
        rows.append((f"{label}: {name} = {value}", evidence, impact))
    return rows


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


def analysis_dimension_lines(summary: dict[str, Any]) -> list[str]:
    dimensions = summary.get("analysis_dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        return []
    lines = [
        "### Analysis Dimensions",
        "",
        "| Dimension | Status | Signal | Evidence |",
        "|---|---|---|---|",
    ]
    for dimension in dimensions:
        title = dimension.get("title") or dimension.get("id") or "n/a"
        status = dimension.get("status") or "insufficient"
        signals = dimension.get("signals") or []
        if not signals:
            lines.append(f"| {md_escape(title)} | {md_escape(status)} | n/a | `analysis/summary.json`; `analysis_dimensions.{md_escape(dimension.get('id', 'unknown'))}` |")
            continue
        for signal in signals[:5]:
            signal_name = signal.get("signal") or "n/a"
            value = signal.get("value")
            field_ref = signal.get("field_ref", "missing")
            if value is None and signal.get("tiling_field") and signal.get("tiling_value") is not None:
                signal_name = f"{str(signal_name).split(' / ', 1)[0]} / {signal['tiling_field']}"
                value = signal.get("tiling_value")
                field_ref = signal.get("tiling_field_ref", field_ref)
            formatted_value = fmt_value(value)
            rendered_signal = signal_name if formatted_value == "n/a" else f"{signal_name} = {formatted_value}"
            evidence = f"`{signal.get('artifact', 'missing')}`; `{field_ref}`"
            lines.append(f"| {md_escape(title)} | {md_escape(status)} | {md_escape(rendered_signal)} | {evidence} |")
    lines.append("")
    return lines


def app_op_correlation_lines(summary: dict[str, Any]) -> list[str]:
    headlines = summary.get("headlines", {})
    if not all(isinstance(headlines.get(group), dict) for _label, group in CORRELATION_GROUPS):
        return []

    lines = [
        "### App/Op Correlation",
        "",
        "| Source | Signal | Value | Evidence |",
        "|---|---|---:|---|",
    ]
    for label, group in CORRELATION_GROUPS:
        item = headlines[group]
        name = item.get("name") or "n/a"
        field = item.get("field")
        signal = f"{name} / {field}" if field else str(name)
        evidence = f"`{item.get('file', 'missing')}`; `{correlation_field_reference(group, item)}`"
        lines.append(f"| {md_escape(label)} | {md_escape(signal)} | {md_escape(fmt_value(item.get('value')))} | {evidence} |")
    lines.append("")
    return lines


def optimization_direction_lines(summary: dict[str, Any], diag_rows: list[tuple[str, str, str]]) -> list[str]:
    has_direction_model = "optimization_directions" in summary
    directions = summary.get("optimization_directions")
    lines = ["## 4. Optimization Directions", ""]
    if isinstance(directions, list) and directions:
        for item in directions:
            rank = item.get("rank") or "?"
            lines.append(f"{rank}. {md_escape(item.get('title', 'Inspection Direction'))}")
            lines.append(f"   - Action: {md_escape(item.get('action', 'Inspect the cited evidence before changing kernel code.'))}")
            lines.append(f"   - Impact basis: {md_escape(item.get('impact_basis', 'Evidence cited in analysis/summary.json.'))}")
            lines.append(f"   - Confidence: {md_escape(item.get('confidence', 'low'))}; effort: {md_escape(item.get('effort', 'medium'))}")
            evidence_items = item.get("evidence") or []
            if evidence_items:
                evidence_text = "; ".join(
                    f"`{evidence.get('artifact', 'missing')}` `{evidence.get('field_ref', 'missing')}`"
                    for evidence in evidence_items
                )
                lines.append(f"   - Evidence: {evidence_text}")
        return lines

    if has_direction_model:
        if diag_rows:
            lines.append("1. No ranked optimization direction generated from the available evidence.")
        else:
            lines.append("1. Collect the missing profiler artifacts before changing kernel code.")
        return lines

    if diag_rows:
        for idx, (finding, evidence, _impact) in enumerate(diag_rows[:3], start=1):
            lines.append(f"{idx}. Inspect {md_escape(finding)} using {evidence} before changing kernel code.")
    else:
        lines.append("1. Collect the missing profiler artifacts before changing kernel code.")
    return lines


def occupancy_summary_lines(summary: dict[str, Any]) -> list[str]:
    occupancy = summary.get("stdout_sections", {}).get("occupancy_summary")
    if not occupancy:
        return []
    lines = [
        "### Occupancy Summary",
        "",
        "| Ordinal | Message | Source |",
        "|---:|---|---|",
    ]
    source = occupancy.get("source", "missing")
    for message in occupancy.get("messages", []):
        lines.append(
            f"| {md_escape(message.get('ordinal'))} | "
            f"{md_escape(message.get('message'))} | "
            f"`{md_escape(source)}` |"
        )
    lines.append("")
    return lines


def roofline_summary_lines(summary: dict[str, Any]) -> list[str]:
    roofline = summary.get("stdout_sections", {}).get("roofline_summary")
    if not roofline:
        return []
    lines = [
        "### RoofLine Summary",
        "",
        "| Message | Source |",
        "|---|---|",
    ]
    source = roofline.get("source", "missing")
    for message in roofline.get("messages", []):
        lines.append(
            f"| {md_escape(message.get('message'))} | "
            f"`{md_escape(source)}` |"
        )
    lines.append("")
    return lines


def caveats(
    summary: dict[str, Any],
    run_dir: Path,
    provenance: dict[str, Any] | None = None,
    tilelang_context: dict[str, Any] | None = None,
    op_profile_enabled: bool = True,
    suppress_uncollected_op_metrics: bool = False,
) -> list[str]:
    out = []
    optional_op_metric_warnings = (
        "missing arithmetic_utilization:",
        "missing l2_cache:",
        "missing memory:",
        "missing resource_conflict:",
    )
    for warning in summary.get("warnings", []):
        if not op_profile_enabled and warning.startswith(
            (
                "missing op_basic_info:",
                "missing pipe_utilization:",
                *optional_op_metric_warnings,
            )
        ):
            continue
        if suppress_uncollected_op_metrics and warning.startswith(optional_op_metric_warnings):
            continue
        out.append(f"Analyzer warning: {warning}")
    for name in OPTIONAL_ANALYSIS_ARTIFACTS:
        if not (run_dir / "analysis" / name).exists():
            out.append(f"Optional analysis artifact missing: analysis/{name}")
    out.extend(provenance_caveats(provenance))
    out.extend(tilelang_caveats(tilelang_context))
    return out


def tilelang_context_lines(tilelang_context: dict[str, Any] | None) -> list[str]:
    if not tilelang_context:
        return []

    benchmark = tilelang_context.get("benchmark", {})
    workload = benchmark.get("workload", {})
    candidate = benchmark.get("candidate", {})
    correctness = benchmark.get("correctness", {})
    payload = tilelang_context.get("sources", {}).get("payload", {})
    jit_debug = tilelang_context.get("jit_debug")
    rows = [
        ("Workload id", workload.get("id"), "benchmark.workload.id"),
        ("Shape", workload.get("shape"), "benchmark.workload.shape"),
        ("Dtype", workload.get("dtype"), "benchmark.workload.dtype"),
        ("Case count", workload.get("case_count"), "benchmark.workload.case_count"),
        ("Compiled", candidate.get("compiled"), "benchmark.candidate.compiled"),
        ("Candidate runtime", candidate.get("runtime"), "benchmark.candidate.runtime"),
        ("Runtime stats", candidate.get("runtime_stats"), "benchmark.candidate.runtime_stats"),
        ("Reference runtime", candidate.get("ref_runtime"), "benchmark.candidate.ref_runtime"),
        ("Speedup", candidate.get("speedup"), "benchmark.candidate.speedup"),
    ]
    maxima = correctness.get("maxima") or []
    if maxima:
        rows.append(
            (
                "Correctness maxima",
                ", ".join(f"{item.get('field')}={fmt_value(item.get('value'))}" for item in maxima),
                "benchmark.correctness.maxima",
            )
        )
    else:
        rows.append(("Correctness maxima", "none recorded", "benchmark.correctness.maxima"))
    if payload:
        rows.append(("Payload source", payload.get("artifact"), "sources.payload.artifact"))
        rows.append(("Payload sha256", payload.get("sha256"), "sources.payload.sha256"))
    jit_config = benchmark.get("jit_config")
    if jit_config not in (None, "", [], {}):
        rows.append(("JIT config", jit_config, "benchmark.jit_config"))
    if jit_debug:
        artifacts = jit_debug.get("artifacts") or []
        if jit_debug.get("found"):
            preview = ", ".join(str(item.get("artifact")) for item in artifacts[:5])
            if len(artifacts) > 5:
                preview = f"{preview}, ..."
            value = f"{jit_debug.get('artifact_count', len(artifacts))} files"
            if preview:
                value = f"{value}: {preview}"
        else:
            value = "not found"
        rows.append(("JIT debug artifacts", value, "jit_debug.artifacts"))

    lines = [
        "### TileLang Benchmark Context",
        "",
        "| Field | Value | Source |",
        "|---|---|---|",
    ]
    for label, value, source in rows:
        lines.append(
            f"| {md_escape(label)} | {md_escape(fmt_compact(value))} | "
            f"`analysis/tilelang_context.json`; `{source}` |"
        )
    lines.append("")
    return lines


def tilelang_setup_shape(tilelang_context: dict[str, Any] | None) -> str:
    if not tilelang_context:
        return "not recorded by this helper."
    workload = tilelang_context.get("benchmark", {}).get("workload", {})
    shape = fmt_compact(workload.get("shape"))
    dtype = fmt_compact(workload.get("dtype"))
    case_count = fmt_compact(workload.get("case_count"))
    return (
        f"{shape}, dtype {dtype}, cases {case_count} "
        "(source: `analysis/tilelang_context.json`; `benchmark.workload`)."
    )


def tilelang_payload_text(tilelang_context: dict[str, Any] | None) -> str:
    if not tilelang_context:
        return "not recorded; inspect run notes if present."
    payload = tilelang_context.get("sources", {}).get("payload", {})
    artifact = payload.get("artifact")
    if artifact:
        return f"TileLang payload `{artifact}` (source: `analysis/tilelang_context.json`; `sources.payload.artifact`)."
    return "TileLang payload recorded in `analysis/tilelang_context.json`."


def build_report(
    summary: dict[str, Any],
    run_dir: Path,
    provenance: dict[str, Any] | None = None,
    tilelang_context: dict[str, Any] | None = None,
) -> str:
    orchestrator = load_tilelang_benchmark_profile_run(run_dir)
    op_profile_enabled = orchestrator is None or orchestrator.get("profiles", {}).get("op_pipe") is not False
    suppress_uncollected_op_metrics = orchestrator is not None
    target = target_name(summary)
    run_label = display_run_dir(run_dir)
    rows = headline_rows(summary)
    diag_rows = diagnosis_rows(summary)
    analysis_artifacts = first_existing_analysis(run_dir, ANALYSIS_ARTIFACTS)
    if provenance:
        analysis_artifacts.append("`analysis/provenance.json`")
    if tilelang_context:
        analysis_artifacts.append("`analysis/tilelang_context.json`")
    caveat_lines = caveats(
        summary,
        run_dir,
        provenance,
        tilelang_context,
        op_profile_enabled,
        suppress_uncollected_op_metrics,
    )
    caveat_lines.extend(orchestrator_caveats(orchestrator))
    cann_text = sourced_value_text(
        provenance.get("cann_version") if provenance else None,
        "not recorded by this helper",
    )
    profile_date_text = sourced_value_text(
        provenance.get("profile_date") if provenance else None,
        "not recorded by this helper",
    )
    hardware_text = sourced_value_text(provenance.get("hardware", {}).get("summary") if provenance else None, "Ascend 910B")
    profile_command_text = sourced_value_text(
        provenance.get("profile_command") if provenance else None,
        "see reproduction section",
    )
    profile_output_line = profile_outputs_setup_line(provenance)
    if rows:
        metric, signal, value, source = rows[0]
        one_line = (
            f"**One-line read:** Available sourced headline `{metric}` reports "
            f"`{signal}` = `{value}`; source {source}."
        )
    else:
        one_line = "**One-line read:** No sourced headline is available yet."

    lines = [
        f"# {target} Ascend Profiling Report",
        "",
        f"**Target:** {hardware_text}",
        f"**CANN / driver / firmware:** {cann_text}",
        f"**Profile date:** {profile_date_text}",
        f"**Run directory:** `{run_label}`",
        "",
        "## 0. Setup",
        "",
        f"- Harness/application: {tilelang_payload_text(tilelang_context)}",
        f"- Workload shape and dtype: {tilelang_setup_shape(tilelang_context)}",
        "- Tiling path and blockDim: see `OpBasicInfo.csv` when present."
        if op_profile_enabled
        else "- Tiling path and blockDim: op profile disabled for this orchestrated run.",
        f"- Profile command: {profile_command_text}",
        profile_output_line,
        "- Raw artifacts: `reports/`",
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
    lines.extend(tilelang_context_lines(tilelang_context))
    lines.extend(analysis_dimension_lines(summary))
    lines.extend(app_op_correlation_lines(summary))
    for title, groups in ANALYSIS_SECTIONS:
        lines.extend(section_lines(summary, title, groups))
    lines.extend(occupancy_summary_lines(summary))
    lines.extend(roofline_summary_lines(summary))
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
    if not diag_rows:
        lines.append("| No headline diagnosis generated | `analysis/summary.json`; `headlines` | Required profiler artifacts were missing. |")

    lines.extend([""])
    lines.extend(optimization_direction_lines(summary, diag_rows))

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
        "python3 helpers/generate_provenance.py --run-dir <run-dir>",
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
    provenance = load_provenance(run_dir)
    tilelang_context = load_tilelang_context(run_dir)
    out = run_dir / "REPORT.md"
    out.write_text(build_report(summary, run_dir, provenance, tilelang_context), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
