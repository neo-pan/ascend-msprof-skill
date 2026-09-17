"""Operator CSV facts, with explicit field semantics and per-artifact scope.

Field tables: reference-sources.yaml; Ascend/msopprof metric_csv_header.h and
pmu_calculate.cpp at 80dae2e3701d14e191d2d461eb6be8aab714d89d.
Raw ratios remain ratios; percent, bandwidth, volume and duration stay distinct.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import median
from pathlib import Path
from typing import Annotated, Iterable, Literal

from pydantic import Field, FiniteFloat, model_validator

from .artifact_reader import read_csv
from .ascend_profile_utils import to_float
from .application_timing import PrimarySelection, observation_field_ref
from .analysis_types import EvidenceSignal
from .evidence_types import ArtifactRecord, EvidenceFact, LaunchCount, MetricObservation, ParseIssue, SourceRef
from ._operator_csv_names import operator_group_for_name


OPERATOR_GROUPS = ("op_basic_info", "pipe_utilization", "arithmetic_utilization", "memory", "l2_cache", "resource_conflict")
# Each spelling maps to one confirmed meaning, unit and statistic. No substring matching.
OP_FIELDS: dict[str, dict[str, tuple[str, str]]] = {
    "op_basic_info": {"Task Duration(us)": ("us", "duration"),
                      "Current Freq": ("MHz", "frequency"), "Rated Freq": ("MHz", "frequency")},
    "pipe_utilization": {
        **{f"aic_{pipe}_ratio": ("ratio", "ratio") for pipe in ("cube", "scalar", "mte1", "mte2", "mte3", "fixpipe")},
        **{f"aiv_{pipe}_ratio": ("ratio", "ratio") for pipe in ("vec", "scalar", "mte2", "mte3")},
        **{field: ("us", "duration") for field in (
            "aic_time(us)", "aic_cube_time(us)", "aic_scalar_time(us)",
            "aic_mte1_time(us)", "aic_mte2_time(us)", "aic_mte3_time(us)", "aic_fixpipe_time(us)",
            "aiv_time(us)", "aiv_vec_time(us)", "aiv_scalar_time(us)",
            "aiv_mte2_time(us)", "aiv_mte3_time(us)",
        )},
        **{field: ("GB/s", "bandwidth") for field in (
            "aic_mte1_active_bw(GB/s)", "aic_mte2_active_bw(GB/s)", "aic_mte3_active_bw(GB/s)",
            "aic_fixpipe_active_bw(GB/s)", "aiv_mte2_active_bw(GB/s)", "aiv_mte3_active_bw(GB/s)",
        )},
        "aic_icache_miss_rate": ("ratio", "ratio"), "aiv_icache_miss_rate": ("ratio", "ratio"),
        "Utilization(%)": ("%", "percentage"),
    },
    "arithmetic_utilization": {**{f"aic_cube{suffix}_ratio": ("ratio", "ratio") for suffix in ("", "_fp16", "_int8")},
                               **{f"aiv_vec{suffix}_ratio": ("ratio", "ratio") for suffix in ("", "_fp32", "_fp16", "_int32", "_int16", "_misc")},
                               "Utilization(%)": ("%", "percentage")},
    "resource_conflict": {**{f"{core}_{pipe}_wait_ratio": ("ratio", "ratio") for core, pipes in (("aic", ("cube", "mte1", "mte2", "mte3")), ("aiv", ("vec", "mte1", "mte2", "mte3"))) for pipe in pipes},
                          **{f"aiv_vec_{kind}_cflt_ratio": ("ratio", "ratio") for kind in ("total", "bankgroup", "bank", "resc", "mte")},
                          "Ratio(%)": ("%", "percentage")},
    "l2_cache": {f"{core}_total_hit_rate(%)": ("%", "percentage") for core in ("aic", "aiv")},
    "memory": {
        **{f"{route}_datas(KB)": ("KB", "volume") for route in ("GM_to_L1", "L0C_to_L1", "L0C_to_GM", "GM_to_UB", "UB_to_GM", "read_main_memory", "write_main_memory")},
        **{f"{route}_bw_usage_rate(%)": ("%", "percentage") for route in ("GM_to_L1", "L0C_to_L1", "L0C_to_GM", "GM_to_UB", "UB_to_GM")},
        "L1_to_GM_datas(KB)(estimate)": ("KB", "estimated_volume"),
        "L1_to_GM_bw_usage_rate(%)(estimate)": ("%", "percentage"),
        **{f"{core}_{memory}_{direction}_bw(GB/s)": ("GB/s", "bandwidth") for core, memories in (("aic", ("l1", "main_mem", "l0a", "l0b")), ("aiv", ("main_mem",))) for memory in memories for direction in ("read", "write")},
        "aiv_ub_to_gm_bw(GB/s)": ("GB/s", "bandwidth"), "aiv_gm_to_ub_bw(GB/s)": ("GB/s", "bandwidth"),
        **{f"aic_l0c_{direction}_bw_cube(GB/s)": ("GB/s", "bandwidth") for direction in ("read", "write")},
        **{f"aiv_ub_{direction}_bw_{pipe}(GB/s)": ("GB/s", "bandwidth") for direction in ("read", "write") for pipe in ("vector", "scalar")},
        "Usage Rate(%)": ("%", "percentage"), "GM Read Bandwidth(GB/s)": ("GB/s", "bandwidth"),
    },
}
META_FIELDS = {
    "Op Name": ("name", "text"), "op_name": ("name", "text"),
    "Op Type": ("op_type", "text"), "Shape": ("shape", "text"),
    "Block Dim": ("block_dim", "integer"), "BlockDim": ("block_dim", "integer"),
    "Mix Block Dim": ("mix_block_dim", "integer"),
    "Device Id": ("device_id", "integer"), "Pid": ("pid", "integer"),
}
SCOPE_FIELDS = ("Device Id", "Pid", "block_id", "sub_block_id", "Pipe", "Metric", "Memory", "Resource")
MISSING_TOKENS = {"", "n/a", "na"}
POPULATION_STATISTICS = frozenset({"volume", "estimated_volume", "ratio", "percentage", "bandwidth"})
ADDITIVE_STATISTICS = frozenset({"volume", "estimated_volume"})
_CORE_TIMES = frozenset({"aic_time(us)", "aiv_time(us)"})


@dataclass(frozen=True)
class JointFieldCell:
    metric: str
    value: float | None
    unit: str
    statistic: str
    raw_token: str
    column: int
    source: SourceRef
    metric_source: SourceRef | None = None


@dataclass(frozen=True)
class JointOperatorRow:
    """Recognized fields from one CSV record; not a summary headline.

    Use this when comparing multiple metrics as one execution state. Per-metric
    maxima in summary.json may come from different records and must not be
    treated as co-occurring without a matching joint row.
    """
    artifact: str
    group: str
    record: int
    scope: tuple[tuple[str, str], ...]
    fields: tuple[JointFieldCell, ...]
    raw_cells: tuple[tuple[str, str], ...]
    unmatched: tuple[str, ...] = ()
    issues: tuple[ParseIssue, ...] = ()


@dataclass(frozen=True)
class OperatorMetricCell:
    """One recognized operator metric cell after shared layout/legality checks."""
    field_key: str
    metric: str
    value: float
    unit: str
    statistic: str
    raw_token: str
    value_index: int
    metric_index: int | None = None
    alias_indexes: tuple[int, ...] = ()


def _source_ref(artifact: str, columns: tuple[str, ...], ordinal: int, index: int) -> SourceRef:
    return SourceRef(artifact=artifact, field=columns[index], record=ordinal, column=index + 1)


def parse_operator_row_metrics(
    group: str,
    artifact: str,
    columns: tuple[str, ...],
    cells: tuple[str, ...],
    ordinal: int,
) -> tuple[tuple[OperatorMetricCell, ...], tuple[ParseIssue, ...], tuple[str, ...]]:
    """Parse wide or Metric/Value operator cells with shared legality checks.

    Both summary normalization and ``joint_operator_row`` use this path so pipe
    durations stay nonnegative and long-form Metric/Value rows resolve the same
    metric label and value cell.
    """
    if group not in OP_FIELDS:
        raise ValueError(f"unknown operator group: {group}")
    lower = tuple(field.lower() for field in columns)
    scope_names = {item.lower() for item in SCOPE_FIELDS}
    issues: list[ParseIssue] = []
    cells_out: list[OperatorMetricCell] = []
    used_indexes: set[int] = set()
    unit_layout = any(field in {"unit", "units"} for field in lower)
    if unit_layout:
        issues.append(ParseIssue(
            code="unsupported_unit_layout",
            source=SourceRef(artifact=artifact, record=ordinal),
            reason="separate unit column is outside the supported operator layout",
            impact="metric",
        ))
        unmatched = tuple(
            column for index, column in enumerate(columns)
            if column.lower() not in scope_names and index not in used_indexes
        )
        return (), tuple(issues), unmatched

    for field, (unit, statistic) in OP_FIELDS[group].items():
        positions = [index for index, column in enumerate(lower) if column == field.lower()]
        metric_index = None
        metric = field
        if lower.count("metric") == 1 and lower.count("value") == 1 and cells[lower.index("metric")].lower() == field.lower():
            if positions:
                issues.append(ParseIssue(
                    code="alias_conflict",
                    source=_source_ref(artifact, columns, ordinal, positions[0]),
                    reason="wide and metric/value layouts overlap",
                    impact="metric",
                ))
                continue
            positions = [lower.index("value")]
            metric_index = lower.index("metric")
            metric = cells[metric_index]
        if not positions or len({columns[index] for index in positions}) != len(positions):
            continue
        values = [to_float(cells[index]) for index in positions]
        if len(set(values)) > 1:
            issues.append(ParseIssue(
                code="alias_conflict",
                source=_source_ref(artifact, columns, ordinal, positions[0]),
                reason=f"numeric aliases for {field} disagree",
                impact="metric",
            ))
            continue
        value = values[0]
        if value is None:
            if any(cells[index].strip().lower() not in MISSING_TOKENS for index in positions):
                issues.append(ParseIssue(
                    code="invalid_number",
                    source=_source_ref(artifact, columns, ordinal, positions[0]),
                    reason="operator cell is not a finite decimal number",
                    impact="metric",
                ))
            continue
        value_index = positions[0]
        if group == "pipe_utilization" and statistic == "duration" and value < 0:
            issues.append(ParseIssue(
                code="invalid_number",
                source=_source_ref(artifact, columns, ordinal, value_index),
                reason="pipe time must be nonnegative",
                impact="metric",
            ))
            continue
        used_indexes.update(positions)
        if metric_index is not None:
            used_indexes.add(metric_index)
        cells_out.append(OperatorMetricCell(
            field_key=field.lower(),
            metric=metric if metric_index is not None else columns[value_index],
            value=value,
            unit=unit,
            statistic=statistic,
            raw_token=cells[value_index],
            value_index=value_index,
            metric_index=metric_index,
            alias_indexes=tuple(positions[1:]),
        ))
    unmatched = tuple(
        column for index, column in enumerate(columns)
        if column.lower() not in scope_names and index not in used_indexes
    )
    return tuple(cells_out), tuple(issues), unmatched


def operator_group_for_path(path: Path) -> str | None:
    return operator_group_for_name(path.name)


class SameRecordCell(EvidenceFact):
    """Another recognized cell on the representative observation's CSV record."""
    metric: str
    value: FiniteFloat
    unit: str
    statistic: Literal[
        "duration", "ratio", "percentage", "bandwidth", "volume", "estimated_volume", "frequency",
    ]


