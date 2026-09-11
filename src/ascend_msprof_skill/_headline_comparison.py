"""Scope-local profiler comparison, shared by both assessment consumers."""
from __future__ import annotations
import json
from typing import Any
from .candidate_feedback import try_float
from .run_evidence import (ComparisonFacts, ComparisonRoleFacts, CompatibilityValueFact,
                           RunEvidence, cann_version_status, select_cann_versions)
from .metric_scope_policy import is_msprof_op_command

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
    status = "conflict" if "conflict" in (a_fact.status, b_fact.status) else check_status(a_fact.value, b_fact.value)
    if name == "cann_version":
        status = cann_version_status(a_fact, b_fact)
    return {
        "id": name,
        "title": title,
        "status": status,
        RUN_A: {"value": a_fact.value, "source": a_fact.source},
        RUN_B: {"value": b_fact.value, "source": b_fact.source},
    }


def build_compatibility(a_run: ComparisonRoleFacts, b_run: ComparisonRoleFacts) -> dict[str, Any]:
    a_facts = a_run.compatibility
    b_facts = b_run.compatibility
    a_version, b_version = select_cann_versions(a_facts, b_facts)
    checks = [
        compatibility_check(
            "cann_version",
            "CANN version",
            a_version,
            b_version,
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
    if statuses & {"mismatch", "conflict", "component_mismatch"}:
        status = "warning"
    elif "missing" in statuses:
        status = "incomplete"
    else:
        status = "compatible"
    return {"status": status, "checks": checks}


def headline_comparison_reasons(a_item: dict[str, Any], b_item: dict[str, Any]) -> list[str]:
    reasons = list(dict.fromkeys(issue["reason"] for item in (a_item, b_item) for issue in item.get("schema_issues", [])))
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


def compare_headlines(facts: ComparisonFacts, workload_checks: tuple[dict[str, Any], ...] | None = None) -> list[dict[str, Any]]:
    rows = []
    if workload_checks is None:
        workload_checks = RunEvidence.workload_checks(facts.baseline.policy_evidence, facts.candidate.policy_evidence)
    workload_reasons = [f"{check['id']} {check['status']}" for check in workload_checks if check["status"] != "match"]
    compatibility = build_compatibility(facts.baseline, facts.candidate)
    profiler_reasons = [
        f"profiler.{check['id']} {check['status']}"
        for check in compatibility["checks"] if check["id"] in {"cann_version", "hardware_summary"} and check["status"] != "match"
    ]
    for group in facts.headline_groups(tuple(HEADLINE_GROUP_ORDER)):
        a_item = facts.baseline.headline_record(group)
        b_item = facts.candidate.headline_record(group)
        present = a_item.get("present", False) and b_item.get("present", False)
        scoped_checks = segment_checks(facts.baseline.policy_evidence, facts.candidate.policy_evidence, a_item.get("segment")) if present else []
        scoped_reasons = [f"profiler.{c['id']} {c['status']}" for c in scoped_checks if c["status"] != "match"]
        reasons = [*workload_reasons, *profiler_reasons, *scoped_reasons, *headline_comparison_reasons(a_item, b_item)] if present else ["headline missing"]
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
                "checks": scoped_checks,
                **numeric,
            }
        )
    return rows



def segment_checks(a: RunEvidence, b: RunEvidence, segment: str | None) -> list[dict[str, Any]]:
    segment = segment if isinstance(segment, str) else None
    def facts(run: RunEvidence) -> tuple[CompatibilityValueFact, CompatibilityValueFact]:
        compatibility = run.comparison_compatibility()
        segments = compatibility.profile_output_segments.value
        item = None
        field = f"profile_output_segments.{segment}"
        if isinstance(segments, dict) and segment:
            if segment.startswith("followup:"):
                action = segment.removeprefix("followup:")
                followups = segments.get("followups", {})
                item = followups.get(action) if isinstance(followups, dict) else None
                field = f"profile_output_segments.followups.{action}"
            else:
                item = segments.get(segment)
        command = run.segment_commands.get(segment)
        if command is None:
            candidate = compatibility.profile_command
            if isinstance(candidate.value, str):
                command_segment = "op" if is_msprof_op_command(candidate.value) else "app"
                if segment == command_segment:
                    command = candidate
        return (CompatibilityValueFact(item, {"artifact": "analysis/provenance.json", "field_ref": field}),
                command or CompatibilityValueFact(None, None))
    left, right = facts(a), facts(b)
    return [compatibility_check(f"segment.{segment}.{name}", name, left[i], right[i])
            for i, name in enumerate(("output", "command"))]
