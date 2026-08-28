"""Raw artifact inventory helpers for Ascend msprof analysis."""
from __future__ import annotations

import csv
import re
from pathlib import Path

from ._profiler_segments import (
    DEFAULT_FOLLOWUP_ACTION_ID,
    app_timeline_segment,
    focused_followup_action_id,
    followup_segment,
    is_supported_followup_action_id,
    metric_scope_for_segment,
    performance_summary_segment,
    segment_receipt_allows_evidence,
    segment_for_relpath,
    stdout_profile_output_segment,
)
from ._profile_target import (
    expected_counts,
    expected_display_names,
    match_expected_name,
    normalize_persisted_target,
    normalize_target_name,
    validate_target_subset,
)
from .ascend_profile_utils import find_files, first_present, normalized_key, read_csv_rows, read_json, rel, summarize_csv, to_float


RAW_ARTIFACT_INDEX_SCHEMA_VERSION = "1.1"
FILE_GROUPS = {
    "op_summary": ["op_summary_*.csv"],
    "op_statistic": ["op_statistic_*.csv"],
    "task_time": ["task_time_*.csv"],
    "api_statistic": ["api_statistic_*.csv"],
    "op_basic_info": ["OpBasicInfo.csv"],
    "pipe_utilization": ["PipeUtilization.csv"],
    "arithmetic_utilization": ["ArithmeticUtilization.csv"],
    "l2_cache": ["L2Cache.csv"],
    "memory": ["Memory.csv", "MemoryL0.csv", "MemoryUB.csv"],
    "resource_conflict": ["ResourceConflictRatio.csv"],
}
SIMULATOR_PATTERNS = ["core*_code_exe.csv", "core*_instr_exe.csv", "trace.json"]
APP_TIMELINE_PATTERNS = ["msprof_*.json"]
UNPARSED_BINARY_PATTERNS = ["visualize_data.bin", "DeviceProf*.bin", "duration.bin"]
OPERATOR_FILE_STEMS = {
    "op_basic_info": ("OpBasicInfo",),
    "pipe_utilization": ("PipeUtilization",),
    "arithmetic_utilization": ("ArithmeticUtilization",),
    "l2_cache": ("L2Cache",),
    "memory": ("Memory", "MemoryL0", "MemoryUB"),
    "resource_conflict": ("ResourceConflictRatio",),
}
OPERATOR_FILENAME_RE = re.compile(r"^(?P<stem>[A-Za-z0-9]+)(?:_(?P<timestamp>[0-9]{17}))?\.csv$")
RAW_NAME_ALIASES = ["op name", "operator name", "kernel name", "kernel_name", "task name", "name"]
RAW_DURATION_ALIASES = ["Task Duration(us)", "task duration(us)", "task duration", "duration"]
METRIC_FAMILY_STEMS = {
    "pipe_utilization": ("PipeUtilization",),
    "arithmetic_utilization": ("ArithmeticUtilization",),
    "l2_cache": ("L2Cache",),
    "memory": ("Memory", "MemoryL0", "MemoryUB"),
    "resource_conflict": ("ResourceConflictRatio",),
}


def operator_file_stem(path: Path, group: str) -> str | None:
    match = OPERATOR_FILENAME_RE.fullmatch(path.name)
    if match is None or match.group("stem") not in OPERATOR_FILE_STEMS.get(group, ()):
        return None
    if not any(part.startswith("OPPROF_") for part in path.parts):
        return None
    return str(match.group("stem"))


def recognized_group_files(run_dir: Path, group: str, patterns: list[str] | None = None) -> list[Path]:
    if group not in OPERATOR_FILE_STEMS:
        return find_files(run_dir, patterns or FILE_GROUPS.get(group, []))
    reports = run_dir / "reports"
    if not reports.exists():
        return []
    return sorted(
        path
        for path in reports.rglob("*.csv")
        if path.is_file() and operator_file_stem(path, group) is not None
    )


def operator_launch_metadata(path: Path, run_dir: Path, segment: str) -> dict:
    rel_path = Path(rel(path, run_dir))
    parts = rel_path.parts
    root_index = next((index for index, part in enumerate(parts) if part.startswith("OPPROF_")), None)
    if root_index is None:
        return {}
    root_path = Path(*parts[: root_index + 1]).as_posix()
    metadata: dict = {"opprof_root": root_path}
    nested = parts[root_index + 1 : -1]
    if len(nested) != 2:
        return metadata
    kernel_dir, launch_dir = nested
    metadata.update(
        {
            "kernel_directory": kernel_dir,
            "launch_directory": launch_dir,
            "launch_ordinal": launch_dir,
            "launch_key": f"{segment}|{root_path}|{kernel_dir}|{launch_dir}",
        }
    )
    return metadata

