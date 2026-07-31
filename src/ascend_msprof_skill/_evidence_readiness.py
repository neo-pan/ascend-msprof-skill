"""Evidence readiness and next collection policy for Evidence Model analysis."""
from __future__ import annotations

from pathlib import Path

from ._profiler_segments import followup_action_from_segment
from .ascend_profile_utils import normalized_key, read_json
from .metric_scope_policy import (
    APP_TIMING_ARTIFACTS,
    APP_TIMING_CONTRACT,
    metric_scope_policy,
    missing_artifact_labels,
    warning_group,
)
from ._evidence_signals import OP_METRIC_GROUPS, READINESS_LEVEL_ORDER


READINESS_COVERAGE_FAMILIES = {
    "pipe_utilization": ("pipe_utilization",),
    "arithmetic_utilization": ("arithmetic_utilization",),
    "memory_cache": ("memory", "l2_cache"),
    "resource_conflict": ("resource_conflict",),
}

DEFAULT_FOLLOWUP_GROUPS = ("arithmetic_utilization", "memory", "resource_conflict")


def missing_groups_from_warnings(summary: dict) -> set[str]:
    groups = set()
    for warning in summary.get("warnings", []):
        group = warning_group(str(warning))
        if group:
            groups.add(group)
    return groups


def scope_evidence(scope: dict) -> list[dict]:
    return [
        {
            "evidence_id": "ev_01_metric_scope",
            "artifact": scope.get("artifact"),
            "field": scope.get("field_ref"),
            "field_ref": scope.get("field_ref"),
            "signal": f"--aic-metrics={scope.get('value')}",
            "value": scope.get("value"),
        }
    ]


def missing_warning_evidence(summary: dict, groups: list[str], start_index: int = 2) -> list[dict]:
    evidence = []
    warnings = [str(warning) for warning in summary.get("warnings", [])]
    for group in groups:
        prefix = f"missing {group}:"
        warning = next((item for item in warnings if item.startswith(prefix)), None)
        if not warning:
            continue
        evidence.append(
            {
                "evidence_id": f"ev_{start_index + len(evidence):02d}_missing_{normalized_key(group)}",
                "artifact": "analysis/summary.json",
                "field": "warnings",
                "field_ref": f"warnings[] startswith {prefix}",
                "signal": warning,
                "value": None,
            }
        )
    return evidence


def missing_stdout_evidence(summary: dict, sections: tuple[str, ...], start_index: int = 2) -> list[dict]:
    evidence = []
    stdout_sections = summary.get("stdout_sections", {})
    if not isinstance(stdout_sections, dict):
        stdout_sections = {}
    for section in sections:
        if stdout_sections.get(section):
            continue
        evidence.append(
            {
                "evidence_id": f"ev_{start_index + len(evidence):02d}_missing_{normalized_key(section)}",
                "artifact": "analysis/summary.json",
                "field": f"stdout_sections.{section}",
                "field_ref": f"stdout_sections.{section}",
                "signal": f"missing stdout section {section}",
                "value": None,
            }
        )
    return evidence


def missing_complete_program_coverage_evidence(
    summary: dict,
    groups: list[str],
    start_index: int = 2,
) -> list[dict]:
    coverage = summary.get("profile_coverage")
    if not isinstance(coverage, dict) or not coverage.get("explicit_target"):
        return []
    selected = coverage.get("selected_segments_by_family") or {}
    evidence = []
    for group in groups:
        if selected.get(group):
            continue
        field_ref = f"profile_coverage.selected_segments_by_family.{group}"
        evidence.append(
            {
                "evidence_id": f"ev_{start_index + len(evidence):02d}_missing_complete_{normalized_key(group)}",
                "artifact": "analysis/summary.json",
                "field": field_ref,
                "field_ref": field_ref,
                "signal": f"missing complete-program {group} coverage",
                "value": None,
            }
        )
    return evidence


