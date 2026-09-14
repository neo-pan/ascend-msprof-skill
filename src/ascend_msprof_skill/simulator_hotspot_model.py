"""Normalize Ascend simulator inputs once into sourced, finite facts."""
from __future__ import annotations

import math
import json
from collections import defaultdict
from pathlib import Path

from .collection_receipts import CollectionReceipts, load_collection_receipts
from .artifact_reader import read_csv, read_json
from .ascend_profile_utils import find_files, rel, to_float
from .evidence_types import ParseIssue, SourceRef, csv_status
from .simulator_types import (SimulatorInput, SimulatorMetric, SimulatorModel, SourceLine,
                              InstructionRow, SourceContext, PipelineEvents, FlowCategory,
                              SyncEvents, MteThroughput, select_trace_artifacts, SourceSnippetLine, classify_source_context,
                              simulator_integer, source_location)

SIMULATOR_HOTSPOT_MODEL_SCHEMA_VERSION = "2.0"
SIMULATOR_PATTERNS = ["core*_code_exe.csv", "core*_instr_exe.csv", "trace.json"]
METRIC_FIELDS = ("call_count", "cycles", "running_time(us)")
SOURCE_CONTEXT_LINES = 3
SOURCE_CONTEXT_MAX_LINE_CHARS = 240

SYNC_EVENT_INSTRUCTIONS = ["SET_FLAG", "WAIT_FLAG"]
SYNC_EVENT_PHASES = ("B", "E")
MTE_THROUGHPUT_CHANNELS = [
    "GM_TO_L1",
    "GM_TO_TOTAL",
    "GM_TO_UB",
    "L1_TO_GM",
    "TOTAL_TO_GM",
    "UB_TO_GM",
]
MTE_THROUGHPUT_FIELD = "throughput(MB/s)"
def build_source_context(run_dir: Path, source_file: str | None, line: int | None,
                         source_texts: dict[Path, list[str] | OSError]) -> SourceContext:
    if source_file is None:
        return SourceContext(status='missing', reason='no_source_file')
    artifact = None
    try:
        path = Path(source_file)
        try:
            resolved = (path if path.is_absolute() else run_dir / path).resolve(strict=False)
        except RuntimeError as exc:  # pathlib reports symlink loops this way before Python 3.13.
            return SourceContext(status='unreadable', source_file=source_file, line=line, reason=str(exc))
        try:
            artifact = resolved.relative_to(run_dir).as_posix()
        except ValueError:
            return SourceContext(status='outside_run_dir', source_file=source_file, line=line)
        if not resolved.exists():
            return SourceContext(status='missing', artifact=artifact, line=line)
        if not resolved.is_file():
            return SourceContext(status='unreadable', artifact=artifact, source_file=source_file,
                                 line=line, reason='not_a_file')
        if resolved not in source_texts:
            try:
                source_texts[resolved] = resolved.read_text(encoding='utf-8', errors='replace').splitlines()
            except OSError as exc:
                source_texts[resolved] = exc
    except (OSError, ValueError) as exc:
        return SourceContext(status='unreadable', artifact=artifact, source_file=source_file,
                             line=line, reason=str(exc))
    lines = source_texts[resolved]
    if isinstance(lines, OSError):
        return SourceContext(status='unreadable', artifact=artifact, source_file=source_file,
                             line=line, reason=str(lines))
    if line is None or line < 1 or line > len(lines):
        return SourceContext(status='invalid_line', artifact=artifact, line=line, line_count=len(lines))
    start, end = max(1, line - SOURCE_CONTEXT_LINES), min(len(lines), line + SOURCE_CONTEXT_LINES)
    snippet = tuple(SourceSnippetLine(line=i, hotspot=i == line,
        text=lines[i - 1] if len(lines[i - 1]) <= SOURCE_CONTEXT_MAX_LINE_CHARS else lines[i - 1][:SOURCE_CONTEXT_MAX_LINE_CHARS - 3] + '...')
        for i in range(start, end + 1))
    tags, basis = classify_source_context(snippet)
    return SourceContext(status='available', artifact=artifact, line=line, snippet=snippet, tags=tags, tag_basis=basis)


def metric_number(token: str, field: str) -> int | float | None:
    if field in {"call_count", "cycles"}:
        return simulator_integer(token)
    return to_float(token)