def annotate_source_metadata(item: dict, rel_path: str, group: str | None, selected_scope: dict | None) -> dict:
    segment = segment_for_relpath(rel_path, group)
    item["segment"] = segment
    item["metric_scope"] = metric_scope_for_segment(segment, selected_scope)
    return item


def collect_group(run_dir: Path, group: str, patterns: list[str], selected_scope: dict | None) -> list[dict]:
    records = []
    for path in recognized_group_files(run_dir, group, patterns):
        try:
            rec = summarize_csv(path)
        except (OSError, UnicodeError, csv.Error) as exc:
            rec = {
                "path": str(path),
                "columns": [],
                "row_count": 0,
                "sample_rows": [],
                "status": "invalid",
                "warnings": [f"invalid csv {rel(path, run_dir)}: {exc}"],
            }
        rec["group"] = group
        annotate_source_metadata(rec, rel(path, run_dir), group, selected_scope)
        if not segment_receipt_allows_evidence(run_dir, rec["segment"]):
            continue
        stem = operator_file_stem(path, group)
        if stem is not None:
            rec["canonical_stem"] = stem
        records.append(rec)
    return records


def empty_raw_artifact_record(
    artifact: str,
    group: str,
    parser: str,
    segment: str,
    metric_scope: str | None,
) -> dict:
    return {
        "artifact": artifact,
        "group": group,
        "parser": parser,
        "segment": segment,
        "metric_scope": metric_scope,
        "status": "empty",
        "columns": [],
        "row_count": 0,
        "sample_rows": [],
        "warnings": [],
    }


def raw_csv_artifact_record(
    path: Path,
    run_dir: Path,
    group: str,
    selected_scope: dict | None,
    segment: str | None = None,
) -> dict:
    rel_path = rel(path, run_dir)
    artifact_segment = segment or segment_for_relpath(rel_path, group)
    record = empty_raw_artifact_record(
        rel_path,
        group,
        "csv",
        artifact_segment,
        metric_scope_for_segment(artifact_segment, selected_scope),
    )
    stem = operator_file_stem(path, group)
    if stem is not None:
        record["canonical_stem"] = stem
        record.update(operator_launch_metadata(path, run_dir, artifact_segment))
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            record["columns"] = list(reader.fieldnames or (list(rows[0].keys()) if rows else []))
            record["row_count"] = len(rows)
            record["sample_rows"] = rows[:5]
            record["status"] = "parsed" if rows else "empty"
            if group == "op_basic_info" and len(rows) == 1:
                raw_name = first_present(rows[0], RAW_NAME_ALIASES)
                if raw_name not in (None, ""):
                    record["target_name"] = str(raw_name)
                    record["normalized_target_name"] = normalize_target_name(raw_name)
                duration = to_float(first_present(rows[0], RAW_DURATION_ALIASES))
                if duration is not None:
                    record["duration_us"] = duration
    except (OSError, UnicodeError, csv.Error) as exc:
        record["status"] = "invalid"
        record["warnings"].append(f"invalid csv {rel_path}: {exc}")
    return record


def propagate_operator_launch_identity(artifacts: list[dict]) -> None:
    by_launch: dict[str, list[dict]] = {}
    for item in artifacts:
        launch_key = item.get("launch_key")
        if launch_key:
            by_launch.setdefault(str(launch_key), []).append(item)
    for records in by_launch.values():
        basic = [item for item in records if item.get("group") == "op_basic_info"]
        valid = [
            item
            for item in basic
            if item.get("status") == "parsed"
            and item.get("row_count") == 1
            and item.get("normalized_target_name")
        ]
        if len(basic) != 1 or len(valid) != 1:
            continue
        identity = valid[0]
        for item in records:
            item["target_name"] = identity.get("target_name")
            item["normalized_target_name"] = identity["normalized_target_name"]


def json_event_rows(data: object) -> list:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ["traceEvents", "events", "data"]:
        events = data.get(key)
        if isinstance(events, list):
            return events
    return []


