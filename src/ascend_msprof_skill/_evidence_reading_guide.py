"""Render a compact, lossless entry point for question-driven evidence reading."""
from __future__ import annotations

from pathlib import Path

from .summary_types import Summary, RawArtifactIndex


_QUESTION_GROUPS = {
    "application timing / hot path": ("op_summary", "op_statistic", "task_time", "api_statistic"),
    "pipe / arithmetic": ("pipe_utilization", "arithmetic_utilization"),
    "memory / cache": ("memory", "l2_cache"),
    "launch / resource context": ("op_basic_info", "resource_conflict"),
    "simulator source / pipeline": ("simulator",),
}


def _fields(index: RawArtifactIndex, artifact: str) -> str:
    item = next((entry for entry in index.artifacts if entry.artifact == artifact), None)
    if item is None or not item.columns:
        return "columns unavailable; inspect raw_artifact_index.json"
    return ", ".join(item.columns)


def write_reading_guide(path: Path, summary: Summary, index: RawArtifactIndex) -> None:
    """Write navigation metadata; all measurements remain in summary/index/raw files."""
    lines = [
        "# Evidence Reading Guide", "",
        "This is a navigation view. `analysis/summary.json` is the complete derived evidence;",
        "`analysis/raw_artifact_index.json` is the complete parser inventory; raw reports retain",
        "the original rows. This guide does not aggregate, round, filter, or replace evidence.", "",
        "## Read First", "",
        "- Gates: `summary.json` → `target_identity`, `profile_coverage`, `metric_scope`,",
        "  `evidence_readiness`, `measurement_quality`, `warnings`, `next_collection_actions`.",
        "- Inventory: `raw_artifact_index.json` → parser status, columns, row counts and artifact paths.",
        "- Full observations: `summary.json` → `headlines`, `analysis_dimensions`, `evidence_relations`.",
        f"- Evidence readiness: `{summary.evidence_readiness.level}`.", "",
        "## Evidence Families", "",
        "| Family | Artifact | Segment | Scope | Rows | Fields / drill-down |",
        "|---|---|---|---|---:|---|",
    ]
    for group, evidence in summary.headlines.items():
        for index_number, artifact in enumerate(evidence.artifacts):
            pointer = f"summary.json#/headlines/{group}/artifacts/{index_number}"
            lines.append(
                f"| `{group}` | `{artifact.artifact}` | `{artifact.segment}` | "
                f"`{artifact.metric_scope or 'application'}` | {artifact.row_count} | "
                f"{_fields(index, artifact.artifact)}; `{pointer}` |"
            )
    lines.extend(["", "## Question Routes", ""])
    for question, groups in _QUESTION_GROUPS.items():
        present = [group for group in groups if group in summary.headlines]
        missing = [group for group in groups if group not in summary.headlines]
        lines.extend([f"### {question}",
                      f"- Available families: {', '.join(f'`{group}`' for group in present) or 'none'}.",
                      f"- Missing families: {', '.join(f'`{group}`' for group in missing) or 'none'}."])
        if present:
            lines.append("- Start with the family rows above, then use `joint-row` for exact fields, scopes and records.")
    lines.extend(["", "## Safe Drill-down", "",
                  "- Full field population: `ascend-msprof joint-row --run-dir <run> --artifact <artifact> --field <name>`.",
                  "- One scope: add `--scope block_id=<id>` or `--scope sub_block_id=<id>`.",
                  "- Raw rows: add `--records --limit 5`; use the returned `next_command` for every page.",
                  "- Same-record context: add `--record <csv-record>`; this is one CSV record, not simultaneous PMU sampling.",
                  "- Keep natural benchmark timing separate from profiler durations; use comparison assessment for eligibility.",
                  "", "## Conditional Collection", ""])
    if summary.next_collection_actions:
        for action in summary.next_collection_actions:
            lines.append(f"- `{action.id}` [{action.necessity}]: {action.reason}; unlocks: {', '.join(action.unlocks_claims) or 'none'}.")
    else:
        lines.append("- None recorded.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