def complete_sum(values: list[int | float], count: int) -> int | float | None:
    if len(values) != count:
        return None
    try:
        total = sum(values) if all(type(v) is int for v in values) else math.fsum(values)
    except OverflowError:
        return None
    return total if type(total) is int or math.isfinite(total) else None


def normalize_simulator_csv(path: Path, run_dir: Path, source_texts: dict[Path, list[str] | OSError]) -> tuple[SimulatorInput, tuple[SourceLine | InstructionRow, ...]]:
    artifact = rel(path, run_dir)
    is_code = path.name.endswith('_code_exe.csv')
    identity_field = 'code' if is_code else 'instr'
    issues = []
    grouped = {}

    def consume(columns, cells, ordinal):
        if columns.count(identity_field) != 1:
            return
        identity_column = columns.index(identity_field)
        identity = cells[identity_column]
        if not identity:
            issues.append(ParseIssue(code='missing_identity', source=SourceRef(artifact=artifact,
                field=identity_field, record=ordinal, column=identity_column + 1),
                reason=f'empty simulator {identity_field}', impact='scope'))
            return
        def metadata(field):
            return cells[columns.index(field)] if columns.count(field) == 1 else None
        key = (identity, None if is_code else metadata('addr'), None if is_code else metadata('pipe'))
        if key not in grouped:
            grouped[key] = {'count': 0, 'source': SourceRef(artifact=artifact,
                field=identity_field, record=ordinal, column=identity_column + 1), 'metrics': defaultdict(list)}
        entry = grouped[key]
        entry['count'] += 1
        for field in METRIC_FIELDS:
            if columns.count(field) != 1:
                continue
            index = columns.index(field)
            token = cells[index]
            number = metric_number(token, field)
            if number is None:
                source = SourceRef(artifact=artifact, field=field, record=ordinal, column=index + 1)
                issues.append(ParseIssue(code='missing_value' if not token.strip() else 'invalid_number', source=source,
                    reason=f'{field} is missing or has an invalid numeric token: {token!r}', impact='metric'))
            else:
                entry['metrics'][field].append((number, ordinal, index + 1, token))

    decoded = read_csv(path, artifact, consume)
    issues[:0] = decoded.issues
    if decoded.columns.count(identity_field) != 1:
        issues.append(ParseIssue(code='unsupported_identity', source=SourceRef(artifact=artifact, field=identity_field),
            reason=f'simulator CSV requires one exact {identity_field} column', impact='scope'))
    if not any(field in decoded.columns for field in METRIC_FIELDS):
        issues.append(ParseIssue(code='unsupported_fields', source=SourceRef(artifact=artifact),
            reason='no confirmed simulator count, cycle, or running_time(us) field', impact='metric'))
    rows = []
    for (identity, addr, pipe), entry in grouped.items():
        metrics = []
        for field, observations in entry['metrics'].items():
            maximum, record_number, column, token = max(observations, key=lambda row: row[0])
            source = SourceRef(artifact=artifact, field=field, record=record_number, column=column)
            total = complete_sum([row[0] for row in observations], entry['count'])
            if total is None and len(observations) == entry['count']:
                issues.append(ParseIssue(code='aggregate_overflow', source=source,
                    reason=f'{field} total overflows; maximum remains available', impact='metric'))
            metrics.append(SimulatorMetric(field=field, total=total, maximum=maximum, maximum_source=source,
                maximum_raw_token=token, records=tuple(row[1] for row in observations), record_count=entry['count']))
        common = dict(artifact=artifact, identity_source=entry['source'], record_count=entry['count'], metrics=tuple(metrics))
        if is_code:
            file, number = source_location(identity)
            raw_file, separator, raw_line = identity.rpartition(':')
            if number is None and separator and raw_file and raw_line.isascii() and raw_line.isdecimal():
                issues.append(ParseIssue(code='invalid_source_line', source=entry['source'],
                    reason='simulator source line is not a representable positive integer', impact='scope'))
            rows.append(SourceLine(**common, code=identity, source_file=file, line=number,
                source_context=build_source_context(run_dir, file, number, source_texts)))
        else:
            rows.append(InstructionRow(**common, instr=identity, addr=addr, pipe=pipe))
    record = SimulatorInput(artifact=artifact, kind='code_execution_csv' if is_code else 'instruction_execution_csv',
        parser_status=csv_status(decoded.row_count, tuple(issues)), row_count=decoded.row_count,
        columns=decoded.columns, sample_rows=decoded.sample_rows, issues=tuple(issues))
    return record, tuple(rows)