def raw_json_artifact_record(
    path: Path,
    run_dir: Path,
    group: str,
    selected_scope: dict | None,
    segment: str | None = None,
) -> dict:
    rel_path = rel(path, run_dir)
    artifact_segment = segment or segment_for_relpath(rel_path, group)
    record = empty_raw_artifact_record(
        rel_path,
        group,
        "json",
        artifact_segment,
        metric_scope_for_segment(artifact_segment, selected_scope),
    )
    try:
        events = json_event_rows(read_json(path))
    except (OSError, ValueError) as exc:
        record["status"] = "invalid"
        record["warnings"].append(f"invalid json {rel_path}: {exc}")
        return record
    record["row_count"] = len(events)
    record["sample_rows"] = events[:5]
    record["status"] = "parsed" if events else "empty"
    return record


def unparsed_binary_role(path: Path) -> str:
    name = path.name
    if name == "visualize_data.bin":
        if "simulator" in path.parts:
            return "simulator visualization artifact"
        return "MindStudio visualization artifact"
    if name.startswith("DeviceProf") and name.endswith(".bin"):
        return "internal device profiling dump"
    if name == "duration.bin":
        return "internal raw duration dump"
    if name == "aicore_binary.o":
        return "kernel object binary"
    return "unparsed binary profiler artifact"


def raw_binary_artifact_record(path: Path, run_dir: Path, selected_scope: dict | None) -> dict:
    rel_path = rel(path, run_dir)
    artifact_segment = segment_for_relpath(rel_path, "unparsed_profiler_binary")
    record = empty_raw_artifact_record(
        rel_path,
        "unparsed_profiler_binary",
        "none",
        artifact_segment,
        metric_scope_for_segment(artifact_segment, selected_scope),
    )
    record["status"] = "unparsed"
    record["size_bytes"] = path.stat().st_size
    record["known_role"] = unparsed_binary_role(path)
    record["diagnosis_role"] = "not_used"
    record["notes"] = "Preserved profiler artifact; not parsed and not used for diagnosis."
    return record

def stdout_raw_artifact_records(summary: dict, selected_scope: dict | None) -> list[dict]:
    out = []
    sections = summary.get("stdout_sections", {})
    if not isinstance(sections, dict):
        return out
    for section_name, group in [
        ("occupancy_summary", "stdout_occupancy_summary"),
        ("roofline_summary", "stdout_roofline_summary"),
        ("performance_summary", "stdout_performance_summary"),
    ]:
        value = sections.get(section_name)
        candidates = value if isinstance(value, list) else [value]
        for section in candidates:
            if not isinstance(section, dict):
                continue
            source = str(section.get("source") or "unknown")
            messages = [message for message in section.get("messages", []) if isinstance(message, dict)]
            if section_name == "performance_summary":
                segment = performance_summary_segment(source)
            else:
                segment = stdout_profile_output_segment(Path(source)) or "unknown"
            record = empty_raw_artifact_record(
                source,
                group,
                "stdout",
                segment,
                metric_scope_for_segment(segment, selected_scope),
            )
            record["row_count"] = len(messages)
            record["sample_rows"] = messages[:5]
            record["status"] = "parsed" if messages else "empty"
            out.append(record)
    return out


def build_raw_artifact_index(
    run_dir: Path,
    summary: dict,
    selected_scope: dict | None,
    *,
    stdout_sections: dict | None = None,
) -> dict:
    artifacts = []
    for group, patterns in FILE_GROUPS.items():
        for path in recognized_group_files(run_dir, group, patterns):
            artifacts.append(raw_csv_artifact_record(path, run_dir, group, selected_scope))
    for path in find_files(run_dir, APP_TIMELINE_PATTERNS):
        if path.name.endswith(".result.json"):
            continue
        rel_path = rel(path, run_dir)
        artifacts.append(
            raw_json_artifact_record(
                path,
                run_dir,
                "app_timeline",
                selected_scope,
                segment=app_timeline_segment(rel_path),
            )
        )
    for path in find_files(run_dir, SIMULATOR_PATTERNS):
        if path.suffix.lower() == ".json":
            artifacts.append(
                raw_json_artifact_record(
                    path,
                    run_dir,
                    "simulator_trace",
                    selected_scope,
                    segment="simulator",
                )
            )
        elif path.suffix.lower() == ".csv":
            artifacts.append(
                raw_csv_artifact_record(
                    path,
                    run_dir,
                    "simulator_csv",
                    selected_scope,
                    segment="simulator",
                )
            )
    for path in find_files(run_dir, UNPARSED_BINARY_PATTERNS):
        artifacts.append(raw_binary_artifact_record(path, run_dir, selected_scope))
    stdout_source = (
        {"stdout_sections": stdout_sections}
        if stdout_sections is not None
        else summary
    )
    artifacts.extend(stdout_raw_artifact_records(stdout_source, selected_scope))
    propagate_operator_launch_identity(artifacts)
    artifacts.sort(key=lambda item: (str(item.get("artifact")), str(item.get("group")), str(item.get("parser"))))
    warnings = [
        warning
        for artifact in artifacts
        for warning in artifact.get("warnings", [])
    ]
    return {
        "raw_artifact_index_schema_version": RAW_ARTIFACT_INDEX_SCHEMA_VERSION,
        "artifacts": artifacts,
        "warnings": warnings,
    }


