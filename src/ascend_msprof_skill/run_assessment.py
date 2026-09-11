"""Independent natural-performance and profiler-mechanism assessments."""
from __future__ import annotations

from typing import Any
from pathlib import Path
import json

from .benchmark_evidence import BenchmarkEvidence, get, json_safe, source_ref
from ._headline_comparison import build_compatibility, compare_headlines, headline_comparison_reasons, segment_checks
from .run_evidence import RunEvidence

RunAssessment = dict[str, Any]

# Compare measurement conditions, excluding identity, observed outcomes and implementation lineage.
COMPARISON_FIELDS = (
    "subject.scope", "workload", "inputs", "outputs", "input_identity",
    "correctness.reference", "correctness.method", "correctness.tolerances", "correctness.case_count",
    "protocol", "environment.device", "environment.driver_version", "environment.runtimes",
    "environment.control_policy", "measurement.statistic",
)


def _performance(candidate: BenchmarkEvidence, baseline: BenchmarkEvidence | None) -> dict[str, Any]:
    checks = []
    for role, evidence in (("baseline", baseline), ("candidate", candidate)):
        if evidence is None:
            continue
        if not evidence.sources and not evidence.issues:
            checks.append({"id": f"{role}.assessment", "status": "missing", "reason_code": "benchmark_context_missing",
                           "baseline": None, "candidate": None, "sources": []})
        for item in evidence.issues:
            checks.append({"id": f"{role}.{item['id']}" if item["id"] else f"{role}.assessment", "status": item["status"], "reason_code": item["reason_code"],
                           "baseline": item.get("value") if role == "baseline" else None,
                           "candidate": item.get("value") if role == "candidate" else None,
                           "sources": [{**s, "role": role} for s in item["sources"]]})
        checks.append({"id": f"{role}.record", "status": "match" if evidence.record is not None and not evidence.issues else "missing" if evidence.record is None and not evidence.issues else "not_applicable",
                       "reason_code": "record_validated" if not evidence.issues else "see_record_issues",
                       "baseline": get(evidence.record, "measurement_id") if role == "baseline" else None,
                       "candidate": get(evidence.record, "measurement_id") if role == "candidate" else None,
                       "sources": [{**source_ref(s), "role": role} for s in evidence.sources]})
    if baseline is not None and baseline.record is not None and candidate.record is not None:
        def compare_condition(field: str, a: Any, b: Any) -> None:
            atomic_objects = {"workload.parameters", "environment.control_policy", "environment.runtimes", "correctness.tolerances", "input_identity.parameters"}
            if isinstance(a, dict) and isinstance(b, dict) and field not in atomic_objects:
                for key in sorted(a.keys() | b.keys()):
                    compare_condition(f"{field}.{key}", a.get(key), b.get(key))
                return
            if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
                for i, (left, right) in enumerate(zip(a, b)):
                    selector = f"name={left['name']}" if field in {"inputs", "outputs"} and isinstance(left, dict) and isinstance(right, dict) and left.get("name") == right.get("name") else str(i)
                    compare_condition(f"{field}[{selector}]", left, right)
                return
            status = "missing" if a is None or b is None else "match" if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) else "mismatch"
            checks.append({"id": field, "status": status, "reason_code": f"condition_{status}",
                           "baseline": a, "candidate": b,
                           "sources": [{**source_ref(s, field), "role": role} for role, ev in (("baseline", baseline), ("candidate", candidate)) for s in ev.sources]})
        for field in COMPARISON_FIELDS:
            compare_condition(field, get(baseline.record, field), get(candidate.record, field))
    statuses = {c["status"] for c in checks}
    eligibility = "blocked" if statuses & {"invalid", "conflict", "mismatch"} else "incomplete" if "missing" in statuses else "eligible"
    observation = None
    comparison_status = "not_applicable" if baseline is None else "not_comparable"
    if baseline is not None and eligibility == "eligible":
        a, b = get(baseline.record, "measurement.value_ms"), get(candidate.record, "measurement.value_ms")
        delta = b - a
        speedup = (a - b) / a * 100
        from .benchmark_evidence import number
        if not number(delta) or not number(speedup):
            eligibility = "blocked"
            checks.append({"id": "observation", "status": "invalid", "reason_code": "nonfinite_delta",
                           "baseline": a, "candidate": b, "sources": []})
        else:
            comparison_status = "observed_only"
            observation = {"delta_ms": delta, "speedup_pct": speedup,
                           "direction": "faster" if delta < 0 else "slower" if delta > 0 else "equal",
                           "statistic": get(candidate.record, "measurement.statistic"),
                           "sources": [{**source_ref(s, "measurement"), "role": role} for role, ev in (("baseline", baseline), ("candidate", candidate)) for s in ev.sources]}
    reasons = [f"{c['id']}: {c['reason_code']}" for c in checks if c["status"] not in {"match", "not_applicable"}]
    return {"contract_version": "1.0", "mode": "comparison" if baseline is not None else "single_run",
            "eligibility": {"status": eligibility, "checks": checks, "reasons": reasons},
            "measurements": {"baseline": baseline.as_measurement() if baseline is not None else None, "candidate": candidate.as_measurement()},
            "comparison": {"status": comparison_status, "observation": observation},
            "limitations": ["Caller-provided records establish declared conditions, not the scientific validity of the measurement method.",
                            "Only point estimates are evaluated; uncertainty, raw sample statistics and practical significance are not assessed."]}