class DerivedPipeQuotient(EvidenceFact):
    """Same-row pipe_time / core_time. Not CalRatio and not a headline replacement."""
    numerator: str
    denominator: str
    value: FiniteFloat
    recorded_ratio: FiniteFloat | None = None


class FieldPopulation(EvidenceFact):
    """Legal population of one metric within one artifact and core-class scope."""
    metric: str
    statistic: Literal["volume", "estimated_volume", "ratio", "percentage", "bandwidth"]
    unit: str
    scope: Annotated[tuple[Annotated[tuple[str, str], Field(strict=False)], ...], Field(strict=False)]
    valid_count: int = Field(ge=1)
    minimum: FiniteFloat
    median: FiniteFloat
    maximum: FiniteFloat
    sum: FiniteFloat | None = None
    aggregation: Literal["population_over_rows", "sum_over_rows"]

    @model_validator(mode="after")
    def consistent_population(self) -> FieldPopulation:
        if not (self.minimum <= self.median <= self.maximum):
            raise ValueError("population extrema disagree")
        additive = self.statistic in ADDITIVE_STATISTICS
        if additive:
            if self.sum is None or self.aggregation != "sum_over_rows":
                raise ValueError("volume population requires a scoped sum")
            if self.valid_count == 1 and self.sum != self.maximum:
                raise ValueError("single-cell volume sum must equal the cell")
        elif self.sum is not None or self.aggregation != "population_over_rows":
            raise ValueError("non-additive population cannot carry a sum")
        return self