def _record_rows(run_dir: Path, record: dict) -> list[dict[str, str]]:
    artifact = record.get("artifact")
    if not isinstance(artifact, str):
        return []
    try:
        return read_csv_rows(run_dir / artifact)
    except (OSError, UnicodeError, csv.Error):
        return []


def _app_tree(record: dict) -> str | None:
    artifact = Path(str(record.get("artifact") or ""))
    parts = artifact.parts
    for index, part in enumerate(parts):
        if part.startswith("PROF_"):
            return Path(*parts[: index + 1]).as_posix()
    return None


def _coverage_counts(
    observations: list[dict],
    target: dict | None,
    *,
    authority: str,
    authority_complete: bool,
    artifacts: list[str],
    ambiguities: list[str],
) -> dict:
    expected = expected_counts(target)
    display_names = expected_display_names(target)
    observed_counts: dict[str, int] = {}
    duration_by_target: dict[str, float] = {}
    observed_names: dict[str, dict] = {}
    extra_counts: dict[str, int] = {}
    for observation in observations:
        raw_name = str(observation.get("name") or "")
        observed_norm = normalize_target_name(raw_name) or "missing_name"
        matched, rule = match_expected_name(target, raw_name)
        key = matched or observed_norm
        observed_counts[key] = observed_counts.get(key, 0) + 1
        duration = observation.get("duration_us")
        if isinstance(duration, (int, float)):
            duration_by_target[key] = duration_by_target.get(key, 0.0) + float(duration)
        name_record = observed_names.setdefault(
            observed_norm,
            {
                "name": raw_name or "missing",
                "normalized_name": observed_norm,
                "count": 0,
                "match_rule": rule,
                "expected_normalized_name": matched,
                "artifacts": [],
            },
        )
        name_record["count"] += 1
        artifact = observation.get("artifact")
        if artifact and artifact not in name_record["artifacts"]:
            name_record["artifacts"].append(artifact)
        if target is not None and matched is None:
            extra_counts[observed_norm] = extra_counts.get(observed_norm, 0) + 1

    missing_counts = {
        name: count - observed_counts.get(name, 0)
        for name, count in expected.items()
        if observed_counts.get(name, 0) < count
    }
    over_counts = {
        name: observed_counts[name] - count
        for name, count in expected.items()
        if observed_counts.get(name, 0) > count
    }
    explicit = target is not None
    count_complete = (
        authority_complete
        and not missing_counts
        and not over_counts
        and not extra_counts
        and sum(observed_counts.values()) == sum(expected.values())
        if explicit
        else None
    )
    return {
        "counting_authority": authority,
        "authority_complete": authority_complete,
        "expected_total": sum(expected.values()) if explicit else None,
        "expected_counts": expected,
        "expected_display_names": display_names,
        "observed_total": len(observations),
        "observed_counts": observed_counts,
        "observed_names": sorted(observed_names.values(), key=lambda item: item["normalized_name"]),
        "missing_counts": missing_counts,
        "over_counts": over_counts,
        "extra_counts": extra_counts,
        "count_complete": count_complete,
        "completeness": "complete" if count_complete else ("incomplete" if explicit else "unverified"),
        "duration_total_us": sum(duration_by_target.values()),
        "duration_by_target_us": duration_by_target,
        "artifacts": sorted(set(artifacts)),
        "ambiguities": ambiguities,
    }


