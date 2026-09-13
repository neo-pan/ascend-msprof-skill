#!/usr/bin/env python3
"""Render sourced Ascend simulator hotspots with explicit metric statistics."""
from __future__ import annotations

import argparse
from pathlib import Path

from .ascend_profile_utils import analysis_dir, write_json
from .simulator_hotspot_model import build_simulator_hotspot_model
from .simulator_types import SimulatorModel, SourceContext, SimulatorMetric


def metric_text(metric: SimulatorMetric) -> str:
    partial = f'; valid records {len(metric.records)}/{metric.record_count}' if metric.total is None else ''
    return f'{metric.value:g} {metric.unit} ({metric.statistic}{partial})'


def render_source_context(context: SourceContext) -> list[str]:
    if context.status != 'available':
        return [f'  - source_context: {context.status}']
    out = [f'  - source_context: {context.artifact}:{context.line}']
    if context.tags:
        out.append(f'  - source_context_tags: {", ".join(context.tags)}')
    out.append('  - source_snippet:')
    for item in context.snippet:
        out.append(f'    {">" if item.hotspot else " "} {item.line}: {item.text}')
    return out


def render_markdown(model: SimulatorModel, top: int) -> str:
    lines = ['# Simulator Hotspots', '', '## Source Lines']
    if not model.source_lines:
        lines.append('No source-line rows with confirmed simulator fields found.')
    for row in model.source_lines[:top]:
        lines.append(f'- {row.code} (source: `{row.artifact}`; record {row.identity_source.record})')
        for metric in row.metrics:
            lines.append(f'  - {metric.field}: {metric_text(metric)}; {metric.field_ref}')
        lines.extend(render_source_context(row.source_context))
    lines.extend(['', '## Instructions'])
    if not model.instructions:
        lines.append('No instruction rows with confirmed simulator fields found.')
    for row in model.instructions[:top]:
        lines.append(f'- {row.instr}; pipe={row.pipe}; addr={row.addr} (source: `{row.artifact}`; record {row.identity_source.record})')
        for metric in row.metrics:
            lines.append(f'  - {metric.field}: {metric_text(metric)}; {metric.field_ref}')
    lines.extend(['', '## Trace Pipeline Context',
                  'Trace durations are in microseconds. displayTimeUnit controls viewer presentation.'])
    for item in model.inputs:
        if item.kind == 'trace_json' and item.display_time_unit:
            lines.append(f'- displayTimeUnit: {item.display_time_unit} (source: `{item.artifact}`)')
    if model.pipeline_events:
        lines.extend(['| Duration (us) | Statistic | Valid events | Pipe | Source |', '|---:|---|---:|---|---|'])
        for row in model.pipeline_events[:top]:
            lines.append(f'| {row.value:g} | {row.statistic} | {row.event_count}/{row.record_count} | pid={row.pid}; tid={row.tid} | `{row.artifact}`; `{row.maximum_source.field}` (maximum) |')
    else:
        lines.append('No trace events with confirmed duration fields found.')
    lines.extend(['', '## Trace Flow Categories'])
    if not model.flow_categories:
        lines.append('No trace flow category events found.')
    for row in model.flow_categories[:top]:
        lines.append(f'- {row.category}: {row.count} events (source: `{row.artifact}`; `{row.first_source.field}`)')
    lines.extend(['', '## Synchronization Event Context',
                  'Trace counts are B/E records. Instruction CSV call counts are listed separately above.'])
    if not model.sync_events:
        lines.append('No SET_FLAG/WAIT_FLAG B/E synchronization events found in selected simulator traces.')
    for row in model.sync_events:
        lines.append(f'- {row.instruction}: {row.trace_events} trace events (source: `{row.artifact}`; `{row.first_source.field}`)')
    lines.extend(['', '## MTE Throughput Context'])
    if not model.mte_throughput:
        lines.append('No MTE Throughput counter events with numeric throughput(MB/s) values found in selected trace.json files.')
    else:
        lines.extend(['| Channel | Max throughput(MB/s) | Avg throughput(MB/s) | Samples | Source |', '|---|---:|---:|---:|---|'])
        for row in model.mte_throughput[:top]:
            lines.append(f'| {row.channel} | {row.maximum:g} | {row.average:g} | {row.samples} | `{row.artifact}`; `{row.maximum_source.field}` |')
    if model.warnings:
        lines.extend(['', '## Parsing Notes', *[f'- {warning}' for warning in model.warnings]])
    return '\n'.join(lines) + '\n'


def write_simulator_markdown(run_dir: Path, model: SimulatorModel, top: int = 20) -> Path:
    output = analysis_dir(run_dir) / 'simulator_hotspots.txt'
    output.write_text(render_markdown(model, top), encoding='utf-8')
    return output


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--top', type=int, default=20)
    args = parser.parse_args(argv)
    run_dir = args.run_dir.resolve()
    model = build_simulator_hotspot_model(run_dir)
    output = analysis_dir(run_dir) / 'simulator_hotspots.json'
    write_json(output, model.model_dump(mode='json'))
    text = write_simulator_markdown(run_dir, model, args.top)
    print(f'wrote {output}')
    print(f'wrote {text}')


if __name__ == '__main__':
    main()
