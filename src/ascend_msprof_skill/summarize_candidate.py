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
    sanitize_json_value,
    single_run_verdict_from_evidence,
)
from .run_evidence import RunEvidence


CANDIDATE_SUMMARY_SCHEMA_VERSION = "1.1"


def load_run_inputs(run_dir: Path) -> dict[str, Any]:
    evidence = RunEvidence.load_candidate_summary(run_dir)
    return {
        "evidence": evidence,
        "summary_facts": evidence.candidate_summary_facts(),
    }


def build_candidate_summary(
    run_dir: Path,
    baseline_run_dir: Path | None = None,
    *,
    min_speedup_pct: float = DEFAULT_MIN_SPEEDUP_PCT,
) -> dict[str, Any]:
    candidate = load_run_inputs(run_dir)
    verdict = single_run_verdict_from_evidence(candidate["evidence"])
    result: dict[str, Any] = {
        "candidate_summary_schema_version": CANDIDATE_SUMMARY_SCHEMA_VERSION,
        "run": candidate["summary_facts"].run.as_summary(),
        "inspection_targets": candidate["summary_facts"].inspection_target_summaries(),
        "verdict": verdict,
        "warnings": candidate["summary_facts"].warnings_list(),
    }

    if baseline_run_dir is not None:
        baseline = load_run_inputs(baseline_run_dir)
        result["baseline"] = baseline["summary_facts"].run.as_summary()
        result["baseline"]["warnings"] = baseline["summary_facts"].warnings_list()
        result["verdict"] = comparison_verdict_from_evidence(
            baseline["evidence"],
            candidate["evidence"],
            min_speedup_pct=min_speedup_pct,
        )
        result["design_feedback"] = build_comparison_design_feedback_from_evidence(
            baseline["evidence"],
            candidate["evidence"],
            result["verdict"].get("compatibility"),
        )
    else:
        result["design_feedback"] = build_single_run_design_feedback_from_evidence(
            candidate["evidence"],
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