def _app_coverage(run_dir: Path, raw_artifact_index: dict, target: dict | None) -> dict:
    records = [
        item
        for item in raw_artifact_index.get("artifacts", [])
        if isinstance(item, dict) and item.get("group") == "op_summary" and item.get("segment") == "app"
    ]
    trees = {_app_tree(item) for item in records}
    ambiguities: list[str] = []
    if None in trees:
        ambiguities.append("app op_summary is not inside a recorded PROF_* tree")
    resolved_trees = {tree for tree in trees if tree is not None}
    if len(resolved_trees) != 1:
        ambiguities.append(f"expected one app PROF_* tree, observed {len(resolved_trees)}")
    if len(records) != 1:
        ambiguities.append(f"expected one app op_summary, observed {len(records)}")
    authority_complete = len(resolved_trees) == 1 and len(records) == 1 and not ambiguities
    observations: list[dict] = []
    if authority_complete:
        record = records[0]
        if record.get("status") != "parsed":
            ambiguities.append("authoritative app op_summary did not parse to non-empty rows")
            authority_complete = False
        else:
            for row in _record_rows(run_dir, record):
                observations.append(
                    {
                        "name": first_present(row, RAW_NAME_ALIASES, ""),
                        "duration_us": to_float(first_present(row, RAW_DURATION_ALIASES)),
                        "artifact": record.get("artifact"),
                    }
                )
    return _coverage_counts(
        observations,
        target,
        authority="one parsed row per launch from the single recorded app op_summary_*.csv; Calls ignored",
        authority_complete=authority_complete,
        artifacts=[str(item.get("artifact")) for item in records if item.get("artifact")],
        ambiguities=ambiguities,
    )


def _operator_coverage(
    run_dir: Path,
    raw_artifact_index: dict,
    target: dict | None,
    segment: str,
) -> dict:
    records = [
        item
        for item in raw_artifact_index.get("artifacts", [])
        if isinstance(item, dict)
        and item.get("segment") == segment
        and item.get("group") in OPERATOR_FILE_STEMS
    ]
    roots = {str(item.get("opprof_root")) for item in records if item.get("opprof_root")}
    keys: dict[str, list[dict]] = {}
    unkeyed = [item for item in records if not item.get("launch_key")]
    for item in records:
        key = item.get("launch_key")
        if key:
            keys.setdefault(str(key), []).append(item)
    ambiguities: list[str] = []
    if len(roots) != 1:
        ambiguities.append(f"expected one OPPROF root for {segment}, observed {len(roots)}")
    if unkeyed:
        ambiguities.append(f"{len(unkeyed)} operator artifacts do not have a supported kernel/launch path")
    observations: list[dict] = []
    launch_family_complete: dict[str, dict[str, bool]] = {}
    for key, key_records in sorted(keys.items()):
        basic = [item for item in key_records if item.get("group") == "op_basic_info"]
        valid_basic = [
            item
            for item in basic
            if item.get("status") == "parsed" and item.get("row_count") == 1
        ]
        if len(basic) != 1 or len(valid_basic) != 1:
            ambiguities.append(
                f"launch key {key} requires one parsed one-row OpBasicInfo; observed {len(basic)} files and {len(valid_basic)} valid"
            )
            continue
        basic_record = valid_basic[0]
        rows = _record_rows(run_dir, basic_record)
        if len(rows) != 1:
            ambiguities.append(f"launch key {key} OpBasicInfo row count changed during coverage read")
            continue
        name = first_present(rows[0], RAW_NAME_ALIASES, "")
        observation = {
            "name": name,
            "duration_us": to_float(first_present(rows[0], RAW_DURATION_ALIASES)),
            "artifact": basic_record.get("artifact"),
            "launch_key": key,
        }
        observations.append(observation)
        family_status: dict[str, bool] = {}
        for family, stems in METRIC_FAMILY_STEMS.items():
            stem_complete = []
            for stem in stems:
                matches = [item for item in key_records if item.get("canonical_stem") == stem]
                stem_complete.append(
                    len(matches) == 1
                    and matches[0].get("status") == "parsed"
                    and int(matches[0].get("row_count") or 0) > 0
                )
            family_status[family] = all(stem_complete)
        launch_family_complete[key] = family_status

    authority_complete = bool(keys) and len(roots) == 1 and not unkeyed and not any(
        "OpBasicInfo" in item for item in ambiguities
    )
    coverage = _coverage_counts(
        observations,
        target,
        authority=(
            "one parsed one-row OpBasicInfo per supported launch key: nested "
            "(segment, OPPROF root, kernel directory, launch directory) or "
            "verified flat single-launch (segment, OPPROF root)"
        ),
        authority_complete=authority_complete,
        artifacts=[str(item.get("artifact")) for item in records if item.get("artifact")],
        ambiguities=ambiguities,
    )
    expected = expected_counts(target)
    metric_coverage: dict[str, dict] = {}
    for family in METRIC_FAMILY_STEMS:
        covered_by_target: dict[str, int] = {}
        covered_total = 0
        for observation in observations:
            if not launch_family_complete.get(str(observation["launch_key"]), {}).get(family):
                continue
            covered_total += 1
            matched, _ = match_expected_name(target, observation.get("name"))
            key = matched or normalize_target_name(observation.get("name")) or "missing_name"
            covered_by_target[key] = covered_by_target.get(key, 0) + 1
        by_target = {
            name: {
                "expected": count,
                "covered": covered_by_target.get(name, 0),
                "missing": max(0, count - covered_by_target.get(name, 0)),
            }
            for name, count in expected.items()
        }
        complete = (
            bool(coverage["count_complete"])
            and all(item["missing"] == 0 for item in by_target.values())
            if target is not None
            else None
        )
        metric_coverage[family] = {
            "required_stems": list(METRIC_FAMILY_STEMS[family]),
            "covered_launches": covered_total,
            "expected_launches": sum(expected.values()) if target is not None else None,
            "covered_by_target": covered_by_target,
            "by_target": by_target,
            "complete": complete,
            "completeness": "complete" if complete else ("incomplete" if target is not None else "unverified"),
        }
    coverage["metric_coverage"] = metric_coverage
    return coverage