def normalize_simulator_trace(path: Path, run_dir: Path) -> tuple[
    SimulatorInput, tuple[PipelineEvents, ...], tuple[FlowCategory, ...],
    tuple[SyncEvents, ...], tuple[MteThroughput, ...],
]:
    artifact = rel(path, run_dir)
    issues = []
    events = []
    display = None
    event_path = None
    try:
        raw = read_json(path)
        if isinstance(raw, list):
            events, event_path = raw, ''
        elif isinstance(raw, dict) and isinstance(raw.get('traceEvents'), list):
            events, event_path = raw['traceEvents'], 'traceEvents'
            display = raw.get('displayTimeUnit') if isinstance(raw.get('displayTimeUnit'), str) else None
        else:
            issues.append(ParseIssue(code='trace_structure', source=SourceRef(artifact=artifact),
                reason='simulator trace requires an event array or traceEvents array', impact='structure'))
    except (OSError, ValueError) as exc:
        issues.append(ParseIssue(code='json_decode', source=SourceRef(artifact=artifact), reason=str(exc), impact='decode'))
    pipelines, flows, syncs, throughput = {}, {}, {}, {}
    def source(index, field):
        return SourceRef(artifact=artifact, field=f'{event_path}[{index}].{field}')
    def numeric(value, index, field):
        number = to_float(value) if type(value) in (int, float) else None
        if number is None:
            issues.append(ParseIssue(code='invalid_number', source=source(index, field),
                reason=f'invalid simulator trace number in {field}', impact='metric'))
        return number
    for i, event in enumerate(events):
        if not isinstance(event, dict):
            issues.append(ParseIssue(code='invalid_event', source=source(i, ''), reason='trace event is not an object', impact='structure'))
            continue
        name, phase = event.get('name'), event.get('ph')
        if phase == 'X':
            tid, pid = event.get('tid'), event.get('pid')
            invalid_ids = [field for field, value in (('tid', tid), ('pid', pid))
                           if type(value) not in (str, int) and not (field == 'pid' and value is None)]
            if invalid_ids:
                issues.extend(ParseIssue(code='invalid_identity', source=source(i, field),
                    reason=f'duration event requires a scalar {field}', impact='scope') for field in invalid_ids)
                continue
            entry = pipelines.setdefault((pid, tid), {'count': 0, 'values': [], 'maximum': None})
            entry['count'] += 1
            duration = numeric(event.get('dur'), i, 'dur')
            if duration is not None:
                entry['values'].append(duration)
                if entry['maximum'] is None or duration > entry['maximum'][0]:
                    entry['maximum'] = (duration, i, name if isinstance(name, str) else None)
        if name == 'flow' and isinstance(event.get('cat'), str) and event['cat']:
            if event['cat'] not in flows:
                flows[event['cat']] = [0, source(i, 'cat')]
            flows[event['cat']][0] += 1
        if name in SYNC_EVENT_INSTRUCTIONS and phase in SYNC_EVENT_PHASES:
            if name not in syncs:
                syncs[name] = [0, source(i, 'name')]
            syncs[name][0] += 1
        if event.get('pid') == 'MTE Throughput' and phase == 'C' and name in MTE_THROUGHPUT_CHANNELS:
            args = event.get('args')
            value = numeric(args.get(MTE_THROUGHPUT_FIELD) if isinstance(args, dict) else None, i, 'args.' + MTE_THROUGHPUT_FIELD)
            if value is not None:
                entry = throughput.setdefault(name, {'values': [], 'maximum': None})
                entry['values'].append(value)
                if entry['maximum'] is None or value > entry['maximum'][0]:
                    entry['maximum'] = (value, i)
    pipeline_rows = []
    for (pid, tid), entry in pipelines.items():
        values = entry['values']
        if not values:
            continue
        maximum, index, name = entry['maximum']
        ref = source(index, 'dur')
        total = complete_sum(values, entry['count'])
        if total is None and len(values) == entry['count']:
            issues.append(ParseIssue(code='aggregate_overflow', source=ref,
                reason='trace duration total overflows; maximum remains available', impact='metric'))
        pipeline_rows.append(PipelineEvents(artifact=artifact, pid=pid, tid=tid, duration_us=total,
            max_duration_us=maximum, maximum_source=ref, max_event_name=name, event_count=len(values), record_count=entry['count']))
    mte_rows = []
    for channel, entry in throughput.items():
        values = entry['values']
        maximum, index = entry['maximum']
        ref = source(index, 'args.' + MTE_THROUGHPUT_FIELD)
        average = math.fsum(v / len(values) for v in values)
        mte_rows.append(MteThroughput(artifact=artifact, channel=channel, maximum=maximum, average=average,
            samples=len(values), maximum_source=ref))
    samples = []
    for index, event in enumerate(events[:5]):
        try:
            json.dumps(event, allow_nan=False)
        except ValueError:
            issues.append(ParseIssue(code='nonfinite_raw_sample', source=SourceRef(artifact=artifact, field=f'{event_path}[{index}]'),
                reason='nonfinite raw event remains in the original trace; omitted from JSON samples', impact='metric'))
        else:
            samples.append(event)
    record = SimulatorInput(artifact=artifact, kind='trace_json', parser_status=csv_status(len(events), tuple(issues)),
        row_count=len(events), columns=(), sample_rows=tuple(samples), issues=tuple(issues),
        display_time_unit=display, event_path=event_path)
    return (record, tuple(pipeline_rows),
            tuple(FlowCategory(artifact=artifact, category=cat, count=value[0], first_source=value[1]) for cat, value in flows.items()),
            tuple(SyncEvents(artifact=artifact, instruction=name, trace_events=value[0], first_source=value[1]) for name, value in syncs.items()),
            tuple(mte_rows))


