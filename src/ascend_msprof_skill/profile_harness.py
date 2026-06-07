#!/usr/bin/env python3
"""Profile a supplied harness manifest or application with msprof."""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import (
    analyze_msprof_outputs,
    collect_tilelang_context,
    extract_simulator_hotspots,
    generate_provenance,
    generate_report,
    plot_timeline,
)


SCHEMA_VERSION = 1
STALE_COLLECTION_ROOTS = ["reports", "logs", "analysis"]
STALE_TOP_LEVEL_FILES = ["REPORT.md"]


def rel_display(run_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(run_dir.resolve()).as_posix()
    except ValueError:
        return path.name


def existing_file(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    if not path.is_file():
        raise ValueError(f"{label} is not a file: {path}")


def load_manifest(path: Path) -> dict[str, Any]:
    existing_file(path, "profile harness manifest")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"profile harness manifest is invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("profile harness manifest must contain a top-level object")
    application = data.get("application")
    if not isinstance(application, str) or not application.strip():
        raise ValueError("profile harness manifest missing non-empty application")
    return data


def application_from_manifest(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    raw_application = str(manifest["application"]).strip()
    application = Path(raw_application).expanduser()
    if not application.is_absolute():
        application = manifest_path.parent / application
    application = application.resolve()
    existing_file(application, "profile harness application")
    return application


def load_verify_json(path: Path) -> dict[str, Any]:
    existing_file(path, "verify JSON")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"verify JSON is invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("verify JSON must contain a top-level object")
    return data


def ensure_fresh_collection_run(run_dir: Path) -> None:
    stale = []
    for name in STALE_COLLECTION_ROOTS:
        root = run_dir / name
        if root.is_dir() and any(path.is_file() for path in root.rglob("*")):
            stale.append(f"{name}/")
        elif root.is_file():
            stale.append(name)
    for name in STALE_TOP_LEVEL_FILES:
        if (run_dir / name).exists():
            stale.append(name)
    if stale:
        preview = ", ".join(stale)
        raise RuntimeError(f"run directory already contains collection artifacts: {preview}; use a fresh run directory")


def command_log_path(run_dir: Path, name: str) -> Path:
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / name


def write_command(path: Path, command: list[str]) -> None:
    path.write_text(shlex.join(command) + "\n", encoding="utf-8")


def run_logged(
    command: list[str],
    run_dir: Path,
    *,
    command_name: str,
    log_stem: str,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    write_command(command_log_path(run_dir, command_name), command)
    completed = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
    command_log_path(run_dir, f"{log_stem}.stdout").write_text(completed.stdout or "", encoding="utf-8")
    command_log_path(run_dir, f"{log_stem}.stderr").write_text(completed.stderr or "", encoding="utf-8")
    command_log_path(run_dir, f"{log_stem}.status").write_text(f"{completed.returncode}\n", encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"{log_stem} failed with exit status {completed.returncode}")
    return completed


def msprof_app_command(run_dir: Path, application: Path) -> list[str]:
    return [
        "msprof",
        f"--output={run_dir / 'reports' / 'app'}",
        f"--application={application}",
        "--runtime-api=on",
        "--task-time=on",
        "--ai-core=on",
        "--aic-metrics=PipeUtilization",
        "--type=text",
        "--summary-format=csv",
    ]


def msprof_op_command(run_dir: Path, application: Path) -> list[str]:
    return [
        "msprof",
        "op",
        f"--output={run_dir / 'reports' / 'op'}",
        f"--application={application}",
        "--aic-metrics=PipeUtilization",
    ]


def run_analysis_pipeline(run_dir: Path) -> None:
    generate_provenance.main(["--run-dir", str(run_dir)])
    analyze_msprof_outputs.main(["--run-dir", str(run_dir)])
    extract_simulator_hotspots.main(["--run-dir", str(run_dir)])
    plot_timeline.main(["--run-dir", str(run_dir)])
    generate_report.main(["--run-dir", str(run_dir)])


def manifest_context(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if manifest is None:
        return None
    return {
        "schema_version": collect_tilelang_context.sanitize_value(manifest.get("schema_version")),
        "task": collect_tilelang_context.sanitize_value(manifest.get("task")),
        "application": collect_tilelang_context.sanitize_value(manifest.get("application")),
        "workload": collect_tilelang_context.sanitize_value(manifest.get("workload")),
        "jit_config": collect_tilelang_context.sanitize_value(manifest.get("jit_config")),
        "metadata": collect_tilelang_context.sanitize_value(manifest.get("metadata")),
    }


def write_profile_context(
    run_dir: Path,
    *,
    manifest_path: Path | None,
    manifest: dict[str, Any] | None,
    application: Path,
    verify_json_path: Path | None,
    verify_json: dict[str, Any] | None,
) -> Path:
    out = run_dir / "analysis" / "profile_context.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    sources: dict[str, Any] = {
        "application": {
            "artifact": rel_display(run_dir, application),
            "resolved_path": str(application),
            "sha256": collect_tilelang_context.sha256_file(application),
            "size_bytes": application.stat().st_size,
        }
    }
    if manifest_path is not None:
        sources["profile_harness_manifest"] = collect_tilelang_context.file_record(run_dir, manifest_path)
    if verify_json_path is not None:
        sources["verify_json"] = collect_tilelang_context.file_record(run_dir, verify_json_path)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sources": sources,
        "profile_harness": manifest_context(manifest)
        or {
            "application": rel_display(run_dir, application),
            "workload": None,
            "jit_config": None,
            "metadata": None,
        },
        "warnings": [],
    }
    if verify_json is not None:
        payload["benchmark"] = collect_tilelang_context.normalize_benchmark(verify_json)
        payload["verify_context"] = {
            "raw": collect_tilelang_context.sanitize_value(verify_json),
            "evidence_role": "correctness_and_timing_context_only",
        }
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return out


def write_workflow_metadata(
    run_dir: Path,
    *,
    manifest_path: Path | None,
    application: Path,
    manifest: dict[str, Any] | None,
    verify_json_path: Path | None,
) -> Path:
    out = run_dir / "analysis" / "profile_harness_run.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "workflow": "generic profile harness profiling workflow",
        "inputs": {
            "manifest": rel_display(run_dir, manifest_path) if manifest_path else None,
            "application": rel_display(run_dir, application),
            "application_resolved_path": str(application),
            "verify_json": rel_display(run_dir, verify_json_path) if verify_json_path else None,
        },
        "commands": {
            "msprof": "logs/command_msprof.txt",
            "msprof_op": "logs/command_msprof_op.txt",
        },
        "outputs": {
            "app": "reports/app",
            "op": "reports/op",
            "provenance": "analysis/provenance.json",
            "summary": "analysis/summary.json",
            "raw_artifact_index": "analysis/raw_artifact_index.json",
            "key_metrics": "analysis/key_metrics.txt",
            "workflow_metadata": "analysis/profile_harness_run.json",
            "profile_context": "analysis/profile_context.json",
            "report": "REPORT.md",
        },
        "boundary": {
            "benchmark_renderer_owned_by": "caller_or_benchmark_skill",
            "profiler_collection_owned_by": "ascend-msprof-skill",
        },
    }
    if manifest is not None:
        payload["profile_harness"] = {
            "schema_version": manifest.get("schema_version"),
            "task": manifest.get("task"),
            "workload": manifest.get("workload"),
            "jit_config": manifest.get("jit_config"),
        }
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return out


def profile_harness(
    run_dir: Path,
    *,
    manifest_path: Path | None,
    application_path: Path | None,
    verify_json_path: Path | None,
) -> Path:
    run_dir = run_dir.expanduser().resolve()
    manifest: dict[str, Any] | None = None
    if manifest_path is not None:
        manifest_path = manifest_path.expanduser().resolve()
        manifest = load_manifest(manifest_path)
        application = application_from_manifest(manifest_path, manifest)
    elif application_path is not None:
        application = application_path.expanduser().resolve()
        existing_file(application, "application")
    else:
        raise ValueError("either --manifest or --application is required")

    verify_json: dict[str, Any] | None = None
    if verify_json_path is not None:
        verify_json_path = verify_json_path.expanduser().resolve()
        verify_json = load_verify_json(verify_json_path)

    ensure_fresh_collection_run(run_dir)
    (run_dir / "reports").mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "analysis").mkdir(parents=True, exist_ok=True)
    write_profile_context(
        run_dir,
        manifest_path=manifest_path,
        manifest=manifest,
        application=application,
        verify_json_path=verify_json_path,
        verify_json=verify_json,
    )
    workflow_path = write_workflow_metadata(
        run_dir,
        manifest_path=manifest_path,
        application=application,
        manifest=manifest,
        verify_json_path=verify_json_path,
    )

    run_logged(
        msprof_app_command(run_dir, application),
        run_dir,
        command_name="command_msprof.txt",
        log_stem="msprof_default",
        cwd=application.parent,
    )
    run_logged(
        msprof_op_command(run_dir, application),
        run_dir,
        command_name="command_msprof_op.txt",
        log_stem="msprof_op",
        cwd=application.parent,
    )
    run_analysis_pipeline(run_dir)
    return workflow_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", type=Path)
    source.add_argument("--application", type=Path)
    ap.add_argument("--verify-json", type=Path)
    args = ap.parse_args(argv)

    try:
        workflow_path = profile_harness(
            args.run_dir,
            manifest_path=args.manifest,
            application_path=args.application,
            verify_json_path=args.verify_json,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {workflow_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