def _admitted_segment_targets(
    run_dir: Path,
    operator_segments: set[str],
    program_target: dict | None,
) -> dict[str, dict]:
    targets = (
        {"op": program_target}
        if program_target is not None
        and segment_receipt_allows_evidence(run_dir, "op")
        else {}
    )
    path = run_dir / "analysis" / "profile_harness_run.json"
    if not path.is_file():
        workflow = {}
    else:
        try:
            workflow = read_json(path)
        except (OSError, ValueError):
            workflow = {}
    actions = workflow.get("follow_up_actions") if isinstance(workflow, dict) else None
    latest_executions: dict[str, dict] = {}
    if isinstance(actions, list):
        for item in actions:
            if not isinstance(item, dict) or item.get("id") != DEFAULT_FOLLOWUP_ACTION_ID:
                continue
            if item.get("status") not in {"succeeded", "failed", "core_dump", "timeout"}:
                continue
            segment_id = item.get("segment_id") or item.get("id")
            if not is_supported_followup_action_id(segment_id):
                continue
            segment = followup_segment(str(segment_id))
            latest_executions[segment] = item

    canonical_segment = followup_segment(DEFAULT_FOLLOWUP_ACTION_ID)
    canonical_result_succeeded = segment_receipt_allows_evidence(
        run_dir,
        canonical_segment,
    )
    if (
        program_target is not None
        and canonical_segment in operator_segments
        and canonical_segment not in latest_executions
        and canonical_result_succeeded
    ):
        targets[canonical_segment] = program_target

    for segment, item in latest_executions.items():
        if item.get("status") != "succeeded" or not segment_receipt_allows_evidence(
            run_dir,
            segment,
        ):
            continue
        persisted = item.get("target_selection")
        normalized = None
        if persisted is not None:
            if not isinstance(persisted, dict):
                raise ValueError(
                    "analysis/profile_harness_run.json follow_up_actions target_selection is invalid"
                )
            try:
                normalized = normalize_persisted_target(persisted)
            except ValueError as exc:
                raise ValueError(
                    "analysis/profile_harness_run.json follow_up_actions target_selection is invalid"
                ) from exc
            validate_target_subset(program_target, normalized)
        if segment == canonical_segment:
            if program_target is not None and (
                normalized is None
                or (
                    normalized.get("kernel_selector") == program_target.get("kernel_selector")
                    and expected_counts(normalized) == expected_counts(program_target)
                )
            ):
                targets[segment] = program_target
        elif normalized is not None and segment == followup_segment(
            focused_followup_action_id(normalized)
        ):
            targets[segment] = normalized
    return targets


