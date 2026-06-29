"""Shared TileLang candidate feedback and verdict helpers."""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from .run_evidence import FeedbackEvidenceFacts, RawArtifactFact, RunEvidence


DEFAULT_MIN_SPEEDUP_PCT = 1.0
DESIGN_FEEDBACK_CONTRACT_VERSION = "1.0"
WORKLOAD_COMPARABILITY_FIELDS = ("id", "shape", "dtype", "case_count")
READINESS_LEVEL_ORDER = {
    "insufficient": 0,
    "triage_only": 1,
    "directional": 2,
    "actionable_experiment": 3,
    "comparison_ready": 4,
}
MIN_COMPARISON_READINESS_LEVEL = "directional"


def context_value(context: dict[str, Any] | None, path: list[str]) -> Any:
    value: Any = context
    for part in path:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def json_equal_value(value: Any) -> str:
    return json.dumps(sanitize_json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def values_match(a_value: Any, b_value: Any) -> bool:
    return json_equal_value(a_value) == json_equal_value(b_value)


def try_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def sanitize_json_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, int):
        return value
    if isinstance(value, list):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): sanitize_json_value(item) for key, item in value.items()}
    return value


def normalize_min_speedup_pct(value: float) -> float:
    threshold = try_float(value)
    if threshold is None or threshold < 0:
        raise ValueError("--min-speedup-pct must be a finite non-negative number")
    return threshold


def runtime_mean_ms(context: dict[str, Any] | None) -> float | None:
    mean_ms = try_float(context_value(context, ["benchmark", "candidate", "runtime_stats", "mean_ms"]))
    if mean_ms is not None:
        return mean_ms
    return try_float(context_value(context, ["benchmark", "candidate", "runtime"]))


def runtime_evidence_field_ref(context: dict[str, Any] | None) -> str | None:
    if try_float(context_value(context, ["benchmark", "candidate", "runtime_stats", "mean_ms"])) is not None:
        return "benchmark.candidate.runtime_stats.mean_ms"
    if try_float(context_value(context, ["benchmark", "candidate", "runtime"])) is not None:
        return "benchmark.candidate.runtime"
    return None


def correctness_passed(context: dict[str, Any] | None) -> bool | None:
    raw = context_value(context, ["benchmark", "correctness", "raw"])
    if isinstance(raw, dict):
        passed = raw.get("passed")
        return passed if isinstance(passed, bool) else None
    return raw if isinstance(raw, bool) else None


def compiled_value(context: dict[str, Any] | None) -> bool | None:
    compiled = context_value(context, ["benchmark", "candidate", "compiled"])
    return compiled if isinstance(compiled, bool) else None


def benchmark_error(context: dict[str, Any] | None) -> Any:
    error = context_value(context, ["benchmark", "candidate", "error"])
    if error in (None, "", [], {}):
        return None
    return error


def benchmark_reject_reasons(context: dict[str, Any] | None, label: str = "candidate") -> list[str]:
    reasons = []
    if compiled_value(context) is False:
        reasons.append(f"{label} compiled=false")
    if correctness_passed(context) is False:
        reasons.append(f"{label} correctness failed")
    if benchmark_error(context) is not None:
        reasons.append(f"{label} benchmark error present")
    return reasons


def collection_action_ids(actions: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("id") or "unknown") for item in actions if isinstance(item, dict)]


def design_evidence(
    *,
    source: str,
    artifact: Any,
    role: str,
    field: Any = None,
    field_ref: Any = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "artifact": artifact,
        "field": field,
        "field_ref": field_ref,
        "role": role,
    }


def missing_design_evidence(
    *,
    source: str,
    artifact: str,
    role: str,
    field: str | None = None,
    field_ref: str | None = None,
) -> dict[str, Any]:
    return design_evidence(source=source, artifact=artifact, field=field, field_ref=field_ref, role=role)


def context_evidence(source: str, field_ref: str, role: str) -> dict[str, Any]:
    return design_evidence(
        source=source,
        artifact="analysis/tilelang_context.json",
        field=field_ref.split(".")[-1],
        field_ref=field_ref,
        role=role,
    )


def artifact_field_from_fact(fact: RawArtifactFact) -> Any:
    return fact.columns[0] if fact.columns else None


def artifact_name_from_fact(fact: RawArtifactFact) -> str:
    return Path(str(fact.artifact or "")).name


