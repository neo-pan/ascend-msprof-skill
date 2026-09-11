#!/usr/bin/env python3
"""Profile a supplied harness manifest or application with msprof."""
from __future__ import annotations

import argparse
import json
import os
import signal
import shlex
import shutil
import subprocess
import sys
import tempfile
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
    summarize_candidate,
)
from ._profiler_segments import (
    DEFAULT_FOLLOWUP_ACTION_ID,
    FOCUSED_DEFAULT_FOLLOWUP_PREFIX,
    focused_followup_action_id,
)
from ._profile_target import normalize_persisted_target, normalize_target_contract, validate_target_subset


SCHEMA_VERSION = 3
PROFILE_CONTEXT_SCHEMA_VERSION = 4
STALE_COLLECTION_ROOTS = ["reports", "logs", "analysis"]
STALE_TOP_LEVEL_FILES = ["REPORT.md"]
SIMULATOR_AIC_METRICS = "PipeUtilization"
DEFAULT_FOLLOWUP_COMMAND_ARTIFACT = f"logs/command_msprof_followup_{DEFAULT_FOLLOWUP_ACTION_ID}.txt"
DEFAULT_FOLLOWUP_OUTPUT_ARTIFACT = f"reports/followups/{DEFAULT_FOLLOWUP_ACTION_ID}"


@dataclass(frozen=True)
class LoggedRunResult:
    status: str
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    core_dumps: tuple[Path, ...] = ()
    output_staged_locally: bool = False
    preserved_output: str | None = None


@dataclass(frozen=True)
class ProfileHarnessRequest:
    run_dir: Path
    manifest_path: Path | None
    application_path: Path | None
    verify_json_path: Path | None
    preset_id: str = "triage"
    simulator_enabled: bool = False
    simulator_timeout_s: float | None = None
    summarize_candidate_enabled: bool = False


@dataclass(frozen=True)
class ResolvedProfileHarnessRequest:
    run_dir: Path
    manifest_path: Path | None
    manifest: dict[str, Any] | None
    application: Path
    verify_json_path: Path | None
    verify_json: dict[str, Any] | None
    target_selection: dict[str, Any] | None
    preset_id: str
    simulator_enabled: bool
    simulator_timeout_s: float | None
    summarize_candidate_enabled: bool


@dataclass(frozen=True)
class ProfileHarnessResult:
    workflow_path: Path
    command_results: dict[str, LoggedRunResult]
    simulator_warnings: tuple[str, ...]
    analysis_reran: bool


@dataclass(frozen=True)
class ContinueFollowupsRequest:
    run_dir: Path
    selected_action_id: str | None = None
    target_selection: dict[str, Any] | None = None
    summarize_candidate_enabled: bool = False


@dataclass(frozen=True)
class ContinueFollowupsResult:
    workflow_path: Path
    records: tuple[dict[str, Any], ...]
    command_results: dict[str, LoggedRunResult]
    analysis_reran: bool


@dataclass(frozen=True)
class FollowupActionDecision:
    record: dict[str, Any]
    execute_default_followup: bool = False
    target_selection: dict[str, Any] | None = None


@dataclass(frozen=True)
class DefaultFollowupLayout:
    segment_id: str
    command_key: str
    output_key: str

    @property
    def log_stem(self) -> str:
        return f"msprof_followup_{self.segment_id}"

    @property
    def command_artifact(self) -> str:
        return f"logs/command_{self.log_stem}.txt"

    @property
    def output_artifact(self) -> str:
        return f"reports/followups/{self.segment_id}"


@dataclass(frozen=True)
class CommandExecutionResult:
    stdout: str
    stderr: str
    returncode: int
    output_staged_locally: bool = False
    preserved_output: str | None = None


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
    def _run_subprocess(
        self,
        command: list[str],
        *,
        cwd: Path,
        timeout_s: float | None,
    ) -> subprocess.CompletedProcess[str]:
        if timeout_s is None:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=cwd,
            )

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            stdout = decode_timeout_stream(exc.stdout)
            stderr = decode_timeout_stream(exc.stderr)
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                terminated_stdout, terminated_stderr = process.communicate(timeout=1.0)
            except subprocess.TimeoutExpired:
                grace_expired = True
            else:
                grace_expired = False
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if grace_expired:
                terminated_stdout, terminated_stderr = process.communicate()
            stdout = terminated_stdout if terminated_stdout is not None else stdout
            stderr = terminated_stderr if terminated_stderr is not None else stderr
            raise subprocess.TimeoutExpired(
                command,
                timeout_s,
                output=stdout,
                stderr=stderr,
            ) from exc
        return subprocess.CompletedProcess(
            command,
            process.returncode,
            stdout,
            stderr,
        )

    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        timeout_s: float | None = None,
    ) -> CommandExecutionResult:
        output_option = _command_output_option(command)
        if Path(command[0]).name != "msprof" or output_option is None:
            completed = self._run_subprocess(
                command,
                cwd=cwd,
                timeout_s=timeout_s,
            )
            return CommandExecutionResult(
                stdout=completed.stdout or "",
                stderr=completed.stderr or "",
                returncode=completed.returncode,
            )

        output_index, final_output = output_option
        stage_root = Path(os.environ.get("ASCEND_MSPROF_STAGE_ROOT", "/tmp"))
        stage_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="ascend-msprof-stage-",
            dir=stage_root,
        ) as temporary_dir:
            staged_output = Path(temporary_dir) / "output"
            staged_command = list(command)
            if command[output_index] == "--output":
                staged_command[output_index + 1] = str(staged_output)
            else:
                staged_command[output_index] = f"--output={staged_output}"
            timeout_error: subprocess.TimeoutExpired | None = None
            output_staged_locally = False
            preserved_output: str | None = None
            try:
                completed = self._run_subprocess(
                    staged_command,
                    cwd=cwd,
                    timeout_s=timeout_s,
                )
            except subprocess.TimeoutExpired as exc:
                timeout_error = exc
            finally:
                if staged_output.exists():
                    if final_output.exists():
                        raise RuntimeError(
                            f"refusing to overwrite profiler output: {final_output}"
                        )
                    final_output.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(staged_output, final_output)
                    output_staged_locally = True
                    preserved_output = str(final_output)
            if timeout_error is not None:
                timeout_error.output_staged_locally = output_staged_locally
                timeout_error.preserved_output = preserved_output
                raise timeout_error
        return CommandExecutionResult(
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            returncode=completed.returncode,
            output_staged_locally=output_staged_locally,
            preserved_output=preserved_output,
        )


