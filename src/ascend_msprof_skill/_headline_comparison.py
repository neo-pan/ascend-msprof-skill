"""Scope-local profiler comparison, shared by both assessment consumers."""
from __future__ import annotations
import math
from .assessment_types import (ComparisonHeadline, Compatibility, CompatibilityCheck, CompatibilitySide,
    HeadlineComparison, WorkloadCheck, headline_comparison_reasons, compatibility_status, compatibility_check_status, mechanism_common_blockers, segment_check_blockers)
from .run_evidence import (ComparisonFacts, ComparisonRoleFacts, CompatibilityValueFact,
                           RunEvidence, select_cann_versions)
from .metric_scope_policy import is_msprof_op_command
from .evidence_types import SourceRef
from .provenance_types import ProfileOutputSegments

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

def compare_numeric(a_value: float | None, b_value: float | None) -> tuple[float | None, float | None, bool]:
    if a_value is None or b_value is None:
        return None, None, False
    delta = b_value - a_value
    delta_pct = None if a_value == 0 else delta / abs(a_value) * 100.0
    if not math.isfinite(delta) or (delta_pct is not None and not math.isfinite(delta_pct)):
        return None, None, False
    return delta, delta_pct, True


def compatibility_check(
    name: str,
    title: str,
    a_fact: CompatibilityValueFact,
    b_fact: CompatibilityValueFact,
) -> CompatibilityCheck:
    a = CompatibilitySide(value=a_fact.value, source=a_fact.source, status=a_fact.status)
    b = CompatibilitySide(value=b_fact.value, source=b_fact.source, status=b_fact.status)
    return CompatibilityCheck(id=name, title=title, status=compatibility_check_status(name, a, b), a=a, b=b)


def build_compatibility(a_run: ComparisonRoleFacts, b_run: ComparisonRoleFacts) -> Compatibility:
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
    return Compatibility(status=compatibility_status(tuple(checks)), checks=tuple(checks))



def compare_headlines(facts: ComparisonFacts, workload_checks: tuple[WorkloadCheck, ...] | None = None,
                      compatibility: Compatibility | None = None) -> list[HeadlineComparison]:
    rows = []
    if workload_checks is None:
        workload_checks = RunEvidence.workload_checks(facts.baseline.policy_evidence, facts.candidate.policy_evidence)
    compatibility = compatibility or build_compatibility(facts.baseline, facts.candidate)
    checks_by_segment = {}
    common_reasons = mechanism_common_blockers(workload_checks, compatibility, require_complete=True)
    for group in facts.headline_groups(tuple(HEADLINE_GROUP_ORDER)):
        left = facts.baseline.headline_records.get(group, ())
        right = facts.candidate.headline_records.get(group, ())
        # Match named metrics, never the largest value chosen independently
        # in each run. Multiple launch observations remain explicitly unpaired.
        fields = sorted({item.field for item in (*left, *right) if item.field})
        pairs = []
        for field in fields:
            a_rows = [item for item in left if item.field == field]
            b_rows = [item for item in right if item.field == field]
            if len(a_rows) == len(b_rows) == 1:
                pairs.append((a_rows[0], b_rows[0], ()))
            else:
                reason = ("metric scope ambiguous",) if len(a_rows) > 1 or len(b_rows) > 1 else ("matching metric missing",)
                pairs.extend((item, ComparisonHeadline(), reason) for item in a_rows)
                pairs.extend((ComparisonHeadline(), item, reason) for item in b_rows)
        if not pairs:
            pairs = [(ComparisonHeadline(), ComparisonHeadline(), ("matching metric missing",))]
        for a_item, b_item, pairing_reasons in pairs:
            present = a_item.present and b_item.present
            if present and a_item.segment not in checks_by_segment:
                checks_by_segment[a_item.segment] = segment_checks(facts.baseline.policy_evidence, facts.candidate.policy_evidence, a_item.segment)
            scoped_checks = checks_by_segment[a_item.segment] if present else []
            scoped_reasons = [f"profiler.{reason}" for reason in segment_check_blockers(tuple(scoped_checks), a_item.segment)] if present else []
            reasons = [*common_reasons, *scoped_reasons, *headline_comparison_reasons(a_item, b_item)] if present else list(pairing_reasons)
            delta, delta_pct, numeric = compare_numeric(None, None) if reasons else compare_numeric(a_item.value, b_item.value)
            if not reasons and not numeric:
                reasons.append("nonfinite_delta")
            status = ("missing" if not present else "not_comparable") if reasons else "same" if a_item.value == b_item.value else "changed"
            rows.append(HeadlineComparison(group=group, status=status, a=a_item, b=b_item,
                comparison_reasons=tuple(reasons), checks=tuple(scoped_checks), delta=delta, delta_pct=delta_pct, numeric=numeric))
    return rows



def segment_checks(a: RunEvidence, b: RunEvidence, segment: str | None) -> list[CompatibilityCheck]:
    segment = segment if isinstance(segment, str) else None
    def facts(run: RunEvidence) -> tuple[CompatibilityValueFact, CompatibilityValueFact]:
        compatibility = run.comparison_compatibility()
        segments = compatibility.profile_output_segments.value
        item = None
        field = f"profile_output_segments.{segment}"
        if isinstance(segments, ProfileOutputSegments) and segment:
            if segment.startswith("followup:"):
                action = segment.removeprefix("followup:")
                item = segments.followups.get(action)
                field = f"profile_output_segments.followups.{action}"
            else:
                item = {"app": segments.app, "op": segments.op, "simulator": segments.simulator}.get(segment)
        command = run.segment_commands.get(segment)
        if command is None:
            candidate = compatibility.profile_command
            if isinstance(candidate.value, str):
                command_segment = "op" if is_msprof_op_command(candidate.value) else "app"
                if segment == command_segment:
                    command = candidate
        return (CompatibilityValueFact(item, SourceRef(artifact="analysis/provenance.json", field=field)),
                command or CompatibilityValueFact(None, None))
    left, right = facts(a), facts(b)
    return [compatibility_check(f"segment.{segment}.{name}", name, left[i], right[i])
            for i, name in enumerate(("output", "command"))]
