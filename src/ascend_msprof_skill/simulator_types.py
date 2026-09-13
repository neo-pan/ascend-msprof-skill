"""Normalized Ascend simulator facts; raw trace events are not persisted here."""
from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, JsonValue, model_validator

from .evidence_types import ArtifactPath, EvidenceFact, ParseIssue, SourceRef
from .ascend_profile_utils import to_float


def simulator_integer(token: str) -> int | None:
    token = token.strip()
    if token.isascii() and token.isdecimal():
        try:
            return int(token)
        except ValueError:
            pass
    return None


def source_location(code: str) -> tuple[str | None, int | None]:
    file, separator, line = code.rpartition(':')
    number = simulator_integer(line) if separator and file and line.isascii() and line.isdecimal() else None
    return (file, number) if number is not None and number > 0 else (None, None)


class SourceSnippetLine(EvidenceFact):
    line: int = Field(ge=1)
    hotspot: bool
    text: str


class SourceContext(EvidenceFact):
    status: Literal['available', 'missing', 'outside_run_dir', 'invalid_line', 'unreadable']
    artifact: ArtifactPath | None = None
    source_file: str | None = None
    line: int | None = None
    line_count: int | None = Field(default=None, ge=0)
    reason: str | None = None
    snippet: Annotated[tuple[SourceSnippetLine, ...], Field(strict=False)] = ()
    tags: Annotated[tuple[str, ...], Field(strict=False)] = ()
    tag_basis: dict[str, Annotated[tuple[str, ...], Field(strict=False)]] = Field(default_factory=dict)

    @model_validator(mode='after')
    def sourced_snippet(self) -> SourceContext:
        if self.status == 'available':
            if not self.artifact or self.line is None or not self.snippet:
                raise ValueError('available source context requires a located snippet')
            if [item.line for item in self.snippet if item.hotspot] != [self.line]:
                raise ValueError('source hotspot marker disagrees with the recorded line')
            numbers = [item.line for item in self.snippet]
            if numbers != list(range(numbers[0], numbers[-1] + 1)):
                raise ValueError('source snippet lines must be consecutive')
            if (self.tags, self.tag_basis) != classify_source_context(self.snippet):
                raise ValueError('source tags disagree with recorded snippet tokens')
        elif self.snippet or self.tags or self.tag_basis:
            raise ValueError('unavailable source context cannot contain a snippet')
        return self


class SimulatorInput(EvidenceFact):
    artifact: ArtifactPath
    kind: Literal['code_execution_csv', 'instruction_execution_csv', 'trace_json']
    parser_status: Literal['parsed', 'empty', 'invalid']
    row_count: int = Field(ge=0)
    columns: Annotated[tuple[str, ...], Field(strict=False)]
    sample_rows: Annotated[tuple[JsonValue, ...], Field(strict=False)]
    issues: Annotated[tuple[ParseIssue, ...], Field(strict=False)]
    display_time_unit: str | None = None
    event_path: Literal['traceEvents', ''] | None = None

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(f'invalid simulator {"trace" if self.kind == "trace_json" else "csv"} {self.artifact}: {issue.reason}'
                     for issue in self.issues)

    @model_validator(mode='after')
    def input_inventory(self) -> SimulatorInput:
        if self.parser_status != ('invalid' if any(i.impact in {'decode', 'structure'} for i in self.issues)
                                  else 'parsed' if self.row_count else 'empty'):
            raise ValueError('simulator parser status disagrees with input issues/count')
        if len(self.sample_rows) > min(5, self.row_count):
            raise ValueError('simulator samples exceed the bounded input inventory')
        if any(i.source.artifact != self.artifact for i in self.issues):
            raise ValueError('simulator issues must identify their input artifact')
        if self.kind != 'trace_json' and (self.event_path is not None or self.display_time_unit is not None):
            raise ValueError('CSV input cannot declare trace metadata')
        return self