def missing_default_followup_groups(summary: dict, missing_groups: set[str]) -> list[str]:
    coverage = summary.get("profile_coverage")
    if not isinstance(coverage, dict) or not coverage.get("explicit_target"):
        return [group for group in DEFAULT_FOLLOWUP_GROUPS if group in missing_groups]
    selected = coverage.get("selected_segments_by_family") or {}
    return [
        group
        for group in DEFAULT_FOLLOWUP_GROUPS
        if group in missing_groups or not selected.get(group)
    ]


def collect_action(
    action_id: str,
    reason: str,
    recommended_aic_metrics: list[str],
    required_groups: list[str],
    evidence: list[dict],
    confidence: str,
    *,
    necessity: str,
    unlocks_claims: list[str],
    target_scope: dict,
    estimated_cost: dict,
) -> dict:
    return {
        "id": action_id,
        "reason": reason,
        "recommended_aic_metrics": recommended_aic_metrics,
        "required_artifacts": missing_artifact_labels(required_groups),
        "evidence": evidence,
        "confidence": confidence,
        "necessity": necessity,
        "unlocks_claims": unlocks_claims,
        "target_scope": target_scope,
        "estimated_cost": estimated_cost,
    }


def collection_target_scope(summary: dict) -> dict:
    coverage = summary.get("profile_coverage")
    if isinstance(coverage, dict) and coverage.get("explicit_target"):
        return {
            "kind": "complete_program",
            "kernel_selector": coverage.get("kernel_selector"),
            "expected_launches": coverage.get("expected_counts") or {},
            "expected_total": coverage.get("expected_total"),
        }
    return {"kind": "observed_run"}


def collection_estimated_cost(summary: dict, scopes: list[str], *, segments: int = 1) -> dict:
    coverage = summary.get("profile_coverage")
    launches = coverage.get("expected_total") if isinstance(coverage, dict) else None
    return {
        "estimated_launches": launches,
        "metric_scopes": scopes,
        "segments": segments,
    }


def build_next_collection_actions(summary: dict) -> list[dict]:
    scope = summary.get("metric_scope")
    if not isinstance(scope, dict):
        return []
    policy = metric_scope_policy(scope.get("value"))
    if not policy:
        return []

    missing_groups = missing_groups_from_warnings(summary)
    actions = []
    required_missing = [group for group in policy.required_artifacts if group in missing_groups]
    required_stdout_missing = []
    if policy.scope in {"Occupancy", "Roofline"}:
        required_stdout_missing = [
            section
            for section in policy.stdout_sections
            if not summary.get("stdout_sections", {}).get(section)
        ]
    if required_missing or required_stdout_missing:
        action_groups = list(required_missing) + list(required_stdout_missing)
        evidence = scope_evidence(scope)
        evidence.extend(missing_warning_evidence(summary, list(required_missing), len(evidence) + 1))
        evidence.extend(missing_stdout_evidence(summary, tuple(required_stdout_missing), len(evidence) + 1))
        actions.append(
            collect_action(
                f"recollect_{normalized_key(policy.scope)}",
                f"Selected {policy.scope} scope is missing expected evidence; recollect before relying on this scope.",
                [policy.scope],
                action_groups,
                evidence,
                "medium",
                necessity="blocking",
                unlocks_claims=[f"rely on selected {policy.scope} metric scope"],
                target_scope=collection_target_scope(summary),
                estimated_cost=collection_estimated_cost(summary, [policy.scope]),
            )
        )

    if policy.scope == "PipeUtilization":
        optional_followup_groups = missing_default_followup_groups(summary, missing_groups)
        if optional_followup_groups:
            evidence = scope_evidence(scope)
            evidence.extend(missing_warning_evidence(summary, optional_followup_groups, len(evidence) + 1))
            evidence.extend(
                missing_complete_program_coverage_evidence(
                    summary,
                    optional_followup_groups,
                    len(evidence) + 1,
                )
            )
            actions.append(
                collect_action(
                    "collect_default_metric_followup",
                    (
                        "PipeUtilization-only evidence leaves arithmetic, memory, or conflict "
                        "families uncollected; select Default depth when the current code-change hypothesis needs them."
                    ),
                    ["Default"],
                    optional_followup_groups,
                    evidence,
                    "low",
                    necessity="hypothesis_required",
                    unlocks_claims=[
                        "inspect arithmetic utilization direction",
                        "inspect memory/cache movement direction",
                        "inspect resource conflict direction",
                    ],
                    target_scope=collection_target_scope(summary),
                    estimated_cost=collection_estimated_cost(summary, ["Default"]),
                )
            )

    return actions