def _segment_target_scope(segment_target: dict | None, program_target: dict | None) -> dict:
    if segment_target is None:
        return {"kind": "observed_run"}
    complete_program = (
        program_target is not None
        and segment_target.get("kernel_selector") == program_target.get("kernel_selector")
        and expected_counts(segment_target) == expected_counts(program_target)
    )
    return {
        "kind": "complete_program" if complete_program else "focused_subset",
        "kernel_selector": segment_target.get("kernel_selector"),
        "expected_counts": expected_counts(segment_target),
        "expected_total": sum(expected_counts(segment_target).values()),
    }


def _normalize_flat_single_launch_identity(
    raw_artifact_index: dict,
    program_target: dict | None,
    segment_targets: dict[str, dict],
) -> None:
    artifacts = raw_artifact_index.get("artifacts", [])
    if not isinstance(artifacts, list):
        return
    for segment, segment_target in segment_targets.items():
        target_scope = _segment_target_scope(segment_target, program_target)
        if target_scope.get("kind") not in {"focused_subset", "complete_program"} or target_scope.get("expected_total") != 1:
            continue
        records = [
            item
            for item in artifacts
            if isinstance(item, dict)
            and item.get("segment") == segment
            and item.get("group") in OPERATOR_FILE_STEMS
        ]
        roots = {str(item.get("opprof_root")) for item in records if item.get("opprof_root")}
        if len(roots) != 1 or any(item.get("launch_key") for item in records):
            continue
        root = next(iter(roots))
        if any(Path(str(item.get("artifact") or "")).parent.as_posix() != root for item in records):
            continue
        basic = [item for item in records if item.get("group") == "op_basic_info"]
        if len(basic) != 1:
            continue
        identity = basic[0]
        if (
            identity.get("status") != "parsed"
            or identity.get("row_count") != 1
            or not identity.get("target_name")
        ):
            continue
        matched, match_rule = match_expected_name(segment_target, identity.get("target_name"))
        if matched is None or match_rule not in {"exact", "known_suffix"}:
            continue
        launch_key = f"{segment}|{root}"
        for item in records:
            item["launch_key"] = launch_key
            item["launch_ordinal"] = "flat"
        propagate_operator_launch_identity(records)


def _attach_segment_target_metadata(coverage: dict, segment_target: dict | None, program_target: dict | None) -> None:
    coverage["target_scope"] = _segment_target_scope(segment_target, program_target)
    if segment_target is None:
        coverage["target_identity"] = {"status": "not_applicable"}
    elif coverage.get("count_complete"):
        coverage["target_identity"] = {"status": "match"}
    elif int(coverage.get("observed_total") or 0) == 0:
        coverage["target_identity"] = {"status": "missing_observed"}
    else:
        coverage["target_identity"] = {"status": "mismatch"}


def _segment_evidence_index(run_dir: Path, raw_artifact_index: dict, segment: str) -> dict:
    if segment_receipt_allows_evidence(run_dir, segment):
        return raw_artifact_index
    return {
        **raw_artifact_index,
        "artifacts": [
            item
            for item in raw_artifact_index.get("artifacts", [])
            if not isinstance(item, dict) or item.get("segment") != segment
        ],
    }


