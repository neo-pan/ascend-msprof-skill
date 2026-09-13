"""Headline and signal derivation for Evidence Model analysis."""
from __future__ import annotations

import re

from .ascend_profile_utils import normalized_key


from .summary_types import SummaryFacts
from .simulator_types import (SimulatorModel, SourceLine, InstructionRow, PipelineEvents,
                              FlowCategory, SyncEvents, MteThroughput)
from .analysis_types import AnalysisDimension, EvidenceSignal, RelationEvidence
from .metric_scope_policy import APP_TIMING_ARTIFACTS
from .application_timing import TimingEvidence, timing_signals, observation_field_ref
from .operator_evidence import OperatorEvidence, operator_signals, select_operator_primary


DIMENSION_GROUPS = [
    (
        "hot_path_dispatch",
        "Hot Path And Dispatch",
        ["op_summary", "op_statistic", "task_time", "api_statistic"],
    ),
    (
        "pipe_arithmetic_mix",
        "Pipe And Arithmetic Mix",
        ["pipe_utilization", "arithmetic_utilization"],
    ),
    (
        "memory_cache_movement",
        "Memory And Cache Movement",
        ["memory", "l2_cache"],
    ),
    (
        "resource_conflict",
        "Resource And UB Conflict",
        ["resource_conflict"],
    ),
    (
        "tiling_core_balance",
        "Tiling And Core Balance",
        ["op_basic_info", "task_time"],
    ),
]
TIMING_GROUPS = [*APP_TIMING_ARTIFACTS, "op_basic_info"]
OP_METRIC_GROUPS = ["pipe_utilization", "arithmetic_utilization", "memory", "l2_cache", "resource_conflict"]


def _trace_group_field(field: str) -> str:
    return re.sub(r'\[\d+\]', '[]', field, count=1)


def simulator_row_signal(group: str, index: int,
                         row: SourceLine | InstructionRow | PipelineEvents | FlowCategory | SyncEvents | MteThroughput) -> EvidenceSignal | None:
    kinds = {'source_lines': 'simulator_source_line', 'instructions': 'simulator_instruction',
             'pipeline_events': 'simulator_trace', 'flow_categories': 'simulator_flow',
             'sync_events': 'simulator_sync_event', 'mte_throughput': 'simulator_mte_throughput'}
    unit, statistic = None, 'count'
    if group in {'source_lines', 'instructions'}:
        metric = row.primary_metric
        if metric is None:
            return None
        label = row.code if group == 'source_lines' else row.instr
        field, value, reference = metric.field, metric.value, metric.field_ref
        unit, statistic = metric.unit, metric.statistic
    elif group == 'pipeline_events':
        label = row.max_event_name or str(row.tid)
        field, value = _trace_group_field(row.maximum_source.field), row.value
        reference = (f'{row.maximum_source.field}; statistic=maximum; unit=us' if row.duration_us is None else
                     f'{field}; pid={row.pid}; tid={row.tid}; events={row.event_count}; statistic=total; unit=us')
        unit, statistic = 'us', row.statistic
    elif group == 'flow_categories':
        label, field, value = row.category, _trace_group_field(row.first_source.field), row.count
        reference = f'{row.first_source.field}; category={row.category}; statistic=event_count'
    elif group == 'sync_events':
        label, field, value = row.instruction, _trace_group_field(row.first_source.field), row.trace_events
        reference = f'{row.first_source.field}; name={row.instruction}; phases=B/E; statistic=event_count'
    else:
        label, field, value = row.channel, 'throughput(MB/s)', row.maximum
        reference = row.maximum_source.field
        unit, statistic = 'MB/s', 'maximum'
    return EvidenceSignal(group='simulator', signal=label, artifact=row.artifact, field=field,
        field_ref=f'analysis/simulator_hotspots.json:{group}[{index}]; {reference}',
        value=value, kind=kinds[group], evidence_id=f'sim.{group}.{index + 1:04d}',
        segment='simulator', metric_scope=None, unit=unit, statistic=statistic)