def has_headline(summary: dict, group: str) -> bool:
    return isinstance((summary.get("headlines") or {}).get(group), dict)


def has_headline_value(summary: dict, group: str) -> bool:
    headline = (summary.get("headlines") or {}).get(group)
    return isinstance(headline, dict) and headline.get("value") is not None


def parsed_artifact_groups(raw_artifact_index: dict) -> set[str]:
    groups = set()
    for item in raw_artifact_index.get("artifacts", []):
        if not isinstance(item, dict):
            continue
        if item.get("status") != "parsed":
            continue
        group = item.get("group")
        if group:
            groups.add(str(group))
    return groups


def available_evidence_families(summary: dict, raw_artifact_index: dict) -> list[str]:
    parsed_groups = parsed_artifact_groups(raw_artifact_index)
    out = []
    if any(has_headline(summary, group) for group in APP_TIMING_ARTIFACTS):
        out.append("app_timing")
    if has_headline(summary, "op_basic_info"):
        out.append("operator_metadata")
    if has_headline(summary, "pipe_utilization"):
        out.append("pipe_utilization")
    if has_headline(summary, "arithmetic_utilization"):
        out.append("arithmetic_utilization")
    if has_headline(summary, "memory") or has_headline(summary, "l2_cache"):
        out.append("memory_cache")
    if has_headline(summary, "resource_conflict"):
        out.append("resource_conflict")
    if "simulator_trace" in parsed_groups or "simulator_csv" in parsed_groups:
        out.append("simulator_source_pipeline")
    stdout_sections = summary.get("stdout_sections") or {}
    if isinstance(stdout_sections.get("occupancy_summary"), dict):
        out.append("stdout_occupancy_summary")
    if isinstance(stdout_sections.get("roofline_summary"), dict):
        out.append("stdout_roofline_summary")
    if isinstance(stdout_sections.get("performance_summary"), dict):
        out.append("stdout_performance_summary")
    return out


def workload_context_available(run_dir: Path) -> bool:
    for name in ["profile_context.json", "tilelang_context.json"]:
        path = run_dir / "analysis" / name
        if not path.is_file():
            continue
        try:
            payload = read_json(path)
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and payload:
            return True
    return False


def readiness_segment_status(missing_required: list[str], present_required: list[str], present_optional: list[str]) -> str:
    if missing_required and (present_required or present_optional):
        return "partial"
    if missing_required:
        return "missing_required_artifacts"
    return "ready"


def readiness_stage_for_app(summary: dict) -> dict:
    required = list(APP_TIMING_ARTIFACTS)
    present_required = [group for group in required if has_headline(summary, group)]
    missing_required = [] if present_required else required
    return {
        "segment": "app",
        "metric_scope": APP_TIMING_CONTRACT["scope"],
        "status": "ready" if present_required else "missing_required_artifacts",
        "missing_required_artifacts": missing_artifact_labels(missing_required),
    }


def segment_artifacts(raw_artifact_index: dict, segment: str) -> list[dict]:
    return [
        item
        for item in raw_artifact_index.get("artifacts", [])
        if isinstance(item, dict) and item.get("segment") == segment
    ]