def build_profile_coverage(run_dir: Path, raw_artifact_index: dict, target: dict | None) -> dict:
    operator_segments = sorted(
        {
            str(item.get("segment"))
            for item in raw_artifact_index.get("artifacts", [])
            if isinstance(item, dict)
            and (item.get("segment") == "op" or str(item.get("segment") or "").startswith("followup:"))
            and item.get("group") in OPERATOR_FILE_STEMS
        },
        key=lambda item: (item != "op", item),
    )
    if "op" not in operator_segments:
        operator_segments.insert(0, "op")
    segment_targets = _admitted_segment_targets(run_dir, set(operator_segments), target)
    _normalize_flat_single_launch_identity(raw_artifact_index, target, segment_targets)
    app_coverage = _app_coverage(
        run_dir,
        _segment_evidence_index(run_dir, raw_artifact_index, "app"),
        target,
    )
    _attach_segment_target_metadata(app_coverage, target, target)
    segments: dict[str, dict] = {"app": app_coverage}
    for segment in operator_segments:
        segment_target = segment_targets.get(segment)
        coverage = _operator_coverage(
            run_dir,
            _segment_evidence_index(run_dir, raw_artifact_index, segment),
            segment_target,
            segment,
        )
        _attach_segment_target_metadata(coverage, segment_target, target)
        segments[segment] = coverage

    selected: dict[str, str | None] = {}
    authority_segments = [
        segment
        for segment in operator_segments
        if (segments.get(segment, {}).get("target_scope") or {}).get("kind") == "complete_program"
    ]
    for family in METRIC_FAMILY_STEMS:
        selected[family] = None
        for segment in authority_segments:
            segment_coverage = segments.get(segment)
            family_coverage = (segment_coverage or {}).get("metric_coverage", {}).get(family, {})
            if segment_coverage and segment_coverage.get("count_complete") and family_coverage.get("complete"):
                selected[family] = segment
                break
    expected = expected_counts(target)
    return {
        "schema_version": "1.1",
        "explicit_target": target is not None,
        "kernel_selector": target.get("kernel_selector") if target else None,
        "expected_total": sum(expected.values()) if target is not None else None,
        "expected_counts": expected,
        "segments": segments,
        "selected_segments_by_family": selected,
        "measurement_boundary": (
            "Application and operator segments are separate profiler measurements; their duration totals must not be compared as a direct performance delta."
        ),
    }


def _row_field(row: dict, aliases: tuple[str, ...]) -> tuple[str | None, object]:
    alias_keys = {normalized_key(alias) for alias in aliases}
    for key, value in row.items():
        if normalized_key(str(key)) in alias_keys:
            return str(key), value
    return None, None


def build_frequency_measurement_quality(raw_artifact_index: dict) -> dict:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for index, item in enumerate(raw_artifact_index.get("artifacts", [])):
        if not isinstance(item, dict) or item.get("status") != "parsed" or item.get("group") != "op_basic_info":
            continue
        rows = item.get("sample_rows")
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            continue
        row = rows[0]
        current_field, current_raw = _row_field(row, ("Current Freq", "Current Frequency"))
        rated_field, rated_raw = _row_field(row, ("Rated Freq", "Rated Frequency"))
        current = to_float(current_raw)
        rated = to_float(rated_raw)
        if current is None and rated is None:
            continue
        segment = str(item.get("segment") or "unknown")
        target = str(
            item.get("normalized_target_name")
            or item.get("target_name")
            or first_present(row, RAW_NAME_ALIASES, "unknown")
        )
        grouped.setdefault((segment, target), []).append(
            {
                "artifact": item.get("artifact"),
                "launch_key": item.get("launch_key"),
                "current_frequency_mhz": current,
                "rated_frequency_mhz": rated,
                "current_frequency_field_ref": (
                    f"artifacts[{index}].sample_rows[0].{current_field}" if current_field else None
                ),
                "rated_frequency_field_ref": (
                    f"artifacts[{index}].sample_rows[0].{rated_field}" if rated_field else None
                ),
            }
        )

    groups = []
    warnings = []
    for (segment, target), observations in sorted(grouped.items()):
        current_values = sorted(
            {item["current_frequency_mhz"] for item in observations if item["current_frequency_mhz"] is not None}
        )
        rated_values = sorted(
            {item["rated_frequency_mhz"] for item in observations if item["rated_frequency_mhz"] is not None}
        )
        below_rated = sum(
            1
            for item in observations
            if item["current_frequency_mhz"] is not None
            and item["rated_frequency_mhz"] is not None
            and item["current_frequency_mhz"] < item["rated_frequency_mhz"]
        )
        mixed = len(current_values) > 1
        group = {
            "segment": segment,
            "target": target,
            "launch_count": len(observations),
            "current_frequencies_mhz": current_values,
            "rated_frequencies_mhz": rated_values,
            "below_rated_launch_count": below_rated,
            "mixed_frequency": mixed,
            "observations": observations,
        }
        groups.append(group)
        if below_rated or mixed:
            warnings.append(
                "measurement quality: frequency variation observed for "
                f"segment={segment} target={target}; below_rated_launch_count={below_rated}, "
                f"mixed_frequency={str(mixed).lower()}"
            )
    return {
        "status": "observed" if groups else "not_available",
        "groups": groups,
        "warnings": warnings,
        "evidence_role": "measurement_quality_context_only",
    }
