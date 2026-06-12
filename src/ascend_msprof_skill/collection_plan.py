"""Small metadata catalog for staged msprof collection plans."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

PRESET_IDS = ("triage", "default-depth", "full")


_TRIAGE_SEGMENTS: list[dict[str, Any]] = [
    {
        "segment_id": "app",
        "kind": "app_timing",
        "output_key": "app",
        "command_log": "logs/command_msprof.txt",
        "required": True,
        "metric_scope": None,
    },
    {
        "segment_id": "op",
        "kind": "op_metrics",
        "output_key": "op",
        "command_log": "logs/command_msprof_op.txt",
        "required": True,
        "metric_scope": "PipeUtilization",
    },
]


_DEFAULT_SEGMENT: dict[str, Any] = {
    "segment_id": "default",
    "kind": "op_metrics",
    "output_key": "default",
    "command_log": "logs/command_msprof_followup_collect_default_metric_followup.txt",
    "required": True,
    "metric_scope": "Default",
}


_SIMULATOR_SEGMENT: dict[str, Any] = {
    "segment_id": "simulator",
    "kind": "simulator",
    "output_key": "simulator",
    "command_log": "logs/command_msprof_simulator.txt",
    "required": False,
    "metric_scope": "PipeUtilization",
}


def preset_plan(preset_id: str) -> dict[str, Any] | None:
    if preset_id == "triage":
        return {
            "preset_id": "triage",
            "purpose": "Minimal first pass: application timing plus operator PipeUtilization.",
            "segments": deepcopy(_TRIAGE_SEGMENTS),
        }
    if preset_id == "default-depth":
        return {
            "preset_id": "default-depth",
            "purpose": "General kernel evidence after triage, adding Default metric scope.",
            "segments": deepcopy([*_TRIAGE_SEGMENTS, _DEFAULT_SEGMENT]),
        }
    if preset_id == "full":
        return {
            "preset_id": "full",
            "purpose": "Broad staged collection metadata with optional simulator context.",
            "segments": deepcopy([*_TRIAGE_SEGMENTS, _DEFAULT_SEGMENT, _SIMULATOR_SEGMENT]),
        }
    return None


def profile_harness_plan(
    preset_id: str,
    *,
    simulator_status: str | None = None,
) -> dict[str, Any]:
    plan = preset_plan(preset_id)
    if plan is None:
        raise ValueError(f"unknown collection preset: {preset_id}")
    plan["source"] = "profile_harness_preset"
    if preset_id == "full" and simulator_status is None:
        plan["segments"] = [segment for segment in plan["segments"] if segment.get("segment_id") != "simulator"]
    if simulator_status is not None:
        simulator_segment = deepcopy(_SIMULATOR_SEGMENT)
        simulator_segment["status"] = simulator_status
        plan["segments"] = [
            segment for segment in plan["segments"] if segment.get("segment_id") != "simulator"
        ]
        plan["segments"].append(simulator_segment)
    return plan
