#!/usr/bin/env python3
"""Profile a supplied harness manifest or application with msprof."""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from . import (
    collection_plan,
    collect_tilelang_context,
    evidence_model,
    extract_simulator_hotspots,
    generate_provenance,
    generate_report,
    plot_timeline,
)


SCHEMA_VERSION = 1
STALE_COLLECTION_ROOTS = ["reports", "logs", "analysis"]
STALE_TOP_LEVEL_FILES = ["REPORT.md"]
SIMULATOR_AIC_METRICS = "PipeUtilization"
DEFAULT_FOLLOWUP_ACTION_ID = "collect_default_metric_followup"


@dataclass(frozen=True)
class LoggedRunResult:
    status: str
    returncode: int | None


@dataclass(frozen=True)
class CommandExecutionResult:
    stdout: str
    stderr: str
    returncode: int


class CommandRunner(Protocol):
    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        timeout_s: float | None = None,
    ) -> CommandExecutionResult:
        ...


class SubprocessCommandRunner:
    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        timeout_s: float | None = None,
    ) -> CommandExecutionResult:
        completed = subprocess.run(command, capture_output=True, text=True, cwd=cwd, timeout=timeout_s)
        return CommandExecutionResult(
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            returncode=completed.returncode,
        )


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


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    existing_file(path, label)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a top-level object")
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
    timeout_s: float | None = None,
    fatal: bool = True,
    runner: CommandRunner | None = None,
) -> LoggedRunResult:
    write_command(command_log_path(run_dir, command_name), command)
    command_runner = runner or SubprocessCommandRunner()
    try:
        completed = command_runner.run(command, cwd=cwd, timeout_s=timeout_s)
    except subprocess.TimeoutExpired as exc:
        stdout = decode_timeout_stream(exc.stdout)
        stderr = decode_timeout_stream(exc.stderr)
        if stderr and not stderr.endswith("\n"):
            stderr += "\n"
        stderr += f"{log_stem} timed out after {timeout_s} seconds\n"
        command_log_path(run_dir, f"{log_stem}.stdout").write_text(stdout, encoding="utf-8")
        command_log_path(run_dir, f"{log_stem}.stderr").write_text(stderr, encoding="utf-8")
        command_log_path(run_dir, f"{log_stem}.status").write_text("timeout\n", encoding="utf-8")
        if fatal:
            raise RuntimeError(f"{log_stem} timed out after {timeout_s} seconds") from exc
        return LoggedRunResult(status="timeout", returncode=None)

    command_log_path(run_dir, f"{log_stem}.stdout").write_text(completed.stdout, encoding="utf-8")
    command_log_path(run_dir, f"{log_stem}.stderr").write_text(completed.stderr, encoding="utf-8")
    command_log_path(run_dir, f"{log_stem}.status").write_text(f"{completed.returncode}\n", encoding="utf-8")
    if completed.returncode != 0:
        if fatal:
            raise RuntimeError(f"{log_stem} failed with exit status {completed.returncode}")
        return LoggedRunResult(status="failed", returncode=completed.returncode)
    return LoggedRunResult(status="succeeded", returncode=completed.returncode)


