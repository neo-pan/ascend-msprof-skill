"""Evidence readiness and next collection policy for Evidence Model analysis."""
from __future__ import annotations

from .analysis_types import EvidenceSignal
from .readiness_types import CollectionAction, EvidenceReadiness
from .summary_types import Summary, SummaryFacts, RawArtifactIndex, IndexedArtifact, SelectedMetricScope, StdoutSections

from ._profiler_segments import followup_action_from_segment
from .ascend_profile_utils import normalized_key
from .metric_scope_policy import (
    APP_TIMING_ARTIFACTS,
    APP_TIMING_CONTRACT,
    metric_scope_policy,
    missing_artifact_labels,
)
from ._evidence_signals import OP_METRIC_GROUPS
from .operator_evidence import OperatorEvidence
from .application_timing import timing_groups


READINESS_COVERAGE_FAMILIES = {
    "pipe_utilization": ("pipe_utilization",),
    "arithmetic_utilization": ("arithmetic_utilization",),
    "memory_cache": ("memory", "l2_cache"),
    "resource_conflict": ("resource_conflict",),
}

DEFAULT_FOLLOWUP_GROUPS = ("arithmetic_utilization", "memory", "resource_conflict")


def missing_artifact_groups(summary: SummaryFacts) -> set[str]:
    """Absence of admitted artifacts, independent of parser validity or prose."""
    return {group for group, headline in summary.headlines.items() if not headline.artifacts}


def scope_evidence(scope: SelectedMetricScope) -> list[dict]:
    return [
        {
            "evidence_id": "ev_01_metric_scope",
            "artifact": scope.artifact,
            "field": scope.field_ref,
            "field_ref": scope.field_ref,
            "signal": f"--aic-metrics={scope.value}",
            "value": scope.value,
        }
    ]


def missing_artifact_evidence(summary: SummaryFacts, groups: list[str], start_index: int = 2) -> list[dict]:
    evidence = []
    missing = missing_artifact_groups(summary)
    for group in groups:
        if group not in missing:
            continue
        evidence.append(
            {
                "evidence_id": f"ev_{start_index + len(evidence):02d}_missing_{normalized_key(group)}",
                "artifact": "analysis/summary.json",
                "field": f"headlines.{group}.artifacts",
                "field_ref": f"headlines.{group}.artifacts",
                "signal": f"no admitted {group} artifacts",
                "value": None,
            }
        )
    return evidence


def missing_stdout_evidence(summary: SummaryFacts, sections: tuple[str, ...], start_index: int = 2) -> list[dict]:
    evidence = []
    stdout_sections = summary.stdout_sections
    for section in sections:
        if getattr(stdout_sections, section):
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
    summary: SummaryFacts,
    groups: list[str],
    start_index: int = 2,
) -> list[dict]:
    coverage = summary.profile_coverage
    if not coverage.explicit_target:
        return []
    selected = coverage.selected_segments_by_family
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


def missing_default_followup_groups(summary: SummaryFacts, missing_groups: set[str]) -> list[str]:
    coverage = summary.profile_coverage
    if not coverage.explicit_target:
        return [group for group in DEFAULT_FOLLOWUP_GROUPS if group in missing_groups]
    selected = coverage.selected_segments_by_family
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
) -> CollectionAction:
    return CollectionAction.model_validate({
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
    })


def collection_target_scope(summary: SummaryFacts) -> dict:
    coverage = summary.profile_coverage
    if coverage.explicit_target:
        return {
            "kind": "complete_program",
            "kernel_selector": coverage.kernel_selector,
            "expected_launches": coverage.expected_counts,
            "expected_total": coverage.expected_total,
        }
    return {"kind": "observed_run"}


def collection_estimated_cost(summary: SummaryFacts, scopes: list[str], *, segments: int = 1) -> dict:
    coverage = summary.profile_coverage
    launches = coverage.expected_total
    return {
        "estimated_launches": launches,
        "metric_scopes": scopes,
        "segments": segments,
    }