class SimulatorMetric(EvidenceFact):
    field: Literal['call_count', 'cycles', 'running_time(us)']
    total: int | FiniteFloat | None
    maximum: int | FiniteFloat
    maximum_source: SourceRef
    maximum_raw_token: str
    records: Annotated[tuple[Annotated[int, Field(ge=2)], ...], Field(strict=False, min_length=1)]
    record_count: int = Field(ge=1)

    @property
    def unit(self) -> str:
        return {'call_count': 'count', 'cycles': 'cycles', 'running_time(us)': 'us'}[self.field]

    @property
    def value(self) -> int | float:
        return self.total if self.total is not None else self.maximum

    @property
    def statistic(self) -> str:
        return 'total' if self.total is not None else 'maximum'

    @property
    def field_ref(self) -> str:
        positions = ','.join(map(str, self.records)) if self.total is not None else str(self.maximum_source.record)
        return f'field={self.field}; column={self.maximum_source.column}; records={positions}; statistic={self.statistic}; unit={self.unit}'

    @model_validator(mode='after')
    def consistent_metric(self) -> SimulatorMetric:
        if (len(self.records) > self.record_count or list(self.records) != sorted(set(self.records))
                or self.maximum_source.record not in self.records
                or self.maximum_source.field != self.field or self.maximum_source.column is None):
            raise ValueError('simulator metric source/counts disagree')
        if len(self.records) < self.record_count and self.total is not None:
            raise ValueError('partial simulator metrics cannot claim a complete total')
        if self.field in {'call_count', 'cycles'}:
            token = self.maximum_raw_token.strip()
            if simulator_integer(token) != self.maximum:
                raise ValueError('simulator counts require integer raw tokens')
            if any(type(v) is not int or v < 0 for v in (self.maximum, self.total) if v is not None):
                raise ValueError('simulator counts must be nonnegative integers')
            if self.total is not None and self.total < self.maximum:
                raise ValueError('count total cannot be less than its maximum')
        elif to_float(self.maximum_raw_token) != self.maximum:
            raise ValueError('simulator maximum disagrees with its raw token')
        if self.record_count == 1 and self.total != self.maximum:
            raise ValueError('single-record simulator total must equal its maximum')
        return self


class SimulatorHotspot(EvidenceFact):
    artifact: ArtifactPath
    identity_source: SourceRef
    record_count: int = Field(ge=1)
    metrics: Annotated[tuple[SimulatorMetric, ...], Field(strict=False)]

    @property
    def primary_metric(self) -> SimulatorMetric | None:
        return next((m for f in ('running_time(us)', 'cycles', 'call_count') for m in self.metrics if m.field == f), None)

    @model_validator(mode='after')
    def located_metrics(self) -> SimulatorHotspot:
        if self.identity_source.artifact != self.artifact:
            raise ValueError('simulator identity source disagrees with artifact')
        if len({m.field for m in self.metrics}) != len(self.metrics):
            raise ValueError('duplicate simulator metric field')
        if any(m.record_count != self.record_count or m.maximum_source.artifact != self.artifact for m in self.metrics):
            raise ValueError('simulator metric aggregate disagrees with hotspot scope')
        return self


class SourceLine(SimulatorHotspot):
    code: str
    source_file: str | None
    line: int | None = Field(ge=1)
    source_context: SourceContext

    @model_validator(mode='after')
    def code_location(self) -> SourceLine:
        if (self.source_file, self.line) != source_location(self.code):
            raise ValueError('source location disagrees with recorded code field')
        if self.source_context.line is not None and self.source_context.line != self.line:
            raise ValueError('source context line disagrees with recorded code field')
        if self.source_context.source_file is not None and self.source_context.source_file != self.source_file:
            raise ValueError('source context file disagrees with recorded code field')
        return self


class InstructionRow(SimulatorHotspot):
    instr: str
    addr: str | None
    pipe: str | None


class PipelineEvents(EvidenceFact):
    artifact: ArtifactPath
    pid: str | int | None
    tid: str | int
    duration_us: FiniteFloat | None
    event_count: int = Field(ge=1)
    record_count: int = Field(ge=1)
    max_duration_us: FiniteFloat
    max_event_name: str | None
    maximum_source: SourceRef

    @property
    def value(self) -> float:
        return self.duration_us if self.duration_us is not None else self.max_duration_us

    @property
    def statistic(self) -> str:
        return 'total' if self.duration_us is not None else 'maximum'

    @model_validator(mode='after')
    def duration_scope(self) -> PipelineEvents:
        if self.event_count > self.record_count or self.maximum_source.artifact != self.artifact:
            raise ValueError('pipeline event source/counts disagree')
        if self.event_count < self.record_count and self.duration_us is not None:
            raise ValueError('partial pipeline events cannot claim a complete duration')
        if self.record_count == 1 and self.duration_us != self.max_duration_us:
            raise ValueError('single-event duration must equal its maximum')
        return self


