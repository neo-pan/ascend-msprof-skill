#!/usr/bin/env python3
"""Generate an evidence-cited REPORT.md from Ascend profiling analysis."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import evidence_model
from .run_evidence import (
    HeadlineFact,
    LaunchMetadataFact,
    MetricScopeFact,
    ReportFacts,
    ReportTableRowFact,
    RunEvidence,
)


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


def load_or_create_summary(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "analysis" / "summary.json"
    if not summary_path.exists():
        evidence_model.write_evidence_model(run_dir)
    with summary_path.open(encoding="utf-8") as f:
        return json.load(f)


def load_provenance(run_dir: Path) -> dict[str, Any] | None:
    provenance_path = run_dir / "analysis" / "provenance.json"
    if not provenance_path.exists():
        return None
    with provenance_path.open(encoding="utf-8") as f:
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
    return RunEvidence.from_loaded(Path("."), summary).target_name()


def op_basic_launch_metadata_line(fact: LaunchMetadataFact | None, op_profile_enabled: bool) -> str:
    if not op_profile_enabled:
        return "- Tiling path and blockDim: op profile disabled for this orchestrated run."
    if fact is None:
        return "- Tiling path and blockDim: see `OpBasicInfo.csv` when present."
    return launch_metadata_line(fact)


def op_metric_scope_setup_line(scope: MetricScopeFact | None) -> str | None:
    if scope is None:
        return None
    return (
        f"- Op metric scope: {md_escape(scope.value)} "
        f"(source: `{md_escape(scope.artifact)}`; `{md_escape(scope.field_ref)}`)."
    )


def launch_metadata_line(fact: LaunchMetadataFact) -> str:
    details = ", ".join(f"{field}={fmt_compact(value)}" for field, value in fact.fields)
    cited_fields = "`, `".join(field for field, _value in fact.fields)
    return (
        f"- Operator launch metadata: {md_escape(details)} "
        f"(source: `{md_escape(fact.artifact)}`; fields `{md_escape(cited_fields)}`)."
    )


def diagnosis_rows(facts: ReportFacts) -> list[tuple[str, str, str]]:
    rows = []
    for label, fact in facts.diagnosis_headlines:
        value = fmt_value(fact.value)
        source = f"`{fact.artifact}`; `{fact.field_ref}`"
        impact = "Use this sourced signal to choose the next focused inspection step."
        rows.append((f"{label}: {fact.name or 'n/a'} = {value}", source, impact))
    return rows


def section_lines(headlines: tuple[HeadlineFact, ...], title: str) -> list[str]:
    lines = [f"### {title}", ""]
    added = False
    for fact in headlines:
        name = fact.name or "n/a"
        value = fmt_value(fact.value)
        field = fact.field
        field_text = f" field `{field}`" if field else ""
        lines.append(
            f"- `{fact.group}`: `{name}`{field_text} = `{value}` from "
            f"`{fact.artifact}`; evidence `{fact.field_ref}`."
        )
        added = True
    if not added:
        lines.append("- No sourced headline available in `analysis/summary.json`.")
    lines.append("")
    return lines


def analysis_dimension_lines(dimensions: tuple[dict[str, Any], ...]) -> list[str]:
    if not dimensions:
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


def app_op_correlation_lines(facts: tuple[tuple[str, HeadlineFact], ...]) -> list[str]:
    if not facts:
        return []

    lines = [
        "### App/Op Correlation",
        "",
        "| Source | Signal | Value | Evidence |",
        "|---|---|---:|---|",
    ]
    for label, fact in facts:
        source = f"`{fact.artifact}`; `{fact.correlation_field_ref}`"
        lines.append(f"| {md_escape(label)} | {md_escape(fact.signal)} | {md_escape(fmt_value(fact.value))} | {source} |")
    lines.append("")
    return lines


def source_context_text(context: dict[str, Any]) -> str:
    text = (
        f"`{context.get('artifact', 'analysis/simulator_hotspots.json')}` "
        f"`{context.get('field_ref', 'missing')}` "
        f"{md_escape(context.get('role', 'source context'))}"
    )
    if context.get("signal") not in (None, ""):
        text += f" signal={md_escape(context.get('signal'))}"
    if context.get("value") not in (None, ""):
        text += f" value={md_escape(fmt_value(context.get('value')))}"
    return text


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
            hint = item.get("experiment_hint")
            if isinstance(hint, dict):
                inspect_code_area = hint.get("inspect_code_area")
                next_experiment = hint.get("next_experiment")
                expected_profiler_change = hint.get("expected_profiler_change")
                recollect_artifacts = hint.get("recollect_artifacts")
                source_context = hint.get("source_context")
                caveats = hint.get("caveats")
                if inspect_code_area:
                    lines.append(f"   - Inspect code area: {md_escape(inspect_code_area)}")
                if next_experiment:
                    lines.append(f"   - Next experiment: {md_escape(next_experiment)}")
                if expected_profiler_change:
                    lines.append(f"   - Expected profiler change: {md_escape(expected_profiler_change)}")
                if isinstance(recollect_artifacts, list) and recollect_artifacts:
                    lines.append(f"   - Recollect artifacts: {md_escape(', '.join(str(value) for value in recollect_artifacts))}")
                if isinstance(source_context, list) and source_context:
                    context_text = "; ".join(
                        source_context_text(context)
                        for context in source_context
                        if isinstance(context, dict)
                    )
                    if context_text:
                        lines.append(f"   - Source context: {context_text}")
                if isinstance(caveats, list) and caveats:
                    lines.append(f"   - Caveats: {md_escape('; '.join(str(value) for value in caveats))}")
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


def next_collection_action_lines(actions: tuple[dict[str, Any], ...]) -> list[str]:
    if not actions:
        return []
    lines = [
        "### Next Collection Actions",
        "",
        "| Action | Necessity | Target Scope | Estimated Cost | Recommended `--aic-metrics` | Required Artifacts | Confidence | Evidence |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for action in actions:
        evidence_items = action.get("evidence") or []
        evidence_text = "; ".join(
            f"`{item.get('evidence_id', 'evidence')}` `{item.get('artifact', 'missing')}` `{item.get('field_ref', 'missing')}`"
            for item in evidence_items
        )
        lines.append(
            f"| {md_escape(action.get('id', 'collect_more_evidence'))}: {md_escape(action.get('reason', 'Collect more profiler evidence.'))} | "
            f"{md_escape(action.get('necessity', 'blocking'))} | "
            f"{md_escape(action.get('target_scope') or {})} | "
            f"{md_escape(action.get('estimated_cost') or {})} | "
            f"{md_escape(', '.join(action.get('recommended_aic_metrics') or []))} | "
            f"{md_escape(', '.join(action.get('required_artifacts') or []))} | "
            f"{md_escape(action.get('confidence', 'low'))} | "
            f"{evidence_text or '`analysis/summary.json`; `next_collection_actions`'} |"
        )
    lines.append("")
    return lines


def measurement_quality_lines(measurement_quality: dict[str, Any]) -> list[str]:
    frequency = measurement_quality.get("frequency") if isinstance(measurement_quality, dict) else None
    groups = frequency.get("groups") if isinstance(frequency, dict) else None
    if not isinstance(groups, list) or not groups:
        return []
    lines = [
        "### Frequency Measurement Quality",
        "",
        "| Segment | Target | Launches | Current MHz | Rated MHz | Below Rated | Mixed |",
        "|---|---|---:|---|---|---:|---|",
    ]
    for item in groups:
        lines.append(
            f"| {md_escape(item.get('segment'))} | {md_escape(item.get('target'))} | "
            f"{md_escape(item.get('launch_count'))} | "
            f"{md_escape(', '.join(str(value) for value in item.get('current_frequencies_mhz') or []))} | "
            f"{md_escape(', '.join(str(value) for value in item.get('rated_frequencies_mhz') or []))} | "
            f"{md_escape(item.get('below_rated_launch_count'))} | {md_escape(item.get('mixed_frequency'))} |"
        )
    lines.extend(
        [
            "",
            "Frequency is measurement-quality context only; it does not filter samples or change profiler readiness or natural-performance assessment.",
            "",
        ]
    )
    return lines


def evidence_readiness_lines(readiness: dict[str, Any]) -> list[str]:
    if not readiness:
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


def profile_coverage_lines(coverage: dict[str, Any]) -> list[str]:
    if not isinstance(coverage, dict) or not coverage.get("explicit_target"):
        return []
    lines = [
        "### Declared Target Coverage",
        "",
        "| Segment | Expected launches | Observed launches | Count coverage | Duration (us) | Complete metric families |",
        "|---|---:|---:|---|---:|---|",
    ]
    for segment, item in (coverage.get("segments") or {}).items():
        if not isinstance(item, dict):
            continue
        complete_families = [
            family
            for family, details in (item.get("metric_coverage") or {}).items()
            if isinstance(details, dict) and details.get("complete")
        ]
        expected = item.get("expected_total")
        lines.append(
            f"| `{md_escape(segment)}` | "
            f"{md_escape(expected if expected is not None else 'unverified')} | "
            f"{md_escape(item.get('observed_total', 0))} | "
            f"{md_escape(item.get('completeness', 'unverified'))} | "
            f"{md_escape(fmt_compact(item.get('duration_total_us', 0)))} | "
            f"{md_escape(', '.join(complete_families) or 'none')} |"
        )
        if item.get("duration_by_target_us"):
            lines.append(
                f"|  |  |  | per-target duration | "
                f"{md_escape(item.get('duration_by_target_us'))} |  |"
            )
        if item.get("missing_counts") or item.get("over_counts") or item.get("extra_counts"):
            lines.append(
                f"|  |  |  | missing={md_escape(item.get('missing_counts') or {})}; "
                f"over={md_escape(item.get('over_counts') or {})}; "
                f"extra={md_escape(item.get('extra_counts') or {})} |  |  |"
            )
    lines.extend(
        [
            "",
            f"- Measurement boundary: {md_escape(coverage.get('measurement_boundary', 'Application and operator measurements have distinct boundaries.'))}",
            "- Per-launch metrics remain in `analysis/raw_artifact_index.json` and the cited raw CSV artifacts.",
            "",
        ]
    )
    return lines


def evidence_relations_lines(relations: tuple[dict[str, Any], ...]) -> list[str]:
    if not relations:
        return []
    lines = [
        "### Evidence Relations",
        "",
        "| Relation | Target | Confidence | Role | Evidence | Interpretation Boundary |",
        "|---|---|---|---|---|---|",
    ]
    for relation in relations:
        if not isinstance(relation, dict):
            continue
        evidence_items = relation.get("evidence") or []
        evidence_text = "; ".join(
            f"`{item.get('evidence_id', 'evidence')}` `{item.get('artifact', 'missing')}` `{item.get('field_ref', 'missing')}`"
            for item in evidence_items
            if isinstance(item, dict)
        )
        source_context_refs = relation.get("source_context_refs") or []
        context_text = "; ".join(
            f"`{item.get('artifact', 'analysis/simulator_hotspots.json')}` `{item.get('field_ref', 'missing')}`"
            for item in source_context_refs
            if isinstance(item, dict)
        )
        if context_text:
            evidence_text = f"{evidence_text}; context {context_text}" if evidence_text else f"context {context_text}"
        allowed = str(relation.get("allowed_interpretation", "inspect the cited artifacts together")).rstrip(".")
        blocked = str(relation.get("blocked_interpretation", "do not treat this relation as a root-cause claim")).rstrip(".")
        boundary = (
            f"Allowed: {allowed}. "
            f"Blocked: {blocked}."
        )
        lines.append(
            f"| `{md_escape(relation.get('kind', 'evidence_relation'))}` | "
            f"{md_escape(relation.get('target', 'profiled target'))} | "
            f"{md_escape(relation.get('confidence', 'low'))} | "
            f"{md_escape(relation.get('role', 'artifact link'))} | "
            f"{evidence_text or '`analysis/summary.json`; `evidence_relations`'} | "
            f"{md_escape(boundary)} |"
        )
    lines.append("")
    return lines


def render_report_context_table(title: str, rows: tuple[ReportTableRowFact, ...]) -> list[str]:
    if not rows:
        return []
    lines = [
        title,
        "",
        "| Field | Value | Source |",
        "|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {md_escape(row.label)} | {md_escape(fmt_compact(row.value))} | "
            f"`{md_escape(row.artifact)}`; `{md_escape(row.field_ref)}` |"
        )
    lines.append("")
    return lines


def build_report(
    summary: dict[str, Any],
    run_dir: Path,
    provenance: dict[str, Any] | None = None,
    tilelang_context: dict[str, Any] | None = None,
    profile_context: dict[str, Any] | None = None,
) -> str:
    evidence = RunEvidence.from_report_inputs(
        run_dir,
        summary,
        provenance=provenance,
        tilelang_context=tilelang_context,
        profile_context=profile_context,
    )
    return build_report_from_evidence(evidence)


def build_report_from_evidence(evidence: RunEvidence) -> str:
    op_profile_enabled = True
    report = evidence.report_facts(
        ANALYSIS_ARTIFACTS,
        OPTIONAL_ANALYSIS_ARTIFACTS,
        ANALYSIS_SECTIONS,
        op_profile_enabled=op_profile_enabled,
    )
    summary = evidence.summary()
    run_dir = evidence.run_dir
    setup_metadata = report.setup_metadata
    metric_scope = setup_metadata.metric_scope
    target = evidence.target_name()
    run_label = display_run_dir(run_dir)
    rows = [
        (label, signal, fmt_value(value), source)
        for label, signal, value, source in report.headline_rows
    ]
    diag_rows = diagnosis_rows(report)
    analysis_artifacts = report.analysis_artifacts
    caveat_lines = report.caveats
    collection_plan_line = setup_metadata.collection_plan_line
    profile_output_line = setup_metadata.profile_output_line
    launch_metadata_line = op_basic_launch_metadata_line(setup_metadata.launch_metadata, op_profile_enabled)
    metric_scope_line = op_metric_scope_setup_line(metric_scope)
    if rows:
        metric, signal, value, source = rows[0]
        one_line = (
            f"**One-line read:** Available sourced headline `{metric}` reports "
            f"`{signal}` = `{value}`; source {source}."
        )
    else:
        one_line = "**One-line read:** No sourced headline is available yet."

    from .run_assessment import assess_run
    from .candidate_feedback import render_assessment_markdown
    assessment_lines = render_assessment_markdown(assess_run(evidence))
    setup_context = report.setup_context
    lines = [
        f"# {target} Ascend Profiling Report",
        "",
        f"**Target:** {setup_metadata.hardware_text}",
        f"**CANN / driver / firmware:** {setup_metadata.cann_text}",
        f"**Profile date:** {setup_metadata.profile_date_text}",
        f"**Run directory:** `{run_label}`",
        "",
        *assessment_lines,
        "",
        "## 0. Setup",
        "",
        f"- Harness/application: {setup_context.application_text}",
        f"- Workload shape and dtype: {setup_context.workload_text}",
        launch_metadata_line,
        f"- Profile command: {setup_metadata.profile_command_text}",
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
        lines.insert(lines.index(f"- Profile command: {setup_metadata.profile_command_text}"), metric_scope_line)
    if collection_plan_line:
        lines.insert(lines.index(profile_output_line), collection_plan_line)
    for metric, signal, value, source in rows:
        lines.append(f"| {md_escape(metric)} | {md_escape(signal)} | {md_escape(value)} | {source} |")
    if not rows:
        lines.append("| No headline available | n/a | n/a | `analysis/summary.json`; `headlines` |")
    lines.extend(["", one_line, ""])

    lines.append("## 2. Analysis")
    lines.append("")
    if report.profile_context_rows or report.tilelang_context_rows:
        lines.extend(["Caller context below is not validated natural measurement evidence.", ""])
    lines.extend(render_report_context_table("### Profile Harness Context", report.profile_context_rows))
    lines.extend(render_report_context_table("### TileLang Benchmark Context", report.tilelang_context_rows))
    lines.extend(profile_coverage_lines(summary.get("profile_coverage")))
    lines.extend(measurement_quality_lines(summary.get("measurement_quality") or {}))
    lines.extend(analysis_dimension_lines(report.analysis_dimensions))
    lines.extend(evidence_readiness_lines(report.evidence_readiness))
    lines.extend(evidence_relations_lines(report.evidence_relations))
    lines.extend(app_op_correlation_lines(report.correlation_headlines))
    for title, headlines in report.section_headlines:
        lines.extend(section_lines(headlines, title))
    lines.extend(occupancy_summary_lines(summary))
    lines.extend(roofline_summary_lines(summary))
    lines.extend(performance_summary_lines(summary))
    if op_profile_enabled:
        lines.extend(next_collection_action_lines(report.pending_collection_actions))
    lines.extend(["### Simulator Hotspots", ""])
    if report.simulator_hotspots.structured_model_present:
        lines.append("- Structured simulator hotspot model is available at `analysis/simulator_hotspots.json`.")
    else:
        lines.append("- No structured simulator hotspot model is available; run the analyzer to generate it.")
    if report.simulator_hotspots.markdown_summary_present:
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
    evidence = RunEvidence.load_report(run_dir, summary)
    out = run_dir / "REPORT.md"
    out.write_text(build_report_from_evidence(evidence), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
