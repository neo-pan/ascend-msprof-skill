"""Build analysis artifacts from Ascend msprof / msprof op output."""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._evidence_artifacts import (
    FILE_GROUPS,
    build_raw_artifact_index,
    collect_group,
)
from ._evidence_relations import build_evidence_relations
from ._evidence_signals import (
    OP_METRIC_GROUPS,
    READINESS_LEVEL_ORDER,
    TIMING_GROUPS,
    build_analysis_dimensions,
    direction_evidence,
    first_signal,
    first_signal_with_value,
    first_timing_signal,
    headline_for_group,
    independent_on_device_signal,
    op_basic_launch_metadata_signals,
    op_basic_tiling_signal,
    performance_summary_signals,
    signals_with_values_for_groups,
)
from .ascend_profile_utils import (
    analysis_dir,
    first_present,
    normalized_key,
    read_json,
    rel,
    to_float,
    write_json,
)
from .metric_scope_policy import (
    APP_TIMING_ARTIFACTS,
    APP_TIMING_CONTRACT,
    command_metric_scope,
    is_msprof_op_command,
    metric_scope_policy,
    missing_artifact_labels,
    normalize_metric_scope,
    warning_group,
)
from .simulator_hotspot_model import write_simulator_hotspot_model


ANALYSIS_SCHEMA_VERSION = "1.3"

TARGET_NAME_FIELDS = [
    "expected_kernel_names",
    "expected_op_names",
    "target_kernel_names",
    "target_op_names",
    "expected_kernel_name",
    "expected_op_name",
    "target_kernel_name",
    "target_op_name",
]
TILELANG_CONTEXT_FIELDS = {
    "task_framework",
    "task_language",
    "framework",
    "language",
}
TILELANG_DEFAULT_EXPECTED_KERNEL = "main_kernel"
TARGET_NAME_SUFFIXES = ("mixaic", "aic", "aiv", "cube", "vector")
OCCUPANCY_SECTION_NAME = "Occupancy Summary Report"
OCCUPANCY_SECTION_START_RE = re.compile(r"^.*\[INFO\]\s+Occupancy Summary Report:\s*$")
ROOFLINE_SECTION_NAME = "RoofLine Summary Report"
ROOFLINE_SECTION_START_RE = re.compile(r"^.*\[INFO\]\s+RoofLine Summary Report:\s*$")
PERFORMANCE_SECTION_NAME = "Performance Summary Report"
PERFORMANCE_SECTION_START_RE = re.compile(r"^.*\[INFO\]\s+Performance Summary Report:\s*$")
REPORT_SECTION_HEADER_RE = re.compile(r"^.*\[INFO\]\s+\S.* Report:\s*$")
CANN_INFO_HEADER_RE = re.compile(r"^.*\[(?:INFO|WARN|ERROR)\]\s+\S.*:\s*$")
OCCUPANCY_MESSAGE_RE = re.compile(r"^\s*(?P<ordinal>[0-9]+)\)\s+(?P<message>.+\S)\s*$")
AUXILIARY_STDOUT_MARKERS = ["help", "export", "validation", "malformed"]


def is_auxiliary_stdout_log(path: Path) -> bool:
    stem = path.stem.lower()
    return any(marker in stem for marker in AUXILIARY_STDOUT_MARKERS)


def selected_profiler_stdout_paths(run_dir: Path, preferred_patterns: list[str] | None = None) -> list[Path]:
    logs_dir = run_dir / "logs"
    if not logs_dir.exists():
        return []
    if preferred_patterns is None:
        preferred_patterns = ["msprof_occupancy*.stdout"]

    paths = [path for path in logs_dir.glob("*.stdout") if path.is_file()]
    paths_by_name = {path.name: path for path in paths}
    selected: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path | None) -> None:
        if path is None or path in seen or is_auxiliary_stdout_log(path):
            return
        selected.append(path)
        seen.add(path)

    for pattern in preferred_patterns:
        for path in sorted(logs_dir.glob(pattern)):
            add(path)
    add(paths_by_name.get("msprof_default.stdout"))
    add(paths_by_name.get("command_msprof.stdout"))
    for path in sorted(logs_dir.glob("msprof*.stdout")):
        add(path)
    return selected


def selected_roofline_stdout_paths(run_dir: Path) -> list[Path]:
    return selected_profiler_stdout_paths(run_dir, ["msprof_roofline*.stdout"])


def selected_performance_stdout_paths(run_dir: Path) -> list[Path]:
    return selected_profiler_stdout_paths(run_dir, ["msprof_op*.stdout"])


def selected_metric_scope(run_dir: Path) -> dict | None:
    for name in ["command_msprof_op.txt", "command_msprof.txt"]:
        path = run_dir / "logs" / name
        if not path.exists():
            continue
        command = path.read_text(encoding="utf-8", errors="replace")
        if name == "command_msprof.txt" and not is_msprof_op_command(command):
            continue
        scope = command_metric_scope(command)
        if scope:
            normalized = normalize_metric_scope(scope)
            policy = metric_scope_policy(normalized)
            out = {
                "value": normalized,
                "artifact": f"logs/{name}",
                "field_ref": "--aic-metrics",
                "known": policy is not None,
            }
            if policy:
                out["policy"] = policy.as_dict()
            return out
    return None


def normalize_target_name(value: object) -> str:
    return normalized_key(str(value))


def target_name_matches(expected: str, observed: str) -> bool:
    expected_norm = normalize_target_name(expected)
    observed_norm = normalize_target_name(observed)
    if not expected_norm or not observed_norm:
        return False
    if expected_norm == observed_norm:
        return True
    if not observed_norm.startswith(expected_norm):
        return False
    suffix = observed_norm[len(expected_norm):]
    return suffix in TARGET_NAME_SUFFIXES


def target_identity_match_rule(expected: str, observed: str) -> str:
    expected_norm = normalize_target_name(expected)
    observed_norm = normalize_target_name(observed)
    if not expected_norm or not observed_norm:
        return "unmatched"
    if expected_norm == observed_norm:
        return "exact"
    if observed_norm.startswith(expected_norm):
        suffix = observed_norm[len(expected_norm):]
        if suffix in TARGET_NAME_SUFFIXES:
            return "known_suffix"
    return "unmatched"


