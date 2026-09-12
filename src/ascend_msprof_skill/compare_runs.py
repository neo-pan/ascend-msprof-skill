#!/usr/bin/env python3
"""Compare natural performance and profiler mechanisms independently."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .ascend_profile_utils import analysis_dir
from .candidate_feedback import render_assessment_markdown
from .run_assessment import assess_run, assessment_metadata
from .run_evidence import RunEvidence, RunEvidenceError

COMPARISON_SCHEMA_VERSION = "3.0"


def build_comparison(run_dir_a: Path, run_dir_b: Path) -> dict[str, Any]:
    baseline = RunEvidence.load_assessment(run_dir_a)
    candidate = RunEvidence.load_assessment(run_dir_b)
    return {"comparison_schema_version": COMPARISON_SCHEMA_VERSION,
            **assessment_metadata(candidate, baseline), **assess_run(candidate, baseline)}


def render_markdown(comparison: dict[str, Any]) -> str:
    lines = ["# Ascend Run Comparison", "", f"Schema: `{comparison['comparison_schema_version']}`.", ""]
    for role, run in comparison["runs"].items():
        lines.append(f"- {role}: `{run['label']}` ({run['run_dir']})")
    lines.extend(["", *render_assessment_markdown(comparison), "", "## Warnings", ""])
    lines.extend(f"- {warning}" for warning in comparison["warnings"])
    return "\n".join(line.rstrip() for line in lines).rstrip() + "\n"


def output_stem(run_dir_a: Path, run_dir_b: Path) -> str:
    return f"compare_{run_dir_a.name}_vs_{run_dir_b.name}"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir-a", type=Path, required=True)
    ap.add_argument("--run-dir-b", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path)
    args = ap.parse_args(argv)
    try:
        comparison = build_comparison(args.run_dir_a.resolve(), args.run_dir_b.resolve())
    except RunEvidenceError as exc:
        ap.error(str(exc))
    destination = args.out_dir or analysis_dir(args.run_dir_b.resolve())
    destination.mkdir(parents=True, exist_ok=True)
    stem = output_stem(args.run_dir_a, args.run_dir_b)
    json_out, md_out = destination / f"{stem}.json", destination / f"{stem}.md"
    json_out.write_text(json.dumps(comparison, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    md_out.write_text(render_markdown(comparison), encoding="utf-8")
    print(f"wrote {json_out}")
    print(f"wrote {md_out}")


if __name__ == "__main__":
    main()