def hotspot_order(row: SourceLine | InstructionRow) -> tuple:
    metric = row.primary_metric
    return (METRIC_FIELDS.index(metric.field) if metric else -1, metric.value if metric else 0,
            row.artifact, row.identity_source.record)


def collect_simulator_model(run_dir: Path, receipts: CollectionReceipts) -> tuple[SimulatorModel, tuple[SimulatorInput, ...]]:
    run_dir = run_dir.resolve()
    admitted = receipts.allows('simulator')
    inputs, source_lines, instructions, traces = [], [], [], []
    source_texts: dict[Path, list[str] | OSError] = {}
    for path in find_files(run_dir, SIMULATOR_PATTERNS):
        if path.suffix == '.csv':
            record, rows = normalize_simulator_csv(path, run_dir, source_texts)
            inputs.append(record)
            (source_lines if record.kind == 'code_execution_csv' else instructions).extend(rows)
        else:
            rows = normalize_simulator_trace(path, run_dir)
            inputs.append(rows[0]); traces.append(rows)
    all_inputs = tuple(inputs)
    inputs = all_inputs if admitted else ()
    selected = select_trace_artifacts(inputs)
    selected_rows = [row for row in traces if row[0].artifact in selected]
    warnings = [warning for item in inputs for warning in item.warnings]
    if not admitted:
        warnings.append('Simulator result receipt is not succeeded; raw artifacts are excluded from derived evidence.')
    else:
        for kind, pattern in (('code_execution_csv', 'core*_code_exe.csv'), ('instruction_execution_csv', 'core*_instr_exe.csv'), ('trace_json', 'trace.json')):
            if not any(item.kind == kind for item in inputs):warnings.append(f'No {pattern} files found.')
    model = SimulatorModel(simulator_hotspot_model_schema_version=SIMULATOR_HOTSPOT_MODEL_SCHEMA_VERSION,
        inputs=inputs, selected_trace_artifacts=selected,
        source_lines=tuple(sorted(source_lines, key=hotspot_order, reverse=True)) if admitted else (),
        instructions=tuple(sorted(instructions, key=hotspot_order, reverse=True)) if admitted else (),
        pipeline_events=tuple(sorted((item for row in selected_rows for item in row[1]), key=lambda x: x.value, reverse=True)),
        flow_categories=tuple(sorted((item for row in selected_rows for item in row[2]), key=lambda x: x.count, reverse=True)),
        sync_events=tuple(item for row in selected_rows for item in row[3]),
        mte_throughput=tuple(sorted((item for row in selected_rows for item in row[4]), key=lambda x: x.maximum, reverse=True)),
        warnings=tuple(warnings))
    return model, all_inputs


def build_simulator_hotspot_model(run_dir: Path) -> SimulatorModel:
    return collect_simulator_model(run_dir, load_collection_receipts(run_dir))[0]