def _command_output_option(command: list[str]) -> tuple[int, Path] | None:
    for index, token in enumerate(command):
        if token == "--output" and index + 1 < len(command):
            return index, Path(command[index + 1]).expanduser().resolve(strict=False)
        if token.startswith("--output="):
            raw_output = token.removeprefix("--output=")
            if raw_output:
                return index, Path(raw_output).expanduser().resolve(strict=False)
    return None


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


def load_followup_target(path: Path) -> dict[str, Any]:
    payload = load_json_object(path.expanduser().resolve(), "follow-up target JSON")
    target = normalize_target_contract(payload if "target" in payload else {"target": payload})
    if target is None:
        raise ValueError("follow-up target JSON must contain a target contract")
    return target


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


def _top_level_core_dumps(cwd: Path) -> set[Path]:
    return {
        path.resolve()
        for path in cwd.iterdir()
        if path.is_file() and (path.name == "core" or path.name.startswith("core."))
    }


def write_command_result(
    run_dir: Path,
    log_stem: str,
    *,
    status: str,
    process_returncode: int | None,
    core_dumps: list[Path] | None = None,
    output_staged_locally: bool = False,
    preserved_output: str | None = None,
) -> None:
    payload = {
        "status": status,
        "process_returncode": process_returncode,
        "retryable_infrastructure_failure": status in {"core_dump", "timeout"},
        "core_dumps": [str(path) for path in (core_dumps or [])],
        "output_staged_locally": output_staged_locally,
        "preserved_output": preserved_output,
    }
    command_log_path(run_dir, f"{log_stem}.result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
    core_dumps_before = _top_level_core_dumps(cwd)
    try:
        completed = command_runner.run(command, cwd=cwd, timeout_s=timeout_s)
    except subprocess.TimeoutExpired as exc:
        stdout = decode_timeout_stream(exc.stdout)
        stderr = decode_timeout_stream(exc.stderr)
        new_core_dumps = sorted(_top_level_core_dumps(cwd) - core_dumps_before)
        logical_status = "core_dump" if new_core_dumps else "timeout"
        output_staged_locally = bool(
            getattr(exc, "output_staged_locally", False)
        )
        preserved_output = getattr(exc, "preserved_output", None)
        if stderr and not stderr.endswith("\n"):
            stderr += "\n"
        stderr += f"{log_stem} timed out after {timeout_s} seconds\n"
        if new_core_dumps:
            stderr += (
                "new core dump after timeout: "
                + ", ".join(str(path) for path in new_core_dumps)
                + "\n"
            )
        command_log_path(run_dir, f"{log_stem}.stdout").write_text(stdout, encoding="utf-8")
        command_log_path(run_dir, f"{log_stem}.stderr").write_text(stderr, encoding="utf-8")
        command_log_path(run_dir, f"{log_stem}.status").write_text("timeout\n", encoding="utf-8")
        write_command_result(
            run_dir,
            log_stem,
            status=logical_status,
            process_returncode=None,
            core_dumps=new_core_dumps,
            output_staged_locally=output_staged_locally,
            preserved_output=preserved_output,
        )
        if fatal:
            if new_core_dumps:
                core_paths = ", ".join(str(path) for path in new_core_dumps)
                raise RuntimeError(
                    f"{log_stem} produced a core dump after timeout: {core_paths}"
                ) from exc
            raise RuntimeError(f"{log_stem} timed out after {timeout_s} seconds") from exc
        return LoggedRunResult(
            status=logical_status,
            returncode=None,
            stdout=stdout,
            stderr=stderr,
            core_dumps=tuple(new_core_dumps),
            output_staged_locally=output_staged_locally,
            preserved_output=preserved_output,
        )

    stderr = completed.stderr
    new_core_dumps = sorted(_top_level_core_dumps(cwd) - core_dumps_before)
    core_dump_failure = bool(new_core_dumps)
    if core_dump_failure:
        if stderr and not stderr.endswith("\n"):
            stderr += "\n"
        stderr += (
            f"new core dump after exit status {completed.returncode}: "
            + ", ".join(str(path) for path in new_core_dumps)
            + "\n"
        )

    command_log_path(run_dir, f"{log_stem}.stdout").write_text(completed.stdout, encoding="utf-8")
    command_log_path(run_dir, f"{log_stem}.stderr").write_text(stderr, encoding="utf-8")
    command_log_path(run_dir, f"{log_stem}.status").write_text(f"{completed.returncode}\n", encoding="utf-8")
    if core_dump_failure:
        write_command_result(
            run_dir,
            log_stem,
            status="core_dump",
            process_returncode=completed.returncode,
            core_dumps=new_core_dumps,
            output_staged_locally=completed.output_staged_locally,
            preserved_output=completed.preserved_output,
        )
        core_paths = ", ".join(str(path) for path in new_core_dumps)
        message = (
            f"{log_stem} produced a core dump with exit status "
            f"{completed.returncode}: {core_paths}"
        )
        if fatal:
            raise RuntimeError(message)
        return LoggedRunResult(
            status="core_dump",
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=stderr,
            core_dumps=tuple(new_core_dumps),
            output_staged_locally=completed.output_staged_locally,
            preserved_output=completed.preserved_output,
        )
    if completed.returncode != 0:
        write_command_result(
            run_dir,
            log_stem,
            status="failed",
            process_returncode=completed.returncode,
            output_staged_locally=completed.output_staged_locally,
            preserved_output=completed.preserved_output,
        )
        if fatal:
            raise RuntimeError(f"{log_stem} failed with exit status {completed.returncode}")
        return LoggedRunResult(
            status="failed",
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=stderr,
            output_staged_locally=completed.output_staged_locally,
            preserved_output=completed.preserved_output,
        )
    write_command_result(
        run_dir,
        log_stem,
        status="succeeded",
        process_returncode=completed.returncode,
        output_staged_locally=completed.output_staged_locally,
        preserved_output=completed.preserved_output,
    )
    return LoggedRunResult(
        status="succeeded",
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=stderr,
        output_staged_locally=completed.output_staged_locally,
        preserved_output=completed.preserved_output,
    )


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


def target_collection_args(target_selection: dict[str, Any] | None) -> list[str]:
    if target_selection is None:
        return []
    return [
        f"--kernel-name={target_selection['kernel_selector']}",
        f"--launch-count={target_selection['launch_count']}",
        "--warm-up=0",
        "--replay-mode=application",
    ]


def default_followup_layout(target_selection: dict[str, Any] | None = None) -> DefaultFollowupLayout:
    if target_selection is None:
        segment_id = DEFAULT_FOLLOWUP_ACTION_ID
        command_key = "msprof_default_followup"
        output_key = "default"
    else:
        segment_id = focused_followup_action_id(target_selection)
        digest = segment_id.removeprefix(FOCUSED_DEFAULT_FOLLOWUP_PREFIX)
        command_key = f"msprof_default_followup_focused_{digest}"
        output_key = f"default_focused_{digest}"
    return DefaultFollowupLayout(
        segment_id=segment_id,
        command_key=command_key,
        output_key=output_key,
    )


def msprof_op_command(
    run_dir: Path,
    application: Path,
    target_selection: dict[str, Any] | None = None,
) -> list[str]:
    return [
        "msprof",
        "op",
        f"--output={run_dir / 'reports' / 'op'}",
        f"--application={application}",
        "--aic-metrics=PipeUtilization",
        *target_collection_args(target_selection),
    ]


def msprof_default_followup_command(
    run_dir: Path,
    application: Path,
    target_selection: dict[str, Any] | None = None,
    *,
    focused_target_selection: dict[str, Any] | None = None,
) -> list[str]:
    layout = default_followup_layout(focused_target_selection)
    return [
        "msprof",
        "op",
        f"--output={run_dir / layout.output_artifact}",
        f"--application={application}",
        "--aic-metrics=Default",
        *target_collection_args(target_selection),
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
    run_profile_harness_analysis(run_dir)


def run_profile_harness_analysis(run_dir: Path) -> None:
    generate_provenance.main(["--run-dir", str(run_dir)])
    evidence_model.write_evidence_model(run_dir)
    extract_simulator_hotspots.main(["--run-dir", str(run_dir)])
    plot_timeline.main(["--run-dir", str(run_dir)])
    generate_report.main(["--run-dir", str(run_dir)])


def manifest_context(
    manifest: dict[str, Any] | None,
    target_selection: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if manifest is None:
        return None
    context = {
        "schema_version": collect_tilelang_context.sanitize_value(manifest.get("schema_version")),
        "task": collect_tilelang_context.sanitize_value(manifest.get("task")),
        "application": collect_tilelang_context.sanitize_value(manifest.get("application")),
        "workload": collect_tilelang_context.sanitize_value(manifest.get("workload")),
        "jit_config": collect_tilelang_context.sanitize_value(manifest.get("jit_config")),
        "metadata": collect_tilelang_context.sanitize_value(manifest.get("metadata")),
    }
    if target_selection is not None:
        context["target"] = collect_tilelang_context.sanitize_value(target_selection)
    return context


def write_profile_context(
    run_dir: Path,
    *,
    manifest_path: Path | None,
    manifest: dict[str, Any] | None,
    application: Path,
    verify_json_path: Path | None,
    verify_json: dict[str, Any] | None,
    target_selection: dict[str, Any] | None = None,
) -> Path:
    return ProfileHarnessArtifacts(run_dir).write_profile_context(
        manifest_path=manifest_path,
        manifest=manifest,
        application=application,
        verify_json_path=verify_json_path,
        verify_json=verify_json,
        target_selection=target_selection,
    )


def append_profile_context_warnings(run_dir: Path, warnings: list[str]) -> None:
    ProfileHarnessArtifacts(run_dir).append_profile_context_warnings(warnings)


def write_workflow_metadata(
    run_dir: Path,
    *,
    manifest_path: Path | None,
    application: Path,
    manifest: dict[str, Any] | None,
    verify_json_path: Path | None,
    preset_id: str,
    target_selection: dict[str, Any] | None = None,
) -> Path:
    return ProfileHarnessArtifacts(run_dir).write_workflow_metadata(
        manifest_path=manifest_path,
        application=application,
        manifest=manifest,
        verify_json_path=verify_json_path,
        preset_id=preset_id,
        target_selection=target_selection,
    )


def append_payload_warnings(payload: dict[str, Any], warnings: list[str]) -> None:
    existing = payload.setdefault("warnings", [])
    if isinstance(existing, list):
        existing.extend(warning for warning in warnings if warning not in existing)
    else:
        payload["warnings"] = warnings


def normalize_profile_benchmark(verify_json: dict[str, Any]) -> dict[str, Any]:
    benchmark = collect_tilelang_context.normalize_benchmark(verify_json)
    workload = verify_json.get("workload")
    if isinstance(workload, dict):
        benchmark_workload = benchmark.setdefault("workload", {})
        for output_key, input_keys in {
            "id": ["task_name", "id", "operator_type"],
            "shape": ["shape"],
            "dtype": ["dtype"],
            "case_count": ["case_count"],
        }.items():
            for input_key in input_keys:
                value = workload.get(input_key)
                if value not in (None, "", [], {}):
                    benchmark_workload[output_key] = collect_tilelang_context.sanitize_value(value)
                    break
    correctness = verify_json.get("correctness")
    if isinstance(correctness, dict):
        receipt = correctness.get("receipt")
        if isinstance(receipt, dict) and benchmark["workload"].get("case_count") in (None, 1):
            case_count = receipt.get("case_count")
            if isinstance(case_count, int) and not isinstance(case_count, bool) and case_count > 0:
                benchmark["workload"]["case_count"] = case_count
    candidate = verify_json.get("candidate")
    if isinstance(candidate, dict) and isinstance(candidate.get("compiled"), bool):
        benchmark["candidate"]["compiled"] = candidate["compiled"]
    official_timing = verify_json.get("official_timing")
    if isinstance(official_timing, dict):
        latency_ms = official_timing.get("latency_ms")
        if isinstance(latency_ms, (int, float)) and not isinstance(latency_ms, bool):
            statistic = official_timing.get("aggregation") or "unspecified"
            runtime_stats = {
                "value_ms": latency_ms,
                "statistic": statistic,
                "samples_ms": official_timing.get("samples_ms"),
                "authority": official_timing.get("authority"),
                "latency_source": official_timing.get("latency_source"),
            }
            if statistic == "mean":
                runtime_stats["mean_ms"] = latency_ms
            benchmark["candidate"]["runtime"] = latency_ms
            benchmark["candidate"]["runtime_stats"] = collect_tilelang_context.sanitize_value(runtime_stats)
    return benchmark


def write_json_artifact(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


class ProfileHarnessArtifacts:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.analysis_dir = run_dir / "analysis"
        self.profile_context_path = self.analysis_dir / "profile_context.json"
        self.workflow_metadata_path = self.analysis_dir / "profile_harness_run.json"

    def write_profile_context(
        self,
        *,
        manifest_path: Path | None,
        manifest: dict[str, Any] | None,
        application: Path,
        verify_json_path: Path | None,
        verify_json: dict[str, Any] | None,
        target_selection: dict[str, Any] | None = None,
    ) -> Path:
        sources: dict[str, Any] = {
            "application": {
                "artifact": rel_display(self.run_dir, application),
                "resolved_path": str(application),
                "sha256": collect_tilelang_context.sha256_file(application),
                "size_bytes": application.stat().st_size,
            }
        }
        if manifest_path is not None:
            sources["profile_harness_manifest"] = collect_tilelang_context.file_record(self.run_dir, manifest_path)
        if verify_json_path is not None:
            sources["verify_json"] = collect_tilelang_context.file_record(self.run_dir, verify_json_path)

        payload: dict[str, Any] = {
            "schema_version": PROFILE_CONTEXT_SCHEMA_VERSION,
            "sources": sources,
            "profile_harness": manifest_context(manifest, target_selection)
            or {
                "application": rel_display(self.run_dir, application),
                "workload": None,
                "jit_config": None,
                "metadata": None,
            },
            "warnings": [],
        }
        if verify_json is not None:
            payload["benchmark"] = normalize_profile_benchmark(verify_json)
            payload["verify_context"] = {
                "raw": collect_tilelang_context.sanitize_value(verify_json),
                "evidence_role": "correctness_and_timing_context_only",
            }
        if verify_json_path is not None:
            from .collect_benchmark_context import import_benchmark
            from .benchmark_evidence import ARTIFACT
            try:
                evidence = import_benchmark(self.run_dir, verify_json_path, entrypoint="profile-harness", optional=True)
                if evidence is not None:
                    payload["benchmark_assessment"] = {"artifact": ARTIFACT}
                    payload["benchmark_issues"] = list(evidence.issues)
            except (OSError, ValueError) as exc:
                payload["benchmark_issues"] = [{"reason_code": "benchmark_import_error", "message": str(exc)}]
        write_json_artifact(self.profile_context_path, payload)
        return self.profile_context_path

    def append_profile_context_warnings(self, warnings: list[str]) -> None:
        if not warnings or not self.profile_context_path.is_file():
            return
        payload = load_json_object(self.profile_context_path, "analysis/profile_context.json")
        append_payload_warnings(payload, warnings)
        write_json_artifact(self.profile_context_path, payload)

    def write_workflow_metadata(
        self,
        *,
        manifest_path: Path | None,
        application: Path,
        manifest: dict[str, Any] | None,
        verify_json_path: Path | None,
        preset_id: str,
        target_selection: dict[str, Any] | None = None,
    ) -> Path:
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "workflow": "generic profile harness profiling workflow",
            "inputs": {
                "manifest": rel_display(self.run_dir, manifest_path) if manifest_path else None,
                "application": rel_display(self.run_dir, application),
                "application_resolved_path": str(application),
                "verify_json": rel_display(self.run_dir, verify_json_path) if verify_json_path else None,
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
            payload["commands"]["msprof_default_followup"] = DEFAULT_FOLLOWUP_COMMAND_ARTIFACT
            payload["outputs"]["default"] = DEFAULT_FOLLOWUP_OUTPUT_ARTIFACT
        if manifest is not None:
            payload["profile_harness"] = {
                "schema_version": manifest.get("schema_version"),
                "task": manifest.get("task"),
                "workload": manifest.get("workload"),
                "jit_config": manifest.get("jit_config"),
            }
        if target_selection is not None:
            payload["target_selection"] = collect_tilelang_context.sanitize_value(target_selection)
        write_json_artifact(self.workflow_metadata_path, payload)
        return self.workflow_metadata_path

    def update_simulator_metadata(
        self,
        *,
        preset_id: str,
        status: str,
        warnings: list[str],
    ) -> None:
        payload = load_json_object(self.workflow_metadata_path, "analysis/profile_harness_run.json")
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
        write_json_artifact(self.workflow_metadata_path, payload)

    def append_followup_action_records(
        self,
        records: list[dict[str, Any]],
        *,
        recorded_commands: dict[str, str],
        recorded_outputs: dict[str, str],
    ) -> None:
        payload = load_json_object(self.workflow_metadata_path, "analysis/profile_harness_run.json")
        existing = payload.get("follow_up_actions")
        if not isinstance(existing, list):
            existing = []
        payload["follow_up_actions"] = [*existing, *records]
        payload.setdefault("commands", {}).update(recorded_commands)
        payload.setdefault("outputs", {}).update(recorded_outputs)
        write_json_artifact(self.workflow_metadata_path, payload)

    def record_candidate_summary_outputs(self) -> None:
        payload = load_json_object(self.workflow_metadata_path, "analysis/profile_harness_run.json")
        payload.setdefault("outputs", {})["candidate_summary"] = "analysis/candidate_summary.json"
        payload["outputs"]["candidate_summary_markdown"] = "analysis/candidate_summary.md"
        write_json_artifact(self.workflow_metadata_path, payload)


def update_workflow_simulator_metadata(
    workflow_path: Path,
    *,
    preset_id: str,
    status: str,
    warnings: list[str],
) -> None:
    ProfileHarnessArtifacts(workflow_path.parent.parent).update_simulator_metadata(
        preset_id=preset_id,
        status=status,
        warnings=warnings,
    )


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


def workflow_target_selection(workflow: dict[str, Any]) -> dict[str, Any] | None:
    persisted = workflow.get("target_selection")
    if persisted is None:
        return None
    if not isinstance(persisted, dict):
        raise ValueError("analysis/profile_harness_run.json target_selection must contain an object")
    return normalize_persisted_target(persisted)


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


def default_followup_paths(
    run_dir: Path,
    target_selection: dict[str, Any] | None = None,
) -> list[Path]:
    layout = default_followup_layout(target_selection)
    return [
        run_dir / layout.output_artifact,
        run_dir / layout.command_artifact,
        run_dir / "logs" / f"{layout.log_stem}.stdout",
        run_dir / "logs" / f"{layout.log_stem}.stderr",
        run_dir / "logs" / f"{layout.log_stem}.status",
    ]


def existing_default_followup_artifact(
    run_dir: Path,
    target_selection: dict[str, Any] | None = None,
) -> Path | None:
    for path in default_followup_paths(run_dir, target_selection):
        if path.exists():
            return path
    return None


def plan_followup_actions(
    run_dir: Path,
    summary: dict[str, Any],
    *,
    selected_action_id: str | None = None,
    target_selection: dict[str, Any] | None = None,
) -> tuple[FollowupActionDecision, ...]:
    actions = followup_actions_from_summary(summary)
    action_ids = {str(action["id"]) for action in actions}
    if selected_action_id is not None and selected_action_id not in action_ids:
        raise ValueError(f"selected follow-up action is not pending: {selected_action_id}")
    if target_selection is not None and selected_action_id != DEFAULT_FOLLOWUP_ACTION_ID:
        raise ValueError("--follow-target-json requires --follow-action collect_default_metric_followup")
    consistency, consistency_reason = target_consistency(summary)
    decisions: list[FollowupActionDecision] = []
    for action in actions:
        action_id = str(action["id"])
        necessity = str(action.get("necessity") or "blocking")
        if action_id != DEFAULT_FOLLOWUP_ACTION_ID:
            decisions.append(
                FollowupActionDecision(
                    record={
                        "id": action_id,
                        "status": "skipped",
                        "reason": "unsupported follow-up action for profile-harness automation",
                        "consistency": consistency,
                        "necessity": necessity,
                    }
                )
            )
            continue

        layout = default_followup_layout(target_selection)
        record: dict[str, Any] = {
            "id": action_id,
            "segment_id": layout.segment_id,
            "command_key": layout.command_key,
            "output_key": layout.output_key,
            "consistency": consistency,
            "necessity": necessity,
            "unlocks_claims": [
                str(claim)
                for claim in action.get("unlocks_claims", [])
                if isinstance(claim, str) and claim.strip()
            ],
        }
        if selected_action_id != action_id and necessity != "blocking":
            record.update(
                {
                    "status": "skipped",
                    "reason": f"{necessity} action requires explicit --follow-action selection",
                }
            )
            decisions.append(FollowupActionDecision(record=record))
            continue
        if consistency == "blocked":
            record.update({"status": "blocked", "reason": consistency_reason})
            decisions.append(FollowupActionDecision(record=record))
            continue

        existing = existing_default_followup_artifact(run_dir, target_selection)
        if existing is not None:
            record.update(
                {
                    "status": "blocked",
                    "reason": f"existing Default follow-up artifact would be overwritten: {rel_display(run_dir, existing)}",
                }
            )
            decisions.append(FollowupActionDecision(record=record))
            continue

        record["reason"] = action.get("reason") or "executed supported Default follow-up"
        if target_selection is not None:
            record["target_selection"] = collect_tilelang_context.sanitize_value(target_selection)
            record["target_scope"] = {
                "kind": "focused_subset",
                "kernel_selector": target_selection["kernel_selector"],
                "expected_total": target_selection["launch_count"],
            }
        else:
            record["target_scope"] = action.get("target_scope") or {"kind": "complete_program"}
        decisions.append(
            FollowupActionDecision(
                record=record,
                execute_default_followup=True,
                target_selection=target_selection,
            )
        )
    return tuple(decisions)


def append_followup_action_records(
    workflow_path: Path,
    records: list[dict[str, Any]],
    *,
    recorded_commands: dict[str, str],
    recorded_outputs: dict[str, str],
) -> None:
    ProfileHarnessArtifacts(workflow_path.parent.parent).append_followup_action_records(
        records,
        recorded_commands=recorded_commands,
        recorded_outputs=recorded_outputs,
    )


def _run_continue_followups_workflow(
    request: ContinueFollowupsRequest,
    *,
    runner: CommandRunner,
) -> ContinueFollowupsResult:
    run_dir = request.run_dir.expanduser().resolve()
    workflow_path = run_dir / "analysis" / "profile_harness_run.json"
    summary_path = run_dir / "analysis" / "summary.json"
    artifacts = ProfileHarnessArtifacts(run_dir)
    workflow = load_json_object(workflow_path, "analysis/profile_harness_run.json")
    summary = load_json_object(summary_path, "analysis/summary.json")
    application = workflow_application(workflow)
    program_target = workflow_target_selection(workflow)
    target_selection = validate_target_subset(program_target, request.target_selection)
    decisions = plan_followup_actions(
        run_dir,
        summary,
        selected_action_id=request.selected_action_id,
        target_selection=target_selection,
    )

    records: list[dict[str, Any]] = []
    command_results: dict[str, LoggedRunResult] = {}
    recorded_commands: dict[str, str] = {}
    recorded_outputs: dict[str, str] = {}
    failed: str | None = None
    for decision in decisions:
        record = dict(decision.record)
        if not decision.execute_default_followup:
            records.append(record)
            continue

        try:
            generate_provenance.require_matching_cann_environment(run_dir)
        except RuntimeError as exc:
            failed = str(exc)
            record.update({"status": "blocked", "reason": failed})
            records.append(record)
            continue
        layout = default_followup_layout(decision.target_selection)
        result = run_logged(
            msprof_default_followup_command(
                run_dir,
                application,
                decision.target_selection or program_target,
                focused_target_selection=decision.target_selection,
            ),
            run_dir,
            command_name=Path(layout.command_artifact).name,
            log_stem=layout.log_stem,
            cwd=application.parent,
            fatal=False,
            runner=runner,
        )
        command_results[layout.command_key] = result
        record["returncode"] = result.returncode
        recorded_commands[layout.command_key] = layout.command_artifact
        if result.status == "succeeded":
            recorded_outputs[layout.output_key] = layout.output_artifact
            record["status"] = "succeeded"
            records.append(record)
        else:
            record.update({"status": result.status, "reason": f"Default follow-up {result.status}"})
            records.append(record)
            failed = f"Default follow-up {result.status}"

    if records:
        artifacts.append_followup_action_records(
            records,
            recorded_commands=recorded_commands,
            recorded_outputs=recorded_outputs,
        )
    if failed is not None:
        raise RuntimeError(failed)
    analysis_reran = any(record.get("status") == "succeeded" for record in records)
    if analysis_reran:
        run_profile_harness_analysis(run_dir)
    if request.summarize_candidate_enabled:
        summarize_candidate.write_candidate_summary(run_dir)
        artifacts.record_candidate_summary_outputs()
    return ContinueFollowupsResult(
        workflow_path=workflow_path,
        records=tuple(records),
        command_results=command_results,
        analysis_reran=analysis_reran,
    )


def continue_from_summary_followups(
    run_dir: Path,
    *,
    selected_action_id: str | None = None,
    target_selection: dict[str, Any] | None = None,
    summarize_candidate_enabled: bool = False,
) -> Path:
    result = _run_continue_followups_workflow(
        ContinueFollowupsRequest(
            run_dir=run_dir,
            selected_action_id=selected_action_id,
            target_selection=target_selection,
            summarize_candidate_enabled=summarize_candidate_enabled,
        ),
        runner=SubprocessCommandRunner(),
    )
    return result.workflow_path


def _resolve_profile_harness_request(request: ProfileHarnessRequest) -> ResolvedProfileHarnessRequest:
    run_dir = request.run_dir.expanduser().resolve()
    manifest: dict[str, Any] | None = None
    manifest_path = request.manifest_path
    application_path = request.application_path
    verify_json_path = request.verify_json_path
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
    target_selection = normalize_target_contract(manifest)
    return ResolvedProfileHarnessRequest(
        run_dir=run_dir,
        manifest_path=manifest_path,
        manifest=manifest,
        application=application,
        verify_json_path=verify_json_path,
        verify_json=verify_json,
        target_selection=target_selection,
        preset_id=request.preset_id,
        simulator_enabled=request.simulator_enabled,
        simulator_timeout_s=request.simulator_timeout_s,
        summarize_candidate_enabled=request.summarize_candidate_enabled,
    )


def _run_profile_harness_workflow(
    request: ProfileHarnessRequest,
    *,
    runner: CommandRunner,
) -> ProfileHarnessResult:
    resolved = _resolve_profile_harness_request(request)
    run_dir = resolved.run_dir
    application = resolved.application
    artifacts = ProfileHarnessArtifacts(run_dir)
    ensure_fresh_collection_run(run_dir)
    (run_dir / "reports").mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "analysis").mkdir(parents=True, exist_ok=True)
    artifacts.write_profile_context(
        manifest_path=resolved.manifest_path,
        manifest=resolved.manifest,
        application=application,
        verify_json_path=resolved.verify_json_path,
        verify_json=resolved.verify_json,
        target_selection=resolved.target_selection,
    )
    workflow_path = artifacts.write_workflow_metadata(
        manifest_path=resolved.manifest_path,
        application=application,
        manifest=resolved.manifest,
        verify_json_path=resolved.verify_json_path,
        preset_id=resolved.preset_id,
        target_selection=resolved.target_selection,
    )

    command_results: dict[str, LoggedRunResult] = {}
    generate_provenance.collect_environment(run_dir / "logs", "msprof")
    command_results["msprof"] = run_logged(
        msprof_app_command(run_dir, application),
        run_dir,
        command_name="command_msprof.txt",
        log_stem="msprof_default",
        cwd=application.parent,
        runner=runner,
    )
    command_results["msprof_op"] = run_logged(
        msprof_op_command(run_dir, application, resolved.target_selection),
        run_dir,
        command_name="command_msprof_op.txt",
        log_stem="msprof_op",
        cwd=application.parent,
        runner=runner,
    )
    if resolved.preset_id in {"default-depth", "full"}:
        command_results["msprof_default_followup"] = run_logged(
            msprof_default_followup_command(run_dir, application, resolved.target_selection),
            run_dir,
            command_name=f"command_msprof_followup_{DEFAULT_FOLLOWUP_ACTION_ID}.txt",
            log_stem=f"msprof_followup_{DEFAULT_FOLLOWUP_ACTION_ID}",
            cwd=application.parent,
            runner=runner,
        )
    simulator_warnings: list[str] = []
    if resolved.simulator_enabled:
        simulator_result = run_logged(
            msprof_simulator_command(run_dir, application),
            run_dir,
            command_name="command_msprof_simulator.txt",
            log_stem="msprof_simulator",
            cwd=application.parent,
            timeout_s=resolved.simulator_timeout_s,
            fatal=False,
            runner=runner,
        )
        command_results["msprof_simulator"] = simulator_result
        if simulator_result.status == "failed":
            simulator_warnings.append(
                "optional simulator collection failed with exit status "
                f"{simulator_result.returncode}; see logs/msprof_simulator.stderr"
            )
        elif simulator_result.status == "core_dump":
            simulator_warnings.append(
                "optional simulator collection produced a core dump; "
                "see logs/msprof_simulator.stderr"
            )
        elif simulator_result.status == "timeout":
            simulator_warnings.append(
                "optional simulator collection timed out; see logs/msprof_simulator.stderr"
            )
        artifacts.append_profile_context_warnings(simulator_warnings)
        artifacts.update_simulator_metadata(
            preset_id=resolved.preset_id,
            status=simulator_result.status,
            warnings=simulator_warnings,
        )
    run_profile_harness_analysis(run_dir)
    if resolved.summarize_candidate_enabled:
        summarize_candidate.write_candidate_summary(run_dir)
        artifacts.record_candidate_summary_outputs()
    return ProfileHarnessResult(
        workflow_path=workflow_path,
        command_results=command_results,
        simulator_warnings=tuple(simulator_warnings),
        analysis_reran=True,
    )


def profile_harness(
    run_dir: Path,
    *,
    manifest_path: Path | None,
    application_path: Path | None,
    verify_json_path: Path | None,
    preset_id: str = "triage",
    simulator_enabled: bool = False,
    simulator_timeout_s: float | None = None,
    summarize_candidate_enabled: bool = False,
) -> Path:
    result = _run_profile_harness_workflow(
        ProfileHarnessRequest(
            run_dir=run_dir,
            manifest_path=manifest_path,
            application_path=application_path,
            verify_json_path=verify_json_path,
            preset_id=preset_id,
            simulator_enabled=simulator_enabled,
            simulator_timeout_s=simulator_timeout_s,
            summarize_candidate_enabled=summarize_candidate_enabled,
        ),
        runner=SubprocessCommandRunner(),
    )
    return result.workflow_path


def validate_profile_harness_cli_args(args: argparse.Namespace) -> str | None:
    if args.simulator_timeout_s is not None and args.simulator_timeout_s <= 0:
        return "--simulator-timeout-s must be greater than 0"
    if args.simulator_timeout_s is not None and not args.simulator:
        return "--simulator-timeout-s requires --simulator"
    if args.follow_next_actions != args.continue_from_summary:
        return "--follow-next-actions and --continue-from-summary must be used together"
    follow_action = getattr(args, "follow_action", None)
    follow_target_json = getattr(args, "follow_target_json", None)
    if (follow_action is not None or follow_target_json is not None) and not args.continue_from_summary:
        return "--follow-action and --follow-target-json require --continue-from-summary"
    if follow_target_json is not None and follow_action is None:
        return "--follow-target-json requires --follow-action"
    if args.continue_from_summary:
        if args.manifest is not None or args.application is not None or args.verify_json is not None:
            return "--continue-from-summary reuses existing workflow inputs; omit --manifest, --application, and --verify-json"
        if args.simulator:
            return "--continue-from-summary does not run simulator collection"
        if args.preset != "triage":
            return "--continue-from-summary cannot be combined with --preset orchestration"
        return None
    if args.manifest is None and args.application is None:
        return "either --manifest or --application is required"
    return None


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
    ap.add_argument("--follow-action", help="explicitly select one hypothesis-required follow-up action")
    ap.add_argument("--follow-target-json", type=Path, help="focused target contract for the selected follow-up action")
    ap.add_argument("--summarize-candidate", action="store_true", help="write candidate summary from existing derived evidence after analysis")
    args = ap.parse_args(argv)
    validation_error = validate_profile_harness_cli_args(args)
    if validation_error is not None:
        print(f"error: {validation_error}", file=sys.stderr)
        return 1
    if args.continue_from_summary:
        try:
            target_selection = load_followup_target(args.follow_target_json) if args.follow_target_json else None
            workflow_path = continue_from_summary_followups(
                args.run_dir,
                selected_action_id=args.follow_action,
                target_selection=target_selection,
                summarize_candidate_enabled=args.summarize_candidate,
            )
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {workflow_path}")
        return 0

    try:
        workflow_path = profile_harness(
            args.run_dir,
            manifest_path=args.manifest,
            application_path=args.application,
            verify_json_path=args.verify_json,
            preset_id=args.preset,
            simulator_enabled=args.simulator,
            simulator_timeout_s=args.simulator_timeout_s,
            summarize_candidate_enabled=args.summarize_candidate,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {workflow_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
