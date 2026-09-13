"""Independent natural-performance and profiler-mechanism assessments."""
from __future__ import annotations

from pathlib import Path

from .benchmark_evidence import BenchmarkEvidence, source_ref
from .benchmark_types import BenchmarkSource, BenchmarkCitation
from .assessment_types import (PerformanceAssessment, PerformanceCheck, PerformanceEligibility, PerformanceComparison,
    PerformanceMeasurements, PerformanceObservation, eligibility_status, eligibility_reasons, performance_condition_checks)
import math
from ._headline_comparison import build_compatibility, compare_headlines, segment_checks
from .run_evidence import RunEvidence, FeedbackDesignQuestionFact
from .assessment_types import (RunAssessment, MechanismAssessment, EvidenceCitation, EvidenceQuestion,
    BenchmarkAssociation, AssociationCheck, Compatibility, HeadlineComparison, MechanismEvidence,
    RoleAction, AssessmentMetadata, RunDescriptor, RunSources, Lineage, PayloadView,
    mechanism_common_blockers, mechanism_coverage, mechanism_findings, ReadinessView,
    headline_comparison_reasons, benchmark_association_status, association_check_status, WorkloadObservation, WORKLOAD_FIELDS)


def _citation(source: BenchmarkSource, field: str, role: str) -> BenchmarkCitation:
    citation = source_ref(source, field)
    return BenchmarkCitation(artifact=citation.artifact, sha256=citation.sha256,
                             field_ref=citation.field_ref, role=role)


def _performance(candidate: BenchmarkEvidence, baseline: BenchmarkEvidence | None) -> PerformanceAssessment:
    checks: list[PerformanceCheck] = []
    for role, evidence in (("baseline", baseline), ("candidate", candidate)):
        if evidence is None:
            continue
        if not evidence.sources and not evidence.issues:
            checks.append(PerformanceCheck(id=f"{role}.assessment", status="missing", reason_code="benchmark_context_missing"))
        for item in evidence.issues:
            checks.append(PerformanceCheck(id=f"{role}.{item.id}" if item.id else f"{role}.assessment",
                status=item.status, reason_code=item.reason_code,
                baseline=item.value if role == "baseline" else None,
                candidate=item.value if role == "candidate" else None,
                sources=tuple(BenchmarkCitation(artifact=s.artifact, sha256=s.sha256, field_ref=s.field_ref, role=role)
                              for s in item.sources)))
        checks.append(PerformanceCheck(id=f"{role}.record",
            status="match" if evidence.record is not None and not evidence.issues else "missing" if evidence.record is None and not evidence.issues else "not_applicable",
            reason_code="record_validated" if not evidence.issues else "see_record_issues",
            baseline=evidence.record.measurement_id if evidence.record and role == "baseline" else None,
            candidate=evidence.record.measurement_id if evidence.record and role == "candidate" else None,
            sources=tuple(_citation(s, "", role) for s in evidence.sources)))
    measurements = PerformanceMeasurements(baseline=baseline.as_measurement() if baseline is not None else None,
                                           candidate=candidate.as_measurement())
    checks.extend(performance_condition_checks(measurements))
    eligibility = eligibility_status(tuple(checks))
    observation = None
    comparison_status = "not_applicable" if baseline is None else "not_comparable"
    if baseline is not None and eligibility == "eligible":
        a, b = baseline.record.measurement.value_ms, candidate.record.measurement.value_ms
        delta, speedup = b - a, (a - b) / a * 100
        if not math.isfinite(delta) or not math.isfinite(speedup):
            checks.append(PerformanceCheck(id="observation", status="invalid", reason_code="nonfinite_delta", baseline=a, candidate=b))
        else:
            comparison_status = "observed_only"
            observation = PerformanceObservation(delta_ms=delta, speedup_pct=speedup,
                direction="faster" if delta < 0 else "slower" if delta > 0 else "equal",
                statistic=candidate.record.measurement.statistic,
                sources=tuple(_citation(s, "measurement", role) for role, ev in (("baseline", baseline), ("candidate", candidate)) for s in ev.sources))
    frozen_checks = tuple(checks)
    return PerformanceAssessment(mode="comparison" if baseline is not None else "single_run",
        eligibility=PerformanceEligibility(status=eligibility_status(frozen_checks), checks=frozen_checks, reasons=eligibility_reasons(frozen_checks)),
        measurements=measurements,
        comparison=PerformanceComparison(status=comparison_status, observation=observation),
        limitations=("Caller-provided records establish declared conditions, not the scientific validity of the measurement method.",
                     "Only point estimates are evaluated; uncertainty, raw sample statistics and practical significance are not assessed."))


