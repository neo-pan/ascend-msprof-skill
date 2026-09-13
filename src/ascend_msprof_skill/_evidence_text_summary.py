"""Text summary rendering for Evidence Model artifacts."""
from __future__ import annotations

from pathlib import Path

from .summary_types import Summary
from .operator_evidence import OperatorEvidence
from .application_timing import TimingEvidence, observation_field_ref


def md_table_cell(value: object) -> str:
    return "" if value is None else str(value).replace("|", "\\|").replace("\n", " ")


def write_text_summary(out_path: Path, summary: Summary) -> None:
    lines = ["# Ascend msprof Key Metrics", ""]
    for group, item in summary.headlines.items():
        if isinstance(item, (TimingEvidence, OperatorEvidence)):
            lines.append(f"- {group}: {item.primary.reason}")
            for artifact in item.artifacts:
                for observation in artifact.observations:
                    lines.append(f"  - {observation.name}: {observation.value:g} {observation.unit} ({observation.statistic}); {artifact.artifact}; {observation_field_ref(group, observation)}")
            if isinstance(item, OperatorEvidence):
                for artifact in item.artifacts:
                    for metadata in artifact.metadata:
                        lines.append(f"  - {metadata.source.field}: {metadata.value}; {artifact.artifact}; record={metadata.source.record}; column={metadata.source.column}")
            continue
    lines.append("")
    lines.append("## Files")
    for group, evidence in summary.headlines.items():
        lines.append(f"- {group}: {len(evidence.artifacts)} file(s)")
        for artifact in evidence.artifacts:
            lines.append(f"  - {artifact.artifact}: {artifact.row_count} row(s)")
    stdout_sections = summary.stdout_sections
    occupancy = stdout_sections.occupancy_summary
    if occupancy:
        lines.append("")
        lines.append("## Occupancy Summary")
        lines.append("")
        lines.append("| Ordinal | Message | Source |")
        lines.append("|---:|---|---|")
        source = occupancy.source
        for message in occupancy.messages:
            lines.append(
                f"| {md_table_cell(message.ordinal)} | "
                f"{md_table_cell(message.message)} | "
                f"{md_table_cell(source)} |"
            )
    roofline = stdout_sections.roofline_summary
    if roofline:
        lines.append("")
        lines.append("## RoofLine Summary")
        lines.append("")
        lines.append("| Message | Source |")
        lines.append("|---|---|")
        source = roofline.source
        for message in roofline.messages:
            lines.append(
                f"| {md_table_cell(message.message)} | "
                f"{md_table_cell(source)} |"
            )
    performance = stdout_sections.performance_summary
    if performance:
        lines.append("")
        lines.append("## CANN Performance Summary")
        lines.append("")
        lines.append("| Ordinal | Message | Source |")
        lines.append("|---:|---|---|")
        source = performance.source
        for message in performance.messages:
            lines.append(
                f"| {md_table_cell(message.ordinal)} | "
                f"{md_table_cell(message.message)} | "
                f"{md_table_cell(source)} |"
            )
    dimensions = summary.analysis_dimensions or []
    if dimensions:
        lines.append("")
        lines.append("## Analysis Dimensions")
        for dimension in dimensions:
            status = dimension.status
            lines.append(f"- {dimension.title}: {status}")
            for signal in dimension.signals[:5]:
                value = signal.value
                value_text = "n/a" if value is None else f"{float(value):g}" if isinstance(value, (int, float)) else str(value)
                lines.append(
                    f"  - {signal.signal} = {value_text} "
                    f"({signal.artifact}; {signal.field_ref})"
                )
    relations = summary.evidence_relations or []
    if relations:
        lines.append("")
        lines.append("## Evidence Relations")
        for item in relations:
            evidence_ids = ", ".join(str(evidence.evidence_id) for evidence in item.evidence)
            lines.append(
                f"- {item.id}: {item.kind} target={item.target} "
                f"confidence={item.confidence} evidence={evidence_ids}"
            )
    frequency = summary.measurement_quality.frequency
    if frequency.groups:
        lines.append("")
        lines.append("## Frequency Measurement Quality")
        for item in frequency.groups:
            lines.append(
                f"- segment={item.segment} target={item.target}: "
                f"launches={item.launch_count}, current_mhz={item.current_frequencies_mhz}, "
                f"rated_mhz={item.rated_frequencies_mhz}, "
                f"below_rated={item.below_rated_launch_count}, mixed={item.mixed_frequency}"
            )
        lines.append("- Frequency context does not filter samples or change profiler readiness or natural-performance assessment.")
    next_actions = summary.next_collection_actions or []
    if next_actions:
        lines.append("")
        lines.append("## Next Collection Actions")
        for item in next_actions:
            metrics = ", ".join(item.recommended_aic_metrics or [])
            artifacts = ", ".join(item.required_artifacts or [])
            lines.append(
                f"- {item.id} [{item.necessity}]: collect {metrics}; "
                f"required artifacts: {artifacts}; target={item.target_scope.model_dump(mode='json', exclude_unset=True)}"
            )
    readiness = summary.evidence_readiness
    if readiness is not None:
        lines.append("")
        lines.append("## Evidence Readiness")
        lines.append(f"- level: {readiness.level}")
        available = ", ".join(readiness.available_evidence_families or []) or "none"
        missing = ", ".join(readiness.missing_evidence_families or []) or "none"
        lines.append(f"- available evidence families: {available}")
        lines.append(f"- missing evidence families: {missing}")
        followups = readiness.recommended_followups or []
        for action in followups:
            lines.append(f"- conditional collection option: {action.id}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