def readiness_stage_for_scope(
    raw_artifact_index: dict,
    segment: str,
    scope_value: str | None,
) -> dict:
    policy = metric_scope_policy(scope_value)
    artifacts = segment_artifacts(raw_artifact_index, segment)
    groups_present = {
        str(item.get("group"))
        for item in artifacts
        if item.get("status") == "parsed" and item.get("group")
    }
    if not policy:
        return {
            "segment": segment,
            "metric_scope": scope_value,
            "status": "not_applicable",
            "missing_required_artifacts": [],
        }

    present_required = [group for group in policy.required_artifacts if group in groups_present]
    missing_required = [group for group in policy.required_artifacts if group not in groups_present]
    present_optional = [group for group in policy.optional_artifacts if group in groups_present]
    return {
        "segment": segment,
        "metric_scope": policy.scope,
        "status": readiness_segment_status(missing_required, present_required, present_optional),
        "missing_required_artifacts": missing_artifact_labels(missing_required),
    }


def known_scope_segments(summary: dict, raw_artifact_index: dict) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    selected = summary.get("metric_scope")
    if isinstance(selected, dict) and selected.get("value"):
        out.append(("op", str(selected["value"])))
    for item in raw_artifact_index.get("artifacts", []):
        if not isinstance(item, dict):
            continue
        segment = item.get("segment")
        scope = item.get("metric_scope")
        action_id = followup_action_from_segment(segment)
        if action_id is not None and scope:
            pair = (segment, str(scope))
            if pair not in out:
                out.append(pair)
    if not out and any(has_headline(summary, group) for group in ["op_basic_info", *OP_METRIC_GROUPS]):
        out.append(("op", None))
    return out


def readiness_level(families: list[str], target_status: str, has_workload_context: bool) -> str:
    has_timing = "app_timing" in families
    metric_families = {
        "pipe_utilization",
        "arithmetic_utilization",
        "memory_cache",
        "resource_conflict",
    }
    has_metric = any(family in families for family in metric_families)
    has_source = "simulator_source_pipeline" in families
    if not has_timing:
        return "triage_only" if has_metric else "insufficient"
    if not has_metric:
        return "triage_only"
    if target_status in {"mismatch", "partial_mismatch", "missing_observed"}:
        return "triage_only"
    if has_source or has_workload_context:
        return "actionable_experiment"
    return "directional"


def explicit_target_readiness_level(summary: dict, families: list[str], target_status: str) -> str:
    has_timing_or_metric = bool(
        set(families)
        & {
            "app_timing",
            "operator_metadata",
            "pipe_utilization",
            "arithmetic_utilization",
            "memory_cache",
            "resource_conflict",
        }
    )
    if not has_timing_or_metric:
        return "insufficient"
    if target_status in {"mismatch", "partial_mismatch", "missing_observed"}:
        return "triage_only"
    coverage = summary.get("profile_coverage") or {}
    segments = coverage.get("segments") or {}
    app_complete = bool((segments.get("app") or {}).get("count_complete"))
    selected = coverage.get("selected_segments_by_family") or {}
    has_value_backed_selected_metric = any(
        family in families and any(selected.get(coverage_family) for coverage_family in coverage_families)
        for family, coverage_families in READINESS_COVERAGE_FAMILIES.items()
    )
    if app_complete and "app_timing" in families and has_value_backed_selected_metric:
        return "actionable_experiment"
    return "directional"


def explicit_target_readiness_reasons(summary: dict, level: str) -> list[str]:
    coverage = summary.get("profile_coverage") or {}
    segments = coverage.get("segments") or {}
    app_complete = bool((segments.get("app") or {}).get("count_complete"))
    selected = [
        f"{family}:{segment}"
        for family, segment in (coverage.get("selected_segments_by_family") or {}).items()
        if segment
    ]
    reasons = [
        f"Declared app launch coverage is {'complete' if app_complete else 'incomplete'}.",
        (
            "Complete count and per-launch metric coverage is available for " + ", ".join(selected) + "."
            if selected
            else "No operator segment has both complete target counts and complete per-launch metric-family coverage."
        ),
    ]
    if level == "actionable_experiment":
        reasons.append("The relevant declared app/operator evidence pair is complete; correctness and simulator context are not profiling-readiness gates.")
    return reasons


