"""Opt-in launch selection and like-for-like operator CSV populations.

Uses the existing CANN operator layout and field registry. Launch ordinals are
the numeric msprof op launch directories, never export timestamps or row pages.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re
from statistics import median

from .artifact_reader import read_csv
from .evidence_binding import raw_reference, safe_path
from .operator_evidence import MISSING_TOKENS, OP_FIELDS, SCOPE_FIELDS, parse_operator_row_metrics
from ._profiler_segments import operator_launch_metadata
from ._profile_target import match_expected_names


LIMITATIONS = [
    "Across-launch statistics describe captured profiler cells within one process/root; launches are not independent process samples.",
    "Metric families, targets, devices, streams, core classes, blocks and sub-blocks remain separate; no percentage, rate or duration sums are computed.",
    "Caller-declared scored selection does not establish natural latency, formal scoring eligibility, simultaneity, overlap or a bottleneck.",
    "Coverage is for this query selection; count-complete BasicInfo does not imply complete PMU fields or program coverage.",
]
_EXTRA_SCOPE = {"stream_id", "stream id", "core type", "core_type", "core id", "core_id",
                "device_id", "process id", "process_id"}


def launch_coordinates(entry) -> dict | None:
    metadata = operator_launch_metadata(entry.artifact, entry.segment)
    ordinal = metadata.get("launch_ordinal")
    if ordinal is None or re.fullmatch(r"[0-9]+", ordinal) is None:
        return None
    return {"segment": entry.segment, "opprof_root": metadata["opprof_root"],
            "kernel_directory": metadata["kernel_directory"],
            "target_name": entry.target_name,
            "launch_index": int(ordinal)}


def _cohort(entry) -> tuple | None:
    coordinates = launch_coordinates(entry)
    if coordinates is None:
        return None
    return tuple(coordinates[key] for key in ("segment", "opprof_root", "kernel_directory", "target_name"))


def _cohort_dict(key: tuple) -> dict:
    return dict(zip(("segment", "opprof_root", "kernel_directory", "target_name"), key))


def select_launches(entries: list, index: tuple, sampling: dict | None, launch_scope: str, *, run_dir: Path,
                    groups: tuple[str, ...], receipts, segment: str | None = None,
                    artifact: str | None = None, declared_coverage=None) -> tuple[list, dict]:
    if launch_scope not in {"all", "scored"}:
        raise ValueError("launch_scope must be all or scored")
    launches = sampling.get("program_launches") if sampling is not None else None
    skip = sampling.get("steady_state_skip") if sampling is not None else None
    if launch_scope == "scored" and (type(launches) is not int or type(skip) is not int or not 0 <= skip < launches):
        raise ValueError("scored launch scope requires caller sampling.program_launches and steady_state_skip with 0 <= skip < program_launches")
    expected = (list(range(skip if launch_scope == "scored" else 0, launches))
                if type(launches) is int and launches >= 0 else None)
    relevant = [entry for entry in index if entry.group in OP_FIELDS
                and (segment is None or entry.segment == segment)]
    all_cohorts = {_cohort(entry) for entry in relevant}
    all_cohorts.discard(None)
    cohorts = {_cohort(entry) for entry in entries + (relevant if artifact is None else [])}
    cohorts.discard(None)
    conflicts = {}
    for cohort in cohorts:
        basics = [entry for entry in relevant if entry.group == "op_basic_info" and _cohort(entry) == cohort]
        extra = sorted({launch_coordinates(entry)["launch_index"] for entry in basics
                        if type(launches) is int and launch_coordinates(entry)["launch_index"] >= launches})
        declared_count = None
        if declared_coverage is not None and type(launches) is int:
            scope = declared_coverage.segments.get(cohort[0])
            if scope is not None:
                target_key, _ = match_expected_names(scope.expected_display_names, cohort[3])
                candidate_count = scope.expected_counts.get(target_key)
                # Segment totals can cover multiple process roots. Only a
                # single-root target count establishes this conflict locally.
                matching_roots = {key[1] for key in all_cohorts if key[0] == cohort[0] and key[3] == cohort[3]}
                if len(matching_roots) == 1 and candidate_count is not None and candidate_count > launches:
                    declared_count = candidate_count
        if extra or declared_count is not None:
            conflicts[cohort] = {"out_of_declared_range_basic_indices": extra,
                "declared_target_launch_count": declared_count,
                "reason": "Operator invocation ordinals conflict with caller program_launches; invocation-to-program mapping is unavailable. Scored statistics are excluded for this cohort."}
    selected, excluded = [], []
    for entry in entries:
        coordinates = launch_coordinates(entry)
        reason = None
        if launch_scope == "scored":
            if _cohort(entry) in conflicts:
                reason = conflicts[_cohort(entry)]["reason"]
            elif coordinates is None:
                reason = "No numeric nested msprof op launch directory; scored index cannot be established."
            elif coordinates["launch_index"] < skip:
                reason = "Caller-declared warmup/steady-state prefix excluded."
            elif coordinates["launch_index"] >= launches:
                reason = "Launch index is outside caller-declared program_launches."
        if reason:
            excluded.append({"artifact": entry.artifact, "group": entry.group,
                             "coordinates": coordinates, "reason": reason})
        else:
            selected.append(entry)
    # Discover cohorts from all selected-segment operator records, including
    # BasicInfo when a requested PMU family is entirely absent.
    coverage = []
    for cohort in sorted(cohorts, key=str):
        basic = [entry for entry in relevant if entry.group == "op_basic_info" and _cohort(entry) == cohort]
        observed = defaultdict(list)
        for entry in basic:
            coordinate = launch_coordinates(entry)["launch_index"]
            if expected is None or coordinate in expected:
                if (receipts.allows(entry.segment) and safe_path(run_dir, entry.artifact).is_file()
                        and entry.status == "parsed" and entry.row_count == 1):
                    observed[coordinate].append(entry.artifact)
        basic_present = sorted(number for number, artifacts in observed.items() if len(artifacts) == 1)
        duplicate_basic = {str(number): artifacts for number, artifacts in observed.items() if len(artifacts) != 1}
        families = []
        for group in groups:
            if group not in OP_FIELDS:
                continue
            by_launch = defaultdict(list)
            for entry in selected:
                if entry.group == group and _cohort(entry) == cohort:
                    if (receipts.allows(entry.segment) and safe_path(run_dir, entry.artifact).is_file()
                            and entry.status in {"parsed", "partial"}):
                        by_launch[launch_coordinates(entry)["launch_index"]].append(entry.artifact)
            present = sorted(by_launch)
            families.append({"group": group, "observed_launch_indices": present,
                "missing_launch_indices": sorted(set(expected) - set(present)) if expected is not None else None,
                "artifact_presence_complete": expected is not None and set(present) == set(expected) and cohort not in conflicts,
                "meaning": "Artifact presence only; per-field complete is reported separately by aggregation groups."})
        coverage.append({**_cohort_dict(cohort), "expected_launch_indices": expected,
            "ordinal_mapping_conflict": conflicts.get(cohort),
            "out_of_declared_range_basic_indices": conflicts.get(cohort, {}).get("out_of_declared_range_basic_indices", []),
            "basic_info_launch_indices": basic_present, "duplicate_basic_info": duplicate_basic,
            "missing_basic_info_launch_indices": sorted(set(expected) - set(basic_present)) if expected is not None else None,
            "basic_info_complete": expected is not None and set(basic_present) == set(expected) and not duplicate_basic and cohort not in conflicts,
            "metric_artifact_coverage": families})
    return selected, {"scope": launch_scope, "sampling": sampling,
        "expected_launch_indices": expected, "included_artifacts": [entry.artifact for entry in selected],
        "excluded_artifacts": excluded, "coverage": coverage, "limitations": LIMITATIONS}


def aggregate_launches(run_dir: Path, entries: list, receipts, selection: dict, *, fields: list[str] | None = None,
                       offset: int = 0, limit: int | None = 20) -> dict:
    """Retain every grouping dimension and one legal cell per launch per group."""
    requested = {field.lower() for field in fields or []}
    buckets = defaultdict(lambda: defaultdict(list))
    excluded, issues = [], []
    expected = selection["expected_launch_indices"]
    conflicted_cohorts = {tuple(item[key] for key in ("segment", "opprof_root", "kernel_directory", "target_name"))
                          for item in selection.get("coverage", []) if item.get("ordinal_mapping_conflict")}
    for entry in entries:
        coordinates = launch_coordinates(entry)
        if entry.group not in OP_FIELDS or coordinates is None:
            excluded.append({"artifact": entry.artifact, "reason": "Not a numeric nested operator launch."})
            continue
        if not receipts.allows(entry.segment) or not safe_path(run_dir, entry.artifact).is_file():
            excluded.append({"artifact": entry.artifact,
                             "reason": "Excluded by collection receipt or raw artifact unavailable."})
            continue
        reference = raw_reference(run_dir, entry.artifact)
        scope_names = {name.lower() for name in SCOPE_FIELDS} | _EXTRA_SCOPE
        known = {name.lower(): (name, unit, statistic) for name, (unit, statistic) in OP_FIELDS[entry.group].items()}
        stem = entry.canonical_stem or entry.group
        cohort = _cohort(entry)

        def consume(columns, cells, ordinal):
            if len(set(columns)) != len(columns):
                return
            scope = tuple(sorted(((column, cells[number]) for number, column in enumerate(columns)
                                  if column.lower() in scope_names), key=lambda item: item[0].lower()))
            parsed, local_issues, _ = parse_operator_row_metrics(entry.group, entry.artifact, columns, cells, ordinal)
            issues.extend(issue.model_dump(mode="json") for issue in local_issues)
            parsed_map = {cell.field_key: cell for cell in parsed}
            lower = {column.lower() for column in columns}
            metric_value = {column.lower(): cells[number] for number, column in enumerate(columns)}
            available = lower & set(known)
            if "unit" not in lower and "units" not in lower and {"metric", "value"} <= lower:
                available |= {metric_value["metric"].lower()} & set(known)
            elif requested and not {"metric", "value"} <= lower:
                # An explicitly requested wide field can be absent in one
                # launch. Keep the row scope and expose that absence.
                available |= requested & set(known)
            for field in sorted(available & requested if requested else available):
                name, unit, statistic = known[field]
                key = (cohort, entry.metric_scope, entry.group, stem, name, unit, statistic, scope)
                cell = parsed_map.get(field)
                value = {"artifact": entry.artifact, "record": ordinal,
                         "launch_index": coordinates["launch_index"]}
                if cell is None:
                    indexes = [number for number, column in enumerate(columns) if column.lower() == field]
                    if not indexes and {"metric", "value"} <= lower and metric_value["metric"].lower() == field:
                        indexes = [next(number for number, column in enumerate(columns) if column.lower() == "value")]
                    value["raw_cells"] = [{"raw_token": cells[number],
                        "source": {"artifact": entry.artifact, "field": columns[number],
                                   "record": ordinal, "column": number + 1},
                        "reference": {**reference, "field": columns[number], "record": ordinal, "column": number + 1}}
                        for number in indexes]
                    if any(issue.code == "unsupported_unit_layout" for issue in local_issues):
                        status = "unsupported_layout"
                    elif not indexes:
                        status = "absent_field"
                    elif all(cells[number].strip().lower() in MISSING_TOKENS for number in indexes):
                        status = "missing"
                    else:
                        status = "invalid"
                    value["cell_status"] = status
                    value["reason"] = {
                        "missing": "Recorded empty/NA metric cell; not zero.",
                        "invalid": "Invalid, negative-duration or conflicting metric cell; excluded.",
                        "absent_field": "Requested metric field is absent from this CSV layout.",
                        "unsupported_layout": "Explicit unit-column layout is unsupported by the operator parser.",
                    }[status]
                    value["record_reference"] = {**reference, "record": ordinal}
                    buckets[key][coordinates["launch_index"]].append(value)
                    continue
                source = {"artifact": entry.artifact, "field": columns[cell.value_index],
                          "record": ordinal, "column": cell.value_index + 1}
                value.update(value=cell.value, raw_token=cell.raw_token, source=source, cell_status="valid",
                             reference={**reference, **source})
                if cell.metric_index is not None:
                    value["metric_source"] = {"artifact": entry.artifact, "field": columns[cell.metric_index],
                                              "record": ordinal, "column": cell.metric_index + 1}
                buckets[key][coordinates["launch_index"]].append(value)

        decoded = read_csv(safe_path(run_dir, entry.artifact), entry.artifact, consume)
        issues.extend(issue.model_dump(mode="json") for issue in decoded.issues)
    groups = []
    for key, launches in sorted(buckets.items(), key=lambda item: str(item[0])):
        cohort, metric_scope, family, stem, name, unit, statistic, scope = key
        cells, rejected = [], []
        for number, candidates in sorted(launches.items()):
            if len(candidates) != 1:
                rejected.extend({**candidate, "reason": "Multiple cells for this group and launch; no arbitrary row or artifact selected."}
                                for candidate in candidates)
            elif "value" in candidates[0]:
                cells.extend(candidates)
            else:
                rejected.extend(candidates)
        values = [cell["value"] for cell in cells]
        present = {cell["launch_index"] for cell in cells}
        missing = sorted(set(expected) - present) if expected is not None else None
        raw_cells = [cell for candidates in launches.values() for cell in candidates]
        duplicate_launches = [number for number, candidates in launches.items() if len(candidates) != 1]
        groups.append({**_cohort_dict(cohort), "metric_scope": metric_scope,
            "group": family, "canonical_stem": stem, "metric": name, "unit": unit, "statistic": statistic,
            "scope": [list(pair) for pair in scope], "count": len(values),
            "valid_count": len(values),
            "missing_cell_count": sum(cell["cell_status"] == "missing" for cell in raw_cells),
            "invalid_cell_count": sum(cell["cell_status"] == "invalid" for cell in raw_cells),
            "absent_field_cell_count": sum(cell["cell_status"] == "absent_field" for cell in raw_cells),
            "unsupported_layout_cell_count": sum(cell["cell_status"] == "unsupported_layout" for cell in raw_cells),
            "duplicate_launch_count": len(duplicate_launches),
            "duplicate_cell_count": sum(len(launches[number]) for number in duplicate_launches),
            "missing_launch_count": len(missing) if missing is not None else None,
            "absent_launch_indices": sorted(set(expected) - set(launches)) if expected is not None else None,
            "count_semantics": "valid_count counts retained unique-launch values; cell-status counts describe raw candidates and can overlap duplicate exclusions; missing_launch_count counts expected launches without a retained value.",
            "minimum": min(values) if values else None, "median": median(values) if values else None,
            "maximum": max(values) if values else None, "launch_indices": sorted(present),
            "expected_launch_indices": expected, "missing_launch_indices": missing,
            "complete": expected is not None and not missing and present == set(expected) and cohort not in conflicted_cohorts,
            "ordinal_mapping_conflict": cohort in conflicted_cohorts,
            "cells": cells, "excluded_cells": rejected,
            "aggregation": "descriptive_distribution_across_launches"})
    page = groups[offset:None if limit is None else offset + limit]
    return {"groups": page, "group_count": len(groups), "offset": offset, "limit": limit,
        "next_offset": offset + len(page) if offset + len(page) < len(groups) else None,
        "excluded_artifacts": excluded, "issues": issues, "requested_fields": fields or [],
        "unrecognized_requested_fields": sorted(requested - {field.lower() for family in OP_FIELDS.values() for field in family}),
        "unavailable_requested_fields": sorted(requested - {key[4].lower() for key in buckets}),
        "range_note": "Pagination selects complete aggregation groups, never launch samples; each group covers all matching selected launches.",
        "limitations": LIMITATIONS}
