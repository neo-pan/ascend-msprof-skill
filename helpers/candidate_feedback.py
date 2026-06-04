"""Shared TileLang candidate feedback and verdict helpers."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_MIN_SPEEDUP_PCT = 1.0


def context_value(context: dict[str, Any] | None, path: list[str]) -> Any:
    value: Any = context
    for part in path:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def json_equal_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def values_match(a_value: Any, b_value: Any) -> bool:
    return json_equal_value(a_value) == json_equal_value(b_value)


def try_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def runtime_mean_ms(context: dict[str, Any] | None) -> float | None:
    mean_ms = try_float(context_value(context, ["benchmark", "candidate", "runtime_stats", "mean_ms"]))
    if mean_ms is not None:
        return mean_ms
    return try_float(context_value(context, ["benchmark", "candidate", "runtime"]))


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


def next_collection_actions(summary: dict[str, Any] | None) -> list[dict[str, Any]]:
    actions = (summary or {}).get("next_collection_actions")
    return actions if isinstance(actions, list) else []


def parsed_artifact_count(raw_index: dict[str, Any] | None) -> int:
    artifacts = (raw_index or {}).get("artifacts")
    if not isinstance(artifacts, list):
        return 0
    return sum(1 for item in artifacts if isinstance(item, dict) and item.get("status") == "parsed")


def profiler_evidence_present(summary: dict[str, Any] | None, raw_index: dict[str, Any] | None) -> bool:
    if not isinstance(summary, dict):
        return False
    return parsed_artifact_count(raw_index) > 0


def profiler_evidence_status(summary: dict[str, Any] | None, raw_index: dict[str, Any] | None) -> dict[str, Any]:
    artifacts = (raw_index or {}).get("artifacts")
    if not isinstance(artifacts, list):
        artifacts = []
    parsed = [item for item in artifacts if isinstance(item, dict) and item.get("status") == "parsed"]
    headline_groups = sorted((summary.get("headlines") or {}).keys()) if isinstance(summary, dict) else []
    actions = next_collection_actions(summary)
    group_counts = Counter(str(item.get("group") or "unknown") for item in parsed)
    segment_counts = Counter(str(item.get("segment") or "unknown") for item in parsed)
    return {
        "summary_present": isinstance(summary, dict),
        "raw_artifact_index_present": isinstance(raw_index, dict),
        "parsed_artifact_count": len(parsed),
        "parsed_group_counts": dict(sorted(group_counts.items())),
        "parsed_segment_counts": dict(sorted(segment_counts.items())),
        "headline_groups": headline_groups,
        "optimization_direction_count": len(summary.get("optimization_directions") or []) if isinstance(summary, dict) else 0,
        "next_collection_actions": actions,
        "evidence_present": profiler_evidence_present(summary, raw_index),
    }


def single_run_verdict(
    summary: dict[str, Any] | None,
    context: dict[str, Any] | None,
    raw_index: dict[str, Any] | None,
) -> dict[str, Any]:
    reject_reasons = benchmark_reject_reasons(context)
    if reject_reasons:
        return {"decision": "reject", "policy": "single_run_v1", "reasons": reject_reasons}

    reasons = []
    if not isinstance(summary, dict):
        reasons.append("missing analysis/summary.json")
    if not isinstance(context, dict):
        reasons.append("missing analysis/tilelang_context.json")
    if correctness_passed(context) is not True:
        reasons.append("correctness pass is not recorded")
    if runtime_mean_ms(context) is None:
        reasons.append("candidate runtime is missing")
    if not profiler_evidence_present(summary, raw_index):
        reasons.append("profiler evidence is missing")
    actions = next_collection_actions(summary)
    if actions:
        action_ids = [str(item.get("id") or "unknown") for item in actions if isinstance(item, dict)]
        reasons.append("pending collection actions: " + ", ".join(action_ids))

    if reasons:
        return {"decision": "inconclusive", "policy": "single_run_v1", "reasons": reasons}
    return {
        "decision": "keep",
        "policy": "single_run_v1",
        "reasons": [
            "correctness passed, runtime is present, profiler evidence is present, and no required collection action is pending"
        ],
    }


def sourced_value(item: Any) -> Any:
    if isinstance(item, dict) and "value" in item:
        return item.get("value")
    return item


def metric_scope_value(summary: dict[str, Any] | None) -> Any:
    scope = (summary or {}).get("metric_scope")
    return scope.get("value") if isinstance(scope, dict) else None


def provenance_value(provenance: dict[str, Any] | None, path: list[str]) -> Any:
    return sourced_value(context_value(provenance, path))


def compatibility_item(item_id: str, a_value: Any, b_value: Any) -> dict[str, Any]:
    if a_value is None or b_value is None:
        status = "missing"
    elif values_match(a_value, b_value):
        status = "match"
    else:
        status = "mismatch"
    return {"id": item_id, "status": status, "a": a_value, "b": b_value}


def verdict_compatibility(
    a_summary: dict[str, Any] | None,
    b_summary: dict[str, Any] | None,
    a_context: dict[str, Any] | None,
    b_context: dict[str, Any] | None,
    a_provenance: dict[str, Any] | None,
    b_provenance: dict[str, Any] | None,
) -> dict[str, Any]:
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
            provenance_value(a_provenance, ["cann_version"]),
            provenance_value(b_provenance, ["cann_version"]),
        ),
        compatibility_item(
            "hardware_summary",
            provenance_value(a_provenance, ["hardware", "summary"]),
            provenance_value(b_provenance, ["hardware", "summary"]),
        ),
        compatibility_item(
            "profile_command",
            provenance_value(a_provenance, ["profile_command"]),
            provenance_value(b_provenance, ["profile_command"]),
        ),
        compatibility_item("metric_scope", metric_scope_value(a_summary), metric_scope_value(b_summary)),
        compatibility_item(
            "profile_output_segments",
            context_value(a_provenance, ["profile_output_segments"]),
            context_value(b_provenance, ["profile_output_segments"]),
        ),
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
    blocking = [item for item in [*workload_checks, *profiler_checks] if item["status"] != "match"]
    return {
        "can_compare": not blocking,
        "workload": workload_checks,
        "profiler": profiler_checks,
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
    compatibility = verdict_compatibility(
        a_summary,
        b_summary,
        a_context,
        b_context,
        a_provenance,
        b_provenance,
    )
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
    elif not profiler_evidence_present(a_summary, a_raw_index) or not profiler_evidence_present(b_summary, b_raw_index):
        decision = "inconclusive"
        reasons = ["profiler evidence is missing"]
    elif next_collection_actions(a_summary) or next_collection_actions(b_summary):
        decision = "inconclusive"
        reasons = ["pending collection actions"]
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