def readiness_reasons(families: list[str], target_status: str, has_workload_context: bool) -> list[str]:
    reasons = []
    if "app_timing" in families:
        reasons.append("Parser-visible application timing evidence is present.")
    else:
        reasons.append("Parser-visible application timing evidence is missing.")
    if any(family in families for family in ["pipe_utilization", "arithmetic_utilization", "memory_cache", "resource_conflict"]):
        reasons.append("At least one parser-visible operator metric family is present.")
    else:
        reasons.append("No parser-visible operator metric family is present.")
    if "simulator_source_pipeline" in families:
        reasons.append("Simulator source or pipeline context is present as raw context.")
    elif has_workload_context:
        reasons.append("Workload or shape context is recorded in analysis context.")
    if target_status in {"mismatch", "partial_mismatch", "missing_observed"}:
        reasons.append(f"Target identity status is {target_status}; optimization claims are limited.")
    return reasons


def missing_evidence_families(
    families: list[str],
    has_workload_context: bool,
    *,
    require_source_context: bool = True,
) -> list[str]:
    required = ["app_timing", "operator_metric"]
    if require_source_context:
        required.append("source_or_workload_context")
    missing = []
    if "app_timing" not in families:
        missing.append("app_timing")
    if not any(family in families for family in ["pipe_utilization", "arithmetic_utilization", "memory_cache", "resource_conflict"]):
        missing.append("operator_metric")
    if require_source_context and "simulator_source_pipeline" not in families and not has_workload_context:
        missing.append("source_or_workload_context")
    return [item for item in required if item in missing]


def claim_lists(level: str, families: list[str]) -> tuple[list[str], list[str]]:
    allowed = []
    blocked = []
    if "app_timing" in families:
        allowed.append("rank application-level hot path")
    else:
        blocked.append("rank hot path without parser-visible timing")
    if "pipe_utilization" in families:
        allowed.append("rank first AI Core pipe inspection direction")
    if "arithmetic_utilization" in families:
        allowed.append("inspect arithmetic utilization direction")
    if "memory_cache" in families:
        allowed.append("inspect memory/cache movement direction")
    if "resource_conflict" in families:
        allowed.append("inspect resource conflict direction")
    if READINESS_LEVEL_ORDER.get(level, 0) < READINESS_LEVEL_ORDER["actionable_experiment"]:
        blocked.append("propose focused kernel code experiment without stronger context")
    if "simulator_source_pipeline" not in families:
        blocked.append("source-line or instruction attribution without simulator/source artifacts")
    return allowed, blocked


def readiness_followups(summary: dict, missing_families: list[str]) -> list[dict]:
    existing = summary.get("next_collection_actions")
    if isinstance(existing, list) and existing:
        return existing
    out = []
    if "app_timing" in missing_families:
        out.append(
            {
                "id": "collect_app_timing",
                "reason": "Collect application-level msprof timing so the hot path is known.",
                "recommended_aic_metrics": [],
                "required_artifacts": list(APP_TIMING_CONTRACT["required_artifacts"]),
                "confidence": "medium",
                "necessity": "blocking",
                "unlocks_claims": ["rank application-level hot path"],
                "target_scope": collection_target_scope(summary),
                "estimated_cost": collection_estimated_cost(summary, [], segments=1),
            }
        )
    if "operator_metric" in missing_families:
        out.append(
            {
                "id": "collect_pipe_utilization",
                "reason": "Collect operator-level PipeUtilization as the minimal AI Core metric family.",
                "recommended_aic_metrics": ["PipeUtilization"],
                "required_artifacts": missing_artifact_labels(("op_basic_info", "pipe_utilization")),
                "confidence": "medium",
                "necessity": "blocking",
                "unlocks_claims": ["rank first AI Core pipe inspection direction"],
                "target_scope": collection_target_scope(summary),
                "estimated_cost": collection_estimated_cost(summary, ["PipeUtilization"]),
            }
        )
    if "source_or_workload_context" in missing_families:
        out.append(
            {
                "id": "collect_source_or_context",
                "reason": "Add simulator/source context or record strong workload/shape context before focused code experiments.",
                "recommended_aic_metrics": ["PipeUtilization"],
                "required_artifacts": ["trace.json or core*_code_exe.csv/core*_instr_exe.csv"],
                "confidence": "low",
                "necessity": "hypothesis_required",
                "unlocks_claims": ["source-line or instruction attribution"],
                "target_scope": collection_target_scope(summary),
                "estimated_cost": collection_estimated_cost(summary, ["PipeUtilization"]),
            }
        )
    return out[:2]


