#!/usr/bin/env python3
"""Generate an evidence-cited REPORT.md from Ascend profiling analysis."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import analyze_msprof_outputs
from .metric_scope_policy import (
    command_metric_scope,
    is_msprof_op_command,
    metric_scope_policy,
    warning_group,
)


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

ANALYSIS_ARTIFACTS = [
    "summary.json",
    "key_metrics.txt",
    "raw_artifact_index.json",
    "timeline.txt",
    "simulator_hotspots.json",
    "simulator_hotspots.txt",
]
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
        analyze_msprof_outputs.main(["--run-dir", str(run_dir)])
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


def load_profile_context(run_dir: Path) -> dict[str, Any] | None:
    context_path = run_dir / "analysis" / "profile_context.json"
    if not context_path.exists():
        return None
    with context_path.open(encoding="utf-8") as f:
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
    followups = segments.get("followups")
    if isinstance(followups, dict):
        for action_id in sorted(followups):
            segment = followups.get(action_id)
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
                rendered.append(f"followups.{action_id}: {', '.join(parts)}")
    if not rendered:
        return None
    return "; ".join(rendered)


def profile_outputs_setup_line(provenance: dict[str, Any] | None) -> str:
    segmented = profile_output_segments_text(provenance)
    if segmented:
        return f"- Profile outputs: {segmented}"
    return f"- Profile output: {profile_outputs_text(provenance)}"


def op_metric_scope(run_dir: Path) -> dict[str, str] | None:
    for name in ["command_msprof_op.txt", "command_msprof.txt"]:
        path = run_dir / "logs" / name
        if not path.exists():
            continue
        command = path.read_text(encoding="utf-8", errors="replace")
        if name == "command_msprof.txt" and not is_msprof_op_command(command):
            continue
        scope = command_metric_scope(command)
        if scope:
            return {
                "value": scope,
                "artifact": f"logs/{name}",
                "field_ref": "--aic-metrics",
            }
    return None


def op_metric_scope_setup_line(scope: dict[str, str] | None) -> str | None:
    if not scope:
        return None
    return (
        f"- Op metric scope: {md_escape(scope.get('value'))} "
        f"(source: `{md_escape(scope.get('artifact'))}`; `{md_escape(scope.get('field_ref'))}`)."
    )


def summary_metric_scope(summary: dict[str, Any]) -> dict[str, str] | None:
    scope = summary.get("metric_scope")
    if not isinstance(scope, dict) or not scope.get("value"):
        return None
    return {
        "value": str(scope.get("value")),
        "artifact": str(scope.get("artifact") or "analysis/summary.json"),
        "field_ref": str(scope.get("field_ref") or "metric_scope.value"),
    }


def op_basic_launch_metadata_line(summary: dict[str, Any], op_profile_enabled: bool) -> str:
    if not op_profile_enabled:
        return "- Tiling path and blockDim: op profile disabled for this orchestrated run."
    item = summary.get("headlines", {}).get("op_basic_info")
    if not isinstance(item, dict):
        return "- Tiling path and blockDim: see `OpBasicInfo.csv` when present."
    row = item.get("first_row") or {}
    if not isinstance(row, dict) or not row:
        return "- Tiling path and blockDim: see `OpBasicInfo.csv` when present."
    normalized = {str(key).strip().lower(): str(key) for key in row}
    fields = []
    for wanted in ["Op Type", "Block Dim", "Mix Block Dim", "Current Freq", "Rated Freq"]:
        field = normalized.get(wanted.strip().lower())
        if not field:
            continue
        value = row.get(field)
        if value in (None, ""):
            continue
        fields.append((field, value))
    if not fields:
        return "- Tiling path and blockDim: see `OpBasicInfo.csv` when present."
    details = ", ".join(f"{field}={fmt_compact(value)}" for field, value in fields)
    cited_fields = "`, `".join(field for field, _value in fields)
    return (
        f"- Operator launch metadata: {md_escape(details)} "
        f"(source: `{md_escape(item.get('file', 'missing'))}`; fields `{md_escape(cited_fields)}`)."
    )


def provenance_caveats(provenance: dict[str, Any] | None) -> list[str]:
    if not provenance:
        return []
    return [f"Provenance warning: {warning}" for warning in provenance.get("warnings", [])]


def tilelang_caveats(tilelang_context: dict[str, Any] | None) -> list[str]:
    if not tilelang_context:
        return []
    return [f"TileLang context warning: {warning}" for warning in tilelang_context.get("warnings", [])]


def profile_context_caveats(profile_context: dict[str, Any] | None) -> list[str]:
    if not profile_context:
        return []
    return [f"Profile context warning: {warning}" for warning in profile_context.get("warnings", [])]


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
            tiling_field = signal.get("tiling_field")
            tiling_value = signal.get("tiling_value")
            tiling_field_ref = signal.get("tiling_field_ref")

            def add_row(row_signal_name: Any, row_value: Any, row_field_ref: Any) -> None:
                formatted_value = fmt_value(row_value)
                rendered_signal = (
                    row_signal_name if formatted_value == "n/a" else f"{row_signal_name} = {formatted_value}"
                )
                evidence = f"`{signal.get('artifact', 'missing')}`; `{row_field_ref}`"
                lines.append(
                    f"| {md_escape(title)} | {md_escape(status)} | {md_escape(rendered_signal)} | {evidence} |"
                )

            if value is None and tiling_field and tiling_value is not None:
                add_row(f"{str(signal_name).split(' / ', 1)[0]} / {tiling_field}", tiling_value, tiling_field_ref or field_ref)
                continue
            add_row(signal_name, value, field_ref)
            if tiling_field and tiling_value is not None:
                add_row(f"{str(signal_name).split(' / ', 1)[0]} / {tiling_field}", tiling_value, tiling_field_ref or field_ref)
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
            direction_id = item.get("id") or "unidentified_direction"
            lines.append(
                f"{rank}. {md_escape(item.get('title', 'Inspection Direction'))} "
                f"(`{md_escape(direction_id)}`)"
            )
            lines.append(f"   - Action: {md_escape(item.get('action', 'Inspect the cited evidence before changing kernel code.'))}")
            lines.append(f"   - Impact basis: {md_escape(item.get('impact_basis', 'Evidence cited in analysis/summary.json.'))}")
            lines.append(f"   - Confidence: {md_escape(item.get('confidence', 'low'))}; effort: {md_escape(item.get('effort', 'medium'))}")
            requires = item.get("requires_artifacts") or []
            missing = item.get("missing_artifacts") or []
            if requires:
                lines.append(f"   - Requires artifacts: {md_escape(', '.join(str(value) for value in requires))}")
            if missing:
                lines.append(f"   - Missing artifacts: {md_escape(', '.join(str(value) for value in missing))}")
            evidence_items = item.get("evidence") or []
            if evidence_items:
                evidence_text = "; ".join(
                    f"`{evidence.get('evidence_id', 'evidence')}` "
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


def performance_summary_lines(summary: dict[str, Any]) -> list[str]:
    performance = summary.get("stdout_sections", {}).get("performance_summary")
    if not performance:
        return []
    lines = [
        "### CANN Performance Summary",
        "",
        "| Ordinal | Message | Source |",
        "|---:|---|---|",
    ]
    source = performance.get("source", "missing")
    for message in performance.get("messages", []):
        lines.append(
            f"| {md_escape(message.get('ordinal'))} | "
            f"{md_escape(message.get('message'))} | "
            f"`{md_escape(message.get('source') or source)}` |"
        )
    lines.append("")
    return lines


def next_collection_action_lines(summary: dict[str, Any]) -> list[str]:
    actions = summary.get("next_collection_actions")
    if not isinstance(actions, list) or not actions:
        return []
    lines = [
        "### Next Collection Actions",
        "",
        "| Action | Recommended `--aic-metrics` | Required Artifacts | Confidence | Evidence |",
        "|---|---|---|---|---|",
    ]
    for action in actions:
        evidence_items = action.get("evidence") or []
        evidence_text = "; ".join(
            f"`{item.get('evidence_id', 'evidence')}` `{item.get('artifact', 'missing')}` `{item.get('field_ref', 'missing')}`"
            for item in evidence_items
        )
        lines.append(
            f"| {md_escape(action.get('id', 'collect_more_evidence'))}: {md_escape(action.get('reason', 'Collect more profiler evidence.'))} | "
            f"{md_escape(', '.join(action.get('recommended_aic_metrics') or []))} | "
            f"{md_escape(', '.join(action.get('required_artifacts') or []))} | "
            f"{md_escape(action.get('confidence', 'low'))} | "
            f"{evidence_text or '`analysis/summary.json`; `next_collection_actions`'} |"
        )
    lines.append("")
    return lines


def evidence_readiness_lines(summary: dict[str, Any]) -> list[str]:
    readiness = summary.get("evidence_readiness")
    if not isinstance(readiness, dict):
        return []
    available = ", ".join(str(item) for item in readiness.get("available_evidence_families") or []) or "none"
    missing = ", ".join(str(item) for item in readiness.get("missing_evidence_families") or []) or "none"
    allowed = readiness.get("allowed_claims") or []
    blocked = readiness.get("blocked_claims") or []
    followups = readiness.get("recommended_followups") or []
    binaries = readiness.get("unparsed_binary_artifacts") or []
    lines = [
        "### Evidence Readiness",
        "",
        f"- Level: `{md_escape(readiness.get('level', 'insufficient'))}`.",
        f"- Available evidence families: {md_escape(available)}.",
        f"- Missing evidence families: {md_escape(missing)}.",
    ]
    if binaries:
        rendered = ", ".join(
            f"{item.get('artifact')} ({item.get('known_role', 'unparsed')})"
            for item in binaries[:5]
            if isinstance(item, dict)
        )
        if len(binaries) > 5:
            rendered = f"{rendered}, ..."
        lines.append(f"- Unparsed binary artifacts preserved but not used for diagnosis: {md_escape(rendered)}.")
    if followups:
        action = followups[0]
        metrics = ", ".join(str(item) for item in action.get("recommended_aic_metrics") or []) or "n/a"
        lines.append(
            f"- Next minimal collection action: `{md_escape(action.get('id', 'collect_more_evidence'))}` "
            f"with `--aic-metrics` {md_escape(metrics)}."
        )
    if allowed:
        lines.append(f"- Allowed claims: {md_escape('; '.join(str(item) for item in allowed[:4]))}.")
    if blocked:
        lines.append(f"- Blocked claims: {md_escape('; '.join(str(item) for item in blocked[:4]))}.")
    lines.append("")
    return lines


def caveats(
    summary: dict[str, Any],
    run_dir: Path,
    provenance: dict[str, Any] | None = None,
    tilelang_context: dict[str, Any] | None = None,
    profile_context: dict[str, Any] | None = None,
    op_profile_enabled: bool = True,
    op_metric_scope_value: str | None = None,
) -> list[str]:
    out = []
    policy = metric_scope_policy(op_metric_scope_value)
    for warning in summary.get("warnings", []):
        if not op_profile_enabled and warning.startswith(
            (
                "missing op_basic_info:",
                "missing pipe_utilization:",
                "missing arithmetic_utilization:",
                "missing l2_cache:",
                "missing memory:",
                "missing resource_conflict:",
            )
        ):
            continue
        group = warning_group(str(warning))
        if (
            policy
            and policy.suppress_optional_missing_caveats
            and group in policy.optional_artifacts
        ):
            continue
        if (
            policy
            and policy.suppress_optional_missing_caveats
            and group
            and group not in policy.required_artifacts
            and group not in policy.optional_artifacts
            and group in {
                "pipe_utilization",
                "arithmetic_utilization",
                "l2_cache",
                "memory",
                "resource_conflict",
            }
        ):
            continue
        out.append(f"Analyzer warning: {warning}")
    for name in OPTIONAL_ANALYSIS_ARTIFACTS:
        if not (run_dir / "analysis" / name).exists():
            out.append(f"Optional analysis artifact missing: analysis/{name}")
    out.extend(provenance_caveats(provenance))
    out.extend(tilelang_caveats(tilelang_context))
    out.extend(profile_context_caveats(profile_context))
    return out


def profile_context_lines(profile_context: dict[str, Any] | None) -> list[str]:
    if not profile_context:
        return []

    profile_harness = profile_context.get("profile_harness") or {}
    benchmark = profile_context.get("benchmark") or {}
    workload = benchmark.get("workload") or {}
    candidate = benchmark.get("candidate") or {}
    correctness = benchmark.get("correctness") or {}
    sources = profile_context.get("sources") or {}
    rows = []
    manifest_source = sources.get("profile_harness_manifest")
    if isinstance(manifest_source, dict):
        rows.append(("Harness manifest", manifest_source.get("artifact"), "sources.profile_harness_manifest.artifact"))
        rows.append(("Harness manifest sha256", manifest_source.get("sha256"), "sources.profile_harness_manifest.sha256"))
    application_source = sources.get("application")
    if isinstance(application_source, dict):
        rows.append(("Application", application_source.get("artifact"), "sources.application.artifact"))
        rows.append(("Application sha256", application_source.get("sha256"), "sources.application.sha256"))

    harness_workload = profile_harness.get("workload") if isinstance(profile_harness, dict) else None
    if harness_workload not in (None, "", [], {}):
        rows.append(("Harness workload", harness_workload, "profile_harness.workload"))
    if isinstance(profile_harness, dict) and profile_harness.get("jit_config") not in (None, "", [], {}):
        rows.append(("Harness JIT config", profile_harness.get("jit_config"), "profile_harness.jit_config"))

    if sources.get("verify_json"):
        rows.append(("Verify JSON", sources["verify_json"].get("artifact"), "sources.verify_json.artifact"))
        rows.append(("Workload id", workload.get("id"), "benchmark.workload.id"))
        rows.append(("Shape", workload.get("shape"), "benchmark.workload.shape"))
        rows.append(("Dtype", workload.get("dtype"), "benchmark.workload.dtype"))
        rows.append(("Case count", workload.get("case_count"), "benchmark.workload.case_count"))
        rows.append(("Compiled", candidate.get("compiled"), "benchmark.candidate.compiled"))
        rows.append(("Candidate runtime", candidate.get("runtime"), "benchmark.candidate.runtime"))
        rows.append(("Runtime stats", candidate.get("runtime_stats"), "benchmark.candidate.runtime_stats"))
        rows.append(("Reference runtime", candidate.get("ref_runtime"), "benchmark.candidate.ref_runtime"))
        rows.append(("Speedup", candidate.get("speedup"), "benchmark.candidate.speedup"))
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

    lines = [
        "### Profile Harness Context",
        "",
        "| Field | Value | Source |",
        "|---|---|---|",
    ]
    for label, value, source in rows:
        lines.append(
            f"| {md_escape(label)} | {md_escape(fmt_compact(value))} | "
            f"`analysis/profile_context.json`; `{source}` |"
        )
    lines.append("")
    return lines


def profile_application_text(profile_context: dict[str, Any] | None, tilelang_context: dict[str, Any] | None) -> str:
    if profile_context:
        sources = profile_context.get("sources") or {}
        manifest = sources.get("profile_harness_manifest")
        application = sources.get("application") or {}
        if isinstance(manifest, dict) and manifest.get("artifact"):
            return (
                f"profile harness manifest `{manifest.get('artifact')}` and application "
                f"`{application.get('artifact', 'not recorded')}` "
                "(source: `analysis/profile_context.json`; `sources.profile_harness_manifest.artifact`, "
                "`sources.application.artifact`)."
            )
        if isinstance(application, dict) and application.get("artifact"):
            return (
                f"application `{application.get('artifact')}` "
                "(source: `analysis/profile_context.json`; `sources.application.artifact`)."
            )
        return "recorded in `analysis/profile_context.json`."
    return tilelang_payload_text(tilelang_context)


def profile_workload_text(profile_context: dict[str, Any] | None, tilelang_context: dict[str, Any] | None) -> str:
    if not profile_context:
        return tilelang_setup_shape(tilelang_context)
    benchmark_workload = profile_context.get("benchmark", {}).get("workload", {})
    if benchmark_workload:
        shape = fmt_compact(benchmark_workload.get("shape"))
        dtype = fmt_compact(benchmark_workload.get("dtype"))
        case_count = fmt_compact(benchmark_workload.get("case_count"))
        return (
            f"{shape}, dtype {dtype}, cases {case_count} "
            "(context only; source: `analysis/profile_context.json`; `benchmark.workload`)."
        )
    harness_workload = profile_context.get("profile_harness", {}).get("workload")
    if harness_workload not in (None, "", [], {}):
        return (
            f"{fmt_compact(harness_workload)} "
            "(context only; source: `analysis/profile_context.json`; `profile_harness.workload`)."
        )
    return "not recorded by this helper."


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
    profile_context: dict[str, Any] | None = None,
) -> str:
    op_profile_enabled = True
    metric_scope = op_metric_scope(run_dir) or summary_metric_scope(summary)
    target = target_name(summary)
    run_label = display_run_dir(run_dir)
    rows = headline_rows(summary)
    diag_rows = diagnosis_rows(summary)
    analysis_artifacts = first_existing_analysis(run_dir, ANALYSIS_ARTIFACTS)
    if provenance:
        analysis_artifacts.append("`analysis/provenance.json`")
    if tilelang_context:
        analysis_artifacts.append("`analysis/tilelang_context.json`")
    if profile_context:
        analysis_artifacts.append("`analysis/profile_context.json`")
    caveat_lines = caveats(
        summary,
        run_dir,
        provenance,
        tilelang_context,
        profile_context,
        op_profile_enabled,
        metric_scope.get("value") if metric_scope else None,
    )
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
    launch_metadata_line = op_basic_launch_metadata_line(summary, op_profile_enabled)
    metric_scope_line = op_metric_scope_setup_line(metric_scope)
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
        f"- Harness/application: {profile_application_text(profile_context, tilelang_context)}",
        f"- Workload shape and dtype: {profile_workload_text(profile_context, tilelang_context)}",
        launch_metadata_line,
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
    if metric_scope_line:
        lines.insert(lines.index(f"- Profile command: {profile_command_text}"), metric_scope_line)
    for metric, signal, value, source in rows:
        lines.append(f"| {md_escape(metric)} | {md_escape(signal)} | {md_escape(value)} | {source} |")
    if not rows:
        lines.append("| No headline available | n/a | n/a | `analysis/summary.json`; `headlines` |")
    lines.extend(["", one_line, ""])

    lines.append("## 2. Analysis")
    lines.append("")
    lines.extend(profile_context_lines(profile_context))
    lines.extend(tilelang_context_lines(tilelang_context))
    lines.extend(analysis_dimension_lines(summary))
    lines.extend(evidence_readiness_lines(summary))
    lines.extend(app_op_correlation_lines(summary))
    for title, groups in ANALYSIS_SECTIONS:
        lines.extend(section_lines(summary, title, groups))
    lines.extend(occupancy_summary_lines(summary))
    lines.extend(roofline_summary_lines(summary))
    lines.extend(performance_summary_lines(summary))
    if op_profile_enabled:
        lines.extend(next_collection_action_lines(summary))
    lines.extend(["### Simulator Hotspots", ""])
    if (run_dir / "analysis" / "simulator_hotspots.json").exists():
        lines.append("- Structured simulator hotspot model is available at `analysis/simulator_hotspots.json`.")
    else:
        lines.append("- No structured simulator hotspot model is available; run the analyzer to generate it.")
    if (run_dir / "analysis" / "simulator_hotspots.txt").exists():
        lines.append("- Optional simulator hotspot Markdown summary is available at `analysis/simulator_hotspots.txt`.")
    else:
        lines.append("- No simulator hotspot Markdown summary is available; this is optional for non-simulator runs.")
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
        "ascend-msprof provenance --run-dir <run-dir>",
        "ascend-msprof analyze --run-dir <run-dir>",
        "ascend-msprof report --run-dir <run-dir>",
        "```",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    args = ap.parse_args(argv)

    run_dir = args.run_dir.resolve()
    summary = load_or_create_summary(run_dir)
    provenance = load_provenance(run_dir)
    tilelang_context = load_tilelang_context(run_dir)
    profile_context = load_profile_context(run_dir)
    out = run_dir / "REPORT.md"
    out.write_text(build_report(summary, run_dir, provenance, tilelang_context, profile_context), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