def derived_pipe_quotients(fields: Iterable[object]) -> tuple[DerivedPipeQuotient, ...]:
    """Same-row pipe_time / core_time quotients from recognized cells."""
    values = {
        metric: value
        for item in fields
        if (metric := getattr(item, "metric", None)) and (value := getattr(item, "value", None)) is not None
    }
    out: list[DerivedPipeQuotient] = []
    for metric, value in values.items():
        if metric in _CORE_TIMES or not metric.endswith("_time(us)"):
            continue
        core = (
            "aic_time(us)" if metric.startswith("aic_")
            else "aiv_time(us)" if metric.startswith("aiv_")
            else None
        )
        denom = values.get(core) if core else None
        quotient = to_float(value / denom) if denom else None
        if core is None or quotient is None:
            continue
        recorded = f"{metric[:3]}_{metric[4:-len('_time(us)')]}_ratio"
        recorded_value = values.get(recorded)
        out.append(DerivedPipeQuotient(
            numerator=metric,
            denominator=core,
            value=quotient,
            recorded_ratio=recorded_value if isinstance(recorded_value, (int, float)) else None,
        ))
    return tuple(out)


def _population_scope(scope: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    return tuple(pair for pair in scope if pair[0].lower() != "block_id")


def observations_are_joint(*items: MetricObservation) -> bool:
    if len(items) < 2:
        return len(items) == 1
    first = items[0]
    return all(
        item.source.artifact == first.source.artifact
        and item.source.record == first.source.record
        and item.source.record is not None
        for item in items[1:]
    )


def joint_operator_row(
    path: Path,
    artifact: str,
    group: str,
    *,
    record: int | None = None,
    scope: dict[str, str] | None = None,
) -> JointOperatorRow:
    """Return recognized cells for one operator CSV record or unique scope.

    Provide ``record`` (CSV record number, header is 1) or ``scope`` keys such
    as ``block_id`` / ``sub_block_id`` / ``Device Id``. Ambiguous scope matches
    raise ``ValueError``. Unknown columns remain in ``raw_cells`` without
    guessed units.
    """
    if group not in OP_FIELDS:
        raise ValueError(f"unknown operator group: {group}")
    if (record is None) == (scope is None):
        raise ValueError("provide exactly one of record or scope")
    if record is not None and record < 2:
        raise ValueError("record must be a data CSV record (>= 2)")
    scope_names = {item.lower() for item in SCOPE_FIELDS}
    wanted = {key.lower(): value for key, value in (scope or {}).items()}
    matches: list[tuple[int, tuple[str, ...], tuple[str, ...], tuple[tuple[str, str], ...]]] = []

    def consume(columns: tuple[str, ...], cells: tuple[str, ...], ordinal: int) -> None:
        if record is not None:
            if ordinal != record:
                return
        else:
            present = {columns[index].lower(): cells[index] for index, field in enumerate(columns)
                       if field.lower() in scope_names}
            if any(present.get(key) != value for key, value in wanted.items()):
                return
            if any(key not in present for key in wanted):
                return
        row_scope = tuple((field, cells[index]) for index, field in enumerate(columns)
                          if field.lower() in scope_names)
        matches.append((ordinal, columns, cells, row_scope))

    decoded = read_csv(path, artifact, consume)
    if decoded.status == "invalid" and not matches and any(issue.code == "csv_decode" for issue in decoded.issues):
        raise ValueError(decoded.issues[0].reason)
    if not matches:
        raise ValueError("no operator CSV row matched the requested record or scope")
    if len(matches) > 1:
        raise ValueError(f"scope matched {len(matches)} operator CSV rows; use record=")
    ordinal, columns, cells, row_scope = matches[0]
    parsed, issues, unmatched = parse_operator_row_metrics(group, artifact, columns, cells, ordinal)
    fields = tuple(
        JointFieldCell(
            metric=item.metric,
            value=item.value,
            unit=item.unit,
            statistic=item.statistic,
            raw_token=item.raw_token,
            column=item.value_index + 1,
            source=_source_ref(artifact, columns, ordinal, item.value_index),
            metric_source=(
                _source_ref(artifact, columns, ordinal, item.metric_index)
                if item.metric_index is not None else None
            ),
        )
        for item in parsed
    )
    return JointOperatorRow(
        artifact=artifact, group=group, record=ordinal, scope=row_scope,
        fields=fields, raw_cells=tuple(zip(columns, cells)), unmatched=unmatched, issues=issues,
    )


def _metadata_value(raw: str, kind: str) -> str | int | None:
    if raw.strip().lower() in MISSING_TOKENS:
        return None
    if kind == "text":
        return raw
    if re.fullmatch(r"[0-9]+", raw.strip()):
        try:
            return int(raw)
        except ValueError:
            pass
    return None


class MetadataObservation(EvidenceFact):
    metric: str
    name: str | None = None
    value: str | int
    source: SourceRef
    raw_token: str
    aliases: Annotated[tuple[SourceRef, ...], Field(strict=False)] = ()

    @model_validator(mode="after")
    def consistent_value(self) -> MetadataObservation:
        spec = next((spec for field, spec in META_FIELDS.items() if field.lower() == (self.source.field or "").lower()), None)
        if spec is None or self.metric != spec[0] or self.value != _metadata_value(self.raw_token, spec[1]):
            raise ValueError("metadata value, field and raw token disagree")
        if (spec[1] == "integer") != isinstance(self.value, int):
            raise ValueError("metadata value type disagrees with field")
        for alias in self.aliases:
            if next((value for field, value in META_FIELDS.items() if field.lower() == (alias.field or "").lower()), None) != spec:
                raise ValueError("metadata alias disagrees with its metric")
        return self


class OperatorObservation(MetricObservation):
    metric_source: SourceRef | None = None
    same_record: Annotated[tuple[SameRecordCell, ...], Field(strict=False)] = ()
    derived_pipe_quotients: Annotated[tuple[DerivedPipeQuotient, ...], Field(strict=False)] = ()

    @model_validator(mode="after")
    def consistent_row_projection(self) -> OperatorObservation:
        metrics = [cell.metric for cell in self.same_record]
        if len(set(metrics)) != len(metrics):
            raise ValueError("same-record peers must be unique metrics")
        if self.metric in set(metrics):
            raise ValueError("same-record peers cannot include the representative metric")
        known = {self.metric, *metrics}
        for item in self.derived_pipe_quotients:
            if item.numerator not in known or item.denominator not in known:
                raise ValueError("derived quotient must use same-record pipe times")
        return self


class CoreTimeDistribution(EvidenceFact):
    metric: str
    scope: Annotated[tuple[Annotated[tuple[str, str], Field(strict=False)], ...], Field(strict=False)]
    valid_count: int = Field(ge=1)
    median_us: FiniteFloat = Field(ge=0)
    maximum: OperatorObservation
    second_largest: OperatorObservation | None

    @model_validator(mode="after")
    def consistent_distribution(self) -> CoreTimeDistribution:
        if (self.valid_count == 1) != (self.second_largest is None):
            raise ValueError("distribution count disagrees with second largest cell")
        if self.median_us > self.maximum.value:
            raise ValueError("distribution median exceeds maximum")
        for item in (self.maximum, self.second_largest):
            if item is None:
                continue
            if (item.metric != self.metric or item.unit != "us" or item.statistic != "duration"
                    or not 0 <= item.value <= self.maximum.value
                    or tuple(pair for pair in item.scope if pair[0].lower() != "block_id") != self.scope):
                raise ValueError("distribution cell disagrees with metric or scope")
        return self


class OperatorArtifact(ArtifactRecord):
    observations: Annotated[tuple[OperatorObservation, ...], Field(strict=False)]
    metadata: Annotated[tuple[MetadataObservation, ...], Field(strict=False)] = ()
    core_time_distributions: Annotated[tuple[CoreTimeDistribution, ...], Field(strict=False)] = ()
    field_populations: Annotated[tuple[FieldPopulation, ...], Field(strict=False)] = ()

    @model_validator(mode="after")
    def consistent_operator(self) -> OperatorArtifact:
        if self.group not in OPERATOR_GROUPS:
            raise ValueError("unknown operator group")
        known = {field.lower(): spec for field, spec in OP_FIELDS[self.group].items()}
        keys = [(item.metric.lower(), item.name if self.group == "op_basic_info" else None,
                 tuple(pair for pair in item.scope if pair[0].lower() not in {"block_id", "sub_block_id"}))
                for item in self.observations]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate representative operator metric within one scope")
        for item in self.observations:
            if any(alias.field.lower() != item.source.field.lower() for alias in item.aliases):
                raise ValueError("operator aliases disagree with metric source")
            if known.get(item.metric.lower()) != (item.unit, item.statistic):
                raise ValueError("operator metric unit/statistic disagrees with field")
            if item.metric_source is not None:
                source = item.metric_source
                if source.artifact != self.artifact or source.record != item.source.record or source.column is None:
                    raise ValueError("metric label must be in the same CSV record")
                if self.columns[source.column - 1:source.column] != (source.field,) or (source.field or "").lower() != "metric" or (item.source.field or "").lower() != "value":
                    raise ValueError("unsupported metric/value layout")
            elif item.metric != item.source.field:
                raise ValueError("operator metric identifier disagrees with source field")
        for item in self.metadata:
            for source in (item.source, *item.aliases):
                if (self.group != "op_basic_info" or source.artifact != self.artifact or source.record is None
                        or source.record < 2 or source.record != item.source.record):
                    raise ValueError("operator metadata source disagrees with artifact")
                if source.column is None or self.columns[source.column - 1:source.column] != (source.field,):
                    raise ValueError("operator metadata column disagrees with header")
        for distribution in self.core_time_distributions:
            if self.group != "pipe_utilization" or distribution.valid_count > self.row_count:
                raise ValueError("core time distribution disagrees with artifact")
            for cell in (distribution.maximum, distribution.second_largest):
                if cell is not None and (cell.source.artifact != self.artifact
                        or cell.source.column is None
                        or self.columns[cell.source.column - 1:cell.source.column] != (cell.source.field,)):
                    raise ValueError("core time distribution source disagrees with artifact")
        for population in self.field_populations:
            if population.valid_count > self.row_count:
                raise ValueError("field population disagrees with artifact")
            spec = known.get(population.metric.lower())
            if spec != (population.unit, population.statistic):
                raise ValueError("field population unit/statistic disagrees with field")
            if (population.statistic in ADDITIVE_STATISTICS) != (population.aggregation == "sum_over_rows"):
                raise ValueError("field population aggregation disagrees with statistic")
        return self

    @property
    def launch_name(self) -> str | None:
        if self.status == "parsed" and self.row_count == 1:
            return next((str(item.value) for item in self.metadata if item.metric == "name"), None)
        return None


def select_operator_primary(artifacts: tuple[OperatorArtifact, ...]) -> PrimarySelection:
    # Retain every metric's located observation. Numeric magnitude and unit
    # families do not decide which metric answers the caller's question.
    # The legacy selection container only resolves a sole observation.
    candidates = [item.source for artifact in artifacts for item in artifact.observations
                  if item.statistic != "frequency"]
    scopes = {(artifact.artifact, tuple(pair for pair in item.scope
               if pair[0].lower() not in {"block_id", "sub_block_id"}))
              for artifact in artifacts for item in artifact.observations if item.statistic != "frequency"}
    return PrimarySelection(candidates=tuple(candidates), selected=candidates[0] if len(candidates) == 1 else None,
        reason="selected" if len(candidates) == 1 else ("multiple_scopes" if len(scopes) > 1 else "multiple_observations") if candidates else "no_valid_observation")


class OperatorEvidence(EvidenceFact):
    group: Literal["op_basic_info", "pipe_utilization", "arithmetic_utilization", "memory", "l2_cache", "resource_conflict"]
    artifacts: Annotated[tuple[OperatorArtifact, ...], Field(strict=False)]
    primary: PrimarySelection

    @model_validator(mode="after")
    def consistent_selection(self) -> OperatorEvidence:
        if any(item.group != self.group for item in self.artifacts):
            raise ValueError("operator group disagrees with artifacts")
        if len({item.artifact for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("duplicate operator artifact")
        if self.primary != select_operator_primary(self.artifacts):
            raise ValueError("operator primary disagrees with observations")
        return self

    @property
    def observation(self) -> MetricObservation | None:
        return next((item for artifact in self.artifacts for item in artifact.observations if item.source == self.primary.selected), None)

    @property
    def available(self) -> bool:
        return any(item.statistic != "frequency" for artifact in self.artifacts for item in artifact.observations)


def normalize_operator(path: Path, artifact: str, group: str, segment: str, metric_scope: str | None) -> OperatorArtifact:
    known = {field.lower(): spec for field, spec in OP_FIELDS[group].items()}
    metadata_fields = {field.lower(): spec for field, spec in META_FIELDS.items()} if group == "op_basic_info" else {}
    best = {}
    metadata = {}
    issues = []
    counts = {}
    distributions = {}
    populations: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[str, str, list[float]]] = {}

    def consume(columns: tuple[str, ...], cells: tuple[str, ...], ordinal: int) -> None:
        lower = tuple(field.lower() for field in columns)
        scope = tuple((field, cells[index]) for index, field in enumerate(columns)
                      if field.lower() in {item.lower() for item in SCOPE_FIELDS})
        def ref(index):
            return SourceRef(artifact=artifact, field=columns[index], record=ordinal, column=index + 1)
        row_metadata = {}
        for key in dict.fromkeys(spec[0] for spec in metadata_fields.values()):
            positions = [index for index, field in enumerate(lower) if field in metadata_fields and metadata_fields[field][0] == key]
            if not positions or len({columns[index] for index in positions}) != len(positions):
                continue
            kind = metadata_fields[lower[positions[0]]][1]
            values = [_metadata_value(cells[index], kind) for index in positions]
            if len(set(values)) > 1:
                issues.append(ParseIssue(code="alias_conflict", source=ref(positions[0]), reason=f"metadata aliases for {key} disagree", impact="scope"))
                continue
            value = values[0]
            if value is not None:
                row_metadata[key] = MetadataObservation(metric=key, value=value, source=ref(positions[0]),
                    raw_token=cells[positions[0]], aliases=tuple(ref(index) for index in positions[1:]))
            elif any(cells[index].strip().lower() not in MISSING_TOKENS for index in positions):
                issues.append(ParseIssue(code="invalid_metadata", source=ref(positions[0]), reason=f"{key} is not a valid {kind}", impact="metric"))
        if group == "op_basic_info":
            name = str(row_metadata["name"].value) if "name" in row_metadata else None
        else:
            name = next((cells[lower.index(field)] for field in ("sub_block_id", "pipe", "metric", "resource") if field in lower), None)
        for key, item in row_metadata.items():
            metadata.setdefault((key, item.value, name, scope), item.model_copy(update={'name': name}))
        duration = None
        parsed, row_issues, _unmatched = parse_operator_row_metrics(group, artifact, columns, cells, ordinal)
        issues.extend(row_issues)
        row_quotients = derived_pipe_quotients(parsed) if group == "pipe_utilization" else ()
        for item in parsed:
            # A launch CSV can contain many core rows. Retain one representative
            # maximum per metric, with its original core/source; do not retain
            # a model for every cell or merge different launch files/devices.
            selection_scope = tuple(pair for pair in scope if pair[0].lower() not in {"block_id", "sub_block_id"})
            key = (item.field_key, name if group == "op_basic_info" else None, selection_scope)
            metric_source = (
                _source_ref(artifact, columns, ordinal, item.metric_index)
                if item.metric_index is not None else None
            )
            observation = OperatorObservation(
                metric=item.metric, value=item.value, unit=item.unit, statistic=item.statistic,
                name=name, scope=scope, source=_source_ref(artifact, columns, ordinal, item.value_index),
                raw_token=item.raw_token,
                aliases=tuple(_source_ref(artifact, columns, ordinal, index) for index in item.alias_indexes),
                metric_source=metric_source,
                same_record=tuple(
                    SameRecordCell(metric=peer.metric, value=peer.value, unit=peer.unit, statistic=peer.statistic)
                    for peer in parsed if peer.field_key != item.field_key
                ),
                derived_pipe_quotients=row_quotients,
            )
            if key not in best or item.value > best[key].value:
                best[key] = observation
            if item.statistic in POPULATION_STATISTICS:
                pop_scope = _population_scope(scope)
                pop_key = (item.metric, pop_scope)
                unit, statistic, values = populations.get(pop_key, (item.unit, item.statistic, []))
                values.append(item.value)
                populations[pop_key] = (unit, statistic, values)
            core_scope = {k.lower(): v for k, v in scope}
            if (group == "pipe_utilization" and item.statistic == "duration"
                    and core_scope.get("block_id", "").isdigit() and core_scope.get("sub_block_id")):
                distribution_scope = tuple(pair for pair in scope if pair[0].lower() != "block_id")
                values, top = distributions.setdefault((observation.metric, distribution_scope), ([], []))
                values.append(item.value)
                top.append(observation)
                top.sort(key=lambda entry: entry.value, reverse=True)
                del top[2:]
            if item.statistic == "duration":
                duration = item.value
        if group == "op_basic_info":
            count, total = counts.get(name or "", (0, 0.0))
            if total is not None and duration is not None:
                total = to_float(total + duration)
                if total is None:
                    issues.append(ParseIssue(code="aggregate_overflow", source=SourceRef(artifact=artifact, record=ordinal),
                        reason="operator duration aggregate exceeds finite range", impact="metric"))
            else:
                total = None
            counts[name or ""] = (count + 1, total)

    decoded = read_csv(path, artifact, consume)
    if decoded.columns and not best and not metadata and not any(field.lower() in known or field.lower() in metadata_fields for field in decoded.columns):
        issues.append(ParseIssue(code="unsupported_fields", source=SourceRef(artifact=artifact, record=1),
            reason="no recognized operator fields", impact="metric"))
    field_populations = []
    for (metric, scope), (unit, statistic, values) in populations.items():
        total = to_float(sum(values)) if statistic in ADDITIVE_STATISTICS else None
        if statistic in ADDITIVE_STATISTICS and total is None:
            issues.append(ParseIssue(
                code="aggregate_overflow",
                source=SourceRef(artifact=artifact, record=1),
                reason=f"volume population for {metric!r} exceeds finite numeric range",
                impact="metric",
            ))
            continue
        field_populations.append(FieldPopulation(
            metric=metric,
            statistic=statistic,  # type: ignore[arg-type]
            unit=unit,
            scope=scope,
            valid_count=len(values),
            minimum=min(values),
            median=median(values),
            maximum=max(values),
            sum=total,
            aggregation="sum_over_rows" if statistic in ADDITIVE_STATISTICS else "population_over_rows",
        ))
    return OperatorArtifact(artifact=artifact, group=group, segment=segment, metric_scope=metric_scope,
        columns=decoded.columns, status=decoded.status, row_count=decoded.row_count, sample_rows=decoded.sample_rows,
        issues=(*decoded.issues, *issues), observations=tuple(best.values()), metadata=tuple(metadata.values()),
        core_time_distributions=tuple(CoreTimeDistribution(metric=metric, scope=scope, valid_count=len(values),
            median_us=median(values), maximum=top[0], second_largest=top[1] if len(top) > 1 else None)
            for (metric, scope), (values, top) in distributions.items()),
        field_populations=tuple(field_populations),
        launch_counts=tuple(LaunchCount(name=name, count=count, duration_us=total) for name, (count, total) in counts.items()))


def operator_metric_kind(group: str, item: MetricObservation) -> str:
    if group == "pipe_utilization" and item.statistic == "duration":
        return "pipe_time"
    if group == "pipe_utilization" and item.statistic == "bandwidth":
        return "pipe_active_bandwidth"
    if group == "memory" and item.statistic == "percentage":
        return "memory_usage_rate"
    if group == "l2_cache":
        return "l2_cache_hit_rate"
    return {"duration": "basic_info", "ratio": "utilization_or_ratio", "percentage": "utilization_or_ratio",
            "bandwidth": "memory_bandwidth", "volume": "memory_volume", "estimated_volume": "memory_volume", "frequency": "frequency"}[item.statistic]


def operator_signals(evidence: OperatorEvidence, artifacts: tuple[OperatorArtifact, ...] | None = None) -> list[EvidenceSignal]:
    signals = []
    for artifact in evidence.artifacts if artifacts is None else artifacts:
        for item in artifact.observations:
            kind = operator_metric_kind(evidence.group, item)
            signals.append(EvidenceSignal.model_validate({"group": evidence.group, "signal": f"{item.name or 'n/a'} / {item.metric}",
                "artifact": artifact.artifact, "field": item.source.field, "field_ref": observation_field_ref(evidence.group, item),
                "value": item.value, "unit": item.unit, "statistic": item.statistic, "kind": kind,
                "row_count": artifact.row_count, "segment": artifact.segment, "metric_scope": artifact.metric_scope}))
        for item in artifact.metadata:
            name = item.name
            field_ref = f"headlines.{evidence.group}.artifacts.metadata; record={item.source.record}; column={item.source.column}; field={item.source.field}"
            signal = {"group": evidence.group, "signal": name or "n/a", "artifact": artifact.artifact,
                "field": item.source.field, "field_ref": field_ref, "value": None, "kind": "basic_info",
                "metadata_field": item.source.field, "metadata_value": item.value,
                "row_count": artifact.row_count, "segment": artifact.segment, "metric_scope": artifact.metric_scope}
            if item.metric in {"block_dim", "mix_block_dim"}:
                signal.update(tiling_field=item.source.field, tiling_value=item.value, tiling_field_ref=field_ref)
            signals.append(EvidenceSignal.model_validate(signal))
    return signals