class FlowCategory(EvidenceFact):
    artifact: ArtifactPath
    category: str
    count: int = Field(ge=1)
    first_source: SourceRef


class SyncEvents(EvidenceFact):
    artifact: ArtifactPath
    instruction: Literal['SET_FLAG', 'WAIT_FLAG']
    # Counts raw B/E records, never paired spans or instruction calls.
    trace_events: int = Field(ge=1)
    first_source: SourceRef


class MteThroughput(EvidenceFact):
    artifact: ArtifactPath
    channel: Literal['GM_TO_L1', 'GM_TO_TOTAL', 'GM_TO_UB', 'L1_TO_GM', 'TOTAL_TO_GM', 'UB_TO_GM']
    maximum: FiniteFloat
    average: FiniteFloat
    samples: int = Field(ge=1)
    maximum_source: SourceRef


class SimulatorModel(EvidenceFact):
    simulator_hotspot_model_schema_version: Literal['2.0']
    inputs: Annotated[tuple[SimulatorInput, ...], Field(strict=False)]
    selected_trace_artifacts: Annotated[tuple[ArtifactPath, ...], Field(strict=False)]
    source_lines: Annotated[tuple[SourceLine, ...], Field(strict=False)]
    instructions: Annotated[tuple[InstructionRow, ...], Field(strict=False)]
    pipeline_events: Annotated[tuple[PipelineEvents, ...], Field(strict=False)]
    flow_categories: Annotated[tuple[FlowCategory, ...], Field(strict=False)]
    sync_events: Annotated[tuple[SyncEvents, ...], Field(strict=False)]
    mte_throughput: Annotated[tuple[MteThroughput, ...], Field(strict=False)]
    warnings: Annotated[tuple[str, ...], Field(strict=False)]

    @model_validator(mode='after')
    def admitted_sources(self) -> SimulatorModel:
        inputs = {item.artifact: item for item in self.inputs}
        if len(inputs) != len(self.inputs):
            raise ValueError('duplicate simulator input artifact')
        if tuple(self.selected_trace_artifacts) != select_trace_artifacts(self.inputs):
            raise ValueError('selected simulator traces disagree with input scope')
        for group, kind in ((self.source_lines, 'code_execution_csv'), (self.instructions, 'instruction_execution_csv')):
            keys = [(row.artifact, row.code) if isinstance(row, SourceLine)
                    else (row.artifact, row.instr, row.addr, row.pipe) for row in group]
            if len(keys) != len(set(keys)):
                raise ValueError('duplicate simulator hotspot identity')
            for row in group:
                item = inputs.get(row.artifact)
                if item is None or item.kind != kind or row.record_count > item.row_count:
                    raise ValueError('simulator hotspot disagrees with its input inventory')
                field = 'code' if kind == 'code_execution_csv' else 'instr'
                if (item.columns.count(field) != 1 or row.identity_source.field != field
                        or row.identity_source.column != item.columns.index(field) + 1
                        or row.identity_source.record is None or row.identity_source.record < 2):
                    raise ValueError('simulator identity source disagrees with input columns or records')
                for metric in row.metrics:
                    if (item.columns.count(metric.field) != 1
                            or metric.maximum_source.column != item.columns.index(metric.field) + 1):
                        raise ValueError('simulator metric source disagrees with input columns')
                    if (metric.total is None and len(metric.records) == metric.record_count
                            and not any(issue.code == 'aggregate_overflow' and issue.source == metric.maximum_source
                                        for issue in item.issues)):
                        raise ValueError('unavailable complete metric total requires a located overflow issue')
            for artifact in {row.artifact for row in group}:
                if sum(row.record_count for row in group if row.artifact == artifact) > inputs[artifact].row_count:
                    raise ValueError('simulator grouped records exceed input inventory')
        for group in (self.pipeline_events, self.flow_categories, self.sync_events, self.mte_throughput):
            if any(row.artifact not in self.selected_trace_artifacts for row in group):
                raise ValueError('simulator aggregate references an unselected trace')
            for artifact in {row.artifact for row in group}:
                count = sum(row.record_count if isinstance(row, PipelineEvents) else
                            row.samples if isinstance(row, MteThroughput) else
                            row.trace_events if isinstance(row, SyncEvents) else row.count
                            for row in group if row.artifact == artifact)
                if count > inputs[artifact].row_count:
                    raise ValueError('simulator trace aggregate counts exceed input inventory')
            for row in group:
                source = row.maximum_source if isinstance(row, (PipelineEvents, MteThroughput)) else row.first_source
                item = inputs[row.artifact]
                prefix = f'{item.event_path}['
                field = source.field or ''
                index, sep, tail = field.removeprefix(prefix).partition('].')
                if (source.artifact != row.artifact or not field.startswith(prefix) or not sep
                        or not index.isdecimal() or int(index) >= item.row_count):
                    raise ValueError('simulator trace source disagrees with event inventory')
                expected = ('dur' if isinstance(row, PipelineEvents) else 'args.throughput(MB/s)' if isinstance(row, MteThroughput)
                            else 'name' if isinstance(row, SyncEvents) else 'cat')
                if tail != expected:
                    raise ValueError('simulator trace source disagrees with metric field')
                if (isinstance(row, PipelineEvents) and row.duration_us is None and row.event_count == row.record_count
                        and not any(issue.code == 'aggregate_overflow' and issue.source == row.maximum_source for issue in item.issues)):
                    raise ValueError('unavailable complete trace duration requires a located overflow issue')
        return self


