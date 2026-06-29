"""Text summary rendering for Evidence Model artifacts."""
from __future__ import annotations

from pathlib import Path

from .ascend_profile_utils import rel


def md_table_cell(value: object) -> str:
    return "" if value is None else str(value).replace("|", "\\|").replace("\n", " ")


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
    roofline = summary.get("stdout_sections", {}).get("roofline_summary")
    if roofline:
        lines.append("")
        lines.append("## RoofLine Summary")
        lines.append("")
        lines.append("| Message | Source |")
        lines.append("|---|---|")
        source = roofline.get("source", "missing")
        for message in roofline.get("messages", []):
            lines.append(
                f"| {md_table_cell(message.get('message'))} | "
                f"{md_table_cell(source)} |"
            )
    performance = summary.get("stdout_sections", {}).get("performance_summary")
    if performance:
        lines.append("")
        lines.append("## CANN Performance Summary")
        lines.append("")
        lines.append("| Ordinal | Message | Source |")
        lines.append("|---:|---|---|")
        source = performance.get("source", "missing")
        for message in performance.get("messages", []):
            lines.append(
                f"| {md_table_cell(message.get('ordinal'))} | "
                f"{md_table_cell(message.get('message'))} | "
                f"{md_table_cell(message.get('source') or source)} |"
            )
    dimensions = summary.get("analysis_dimensions") or []
    if dimensions:
        lines.append("")
        lines.append("## Analysis Dimensions")
        for dimension in dimensions:
            status = dimension.get("status", "insufficient")
            lines.append(f"- {dimension.get('title')}: {status}")
            for signal in dimension.get("signals", [])[:5]:
                value = signal.get("value")
                value_text = "n/a" if value is None else f"{float(value):g}" if isinstance(value, (int, float)) else str(value)
                lines.append(
                    f"  - {signal.get('signal')} = {value_text} "
                    f"({signal.get('artifact')}; {signal.get('field_ref')})"
                )
    relations = summary.get("evidence_relations") or []
    if relations:
        lines.append("")
        lines.append("## Evidence Relations")
        for item in relations:
            evidence_ids = ", ".join(str(evidence.get("evidence_id")) for evidence in item.get("evidence", []))
            lines.append(
                f"- {item.get('id')}: {item.get('kind')} target={item.get('target')} "
                f"confidence={item.get('confidence')} evidence={evidence_ids}"
            )
    directions = summary.get("optimization_directions") or []
    if directions:
        lines.append("")
        lines.append("## Optimization Directions")
        for item in directions:
            lines.append(
                f"- {item.get('rank')}. {item.get('id')}: "
                f"{item.get('title')}: {item.get('impact_basis')}"
            )
    next_actions = summary.get("next_collection_actions") or []
    if next_actions:
        lines.append("")
        lines.append("## Next Collection Actions")
        for item in next_actions:
            metrics = ", ".join(item.get("recommended_aic_metrics") or [])
            artifacts = ", ".join(item.get("required_artifacts") or [])
            lines.append(f"- {item.get('id')}: collect {metrics}; required artifacts: {artifacts}")
    readiness = summary.get("evidence_readiness")
    if isinstance(readiness, dict):
        lines.append("")
        lines.append("## Evidence Readiness")
        lines.append(f"- level: {readiness.get('level', 'insufficient')}")
        available = ", ".join(readiness.get("available_evidence_families") or []) or "none"
        missing = ", ".join(readiness.get("missing_evidence_families") or []) or "none"
        lines.append(f"- available evidence families: {available}")
        lines.append(f"- missing evidence families: {missing}")
        followups = readiness.get("recommended_followups") or []
        if followups:
            lines.append(f"- next minimal action: {followups[0].get('id')}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
