"""Build analysis artifacts from Ascend msprof / msprof op output."""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ._evidence_artifacts import (
    FILE_GROUPS,
    build_frequency_measurement_quality,
    build_profile_coverage,
    build_raw_artifact_index,
    collect_group,
)
from ._evidence_directions import build_optimization_directions
from ._evidence_relations import build_evidence_relations
from ._evidence_readiness import build_evidence_readiness, build_next_collection_actions
from ._evidence_signals import (
    build_analysis_dimensions,
    headline_for_group,
    headline_schema_issues,
)
from ._evidence_text_summary import write_text_summary
from ._profiler_segments import (
    performance_summary_segment,
    segment_receipt_allows_evidence,
    stdout_profile_output_segment,
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
    command_metric_scope,
    is_msprof_op_command,
    metric_scope_policy,
    normalize_metric_scope,
)
from ._profile_target import (
    normalize_persisted_target,
    normalize_target_name,
    target_name_match_rule,
)
from .simulator_hotspot_model import write_simulator_hotspot_model


ANALYSIS_SCHEMA_VERSION = "1.5"

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


@dataclass(frozen=True)
class DeclaredTarget:
    target: dict[str, Any]
    artifact: str
    field_ref: str


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


def target_name_matches(expected: str, observed: str) -> bool:
    return target_name_match_rule(expected, observed) in {"exact", "known_suffix"}


def target_identity_match_rule(expected: str, observed: str) -> str:
    return target_name_match_rule(expected, observed)


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


def declared_target_from_run(run_dir: Path) -> DeclaredTarget | None:
    workflow_path = run_dir / "analysis" / "profile_harness_run.json"
    if workflow_path.is_file():
        try:
            workflow = read_json(workflow_path)
        except (OSError, ValueError):
            pass
        else:
            if isinstance(workflow, dict) and workflow.get("target_selection") is not None:
                try:
                    target = normalize_persisted_target(workflow.get("target_selection"))
                except ValueError as exc:
                    raise ValueError(f"analysis/profile_harness_run.json target_selection is invalid: {exc}") from exc
                return DeclaredTarget(
                    target=target,
                    artifact="analysis/profile_harness_run.json",
                    field_ref="target_selection.expected_launches",
                )
    context_path = run_dir / "analysis" / "profile_context.json"
    if context_path.is_file():
        try:
            context = read_json(context_path)
            profile_harness = context.get("profile_harness") if isinstance(context, dict) else None
        except (OSError, ValueError):
            pass
        else:
            if isinstance(profile_harness, dict) and profile_harness.get("target") is not None:
                try:
                    target = normalize_persisted_target(profile_harness.get("target"))
                except ValueError as exc:
                    raise ValueError(f"analysis/profile_context.json profile_harness.target is invalid: {exc}") from exc
                return DeclaredTarget(
                    target=target,
                    artifact="analysis/profile_context.json",
                    field_ref="profile_harness.target.expected_launches",
                )
    return None


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


def build_target_identity(run_dir: Path, summary: dict, declared_target: DeclaredTarget | None) -> dict:
    if declared_target is not None:
        target = declared_target.target
        expected = {
            "names": [str(item["name"]) for item in target["expected_launches"]],
            "counts": {
                str(item["normalized_name"]): int(item["count"])
                for item in target["expected_launches"]
            },
            "artifact": declared_target.artifact,
            "field_ref": declared_target.field_ref,
            "explicit_target": True,
        }
        segment_identities: dict[str, dict] = {}
        segments = (summary.get("profile_coverage") or {}).get("segments") or {}
        for segment, coverage in segments.items():
            if not isinstance(coverage, dict):
                continue
            segment_counts = coverage.get("expected_counts")
            segment_display_names = coverage.get("expected_display_names")
            if isinstance(segment_counts, dict) and isinstance(segment_display_names, dict):
                segment_expected = {
                    **expected,
                    "names": [
                        str(segment_display_names.get(name) or name)
                        for name in segment_counts
                    ],
                    "counts": {
                        str(name): int(count)
                        for name, count in segment_counts.items()
                    },
                }
            else:
                segment_expected = expected
            observed = []
            for item in coverage.get("observed_names", []):
                if not isinstance(item, dict):
                    continue
                observed.append(
                    {
                        "group": "op_summary" if segment == "app" else "op_basic_info",
                        "name": item.get("name"),
                        "artifact": (item.get("artifacts") or [None])[0],
                        "field_ref": f"profile_coverage.segments.{segment}.observed_names",
                        "count": item.get("count"),
                        "status": "match" if item.get("match_rule") in {"exact", "known_suffix"} else "mismatch",
                        "match_rule": item.get("match_rule") or "unmatched",
                    }
                )
            if not observed:
                status = "missing_observed"
            else:
                mismatches = [item for item in observed if item["status"] == "mismatch"]
                status = "match" if not mismatches else ("mismatch" if len(mismatches) == len(observed) else "partial_mismatch")
            segment_identity = {"status": status, "expected": segment_expected, "observed": observed}
            segment_identity["confidence"] = target_identity_confidence(segment_identity)
            segment_identities[str(segment)] = segment_identity
        primary = segment_identities.get("op") or {
            "status": "missing_observed",
            "expected": expected,
            "observed": [],
            "confidence": "blocked",
        }
        return {**primary, "expected": expected, "segments": segment_identities}

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
    selected, _ = _parse_stdout_sections(
        run_dir,
        selected_profiler_stdout_paths(run_dir),
        parse_occupancy_summary_text,
        stdout_profile_output_segment,
    )
    return selected


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
    selected, _ = _parse_stdout_sections(
        run_dir,
        selected_roofline_stdout_paths(run_dir),
        parse_roofline_summary_text,
        stdout_profile_output_segment,
    )
    return selected


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
    selected, _ = _parse_stdout_sections(
        run_dir,
        selected_performance_stdout_paths(run_dir),
        parse_performance_summary_text,
        performance_summary_segment,
    )
    return selected