def simulator_signals_from_model(model: SimulatorModel) -> tuple[EvidenceSignal, ...]:
    signals = []
    for group, limit in (('instructions', 1), ('source_lines', 1), ('pipeline_events', 1),
                         ('flow_categories', 1), ('sync_events', 2), ('mte_throughput', 2)):
        available = [signal for i, row in enumerate(getattr(model, group))
                     if (signal := simulator_row_signal(group, i, row)) is not None]
        signals.extend(available[:limit])
    if not signals:
        signals.extend(EvidenceSignal(group='simulator', signal=item.artifact, artifact=item.artifact,
            field='file', field_ref=f'analysis/simulator_hotspots.json:inputs[{i}].artifact', value=None,
            kind='simulator_artifact', segment='simulator', metric_scope=None)
            for i, item in enumerate(model.inputs))
    return tuple(signals)


def build_simulator_dimension(model: SimulatorModel) -> AnalysisDimension:
    signals = simulator_signals_from_model(model)
    return AnalysisDimension(id='source_pipeline_context', title='Source And Pipeline Context',
        status='available' if signals else 'insufficient', model_artifact='analysis/simulator_hotspots.json',
        signals=signals, evidence_refs=tuple(f'{s.artifact}; {s.field_ref}' for s in signals))


def build_profiler_dimensions(headlines: dict[str, TimingEvidence | OperatorEvidence]) -> tuple[AnalysisDimension, ...]:
    dimensions: list[AnalysisDimension] = []
    for dimension_id, title, groups in DIMENSION_GROUPS:
        signals = []
        for group in groups:
            item = headlines.get(group)
            if isinstance(item, TimingEvidence):
                signals.extend(timing_signals(item))
            elif isinstance(item, OperatorEvidence):
                signals.extend(operator_signals(item))
        dimensions.append(
            AnalysisDimension.model_validate({
                "id": dimension_id,
                "title": title,
                "status": "available" if signals else "insufficient",
                "signals": signals,
                "evidence_refs": [f"{signal.artifact}; {signal.field_ref}" for signal in signals],
            })
        )

    return tuple(dimensions)


def build_analysis_dimensions(summary: SummaryFacts, simulator_model: SimulatorModel) -> tuple[AnalysisDimension, ...]:
    return (*build_profiler_dimensions(summary.headlines), build_simulator_dimension(simulator_model))


def app_timing_relation_signals(summary: SummaryFacts) -> list[EvidenceSignal]:
    """Keep all statistics from the first timing group with a unique scope."""
    for group in APP_TIMING_ARTIFACTS:
        timing = summary.headlines.get(group)
        if isinstance(timing, TimingEvidence) and timing.unique_scope:
            return timing_signals(timing)
    return []


def operator_relation_signals(summary: SummaryFacts, groups: list[str]) -> list[EvidenceSignal]:
    """Link each scoped representative without inventing a unique group headline."""
    coverage = summary.profile_coverage
    out = []
    for group in groups:
        evidence = summary.headlines.get(group)
        if not isinstance(evidence, OperatorEvidence):
            continue
        selected = coverage.selected_segments_by_family.get(group) if coverage is not None else None
        if coverage is not None and coverage.explicit_target and (
                not coverage.segments["app"].count_complete or selected is None):
            continue
        artifacts = tuple(item for item in evidence.artifacts if selected is None or item.segment == selected)
        candidates = set(select_operator_primary(artifacts).candidates)
        references = {(item.source.artifact, observation_field_ref(group, item))
                      for artifact in artifacts for item in artifact.observations if item.source in candidates}
        out.extend(signal for signal in operator_signals(evidence, artifacts)
                   if (signal.artifact, signal.field_ref) in references)
    return out


def evidence_id(signal: EvidenceSignal, index: int) -> str:
    group = normalized_key(str(signal.group or "signal")) or "signal"
    field = normalized_key(str(signal.field or signal.kind or "value")) or "value"
    return f"ev_{index:02d}_{group}_{field}"


def relation_evidence(signals: list[EvidenceSignal]) -> tuple[RelationEvidence, ...]:
    out = []
    seen: set[tuple[str, str]] = set()
    for signal in signals:
        key = (str(signal.artifact), str(signal.field_ref))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            RelationEvidence.model_validate({
                "evidence_id": evidence_id(signal, len(out) + 1),
                "artifact": signal.artifact,
                "field": signal.field,
                "field_ref": signal.field_ref,
                "signal": signal.signal,
                "value": signal.value,
                "segment": signal.segment,
                "metric_scope": signal.metric_scope,
            })
        )
    return tuple(out)