def decode_timeout_stream(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


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


def msprof_default_followup_command(run_dir: Path, application: Path) -> list[str]:
    return [
        "msprof",
        "op",
        f"--output={run_dir / 'reports' / 'followups' / DEFAULT_FOLLOWUP_ACTION_ID}",
        f"--application={application}",
        "--aic-metrics=Default",
    ]


def msprof_simulator_command(run_dir: Path, application: Path) -> list[str]:
    return [
        "msprof",
        "op",
        "simulator",
        f"--output={run_dir / 'reports' / 'sim'}",
        f"--application={application}",
        f"--aic-metrics={SIMULATOR_AIC_METRICS}",
    ]


def run_analysis_pipeline(run_dir: Path) -> None:
    generate_provenance.main(["--run-dir", str(run_dir)])
    evidence_model.write_evidence_model(run_dir)
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


def append_profile_context_warnings(run_dir: Path, warnings: list[str]) -> None:
    if not warnings:
        return
    path = run_dir / "analysis" / "profile_context.json"
    if not path.is_file():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    append_payload_warnings(payload, warnings)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_workflow_metadata(
    run_dir: Path,
    *,
    manifest_path: Path | None,
    application: Path,
    manifest: dict[str, Any] | None,
    verify_json_path: Path | None,
    preset_id: str,
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
        "collection_plan": collection_plan.profile_harness_plan(preset_id),
    }
    if preset_id in {"default-depth", "full"}:
        payload["commands"]["msprof_default_followup"] = (
            f"logs/command_msprof_followup_{DEFAULT_FOLLOWUP_ACTION_ID}.txt"
        )
        payload["outputs"]["default"] = f"reports/followups/{DEFAULT_FOLLOWUP_ACTION_ID}"
    if manifest is not None:
        payload["profile_harness"] = {
            "schema_version": manifest.get("schema_version"),
            "task": manifest.get("task"),
            "workload": manifest.get("workload"),
            "jit_config": manifest.get("jit_config"),
        }
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return out


def append_payload_warnings(payload: dict[str, Any], warnings: list[str]) -> None:
    existing = payload.setdefault("warnings", [])
    if isinstance(existing, list):
        existing.extend(warning for warning in warnings if warning not in existing)
    else:
        payload["warnings"] = warnings


def update_workflow_simulator_metadata(
    workflow_path: Path,
    *,
    preset_id: str,
    status: str,
    warnings: list[str],
) -> None:
    payload = json.loads(workflow_path.read_text(encoding="utf-8"))
    payload.setdefault("commands", {})["msprof_simulator"] = "logs/command_msprof_simulator.txt"
    payload.setdefault("outputs", {})["simulator"] = "reports/sim"
    payload["simulator"] = {
        "enabled": True,
        "aic_metrics": SIMULATOR_AIC_METRICS,
        "required": False,
        "status": status,
    }
    payload["collection_plan"] = collection_plan.profile_harness_plan(
        preset_id,
        simulator_status=status,
    )
    if warnings:
        append_payload_warnings(payload, warnings)
    workflow_path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def workflow_application(workflow: dict[str, Any]) -> Path:
    inputs = workflow.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("analysis/profile_harness_run.json missing inputs")
    raw_path = inputs.get("application_resolved_path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("analysis/profile_harness_run.json missing inputs.application_resolved_path")
    application = Path(raw_path).expanduser().resolve()
    existing_file(application, "profile harness application")
    return application


def followup_actions_from_summary(summary: dict[str, Any]) -> list[dict[str, Any]]:
    actions = summary.get("next_collection_actions")
    if not isinstance(actions, list) or not actions:
        readiness = summary.get("evidence_readiness")
        if isinstance(readiness, dict):
            actions = readiness.get("recommended_followups")
    if not isinstance(actions, list):
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in actions:
        if not isinstance(item, dict):
            continue
        action_id = item.get("id")
        if not isinstance(action_id, str) or not action_id.strip():
            action_id = "unknown"
        if action_id in seen:
            continue
        seen.add(action_id)
        normalized = dict(item)
        normalized["id"] = action_id
        out.append(normalized)
    return out


def target_consistency(summary: dict[str, Any]) -> tuple[str, str]:
    target = summary.get("target_identity")
    raw_status = target.get("status") if isinstance(target, dict) else None
    status = str(raw_status or "unknown")
    if status in {"mismatch", "partial_mismatch"}:
        return "blocked", f"target identity status is {status}"
    if status in {"", "unknown", "missing", "missing_observed", "not_applicable"}:
        return "limited", f"target identity status is {status or 'unknown'}"
    return "ok", f"target identity status is {status}"


def default_followup_paths(run_dir: Path) -> list[Path]:
    return [
        run_dir / "reports" / "followups" / DEFAULT_FOLLOWUP_ACTION_ID,
        run_dir / "logs" / f"command_msprof_followup_{DEFAULT_FOLLOWUP_ACTION_ID}.txt",
        run_dir / "logs" / f"msprof_followup_{DEFAULT_FOLLOWUP_ACTION_ID}.stdout",
        run_dir / "logs" / f"msprof_followup_{DEFAULT_FOLLOWUP_ACTION_ID}.stderr",
        run_dir / "logs" / f"msprof_followup_{DEFAULT_FOLLOWUP_ACTION_ID}.status",
    ]


def existing_default_followup_artifact(run_dir: Path) -> Path | None:
    for path in default_followup_paths(run_dir):
        if path.exists():
            return path
    return None


def append_followup_action_records(
    workflow_path: Path,
    records: list[dict[str, Any]],
    *,
    default_followup_command_recorded: bool,
    default_followup_output_recorded: bool,
) -> None:
    payload = load_json_object(workflow_path, "analysis/profile_harness_run.json")
    existing = payload.get("follow_up_actions")
    if not isinstance(existing, list):
        existing = []
    payload["follow_up_actions"] = [*existing, *records]
    if default_followup_command_recorded:
        payload.setdefault("commands", {})["msprof_default_followup"] = (
            f"logs/command_msprof_followup_{DEFAULT_FOLLOWUP_ACTION_ID}.txt"
        )
    if default_followup_output_recorded:
        payload.setdefault("outputs", {})["default"] = f"reports/followups/{DEFAULT_FOLLOWUP_ACTION_ID}"
    workflow_path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def continue_from_summary_followups(run_dir: Path) -> Path:
    run_dir = run_dir.expanduser().resolve()
    workflow_path = run_dir / "analysis" / "profile_harness_run.json"
    summary_path = run_dir / "analysis" / "summary.json"
    workflow = load_json_object(workflow_path, "analysis/profile_harness_run.json")
    summary = load_json_object(summary_path, "analysis/summary.json")
    application = workflow_application(workflow)
    actions = followup_actions_from_summary(summary)
    consistency, consistency_reason = target_consistency(summary)

    records: list[dict[str, Any]] = []
    default_command_recorded = False
    default_output_recorded = False
    failed: str | None = None
    for action in actions:
        action_id = str(action["id"])
        if action_id != DEFAULT_FOLLOWUP_ACTION_ID:
            records.append(
                {
                    "id": action_id,
                    "status": "skipped",
                    "reason": "unsupported follow-up action for profile-harness automation",
                    "consistency": consistency,
                }
            )
            continue

        record: dict[str, Any] = {
            "id": action_id,
            "command_key": "msprof_default_followup",
            "output_key": "default",
            "consistency": consistency,
        }
        if consistency == "blocked":
            record.update({"status": "blocked", "reason": consistency_reason})
            records.append(record)
            continue

        existing = existing_default_followup_artifact(run_dir)
        if existing is not None:
            record.update(
                {
                    "status": "blocked",
                    "reason": f"existing Default follow-up artifact would be overwritten: {rel_display(run_dir, existing)}",
                }
            )
            records.append(record)
            continue

        result = run_logged(
            msprof_default_followup_command(run_dir, application),
            run_dir,
            command_name=f"command_msprof_followup_{DEFAULT_FOLLOWUP_ACTION_ID}.txt",
            log_stem=f"msprof_followup_{DEFAULT_FOLLOWUP_ACTION_ID}",
            cwd=application.parent,
            fatal=False,
        )
        record["returncode"] = result.returncode
        default_command_recorded = True
        if result.status == "succeeded":
            default_output_recorded = True
            record.update({"status": "succeeded", "reason": action.get("reason") or "executed supported Default follow-up"})
            records.append(record)
        else:
            record.update({"status": result.status, "reason": f"Default follow-up {result.status}"})
            records.append(record)
            failed = f"Default follow-up {result.status}"

    if records:
        append_followup_action_records(
            workflow_path,
            records,
            default_followup_command_recorded=default_command_recorded,
            default_followup_output_recorded=default_output_recorded,
        )
    if failed is not None:
        raise RuntimeError(failed)
    if any(record.get("status") == "succeeded" for record in records):
        run_analysis_pipeline(run_dir)
    return workflow_path


def profile_harness(
    run_dir: Path,
    *,
    manifest_path: Path | None,
    application_path: Path | None,
    verify_json_path: Path | None,
    preset_id: str = "triage",
    simulator_enabled: bool = False,
    simulator_timeout_s: float | None = None,
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
        preset_id=preset_id,
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
    if preset_id in {"default-depth", "full"}:
        run_logged(
            msprof_default_followup_command(run_dir, application),
            run_dir,
            command_name=f"command_msprof_followup_{DEFAULT_FOLLOWUP_ACTION_ID}.txt",
            log_stem=f"msprof_followup_{DEFAULT_FOLLOWUP_ACTION_ID}",
            cwd=application.parent,
        )
    simulator_warnings: list[str] = []
    if simulator_enabled:
        simulator_result = run_logged(
            msprof_simulator_command(run_dir, application),
            run_dir,
            command_name="command_msprof_simulator.txt",
            log_stem="msprof_simulator",
            cwd=application.parent,
            timeout_s=simulator_timeout_s,
            fatal=False,
        )
        if simulator_result.status == "failed":
            simulator_warnings.append(
                "optional simulator collection failed with exit status "
                f"{simulator_result.returncode}; see logs/msprof_simulator.stderr"
            )
        elif simulator_result.status == "timeout":
            simulator_warnings.append(
                "optional simulator collection timed out; see logs/msprof_simulator.stderr"
            )
        append_profile_context_warnings(run_dir, simulator_warnings)
        update_workflow_simulator_metadata(
            workflow_path,
            preset_id=preset_id,
            status=simulator_result.status,
            warnings=simulator_warnings,
        )
    run_analysis_pipeline(run_dir)
    return workflow_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--manifest", type=Path)
    source.add_argument("--application", type=Path)
    ap.add_argument("--verify-json", type=Path)
    ap.add_argument("--preset", choices=collection_plan.PRESET_IDS, default="triage")
    ap.add_argument("--simulator", action="store_true", help="also collect optional msprof op simulator output")
    ap.add_argument("--simulator-timeout-s", type=float, help="optional timeout for simulator collection in seconds")
    ap.add_argument("--follow-next-actions", action="store_true", help="run supported follow-up actions from analysis/summary.json")
    ap.add_argument("--continue-from-summary", action="store_true", help="append supported follow-up actions to an existing profile-harness run")
    args = ap.parse_args(argv)
    if args.simulator_timeout_s is not None and args.simulator_timeout_s <= 0:
        print("error: --simulator-timeout-s must be greater than 0", file=sys.stderr)
        return 1
    if args.simulator_timeout_s is not None and not args.simulator:
        print("error: --simulator-timeout-s requires --simulator", file=sys.stderr)
        return 1
    if args.follow_next_actions != args.continue_from_summary:
        print("error: --follow-next-actions and --continue-from-summary must be used together", file=sys.stderr)
        return 1
    if args.continue_from_summary:
        if args.manifest is not None or args.application is not None or args.verify_json is not None:
            print("error: --continue-from-summary reuses existing workflow inputs; omit --manifest, --application, and --verify-json", file=sys.stderr)
            return 1
        if args.simulator:
            print("error: --continue-from-summary does not run simulator collection", file=sys.stderr)
            return 1
        if args.preset != "triage":
            print("error: --continue-from-summary cannot be combined with --preset orchestration", file=sys.stderr)
            return 1
        try:
            workflow_path = continue_from_summary_followups(args.run_dir)
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {workflow_path}")
        return 0
    if args.manifest is None and args.application is None:
        print("error: either --manifest or --application is required", file=sys.stderr)
        return 1

    try:
        workflow_path = profile_harness(
            args.run_dir,
            manifest_path=args.manifest,
            application_path=args.application,
            verify_json_path=args.verify_json,
            preset_id=args.preset,
            simulator_enabled=args.simulator,
            simulator_timeout_s=args.simulator_timeout_s,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {workflow_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