def build_next_collection_actions(summary: SummaryFacts) -> tuple[CollectionAction, ...]:
    scope = summary.metric_scope
    if scope is None:
        return ()
    policy = metric_scope_policy(scope.value)
    if not policy:
        return ()

    missing_groups = missing_artifact_groups(summary)
    actions = []
    required_missing = [group for group in policy.required_artifacts if group in missing_groups]
    required_stdout_missing = []
    if policy.scope in {"Occupancy", "Roofline"}:
        required_stdout_missing = [
            section
            for section in policy.stdout_sections
            if not getattr(summary.stdout_sections, section)
        ]
    if required_missing or required_stdout_missing:
        action_groups = list(required_missing) + list(required_stdout_missing)
        evidence = scope_evidence(scope)
        evidence.extend(missing_artifact_evidence(summary, list(required_missing), len(evidence) + 1))
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
            evidence.extend(missing_artifact_evidence(summary, optional_followup_groups, len(evidence) + 1))
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
                        "families uncollected; select Default depth only when these fields are needed to answer the current question."
                    ),
                    ["Default"],
                    optional_followup_groups,
                    evidence,
                    "low",
                    necessity="question_required",
                    unlocks_claims=[
                        "describe recorded arithmetic time and ratios",
                        "describe recorded memory/cache fields",
                        "describe recorded resource conflict fields",
                    ],
                    target_scope=collection_target_scope(summary),
                    estimated_cost=collection_estimated_cost(summary, ["Default"]),
                )
            )

    return tuple(actions)


def has_headline(summary: SummaryFacts, group: str) -> bool:
    item = summary.headlines[group]
    return item.available or (isinstance(item, OperatorEvidence) and any(artifact.metadata for artifact in item.artifacts))


def has_headline_value(summary: SummaryFacts, group: str) -> bool:
    return summary.headlines[group].available


def available_evidence_families(summary: SummaryFacts, raw_artifact_index: RawArtifactIndex | None,
                                simulator_signals: tuple[EvidenceSignal, ...] = ()) -> list[str]:
    parsed_groups = {item.group for item in raw_artifact_index.artifacts if item.status == "parsed"} if raw_artifact_index else set()
    out = []
    if timing_groups(summary.headlines):
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
    if ("simulator_trace" in parsed_groups or "simulator_csv" in parsed_groups
            or any(item.value is not None for item in simulator_signals)):
        out.append("simulator_source_pipeline")
    stdout_sections = summary.stdout_sections
    if stdout_sections.occupancy_summary is not None:
        out.append("stdout_occupancy_summary")
    if stdout_sections.roofline_summary is not None:
        out.append("stdout_roofline_summary")
    if stdout_sections.performance_summary is not None:
        out.append("stdout_performance_summary")
    return out



def readiness_segment_status(missing_required: list[str], present_required: list[str], present_optional: list[str]) -> str:
    if missing_required and (present_required or present_optional):
        return "partial"
    if missing_required:
        return "missing_required_artifacts"
    return "ready"


def readiness_stage_for_app(summary: SummaryFacts) -> dict:
    required = list(APP_TIMING_ARTIFACTS)
    available = timing_groups(summary.headlines)
    present = any(summary.headlines[group].artifacts for group in required)
    return {
        "segment": "app",
        "metric_scope": APP_TIMING_CONTRACT["scope"],
        "status": ("ready" if timing_groups(summary.headlines, unique_scope=True) else "ambiguous_timing") if available else "no_usable_timing" if present else "missing_required_artifacts",
        "missing_required_artifacts": [] if present else missing_artifact_labels(required),
    }


def segment_artifacts(raw_artifact_index: RawArtifactIndex, segment: str) -> list[IndexedArtifact]:
    return [
        item
        for item in raw_artifact_index.artifacts
        if item.segment == segment
    ]


