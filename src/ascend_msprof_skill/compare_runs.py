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
    build_comparison_design_feedback_from_evidence,
    comparison_verdict_from_evidence,
    normalize_min_speedup_pct,
    render_design_feedback_markdown,
    sanitize_json_value,
    try_float,
)
from .run_evidence import (
    ComparisonFacts,
    ComparisonFieldFact,
    ComparisonRoleFacts,
    CompatibilityValueFact,
    RunEvidence,
    RunEvidenceError,
)


COMPARISON_SCHEMA_VERSION = "1.4"
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


def compatibility_check(
    name: str,
    title: str,
    a_fact: CompatibilityValueFact,
    b_fact: CompatibilityValueFact,
) -> dict[str, Any]:
    return {
        "id": name,
        "title": title,
        "status": check_status(a_fact.value, b_fact.value),
        RUN_A: {"value": a_fact.value, "source": a_fact.source},
        RUN_B: {"value": b_fact.value, "source": b_fact.source},
    }


def build_compatibility(a_run: ComparisonRoleFacts, b_run: ComparisonRoleFacts) -> dict[str, Any]:
    a_facts = a_run.compatibility
    b_facts = b_run.compatibility
    checks = [
        compatibility_check(
            "cann_version",
            "CANN version",
            a_facts.cann_version,
            b_facts.cann_version,
        ),
        compatibility_check(
            "hardware_summary",
            "Hardware summary",
            a_facts.hardware_summary,
            b_facts.hardware_summary,
        ),
        compatibility_check(
            "profile_command",
            "Profile command",
            a_facts.profile_command,
            b_facts.profile_command,
        ),
        compatibility_check(
            "metric_scope",
            "Metric scope",
            a_facts.metric_scope,
            b_facts.metric_scope,
        ),
        compatibility_check(
            "profile_output_segments",
            "Profile output segments",
            a_facts.profile_output_segments,
            b_facts.profile_output_segments,
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


def headline_comparison_reasons(a_item: dict[str, Any], b_item: dict[str, Any]) -> list[str]:
    reasons = []
    for key in ("field", "field_kind", "name", "segment", "metric_scope"):
        a_value, b_value = a_item.get(key), b_item.get(key)
        if a_value in (None, "") or b_value in (None, ""):
            reasons.append(f"{key} missing")
        elif a_value != b_value:
            reasons.append(f"{key} mismatch")
    a_scope, b_scope = a_item.get("block_scope"), b_item.get("block_scope")
    if any(
        scope is None or any(value in (None, "") for value in scope.values())
        for scope in (a_scope, b_scope)
    ):
        reasons.append("block_scope missing")
    elif a_scope != b_scope:
        reasons.append("block_scope mismatch")

    identities = [a_item["target_identity"], b_item["target_identity"]]
    if any(identity.get("status") != "match" for identity in identities):
        reasons.append("target unverified")
    targets = [(identity.get("expected") or {}).get("names") or [] for identity in identities]
    if any(len(names) != 1 for names in targets):
        reasons.append("target ambiguous")
    elif targets[0] != targets[1]:
        reasons.append("target mismatch")
    if try_float(a_item.get("value")) is None or try_float(b_item.get("value")) is None:
        reasons.append("finite numeric value missing")
    return reasons


def compare_headlines(facts: ComparisonFacts) -> list[dict[str, Any]]:
    rows = []
    compatibility = build_compatibility(facts.baseline, facts.candidate)
    profiler_reasons = [
        f"profiler.{check['id']} {check['status']}"
        for check in compatibility["checks"] if check["status"] != "match"
    ]
    for group in facts.headline_groups(tuple(HEADLINE_GROUP_ORDER)):
        a_item = facts.baseline.headline_record(group)
        b_item = facts.candidate.headline_record(group)
        present = a_item.get("present", False) and b_item.get("present", False)
        reasons = [*profiler_reasons, *headline_comparison_reasons(a_item, b_item)] if present else ["headline missing"]
        numeric = compare_numeric(None, None) if reasons else compare_numeric(a_item.get("value"), b_item.get("value"))
        rows.append(
            {
                "group": group,
                "status": ("missing" if not present else "not_comparable") if reasons else comparison_status(
                    a_item.get("present", False),
                    b_item.get("present", False),
                    a_item.get("value"),
                    b_item.get("value"),
                ),
                RUN_A: a_item,
                RUN_B: b_item,
                "comparison_reasons": reasons,
                **numeric,
            }
        )
    return rows


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


def aggregate_status(rows: list[dict[str, Any]]) -> str:
    return "match" if all(item["status"] == "match" for item in rows) else "warning"


def compare_fact(a_fact: ComparisonFieldFact, b_fact: ComparisonFieldFact) -> dict[str, Any]:
    return compare_field(a_fact.id, a_fact.title, a_fact.value, b_fact.value)


def compare_fact_group(
    a_facts: tuple[ComparisonFieldFact, ...],
    b_facts: tuple[ComparisonFieldFact, ...],
) -> list[dict[str, Any]]:
    by_id: dict[str, tuple[ComparisonFieldFact | None, ComparisonFieldFact | None]] = {}
    for fact in a_facts:
        by_id[fact.id] = (fact, None)
    for fact in b_facts:
        a_fact, _ = by_id.get(fact.id, (None, None))
        by_id[fact.id] = (a_fact, fact)

    rows = []
    for a_fact, b_fact in sorted(
        by_id.values(),
        key=lambda pair: (
            min(item.order for item in pair if item is not None),
            (pair[0] or pair[1]).id,
        ),
    ):
        fact = a_fact or b_fact
        if fact is None:
            continue
        rows.append(
            compare_field(
                fact.id,
                fact.title,
                a_fact.value if a_fact is not None else None,
                b_fact.value if b_fact is not None else None,
            )
        )
    return rows


def compare_benchmark(a_run: ComparisonRoleFacts, b_run: ComparisonRoleFacts) -> dict[str, Any]:
    a_facts = a_run.benchmark
    b_facts = b_run.benchmark
    if not a_facts.present or not b_facts.present:
        return {
            "status": "incomplete",
            "workload": [],
            "runtime": [],
            "correctness": [],
            "payload": compare_fact(a_facts.payload, b_facts.payload),
            "jit_config": compare_fact(a_facts.jit_config, b_facts.jit_config),
        }

    workload = compare_fact_group(a_facts.workload, b_facts.workload)
    runtime = compare_fact_group(a_facts.runtime, b_facts.runtime)
    correctness = compare_fact_group(a_facts.correctness, b_facts.correctness)
    payload = compare_fact(a_facts.payload, b_facts.payload)
    jit_config = compare_fact(a_facts.jit_config, b_facts.jit_config)
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
    facts = RunEvidence.comparison_facts(a_evidence, b_evidence)
    warnings.extend(facts.labeled_warnings())
    verdict = comparison_verdict_from_evidence(
        facts.baseline.policy_evidence,
        facts.candidate.policy_evidence,
        min_speedup_pct=min_speedup_pct,
    )
    comparison = {
        "comparison_schema_version": COMPARISON_SCHEMA_VERSION,
        "runs": facts.run_summaries(),
        "compatibility": build_compatibility(facts.baseline, facts.candidate),
        "benchmark": compare_benchmark(facts.baseline, facts.candidate),
        "headlines": compare_headlines(facts),
        "evidence": facts.evidence_summaries(),
        "design_feedback": build_comparison_design_feedback_from_evidence(
            facts.baseline.policy_evidence,
            facts.candidate.policy_evidence,
            verdict.get("compatibility"),
        ),
        "verdict": verdict,
        "warnings": warnings,
    }
    return comparison


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
            "| Group | Status | Segment A | Segment B | Field A | Field B | A | B | Delta | Delta % | Artifact A | Artifact B | Reasons |",
            "|---|---|---|---|---|---|---:|---:|---:|---:|---|---|---|",
        ]
    )
    for row in comparison["headlines"]:
        a_item = row[RUN_A]
        b_item = row[RUN_B]
        lines.append(
            f"| {row['group']} | {row['status']} | {md_value(a_item.get('segment'))} | "
            f"{md_value(b_item.get('segment'))} | {md_value(a_item.get('field'))} | {md_value(b_item.get('field'))} | "
            f"{md_value(a_item.get('value'))} | {md_value(b_item.get('value'))} | "
            f"{md_num(row.get('delta'))} | {md_num(row.get('delta_pct'))} | "
            f"{md_value(a_item.get('artifact'))} | {md_value(b_item.get('artifact'))} | "
            f"{md_value('; '.join(row.get('comparison_reasons', [])))} |"
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
