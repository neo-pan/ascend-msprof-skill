"""Optimization direction and experiment hint derivation for Evidence Model analysis."""
from __future__ import annotations

from ._evidence_signals import (
    direction_evidence,
    first_signal,
    first_signal_with_value,
    first_timing_signal,
    independent_on_device_signal,
    op_basic_launch_metadata_signals,
    op_basic_tiling_signal,
    performance_summary_signals,
    signals_with_values_for_groups,
)


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