def build_evidence_readiness(run_dir: Path, summary: dict, raw_artifact_index: dict) -> dict:
    families = available_evidence_families(summary, raw_artifact_index)
    target_status = str((summary.get("target_identity") or {}).get("status") or "unknown")
    has_context = workload_context_available(run_dir)
    explicit_target = bool((summary.get("profile_coverage") or {}).get("explicit_target"))
    readiness_families = families
    if explicit_target:
        value_groups = {
            "app_timing": APP_TIMING_ARTIFACTS,
            "operator_metadata": ("op_basic_info",),
            "pipe_utilization": ("pipe_utilization",),
            "arithmetic_utilization": ("arithmetic_utilization",),
            "memory_cache": ("memory", "l2_cache"),
            "resource_conflict": ("resource_conflict",),
        }
        readiness_families = [
            family
            for family in families
            if family not in value_groups
            or any(has_headline_value(summary, group) for group in value_groups[family])
        ]
    level = (
        explicit_target_readiness_level(summary, readiness_families, target_status)
        if explicit_target
        else readiness_level(families, target_status, has_context)
    )
    claim_families = readiness_families
    if explicit_target:
        selected = (summary.get("profile_coverage") or {}).get("selected_segments_by_family") or {}
        claim_families = [
            family
            for family in readiness_families
            if family not in READINESS_COVERAGE_FAMILIES
            or any(
                selected.get(coverage_family)
                for coverage_family in READINESS_COVERAGE_FAMILIES[family]
            )
        ]
    missing_families = missing_evidence_families(
        claim_families,
        has_context,
        require_source_context=not explicit_target,
    )
    allowed, blocked = claim_lists(level, claim_families)
    stages = [readiness_stage_for_app(summary)]
    for segment, scope in known_scope_segments(summary, raw_artifact_index):
        stages.append(readiness_stage_for_scope(raw_artifact_index, segment, scope))
    unparsed = [
        {
            "artifact": item.get("artifact"),
            "segment": item.get("segment"),
            "known_role": item.get("known_role"),
            "diagnosis_role": item.get("diagnosis_role"),
        }
        for item in raw_artifact_index.get("artifacts", [])
        if isinstance(item, dict) and item.get("group") == "unparsed_profiler_binary"
    ]
    if explicit_target:
        coverage_segments = (summary.get("profile_coverage") or {}).get("segments") or {}
        stages = [
            {
                "segment": segment,
                "metric_scope": (coverage.get("metric_scope") if isinstance(coverage, dict) else None),
                "status": (
                    "ready"
                    if isinstance(coverage, dict) and coverage.get("count_complete")
                    else "incomplete_target_coverage"
                ),
                "count_complete": coverage.get("count_complete") if isinstance(coverage, dict) else False,
                "metric_family_completeness": {
                    family: details.get("complete")
                    for family, details in (coverage.get("metric_coverage") or {}).items()
                    if isinstance(details, dict)
                }
                if isinstance(coverage, dict)
                else {},
            }
            for segment, coverage in coverage_segments.items()
        ]
    reasons = readiness_reasons(readiness_families, target_status, has_context)
    if explicit_target:
        reasons.extend(explicit_target_readiness_reasons(summary, level))
    return {
        "schema_version": "1.1" if explicit_target else "1.0",
        "level": level,
        "reasons": reasons,
        "available_evidence_families": readiness_families,
        "missing_evidence_families": missing_families,
        "allowed_claims": allowed,
        "blocked_claims": blocked,
        "recommended_followups": readiness_followups(summary, missing_families),
        "segments": stages,
        "unparsed_binary_artifacts": unparsed,
    }