def summary_signal_evidence_from_facts(
    facts: FeedbackEvidenceFacts,
    groups: set[str],
    *,
    source: str,
    role: str,
    limit: int = 3,
    allowed_artifact_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    return [
        design_evidence(
            source=source,
            artifact=signal.artifact,
            field=signal.field,
            field_ref=signal.field_ref,
            role=role,
        )
        for signal in facts.summary_signal_records(groups, limit=limit, allowed_artifact_keys=allowed_artifact_keys)
    ]


def raw_group_evidence_from_facts(
    facts: FeedbackEvidenceFacts,
    groups: set[str],
    *,
    source: str,
    role: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    out = []
    for fact in facts.raw_artifacts_by_group(groups)[:limit]:
        out.append(
            design_evidence(
                source=source,
                artifact=fact.artifact,
                field=artifact_field_from_fact(fact),
                field_ref=f"raw_artifact_index.artifacts[group={fact.group}]",
                role=role,
            )
        )
    return out


def raw_artifact_evidence_from_facts(
    artifacts: list[RawArtifactFact],
    *,
    source: str,
    role: str,
) -> list[dict[str, Any]]:
    out = []
    for fact in artifacts:
        out.append(
            design_evidence(
                source=source,
                artifact=fact.artifact,
                field=artifact_field_from_fact(fact),
                field_ref=f"raw_artifact_index.artifacts[artifact={artifact_name_from_fact(fact)}]",
                role=role,
            )
        )
    return out


def design_question(
    question_id: str,
    evidence_family: str,
    question: str,
    related_design_variables: list[str],
    available_evidence: list[dict[str, Any]],
    missing_evidence: list[dict[str, Any]],
    next_experiment: str,
    blocked_by: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": question_id,
        "evidence_family": evidence_family,
        "question": question,
        "related_design_variables": related_design_variables,
        "available_evidence": available_evidence,
        "missing_evidence": missing_evidence,
        "next_experiment": next_experiment,
        "blocked_by": blocked_by or [],
    }


def prefix_blockers(source: str, blockers: list[Any]) -> list[str]:
    return list(dict.fromkeys(f"{source}: {blocker}" for blocker in blockers))


def aggregate_design_feedback_status(questions: list[dict[str, Any]], contract_blockers: list[str]) -> str:
    if contract_blockers:
        return "blocked"
    if not questions:
        return "blocked"
    if any(question.get("blocked_by") for question in questions):
        return "incomplete"
    if any(question.get("missing_evidence") for question in questions):
        return "incomplete"
    return "ready"


def design_feedback_payload(questions: list[dict[str, Any]], contract_blockers: list[str]) -> dict[str, Any]:
    return {
        "contract_version": DESIGN_FEEDBACK_CONTRACT_VERSION,
        "status": aggregate_design_feedback_status(questions, contract_blockers),
        "questions": questions,
    }


def single_run_contract_blockers_from_facts(
    facts: FeedbackEvidenceFacts,
    context: dict[str, Any] | None,
) -> list[str]:
    blockers = []
    if compiled_value(context) is False:
        blockers.append("compile stage did not produce a runnable candidate")
    if correctness_passed(context) is False:
        blockers.append("correctness did not pass")
    if not facts.summary_present:
        blockers.append("missing analysis/summary.json")
    if not isinstance(context, dict):
        blockers.append("missing analysis/tilelang_context.json")
    if not facts.raw_artifact_index_present:
        blockers.append("missing analysis/raw_artifact_index.json")
    elif not facts.raw_inventory_present():
        blockers.append("missing parsed on-device profiler evidence")
    return blockers


def candidate_comparability_question_from_facts(
    facts: FeedbackEvidenceFacts,
    context: dict[str, Any] | None,
    *,
    source: str,
    blocked_by: list[str] | None = None,
) -> dict[str, Any]:
    available: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for field in WORKLOAD_COMPARABILITY_FIELDS:
        if context_value(context, ["benchmark", "workload", field]) is None:
            missing.append(
                missing_design_evidence(
                    source=source,
                    artifact="analysis/tilelang_context.json",
                    field=field,
                    field_ref=f"benchmark.workload.{field}",
                    role="workload comparability field is missing",
                )
            )
        else:
            available.append(context_evidence(source, f"benchmark.workload.{field}", "workload comparability field"))
    if correctness_passed(context) is True:
        available.append(context_evidence(source, "benchmark.correctness.raw", "correctness pass record"))
    else:
        missing.append(
            missing_design_evidence(
                source=source,
                artifact="analysis/tilelang_context.json",
                field="raw",
                field_ref="benchmark.correctness.raw",
                role="correctness pass record is missing",
            )
        )
    field_ref = runtime_evidence_field_ref(context)
    if field_ref is not None:
        available.append(context_evidence(source, field_ref, "runtime evidence"))
    else:
        missing.append(
            missing_design_evidence(
                source=source,
                artifact="analysis/tilelang_context.json",
                field="mean_ms",
                field_ref="benchmark.candidate.runtime_stats.mean_ms",
                role="runtime evidence is missing",
            )
        )
    if facts.provenance_present:
        for field_ref, role in [
            ("cann_version", "CANN version evidence"),
            ("hardware.summary", "hardware summary evidence"),
            ("profile_output_segments", "profile output segment evidence"),
        ]:
            value = facts.provenance_value(field_ref.split("."))
            if value is not None:
                available.append(
                    design_evidence(
                        source=source,
                        artifact="analysis/provenance.json",
                        field=field_ref.split(".")[-1],
                        field_ref=field_ref,
                        role=role,
                    )
                )
            else:
                missing.append(
                    missing_design_evidence(
                        source=source,
                        artifact="analysis/provenance.json",
                        field=field_ref.split(".")[-1],
                        field_ref=field_ref,
                        role=f"{role} is missing",
                    )
                )
    else:
        missing.append(
            missing_design_evidence(
                source=source,
                artifact="analysis/provenance.json",
                role="provenance evidence is missing",
            )
        )
    if facts.summary_present:
        available.append(
            design_evidence(
                source=source,
                artifact="analysis/summary.json",
                field="analysis_schema_version",
                field_ref="analysis_schema_version",
                role="analysis summary evidence",
            )
        )
    else:
        missing.append(
            missing_design_evidence(
                source=source,
                artifact="analysis/summary.json",
                field="analysis_schema_version",
                field_ref="analysis_schema_version",
                role="analysis summary evidence is missing",
            )
        )
    if facts.raw_inventory_present():
        available.append(
            design_evidence(
                source=source,
                artifact="analysis/raw_artifact_index.json",
                field="artifacts",
                field_ref="artifacts[status=parsed]",
                role="parsed raw artifact inventory",
            )
        )
    else:
        missing.append(
            missing_design_evidence(
                source=source,
                artifact="analysis/raw_artifact_index.json",
                field="artifacts",
                field_ref="artifacts[status=parsed]",
                role="parsed raw artifact inventory is missing",
            )
        )
    return design_question(
        "candidate_comparability",
        "candidate_comparability",
        "Is the candidate evidence complete enough to compare one changed design variable against the baseline?",
        ["workload", "correctness", "provenance", "metric_scope", "raw_artifact_inventory"],
        available,
        missing,
        "Collect or align the missing workload, correctness, provenance, metric-scope, and raw-artifact evidence before comparing the design variable.",
        blocked_by,
    )


def family_question_from_facts(
    question_id: str,
    evidence_family: str,
    question: str,
    related_design_variables: list[str],
    facts: FeedbackEvidenceFacts,
    groups: set[str],
    *,
    source: str,
    required_artifacts: list[str],
    next_experiment: str,
) -> dict[str, Any]:
    present_artifacts, missing_artifacts, allowed_artifact_keys = facts.parsed_required_artifacts(groups, required_artifacts)
    available = [
        *summary_signal_evidence_from_facts(
            facts,
            groups,
            source=source,
            role=f"{evidence_family} summary signal",
            allowed_artifact_keys=allowed_artifact_keys,
        ),
        *raw_artifact_evidence_from_facts(present_artifacts, source=source, role=f"{evidence_family} raw artifact"),
    ]
    missing = []
    blocked = []
    if missing_artifacts:
        blocked.append(f"missing {evidence_family} profiler evidence")
        for artifact in missing_artifacts:
            missing.append(
                missing_design_evidence(
                    source=source,
                    artifact=artifact,
                    role=f"{evidence_family} artifact is missing",
                )
            )
    return design_question(
        question_id,
        evidence_family,
        question,
        related_design_variables,
        available,
        missing,
        next_experiment,
        blocked,
    )


def opbasic_workload_question_from_facts(
    facts: FeedbackEvidenceFacts,
    context: dict[str, Any] | None,
    *,
    source: str,
) -> dict[str, Any]:
    available = [
        *summary_signal_evidence_from_facts(
            facts,
            {"op_basic_info", "task_time"},
            source=source,
            role="work distribution summary signal",
        ),
        *raw_group_evidence_from_facts(facts, {"op_basic_info"}, source=source, role="work distribution raw artifact"),
    ]
    missing = []
    blocked = []
    if not facts.raw_group_present({"op_basic_info"}):
        blocked.append("missing opbasic_workload profiler evidence")
        missing.append(missing_design_evidence(source=source, artifact="OpBasicInfo.csv", role="opbasic_workload artifact is missing"))
    workload = context_value(context, ["benchmark", "workload"])
    if isinstance(workload, dict):
        for field in WORKLOAD_COMPARABILITY_FIELDS:
            if context_value(context, ["benchmark", "workload", field]) is None:
                blocked.append("missing workload context")
                missing.append(
                    missing_design_evidence(
                        source=source,
                        artifact="analysis/tilelang_context.json",
                        field=field,
                        field_ref=f"benchmark.workload.{field}",
                        role="workload context field is missing",
                    )
                )
            else:
                available.append(context_evidence(source, f"benchmark.workload.{field}", "workload context"))
    else:
        blocked.append("missing workload context")
        missing.append(
            missing_design_evidence(
                source=source,
                artifact="analysis/tilelang_context.json",
                field="workload",
                field_ref="benchmark.workload",
                role="workload context is missing",
            )
        )
    return design_question(
        "opbasic_workload",
        "opbasic_workload",
        "Should the next inspection compare work distribution and launch shape context against the intended TileLang design variable?",
        ["work_distribution", "block_dim", "shape_specialization", "tail_work"],
        available,
        missing,
        "Collect OpBasicInfo.csv with matching TileLang workload context, then compare block/work-distribution fields against the intended design variable.",
        blocked,
    )


def generated_context_records_from_facts(
    context: dict[str, Any] | None,
    facts: FeedbackEvidenceFacts,
    *,
    source: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    available = []
    missing = []
    blocked = []
    jit_debug = context_value(context, ["jit_debug"])
    if isinstance(jit_debug, dict) and jit_debug.get("found") is True:
        available.append(
            design_evidence(
                source=source,
                artifact="analysis/tilelang_context.json",
                field="jit_debug",
                field_ref="jit_debug",
                role="generated TileLang source context",
            )
        )
    else:
        blocked.append("missing generated context")
        missing.append(
            missing_design_evidence(
                source=source,
                artifact="analysis/tilelang_context.json",
                field="jit_debug",
                field_ref="jit_debug",
                role="generated TileLang source context is missing",
            )
        )
    if facts.simulator_present:
        available.append(
            design_evidence(
                source=source,
                artifact="analysis/simulator_hotspots.json",
                field="simulator_hotspot_model_schema_version",
                field_ref="simulator_hotspot_model_schema_version",
                role="optional source inspection context",
            )
        )
    if facts.raw_inventory_present():
        available.append(
            design_evidence(
                source=source,
                artifact="analysis/raw_artifact_index.json",
                field="artifacts",
                field_ref="artifacts[status=parsed]",
                role="on-device evidence required before source inspection",
            )
        )
    else:
        blocked.append("missing on-device profiler evidence")
        missing.append(
            missing_design_evidence(
                source=source,
                artifact="analysis/raw_artifact_index.json",
                field="artifacts",
                field_ref="artifacts[status=parsed]",
                role="on-device evidence is required before source inspection",
            )
        )
    return available, missing, blocked


def generated_context_question_from_facts(
    context: dict[str, Any] | None,
    facts: FeedbackEvidenceFacts,
    *,
    source: str,
) -> dict[str, Any]:
    available, missing, blocked = generated_context_records_from_facts(context, facts, source=source)
    return design_question(
        "generated_context",
        "generated_context",
        "Can the generated TileLang context guide source inspection after on-device evidence is available?",
        ["generated_source_context", "jit_configuration", "source_inspection_context"],
        available,
        missing,
        "Pair the generated TileLang source context with parsed on-device profiler artifacts before using it to guide source inspection.",
        blocked,
    )


def comparison_candidate_comparability_question_from_facts(
    a_facts: FeedbackEvidenceFacts,
    b_facts: FeedbackEvidenceFacts,
    a_context: dict[str, Any] | None,
    b_context: dict[str, Any] | None,
    contract_blockers: list[str],
) -> dict[str, Any]:
    a_question = candidate_comparability_question_from_facts(a_facts, a_context, source="a")
    b_question = candidate_comparability_question_from_facts(b_facts, b_context, source="b")
    return design_question(
        "candidate_comparability",
        "candidate_comparability",
        "Are both runs complete enough to compare one changed design variable under the same workload and profiler scope?",
        ["workload", "correctness", "provenance", "metric_scope", "raw_artifact_inventory"],
        [*a_question["available_evidence"], *b_question["available_evidence"]],
        [*a_question["missing_evidence"], *b_question["missing_evidence"]],
        "Collect or align the missing evidence on the named branch before comparing the design variable.",
        contract_blockers,
    )


def comparison_family_question_from_facts(
    question_id: str,
    evidence_family: str,
    question: str,
    related_design_variables: list[str],
    a_facts: FeedbackEvidenceFacts,
    b_facts: FeedbackEvidenceFacts,
    groups: set[str],
    *,
    required_artifacts: list[str],
    next_experiment: str,
) -> dict[str, Any]:
    a_question = family_question_from_facts(
        question_id,
        evidence_family,
        question,
        related_design_variables,
        a_facts,
        groups,
        source="a",
        required_artifacts=required_artifacts,
        next_experiment=next_experiment,
    )
    b_question = family_question_from_facts(
        question_id,
        evidence_family,
        question,
        related_design_variables,
        b_facts,
        groups,
        source="b",
        required_artifacts=required_artifacts,
        next_experiment=next_experiment,
    )
    return design_question(
        question_id,
        evidence_family,
        question,
        related_design_variables,
        [*a_question["available_evidence"], *b_question["available_evidence"]],
        [*a_question["missing_evidence"], *b_question["missing_evidence"]],
        next_experiment,
        [*prefix_blockers("a", a_question["blocked_by"]), *prefix_blockers("b", b_question["blocked_by"])],
    )


def comparison_opbasic_workload_question_from_facts(
    a_facts: FeedbackEvidenceFacts,
    b_facts: FeedbackEvidenceFacts,
    a_context: dict[str, Any] | None,
    b_context: dict[str, Any] | None,
) -> dict[str, Any]:
    question = "Should the next inspection compare work distribution and launch shape context between the two runs?"
    next_experiment = "Collect OpBasicInfo.csv and complete workload context for both runs before comparing work distribution."
    a_question = opbasic_workload_question_from_facts(a_facts, a_context, source="a")
    b_question = opbasic_workload_question_from_facts(b_facts, b_context, source="b")
    return design_question(
        "opbasic_workload",
        "opbasic_workload",
        question,
        ["work_distribution", "block_dim", "shape_specialization", "tail_work"],
        [*a_question["available_evidence"], *b_question["available_evidence"]],
        [*a_question["missing_evidence"], *b_question["missing_evidence"]],
        next_experiment,
        [*prefix_blockers("a", a_question["blocked_by"]), *prefix_blockers("b", b_question["blocked_by"])],
    )


def comparison_generated_context_question_from_facts(
    a_context: dict[str, Any] | None,
    b_context: dict[str, Any] | None,
    a_facts: FeedbackEvidenceFacts,
    b_facts: FeedbackEvidenceFacts,
) -> dict[str, Any]:
    a_available, a_missing, a_blocked = generated_context_records_from_facts(a_context, a_facts, source="a")
    b_available, b_missing, b_blocked = generated_context_records_from_facts(b_context, b_facts, source="b")
    return design_question(
        "generated_context",
        "generated_context",
        "Can both generated TileLang contexts guide source inspection after on-device evidence is available?",
        ["generated_source_context", "jit_configuration", "source_inspection_context"],
        [*a_available, *b_available],
        [*a_missing, *b_missing],
        "Pair generated TileLang source context from both runs with parsed on-device profiler artifacts before using it to guide source inspection.",
        [*prefix_blockers("a", a_blocked), *prefix_blockers("b", b_blocked)],
    )


def comparison_pipeline_expression_question_from_facts(
    a_context: dict[str, Any] | None,
    b_context: dict[str, Any] | None,
    a_facts: FeedbackEvidenceFacts,
    b_facts: FeedbackEvidenceFacts,
) -> dict[str, Any]:
    a_available, a_missing, a_blocked = generated_context_records_from_facts(a_context, a_facts, source="a")
    b_available, b_missing, b_blocked = generated_context_records_from_facts(b_context, b_facts, source="b")
    return design_question(
        "pipeline_expression",
        "pipeline_expression",
        "Does correctness-passing on-device evidence exist to compare the intended pipeline-stage expression between the two generated contexts?",
        ["pipeline_stage_expression", "generated_source_context", "correctness", "on_device_evidence"],
        [*a_available, *b_available],
        [*a_missing, *b_missing],
        "Keep compile-blocked evidence separate, then compare only correctness-passing on-device runs with matching workload and profiler scope.",
        [*prefix_blockers("a", a_blocked), *prefix_blockers("b", b_blocked)],
    )


def build_single_run_design_feedback(
    summary: dict[str, Any] | None,
    context: dict[str, Any] | None,
    raw_index: dict[str, Any] | None,
    provenance: dict[str, Any] | None = None,
    simulator: dict[str, Any] | None = None,
    *,
    source: str = "run",
) -> dict[str, Any]:
    evidence = RunEvidence.from_loaded(
        Path("."),
        summary,
        raw_artifact_index=raw_index,
        provenance=provenance,
        simulator_hotspots=simulator,
    )
    return build_single_run_design_feedback_from_evidence(evidence, context, source=source)


def build_single_run_design_feedback_from_evidence(
    evidence: RunEvidence,
    context: dict[str, Any] | None,
    *,
    source: str = "run",
) -> dict[str, Any]:
    facts = evidence.feedback_facts()
    contract_blockers = single_run_contract_blockers_from_facts(facts, context)
    compiled = compiled_value(context)
    passed = correctness_passed(context)
    hard_blocked = compiled is False or passed is False
    questions: list[dict[str, Any]] = []
    if hard_blocked:
        available: list[dict[str, Any]] = []
        missing = [
            missing_design_evidence(
                source=source,
                artifact="analysis/tilelang_context.json",
                field="raw",
                field_ref="benchmark.correctness.raw",
                role="correctness pass is required before profiler design questions",
            ),
            missing_design_evidence(
                source=source,
                artifact="analysis/raw_artifact_index.json",
                field="artifacts",
                field_ref="artifacts[status=parsed]",
                role="parsed profiler evidence is required after correctness passes",
            ),
        ]
        if compiled is not None:
            available.append(context_evidence(source, "benchmark.candidate.compiled", "compile status"))
        else:
            missing.insert(
                0,
                missing_design_evidence(
                    source=source,
                    artifact="analysis/tilelang_context.json",
                    field="compiled",
                    field_ref="benchmark.candidate.compiled",
                    role="compile status is missing",
                ),
            )
        questions.append(
            design_question(
                "missing_evidence",
                "missing_evidence",
                "Which required candidate evidence is missing before design feedback can be asked?",
                ["compile_status", "correctness", "profiler_evidence"],
                available,
                missing,
                "Fix compile or correctness collection first, then collect on-device profiler evidence for the same workload.",
                contract_blockers,
            )
        )
        return design_feedback_payload(questions, contract_blockers)

    questions.append(candidate_comparability_question_from_facts(facts, context, source=source))
    questions.append(
        family_question_from_facts(
            "memory_cache",
            "memory_cache",
            "Should the next inspection compare memory movement or cache context for the changed design variable?",
            ["memory_movement", "cache_context", "metric_scope"],
            facts,
            {"memory", "l2_cache"},
            source=source,
            required_artifacts=["Memory.csv", "MemoryL0.csv", "MemoryUB.csv", "L2Cache.csv"],
            next_experiment="Collect the Default metric follow-up artifacts containing Memory.csv, MemoryL0.csv, MemoryUB.csv, and L2Cache.csv for the same workload.",
        )
    )
    questions.append(
        family_question_from_facts(
            "pipe_arithmetic",
            "pipe_arithmetic",
            "Should the next inspection compare Cube, Vector, Scalar, or MTE path mix against the intended generated code?",
            ["pipe_mix", "arithmetic_mix", "generated_code_path"],
            facts,
            {"pipe_utilization", "arithmetic_utilization"},
            source=source,
            required_artifacts=["PipeUtilization.csv", "ArithmeticUtilization.csv"],
            next_experiment="Collect PipeUtilization.csv and ArithmeticUtilization.csv for the same workload before comparing path mix.",
        )
    )
    questions.append(opbasic_workload_question_from_facts(facts, context, source=source))
    if context_value(context, ["jit_debug", "found"]) is True or facts.simulator_present:
        questions.append(generated_context_question_from_facts(context, facts, source=source))
    return design_feedback_payload(questions, contract_blockers)


def comparison_contract_blockers_from_facts(
    compatibility: dict[str, Any] | None,
    a_context: dict[str, Any] | None,
    b_context: dict[str, Any] | None,
    a_facts: FeedbackEvidenceFacts,
    b_facts: FeedbackEvidenceFacts,
) -> list[str]:
    blockers = []
    if compiled_value(a_context) is False:
        blockers.append("baseline compile stage did not produce a runnable candidate")
    if compiled_value(b_context) is False:
        blockers.append("candidate compile stage did not produce a runnable candidate")
    if correctness_passed(a_context) is False:
        blockers.append("baseline correctness did not pass")
    if correctness_passed(b_context) is False:
        blockers.append("candidate correctness did not pass")
    if isinstance(compatibility, dict) and compatibility.get("can_compare") is False:
        blockers.extend(str(reason) for reason in compatibility.get("blocking_reasons") or ["incompatible runs"])
    for label, facts in [
        ("baseline", a_facts),
        ("candidate", b_facts),
    ]:
        if not facts.summary_present:
            blockers.append(f"{label} missing analysis/summary.json")
        if not facts.raw_artifact_index_present:
            blockers.append(f"{label} missing analysis/raw_artifact_index.json")
        elif not facts.raw_inventory_present():
            blockers.append(f"{label} missing parsed on-device profiler evidence")
    return blockers


def build_comparison_design_feedback(
    a_summary: dict[str, Any] | None,
    b_summary: dict[str, Any] | None,
    a_context: dict[str, Any] | None,
    b_context: dict[str, Any] | None,
    a_raw_index: dict[str, Any] | None,
    b_raw_index: dict[str, Any] | None,
    a_provenance: dict[str, Any] | None,
    b_provenance: dict[str, Any] | None,
    compatibility: dict[str, Any] | None,
) -> dict[str, Any]:
    a_evidence = RunEvidence.from_loaded(
        Path("."),
        a_summary,
        raw_artifact_index=a_raw_index,
        provenance=a_provenance,
    )
    b_evidence = RunEvidence.from_loaded(
        Path("."),
        b_summary,
        raw_artifact_index=b_raw_index,
        provenance=b_provenance,
    )
    return build_comparison_design_feedback_from_evidence(
        a_evidence,
        b_evidence,
        a_context,
        b_context,
        compatibility,
    )


def build_comparison_design_feedback_from_evidence(
    a_evidence: RunEvidence,
    b_evidence: RunEvidence,
    a_context: dict[str, Any] | None,
    b_context: dict[str, Any] | None,
    compatibility: dict[str, Any] | None,
) -> dict[str, Any]:
    a_facts = a_evidence.feedback_facts()
    b_facts = b_evidence.feedback_facts()
    contract_blockers = comparison_contract_blockers_from_facts(
        compatibility,
        a_context,
        b_context,
        a_facts,
        b_facts,
    )
    questions: list[dict[str, Any]] = [
        comparison_candidate_comparability_question_from_facts(
            a_facts,
            b_facts,
            a_context,
            b_context,
            contract_blockers,
        )
    ]
    if not contract_blockers:
        questions.extend(
            [
                comparison_family_question_from_facts(
                    "memory_cache",
                    "memory_cache",
                    "Should the next inspection compare memory movement or cache context between the two runs for the changed design variable?",
                    ["memory_movement", "cache_context", "metric_scope"],
                    a_facts,
                    b_facts,
                    {"memory", "l2_cache"},
                    required_artifacts=["Memory.csv", "MemoryL0.csv", "MemoryUB.csv", "L2Cache.csv"],
                    next_experiment="Collect matching memory/cache follow-up artifacts for both runs, then compare the cited fields under the same metric scope.",
                ),
                comparison_family_question_from_facts(
                    "pipe_arithmetic",
                    "pipe_arithmetic",
                    "Should the next inspection compare Cube, Vector, Scalar, or MTE path mix between the two runs?",
                    ["pipe_mix", "arithmetic_mix", "generated_code_path"],
                    a_facts,
                    b_facts,
                    {"pipe_utilization", "arithmetic_utilization"},
                    required_artifacts=["PipeUtilization.csv", "ArithmeticUtilization.csv"],
                    next_experiment="Collect matching pipe and arithmetic utilization artifacts for both runs before comparing path mix.",
                ),
                comparison_opbasic_workload_question_from_facts(a_facts, b_facts, a_context, b_context),
            ]
        )
        if context_value(a_context, ["jit_debug", "found"]) is True or context_value(b_context, ["jit_debug", "found"]) is True:
            questions.append(comparison_pipeline_expression_question_from_facts(a_context, b_context, a_facts, b_facts))
            questions.append(comparison_generated_context_question_from_facts(a_context, b_context, a_facts, b_facts))
    return design_feedback_payload(questions, contract_blockers)


def md_escape(value: Any) -> str:
    if value is None:
        return "n/a"
    return str(value).replace("|", "\\|")


def evidence_label(item: dict[str, Any]) -> str:
    source = item.get("source")
    role = item.get("role")
    artifact = item.get("artifact") or "n/a"
    field_ref = item.get("field_ref") or item.get("field")
    prefix_parts = [str(part) for part in [source, role] if part not in (None, "")]
    prefix = ": ".join(prefix_parts)
    body = str(artifact)
    if field_ref:
        body = f"{body} ({field_ref})"
    if prefix:
        return f"{prefix}: {body}"
    return body


def markdown_evidence_sample(items: list[Any], limit_per_source: int = 5) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for item in items:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "unknown")
        if counts[source] >= limit_per_source:
            continue
        selected.append(item)
        counts[source] += 1
    return selected


def render_design_feedback_markdown(feedback: dict[str, Any]) -> list[str]:
    lines = ["## Design Feedback", "", f"Status: `{feedback.get('status', 'blocked')}`", ""]
    questions = feedback.get("questions")
    if not isinstance(questions, list) or not questions:
        lines.append("No design feedback questions recorded.")
        return lines
    lines.extend(
        [
            "| Question ID | Family | Question | Available Evidence | Missing Evidence | Blockers |",
            "|---|---|---|---:|---:|---|",
        ]
    )
    for question in questions:
        if not isinstance(question, dict):
            continue
        blockers = question.get("blocked_by") if isinstance(question.get("blocked_by"), list) else []
        lines.append(
            f"| `{md_escape(question.get('id'))}` | `{md_escape(question.get('evidence_family'))}` | "
            f"{md_escape(question.get('question'))} | "
            f"{len(question.get('available_evidence') or [])} | {len(question.get('missing_evidence') or [])} | "
            f"{md_escape(', '.join(str(item) for item in blockers) if blockers else 'none')} |"
        )
    for question in questions:
        if not isinstance(question, dict):
            continue
        lines.extend(
            [
                "",
                f"### {md_escape(question.get('id'))}",
                "",
                f"- Question: {md_escape(question.get('question'))}",
                f"- Related design variables: `{md_escape(', '.join(str(item) for item in question.get('related_design_variables') or []))}`",
            ]
        )
        available = question.get("available_evidence") if isinstance(question.get("available_evidence"), list) else []
        if available:
            lines.append("- Available evidence:")
            for item in markdown_evidence_sample(available):
                lines.append(f"  - `{md_escape(evidence_label(item))}`")
        missing = question.get("missing_evidence") if isinstance(question.get("missing_evidence"), list) else []
        if missing:
            lines.append("- Missing evidence:")
            for item in markdown_evidence_sample(missing):
                lines.append(f"  - `{md_escape(evidence_label(item))}`")
        blockers = question.get("blocked_by") if isinstance(question.get("blocked_by"), list) else []
        if blockers:
            lines.append("- Blocked by:")
            for blocker in blockers:
                lines.append(f"  - {md_escape(blocker)}")
        lines.append(f"- Next experiment: {md_escape(question.get('next_experiment'))}")
    return lines


def single_run_verdict(
    summary: dict[str, Any] | None,
    context: dict[str, Any] | None,
    raw_index: dict[str, Any] | None,
) -> dict[str, Any]:
    evidence = RunEvidence.from_loaded(Path("."), summary, raw_artifact_index=raw_index)
    return single_run_verdict_from_evidence(evidence, context)


def single_run_verdict_from_evidence(
    evidence: RunEvidence,
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    facts = evidence.feedback_facts()
    reject_reasons = benchmark_reject_reasons(context)
    if reject_reasons:
        return {"decision": "reject", "policy": "single_run_v1", "reasons": reject_reasons}

    reasons = []
    if not facts.summary_present:
        reasons.append("missing analysis/summary.json")
    if not isinstance(context, dict):
        reasons.append("missing analysis/tilelang_context.json")
    if correctness_passed(context) is not True:
        reasons.append("correctness pass is not recorded")
    if runtime_mean_ms(context) is None:
        reasons.append("candidate runtime is missing")
    if not facts.profiler_evidence_present():
        reasons.append("profiler evidence is missing")
    if facts.summary_present:
        if not facts.readiness_status()["present"]:
            reasons.append("evidence readiness is missing")
        elif not facts.readiness_at_least(MIN_COMPARISON_READINESS_LEVEL, READINESS_LEVEL_ORDER):
            reasons.append(
                f"evidence readiness level {facts.readiness_level() or 'unknown'} is below {MIN_COMPARISON_READINESS_LEVEL}"
            )
    actions = facts.combined_pending_collection_actions()
    if actions:
        action_ids = collection_action_ids(actions)
        reasons.append("pending collection actions: " + ", ".join(action_ids))

    if reasons:
        return {"decision": "inconclusive", "policy": "single_run_v1", "reasons": reasons}
    return {
        "decision": "keep",
        "policy": "single_run_v1",
        "reasons": [
            "correctness passed, runtime is present, profiler evidence is directional or better, and no required collection action is pending"
        ],
    }


def sourced_value(item: Any) -> Any:
    if isinstance(item, dict) and "value" in item:
        return item.get("value")
    return item


def compatibility_item(item_id: str, a_value: Any, b_value: Any) -> dict[str, Any]:
    if a_value is None or b_value is None:
        status = "missing"
    elif values_match(a_value, b_value):
        status = "match"
    else:
        status = "mismatch"
    return {"id": item_id, "status": status, "a": a_value, "b": b_value}


def optional_compatibility_item(item_id: str, a_value: Any, b_value: Any) -> dict[str, Any]:
    if a_value is None and b_value is None:
        return {"id": item_id, "status": "match", "a": a_value, "b": b_value}
    return compatibility_item(item_id, a_value, b_value)


def readiness_level_compatibility_item_from_facts(
    a_facts: FeedbackEvidenceFacts,
    b_facts: FeedbackEvidenceFacts,
) -> dict[str, Any]:
    a_level = a_facts.readiness_level()
    b_level = b_facts.readiness_level()
    if a_level is None or b_level is None:
        status = "missing"
    elif not a_facts.readiness_at_least(MIN_COMPARISON_READINESS_LEVEL, READINESS_LEVEL_ORDER) or not b_facts.readiness_at_least(
        MIN_COMPARISON_READINESS_LEVEL, READINESS_LEVEL_ORDER
    ):
        status = "insufficient"
    else:
        status = "match"
    return {"id": "evidence_readiness.level", "status": status, "a": a_level, "b": b_level}


def readiness_family_compatibility_item_from_facts(
    a_facts: FeedbackEvidenceFacts,
    b_facts: FeedbackEvidenceFacts,
) -> dict[str, Any]:
    a_families = a_facts.material_evidence_families()
    b_families = b_facts.material_evidence_families()
    if not a_families or not b_families:
        status = "missing"
    elif values_match(a_families, b_families):
        status = "match"
    else:
        status = "mismatch"
    return {"id": "evidence_readiness.material_families", "status": status, "a": a_families, "b": b_families}


def readiness_followup_compatibility_item_from_facts(
    a_facts: FeedbackEvidenceFacts,
    b_facts: FeedbackEvidenceFacts,
) -> dict[str, Any]:
    a_actions = collection_action_ids(a_facts.combined_pending_collection_actions())
    b_actions = collection_action_ids(b_facts.combined_pending_collection_actions())
    status = "match" if not a_actions and not b_actions else "pending"
    return {"id": "evidence_readiness.pending_followups", "status": status, "a": a_actions, "b": b_actions}


def verdict_compatibility(
    a_summary: dict[str, Any] | None,
    b_summary: dict[str, Any] | None,
    a_context: dict[str, Any] | None,
    b_context: dict[str, Any] | None,
    a_provenance: dict[str, Any] | None,
    b_provenance: dict[str, Any] | None,
) -> dict[str, Any]:
    a_evidence = RunEvidence.from_loaded(Path("."), a_summary, provenance=a_provenance)
    b_evidence = RunEvidence.from_loaded(Path("."), b_summary, provenance=b_provenance)
    return verdict_compatibility_from_evidence(a_evidence, b_evidence, a_context, b_context)


def verdict_compatibility_from_evidence(
    a_evidence: RunEvidence,
    b_evidence: RunEvidence,
    a_context: dict[str, Any] | None,
    b_context: dict[str, Any] | None,
) -> dict[str, Any]:
    a_facts = a_evidence.feedback_facts()
    b_facts = b_evidence.feedback_facts()
    workload_checks = [
        compatibility_item(
            f"workload.{field}",
            context_value(a_context, ["benchmark", "workload", field]),
            context_value(b_context, ["benchmark", "workload", field]),
        )
        for field in ["id", "shape", "dtype", "case_count"]
    ]
    profiler_checks = [
        compatibility_item(
            "cann_version",
            a_facts.provenance_value(["cann_version"]),
            b_facts.provenance_value(["cann_version"]),
        ),
        compatibility_item(
            "hardware_summary",
            a_facts.provenance_value(["hardware", "summary"]),
            b_facts.provenance_value(["hardware", "summary"]),
        ),
        optional_compatibility_item(
            "profile_command",
            a_facts.provenance_value(["profile_command"]),
            b_facts.provenance_value(["profile_command"]),
        ),
        compatibility_item("metric_scope", a_facts.metric_scope_value(), b_facts.metric_scope_value()),
        compatibility_item(
            "profile_output_segments",
            a_facts.provenance_payload_value(["profile_output_segments"]),
            b_facts.provenance_payload_value(["profile_output_segments"]),
        ),
    ]
    readiness_checks = [
        readiness_level_compatibility_item_from_facts(a_facts, b_facts),
        readiness_family_compatibility_item_from_facts(a_facts, b_facts),
        readiness_followup_compatibility_item_from_facts(a_facts, b_facts),
    ]
    lineage = [
        compatibility_item(
            "payload.sha256",
            context_value(a_context, ["sources", "payload", "sha256"]),
            context_value(b_context, ["sources", "payload", "sha256"]),
        ),
        compatibility_item(
            "jit_config",
            context_value(a_context, ["benchmark", "jit_config"]),
            context_value(b_context, ["benchmark", "jit_config"]),
        ),
    ]
    blocking = [item for item in [*workload_checks, *profiler_checks, *readiness_checks] if item["status"] != "match"]
    return {
        "can_compare": not blocking,
        "workload": workload_checks,
        "profiler": profiler_checks,
        "evidence_readiness": readiness_checks,
        "lineage": lineage,
        "blocking_reasons": [f"{item['id']} {item['status']}" for item in blocking],
    }


def comparison_verdict(
    a_summary: dict[str, Any] | None,
    b_summary: dict[str, Any] | None,
    a_context: dict[str, Any] | None,
    b_context: dict[str, Any] | None,
    a_raw_index: dict[str, Any] | None,
    b_raw_index: dict[str, Any] | None,
    a_provenance: dict[str, Any] | None,
    b_provenance: dict[str, Any] | None,
    *,
    min_speedup_pct: float = DEFAULT_MIN_SPEEDUP_PCT,
) -> dict[str, Any]:
    a_evidence = RunEvidence.from_loaded(
        Path("."),
        a_summary,
        raw_artifact_index=a_raw_index,
        provenance=a_provenance,
    )
    b_evidence = RunEvidence.from_loaded(
        Path("."),
        b_summary,
        raw_artifact_index=b_raw_index,
        provenance=b_provenance,
    )
    return comparison_verdict_from_evidence(
        a_evidence,
        b_evidence,
        a_context,
        b_context,
        min_speedup_pct=min_speedup_pct,
    )


def comparison_verdict_from_evidence(
    a_evidence: RunEvidence,
    b_evidence: RunEvidence,
    a_context: dict[str, Any] | None,
    b_context: dict[str, Any] | None,
    *,
    min_speedup_pct: float = DEFAULT_MIN_SPEEDUP_PCT,
) -> dict[str, Any]:
    min_speedup_pct = normalize_min_speedup_pct(min_speedup_pct)
    compatibility = verdict_compatibility_from_evidence(
        a_evidence,
        b_evidence,
        a_context,
        b_context,
    )
    a_facts = a_evidence.feedback_facts()
    b_facts = b_evidence.feedback_facts()
    baseline_ms = runtime_mean_ms(a_context)
    candidate_ms = runtime_mean_ms(b_context)
    speedup_pct = None
    delta_ms = None
    if baseline_ms is not None and candidate_ms is not None:
        delta_ms = candidate_ms - baseline_ms
        if baseline_ms != 0:
            speedup_pct = (baseline_ms - candidate_ms) / abs(baseline_ms) * 100.0

    reject_reasons = [
        *benchmark_reject_reasons(a_context, "baseline"),
        *benchmark_reject_reasons(b_context, "candidate"),
    ]
    if reject_reasons:
        decision = "reject"
        reasons = reject_reasons
    elif not compatibility["can_compare"]:
        decision = "inconclusive"
        reasons = ["incompatible runs: " + ", ".join(compatibility["blocking_reasons"])]
    elif not a_facts.profiler_evidence_present() or not b_facts.profiler_evidence_present():
        decision = "inconclusive"
        reasons = ["profiler evidence is missing"]
    elif correctness_passed(a_context) is not True or correctness_passed(b_context) is not True:
        decision = "inconclusive"
        reasons = ["baseline and candidate correctness passes are not both recorded"]
    elif baseline_ms is None or candidate_ms is None or speedup_pct is None:
        decision = "inconclusive"
        reasons = ["comparable runtime is missing"]
    elif speedup_pct >= min_speedup_pct:
        decision = "promote"
        reasons = [f"candidate mean runtime improves by {speedup_pct:.6g}%"]
    elif speedup_pct <= -min_speedup_pct:
        decision = "reject"
        reasons = [f"candidate mean runtime regresses by {-speedup_pct:.6g}%"]
    else:
        decision = "inconclusive"
        reasons = [f"runtime change is inside +/-{min_speedup_pct:.6g}% threshold"]

    return {
        "decision": decision,
        "policy": "baseline_v1",
        "min_speedup_pct": min_speedup_pct,
        "can_compare": compatibility["can_compare"],
        "compatibility": compatibility,
        "baseline_mean_ms": baseline_ms,
        "candidate_mean_ms": candidate_ms,
        "runtime_delta_ms": delta_ms,
        "candidate_speedup_pct": speedup_pct,
        "reasons": reasons,
    }


def run_display(path: Path) -> str:
    if path.is_absolute():
        return f"<abs-path>/{path.name}"
    return path.as_posix()
