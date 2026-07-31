"""Evidence relation derivation for Evidence Model analysis."""
from __future__ import annotations

from ._evidence_signals import (
    direction_evidence,
    first_app_timing_signal,
    signals_with_values_for_groups,
)


RELATION_SOURCE_CONTEXT_ROLES = {
    "source_lines": "source-line inspection context",
    "instructions": "instruction inspection context",
    "pipeline_events": "pipeline inspection context",
}


def first_present_value(row: dict, keys: list[str]) -> object:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def source_context_signal(row: dict) -> object:
    return first_present_value(row, ["signal", "evidence_id", "max_event_name", "source_file", "instruction"])


def source_context_value(row: dict) -> object:
    return first_present_value(row, ["value", "duration", "running_time(us)", "running_time", "max_duration"])


def evidence_relation_target(summary: dict, timing: dict) -> str:
    coverage = summary.get("profile_coverage")
    if isinstance(coverage, dict) and coverage.get("explicit_target"):
        expected = coverage.get("expected_counts") or {}
        if expected:
            return ", ".join(f"{name} x{count}" for name, count in expected.items())
    identity = summary.get("target_identity")
    if isinstance(identity, dict):
        matched = [
            str(item.get("name"))
            for item in identity.get("observed", [])
            if isinstance(item, dict) and item.get("status") == "match" and item.get("name")
        ]
        if matched:
            return ", ".join(matched)
    return str(timing.get("signal") or "profiled target")


def evidence_relation_confidence(summary: dict) -> str | None:
    confidence = str((summary.get("target_identity") or {}).get("confidence") or "low")
    if confidence == "blocked":
        return None
    return confidence if confidence in {"high", "medium", "low"} else "low"


def source_pipeline_signals(dimensions: list[dict], kinds: list[str]) -> list[dict]:
    out = []
    kind_set = set(kinds)
    for dimension in dimensions:
        if dimension.get("id") != "source_pipeline_context":
            continue
        for signal in dimension.get("signals", []):
            if signal.get("group") == "simulator" and signal.get("kind") in kind_set and signal.get("value") is not None:
                out.append(signal)
    return out


def simulator_context_ref(group: str, index: int, row: dict) -> dict:
    ref = {
        "artifact": "analysis/simulator_hotspots.json",
        "field_ref": f"{group}[{index}]",
        "role": RELATION_SOURCE_CONTEXT_ROLES.get(group, "simulator inspection context"),
    }
    signal = source_context_signal(row)
    if signal not in (None, ""):
        ref["signal"] = signal
    value = source_context_value(row)
    if value not in (None, ""):
        ref["value"] = value
    return ref


def first_simulator_context_ref(model: dict, group: str) -> dict | None:
    rows = model.get(group)
    if not isinstance(rows, list):
        return None
    for index, row in enumerate(rows):
        if isinstance(row, dict):
            return simulator_context_ref(group, index, row)
    return None


def simulator_input_context_ref(model: dict, simulator_signal: dict) -> dict | None:
    artifact = simulator_signal.get("artifact")
    inputs = model.get("inputs")
    if not artifact or not isinstance(inputs, list):
        return None
    for index, row in enumerate(inputs):
        if not isinstance(row, dict) or row.get("artifact") != artifact:
            continue
        ref = {
            "artifact": "analysis/simulator_hotspots.json",
            "field_ref": f"inputs[{index}]",
            "role": "simulator input artifact context",
            "signal": row.get("artifact"),
        }
        for key in ["row_count", "event_count"]:
            if row.get(key) not in (None, ""):
                ref["value"] = row.get(key)
                break
        return ref
    return None


def evidence_relation(
    relation_id: str,
    kind: str,
    target: str,
    confidence: str,
    role: str,
    signals: list[dict],
    allowed_interpretation: str,
    blocked_interpretation: str,
    source_context_refs: list[dict] | None = None,
) -> dict:
    relation = {
        "id": relation_id,
        "kind": kind,
        "target": target,
        "confidence": confidence,
        "role": role,
        "evidence": direction_evidence(signals),
        "allowed_interpretation": allowed_interpretation,
        "blocked_interpretation": blocked_interpretation,
    }
    if source_context_refs:
        relation["source_context_refs"] = source_context_refs
    return relation


