#!/usr/bin/env python3
"""Compare two analyzed Ascend profiling runs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .ascend_profile_utils import analysis_dir
from .candidate_feedback import (
    DEFAULT_MIN_SPEEDUP_PCT,
    build_comparison_design_feedback,
    comparison_verdict,
    normalize_min_speedup_pct,
    render_design_feedback_markdown,
    sanitize_json_value,
    sourced_value,
    try_float,
)
from .run_evidence import RunEvidence, RunEvidenceError


COMPARISON_SCHEMA_VERSION = "1.2"
RUN_A = "a"
RUN_B = "b"
HEADLINE_GROUP_ORDER = [
    "op_summary",
    "op_statistic",
    "task_time",
    "api_statistic",
    "op_basic_info",
    "pipe_utilization",
    "arithmetic_utilization",
    "l2_cache",
    "memory",
    "resource_conflict",
]

def run_display(path: Path) -> str:
    if path.is_absolute():
        return f"<abs-path>/{path.name}"
    return path.as_posix()


def source_ref(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    source = item.get("source")
    if isinstance(source, dict):
        return {
            "artifact": source.get("artifact"),
            "field": source.get("field") or source.get("field_ref"),
        }
    return None


def compare_numeric(a_value: Any, b_value: Any) -> dict[str, Any]:
    a_num = try_float(a_value)
    b_num = try_float(b_value)
    if a_num is None or b_num is None:
        return {"delta": None, "delta_pct": None, "numeric": False}
    delta = b_num - a_num
    delta_pct = None if a_num == 0 else delta / abs(a_num) * 100.0
    return {"delta": delta, "delta_pct": delta_pct, "numeric": True}


def comparison_status(a_present: bool, b_present: bool, a_value: Any, b_value: Any) -> str:
    if not a_present and not b_present:
        return "missing"
    if not a_present or not b_present:
        return "missing"
    if try_float(a_value) is None or try_float(b_value) is None:
        return "same" if a_value == b_value else "changed"
    return "same" if float(a_value) == float(b_value) else "changed"


def json_equal_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def check_status(a_value: Any, b_value: Any) -> str:
    if a_value is None or b_value is None:
        return "missing"
    if json_equal_value(a_value) == json_equal_value(b_value):
        return "match"
    return "mismatch"


def compatibility_check(name: str, title: str, a_value: Any, b_value: Any, a_source=None, b_source=None) -> dict[str, Any]:
    return {
        "id": name,
        "title": title,
        "status": check_status(a_value, b_value),
        RUN_A: {"value": a_value, "source": a_source},
        RUN_B: {"value": b_value, "source": b_source},
    }


def build_compatibility(
    a_evidence: RunEvidence,
    b_evidence: RunEvidence,
    a_provenance: dict[str, Any] | None,
    b_provenance: dict[str, Any] | None,
) -> dict[str, Any]:
    a_scope, a_scope_source = a_evidence.comparison_metric_scope()
    b_scope, b_scope_source = b_evidence.comparison_metric_scope()
    checks = [
        compatibility_check(
            "cann_version",
            "CANN version",
            sourced_value((a_provenance or {}).get("cann_version")),
            sourced_value((b_provenance or {}).get("cann_version")),
            source_ref((a_provenance or {}).get("cann_version")),
            source_ref((b_provenance or {}).get("cann_version")),
        ),
        compatibility_check(
            "hardware_summary",
            "Hardware summary",
            sourced_value(((a_provenance or {}).get("hardware") or {}).get("summary")),
            sourced_value(((b_provenance or {}).get("hardware") or {}).get("summary")),
            source_ref(((a_provenance or {}).get("hardware") or {}).get("summary")),
            source_ref(((b_provenance or {}).get("hardware") or {}).get("summary")),
        ),
        compatibility_check(
            "profile_command",
            "Profile command",
            sourced_value((a_provenance or {}).get("profile_command")),
            sourced_value((b_provenance or {}).get("profile_command")),
            source_ref((a_provenance or {}).get("profile_command")),
            source_ref((b_provenance or {}).get("profile_command")),
        ),
        compatibility_check(
            "metric_scope",
            "Metric scope",
            a_scope,
            b_scope,
            a_scope_source,
            b_scope_source,
        ),
        compatibility_check(
            "profile_output_segments",
            "Profile output segments",
            (a_provenance or {}).get("profile_output_segments"),
            (b_provenance or {}).get("profile_output_segments"),
            {"artifact": "analysis/provenance.json", "field": "profile_output_segments"} if a_provenance else None,
            {"artifact": "analysis/provenance.json", "field": "profile_output_segments"} if b_provenance else None,
        ),
    ]
    statuses = {check["status"] for check in checks}
    if "mismatch" in statuses:
        status = "warning"
    elif "missing" in statuses:
        status = "incomplete"
    else:
        status = "compatible"
    return {"status": status, "checks": checks}


def headline_groups(a_evidence: RunEvidence, b_evidence: RunEvidence) -> list[str]:
    names = a_evidence.headline_group_names() | b_evidence.headline_group_names()
    ordered = [name for name in HEADLINE_GROUP_ORDER if name in names]
    ordered.extend(sorted(names - set(ordered)))
    return ordered


def compare_headlines(a_evidence: RunEvidence, b_evidence: RunEvidence) -> list[dict[str, Any]]:
    rows = []
    for group in headline_groups(a_evidence, b_evidence):
        a_item = a_evidence.comparison_headline_record(group)
        b_item = b_evidence.comparison_headline_record(group)
        numeric = compare_numeric(a_item.get("value"), b_item.get("value"))
        rows.append(
            {
                "group": group,
                "status": comparison_status(
                    a_item.get("present", False),
                    b_item.get("present", False),
                    a_item.get("value"),
                    b_item.get("value"),
                ),
                RUN_A: a_item,
                RUN_B: b_item,
                **numeric,
            }
        )
    return rows


def context_value(context: dict[str, Any] | None, path: list[str]) -> Any:
    value: Any = context
    for part in path:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def compare_field(field_id: str, title: str, a_value: Any, b_value: Any) -> dict[str, Any]:
    numeric = compare_numeric(a_value, b_value)
    return {
        "id": field_id,
        "title": title,
        "status": check_status(a_value, b_value),
        RUN_A: a_value,
        RUN_B: b_value,
        **numeric,
    }


def compare_mapping(prefix: str, title_prefix: str, a_mapping: Any, b_mapping: Any) -> list[dict[str, Any]]:
    if not isinstance(a_mapping, dict):
        a_mapping = {}
    if not isinstance(b_mapping, dict):
        b_mapping = {}
    fields = sorted(set(a_mapping) | set(b_mapping))
    return [
        compare_field(f"{prefix}.{field}", f"{title_prefix} {field}", a_mapping.get(field), b_mapping.get(field))
        for field in fields
    ]


def maxima_by_field(context: dict[str, Any] | None) -> dict[str, Any]:
    maxima = context_value(context, ["benchmark", "correctness", "maxima"])
    if not isinstance(maxima, list):
        return {}
    result = {}
    for item in maxima:
        if isinstance(item, dict) and item.get("field"):
            result[str(item["field"])] = item.get("value")
    return result


def correctness_passed(context: dict[str, Any] | None) -> bool | None:
    raw = context_value(context, ["benchmark", "correctness", "raw"])
    if isinstance(raw, dict):
        passed = raw.get("passed")
        return passed if isinstance(passed, bool) else None
    return raw if isinstance(raw, bool) else None


def payload_comparison(a_context: dict[str, Any] | None, b_context: dict[str, Any] | None) -> dict[str, Any]:
    return compare_field(
        "payload.sha256",
        "Payload sha256",
        context_value(a_context, ["sources", "payload", "sha256"]),
        context_value(b_context, ["sources", "payload", "sha256"]),
    )


def jit_config_comparison(a_context: dict[str, Any] | None, b_context: dict[str, Any] | None) -> dict[str, Any]:
    return compare_field(
        "jit_config",
        "JIT config",
        context_value(a_context, ["benchmark", "jit_config"]),
        context_value(b_context, ["benchmark", "jit_config"]),
    )


def aggregate_status(rows: list[dict[str, Any]]) -> str:
    return "match" if all(item["status"] == "match" for item in rows) else "warning"


def compare_benchmark(a_context: dict[str, Any] | None, b_context: dict[str, Any] | None) -> dict[str, Any]:
    if a_context is None or b_context is None:
        return {
            "status": "incomplete",
            "workload": [],
            "runtime": [],
            "correctness": [],
            "payload": payload_comparison(a_context, b_context),
            "jit_config": jit_config_comparison(a_context, b_context),
        }

    workload = [
        compare_field(f"workload.{field}", f"Workload {field}", context_value(a_context, ["benchmark", "workload", field]), context_value(b_context, ["benchmark", "workload", field]))
        for field in ["id", "shape", "dtype", "case_count"]
    ]
    runtime = [
        compare_field("candidate.runtime", "Candidate runtime", context_value(a_context, ["benchmark", "candidate", "runtime"]), context_value(b_context, ["benchmark", "candidate", "runtime"])),
        compare_field("candidate.ref_runtime", "Reference runtime", context_value(a_context, ["benchmark", "candidate", "ref_runtime"]), context_value(b_context, ["benchmark", "candidate", "ref_runtime"])),
        compare_field("candidate.speedup", "Speedup", context_value(a_context, ["benchmark", "candidate", "speedup"]), context_value(b_context, ["benchmark", "candidate", "speedup"])),
        *compare_mapping(
            "candidate.runtime_stats",
            "Runtime stat",
            context_value(a_context, ["benchmark", "candidate", "runtime_stats"]),
            context_value(b_context, ["benchmark", "candidate", "runtime_stats"]),
        ),
    ]
    correctness = [
        compare_field(
            "correctness.passed",
            "Correctness passed",
            correctness_passed(a_context),
            correctness_passed(b_context),
        ),
        *compare_mapping("correctness.maxima", "Correctness maximum", maxima_by_field(a_context), maxima_by_field(b_context)),
    ]
    payload = payload_comparison(a_context, b_context)
    jit_config = jit_config_comparison(a_context, b_context)
    sections = [*workload, *runtime, *correctness, payload, jit_config]
    return {
        "status": aggregate_status(sections),
        "workload": workload,
        "runtime": runtime,
        "correctness": correctness,
        "payload": payload,
        "jit_config": jit_config,
    }


def build_comparison(
    run_dir_a: Path,
    run_dir_b: Path,
    *,
    min_speedup_pct: float = DEFAULT_MIN_SPEEDUP_PCT,
) -> dict[str, Any]:
    warnings: list[str] = []
    try:
        a_evidence = RunEvidence.load(run_dir_a)
        b_evidence = RunEvidence.load(run_dir_b)
    except RunEvidenceError as exc:
        raise SystemExit(str(exc)) from exc
    warnings.extend(f"{RUN_A}: {warning}" for warning in _comparison_warnings(a_evidence))
    warnings.extend(f"{RUN_B}: {warning}" for warning in _comparison_warnings(b_evidence))
    a_summary = a_evidence.summary()
    b_summary = b_evidence.summary()
    a_provenance = a_evidence.provenance()
    b_provenance = b_evidence.provenance()
    a_context = a_evidence.tilelang_context()
    b_context = b_evidence.tilelang_context()
    a_raw_index = a_evidence.raw_artifact_index()
    b_raw_index = b_evidence.raw_artifact_index()

    verdict = comparison_verdict(
        a_summary,
        b_summary,
        a_context,
        b_context,
        a_raw_index,
        b_raw_index,
        a_provenance,
        b_provenance,
        min_speedup_pct=min_speedup_pct,
    )
    comparison = {
        "comparison_schema_version": COMPARISON_SCHEMA_VERSION,
        "runs": {
            RUN_A: {
                "role": "baseline",
                "label": run_dir_a.name,
                "run_dir": run_display(run_dir_a),
                "artifacts": {
                    "summary": "analysis/summary.json",
                    "provenance": a_evidence.artifact_presence()["provenance"],
                    "tilelang_context": a_evidence.artifact_presence()["tilelang_context"],
                    "raw_artifact_index": a_evidence.artifact_presence()["raw_artifact_index"],
                },
            },
            RUN_B: {
                "role": "candidate",
                "label": run_dir_b.name,
                "run_dir": run_display(run_dir_b),
                "artifacts": {
                    "summary": "analysis/summary.json",
                    "provenance": b_evidence.artifact_presence()["provenance"],
                    "tilelang_context": b_evidence.artifact_presence()["tilelang_context"],
                    "raw_artifact_index": b_evidence.artifact_presence()["raw_artifact_index"],
                },
            },
        },
        "compatibility": build_compatibility(a_evidence, b_evidence, a_provenance, b_provenance),
        "benchmark": compare_benchmark(a_context, b_context),
        "headlines": compare_headlines(a_evidence, b_evidence),
        "evidence": {
            RUN_A: a_evidence.summary_evidence(),
            RUN_B: b_evidence.summary_evidence(),
        },
        "design_feedback": build_comparison_design_feedback(
            a_summary,
            b_summary,
            a_context,
            b_context,
            a_raw_index,
            b_raw_index,
            a_provenance,
            b_provenance,
            verdict.get("compatibility"),
        ),
        "verdict": verdict,
        "warnings": warnings,
    }
    return comparison


def _comparison_warnings(evidence: RunEvidence) -> list[str]:
    return [warning for warning in evidence.warnings() if "analysis/profile_context.json" not in warning]


def md_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, (dict, list)):
        return "`" + json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "`"
    return "`" + str(value).replace("|", "\\|") + "`"


def md_num(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{float(value):.6g}"
    return str(value)


def render_field_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = ["| Field | A | B | Status | Delta | Delta % |", "|---|---:|---:|---|---:|---:|"]
    for row in rows:
        lines.append(
            f"| {row['title']} | {md_value(row.get(RUN_A))} | {md_value(row.get(RUN_B))} | "
            f"{row['status']} | {md_num(row.get('delta'))} | {md_num(row.get('delta_pct'))} |"
        )
    return lines


def render_markdown(comparison: dict[str, Any]) -> str:
    lines = ["# Ascend Run Comparison", ""]
    a_run = comparison["runs"][RUN_A]
    b_run = comparison["runs"][RUN_B]
    verdict = comparison.get("verdict", {})
    lines.extend(
        [
            f"- A baseline: `{a_run['label']}` ({a_run['run_dir']})",
            f"- B candidate: `{b_run['label']}` ({b_run['run_dir']})",
            f"- Comparison schema: `{comparison['comparison_schema_version']}`",
            f"- Verdict: `{verdict.get('decision', 'n/a')}`",
            "",
            "## Verdict",
            "",
            f"- Policy: `{verdict.get('policy', 'n/a')}`",
            f"- Can compare: `{verdict.get('can_compare', False)}`",
            f"- Candidate speedup percent: {md_num(verdict.get('candidate_speedup_pct'))}",
            f"- Minimum speedup threshold: {md_num(verdict.get('min_speedup_pct'))}",
            "",
        ]
    )
    reasons = verdict.get("reasons") if isinstance(verdict.get("reasons"), list) else []
    if reasons:
        lines.extend(f"- {reason}" for reason in reasons)
        lines.append("")
    lines.extend(
        [
            "## Compatibility",
            "",
            f"Status: `{comparison['compatibility']['status']}`",
            "",
            "| Check | Status | A | B |",
            "|---|---|---|---|",
        ]
    )
    for check in comparison["compatibility"]["checks"]:
        lines.append(
            f"| {check['title']} | {check['status']} | {md_value(check[RUN_A]['value'])} | "
            f"{md_value(check[RUN_B]['value'])} |"
        )

    lines.extend(["", "## Benchmark Context", "", f"Status: `{comparison['benchmark']['status']}`", ""])
    for title, key in [
        ("### Workload", "workload"),
        ("### Runtime", "runtime"),
        ("### Correctness", "correctness"),
    ]:
        rows = comparison["benchmark"].get(key) or []
        lines.extend([title, ""])
        if rows:
            lines.extend(render_field_table(rows))
        else:
            lines.append("No comparable fields recorded.")
        lines.append("")
    lines.extend(
        [
            "### Payload And JIT",
            "",
            *render_field_table([comparison["benchmark"]["payload"], comparison["benchmark"]["jit_config"]]),
            "",
            "## Profiler Headlines",
            "",
            "| Group | Status | Segment A | Segment B | Field | A | B | Delta | Delta % | Artifact A | Artifact B |",
            "|---|---|---|---|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in comparison["headlines"]:
        a_item = row[RUN_A]
        b_item = row[RUN_B]
        lines.append(
            f"| {row['group']} | {row['status']} | {md_value(a_item.get('segment'))} | "
            f"{md_value(b_item.get('segment'))} | {md_value(b_item.get('field') or a_item.get('field'))} | "
            f"{md_value(a_item.get('value'))} | {md_value(b_item.get('value'))} | "
            f"{md_num(row.get('delta'))} | {md_num(row.get('delta_pct'))} | "
            f"{md_value(a_item.get('artifact'))} | {md_value(b_item.get('artifact'))} |"
        )

    lines.extend(["", "## Evidence Status", ""])
    for label, title in [(RUN_A, "A"), (RUN_B, "B")]:
        evidence = comparison["evidence"][label]
        raw_index = evidence["raw_artifact_index"]
        lines.extend(
            [
                f"### {title}",
                "",
                f"- Summary warnings: {len(evidence['summary_warnings'])}",
                f"- Evidence readiness: `{evidence['evidence_readiness']['level']}`",
                f"- Material evidence families: {len(evidence['evidence_readiness']['material_evidence_families'])}",
                f"- Pending collection actions: {len(evidence['pending_collection_actions'])}",
                f"- Raw artifact index present: `{raw_index['present']}`",
            ]
        )
        if raw_index["present"]:
            lines.append(f"- Raw artifact count: {raw_index['artifact_count']}")
        lines.append("")

    lines.extend([*render_design_feedback_markdown(comparison.get("design_feedback") or {}), "", "## Warnings", ""])
    if comparison["warnings"]:
        for warning in comparison["warnings"]:
            lines.append(f"- {warning}")
    else:
        lines.append("No comparison warnings.")
    return "\n".join(lines) + "\n"


def output_stem(run_dir_a: Path, run_dir_b: Path) -> str:
    return f"compare_{run_dir_a.name}_vs_{run_dir_b.name}"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir-a", type=Path, required=True)
    ap.add_argument("--run-dir-b", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--min-speedup-pct", type=float, default=DEFAULT_MIN_SPEEDUP_PCT)
    args = ap.parse_args(argv)
    try:
        min_speedup_pct = normalize_min_speedup_pct(args.min_speedup_pct)
    except ValueError as exc:
        ap.error(str(exc))

    comparison = sanitize_json_value(
        build_comparison(args.run_dir_a, args.run_dir_b, min_speedup_pct=min_speedup_pct)
    )
    out_dir = args.out_dir or analysis_dir(args.run_dir_b.resolve())
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = output_stem(args.run_dir_a, args.run_dir_b)
    json_out = out_dir / f"{stem}.json"
    md_out = out_dir / f"{stem}.md"
    json_out.write_text(json.dumps(comparison, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    md_out.write_text(render_markdown(comparison), encoding="utf-8")
    print(f"wrote {json_out}")
    print(f"wrote {md_out}")


if __name__ == "__main__":
    main()
