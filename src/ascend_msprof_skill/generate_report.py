#!/usr/bin/env python3
"""Generate an evidence-cited REPORT.md from Ascend profiling analysis."""
from __future__ import annotations
from .provenance_types import Provenance, load_provenance
from .caller_context import CallerContext

from .coverage_types import ProfileCoverage
from .summary_types import MeasurementQuality

import argparse
import json
from pathlib import Path
from typing import Any

from . import evidence_model
from .readiness_types import CollectionAction, EvidenceReadiness
from .analysis_types import AnalysisDimension, EvidenceRelation
from .summary_types import Summary, StdoutSections, load_summary
from .metric_scope_policy import APP_TIMING_ARTIFACTS
from .run_evidence import (
    HeadlineFact,
    LaunchMetadataFact,
    MetricScopeFact,
    ReportFacts,
    ReportTableRowFact,
    RunEvidence,
)


ANALYSIS_SECTIONS = [
    ("Duration And Calls", list(APP_TIMING_ARTIFACTS)),
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


def load_or_create_summary(run_dir: Path) -> Summary:
    summary_path = run_dir / "analysis" / "summary.json"
    if not summary_path.exists():
        evidence_model.write_evidence_model(run_dir)
    from .ascend_profile_utils import read_json
    return load_summary(read_json(summary_path))


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


def target_name(summary: Summary | None) -> str:
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
        source = f"`{md_escape(fact.artifact)}`; `{md_escape(fact.correlation_field_ref)}`"
        impact = "Descriptive observation within the recorded target and metric scope; not a bottleneck finding."
        if fact.group == "api_statistic":
            impact = "Host/runtime API timing context; not standalone device kernel duration or bottleneck evidence."
        elif fact.group == "op_statistic":
            impact = "Aggregate operator-type timing; not an individual kernel invocation or bottleneck finding."
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


def analysis_dimension_lines(dimensions: tuple[AnalysisDimension, ...]) -> list[str]:
    if not dimensions:
        return []
    lines = [
        "### Analysis Dimensions",
        "",
        "| Dimension | Status | Signal | Evidence |",
        "|---|---|---|---|",
    ]
    for dimension in dimensions:
        title = dimension.title or dimension.id or "n/a"
        status = dimension.status or "insufficient"
        signals = dimension.signals or []
        if not signals:
            lines.append(f"| {md_escape(title)} | {md_escape(status)} | n/a | `analysis/summary.json`; `analysis_dimensions.{md_escape(dimension.id)}` |")
            continue
        for signal in signals[:5]:
            signal_name = signal.signal or "n/a"
            value = signal.value
            field_ref = signal.field_ref
            tiling_field = signal.tiling_field
            tiling_value = signal.tiling_value
            tiling_field_ref = signal.tiling_field_ref

            def add_row(row_signal_name: Any, row_value: Any, row_field_ref: Any) -> None:
                formatted_value = fmt_value(row_value)
                rendered_signal = (
                    row_signal_name if formatted_value == "n/a" else f"{row_signal_name} = {formatted_value}"
                )
                evidence = f"`{signal.artifact}`; `{row_field_ref}`"
                lines.append(
                    f"| {md_escape(title)} | {md_escape(status)} | {md_escape(rendered_signal)} | {evidence} |"
                )

            if value is None and signal.metadata_field and not tiling_field:
                add_row(f"{str(signal_name).split(' / ', 1)[0]} / {signal.metadata_field}", signal.metadata_value, field_ref)
                continue
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


def occupancy_summary_lines(summary: Summary | None) -> list[str]:
    occupancy = (summary.stdout_sections if summary is not None else StdoutSections()).occupancy_summary
    if not occupancy:
        return []
    lines = [
        "### Occupancy Summary",
        "",
        "| Ordinal | Message | Source |",
        "|---:|---|---|",
    ]
    source = occupancy.source
    for message in occupancy.messages:
        lines.append(
            f"| {md_escape(message.ordinal)} | "
            f"{md_escape(message.message)} | "
            f"`{md_escape(source)}` |"
        )
    lines.append("")
    return lines


def roofline_summary_lines(summary: Summary | None) -> list[str]:
    roofline = (summary.stdout_sections if summary is not None else StdoutSections()).roofline_summary
    if not roofline:
        return []
    lines = [
        "### RoofLine Summary",
        "",
        "| Message | Source |",
        "|---|---|",
    ]
    source = roofline.source
    for message in roofline.messages:
        lines.append(
            f"| {md_escape(message.message)} | "
            f"`{md_escape(source)}` |"
        )
    lines.append("")
    return lines


def performance_summary_lines(summary: Summary | None) -> list[str]:
    performance = (summary.stdout_sections if summary is not None else StdoutSections()).performance_summary
    if not performance:
        return []
    lines = [
        "### CANN Performance Summary",
        "",
        "| Ordinal | Message | Source |",
        "|---:|---|---|",
    ]
    source = performance.source
    for message in performance.messages:
        lines.append(
            f"| {md_escape(message.ordinal)} | "
            f"{md_escape(message.message)} | "
            f"`{md_escape(source)}` |"
        )
    lines.append("")
    return lines


def next_collection_action_lines(actions: tuple[CollectionAction, ...]) -> list[str]:
    if not actions:
        return []
    lines = [
        "### Next Collection Actions",
        "",
        "| Action | Necessity | Target Scope | Estimated Cost | Recommended `--aic-metrics` | Required Artifacts | Confidence | Evidence |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for action in actions:
        evidence_items = action.evidence or []
        evidence_text = "; ".join(
            f"`{item.evidence_id}` `{item.artifact}` `{item.field_ref}`"
            for item in evidence_items
        )
        lines.append(
            f"| {md_escape(action.id)}: {md_escape(action.reason)} | "
            f"{md_escape(action.necessity)} | "
            f"{md_escape(action.target_scope.model_dump(mode='json', exclude_unset=True))} | "
            f"{md_escape(action.estimated_cost.model_dump(mode='json'))} | "
            f"{md_escape(', '.join(action.recommended_aic_metrics or []))} | "
            f"{md_escape(', '.join(action.required_artifacts or []))} | "
            f"{md_escape(action.confidence)} | "
            f"{evidence_text or '`analysis/summary.json`; `next_collection_actions`'} |"
        )
    lines.append("")
    return lines


def measurement_quality_lines(measurement_quality: MeasurementQuality | None) -> list[str]:
    if measurement_quality is None or not measurement_quality.frequency.groups:
        return []
    groups = measurement_quality.frequency.groups
    lines = [
        "### Frequency Measurement Quality",
        "",
        "| Segment | Target | Launches | Current MHz | Rated MHz | Below Rated | Mixed |",
        "|---|---|---:|---|---|---:|---|",
    ]
    for item in groups:
        lines.append(
            f"| {md_escape(item.segment)} | {md_escape(item.target)} | "
            f"{md_escape(item.launch_count)} | "
            f"{md_escape(', '.join(str(value) for value in item.current_frequencies_mhz or []))} | "
            f"{md_escape(', '.join(str(value) for value in item.rated_frequencies_mhz or []))} | "
            f"{md_escape(item.below_rated_launch_count)} | {md_escape(item.mixed_frequency)} |"
        )
    lines.extend(
        [
            "",
            "Frequency is measurement-quality context only; it does not filter samples or change profiler readiness or natural-performance assessment.",
            "",
        ]
    )
    return lines


def evidence_readiness_lines(readiness: EvidenceReadiness | None) -> list[str]:
    if not readiness:
        return []
    available = ", ".join(str(item) for item in readiness.available_evidence_families or []) or "none"
    missing = ", ".join(str(item) for item in readiness.missing_evidence_families or []) or "none"
    allowed = readiness.allowed_claims or []
    blocked = readiness.blocked_claims or []
    followups = readiness.recommended_followups or []
    binaries = readiness.unparsed_binary_artifacts or []
    lines = [
        "### Evidence Readiness",
        "",
        f"- Level: `{md_escape(readiness.level)}`.",
        f"- Available evidence families: {md_escape(available)}.",
        f"- Missing evidence families: {md_escape(missing)}.",
    ]
    if binaries:
        rendered = ", ".join(
            f"{item.artifact} ({item.known_role})"
            for item in binaries[:5]
        )
        if len(binaries) > 5:
            rendered = f"{rendered}, ..."
        lines.append(f"- Unparsed binary artifacts preserved but not used for diagnosis: {md_escape(rendered)}.")
    for action in followups:
        metrics = ", ".join(str(item) for item in action.recommended_aic_metrics or [])
        metric_text = f" with `--aic-metrics` {md_escape(metrics)}" if metrics else ""
        lines.append(
            f"- Conditional collection option: `{md_escape(action.id)}`"
            f"{metric_text}."
        )
    if allowed:
        lines.append(f"- Allowed claims: {md_escape('; '.join(str(item) for item in allowed[:4]))}.")
    if blocked:
        lines.append(f"- Blocked claims: {md_escape('; '.join(str(item) for item in blocked[:4]))}.")
    lines.append("")
    return lines


def profile_coverage_lines(coverage: ProfileCoverage | None) -> list[str]:
    if coverage is None or not coverage.explicit_target:
        return []
    lines = [
        "### Declared Target Coverage",
        "",
        "| Segment | Expected launches | Observed launches | Count coverage | Duration (us) | Complete metric families |",
        "|---|---:|---:|---|---:|---|",
    ]
    for segment, item in coverage.segments.items():
        complete_families = [
            family
            for family, details in item.metric_coverage.items()
            if details.complete
        ]
        expected = item.expected_total
        lines.append(
            f"| `{md_escape(segment)}` | "
            f"{md_escape(expected if expected is not None else 'unverified')} | "
            f"{md_escape(item.observed_total)} | "
            f"{md_escape(item.completeness)} | "
            f"{md_escape(fmt_compact(item.duration_total_us))} | "
            f"{md_escape(', '.join(complete_families) or 'none')} |"
        )
        if item.duration_by_target_us:
            lines.append(
                f"|  |  |  | per-target duration | "
                f"{md_escape(item.duration_by_target_us)} |  |"
            )
        if item.missing_counts or item.over_counts or item.extra_counts:
            lines.append(
                f"|  |  |  | missing={md_escape(item.missing_counts or {})}; "
                f"over={md_escape(item.over_counts or {})}; "
                f"extra={md_escape(item.extra_counts or {})} |  |  |"
            )
    lines.extend(
        [
            "",
            f"- Measurement boundary: {md_escape(coverage.measurement_boundary)}",
            "- Per-launch metrics remain in `analysis/raw_artifact_index.json` and the cited raw CSV artifacts.",
            "",
        ]
    )
    return lines


def evidence_relations_lines(relations: tuple[EvidenceRelation, ...]) -> list[str]:
    if not relations:
        return []
    lines = [
        "### Evidence Relations",
        "",
        "| Relation | Target | Confidence | Role | Evidence | Interpretation Boundary |",
        "|---|---|---|---|---|---|",
    ]
    for relation in relations:
        evidence_items = relation.evidence or []
        evidence_text = "; ".join(
            f"`{item.evidence_id}` `{item.artifact}` `{item.field_ref}`"
            for item in evidence_items
        )
        source_context_refs = relation.source_context_refs or []
        context_text = "; ".join(
            f"`{item.artifact}` `{item.field_ref}`"
            for item in source_context_refs
        )
        if context_text:
            evidence_text = f"{evidence_text}; context {context_text}" if evidence_text else f"context {context_text}"
        allowed = str(relation.allowed_interpretation).rstrip(".")
        blocked = str(relation.blocked_interpretation).rstrip(".")
        boundary = (
            f"Allowed: {allowed}. "
            f"Blocked: {blocked}."
        )
        lines.append(
            f"| `{md_escape(relation.kind)}` | "
            f"{md_escape(relation.target)} | "
            f"{md_escape(relation.confidence)} | "
            f"{md_escape(relation.role)} | "
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
    summary: Summary | None,
    run_dir: Path,
    provenance: Provenance | None = None,
    tilelang_context: CallerContext | dict[str, Any] | None = None,
    profile_context: CallerContext | dict[str, Any] | None = None,
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
    primary = report.primary_headline
    if primary is not None:
        source = f"`{md_escape(primary.artifact)}`; `{md_escape(primary.correlation_field_ref)}`"
        one_line = (
            f"**One-line read:** Available sourced headline `{md_escape(primary.label or primary.group)}` reports "
            f"`{md_escape(primary.signal)}` = `{md_escape(fmt_value(primary.value))}`; source {source}."
        )
    elif evidence.ambiguous_timing():
        one_line = "**One-line read:** Valid application timing observations span multiple sources or scopes; no unique headline was selected."
    elif evidence.ambiguous_operator_groups():
        one_line = "**One-line read:** Valid operator observations span multiple sources or scopes; no unique headline was selected."
    else:
        one_line = "**One-line read:** No finite sourced headline is available yet."

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
    lines.extend(profile_coverage_lines(summary.profile_coverage if summary is not None else None))
    lines.extend(measurement_quality_lines(evidence.measurement_quality()))
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
        "## 3. Observations",
        "",
        "| Observation | Evidence | Interpretation boundary |",
        "|---|---|---|",
    ])
    for finding, evidence_ref, impact in diag_rows:
        lines.append(f"| {md_escape(finding)} | {evidence_ref} | {md_escape(impact)} |")
    if evidence.ambiguous_timing():
        lines.append("| Valid application timing observations span multiple sources or scopes | `analysis/summary.json`; `headlines` | No unique headline was selected. Inspect per-artifact observations; coverage and attribution remain separate checks. |")
    elif not diag_rows:
        sources = ", ".join(f"`headlines.{group}`" for group in APP_TIMING_ARTIFACTS)
        lines.append(f"| No finite application timing headline was parsed | `analysis/summary.json`; {sources} | Inspect raw artifacts and parser status for missing, empty or invalid inputs; target attribution and coverage require separate checks. |")

    lines.extend([""])

    lines.extend([
        "",
        "## 4. Assessment Limits",
        "",
        "- Observations are limited to the recorded target, collection scope and comparable measurement conditions.",
    ])
    if caveat_lines:
        for caveat in caveat_lines:
            lines.append(f"- {md_escape(caveat)}")
    else:
        lines.append("- No missing optional analysis artifacts were detected.")

    lines.extend([
        "",
        "## 5. Reproduction",
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