def _questions(run: RunEvidence, role: str) -> list[FeedbackDesignQuestionFact]:
    facts = run.feedback_facts()
    questions = [facts.family_question(
        "memory_cache", "memory_cache", "Which memory/cache fields are available, and for which target scope?",
        {"memory", "l2_cache"}, source=role,
        required_artifacts=["Memory.csv", "MemoryL0.csv", "MemoryUB.csv", "L2Cache.csv"]),
        facts.family_question(
        "pipe_arithmetic", "pipe_arithmetic", "Which Cube, Vector, Scalar or MTE fields are available, and for which target scope?",
        {"pipe_utilization", "arithmetic_utilization"}, source=role,
        required_artifacts=["PipeUtilization.csv", "ArithmeticUtilization.csv"]),
        facts.opbasic_workload_question(source=role)]
    if facts.jit_debug_found() or facts.simulator_present:
        questions.append(facts.generated_context_question(source=role))
    return questions


def _association(run: RunEvidence, role: str) -> BenchmarkAssociation:
    checks = run.benchmark_subject_checks()
    linked = run.linked_benchmark()
    if linked is not None:
        context = run.candidate_context()
        workload = linked.workload.model_dump(mode='json') if linked.workload else {}
        for field in WORKLOAD_FIELDS:
            a = workload.get(field)
            b = context.workload.get(field)
            sources = tuple(WorkloadObservation.model_validate(item) for item in context.workload_evidence[field])
            check_id = f"benchmark_workload.{field}"
            checks.append(AssociationCheck(id=check_id,
                status=association_check_status(check_id, a, b, sources), benchmark=a, profiler=b, sources=sources))
    status = benchmark_association_status(tuple(checks))
    return BenchmarkAssociation(role=role, status=status, checks=tuple(checks),
        limitation=None if status == "linked" else "Benchmark and profiler observations cannot explain the same performance change without a matching recorded implementation and workload.")