def select_trace_artifacts(inputs: tuple[SimulatorInput, ...]) -> tuple[str, ...]:
    from pathlib import PurePosixPath
    traces = [item.artifact for item in inputs if item.kind == 'trace_json' and item.row_count]
    # Select aggregate vs per-core within each simulator collection, not across runs/collections.
    roots: dict[str, list[str]] = {}
    for artifact in traces:
        parts = PurePosixPath(artifact).parts
        root = '/'.join(parts[:parts.index('simulator') + 1]) if 'simulator' in parts else str(PurePosixPath(artifact).parent)
        roots.setdefault(root, []).append(artifact)
    return tuple(path for root, paths in roots.items()
                 for path in ([p for p in paths if str(PurePosixPath(p).parent) == root] or paths))


SOURCE_CONTEXT_TAG_RULES = [
    ("memory_movement", ["DataCopy", "Copy", "GlobalTensor", "LocalTensor", "GM", "UB", "L1"]),
    ("pipeline_buffer", ["TPipe", "TQue", "AllocTensor", "FreeTensor", "EnQue", "DeQue", "InitBuffer"]),
    ("scalar_control", ["if (", "if(", "for (", "for(", "GetBlockIdx", "blockIdx", "BlockIdx"]),
    (
        "vector_compute",
        [
            "AscendC::Add",
            "AscendC::Adds",
            "AscendC::Mul",
            "AscendC::Muls",
            "AscendC::Sub",
            "AscendC::Exp",
            "AscendC::Abs",
            "AscendC::Reduce",
        ],
    ),
    ("sync_context", ["SetFlag", "WaitFlag", "Sync", "SyncAll", "Barrier", "PipeBarrier", "BAR"]),
]


def source_context_token_matches(text: str, token: str) -> bool:
    if any(ch.isspace() for ch in token) or "(" in token:
        return token.lower() in text.lower()
    pattern = rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def classify_source_context(snippet: tuple[SourceSnippetLine, ...]) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    text = "\n".join(item.text for item in snippet)
    tags: list[str] = []
    basis: dict[str, tuple[str, ...]] = {}
    for tag, tokens in SOURCE_CONTEXT_TAG_RULES:
        hits = []
        for token in tokens:
            if source_context_token_matches(text, token):
                hits.append(token)
        if hits:
            tags.append(tag)
            basis[tag] = tuple(sorted(set(hits)))
    return tuple(tags), basis