def readiness_stage_for_scope(
    raw_artifact_index: RawArtifactIndex,
    segment: str,
    scope_value: str | None,
) -> dict:
    policy = metric_scope_policy(scope_value)
    artifacts = segment_artifacts(raw_artifact_index, segment)
    groups_present = {
        str(item.group)
        for item in artifacts
        if item.status == "parsed" and item.group
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


def known_scope_segments(summary: SummaryFacts, raw_artifact_index: RawArtifactIndex) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    selected = summary.metric_scope
    if selected is not None:
        out.append(("op", selected.value))
    for item in raw_artifact_index.artifacts:
        segment = item.segment
        scope = item.metric_scope
        action_id = followup_action_from_segment(segment)
        if action_id is not None and scope:
            pair = (segment, str(scope))
            if pair not in out:
                out.append(pair)
    if not out and any(has_headline(summary, group) for group in ["op_basic_info", *OP_METRIC_GROUPS]):
        out.append(("op", None))
    return out


def readiness_level(families: list[str], target_status: str) -> str:
    has_timing = "app_timing" in families
    metric_families = {
        "pipe_utilization",
        "arithmetic_utilization",
        "memory_cache",
        "resource_conflict",
    }
    has_metric = any(family in families for family in metric_families)
    if not has_timing:
        return "partial" if has_metric else "insufficient"
    if not has_metric:
        return "partial"
    if target_status in {"mismatch", "partial_mismatch", "missing_observed"}:
        return "partial"
    return "available"


def explicit_target_readiness_level(summary: SummaryFacts, families: list[str], target_status: str) -> str:
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
        return "partial"
    coverage = summary.profile_coverage
    segments = coverage.segments
    app_complete = bool(segments["app"].count_complete)
    selected = coverage.selected_segments_by_family
    has_value_backed_selected_metric = any(
        family in families and any(selected.get(coverage_family) for coverage_family in coverage_families)
        for family, coverage_families in READINESS_COVERAGE_FAMILIES.items()
    )
    if app_complete and "app_timing" in families and has_value_backed_selected_metric:
        return "available"
    return "partial"


def explicit_target_readiness_reasons(summary: SummaryFacts, level: str) -> list[str]:
    coverage = summary.profile_coverage
    segments = coverage.segments
    app_complete = bool(segments["app"].count_complete)
    selected = [
        f"{family}:{segment}"
        for family, segment in (coverage.selected_segments_by_family).items()
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
    if level == "available":
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
        reasons.append(f"Target identity status is {target_status}; attribution to the intended target is unverified.")
    return reasons


def missing_evidence_families(families: list[str]) -> list[str]:
    missing = []
    if "app_timing" not in families:
        missing.append("app_timing")
    if not any(family in families for family in ["pipe_utilization", "arithmetic_utilization", "memory_cache", "resource_conflict"]):
        missing.append("operator_metric")
    return missing


def claim_lists(families: list[str]) -> tuple[list[str], list[str]]:
    allowed = []
    blocked = []
    if "app_timing" in families:
        allowed.append("rank application-level hot path")
    else:
        blocked.append("rank hot path without parser-visible timing")
    if "pipe_utilization" in families:
        allowed.append("describe recorded AI Core pipe time and ratios")
    if "arithmetic_utilization" in families:
        allowed.append("describe recorded arithmetic time and ratios")
    if "memory_cache" in families:
        allowed.append("describe recorded memory/cache fields")
    if "resource_conflict" in families:
        allowed.append("describe recorded resource conflict fields")
    if "simulator_source_pipeline" not in families:
        blocked.append("source-line or instruction attribution without simulator/source artifacts")
    return allowed, blocked


def readiness_followups(summary: SummaryFacts, missing_families: list[str], actions: tuple[CollectionAction, ...]) -> tuple[CollectionAction, ...]:
    if actions:
        return actions
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
                "unlocks_claims": ["describe recorded AI Core pipe time and ratios"],
                "target_scope": collection_target_scope(summary),
                "estimated_cost": collection_estimated_cost(summary, ["PipeUtilization"]),
            }
        )
    return tuple(CollectionAction.model_validate(item) for item in out[:2])


def readiness_claims(summary: SummaryFacts, readiness_families: list[str], target_status: str) -> tuple[list[str], list[str], list[str]]:
    profile_coverage = summary.profile_coverage
    explicit_target = profile_coverage.explicit_target
    claim_families = readiness_families
    if explicit_target:
        selected = profile_coverage.selected_segments_by_family
        claim_families = [
            family
            for family in readiness_families
            if family not in READINESS_COVERAGE_FAMILIES
            or any(
                selected.get(coverage_family)
                for coverage_family in READINESS_COVERAGE_FAMILIES[family]
            )
        ]
    missing_families = missing_evidence_families(claim_families)
    allowed, blocked = claim_lists(claim_families)
    if timing_groups(summary.headlines) and not timing_groups(summary.headlines, unique_scope=True):
        allowed = [claim for claim in allowed if claim != "rank application-level hot path"]
        blocked.append("rank a unique application hot path across unresolved timing scopes")
    if target_status in {"mismatch", "partial_mismatch", "missing_observed"}:
        allowed = []
        blocked.append("attribute observations to the intended target before identity is verified")
    coverage_segments = profile_coverage.segments
    app_complete = bool(coverage_segments["app"].count_complete) if "app" in coverage_segments else False
    if explicit_target and not app_complete:
        allowed = [claim for claim in allowed if claim != "rank application-level hot path"]
        blocked.append("rank complete-program hot paths without complete application launch coverage")
    return missing_families, allowed, blocked


def value_backed_families(summary: SummaryFacts, families: list[str]) -> list[str]:
    coverage = summary.profile_coverage
    readiness_families = families
    if coverage.explicit_target:
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
    return readiness_families