def _parse_stdout_sections(
    run_dir: Path,
    paths: list[Path],
    parse_text: Callable[[str, str], dict | None],
    segment_for_path: Callable[[Path], str | None],
) -> tuple[dict | None, list[dict]]:
    selected = None
    parsed = []
    for path in paths:
        section = parse_text(
            path.read_text(encoding="utf-8", errors="replace"),
            rel(path, run_dir),
        )
        if section is None:
            continue
        parsed.append(section)
        segment = segment_for_path(path)
        if selected is None and (
            segment is None or segment_receipt_allows_evidence(run_dir, segment)
        ):
            selected = section
    return selected, parsed


@dataclass(frozen=True)
class EvidenceModelArtifacts:
    summary_path: Path
    raw_artifact_index_path: Path
    key_metrics_path: Path
    summary: dict[str, Any]
    raw_artifact_index: dict[str, Any]


def build_evidence_model(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    run_dir = run_dir.resolve()
    metric_scope = selected_metric_scope(run_dir)
    occupancy_summary, raw_occupancy_sections = _parse_stdout_sections(
        run_dir,
        selected_profiler_stdout_paths(run_dir),
        parse_occupancy_summary_text,
        stdout_profile_output_segment,
    )
    roofline_summary, raw_roofline_sections = _parse_stdout_sections(
        run_dir,
        selected_roofline_stdout_paths(run_dir),
        parse_roofline_summary_text,
        stdout_profile_output_segment,
    )
    performance_summary, raw_performance_sections = _parse_stdout_sections(
        run_dir,
        selected_performance_stdout_paths(run_dir),
        parse_performance_summary_text,
        performance_summary_segment,
    )
    summary: dict[str, Any] = {
        "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
        "run_dir": str(run_dir),
        "run_dir_path": run_dir,
        "files": {},
        "headlines": {},
        "stdout_sections": {
            "occupancy_summary": occupancy_summary,
            "roofline_summary": roofline_summary,
            "performance_summary": performance_summary,
        },
        "warnings": [],
    }
    declared_target = declared_target_from_run(run_dir)
    target = declared_target.target if declared_target is not None else None
    if metric_scope:
        summary["metric_scope"] = metric_scope
    for group, patterns in FILE_GROUPS.items():
        records = collect_group(run_dir, group, patterns, metric_scope)
        summary["files"][group] = records
        summary["headlines"][group] = headline_for_group(
            run_dir,
            group,
            patterns,
            metric_scope,
            prefer_primary_op=target is not None,
        )
        if not records:
            summary["warnings"].append(f"missing {group}: {patterns}")
    raw_artifact_index = build_raw_artifact_index(
        run_dir,
        summary,
        metric_scope,
        stdout_sections={
            "occupancy_summary": raw_occupancy_sections,
            "roofline_summary": raw_roofline_sections,
            "performance_summary": raw_performance_sections,
        },
    )
    artifact_segments = {
        str(item.get("segment") or "unknown")
        for item in raw_artifact_index.get("artifacts", [])
        if isinstance(item, dict)
    }
    excluded_segments = {
        segment
        for segment in artifact_segments
        if not segment_receipt_allows_evidence(run_dir, segment)
    }
    evidence_artifact_index = {
        **raw_artifact_index,
        "artifacts": [
            item
            for item in raw_artifact_index.get("artifacts", [])
            if not isinstance(item, dict)
            or str(item.get("segment") or "unknown") not in excluded_segments
        ],
    }
    summary["warnings"].extend(
        f"{segment} result receipt is not succeeded; raw artifacts are excluded from derived evidence"
        for segment in sorted(excluded_segments)
    )
    summary["profile_coverage"] = build_profile_coverage(
        run_dir,
        raw_artifact_index,
        target,
    )
    if target is not None:
        selected_segments = summary["profile_coverage"].get("selected_segments_by_family") or {}
        for group, family in {
            "pipe_utilization": "pipe_utilization",
            "arithmetic_utilization": "arithmetic_utilization",
            "memory": "memory",
            "l2_cache": "l2_cache",
            "resource_conflict": "resource_conflict",
        }.items():
            preferred_segment = selected_segments.get(family)
            if preferred_segment:
                summary["headlines"][group] = headline_for_group(
                    run_dir,
                    group,
                    FILE_GROUPS[group],
                    metric_scope,
                    preferred_segment=str(preferred_segment),
                )
    for group, item in summary["headlines"].items():
        if item:
            item["schema_issues"] = headline_schema_issues(group, item)
    summary["target_identity"] = build_target_identity(run_dir, summary, declared_target)
    summary["warnings"].extend(target_identity_warnings(summary["target_identity"]))
    simulator_model = write_simulator_hotspot_model(run_dir)
    summary["_simulator_hotspot_model"] = simulator_model
    for warning in simulator_model.get("warnings", []):
        if str(warning).startswith("invalid simulator"):
            summary["warnings"].append(str(warning))
    summary["analysis_dimensions"] = build_analysis_dimensions(run_dir, summary)
    summary["next_collection_actions"] = build_next_collection_actions(summary)
    summary["evidence_relations"] = build_evidence_relations(summary)
    summary["evidence_readiness"] = build_evidence_readiness(
        run_dir,
        summary,
        evidence_artifact_index,
    )
    summary["optimization_directions"] = build_optimization_directions(summary)
    frequency_quality = build_frequency_measurement_quality(evidence_artifact_index)
    summary["measurement_quality"] = {"frequency": frequency_quality}
    summary["warnings"].extend(frequency_quality["warnings"])
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