def target_identity_confidence(identity: dict) -> str:
    status = identity.get("status")
    if status in {"mismatch", "partial_mismatch", "missing_observed"}:
        return "blocked"
    if status == "unverified":
        return "low"
    if status == "match":
        rules = [
            item.get("match_rule")
            for item in identity.get("observed", [])
            if isinstance(item, dict) and item.get("status") == "match"
        ]
        names = {
            normalize_target_name(str(item.get("name")))
            for item in identity.get("observed", [])
            if isinstance(item, dict) and item.get("status") == "match" and item.get("name")
        }
        if rules and all(rule == "exact" for rule in rules):
            return "high" if len(names) <= 1 else "medium"
        if rules and all(rule in {"exact", "known_suffix"} for rule in rules):
            return "medium"
    return "blocked"


def target_names_from_value(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "", [])]
    return []


def first_target_names(value: object, field_path: list[str]) -> tuple[list[str], str | None]:
    if isinstance(value, dict):
        for field in TARGET_NAME_FIELDS:
            item = value.get(field)
            names = target_names_from_value(item)
            if names:
                return names, ".".join([*field_path, field])
        for key in ["target", "kernel", "operator", "metadata", "jit_config", "profile_harness", "benchmark"]:
            item = value.get(key)
            found, ref = first_target_names(item, [*field_path, key])
            if found:
                return found, ref
    return [], None