def _mechanism(candidate: RunEvidence, baseline: RunEvidence | None) -> MechanismAssessment:
    runs = [("candidate", candidate)] if baseline is None else [("baseline", baseline), ("candidate", candidate)]
    questions_by_role = {role: {q.question_id: q for q in _questions(run, role)} for role, run in runs}
    associations = tuple(_association(run, role) for role, run in runs)
    facts = RunEvidence.comparison_facts(baseline, candidate) if baseline is not None else None
    compatibility = build_compatibility(facts.baseline, facts.candidate) if facts else Compatibility(status="not_applicable", checks=())
    workload_checks = RunEvidence.workload_checks(baseline, candidate) if baseline is not None else ()
    headlines = compare_headlines(facts, workload_checks) if facts else []
    common_blockers = mechanism_common_blockers(workload_checks, compatibility)
    questions = []
    for qid in dict.fromkeys(qid for by_id in questions_by_role.values() for qid in by_id):
        originals = [by_id[qid] for by_id in questions_by_role.values() if qid in by_id]
        available = tuple(EvidenceCitation.model_validate(item, from_attributes=True) for original in originals for item in original.available_evidence)
        missing_evidence = tuple(EvidenceCitation.model_validate(item, from_attributes=True) for original in originals for item in original.missing_evidence)
        blocked_by = [*common_blockers, *(text for original in originals for text in original.blocked_by)]
        if len(originals) < len(runs):
            blocked_by.append("paired inspection context missing")
        for role, run in runs:
            target = run.target_identity()
            if target is not None and target.status != "match":
                blocked_by.append(f"{role}: target unverified")
        if baseline is not None:
            for segment in sorted({item.segment for item in available if item.segment is not None}):
                blocked_by.extend(f"profiler.{c.id} {c.status}" for c in segment_checks(baseline, candidate, segment) if c.status != "match")
        for role, run in runs:
            missing = {Path(item.artifact).name for item in missing_evidence if item.source == role and item.artifact}
            for action in run.combined_pending_collection_actions():
                required = {Path(name).name for name in action.required_artifacts}
                if missing & required and action.necessity != "optional":
                    blocked_by.append(f"{role}: pending {action.id}")
        blockers = tuple(dict.fromkeys(blocked_by))
        first = originals[0]
        questions.append(EvidenceQuestion(id=qid, evidence_family=first.evidence_family, question=first.question,
            available_evidence=available, missing_evidence=missing_evidence, blocked_by=blockers,
            status="blocked" if blockers else "missing" if missing_evidence else "available"))
    if facts is None:
        for group in sorted(candidate.headline_group_names()):
            for item in candidate.comparison_observations(group):
                reasons = tuple(headline_comparison_reasons(item, item))
                headlines.append(HeadlineComparison(group=group, status="unassessed" if reasons else "observed",
                                                     candidate=item, comparison_reasons=reasons))
    findings = mechanism_findings(tuple(headlines))
    evidence = {}
    for role, run in runs:
        readiness = run.evidence_readiness()
        evidence[role] = MechanismEvidence(
            summary_warnings=tuple(run.summary_warnings()), next_collection_actions=run.next_collection_actions(),
            pending_collection_actions=tuple(run.combined_pending_collection_actions()),
            evidence_readiness=ReadinessView(present=readiness is not None, level=readiness.level if readiness else None,
                available_evidence_families=readiness.available_evidence_families if readiness else (),
                missing_evidence_families=readiness.missing_evidence_families if readiness else (),
                material_evidence_families=tuple(run.material_evidence_families()), recommended_followups=run.readiness_followups()),
            measurement_quality=run.measurement_quality(), raw_artifact_index=run.raw_artifact_index_view(),
            parsed_artifact_count=run.parsed_raw_artifact_counts()[0],
            evidence_present=run.feedback_facts().profiler_evidence_present(),
            inputs_present=bool(run.summary() or run.raw_artifacts() or run.feedback_facts().simulator_present))
    return MechanismAssessment(mode="comparison" if baseline is not None else "single_run",
        coverage=mechanism_coverage(evidence, tuple(questions), workload_checks, compatibility, findings),
        compatibility=compatibility, workload_checks=workload_checks, headlines=tuple(headlines), questions=tuple(questions),
        findings=tuple(findings), benchmark_association=associations, evidence=evidence,
        pending_actions=tuple(RoleAction(role=role, **{field: getattr(action, field) for field in type(action).model_fields})
                              for role, run in runs for action in run.combined_pending_collection_actions()),
        limitations=("Metric observations describe the recorded scope; they do not establish a bottleneck or cause of speedup. Question status describes evidence availability, not experiment readiness.",))


def assess_run(candidate: RunEvidence, baseline: RunEvidence | None = None) -> RunAssessment:
    """Pure computation over loaded facts; both CLIs use this interface."""
    return RunAssessment(performance_assessment=_performance(candidate.benchmark, baseline.benchmark if baseline is not None else None),
                         mechanism_assessment=_mechanism(candidate, baseline))


def assessment_metadata(candidate: RunEvidence, baseline: RunEvidence | None = None) -> AssessmentMetadata:
    runs = [("candidate", candidate)] if baseline is None else [("baseline", baseline), ("candidate", candidate)]
    return AssessmentMetadata(
        runs={role: RunDescriptor.model_validate(run.comparison_role_facts(role).descriptor, from_attributes=True) for role, run in runs},
        source_artifacts={role: RunSources(**run.source_artifacts, benchmark=run.benchmark.sources) for role, run in runs},
        lineage={role: Lineage(subject=run.benchmark.record.subject if run.benchmark.record else None,
                              payload=PayloadView.model_validate(run.candidate_context().payload, from_attributes=True),
                              jit_config=run.candidate_context().jit.config) for role, run in runs},
        warnings=tuple(f"{role}: {warning}" for role, run in runs for warning in run.warnings()))
