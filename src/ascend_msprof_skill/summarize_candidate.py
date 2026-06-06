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
    benchmark_error,
    build_comparison_design_feedback,
    build_single_run_design_feedback,
    compiled_value,
    comparison_verdict,
    context_value,
    correctness_passed,
    normalize_min_speedup_pct,
    profiler_evidence_status,
    render_design_feedback_markdown,
    run_display,
    runtime_mean_ms,
    sanitize_json_value,
    single_run_verdict,
)


CANDIDATE_SUMMARY_SCHEMA_VERSION = "1.1"


def load_analysis_json(run_dir: Path, name: str, warnings: list[str], *, required: bool = False) -> dict[str, Any] | None:
    path = run_dir / "analysis" / name
    if not path.exists():
        if required:
            warnings.append(f"missing analysis/{name}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        warnings.append(f"invalid analysis/{name}: {exc}")
        return None
    if not isinstance(value, dict):
        warnings.append(f"analysis/{name} is not a JSON object")
        return None
    return value


def artifact_presence(
    summary: dict[str, Any] | None,
    provenance: dict[str, Any] | None,
    context: dict[str, Any] | None,
    raw_index: dict[str, Any] | None,
    simulator: dict[str, Any] | None,
) -> dict[str, str | None]:
    return {
        "summary": "analysis/summary.json" if summary else None,
        "provenance": "analysis/provenance.json" if provenance else None,
        "tilelang_context": "analysis/tilelang_context.json" if context else None,
        "raw_artifact_index": "analysis/raw_artifact_index.json" if raw_index else None,
        "simulator_hotspots": "analysis/simulator_hotspots.json" if simulator else None,
    }


def payload_context(context: dict[str, Any] | None) -> dict[str, Any]:
    payload = context_value(context, ["sources", "payload"])
    if not isinstance(payload, dict):
        return {"present": False}
    return {
        "present": True,
        "artifact": payload.get("artifact"),
        "sha256": payload.get("sha256"),
        "size_bytes": payload.get("size_bytes"),
    }


def workload_context(context: dict[str, Any] | None) -> dict[str, Any]:
    workload = context_value(context, ["benchmark", "workload"])
    return workload if isinstance(workload, dict) else {}


def jit_context(context: dict[str, Any] | None) -> dict[str, Any]:
    debug = context_value(context, ["jit_debug"])
    config = context_value(context, ["benchmark", "jit_config"])
    out = {"config": config}
    if isinstance(debug, dict):
        out["debug"] = {
            "found": debug.get("found"),
            "provided": debug.get("provided"),
            "artifact_count": debug.get("artifact_count", len(debug.get("artifacts") or [])),
            "artifacts": debug.get("artifacts") or [],
        }
    else:
        out["debug"] = None
    return out


def correctness_context(context: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "compiled": compiled_value(context),
        "passed": correctness_passed(context),
        "error": benchmark_error(context),
        "maxima": context_value(context, ["benchmark", "correctness", "maxima"]) or [],
        "source": "analysis/tilelang_context.json" if context else None,
    }


def runtime_context(context: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "mean_ms": runtime_mean_ms(context),
        "runtime": context_value(context, ["benchmark", "candidate", "runtime"]),
        "runtime_stats": context_value(context, ["benchmark", "candidate", "runtime_stats"]),
        "ref_runtime": context_value(context, ["benchmark", "candidate", "ref_runtime"]),
        "speedup": context_value(context, ["benchmark", "candidate", "speedup"]),
        "source": "analysis/tilelang_context.json" if context else None,
    }


def direction_targets(summary: dict[str, Any] | None) -> list[dict[str, Any]]:
    directions = (summary or {}).get("optimization_directions")
    if not isinstance(directions, list):
        return []
    out = []
    for item in directions:
        if not isinstance(item, dict):
            continue
        out.append(
            {
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
        )
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


def load_run_inputs(run_dir: Path, warnings: list[str], *, summary_required: bool = False) -> dict[str, Any]:
    summary = load_analysis_json(run_dir, "summary.json", warnings, required=summary_required)
    provenance = load_analysis_json(run_dir, "provenance.json", warnings)
    context = load_analysis_json(run_dir, "tilelang_context.json", warnings)
    raw_index = load_analysis_json(run_dir, "raw_artifact_index.json", warnings)
    simulator = load_analysis_json(run_dir, "simulator_hotspots.json", warnings)
    return {
        "summary": summary,
        "provenance": provenance,
        "context": context,
        "raw_index": raw_index,
        "simulator": simulator,
    }


def run_summary(run_dir: Path, inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": run_dir.name,
        "run_dir": run_display(run_dir),
        "artifacts": artifact_presence(
            inputs["summary"],
            inputs["provenance"],
            inputs["context"],
            inputs["raw_index"],
            inputs["simulator"],
        ),
        "workload": workload_context(inputs["context"]),
        "payload": payload_context(inputs["context"]),
        "jit": jit_context(inputs["context"]),
        "correctness": correctness_context(inputs["context"]),
        "runtime": runtime_context(inputs["context"]),
        "profiler_evidence": profiler_evidence_status(inputs["summary"], inputs["raw_index"]),
    }


def build_candidate_summary(
    run_dir: Path,
    baseline_run_dir: Path | None = None,
    *,
    min_speedup_pct: float = DEFAULT_MIN_SPEEDUP_PCT,
) -> dict[str, Any]:
    warnings: list[str] = []
    candidate = load_run_inputs(run_dir, warnings, summary_required=True)
    verdict = single_run_verdict(candidate["summary"], candidate["context"], candidate["raw_index"])
    result: dict[str, Any] = {
        "candidate_summary_schema_version": CANDIDATE_SUMMARY_SCHEMA_VERSION,
        "run": run_summary(run_dir, candidate),
        "inspection_targets": [
            *direction_targets(candidate["summary"]),
            *simulator_targets(candidate["simulator"]),
        ],
        "verdict": verdict,
        "warnings": warnings,
    }

    if baseline_run_dir is not None:
        baseline_warnings: list[str] = []
        baseline = load_run_inputs(baseline_run_dir, baseline_warnings, summary_required=True)
        result["baseline"] = run_summary(baseline_run_dir, baseline)
        result["baseline"]["warnings"] = baseline_warnings
        result["verdict"] = comparison_verdict(
            baseline["summary"],
            candidate["summary"],
            baseline["context"],
            candidate["context"],
            baseline["raw_index"],
            candidate["raw_index"],
            baseline["provenance"],
            candidate["provenance"],
            min_speedup_pct=min_speedup_pct,
        )
        result["design_feedback"] = build_comparison_design_feedback(
            baseline["summary"],
            candidate["summary"],
            baseline["context"],
            candidate["context"],
            baseline["raw_index"],
            candidate["raw_index"],
            baseline["provenance"],
            candidate["provenance"],
            result["verdict"].get("compatibility"),
        )
    else:
        result["design_feedback"] = build_single_run_design_feedback(
            candidate["summary"],
            candidate["context"],
            candidate["raw_index"],
            candidate["provenance"],
            candidate["simulator"],
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
            f"- Parsed raw artifacts: {run['profiler_evidence']['parsed_artifact_count']}",
            f"- Pending collection actions: {len(run['profiler_evidence']['next_collection_actions'])}",
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