def context_mentions_tilelang(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in TILELANG_CONTEXT_FIELDS and "tilelang" in str(item).lower():
                return True
            if context_mentions_tilelang(item):
                return True
    elif isinstance(value, list):
        return any(context_mentions_tilelang(item) for item in value)
    return False


def expected_target_from_context(run_dir: Path) -> dict | None:
    tilelang_default: dict | None = None
    for name in ["profile_context.json", "tilelang_context.json"]:
        path = run_dir / "analysis" / name
        if not path.is_file():
            continue
        try:
            payload = read_json(path)
        except (OSError, ValueError):
            continue
        targets, field_ref = first_target_names(payload, [])
        if targets:
            return {
                "names": targets,
                "artifact": f"analysis/{name}",
                "field_ref": field_ref,
            }
        if tilelang_default is None and context_mentions_tilelang(payload):
            tilelang_default = {
                "names": [TILELANG_DEFAULT_EXPECTED_KERNEL],
                "artifact": f"analysis/{name}",
                "field_ref": "inferred:tilelang_default_kernel",
                "inferred": True,
            }
    return tilelang_default


def observed_target_records(summary: dict) -> list[dict]:
    records = []
    for group in ["op_basic_info", "op_summary", "op_statistic", "task_time"]:
        item = (summary.get("headlines") or {}).get(group)
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if name in (None, "", "n/a"):
            continue
        records.append(
            {
                "group": group,
                "name": str(name),
                "artifact": item.get("file"),
                "field_ref": f"headlines.{group}.name",
            }
        )
    return records


def build_target_identity(run_dir: Path, summary: dict) -> dict:
    expected = expected_target_from_context(run_dir)
    observed = observed_target_records(summary)
    if expected is None:
        status = "unverified" if observed else "missing"
    elif not observed:
        status = "missing_observed"
    else:
        expected_names = [str(name) for name in expected.get("names", [])]
        for item in observed:
            match_rule = "unmatched"
            for expected_name in expected_names:
                rule = target_identity_match_rule(expected_name, str(item["name"]))
                if rule == "exact":
                    match_rule = rule
                    break
                if rule == "known_suffix":
                    match_rule = rule
            item["status"] = (
                "match"
                if match_rule in {"exact", "known_suffix"}
                else "mismatch"
            )
            item["match_rule"] = match_rule
        mismatches = [item for item in observed if item.get("status") == "mismatch"]
        if not mismatches:
            status = "match"
        elif len(mismatches) == len(observed):
            status = "mismatch"
        else:
            status = "partial_mismatch"
    identity = {
        "status": status,
        "expected": expected,
        "observed": observed,
    }
    identity["confidence"] = target_identity_confidence(identity)
    return identity


def target_identity_warnings(identity: dict) -> list[str]:
    expected = identity.get("expected")
    if not isinstance(expected, dict):
        return []
    expected_names = ", ".join(str(item) for item in expected.get("names", []))
    if identity.get("status") in {"mismatch", "partial_mismatch"}:
        mismatched_names = ", ".join(
            str(item.get("name")) for item in identity.get("observed", []) if item.get("status") != "match"
        )
        return [f"target identity {identity.get('status')}: expected {expected_names}; observed {mismatched_names or 'none'}"]
    if identity.get("status") == "missing_observed":
        return [f"target identity missing observed profiler operator: expected {expected_names}"]
    return []


def parse_occupancy_summary_text(text: str, source: str) -> dict | None:
    messages = []
    in_section = False
    for line in text.splitlines():
        if not in_section:
            if OCCUPANCY_SECTION_START_RE.match(line):
                in_section = True
            continue
        if REPORT_SECTION_HEADER_RE.match(line):
            break
        match = OCCUPANCY_MESSAGE_RE.match(line)
        if match:
            messages.append(
                {
                    "ordinal": int(match.group("ordinal")),
                    "message": match.group("message"),
                }
            )
    if not messages:
        return None
    return {
        "source": source,
        "section": OCCUPANCY_SECTION_NAME,
        "messages": messages,
    }


def parse_occupancy_summary_stdout(run_dir: Path) -> dict | None:
    for path in selected_profiler_stdout_paths(run_dir):
        section = parse_occupancy_summary_text(
            path.read_text(encoding="utf-8", errors="replace"),
            rel(path, run_dir),
        )
        if section:
            return section
    return None


def parse_roofline_summary_text(text: str, source: str) -> dict | None:
    messages = []
    in_section = False
    for line in text.splitlines():
        if not in_section:
            if ROOFLINE_SECTION_START_RE.match(line):
                in_section = True
            continue
        if REPORT_SECTION_HEADER_RE.match(line):
            break
        message = line.strip()
        if message:
            messages.append({"message": message})
    if not messages:
        return None
    return {
        "source": source,
        "section": ROOFLINE_SECTION_NAME,
        "messages": messages,
    }


def parse_roofline_summary_stdout(run_dir: Path) -> dict | None:
    for path in selected_roofline_stdout_paths(run_dir):
        section = parse_roofline_summary_text(
            path.read_text(encoding="utf-8", errors="replace"),
            rel(path, run_dir),
        )
        if section:
            return section
    return None


def parse_performance_summary_text(text: str, source: str) -> dict | None:
    messages = []
    in_section = False
    for line in text.splitlines():
        if not in_section:
            if PERFORMANCE_SECTION_START_RE.match(line):
                in_section = True
            continue
        if REPORT_SECTION_HEADER_RE.match(line) or CANN_INFO_HEADER_RE.match(line):
            break
        match = OCCUPANCY_MESSAGE_RE.match(line)
        if match:
            messages.append(
                {
                    "ordinal": int(match.group("ordinal")),
                    "message": match.group("message"),
                    "source": source,
                }
            )
    if not messages:
        return None
    return {
        "source": source,
        "section": PERFORMANCE_SECTION_NAME,
        "messages": messages,
    }


def parse_performance_summary_stdout(run_dir: Path) -> dict | None:
    for path in selected_performance_stdout_paths(run_dir):
        section = parse_performance_summary_text(
            path.read_text(encoding="utf-8", errors="replace"),
            rel(path, run_dir),
        )
        if section:
            return section
    return None


def md_table_cell(value: object) -> str:
    return "" if value is None else str(value).replace("|", "\\|").replace("\n", " ")


def direction(
    direction_id: str,
    title: str,
    action: str,
    signals: list[dict],
    score: tuple[int, int, int],
    confidence: str,
    effort: str,
    impact_basis: str,
) -> dict:
    evidence = direction_evidence(signals)
    return {
        "id": direction_id,
        "title": title,
        "action": action,
        "evidence": evidence,
        "requires_artifacts": sorted(
            {
                str(item.get("artifact"))
                for item in evidence
                if item.get("artifact") not in (None, "", "missing")
            }
        ),
        "missing_artifacts": [],
        "confidence": confidence,
        "effort": effort,
        "impact_basis": impact_basis,
        "score": list(score),
    }


EXPERIMENT_HINTS = {
    "focus_hot_path": {
        "inspect_code_area": (
            "Profiled operator, task, or host/runtime path named by the timing evidence."
        ),
        "next_experiment": (
            "Collect the missing operator-level metric family before changing kernel code, "
            "or isolate the hot operator with a standalone harness."
        ),
        "expected_profiler_change": (
            "A useful follow-up should preserve the same hot target while adding pipe, "
            "arithmetic, memory/cache, conflict, or simulator evidence."
        ),
        "recollect_artifacts": [
            "op_summary_*.csv",
            "task_time_*.csv",
            "OpBasicInfo.csv",
            "PipeUtilization.csv",
        ],
        "caveats": [
            "Timing-only evidence ranks what to inspect next; it does not justify a concrete kernel change.",
        ],
    },
    "inspect_pipe_arithmetic_mix": {
        "inspect_code_area": (
            "Compute loop, vector/cube/scalar work split, epilogue, and instruction mix around the timed kernel path."
        ),
        "next_experiment": (
            "Change one compute-path or pipe-balance variable at a time, keeping workload and launch metadata fixed."
        ),
        "expected_profiler_change": (
            "If the experiment is useful, duration should decrease and the relevant "
            "PipeUtilization.csv / ArithmeticUtilization.csv ratio or time fields should move consistently "
            "with the intended path."
        ),
        "recollect_artifacts": [
            "task_time_*.csv",
            "op_summary_*.csv",
            "PipeUtilization.csv",
            "ArithmeticUtilization.csv",
            "OpBasicInfo.csv",
        ],
        "caveats": [
            "This is an experiment hint, not a code-change instruction.",
        ],
    },
    "inspect_pipe_utilization_advisory": {
        "inspect_code_area": (
            "Launch metadata, blockDim/mix blockDim, and pipe usage around the timed kernel path."
        ),
        "next_experiment": (
            "Validate the stdout message against CSV evidence, then change one launch or path-mix "
            "variable at a time only if the CSV evidence stays aligned."
        ),
        "expected_profiler_change": (
            "If the experiment is useful, duration and the cited pipe CSV fields should improve; "
            "stdout wording alone is not enough."
        ),
        "recollect_artifacts": [
            "task_time_*.csv",
            "op_summary_*.csv",
            "PipeUtilization.csv",
            "OpBasicInfo.csv",
            "profiler stdout log",
        ],
        "caveats": [
            "Treat stdout performance-summary messages as corroborating context, not an independent diagnosis source.",
            "This is an experiment hint, not a code-change instruction.",
        ],
    },
    "inspect_memory_movement": {
        "inspect_code_area": (
            "DataCopy granularity, GM/UB movement, UB/L0 buffering, tile reuse, queue depth, "
            "and double-buffering around the timed path."
        ),
        "next_experiment": (
            "Change one memory-movement variable at a time, such as tile shape, copy granularity, "
            "buffering strategy, or reuse pattern."
        ),
        "expected_profiler_change": (
            "If the experiment is useful, duration should decrease and memory/cache fields should move "
            "consistently with pipe/MTE evidence."
        ),
        "recollect_artifacts": [
            "task_time_*.csv",
            "op_summary_*.csv",
            "PipeUtilization.csv",
            "Memory.csv",
            "MemoryL0.csv",
            "MemoryUB.csv",
            "L2Cache.csv",
            "OpBasicInfo.csv",
        ],
        "caveats": [
            "This is an experiment hint, not a code-change instruction.",
        ],
    },
    "inspect_resource_conflict": {
        "inspect_code_area": (
            "UB layout, alignment, queue schedule, resource sharing, and synchronization/control path "
            "near the timed kernel path."
        ),
        "next_experiment": (
            "Change one layout, alignment, queue, or schedule variable at a time and compare conflict "
            "ratios with timing."
        ),
        "expected_profiler_change": (
            "If the experiment is useful, duration should decrease and ResourceConflictRatio.csv fields "
            "should improve without regressing pipe or memory evidence."
        ),
        "recollect_artifacts": [
            "task_time_*.csv",
            "op_summary_*.csv",
            "ResourceConflictRatio.csv",
            "PipeUtilization.csv",
            "ArithmeticUtilization.csv",
            "OpBasicInfo.csv",
        ],
        "caveats": [
            "This is an experiment hint, not a code-change instruction.",
        ],
    },
    "inspect_tiling_core_balance": {
        "inspect_code_area": (
            "Tiling calculation, blockDim/mix blockDim, tail handling, per-core workload partitioning, "
            "and shape specialization."
        ),
        "next_experiment": (
            "Change one tiling or work-distribution variable at a time while keeping the same workload "
            "and correctness contract."
        ),
        "expected_profiler_change": (
            "If the experiment is useful, duration should decrease and simulator per-core/source context "
            "or task timing should show a more favorable distribution for the same target."
        ),
        "recollect_artifacts": [
            "task_time_*.csv",
            "op_summary_*.csv",
            "OpBasicInfo.csv",
            "trace.json",
            "core*_code_exe.csv",
            "core*_instr_exe.csv",
        ],
        "caveats": [
            "This is an experiment hint, not a code-change instruction.",
        ],
    },
}


def base_recollect_artifacts(direction_id: str, summary: dict) -> list[str]:
    template = EXPERIMENT_HINTS.get(direction_id)
    if not template:
        return []
    artifacts = list(template.get("recollect_artifacts") or [])
    if direction_id == "focus_hot_path":
        for action in summary.get("next_collection_actions") or []:
            if isinstance(action, dict):
                artifacts.extend(str(item) for item in action.get("required_artifacts") or [])
    out = []
    seen = set()
    for artifact in artifacts:
        if artifact in seen:
            continue
        seen.add(artifact)
        out.append(artifact)
    return out


def experiment_caveats(direction_id: str) -> list[str]:
    template = EXPERIMENT_HINTS.get(direction_id)
    if not template:
        return []
    return list(template.get("caveats") or [])


def evidence_text(evidence_items: list[dict]) -> str:
    return repr(evidence_items).lower()


def has_timing_evidence(evidence_items: list[dict]) -> bool:
    text = evidence_text(evidence_items)
    return any(
        token in text
        for token in [
            "opsummary",
            "opstatistic",
            "tasktime",
            "task duration",
            "duration_or_time",
        ]
    )


def has_relevant_source_context_evidence(direction_id: str, evidence_items: list[dict]) -> bool:
    text = evidence_text(evidence_items)
    if direction_id == "inspect_pipe_arithmetic_mix":
        return "pipeutilization" in text and "arithmeticutilization" in text
    if direction_id == "inspect_pipe_utilization_advisory":
        return "pipeutilization" in text
    if direction_id == "inspect_memory_movement":
        return "pipeutilization" in text and any(token in text for token in ["memory", "l2cache"])
    if direction_id == "inspect_resource_conflict":
        return "resourceconflict" in text
    if direction_id == "inspect_tiling_core_balance":
        return "opbasicinfo" in text and "simulator" in text
    return False


SOURCE_CONTEXT_ORDER = {
    "inspect_pipe_arithmetic_mix": ["instructions", "pipeline_events", "source_lines"],
    "inspect_pipe_utilization_advisory": ["instructions", "pipeline_events", "source_lines"],
    "inspect_memory_movement": ["source_lines", "instructions", "pipeline_events"],
    "inspect_resource_conflict": ["source_lines", "instructions", "pipeline_events"],
    "inspect_tiling_core_balance": ["source_lines", "pipeline_events", "instructions"],
}


SOURCE_CONTEXT_ROLES = {
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


def source_context_hints(summary: dict, direction_id: str, evidence_items: list[dict], limit: int = 3) -> list[dict]:
    if not has_timing_evidence(evidence_items):
        return []
    if not has_relevant_source_context_evidence(direction_id, evidence_items):
        return []
    model = summary.get("_simulator_hotspot_model")
    if not isinstance(model, dict):
        return []
    out = []
    for group in SOURCE_CONTEXT_ORDER.get(direction_id, []):
        rows = model.get(group)
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            item = {
                "artifact": "analysis/simulator_hotspots.json",
                "field_ref": f"{group}[{index}]",
                "role": SOURCE_CONTEXT_ROLES[group],
            }
            signal = source_context_signal(row)
            if signal not in (None, ""):
                item["signal"] = signal
            value = source_context_value(row)
            if value not in (None, ""):
                item["value"] = value
            out.append(item)
            if len(out) >= limit:
                return out
    return out


def experiment_hint_for_direction(direction_id: str, summary: dict, evidence_items: list[dict]) -> dict | None:
    template = EXPERIMENT_HINTS.get(direction_id)
    if not template or not evidence_items:
        return None
    hint = {
        "inspect_code_area": template["inspect_code_area"],
        "next_experiment": template["next_experiment"],
        "expected_profiler_change": template["expected_profiler_change"],
        "recollect_artifacts": base_recollect_artifacts(direction_id, summary),
        "caveats": experiment_caveats(direction_id),
    }
    source_context = source_context_hints(summary, direction_id, evidence_items)
    if source_context:
        hint["source_context"] = source_context
    return hint


def build_optimization_directions(summary: dict) -> list[dict]:
    target_identity = summary.get("target_identity")
    if isinstance(target_identity, dict) and target_identity.get("status") in {
        "mismatch",
        "partial_mismatch",
        "missing_observed",
    }:
        return []

    dimensions = summary.get("analysis_dimensions", [])
    timing = first_timing_signal(dimensions)
    pipe = first_signal_with_value(dimensions, ["pipe_utilization"])
    arithmetic = first_signal_with_value(dimensions, ["arithmetic_utilization"])
    memory = first_signal_with_value(dimensions, ["memory"])
    l2_cache = first_signal_with_value(dimensions, ["l2_cache"])
    memory_or_cache = memory or l2_cache
    conflict = first_signal_with_value(dimensions, ["resource_conflict"])
    op_basic = first_signal(dimensions, ["op_basic_info"])
    simulator = first_signal_with_value(dimensions, ["simulator"])
    on_device_corroboration = independent_on_device_signal(dimensions)
    performance_messages = performance_summary_signals(summary)

    if not timing:
        return []

    directions = [
        direction(
            "focus_hot_path",
            "Focus Hot Path Inspection",
            "Use the top timing evidence to choose the next profiling target before changing kernel code.",
            [timing],
            (10, 0, 0),
            "low",
            "low",
            "Timing evidence is available without enough corroborating metric families for a concrete code direction.",
        )
    ]

    pipe_arithmetic = signals_with_values_for_groups(dimensions, ["pipe_utilization", "arithmetic_utilization"])
    if pipe and arithmetic:
        directions.append(
            direction(
                "inspect_pipe_arithmetic_mix",
                "Inspect Pipe And Arithmetic Mix",
                "Inspect whether the dominant pipe and arithmetic mix match the intended Ascend C execution path before changing tiling or compute code.",
                [timing, *pipe_arithmetic],
                (70, len(pipe_arithmetic), 1),
                "medium",
                "medium",
                "Timing evidence is corroborated by PipeUtilization and ArithmeticUtilization signals.",
            )
        )

    if pipe and performance_messages:
        launch_metadata = op_basic_launch_metadata_signals(summary)
        directions.append(
            direction(
                "inspect_pipe_utilization_advisory",
                "Inspect Pipe Utilization Advisory",
                "Inspect CANN performance summary messages with PipeUtilization.csv and launch metadata before changing kernel code.",
                [timing, pipe, *performance_messages, *launch_metadata],
                (68, 1 + len(performance_messages), 1),
                "medium",
                "medium",
                "Timing evidence is corroborated by PipeUtilization.csv and CANN performance summary stdout messages.",
            )
        )

    memory_signals = signals_with_values_for_groups(dimensions, ["pipe_utilization", "memory", "l2_cache"])
    if pipe and memory_or_cache:
        directions.append(
            direction(
                "inspect_memory_movement",
                "Inspect Memory And Data Movement",
                "Inspect GM/UB/L0 movement and DataCopy feeding around the timed path before changing buffering or tile reuse.",
                [timing, *memory_signals],
                (65, len(memory_signals), 1),
                "medium",
                "medium",
                "Timing evidence is corroborated by pipe and memory/cache movement signals.",
            )
        )

    conflict_signals = signals_with_values_for_groups(
        dimensions,
        ["resource_conflict", "pipe_utilization", "arithmetic_utilization", "simulator"],
    )
    if conflict and (pipe or arithmetic or simulator):
        conflict_impact_basis = (
            "Timing evidence is corroborated by ResourceConflictRatio and another operator-level metric family."
            if pipe or arithmetic
            else "Timing evidence is corroborated by ResourceConflictRatio and simulator source/pipeline context."
        )
        directions.append(
            direction(
                "inspect_resource_conflict",
                "Inspect UB Or Resource Conflict",
                "Inspect UB layout, queue schedule, and conflicting resource usage around the timed path before changing kernel structure.",
                [timing, *conflict_signals],
                (60, len(conflict_signals), 1),
                "medium",
                "medium",
                conflict_impact_basis,
            )
        )

    tiling_signal = op_basic_tiling_signal(op_basic)
    balance_signals = [signal for signal in [tiling_signal, on_device_corroboration, simulator] if signal]
    if tiling_signal and simulator and on_device_corroboration:
        directions.append(
            direction(
                "inspect_tiling_core_balance",
                "Inspect Tiling And Core Balance",
                "Inspect blockDim, per-core simulator timing, and workload shape before changing work distribution.",
                [timing, *balance_signals],
                (55, len(balance_signals), 1),
                "medium",
                "high",
                "Timing evidence is corroborated by operator metadata and simulator context.",
            )
        )

    directions.sort(key=lambda item: (-item["score"][0], -item["score"][1], -item["score"][2], item["id"]))
    for index, item in enumerate(directions[:3], start=1):
        item["rank"] = index
        item.pop("score", None)
        hint = experiment_hint_for_direction(item["id"], summary, item.get("evidence") or [])
        if hint:
            item["experiment_hint"] = hint
    return directions[:3]


def missing_groups_from_warnings(summary: dict) -> set[str]:
    groups = set()
    for warning in summary.get("warnings", []):
        group = warning_group(str(warning))
        if group:
            groups.add(group)
    return groups


def scope_evidence(scope: dict) -> list[dict]:
    return [
        {
            "evidence_id": "ev_01_metric_scope",
            "artifact": scope.get("artifact"),
            "field": scope.get("field_ref"),
            "field_ref": scope.get("field_ref"),
            "signal": f"--aic-metrics={scope.get('value')}",
            "value": scope.get("value"),
        }
    ]


def missing_warning_evidence(summary: dict, groups: list[str], start_index: int = 2) -> list[dict]:
    evidence = []
    warnings = [str(warning) for warning in summary.get("warnings", [])]
    for group in groups:
        prefix = f"missing {group}:"
        warning = next((item for item in warnings if item.startswith(prefix)), None)
        if not warning:
            continue
        evidence.append(
            {
                "evidence_id": f"ev_{start_index + len(evidence):02d}_missing_{normalized_key(group)}",
                "artifact": "analysis/summary.json",
                "field": "warnings",
                "field_ref": f"warnings[] startswith {prefix}",
                "signal": warning,
                "value": None,
            }
        )
    return evidence


def missing_stdout_evidence(summary: dict, sections: tuple[str, ...], start_index: int = 2) -> list[dict]:
    evidence = []
    stdout_sections = summary.get("stdout_sections", {})
    if not isinstance(stdout_sections, dict):
        stdout_sections = {}
    for section in sections:
        if stdout_sections.get(section):
            continue
        evidence.append(
            {
                "evidence_id": f"ev_{start_index + len(evidence):02d}_missing_{normalized_key(section)}",
                "artifact": "analysis/summary.json",
                "field": f"stdout_sections.{section}",
                "field_ref": f"stdout_sections.{section}",
                "signal": f"missing stdout section {section}",
                "value": None,
            }
        )
    return evidence


def collect_action(
    action_id: str,
    reason: str,
    recommended_aic_metrics: list[str],
    required_groups: list[str],
    evidence: list[dict],
    confidence: str,
) -> dict:
    return {
        "id": action_id,
        "reason": reason,
        "recommended_aic_metrics": recommended_aic_metrics,
        "required_artifacts": missing_artifact_labels(required_groups),
        "evidence": evidence,
        "confidence": confidence,
    }


def build_next_collection_actions(summary: dict) -> list[dict]:
    scope = summary.get("metric_scope")
    if not isinstance(scope, dict):
        return []
    policy = metric_scope_policy(scope.get("value"))
    if not policy:
        return []

    missing_groups = missing_groups_from_warnings(summary)
    actions = []
    required_missing = [group for group in policy.required_artifacts if group in missing_groups]
    required_stdout_missing = []
    if policy.scope in {"Occupancy", "Roofline"}:
        required_stdout_missing = [
            section
            for section in policy.stdout_sections
            if not summary.get("stdout_sections", {}).get(section)
        ]
    if required_missing or required_stdout_missing:
        action_groups = list(required_missing) + list(required_stdout_missing)
        evidence = scope_evidence(scope)
        evidence.extend(missing_warning_evidence(summary, list(required_missing), len(evidence) + 1))
        evidence.extend(missing_stdout_evidence(summary, tuple(required_stdout_missing), len(evidence) + 1))
        actions.append(
            collect_action(
                f"recollect_{normalized_key(policy.scope)}",
                f"Selected {policy.scope} scope is missing expected evidence; recollect before relying on this scope.",
                [policy.scope],
                action_groups,
                evidence,
                "medium",
            )
        )

    if policy.scope == "PipeUtilization":
        optional_followup_groups = [
            group
            for group in ["arithmetic_utilization", "memory", "resource_conflict"]
            if group in missing_groups
        ]
        if optional_followup_groups:
            evidence = scope_evidence(scope)
            evidence.extend(missing_warning_evidence(summary, optional_followup_groups, len(evidence) + 1))
            actions.append(
                collect_action(
                    "collect_default_metric_followup",
                    (
                        "PipeUtilization-only evidence leaves arithmetic, memory, or conflict "
                        "families uncollected; use this as optional follow-up before code-change hypotheses."
                    ),
                    ["Default"],
                    optional_followup_groups,
                    evidence,
                    "low",
                )
            )

    return actions


def has_headline(summary: dict, group: str) -> bool:
    return isinstance((summary.get("headlines") or {}).get(group), dict)


def parsed_artifact_groups(raw_artifact_index: dict) -> set[str]:
    groups = set()
    for item in raw_artifact_index.get("artifacts", []):
        if not isinstance(item, dict):
            continue
        if item.get("status") != "parsed":
            continue
        group = item.get("group")
        if group:
            groups.add(str(group))
    return groups


def available_evidence_families(summary: dict, raw_artifact_index: dict) -> list[str]:
    parsed_groups = parsed_artifact_groups(raw_artifact_index)
    out = []
    if any(has_headline(summary, group) for group in APP_TIMING_ARTIFACTS):
        out.append("app_timing")
    if has_headline(summary, "op_basic_info"):
        out.append("operator_metadata")
    if has_headline(summary, "pipe_utilization"):
        out.append("pipe_utilization")
    if has_headline(summary, "arithmetic_utilization"):
        out.append("arithmetic_utilization")
    if has_headline(summary, "memory") or has_headline(summary, "l2_cache"):
        out.append("memory_cache")
    if has_headline(summary, "resource_conflict"):
        out.append("resource_conflict")
    if "simulator_trace" in parsed_groups or "simulator_csv" in parsed_groups:
        out.append("simulator_source_pipeline")
    stdout_sections = summary.get("stdout_sections") or {}
    if isinstance(stdout_sections.get("occupancy_summary"), dict):
        out.append("stdout_occupancy_summary")
    if isinstance(stdout_sections.get("roofline_summary"), dict):
        out.append("stdout_roofline_summary")
    if isinstance(stdout_sections.get("performance_summary"), dict):
        out.append("stdout_performance_summary")
    return out


def workload_context_available(run_dir: Path) -> bool:
    for name in ["profile_context.json", "tilelang_context.json"]:
        path = run_dir / "analysis" / name
        if not path.is_file():
            continue
        try:
            payload = read_json(path)
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and payload:
            return True
    return False


def readiness_segment_status(missing_required: list[str], present_required: list[str], present_optional: list[str]) -> str:
    if missing_required and (present_required or present_optional):
        return "partial"
    if missing_required:
        return "missing_required_artifacts"
    return "ready"


def readiness_stage_for_app(summary: dict) -> dict:
    required = list(APP_TIMING_ARTIFACTS)
    present_required = [group for group in required if has_headline(summary, group)]
    missing_required = [] if present_required else required
    return {
        "segment": "app",
        "metric_scope": APP_TIMING_CONTRACT["scope"],
        "status": "ready" if present_required else "missing_required_artifacts",
        "missing_required_artifacts": missing_artifact_labels(missing_required),
    }


def segment_artifacts(raw_artifact_index: dict, segment: str) -> list[dict]:
    return [
        item
        for item in raw_artifact_index.get("artifacts", [])
        if isinstance(item, dict) and item.get("segment") == segment
    ]


def readiness_stage_for_scope(
    raw_artifact_index: dict,
    segment: str,
    scope_value: str | None,
) -> dict:
    policy = metric_scope_policy(scope_value)
    artifacts = segment_artifacts(raw_artifact_index, segment)
    groups_present = {
        str(item.get("group"))
        for item in artifacts
        if item.get("status") == "parsed" and item.get("group")
    }
    if not policy:
        return {
            "segment": segment,
            "metric_scope": scope_value,
            "status": "not_applicable",
            "missing_required_artifacts": [],
        }

    present_required = [group for group in policy.required_artifacts if group in groups_present]
    missing_required = [group for group in policy.required_artifacts if group not in groups_present]
    present_optional = [group for group in policy.optional_artifacts if group in groups_present]
    return {
        "segment": segment,
        "metric_scope": policy.scope,
        "status": readiness_segment_status(missing_required, present_required, present_optional),
        "missing_required_artifacts": missing_artifact_labels(missing_required),
    }


def known_scope_segments(summary: dict, raw_artifact_index: dict) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    selected = summary.get("metric_scope")
    if isinstance(selected, dict) and selected.get("value"):
        out.append(("op", str(selected["value"])))
    for item in raw_artifact_index.get("artifacts", []):
        if not isinstance(item, dict):
            continue
        segment = str(item.get("segment") or "")
        scope = item.get("metric_scope")
        if segment.startswith("followup:") and scope:
            pair = (segment, str(scope))
            if pair not in out:
                out.append(pair)
    if not out and any(has_headline(summary, group) for group in ["op_basic_info", *OP_METRIC_GROUPS]):
        out.append(("op", None))
    return out


def readiness_level(families: list[str], target_status: str, has_workload_context: bool) -> str:
    has_timing = "app_timing" in families
    metric_families = {
        "pipe_utilization",
        "arithmetic_utilization",
        "memory_cache",
        "resource_conflict",
    }
    has_metric = any(family in families for family in metric_families)
    has_source = "simulator_source_pipeline" in families
    if not has_timing:
        return "triage_only" if has_metric else "insufficient"
    if not has_metric:
        return "triage_only"
    if target_status in {"mismatch", "partial_mismatch", "missing_observed"}:
        return "triage_only"
    if has_source or has_workload_context:
        return "actionable_experiment"
    return "directional"


def readiness_reasons(families: list[str], target_status: str, has_workload_context: bool) -> list[str]:
    reasons = []
    if "app_timing" in families:
        reasons.append("Parser-visible application timing evidence is present.")
    else:
        reasons.append("Parser-visible application timing evidence is missing.")
    if any(family in families for family in ["pipe_utilization", "arithmetic_utilization", "memory_cache", "resource_conflict"]):
        reasons.append("At least one parser-visible operator metric family is present.")
    else:
        reasons.append("No parser-visible operator metric family is present.")
    if "simulator_source_pipeline" in families:
        reasons.append("Simulator source or pipeline context is present as raw context.")
    elif has_workload_context:
        reasons.append("Workload or shape context is recorded in analysis context.")
    if target_status in {"mismatch", "partial_mismatch", "missing_observed"}:
        reasons.append(f"Target identity status is {target_status}; optimization claims are limited.")
    return reasons


def missing_evidence_families(families: list[str], has_workload_context: bool) -> list[str]:
    required = ["app_timing", "operator_metric", "source_or_workload_context"]
    missing = []
    if "app_timing" not in families:
        missing.append("app_timing")
    if not any(family in families for family in ["pipe_utilization", "arithmetic_utilization", "memory_cache", "resource_conflict"]):
        missing.append("operator_metric")
    if "simulator_source_pipeline" not in families and not has_workload_context:
        missing.append("source_or_workload_context")
    return [item for item in required if item in missing]


def claim_lists(level: str, families: list[str]) -> tuple[list[str], list[str]]:
    allowed = []
    blocked = []
    if "app_timing" in families:
        allowed.append("rank application-level hot path")
    else:
        blocked.append("rank hot path without parser-visible timing")
    if "pipe_utilization" in families:
        allowed.append("rank first AI Core pipe inspection direction")
    if "arithmetic_utilization" in families:
        allowed.append("inspect arithmetic utilization direction")
    if "memory_cache" in families:
        allowed.append("inspect memory/cache movement direction")
    if "resource_conflict" in families:
        allowed.append("inspect resource conflict direction")
    if READINESS_LEVEL_ORDER.get(level, 0) < READINESS_LEVEL_ORDER["actionable_experiment"]:
        blocked.append("propose focused kernel code experiment without stronger context")
    if "simulator_source_pipeline" not in families:
        blocked.append("source-line or instruction attribution without simulator/source artifacts")
    return allowed, blocked


def readiness_followups(summary: dict, missing_families: list[str]) -> list[dict]:
    existing = summary.get("next_collection_actions")
    if isinstance(existing, list) and existing:
        return existing
    out = []
    if "app_timing" in missing_families:
        out.append(
            {
                "id": "collect_app_timing",
                "reason": "Collect application-level msprof timing so the hot path is known.",
                "recommended_aic_metrics": [],
                "required_artifacts": list(APP_TIMING_CONTRACT["required_artifacts"]),
                "confidence": "medium",
            }
        )
    if "operator_metric" in missing_families:
        out.append(
            {
                "id": "collect_pipe_utilization",
                "reason": "Collect operator-level PipeUtilization as the minimal AI Core metric family.",
                "recommended_aic_metrics": ["PipeUtilization"],
                "required_artifacts": missing_artifact_labels(("op_basic_info", "pipe_utilization")),
                "confidence": "medium",
            }
        )
    if "source_or_workload_context" in missing_families:
        out.append(
            {
                "id": "collect_source_or_context",
                "reason": "Add simulator/source context or record strong workload/shape context before focused code experiments.",
                "recommended_aic_metrics": ["PipeUtilization"],
                "required_artifacts": ["trace.json or core*_code_exe.csv/core*_instr_exe.csv"],
                "confidence": "low",
            }
        )
    return out[:2]


def build_evidence_readiness(run_dir: Path, summary: dict, raw_artifact_index: dict) -> dict:
    families = available_evidence_families(summary, raw_artifact_index)
    target_status = str((summary.get("target_identity") or {}).get("status") or "unknown")
    has_context = workload_context_available(run_dir)
    level = readiness_level(families, target_status, has_context)
    missing_families = missing_evidence_families(families, has_context)
    allowed, blocked = claim_lists(level, families)
    stages = [readiness_stage_for_app(summary)]
    for segment, scope in known_scope_segments(summary, raw_artifact_index):
        stages.append(readiness_stage_for_scope(raw_artifact_index, segment, scope))
    unparsed = [
        {
            "artifact": item.get("artifact"),
            "segment": item.get("segment"),
            "known_role": item.get("known_role"),
            "diagnosis_role": item.get("diagnosis_role"),
        }
        for item in raw_artifact_index.get("artifacts", [])
        if isinstance(item, dict) and item.get("group") == "unparsed_profiler_binary"
    ]
    return {
        "schema_version": "1.0",
        "level": level,
        "reasons": readiness_reasons(families, target_status, has_context),
        "available_evidence_families": families,
        "missing_evidence_families": missing_families,
        "allowed_claims": allowed,
        "blocked_claims": blocked,
        "recommended_followups": readiness_followups(summary, missing_families),
        "segments": stages,
        "unparsed_binary_artifacts": unparsed,
    }


def write_text_summary(out_path: Path, summary: dict) -> None:
    lines = ["# Ascend msprof Key Metrics", ""]
    for group, item in summary["headlines"].items():
        if item is None:
            lines.append(f"- {group}: missing")
            continue
        value = item.get("value")
        value_text = "n/a" if value is None else f"{value:g}"
        name = item.get("name") or "n/a"
        field = item.get("field")
        field_text = f" {field}" if field else ""
        lines.append(f"- {group}: {name}{field_text} = {value_text} ({item.get('file')})")
    lines.append("")
    lines.append("## Files")
    for group, records in summary["files"].items():
        lines.append(f"- {group}: {len(records)} file(s)")
        for rec in records:
            lines.append(f"  - {rel(Path(rec['path']), summary['run_dir_path'])}: {rec['row_count']} row(s)")
    occupancy = summary.get("stdout_sections", {}).get("occupancy_summary")
    if occupancy:
        lines.append("")
        lines.append("## Occupancy Summary")
        lines.append("")
        lines.append("| Ordinal | Message | Source |")
        lines.append("|---:|---|---|")
        source = occupancy.get("source", "missing")
        for message in occupancy.get("messages", []):
            lines.append(
                f"| {md_table_cell(message.get('ordinal'))} | "
                f"{md_table_cell(message.get('message'))} | "
                f"{md_table_cell(source)} |"
            )
    roofline = summary.get("stdout_sections", {}).get("roofline_summary")
    if roofline:
        lines.append("")
        lines.append("## RoofLine Summary")
        lines.append("")
        lines.append("| Message | Source |")
        lines.append("|---|---|")
        source = roofline.get("source", "missing")
        for message in roofline.get("messages", []):
            lines.append(
                f"| {md_table_cell(message.get('message'))} | "
                f"{md_table_cell(source)} |"
            )
    performance = summary.get("stdout_sections", {}).get("performance_summary")
    if performance:
        lines.append("")
        lines.append("## CANN Performance Summary")
        lines.append("")
        lines.append("| Ordinal | Message | Source |")
        lines.append("|---:|---|---|")
        source = performance.get("source", "missing")
        for message in performance.get("messages", []):
            lines.append(
                f"| {md_table_cell(message.get('ordinal'))} | "
                f"{md_table_cell(message.get('message'))} | "
                f"{md_table_cell(message.get('source') or source)} |"
            )
    dimensions = summary.get("analysis_dimensions") or []
    if dimensions:
        lines.append("")
        lines.append("## Analysis Dimensions")
        for dimension in dimensions:
            status = dimension.get("status", "insufficient")
            lines.append(f"- {dimension.get('title')}: {status}")
            for signal in dimension.get("signals", [])[:5]:
                value = signal.get("value")
                value_text = "n/a" if value is None else f"{float(value):g}" if isinstance(value, (int, float)) else str(value)
                lines.append(
                    f"  - {signal.get('signal')} = {value_text} "
                    f"({signal.get('artifact')}; {signal.get('field_ref')})"
                )
    relations = summary.get("evidence_relations") or []
    if relations:
        lines.append("")
        lines.append("## Evidence Relations")
        for item in relations:
            evidence_ids = ", ".join(str(evidence.get("evidence_id")) for evidence in item.get("evidence", []))
            lines.append(
                f"- {item.get('id')}: {item.get('kind')} target={item.get('target')} "
                f"confidence={item.get('confidence')} evidence={evidence_ids}"
            )
    directions = summary.get("optimization_directions") or []
    if directions:
        lines.append("")
        lines.append("## Optimization Directions")
        for item in directions:
            lines.append(
                f"- {item.get('rank')}. {item.get('id')}: "
                f"{item.get('title')}: {item.get('impact_basis')}"
            )
    next_actions = summary.get("next_collection_actions") or []
    if next_actions:
        lines.append("")
        lines.append("## Next Collection Actions")
        for item in next_actions:
            metrics = ", ".join(item.get("recommended_aic_metrics") or [])
            artifacts = ", ".join(item.get("required_artifacts") or [])
            lines.append(f"- {item.get('id')}: collect {metrics}; required artifacts: {artifacts}")
    readiness = summary.get("evidence_readiness")
    if isinstance(readiness, dict):
        lines.append("")
        lines.append("## Evidence Readiness")
        lines.append(f"- level: {readiness.get('level', 'insufficient')}")
        available = ", ".join(readiness.get("available_evidence_families") or []) or "none"
        missing = ", ".join(readiness.get("missing_evidence_families") or []) or "none"
        lines.append(f"- available evidence families: {available}")
        lines.append(f"- missing evidence families: {missing}")
        followups = readiness.get("recommended_followups") or []
        if followups:
            lines.append(f"- next minimal action: {followups[0].get('id')}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class EvidenceModelArtifacts:
    summary_path: Path
    raw_artifact_index_path: Path
    key_metrics_path: Path
    summary: dict[str, Any]
    raw_artifact_index: dict[str, Any]


def build_evidence_model(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    run_dir = run_dir.resolve()
    summary: dict[str, Any] = {
        "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
        "run_dir": str(run_dir),
        "run_dir_path": run_dir,
        "files": {},
        "headlines": {},
        "stdout_sections": {
            "occupancy_summary": parse_occupancy_summary_stdout(run_dir),
            "roofline_summary": parse_roofline_summary_stdout(run_dir),
            "performance_summary": parse_performance_summary_stdout(run_dir),
        },
        "warnings": [],
    }
    metric_scope = selected_metric_scope(run_dir)
    if metric_scope:
        summary["metric_scope"] = metric_scope
    for group, patterns in FILE_GROUPS.items():
        records = collect_group(run_dir, group, patterns, metric_scope)
        summary["files"][group] = records
        summary["headlines"][group] = headline_for_group(run_dir, group, patterns, metric_scope)
        if not records:
            summary["warnings"].append(f"missing {group}: {patterns}")
    summary["target_identity"] = build_target_identity(run_dir, summary)
    summary["warnings"].extend(target_identity_warnings(summary["target_identity"]))
    simulator_model = write_simulator_hotspot_model(run_dir)
    summary["_simulator_hotspot_model"] = simulator_model
    for warning in simulator_model.get("warnings", []):
        if str(warning).startswith("invalid simulator"):
            summary["warnings"].append(str(warning))
    summary["analysis_dimensions"] = build_analysis_dimensions(run_dir, summary)
    summary["next_collection_actions"] = build_next_collection_actions(summary)
    summary["evidence_relations"] = build_evidence_relations(summary)
    summary["optimization_directions"] = build_optimization_directions(summary)
    raw_artifact_index = build_raw_artifact_index(run_dir, summary, metric_scope)
    summary["evidence_readiness"] = build_evidence_readiness(run_dir, summary, raw_artifact_index)
    return summary, raw_artifact_index


def serializable_summary(summary: dict[str, Any]) -> dict[str, Any]:
    payload = dict(summary)
    payload.pop("run_dir_path", None)
    payload.pop("_simulator_hotspot_model", None)
    return payload


def write_evidence_model(run_dir: Path) -> EvidenceModelArtifacts:
    run_dir = run_dir.resolve()
    out_dir = analysis_dir(run_dir)
    summary, raw_artifact_index = build_evidence_model(run_dir)
    summary_path = out_dir / "summary.json"
    raw_artifact_index_path = out_dir / "raw_artifact_index.json"
    key_metrics_path = out_dir / "key_metrics.txt"
    write_json(summary_path, serializable_summary(summary))
    write_json(raw_artifact_index_path, raw_artifact_index)
    write_text_summary(key_metrics_path, summary)
    return EvidenceModelArtifacts(
        summary_path=summary_path,
        raw_artifact_index_path=raw_artifact_index_path,
        key_metrics_path=key_metrics_path,
        summary=summary,
        raw_artifact_index=raw_artifact_index,
    )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    args = ap.parse_args(argv)

    artifacts = write_evidence_model(args.run_dir.resolve())
    print(f"wrote {artifacts.summary_path}")
    print(f"wrote {artifacts.raw_artifact_index_path}")
    print(f"wrote {artifacts.key_metrics_path}")


if __name__ == "__main__":
    main()
