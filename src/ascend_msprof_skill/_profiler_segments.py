"""Profiler artifact segment classification helpers."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


APP_SEGMENT = "app"
OP_SEGMENT = "op"
SIMULATOR_SEGMENT = "simulator"
UNKNOWN_SEGMENT = "unknown"
FOLLOWUP_SEGMENT_PREFIX = "followup:"

APP_FILE_GROUPS = {"op_summary", "op_statistic", "task_time", "api_statistic"}
DEFAULT_FOLLOWUP_ACTION_ID = "collect_default_metric_followup"
FOCUSED_DEFAULT_FOLLOWUP_PREFIX = f"{DEFAULT_FOLLOWUP_ACTION_ID}_focused_"
FOCUSED_DEFAULT_FOLLOWUP_RE = re.compile(
    rf"{re.escape(FOCUSED_DEFAULT_FOLLOWUP_PREFIX)}[0-9a-f]{{12}}"
)
OP_STDOUT_PREFIXES = (
    "msprof_op",
    "command_msprof_op",
    "msprof_occupancy",
    "msprof_roofline",
)


def followup_segment(action_id: str) -> str:
    return f"{FOLLOWUP_SEGMENT_PREFIX}{action_id}"


def followup_action_from_segment(segment: object) -> str | None:
    if not isinstance(segment, str) or not segment.startswith(FOLLOWUP_SEGMENT_PREFIX):
        return None
    action_id = segment.removeprefix(FOLLOWUP_SEGMENT_PREFIX)
    return action_id or None


def is_followup_segment(segment: object) -> bool:
    return followup_action_from_segment(segment) is not None


def is_supported_followup_action_id(action_id: object) -> bool:
    return isinstance(action_id, str) and (
        action_id == DEFAULT_FOLLOWUP_ACTION_ID
        or FOCUSED_DEFAULT_FOLLOWUP_RE.fullmatch(action_id) is not None
    )


def focused_followup_action_id(target_selection: dict) -> str:
    digest = hashlib.sha256(
        json.dumps(target_selection, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    return f"{FOCUSED_DEFAULT_FOLLOWUP_PREFIX}{digest}"


def segment_receipt_allows_evidence(run_dir: Path, segment: str) -> bool:
    log_stem = {
        APP_SEGMENT: "msprof_default",
        OP_SEGMENT: "msprof_op",
        SIMULATOR_SEGMENT: "msprof_simulator",
    }.get(segment)
    if log_stem is None:
        action_id = followup_action_from_segment(segment)
        if is_supported_followup_action_id(action_id):
            log_stem = f"msprof_followup_{action_id}"
    if log_stem is None:
        return True
    receipt_path = run_dir / "logs" / f"{log_stem}.result.json"
    if not receipt_path.is_file():
        return True
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(receipt, dict) and receipt.get("status") == "succeeded"


def followup_action_from_command_path(path: Path) -> str | None:
    prefix = "command_msprof_followup_"
    suffix = ".txt"
    if not path.name.startswith(prefix) or not path.name.endswith(suffix):
        return None
    action_id = path.name[len(prefix) : -len(suffix)]
    return action_id if is_supported_followup_action_id(action_id) else None


def followup_action_from_log_path(path: Path) -> str | None:
    prefix = "msprof_followup_"
    if not path.name.startswith(prefix) or path.suffix not in {".stdout", ".stderr", ".status"}:
        return None
    action_id = path.stem.removeprefix(prefix)
    return action_id if is_supported_followup_action_id(action_id) else None


def is_followup_command(path: Path) -> bool:
    return path.name.startswith("command_msprof_followup_") and path.name.endswith(".txt")


def is_followup_stdout_or_status(path: Path) -> bool:
    return path.name.startswith("msprof_followup_") and path.suffix in {".stdout", ".status"}


def segment_for_relpath(rel_path: str, group: str | None = None) -> str:
    parts = Path(rel_path).parts
    if "simulator" in parts:
        return SIMULATOR_SEGMENT
    if "followups" in parts:
        index = parts.index("followups")
        if index + 1 < len(parts):
            return followup_segment(parts[index + 1])
        return UNKNOWN_SEGMENT
    if len(parts) >= 2 and parts[0] == "reports" and parts[1] == "app":
        return APP_SEGMENT
    if len(parts) >= 2 and parts[0] == "reports" and parts[1] == "op":
        return OP_SEGMENT
    if any(part.startswith("PROF_") for part in parts):
        return APP_SEGMENT
    if any(part.startswith("OPPROF_") for part in parts):
        return OP_SEGMENT
    if group in APP_FILE_GROUPS:
        return APP_SEGMENT
    return UNKNOWN_SEGMENT


def metric_scope_for_segment(segment: str, selected_scope: dict | None) -> str | None:
    if segment == OP_SEGMENT and isinstance(selected_scope, dict):
        value = selected_scope.get("value")
        return str(value) if value else None
    action_id = followup_action_from_segment(segment)
    if is_supported_followup_action_id(action_id):
        return "Default"
    return None


def app_timeline_segment(rel_path: str) -> str:
    parts = Path(rel_path).parts
    if len(parts) >= 2 and parts[0] == "reports" and parts[1] == "app":
        return APP_SEGMENT
    if any(part.startswith("PROF_") for part in parts):
        return APP_SEGMENT
    return segment_for_relpath(rel_path, "app_timeline")


def performance_summary_segment(source: object) -> str:
    return stdout_profile_output_segment(Path(str(source))) or UNKNOWN_SEGMENT


def command_profile_output_segment(path: Path) -> str | None:
    if path.name in {"command_msprof.txt", "command_msprof_default.txt"}:
        return APP_SEGMENT
    if path.name == "command_msprof_op.txt":
        return OP_SEGMENT
    return None


def stdout_profile_output_segment(path: Path) -> str | None:
    if path.name in {"msprof_default.stdout", "msprof.stdout", "command_msprof.stdout"}:
        return APP_SEGMENT
    if path.suffix == ".stdout" and path.name.startswith(OP_STDOUT_PREFIXES):
        return OP_SEGMENT
    if path.name == "msprof_simulator.stdout":
        return SIMULATOR_SEGMENT
    action_id = followup_action_from_log_path(path)
    if action_id is not None:
        return followup_segment(action_id)
    return None