def build_evidence_readiness(summary: SummaryFacts, raw_artifact_index: RawArtifactIndex, *, actions: tuple[CollectionAction, ...], simulator_signals: tuple[EvidenceSignal, ...]) -> EvidenceReadiness:
    families = available_evidence_families(summary, raw_artifact_index, simulator_signals)
    identity = summary.target_identity
    target_status = identity.status
    profile_coverage = summary.profile_coverage
    explicit_target = profile_coverage.explicit_target
    readiness_families = value_backed_families(summary, families)
    level = (
        explicit_target_readiness_level(summary, readiness_families, target_status)
        if explicit_target
        else readiness_level(families, target_status)
    )
    missing_families, allowed, blocked = readiness_claims(summary, readiness_families, target_status)
    stages = [readiness_stage_for_app(summary)]
    for segment, scope in known_scope_segments(summary, raw_artifact_index):
        stages.append(readiness_stage_for_scope(raw_artifact_index, segment, scope))
    unparsed = [
        {
            "artifact": item.artifact,
            "segment": item.segment,
            "known_role": item.known_role,
            "diagnosis_role": item.diagnosis_role,
        }
        for item in raw_artifact_index.artifacts
        if item.group == "unparsed_profiler_binary"
    ]
    if explicit_target:
        coverage_segments = profile_coverage.segments
        scopes_by_segment = dict(known_scope_segments(summary, raw_artifact_index))
        stages = [
            {
                "segment": segment,
                "metric_scope": scopes_by_segment.get(segment),
                "status": "ready" if coverage.count_complete else "incomplete_target_coverage",
                "count_complete": coverage.count_complete,
                "metric_family_completeness": {family: details.complete for family, details in coverage.metric_coverage.items()},
            }
            for segment, coverage in coverage_segments.items()
        ]
    reasons = readiness_reasons(readiness_families, target_status, summary.analysis_context.has_workload)
    if explicit_target:
        reasons.extend(explicit_target_readiness_reasons(summary, level))
    return EvidenceReadiness.model_validate({
        "schema_version": "2.0",
        "level": level,
        "reasons": reasons,
        "available_evidence_families": readiness_families,
        "missing_evidence_families": missing_families,
        "allowed_claims": allowed,
        "blocked_claims": blocked,
        "recommended_followups": readiness_followups(summary, missing_families, actions),
        "segments": stages,
        "unparsed_binary_artifacts": unparsed,
    })


def validate_readiness_state(summary: Summary) -> None:
    """Check self-contained status/claim rules even without an optional index."""
    recorded = summary.evidence_readiness
    if summary.next_collection_actions != build_next_collection_actions(summary):
        raise ValueError("next collection actions disagree with normalized collection facts")
    expected_followups = readiness_followups(
        summary, list(recorded.missing_evidence_families), summary.next_collection_actions)
    if recorded.recommended_followups != expected_followups:
        raise ValueError("readiness followups disagree with normalized collection facts")
    identity = summary.target_identity
    target_status = identity.status
    coverage = summary.profile_coverage
    families = list(recorded.available_evidence_families)
    expected_families = value_backed_families(summary, available_evidence_families(summary, None))
    if [family for family in families if family != "simulator_source_pipeline"] != expected_families:
        raise ValueError("readiness families disagree with normalized profiler observations")
    reasons = readiness_reasons(families, target_status, summary.analysis_context.has_workload)
    if coverage.explicit_target:
        reasons.extend(explicit_target_readiness_reasons(summary, recorded.level))
    if recorded.reasons != tuple(reasons):
        raise ValueError("readiness reasons disagree with normalized context and profiler facts")
    expected_level = (explicit_target_readiness_level(summary, families, target_status)
                      if coverage.explicit_target
                      else readiness_level(families, target_status))
    if recorded.level != expected_level:
        raise ValueError("readiness level disagrees with normalized target and evidence families")
    for field, expected in zip(("missing_evidence_families", "allowed_claims", "blocked_claims"),
                               readiness_claims(summary, families, target_status)):
        if getattr(recorded, field) != tuple(expected):
            raise ValueError(f"readiness {field} disagrees with normalized target and evidence families")


def validate_readiness_inventory(summary: Summary, index: RawArtifactIndex) -> None:
    recorded = summary.evidence_readiness
    expected = build_evidence_readiness(summary, index, actions=summary.next_collection_actions,
        simulator_signals=next(item.signals for item in summary.analysis_dimensions if item.id == "source_pipeline_context"))
    for field in ("level", "available_evidence_families", "missing_evidence_families", "allowed_claims",
                  "blocked_claims", "recommended_followups", "segments", "unparsed_binary_artifacts", "reasons"):
        if getattr(recorded, field) != getattr(expected, field):
            raise ValueError(f"readiness {field} disagrees with admitted normalized inventory")
