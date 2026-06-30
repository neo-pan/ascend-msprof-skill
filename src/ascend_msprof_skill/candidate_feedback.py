"""Shared TileLang candidate feedback and verdict helpers."""
from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from typing import Any

from .run_evidence import RunEvidence


DEFAULT_MIN_SPEEDUP_PCT = 1.0


def try_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def sanitize_json_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, int):
        return value
    if isinstance(value, list):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): sanitize_json_value(item) for key, item in value.items()}
    return value


def normalize_min_speedup_pct(value: float) -> float:
    threshold = try_float(value)
    if threshold is None or threshold < 0:
        raise ValueError("--min-speedup-pct must be a finite non-negative number")
    return threshold


def build_single_run_design_feedback(
    summary: dict[str, Any] | None,
    context: dict[str, Any] | None,
    raw_index: dict[str, Any] | None,
    provenance: dict[str, Any] | None = None,
    simulator: dict[str, Any] | None = None,
    *,
    source: str = "run",
) -> dict[str, Any]:
    evidence = RunEvidence.from_loaded(
        Path("."),
        summary,
        raw_artifact_index=raw_index,
        provenance=provenance,
        tilelang_context=context,
        simulator_hotspots=simulator,
    )
    return build_single_run_design_feedback_from_evidence(evidence, source=source)


def build_single_run_design_feedback_from_evidence(
    evidence: RunEvidence,
    *,
    source: str = "run",
) -> dict[str, Any]:
    return evidence.single_run_design_feedback_facts(source=source).as_payload()


def build_comparison_design_feedback(
    a_summary: dict[str, Any] | None,
    b_summary: dict[str, Any] | None,
    a_context: dict[str, Any] | None,
    b_context: dict[str, Any] | None,
    a_raw_index: dict[str, Any] | None,
    b_raw_index: dict[str, Any] | None,
    a_provenance: dict[str, Any] | None,
    b_provenance: dict[str, Any] | None,
    compatibility: dict[str, Any] | None,
) -> dict[str, Any]:
    a_evidence = RunEvidence.from_loaded(
        Path("."),
        a_summary,
        raw_artifact_index=a_raw_index,
        provenance=a_provenance,
        tilelang_context=a_context,
    )
    b_evidence = RunEvidence.from_loaded(
        Path("."),
        b_summary,
        raw_artifact_index=b_raw_index,
        provenance=b_provenance,
        tilelang_context=b_context,
    )
    return build_comparison_design_feedback_from_evidence(
        a_evidence,
        b_evidence,
        compatibility,
    )


def build_comparison_design_feedback_from_evidence(
    a_evidence: RunEvidence,
    b_evidence: RunEvidence,
    compatibility: dict[str, Any] | None,
) -> dict[str, Any]:
    return RunEvidence.comparison_design_feedback_facts(a_evidence, b_evidence, compatibility).as_payload()


def md_escape(value: Any) -> str:
    if value is None:
        return "n/a"
    return str(value).replace("|", "\\|")


def evidence_label(item: dict[str, Any]) -> str:
    source = item.get("source")
    role = item.get("role")
    artifact = item.get("artifact") or "n/a"
    field_ref = item.get("field_ref") or item.get("field")
    prefix_parts = [str(part) for part in [source, role] if part not in (None, "")]
    prefix = ": ".join(prefix_parts)
    body = str(artifact)
    if field_ref:
        body = f"{body} ({field_ref})"
    if prefix:
        return f"{prefix}: {body}"
    return body


def markdown_evidence_sample(items: list[Any], limit_per_source: int = 5) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for item in items:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "unknown")
        if counts[source] >= limit_per_source:
            continue
        selected.append(item)
        counts[source] += 1
    return selected