def _questions(run: RunEvidence, role: str) -> list[dict[str, Any]]:
    facts = run.feedback_facts()
    questions = [facts.family_question(
        "memory_cache", "memory_cache", "Which memory movement or cache fields support the next inspection?",
        ("memory_movement", "cache_context", "metric_scope"), {"memory", "l2_cache"}, source=role,
        required_artifacts=["Memory.csv", "MemoryL0.csv", "MemoryUB.csv", "L2Cache.csv"],
        next_experiment="Collect the missing Default family artifacts for the stated target and workload.").as_payload(),
        facts.family_question(
        "pipe_arithmetic", "pipe_arithmetic", "Which Cube, Vector, Scalar or MTE fields support the next inspection?",
        ("pipe_mix", "arithmetic_mix"), {"pipe_utilization", "arithmetic_utilization"}, source=role,
        required_artifacts=["PipeUtilization.csv", "ArithmeticUtilization.csv"],
        next_experiment="Collect matching pipe and arithmetic artifacts for the stated target and workload.").as_payload(),
        facts.opbasic_workload_question(source=role).as_payload()]
    if facts.jit_debug_found() or facts.simulator_present:
        questions.append(facts.generated_context_question(source=role).as_payload())
    return questions


def _association(run: RunEvidence, role: str) -> dict[str, Any]:
    checks = run.benchmark_subject_checks()
    linked = run.linked_benchmark()
    if linked is not None:
        context = run.candidate_context()
        for field in ("id", "shape", "dtype", "case_count"):
            a, b = get(linked, f"workload.{field}"), context.workload.get(field)
            checks.append({"id": f"benchmark_workload.{field}", "status": "missing" if a is None else "conflict" if b is None else "match" if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) else "mismatch",
                           "benchmark": a, "profiler": b, "sources": context.workload_evidence[field]})
    workload_failed = any(c["id"].startswith("benchmark_workload") and c["status"] != "match" for c in checks)
    status = "linked" if linked is not None and not workload_failed else "blocked" if workload_failed or any(c["status"] == "mismatch" for c in checks) else "missing"
    return {"role": role, "status": status, "checks": checks,
            "limitation": None if status == "linked" else "Benchmark and profiler observations cannot explain the same performance change without a matching recorded implementation and workload."}


