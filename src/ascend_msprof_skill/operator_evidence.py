"""Operator CSV facts, with explicit field semantics and per-artifact scope.

Field tables: reference-sources.yaml; Ascend/msopprof metric_csv_header.h and
pmu_calculate.cpp at 80dae2e3701d14e191d2d461eb6be8aab714d89d.
Raw ratios remain ratios; percent, bandwidth, volume and duration stay distinct.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .artifact_reader import read_csv
from .ascend_profile_utils import to_float
from .application_timing import PrimarySelection, observation_field_ref
from .analysis_types import EvidenceSignal
from .evidence_types import ArtifactRecord, EvidenceFact, LaunchCount, MetricObservation, ParseIssue, SourceRef


OPERATOR_GROUPS = ("op_basic_info", "pipe_utilization", "arithmetic_utilization", "memory", "l2_cache", "resource_conflict")
# Each spelling maps to one confirmed meaning, unit and statistic. No substring matching.
OP_FIELDS: dict[str, dict[str, tuple[str, str]]] = {
    "op_basic_info": {"Task Duration(us)": ("us", "duration"),
                      "Current Freq": ("MHz", "frequency"), "Rated Freq": ("MHz", "frequency")},
    "pipe_utilization": {**{f"aic_{pipe}_ratio": ("ratio", "ratio") for pipe in ("cube", "scalar", "mte1", "mte2", "mte3", "fixpipe")},
                         **{f"aiv_{pipe}_ratio": ("ratio", "ratio") for pipe in ("vec", "scalar", "mte2", "mte3")},
                         "Utilization(%)": ("%", "percentage")},
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


class OperatorArtifact(ArtifactRecord):
    observations: Annotated[tuple[OperatorObservation, ...], Field(strict=False)]
    metadata: Annotated[tuple[MetadataObservation, ...], Field(strict=False)] = ()

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
        unit_layout = any(field in {"unit", "units"} for field in lower)
        if unit_layout:
            issues.append(ParseIssue(code="unsupported_unit_layout", source=SourceRef(artifact=artifact, record=ordinal),
                reason="separate unit column is outside the supported operator layout", impact="metric"))
        for field, (unit, statistic) in OP_FIELDS[group].items():
            positions = [index for index, column in enumerate(lower) if column == field.lower()]
            metric_source = None
            metric = field
            if lower.count("metric") == 1 and lower.count("value") == 1 and cells[lower.index("metric")].lower() == field.lower():
                if positions:
                    issues.append(ParseIssue(code="alias_conflict", source=ref(positions[0]), reason="wide and metric/value layouts overlap", impact="metric"))
                    continue
                positions = [lower.index("value")]
                metric_source = ref(lower.index("metric"))
                metric = cells[lower.index("metric")]
            if not positions or unit_layout or len({columns[index] for index in positions}) != len(positions):
                continue
            values = [to_float(cells[index]) for index in positions]
            if len(set(values)) > 1:
                issues.append(ParseIssue(code="alias_conflict", source=ref(positions[0]), reason=f"numeric aliases for {field} disagree", impact="metric"))
                continue
            value = values[0]
            if value is None:
                if any(cells[index].strip().lower() not in MISSING_TOKENS for index in positions):
                    issues.append(ParseIssue(code="invalid_number", source=ref(positions[0]), reason="operator cell is not a finite decimal number", impact="metric"))
                continue
            index = positions[0]
            # A launch CSV can contain many core rows. Retain one representative
            # maximum per metric, with its original core/source; do not retain
            # a model for every cell or merge different launch files/devices.
            selection_scope = tuple(pair for pair in scope if pair[0].lower() not in {"block_id", "sub_block_id"})
            key = (field.lower(), name if group == "op_basic_info" else None, selection_scope)
            if key not in best or value > best[key].value:
                best[key] = OperatorObservation(metric=metric if metric_source else columns[index], value=value, unit=unit, statistic=statistic,
                    name=name, scope=scope, source=ref(index), raw_token=cells[index], aliases=tuple(ref(i) for i in positions[1:]), metric_source=metric_source)
            if statistic == "duration":
                duration = value
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
    return OperatorArtifact(artifact=artifact, group=group, segment=segment, metric_scope=metric_scope,
        columns=decoded.columns, status=decoded.status, row_count=decoded.row_count, sample_rows=decoded.sample_rows,
        issues=(*decoded.issues, *issues), observations=tuple(best.values()), metadata=tuple(metadata.values()),
        launch_counts=tuple(LaunchCount(name=name, count=count, duration_us=total) for name, (count, total) in counts.items()))


def operator_metric_kind(group: str, item: MetricObservation) -> str:
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
