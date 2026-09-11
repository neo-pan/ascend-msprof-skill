"""Candidate evidence rendering and JSON formatting helpers."""
from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from typing import Any


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


def run_display(path: Path) -> str:
    if path.is_absolute():
        return f"<abs-path>/{path.name}"
    return path.as_posix()


def render_assessment_markdown(result: dict[str, Any]) -> list[str]:
    performance = result["performance_assessment"]
    mechanism = result["mechanism_assessment"]
    lines = ["## Performance Assessment", "", f"Eligibility: `{performance['eligibility']['status']}`; comparison: `{performance['comparison']['status']}`.", "",
             "| Measurement | Value ms | Statistic | Samples | Source |", "|---|---:|---|---:|---|"]
    for role, evidence in performance["measurements"].items():
        if evidence is None:
            continue
        record = evidence.get("record") or {}
        measurement = record.get("measurement")
        measurement = measurement if isinstance(measurement, dict) else {}
        sources = "; ".join(evidence_label(s) for s in evidence["sources"])
        lines.append(f"| {role} | {md_escape(measurement.get('value_ms'))} | {md_escape(measurement.get('statistic'))} | {md_escape(measurement.get('sample_count'))} | {md_escape(sources)} |")
    observation = performance["comparison"]["observation"]
    if observation:
        lines.extend(["", f"Observed in these caller-provided measurements: `{observation['direction']}`; delta `{observation['delta_ms']:.6g} ms`; elapsed-time reduction `{observation['speedup_pct']:.6g}%`.",
                      "Sources: " + "; ".join(f"`{md_escape(evidence_label(s))}`" for s in observation["sources"])])
    else:
        lines.extend(["", "No comparative performance delta is available."])
    for check in performance["eligibility"]["checks"]:
        if check["status"] in {"match", "not_applicable"}:
            continue
        lines.append(f"- `{md_escape(check['id'])}`: {md_escape(check['reason_code'])}; baseline `{md_escape(check.get('baseline'))}`, candidate `{md_escape(check.get('candidate'))}`; " + "; ".join(f"`{md_escape(evidence_label(s))}`" for s in check["sources"]))
    lines.extend(["", *[f"- {text}" for text in performance["limitations"]], "", "## Mechanism Assessment", "", f"Coverage: `{mechanism['coverage']}`.", "",
                  "| Group | Status | Field A | Field B | Baseline | Candidate | Delta | Delta % | Sources / gaps |", "|---|---|---|---|---:|---:|---:|---:|---|"])
    for row in mechanism["headlines"]:
        a, b = row.get("a", {}), row.get("b", row.get("candidate", {}))
        sources = "; ".join(evidence_label(e) for e in (a, b) if e.get("artifact"))
        reasons = "; ".join(row.get("comparison_reasons", []))
        lines.append(f"| {row['group']} | {row['status']} | {md_escape(a.get('field'))} | {md_escape(b.get('field'))} | {md_escape(a.get('value'))} | {md_escape(b.get('value'))} | {md_escape(row.get('delta'))} | {md_escape(row.get('delta_pct'))} | {md_escape(sources + '; ' + reasons)} |")
    lines.extend(["", "### Profiler Compatibility", ""])
    for check in [*mechanism["compatibility"]["checks"], *mechanism["workload_checks"]]:
        lines.append(f"- `{check['id']}`: `{check['status']}`; A `{md_escape(check.get('a'))}`, B `{md_escape(check.get('b'))}`.")
    for association in mechanism["benchmark_association"]:
        lines.append(f"- {association['role']} benchmark association: `{association['status']}`.")
        if association["limitation"]:
            lines.append(f"  {association['limitation']}")
    lines.extend(["", *render_design_feedback_markdown({"status": mechanism["coverage"], "questions": mechanism["questions"]}), "", "### Pending Collection Actions", ""])
    for action in mechanism["pending_actions"]:
        lines.append(f"- {action['role']}: `{action.get('id', 'unknown')}` ({action.get('necessity', 'unspecified')}); {action.get('reason', action.get('description', 'scope and evidence requirements remain in the action record'))}.")
    lines.extend(["", *[f"- {text}" for text in mechanism["limitations"]]])
    return lines