def build_evidence_relations(summary: dict) -> list[dict]:
    dimensions = summary.get("analysis_dimensions")
    if not isinstance(dimensions, list):
        return []
    timing = first_app_timing_signal(dimensions)
    if not timing:
        return []
    confidence = evidence_relation_confidence(summary)
    if confidence is None:
        return []
    target = evidence_relation_target(summary, timing)

    relations = []
    coverage = summary.get("profile_coverage") or {}
    explicit_target = bool(coverage.get("explicit_target"))
    app_complete = bool(((coverage.get("segments") or {}).get("app") or {}).get("count_complete"))
    selected_families = coverage.get("selected_segments_by_family") or {}
    metric_signals = signals_with_values_for_groups(
        dimensions,
        ["pipe_utilization", "arithmetic_utilization", "memory", "l2_cache", "resource_conflict"],
    )
    if explicit_target:
        eligible_groups = {
            group
            for family, groups in {
                "pipe_utilization": ("pipe_utilization",),
                "arithmetic_utilization": ("arithmetic_utilization",),
                "memory": ("memory",),
                "l2_cache": ("l2_cache",),
                "resource_conflict": ("resource_conflict",),
            }.items()
            if app_complete and selected_families.get(family)
            for group in groups
        }
        metric_signals = [signal for signal in metric_signals if signal.get("group") in eligible_groups]
    metric_by_group = {signal.get("group"): signal for signal in metric_signals}

    metric_specs = [
        (
            "timing_plus_pipe",
            ["pipe_utilization"],
            ["pipe_utilization"],
            "mechanical timing-to-pipe artifact link",
            "Timing and PipeUtilization evidence can be inspected together for the recorded target.",
        ),
        (
            "timing_plus_arithmetic",
            ["arithmetic_utilization"],
            ["arithmetic_utilization"],
            "mechanical timing-to-arithmetic artifact link",
            "Timing and ArithmeticUtilization evidence can be inspected together for the recorded target.",
        ),
        (
            "timing_plus_memory_cache",
            ["memory", "l2_cache"],
            ["memory", "l2_cache"],
            "mechanical timing-to-memory/cache artifact link",
            "Timing and memory/cache evidence can be inspected together for the recorded target.",
        ),
        (
            "timing_plus_resource_conflict",
            ["resource_conflict"],
            ["resource_conflict"],
            "mechanical timing-to-resource-conflict artifact link",
            "Timing and ResourceConflictRatio evidence can be inspected together for the recorded target.",
        ),
    ]
    blocked = "This relation does not establish a performance cause, root cause, or code-change instruction by itself."
    for kind, groups, families, role, allowed in metric_specs:
        if explicit_target and (
            not app_complete or not any(selected_families.get(family) for family in families)
        ):
            continue
        signals = [metric_by_group[group] for group in groups if group in metric_by_group]
        if not signals:
            continue
        relations.append(
            evidence_relation(
                f"rel_{len(relations) + 1:02d}_{kind}",
                kind,
                target,
                confidence,
                role,
                [timing, *signals],
                allowed,
                blocked,
            )
        )

    if not metric_signals:
        return relations

    simulator_model = summary.get("_simulator_hotspot_model")
    if not isinstance(simulator_model, dict):
        simulator_model = {}
    simulator_specs = [
        (
            "timing_metric_plus_simulator_source",
            ["simulator_source_line"],
            "source_lines",
            "mechanical timing/metric-to-simulator-source artifact link",
            "Timing, operator metric, and simulator source-line context can be inspected together for the recorded target.",
        ),
        (
            "timing_metric_plus_simulator_instruction",
            ["simulator_instruction"],
            "instructions",
            "mechanical timing/metric-to-simulator-instruction artifact link",
            "Timing, operator metric, and simulator instruction context can be inspected together for the recorded target.",
        ),
        (
            "timing_metric_plus_simulator_trace",
            ["simulator_trace"],
            "pipeline_events",
            "mechanical timing/metric-to-simulator-trace artifact link",
            "Timing, operator metric, and simulator trace context can be inspected together for the recorded target.",
        ),
    ]
    primary_metric = metric_signals[0]
    for kind, simulator_kinds, model_group, role, allowed in simulator_specs:
        simulator_signals = source_pipeline_signals(dimensions, simulator_kinds)
        if not simulator_signals:
            continue
        context_ref = first_simulator_context_ref(simulator_model, model_group)
        if context_ref is None:
            context_ref = simulator_input_context_ref(simulator_model, simulator_signals[0])
        relations.append(
            evidence_relation(
                f"rel_{len(relations) + 1:02d}_{kind}",
                kind,
                target,
                confidence,
                role,
                [timing, primary_metric, simulator_signals[0]],
                allowed,
                blocked,
                [context_ref] if context_ref else None,
            )
        )
    return relations
