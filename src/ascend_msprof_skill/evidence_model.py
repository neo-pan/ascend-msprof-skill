"""Build analysis artifacts from an Ascend profiling run directory."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ascend_profile_utils import analysis_dir, write_json
from . import analyze_msprof_outputs as analyzer


@dataclass(frozen=True)
class EvidenceModelArtifacts:
    summary_path: Path
    raw_artifact_index_path: Path
    key_metrics_path: Path
    summary: dict[str, Any]
    raw_artifact_index: dict[str, Any]


def build_evidence_model(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the summary and raw artifact index without writing final artifacts."""

    run_dir = run_dir.resolve()
    summary: dict[str, Any] = {
        "analysis_schema_version": analyzer.ANALYSIS_SCHEMA_VERSION,
        "run_dir": str(run_dir),
        "run_dir_path": run_dir,
        "files": {},
        "headlines": {},
        "stdout_sections": {
            "occupancy_summary": analyzer.parse_occupancy_summary_stdout(run_dir),
            "roofline_summary": analyzer.parse_roofline_summary_stdout(run_dir),
            "performance_summary": analyzer.parse_performance_summary_stdout(run_dir),
        },
        "warnings": [],
    }
    metric_scope = analyzer.selected_metric_scope(run_dir)
    if metric_scope:
        summary["metric_scope"] = metric_scope
    for group, patterns in analyzer.FILE_GROUPS.items():
        records = analyzer.collect_group(run_dir, group, patterns, metric_scope)
        summary["files"][group] = records
        summary["headlines"][group] = analyzer.headline_for_group(run_dir, group, patterns, metric_scope)
        if not records:
            summary["warnings"].append(f"missing {group}: {patterns}")
    summary["target_identity"] = analyzer.build_target_identity(run_dir, summary)
    summary["warnings"].extend(analyzer.target_identity_warnings(summary["target_identity"]))
    simulator_model = analyzer.write_simulator_hotspot_model(run_dir)
    summary["_simulator_hotspot_model"] = simulator_model
    for warning in simulator_model.get("warnings", []):
        if str(warning).startswith("invalid simulator"):
            summary["warnings"].append(str(warning))
    summary["analysis_dimensions"] = analyzer.build_analysis_dimensions(run_dir, summary)
    summary["next_collection_actions"] = analyzer.build_next_collection_actions(summary)
    summary["evidence_relations"] = analyzer.build_evidence_relations(summary)
    summary["optimization_directions"] = analyzer.build_optimization_directions(summary)
    raw_artifact_index = analyzer.build_raw_artifact_index(run_dir, summary, metric_scope)
    summary["evidence_readiness"] = analyzer.build_evidence_readiness(run_dir, summary, raw_artifact_index)
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
    analyzer.write_text_summary(key_metrics_path, summary)
    return EvidenceModelArtifacts(
        summary_path=summary_path,
        raw_artifact_index_path=raw_artifact_index_path,
        key_metrics_path=key_metrics_path,
        summary=summary,
        raw_artifact_index=raw_artifact_index,
    )