def _mechanism(candidate: RunEvidence, baseline: RunEvidence | None) -> dict[str, Any]:
    runs = [("candidate", candidate)] if baseline is None else [("baseline", baseline), ("candidate", candidate)]
    questions_by_role = {role: {q["id"]: q for q in _questions(run, role)} for role, run in runs}
    associations = [_association(run, role) for role, run in runs]
    facts = RunEvidence.comparison_facts(baseline, candidate) if baseline is not None else None
    compatibility = build_compatibility(facts.baseline, facts.candidate) if facts else {"status": "not_applicable", "checks": []}
    workload_checks = list(RunEvidence.workload_checks(baseline, candidate)) if baseline is not None else []
    headlines = compare_headlines(facts, tuple(workload_checks)) if facts else []
    common_blockers = [f"{c['id']} {c['status']}" for c in workload_checks if c["status"] != "match"]
    common_blockers += [f"profiler.{c['id']} {c['status']}" for c in compatibility["checks"] if c["id"] in {"cann_version", "hardware_summary"} and c["status"] != "match"]
    questions = []
    for qid in dict.fromkeys(qid for by_id in questions_by_role.values() for qid in by_id):
        originals = [by_id[qid] for by_id in questions_by_role.values() if qid in by_id]
        question = {**originals[0], "available_evidence": [], "missing_evidence": [], "blocked_by": list(common_blockers)}
        for original in originals:
            for key in ("available_evidence", "missing_evidence", "blocked_by"):
                question[key].extend(original[key])
        if len(originals) < len(runs):
            question["blocked_by"].append("paired inspection context missing")
        for role, run in runs:
            target = run.summary().get("target_identity")
            target = target if isinstance(target, dict) else {}
            if target.get("status") not in (None, "match"):
                question["blocked_by"].append(f"{role}: target unverified")
        if baseline is not None:
            segments = {e.get("segment") for e in question["available_evidence"] if isinstance(e.get("segment"), str)}
            for segment in sorted(segments):
                question["blocked_by"].extend(f"profiler.{c['id']} {c['status']}" for c in segment_checks(baseline, candidate, segment) if c["status"] != "match")
        if qid == "generated_context":
            for role, run in runs:
                linked = run.linked_benchmark()
                if linked:
                    passed, issues = run.benchmark.correctness()
                    for item in issues:
                        citations = "; ".join(f"{s['artifact']}:{s['field_ref']}" for s in item["sources"])
                        question["blocked_by"].append(f"{role}: {item['reason_code']} ({citations})")
                else:
                    passed = run.feedback_facts().correctness_passed()
                if passed is not True:
                    question["blocked_by"].append(f"{role}: correctness pass for the inspected implementation is required")
        # Reuse action artifact requirements; do not infer a scope from action prose.
        for role, run in runs:
            missing = {Path(str(e.get("artifact"))).name for e in question["missing_evidence"] if e.get("source") == role}
            for action in run.combined_pending_collection_actions():
                names = action.get("required_artifacts")
                required = {Path(str(name)).name for name in names} if isinstance(names, list) else set()
                if missing & required and action.get("necessity", "blocking") != "optional":
                    question["blocked_by"].append(f"{role}: pending {action.get('id')}")
        question["blocked_by"] = list(dict.fromkeys(question["blocked_by"]))
        question["status"] = "blocked" if question["blocked_by"] else "missing" if question["missing_evidence"] else "available"
        questions.append(question)
    findings = []
    if facts:
        for row in headlines:
            if row["numeric"]:
                findings.append({"kind": "metric_observation", "evidence_level": "descriptive", "group": row["group"],
                                 "delta": row["delta"], "delta_pct": row["delta_pct"],
                                 "evidence": [{"artifact": item.get("artifact"), "field_ref": item.get("field_ref") or item.get("field"), "role": role} for role, item in (("baseline", row["a"]), ("candidate", row["b"]))]})
    else:
        for group in sorted(candidate.headline_group_names()):
            item = candidate.comparison_headline_record(group)
            if item.get("present") and not headline_comparison_reasons(item, item):
                headlines.append({"group": group, "status": "observed", "candidate": item})
                findings.append({"kind": "metric_observation", "evidence_level": "descriptive", "group": group, "evidence": [{"artifact": item.get("artifact"), "field_ref": item.get("field_ref") or item.get("field")}]})
    findings.extend({"kind": "inspection_hypothesis", "evidence_level": "directional", "question_id": q["id"]} for q in questions if q["status"] == "available")
    present = any(run.summary() or run.raw_artifacts() or run.feedback_facts().simulator_present for _, run in runs)
    coverage = "missing" if not present else "available" if questions and all(q["status"] == "available" for q in questions) else "blocked" if common_blockers and not findings else "partial"
    return {"contract_version": "1.0", "mode": "comparison" if baseline is not None else "single_run", "coverage": coverage,
            "compatibility": compatibility, "workload_checks": workload_checks, "headlines": headlines,
            "questions": questions, "findings": findings, "benchmark_association": associations,
            "evidence": {role: {**run.summary_evidence(), "parsed_artifact_count": run.parsed_raw_artifact_counts()[0],
                                "evidence_present": run.feedback_facts().profiler_evidence_present()} for role, run in runs},
            "pending_actions": [{"role": role, **action} for role, run in runs for action in run.combined_pending_collection_actions()],
            "limitations": ["Metric observations and inspection hypotheses do not establish a cause of speedup."]}


def assess_run(candidate: RunEvidence, baseline: RunEvidence | None = None) -> RunAssessment:
    """Pure computation over loaded facts; both CLIs use this interface."""
    return json_safe({"performance_assessment": _performance(candidate.benchmark, baseline.benchmark if baseline is not None else None),
                      "mechanism_assessment": _mechanism(candidate, baseline)})


def assessment_metadata(candidate: RunEvidence, baseline: RunEvidence | None = None) -> dict[str, Any]:
    runs = [("candidate", candidate)] if baseline is None else [("baseline", baseline), ("candidate", candidate)]
    return json_safe({
        "runs": {role: run.comparison_role_facts(role).descriptor.as_summary() for role, run in runs},
        "source_artifacts": {role: {**run.source_artifacts, "benchmark": list(run.benchmark.sources)} for role, run in runs},
        "lineage": {role: {"subject": get(run.benchmark.record, "subject"),
                           "payload": run.candidate_context().payload.as_summary(),
                           "jit_config": run.candidate_context().jit.config} for role, run in runs},
        "warnings": [f"{role}: {warning}" for role, run in runs for warning in run.warnings()],
    })
