"""Evidence relation derivation for Evidence Model analysis."""
from __future__ import annotations

from .summary_types import Summary, SummaryFacts
from .simulator_types import SimulatorModel
from .analysis_types import AnalysisDimension, EvidenceRelation, EvidenceSignal
from ._evidence_signals import (
    relation_evidence,
    simulator_row_signal,
    app_timing_relation_signals,
    operator_relation_signals,
)


RELATION_SOURCE_CONTEXT_ROLES = {
    "source_lines": "source-line inspection context",
    "instructions": "instruction inspection context",
    "pipeline_events": "pipeline inspection context",
}


def evidence_relation_target(summary: SummaryFacts, timing: EvidenceSignal) -> str:
    coverage = summary.profile_coverage
    if coverage is not None and coverage.explicit_target:
        expected = coverage.expected_counts or {}
        if expected:
            return ", ".join(f"{name} x{count}" for name, count in expected.items())
    identity = summary.target_identity
    if identity is not None:
        matched = [
            item.name for item in identity.observed if item.status == "match" and item.name
        ]
        if matched:
            return ", ".join(matched)
    return str(timing.signal or "profiled target")


def evidence_relation_confidence(summary: SummaryFacts) -> str | None:
    identity = summary.target_identity
    confidence = identity.confidence if identity is not None else "low"
    if confidence == "blocked":
        return None
    return confidence if confidence in {"high", "medium", "low"} else "low"


def source_pipeline_signals(dimensions: tuple[AnalysisDimension, ...], kinds: list[str]) -> list[EvidenceSignal]:
    out = []
    kind_set = set(kinds)
    for dimension in dimensions:
        if dimension.id != "source_pipeline_context":
            continue
        for signal in dimension.signals:
            if signal.group == "simulator" and signal.kind in kind_set and signal.value is not None:
                out.append(signal)
    return out


def first_simulator_context_ref(model: SimulatorModel | None, group: str) -> dict | None:
    if model is None:
        return None
    for index, row in enumerate(getattr(model, group)):
        signal = simulator_row_signal(group, index, row)
        if signal is not None:
            return {'artifact': 'analysis/simulator_hotspots.json', 'field_ref': f'{group}[{index}]',
                    'role': RELATION_SOURCE_CONTEXT_ROLES[group], 'signal': signal.signal, 'value': signal.value}
    return None


def evidence_relation(
    relation_id: str,
    kind: str,
    target: str,
    confidence: str,
    role: str,
    signals: list[EvidenceSignal],
    allowed_interpretation: str,
    blocked_interpretation: str,
    source_context_refs: list[dict] | None = None,
) -> EvidenceRelation:
    relation = {
        "id": relation_id,
        "kind": kind,
        "target": target,
        "confidence": confidence,
        "role": role,
        "evidence": relation_evidence(signals),
        "allowed_interpretation": allowed_interpretation,
        "blocked_interpretation": blocked_interpretation,
    }
    if source_context_refs:
        relation["source_context_refs"] = source_context_refs
    return EvidenceRelation.model_validate(relation)


def build_evidence_relations(summary: SummaryFacts, dimensions: tuple[AnalysisDimension, ...], simulator_model: SimulatorModel | None) -> tuple[EvidenceRelation, ...]:
    timings = app_timing_relation_signals(summary)
    if not timings:
        return ()
    confidence = evidence_relation_confidence(summary)
    if confidence is None:
        return ()
    target = evidence_relation_target(summary, timings[0])

    relations = []
    coverage = summary.profile_coverage
    explicit_target = coverage is not None and coverage.explicit_target
    app_complete = bool(coverage.segments["app"].count_complete) if coverage is not None else False
    selected_families = coverage.selected_segments_by_family if coverage is not None else {}
    metric_signals = operator_relation_signals(
        summary, ["pipe_utilization", "arithmetic_utilization", "memory", "l2_cache", "resource_conflict"],
    )

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
        signals = [signal for signal in metric_signals if signal.group in groups]
        if not signals:
            continue
        relations.append(
            evidence_relation(
                f"rel_{len(relations) + 1:02d}_{kind}",
                kind,
                target,
                confidence,
                role,
                [*timings, *signals],
                allowed,
                blocked,
            )
        )

    if not metric_signals:
        return tuple(relations)

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
    for kind, simulator_kinds, model_group, role, allowed in simulator_specs:
        simulator_signals = source_pipeline_signals(dimensions, simulator_kinds)
        if not simulator_signals:
            continue
        context_ref = first_simulator_context_ref(simulator_model, model_group)
        relations.append(
            evidence_relation(
                f"rel_{len(relations) + 1:02d}_{kind}",
                kind,
                target,
                confidence,
                role,
                [*timings, *metric_signals, simulator_signals[0]],
                allowed,
                blocked,
                [context_ref] if context_ref else None,
            )
        )
    return tuple(relations)


def validate_relation_facts(summary: Summary) -> None:
    """Rebuild links from normalized signals; simulator context refs load separately."""
    expected = build_evidence_relations(summary, summary.analysis_dimensions, None)
    recorded = summary.evidence_relations
    if len(recorded) != len(expected):
        raise ValueError("relation inventory disagrees with normalized observations")
    for actual, derived in zip(recorded, expected):
        for field in ("id", "kind", "target", "confidence", "role", "evidence",
                      "allowed_interpretation", "blocked_interpretation"):
            if getattr(actual, field) != getattr(derived, field):
                raise ValueError(f"relation {field} disagrees with normalized observations")
