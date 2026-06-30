#!/usr/bin/env python3
"""Summarize an existing TileLang candidate profiling run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .ascend_profile_utils import analysis_dir
from .candidate_feedback import (
    DEFAULT_MIN_SPEEDUP_PCT,
    build_comparison_design_feedback_from_evidence,
    build_single_run_design_feedback_from_evidence,
    comparison_verdict_from_evidence,
    normalize_min_speedup_pct,
    render_design_feedback_markdown,
    run_display,
    sanitize_json_value,
    single_run_verdict_from_evidence,
)
from .run_evidence import RunEvidence


CANDIDATE_SUMMARY_SCHEMA_VERSION = "1.1"


def direction_targets(summary: dict[str, Any] | None) -> list[dict[str, Any]]:
    directions = (summary or {}).get("optimization_directions")
    if not isinstance(directions, list):
        return []
    out = []
    for item in directions:
        if not isinstance(item, dict):
            continue
        target = {
            "source": "optimization_directions",
            "id": item.get("id"),
            "rank": item.get("rank"),
            "title": item.get("title"),
            "action": item.get("action"),
            "impact_basis": item.get("impact_basis"),
            "confidence": item.get("confidence"),
            "effort": item.get("effort"),
            "evidence": item.get("evidence") if isinstance(item.get("evidence"), list) else [],
        }
        if isinstance(item.get("experiment_hint"), dict):
            target["experiment_hint"] = item["experiment_hint"]
        out.append(target)
    return out


def simulator_targets(simulator: dict[str, Any] | None, limit: int = 3) -> list[dict[str, Any]]:
    if not isinstance(simulator, dict):
        return []
    out = []
    for key, kind in [
        ("source_lines", "source_line"),
        ("instructions", "instruction"),
        ("pipeline_events", "pipeline_event"),
    ]:
        rows = simulator.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            evidence_id = row.get("evidence_id") or f"simulator.{kind}.{len(out) + 1}"
            target = {
                "source": "simulator_hotspots",
                "kind": kind,
                "id": evidence_id,
                "rank": row.get("rank"),
                "artifact": row.get("artifact"),
                "field": row.get("field"),
                "field_ref": row.get("field_ref"),
                "value": row.get("value") if row.get("value") is not None else row.get("duration"),
                "source_file": row.get("source_file"),
                "line": row.get("line"),
                "instruction": row.get("instr") or row.get("instruction"),
            }
            if kind == "source_line" and isinstance(row.get("source_context"), dict):
                target["source_context"] = row.get("source_context")
            out.append(target)
    return out


def load_run_inputs(run_dir: Path) -> dict[str, Any]:
    evidence = RunEvidence.load_candidate_summary(run_dir)
    return {
        "evidence": evidence,
        "summary": evidence.summary() if evidence.summary_present() else None,
        "context": evidence.tilelang_context(),
        "simulator": evidence.simulator_hotspots(),
        "warnings": evidence.warnings(),
    }


def run_summary(run_dir: Path, inputs: dict[str, Any]) -> dict[str, Any]:
    candidate_context = inputs["evidence"].candidate_context()
    return {
        "label": run_dir.name,
        "run_dir": run_display(run_dir),
        "artifacts": _candidate_artifact_presence(inputs["evidence"]),
        "workload": candidate_context.workload,
        "payload": candidate_context.payload.as_summary(),
        "jit": candidate_context.jit.as_summary(),
        "correctness": candidate_context.correctness.as_summary(),
        "runtime": candidate_context.runtime.as_summary(),
        "profiler_evidence": inputs["evidence"].profiler_evidence_status(),
    }


def _candidate_artifact_presence(evidence: RunEvidence) -> dict[str, str | None]:
    presence = evidence.artifact_presence()
    return {
        "summary": presence["summary"],
        "provenance": presence["provenance"],
        "tilelang_context": presence["tilelang_context"],
        "raw_artifact_index": presence["raw_artifact_index"],
        "simulator_hotspots": presence["simulator_hotspots"],
    }


def build_candidate_summary(
    run_dir: Path,
    baseline_run_dir: Path | None = None,
    *,
    min_speedup_pct: float = DEFAULT_MIN_SPEEDUP_PCT,
) -> dict[str, Any]:
    candidate = load_run_inputs(run_dir)
    verdict = single_run_verdict_from_evidence(candidate["evidence"], candidate["context"])
    result: dict[str, Any] = {
        "candidate_summary_schema_version": CANDIDATE_SUMMARY_SCHEMA_VERSION,
        "run": run_summary(run_dir, candidate),
        "inspection_targets": [
            *direction_targets(candidate["summary"]),
            *simulator_targets(candidate["simulator"]),
        ],
        "verdict": verdict,
        "warnings": candidate["warnings"],
    }

    if baseline_run_dir is not None:
        baseline = load_run_inputs(baseline_run_dir)
        result["baseline"] = run_summary(baseline_run_dir, baseline)
        result["baseline"]["warnings"] = baseline["warnings"]
        result["verdict"] = comparison_verdict_from_evidence(
            baseline["evidence"],
            candidate["evidence"],
            baseline["context"],
            candidate["context"],
            min_speedup_pct=min_speedup_pct,
        )
        result["design_feedback"] = build_comparison_design_feedback_from_evidence(
            baseline["evidence"],
            candidate["evidence"],
            baseline["context"],
            candidate["context"],
            result["verdict"].get("compatibility"),
        )
    else:
        result["design_feedback"] = build_single_run_design_feedback_from_evidence(
            candidate["evidence"],
            candidate["context"],
        )
    return result


def md_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (dict, list)):
        return "`" + json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "`"
    return "`" + str(value).replace("|", "\\|") + "`"


def render_markdown(summary: dict[str, Any]) -> str:
    run = summary["run"]
    verdict = summary["verdict"]
    lines = [
        "# TileLang Candidate Summary",
        "",
        f"- Candidate: `{run['label']}` ({run['run_dir']})",
        f"- Schema: `{summary['candidate_summary_schema_version']}`",
        f"- Verdict: `{verdict['decision']}`",
        f"- Policy: `{verdict['policy']}`",
        "",
        "## Verdict Reasons",
        "",
    ]
    for reason in verdict.get("reasons") or []:
        lines.append(f"- {reason}")

    lines.extend(
        [
            "",
            "## Workload And Runtime",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Workload id | {md_value(run['workload'].get('id'))} |",
            f"| Shape | {md_value(run['workload'].get('shape'))} |",
            f"| Dtype | {md_value(run['workload'].get('dtype'))} |",
            f"| Case count | {md_value(run['workload'].get('case_count'))} |",
            f"| Mean runtime ms | {md_value(run['runtime'].get('mean_ms'))} |",
            f"| Correctness passed | {md_value(run['correctness'].get('passed'))} |",
            f"| Compiled | {md_value(run['correctness'].get('compiled'))} |",
            "",
            "## Profiler Evidence",
            "",
            f"- Evidence present: `{run['profiler_evidence']['evidence_present']}`",
            f"- Evidence readiness: `{run['profiler_evidence']['evidence_readiness']['level']}`",
            f"- Material evidence families: {len(run['profiler_evidence']['evidence_readiness']['material_evidence_families'])}",
            f"- Parsed raw artifacts: {run['profiler_evidence']['parsed_artifact_count']}",
            f"- Pending collection actions: {len(run['profiler_evidence']['pending_collection_actions'])}",
            "",
            "## Inspection Targets",
            "",
        ]
    )
    targets = summary.get("inspection_targets") or []
    if targets:
        lines.extend(["| Source | ID | Rank | Evidence |", "|---|---|---:|---|"])
        for target in targets:
            evidence = target.get("evidence")
            if isinstance(evidence, list) and evidence:
                evidence_text = ", ".join(str(item.get("evidence_id") or item.get("artifact")) for item in evidence if isinstance(item, dict))
            else:
                evidence_text = str(target.get("field_ref") or target.get("artifact") or "n/a")
            lines.append(
                f"| {md_value(target.get('source'))} | {md_value(target.get('id'))} | "
                f"{md_value(target.get('rank'))} | {md_value(evidence_text)} |"
            )
    else:
        lines.append("No inspection targets recorded.")

    lines.extend(["", *render_design_feedback_markdown(summary.get("design_feedback") or {})])

    if summary.get("baseline"):
        lines.extend(
            [
                "",
                "## Baseline Comparison",
                "",
                f"- Baseline: `{summary['baseline']['label']}` ({summary['baseline']['run_dir']})",
                f"- Can compare: `{verdict.get('can_compare')}`",
                f"- Baseline mean ms: {md_value(verdict.get('baseline_mean_ms'))}",
                f"- Candidate mean ms: {md_value(verdict.get('candidate_mean_ms'))}",
                f"- Candidate speedup pct: {md_value(verdict.get('candidate_speedup_pct'))}",
            ]
        )

    lines.extend(["", "## Warnings", ""])
    if summary.get("warnings"):
        lines.extend(f"- {warning}" for warning in summary["warnings"])
    else:
        lines.append("No candidate summary warnings.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--baseline-run-dir", type=Path)
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--min-speedup-pct", type=float, default=DEFAULT_MIN_SPEEDUP_PCT)
    args = ap.parse_args(argv)
    try:
        min_speedup_pct = normalize_min_speedup_pct(args.min_speedup_pct)
    except ValueError as exc:
        ap.error(str(exc))

    run_dir = args.run_dir.resolve()
    baseline_run_dir = args.baseline_run_dir.resolve() if args.baseline_run_dir else None
    candidate_summary = sanitize_json_value(
        build_candidate_summary(
            run_dir,
            baseline_run_dir,
            min_speedup_pct=min_speedup_pct,
        )
    )
    out_dir = args.out_dir or analysis_dir(run_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_out = out_dir / "candidate_summary.json"
    md_out = out_dir / "candidate_summary.md"
    json_out.write_text(json.dumps(candidate_summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    md_out.write_text(render_markdown(candidate_summary), encoding="utf-8")
    print(f"wrote {json_out}")
    print(f"wrote {md_out}")


if __name__ == "__main__":
    main()
