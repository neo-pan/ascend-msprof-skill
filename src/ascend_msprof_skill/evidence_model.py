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
from ._evidence_directions import build_optimization_directions
from ._evidence_relations import build_evidence_relations
from ._evidence_readiness import build_evidence_readiness, build_next_collection_actions
from ._evidence_signals import (
    build_analysis_dimensions,
    headline_for_group,
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
