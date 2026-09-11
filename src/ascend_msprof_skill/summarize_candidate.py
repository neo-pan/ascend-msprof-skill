#!/usr/bin/env python3
"""Summarize candidate performance and profiler mechanisms independently."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .ascend_profile_utils import analysis_dir
from .candidate_feedback import render_assessment_markdown
from .run_assessment import assess_run, assessment_metadata
from .run_evidence import RunEvidence, RunEvidenceError

CANDIDATE_SUMMARY_SCHEMA_VERSION = "2.0"


def build_candidate_summary(run_dir: Path, baseline_run_dir: Path | None = None) -> dict[str, Any]:
    candidate = RunEvidence.load_assessment(run_dir)
    baseline = RunEvidence.load_assessment(baseline_run_dir) if baseline_run_dir is not None else None
    return {"candidate_summary_schema_version": CANDIDATE_SUMMARY_SCHEMA_VERSION,
            **assessment_metadata(candidate, baseline), **assess_run(candidate, baseline),
            "inspection_targets": candidate.candidate_summary_facts().inspection_target_summaries()}


def render_markdown(summary: dict[str, Any]) -> str:
    lines = ["# Ascend Candidate Summary", "", f"Schema: `{summary['candidate_summary_schema_version']}`.", ""]
    for role, run in summary["runs"].items():
        lines.append(f"- {role}: `{run['label']}` ({run['run_dir']})")
    lines.extend(["", *render_assessment_markdown(summary), "", "## Inspection Targets", ""])
    for target in summary["inspection_targets"]:
        lines.append(f"- `{target.get('id')}`: `{target.get('artifact')}` ({target.get('field_ref') or target.get('field') or target.get('source')}).")
    lines.extend(["", "## Warnings", "", *[f"- {w}" for w in summary["warnings"]]])
    return "\n".join(line.rstrip() for line in lines).rstrip() + "\n"


def write_candidate_summary(run_dir: Path, baseline_run_dir: Path | None = None, *, out_dir: Path | None = None) -> tuple[Path, Path]:
    run_dir = run_dir.resolve()
    baseline_run_dir = baseline_run_dir.resolve() if baseline_run_dir is not None else None
    result = build_candidate_summary(run_dir, baseline_run_dir)
    destination = out_dir or analysis_dir(run_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_out, md_out = destination / "candidate_summary.json", destination / "candidate_summary.md"
    json_out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    md_out.write_text(render_markdown(result), encoding="utf-8")
    return json_out, md_out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--baseline-run-dir", type=Path)
    ap.add_argument("--out-dir", type=Path)
    args = ap.parse_args(argv)
    try:
        outputs = write_candidate_summary(args.run_dir, args.baseline_run_dir, out_dir=args.out_dir)
    except RunEvidenceError as exc:
        ap.error(str(exc))
    for path in outputs:
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
