"""Ascend msprof op metric-scope policy shared by analyzer and report code."""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path


ARTIFACT_LABELS = {
    "op_basic_info": "OpBasicInfo.csv",
    "pipe_utilization": "PipeUtilization.csv",
    "arithmetic_utilization": "ArithmeticUtilization.csv",
    "l2_cache": "L2Cache.csv",
    "memory": "Memory.csv/MemoryL0.csv/MemoryUB.csv",
    "resource_conflict": "ResourceConflictRatio.csv",
    "simulator": "simulator trace.json/core*_*.csv",
    "occupancy_summary": "stdout_sections.occupancy_summary",
    "roofline_summary": "stdout_sections.roofline_summary",
    "performance_summary": "stdout_sections.performance_summary",
}


@dataclass(frozen=True)
class MetricScopePolicy:
    scope: str
    required_artifacts: tuple[str, ...]
    optional_artifacts: tuple[str, ...]
    stdout_sections: tuple[str, ...]
    suppress_optional_missing_caveats: bool
    notes: str

    def as_dict(self) -> dict:
        return {
            "scope": self.scope,
            "required_artifacts": [ARTIFACT_LABELS.get(item, item) for item in self.required_artifacts],
            "optional_artifacts": [ARTIFACT_LABELS.get(item, item) for item in self.optional_artifacts],
            "stdout_sections": [ARTIFACT_LABELS.get(item, item) for item in self.stdout_sections],
            "report_caveat_behavior": (
                "suppress optional missing artifact caveats"
                if self.suppress_optional_missing_caveats
                else "preserve missing artifact caveats"
            ),
            "notes": self.notes,
        }


METRIC_SCOPE_POLICIES = {
    "PipeUtilization": MetricScopePolicy(
        scope="PipeUtilization",
        required_artifacts=("op_basic_info", "pipe_utilization"),
        optional_artifacts=("arithmetic_utilization", "memory", "resource_conflict", "l2_cache"),
        stdout_sections=("performance_summary",),
        suppress_optional_missing_caveats=True,
        notes="Pipe-only collection; use optional follow-up collection for other metric families.",
    ),
    "Default": MetricScopePolicy(
        scope="Default",
        required_artifacts=(
            "op_basic_info",
            "pipe_utilization",
            "arithmetic_utilization",
            "memory",
            "resource_conflict",
        ),
        optional_artifacts=("l2_cache",),
        stdout_sections=("performance_summary",),
        suppress_optional_missing_caveats=True,
        notes="Default onboard operator metric collection expected by local fixtures.",
    ),
    "KernelScale": MetricScopePolicy(
        scope="KernelScale",
        required_artifacts=("op_basic_info",),
        optional_artifacts=("simulator",),
        stdout_sections=(),
        suppress_optional_missing_caveats=True,
        notes="Kernel-scale scope; non-selected metric families are not caveats.",
    ),
    "ResourceConflictRatio": MetricScopePolicy(
        scope="ResourceConflictRatio",
        required_artifacts=("op_basic_info", "resource_conflict"),
        optional_artifacts=("simulator",),
        stdout_sections=(),
        suppress_optional_missing_caveats=True,
        notes="Resource conflict scope; simulator sync-event context is optional raw evidence.",
    ),
    "PMSampling": MetricScopePolicy(
        scope="PMSampling",
        required_artifacts=("op_basic_info",),
        optional_artifacts=("simulator",),
        stdout_sections=(),
        suppress_optional_missing_caveats=True,
        notes="PM sampling scope; this skill keeps observed simulator throughput context raw.",
    ),
    "Occupancy": MetricScopePolicy(
        scope="Occupancy",
        required_artifacts=("op_basic_info",),
        optional_artifacts=(),
        stdout_sections=("occupancy_summary",),
        suppress_optional_missing_caveats=True,
        notes="Occupancy scope; parsed stdout is raw evidence and not diagnosis by itself.",
    ),
    "Roofline": MetricScopePolicy(
        scope="Roofline",
        required_artifacts=("op_basic_info",),
        optional_artifacts=(),
        stdout_sections=("roofline_summary",),
        suppress_optional_missing_caveats=True,
        notes="Roofline scope; parsed stdout is raw evidence and not diagnosis by itself.",
    ),
}


def normalize_metric_scope(scope: str | None) -> str | None:
    if not scope:
        return None
    normalized = str(scope).strip()
    for known in METRIC_SCOPE_POLICIES:
        if normalized.lower() == known.lower():
            return known
    return normalized or None


def metric_scope_policy(scope: str | None) -> MetricScopePolicy | None:
    normalized = normalize_metric_scope(scope)
    if not normalized:
        return None
    return METRIC_SCOPE_POLICIES.get(normalized)


def command_parts(command: object) -> list[str] | None:
    if isinstance(command, str):
        try:
            return shlex.split(command)
        except ValueError:
            return command.split()
    if isinstance(command, list):
        return [str(part) for part in command]
    return None


def command_metric_scope(command: object) -> str | None:
    parts = command_parts(command)
    if not parts:
        return None
    for index, part in enumerate(parts):
        if part.startswith("--aic-metrics="):
            value = part.split("=", 1)[1].strip()
            return value or None
        if part == "--aic-metrics" and index + 1 < len(parts):
            value = parts[index + 1].strip()
            return value or None
    return None


def is_msprof_op_command(command: object) -> bool:
    parts = command_parts(command)
    if not parts or len(parts) < 2:
        return False
    return Path(parts[0]).name == "msprof" and parts[1] == "op"


def missing_warning_prefix(group: str) -> str:
    return f"missing {group}:"


def warning_group(warning: str) -> str | None:
    if not warning.startswith("missing "):
        return None
    return warning.split(":", 1)[0].removeprefix("missing ").strip()


def missing_artifact_labels(groups: list[str] | tuple[str, ...]) -> list[str]:
    return [ARTIFACT_LABELS.get(group, group) for group in groups]