def render_design_feedback_markdown(feedback: dict[str, Any]) -> list[str]:
    lines = ["## Design Feedback", "", f"Status: `{feedback.get('status', 'blocked')}`", ""]
    questions = feedback.get("questions")
    if not isinstance(questions, list) or not questions:
        lines.append("No design feedback questions recorded.")
        return lines
    lines.extend(
        [
            "| Question ID | Family | Question | Available Evidence | Missing Evidence | Blockers |",
            "|---|---|---|---:|---:|---|",
        ]
    )
    for question in questions:
        if not isinstance(question, dict):
            continue
        blockers = question.get("blocked_by") if isinstance(question.get("blocked_by"), list) else []
        lines.append(
            f"| `{md_escape(question.get('id'))}` | `{md_escape(question.get('evidence_family'))}` | "
            f"{md_escape(question.get('question'))} | "
            f"{len(question.get('available_evidence') or [])} | {len(question.get('missing_evidence') or [])} | "
            f"{md_escape(', '.join(str(item) for item in blockers) if blockers else 'none')} |"
        )
    for question in questions:
        if not isinstance(question, dict):
            continue
        lines.extend(
            [
                "",
                f"### {md_escape(question.get('id'))}",
                "",
                f"- Question: {md_escape(question.get('question'))}",
                f"- Related design variables: `{md_escape(', '.join(str(item) for item in question.get('related_design_variables') or []))}`",
            ]
        )
        available = question.get("available_evidence") if isinstance(question.get("available_evidence"), list) else []
        if available:
            lines.append("- Available evidence:")
            for item in markdown_evidence_sample(available):
                lines.append(f"  - `{md_escape(evidence_label(item))}`")
        missing = question.get("missing_evidence") if isinstance(question.get("missing_evidence"), list) else []
        if missing:
            lines.append("- Missing evidence:")
            for item in markdown_evidence_sample(missing):
                lines.append(f"  - `{md_escape(evidence_label(item))}`")
        blockers = question.get("blocked_by") if isinstance(question.get("blocked_by"), list) else []
        if blockers:
            lines.append("- Blocked by:")
            for blocker in blockers:
                lines.append(f"  - {md_escape(blocker)}")
        lines.append(f"- Next experiment: {md_escape(question.get('next_experiment'))}")
    return lines


def single_run_verdict(
    summary: dict[str, Any] | None,
    context: dict[str, Any] | None,
    raw_index: dict[str, Any] | None,
) -> dict[str, Any]:
    evidence = RunEvidence.from_loaded(Path("."), summary, raw_artifact_index=raw_index, tilelang_context=context)
    return single_run_verdict_from_evidence(evidence)


def single_run_verdict_from_evidence(
    evidence: RunEvidence,
) -> dict[str, Any]:
    return evidence.single_run_feedback_verdict().as_payload()


def verdict_compatibility(
    a_summary: dict[str, Any] | None,
    b_summary: dict[str, Any] | None,
    a_context: dict[str, Any] | None,
    b_context: dict[str, Any] | None,
    a_provenance: dict[str, Any] | None,
    b_provenance: dict[str, Any] | None,
) -> dict[str, Any]:
    a_evidence = RunEvidence.from_loaded(Path("."), a_summary, provenance=a_provenance, tilelang_context=a_context)
    b_evidence = RunEvidence.from_loaded(Path("."), b_summary, provenance=b_provenance, tilelang_context=b_context)
    return verdict_compatibility_from_evidence(a_evidence, b_evidence)


def verdict_compatibility_from_evidence(
    a_evidence: RunEvidence,
    b_evidence: RunEvidence,
) -> dict[str, Any]:
    return RunEvidence.feedback_verdict_compatibility(a_evidence, b_evidence).as_payload()


def comparison_verdict(
    a_summary: dict[str, Any] | None,
    b_summary: dict[str, Any] | None,
    a_context: dict[str, Any] | None,
    b_context: dict[str, Any] | None,
    a_raw_index: dict[str, Any] | None,
    b_raw_index: dict[str, Any] | None,
    a_provenance: dict[str, Any] | None,
    b_provenance: dict[str, Any] | None,
    *,
    min_speedup_pct: float = DEFAULT_MIN_SPEEDUP_PCT,
) -> dict[str, Any]:
    a_evidence = RunEvidence.from_loaded(
        Path("."),
        a_summary,
        raw_artifact_index=a_raw_index,
        provenance=a_provenance,
        tilelang_context=a_context,
    )
    b_evidence = RunEvidence.from_loaded(
        Path("."),
        b_summary,
        raw_artifact_index=b_raw_index,
        provenance=b_provenance,
        tilelang_context=b_context,
    )
    return comparison_verdict_from_evidence(
        a_evidence,
        b_evidence,
        min_speedup_pct=min_speedup_pct,
    )


def comparison_verdict_from_evidence(
    a_evidence: RunEvidence,
    b_evidence: RunEvidence,
    *,
    min_speedup_pct: float = DEFAULT_MIN_SPEEDUP_PCT,
) -> dict[str, Any]:
    return RunEvidence.comparison_feedback_verdict(
        a_evidence,
        b_evidence,
        min_speedup_pct=min_speedup_pct,
    ).as_payload()


def run_display(path: Path) -> str:
    if path.is_absolute():
        return f"<abs-path>/{path.name}"
    return path.as_posix()
