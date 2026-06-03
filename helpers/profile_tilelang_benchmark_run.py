#!/usr/bin/env python3
"""Run a TileLang benchmark repo candidate under Ascend msprof collection."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from analyze_msprof_outputs import main as analyze_main
from collect_tilelang_context import existing_file
from generate_report import main as generate_report_main
from generate_provenance import build_manifest, write_manifest
from plot_timeline import main as timeline_main
from prepare_tilelang_profile_run import prepare_profile_run


SCHEMA_VERSION = 1
COMMAND_PLAN_SCHEMA_VERSION = "1.0"
RUNNER_MODULE = "ascend_svd_benchmark.runner"
REQUIRED_APP_PATTERNS = [
    "op_summary_*.csv",
    "task_time_*.csv",
    "api_statistic_*.csv",
    "msprof_*.json",
]
REQUIRED_OP_PATTERNS = [
    "OpBasicInfo.csv",
    "PipeUtilization.csv",
]
FOLLOWUP_DEFAULT_ACTION_ID = "collect_default_metric_followup"
FOLLOWUP_DEFAULT_AIC_METRICS = "Default"
REQUIRED_DEFAULT_FOLLOWUP_PATTERNS = [
    "OpBasicInfo.csv",
    "PipeUtilization.csv",
    "ArithmeticUtilization.csv",
    "Memory.csv",
    "MemoryL0.csv",
    "MemoryUB.csv",
    "ResourceConflictRatio.csv",
]
ENV_KEYS = [
    "ASCEND_HOME_PATH",
    "ASCEND_OPP_PATH",
    "ASCEND_TOOLKIT_HOME",
    "ASCEND_AICPU_PATH",
    "CANN_PATH",
    "DDK_PATH",
    "PYTHONPATH",
]
CANN_VERSION_ROOT_KEYS = [
    "ASCEND_TOOLKIT_HOME",
    "ASCEND_HOME_PATH",
    "CANN_PATH",
    "DDK_PATH",
]


@dataclass(frozen=True)
class RunPaths:
    run_dir: Path
    harness_dir: Path
    logs_dir: Path
    reports_dir: Path
    analysis_dir: Path
    benchmark_json: Path
    app_benchmark_json: Path
    op_benchmark_json: Path
    canonical_script: Path
    app_script: Path
    op_script: Path


def rel(run_dir: Path, path: Path) -> str:
    try:
        return path.relative_to(run_dir).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_payload(benchmark_repo: Path, payload_src: Path) -> Path:
    payload = payload_src if payload_src.is_absolute() else benchmark_repo / payload_src
    return payload.resolve()


def ensure_repo_shape(benchmark_repo: Path) -> None:
    if not benchmark_repo.exists():
        raise FileNotFoundError(f"benchmark repo not found: {benchmark_repo}")
    if not benchmark_repo.is_dir():
        raise ValueError(f"benchmark repo is not a directory: {benchmark_repo}")
    runner = benchmark_repo / "ascend_svd_benchmark" / "runner.py"
    if not runner.is_file():
        raise FileNotFoundError(f"unsupported benchmark repo shape; missing {runner}")


def create_run_paths(run_dir: Path) -> RunPaths:
    return RunPaths(
        run_dir=run_dir,
        harness_dir=run_dir / "harness",
        logs_dir=run_dir / "logs",
        reports_dir=run_dir / "reports",
        analysis_dir=run_dir / "analysis",
        benchmark_json=run_dir / "benchmark_result.json",
        app_benchmark_json=run_dir / "harness" / "app_profile_benchmark_result.json",
        op_benchmark_json=run_dir / "harness" / "op_profile_benchmark_result.json",
        canonical_script=run_dir / "harness" / "run_benchmark_canonical.sh",
        app_script=run_dir / "harness" / "run_benchmark_app_profile.sh",
        op_script=run_dir / "harness" / "run_benchmark_op_profile.sh",
    )


def ensure_layout(paths: RunPaths) -> None:
    for path in [paths.harness_dir, paths.logs_dir, paths.reports_dir, paths.analysis_dir]:
        path.mkdir(parents=True, exist_ok=True)


def existing_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root]
    return sorted(path for path in root.rglob("*") if path.is_file())


def collection_evidence_conflicts(paths: RunPaths) -> list[str]:
    candidates = [
        paths.benchmark_json,
        paths.reports_dir,
        paths.logs_dir,
        paths.analysis_dir,
        paths.harness_dir,
        paths.run_dir / "REPORT.md",
    ]

    conflicts: list[str] = []
    for candidate in candidates:
        for path in existing_files(candidate):
            conflicts.append(rel(paths.run_dir, path))
    return conflicts


def require_fresh_collection_run(paths: RunPaths) -> None:
    conflicts = collection_evidence_conflicts(paths)
    if not conflicts:
        return
    preview = ", ".join(conflicts[:8])
    if len(conflicts) > 8:
        preview = f"{preview}, ..."
    raise RuntimeError(
        "run directory already contains collection evidence; choose a fresh --run-dir "
        "instead of deleting or overwriting raw profiler outputs: "
        f"{preview}"
    )


def benchmark_command(
    *,
    python_bin: str,
    payload_src: Path,
    output: Path,
    task: str,
    warmups: int,
    repeats: int,
    timeout_s: float,
    baseline_ms: float | None,
    baseline_std_ms: float | None,
    jit_debug_root: Path | None,
    jit_verbose: bool,
) -> list[str]:
    cmd = [
        python_bin,
        "-u",
        "-m",
        RUNNER_MODULE,
        "--task",
        task,
        "--kernel-payload-src",
        str(payload_src),
        "--warmups",
        str(warmups),
        "--repeats",
        str(repeats),
        "--timeout-s",
        str(timeout_s),
        "--output",
        str(output),
    ]
    if baseline_ms is not None:
        cmd.extend(["--baseline-ms", str(baseline_ms)])
    if baseline_std_ms is not None:
        cmd.extend(["--baseline-std-ms", str(baseline_std_ms)])
    if jit_verbose:
        cmd.append("--jit-verbose")
    if jit_debug_root is not None:
        cmd.extend(["--jit-debug-root", str(jit_debug_root)])
    return cmd


def script_text(*, benchmark_repo: Path, phase: str, cmd: list[str]) -> str:
    quoted_cmd = " ".join(shlex.quote(part) for part in cmd)
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f"cd {shlex.quote(str(benchmark_repo))}",
            'if [[ -n "${PYTHONPATH:-}" ]]; then',
            f"  export PYTHONPATH={shlex.quote(str(benchmark_repo))}:$PYTHONPATH",
            "else",
            f"  export PYTHONPATH={shlex.quote(str(benchmark_repo))}",
            "fi",
            f"export TILELANG_PROFILE_PHASE={shlex.quote(phase)}",
            quoted_cmd,
            "",
        ]
    )


def write_script(path: Path, *, benchmark_repo: Path, phase: str, cmd: list[str]) -> None:
    script = script_text(benchmark_repo=benchmark_repo, phase=phase, cmd=cmd)
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def build_harness_commands(
    paths: RunPaths,
    *,
    payload_src: Path,
    python_bin: str,
    task: str,
    warmups: int,
    repeats: int,
    timeout_s: float,
    baseline_ms: float | None,
    baseline_std_ms: float | None,
    jit_debug_root: Path | None,
    jit_verbose: bool,
) -> dict[str, list[str]]:
    return {
        "canonical": benchmark_command(
            python_bin=python_bin,
            payload_src=payload_src,
            output=paths.benchmark_json,
            task=task,
            warmups=warmups,
            repeats=repeats,
            timeout_s=timeout_s,
            baseline_ms=baseline_ms,
            baseline_std_ms=baseline_std_ms,
            jit_debug_root=jit_debug_root,
            jit_verbose=jit_verbose,
        ),
        "app_profile": benchmark_command(
            python_bin=python_bin,
            payload_src=payload_src,
            output=paths.app_benchmark_json,
            task=task,
            warmups=warmups,
            repeats=repeats,
            timeout_s=timeout_s,
            baseline_ms=baseline_ms,
            baseline_std_ms=baseline_std_ms,
            jit_debug_root=jit_debug_root,
            jit_verbose=jit_verbose,
        ),
        "op_profile": benchmark_command(
            python_bin=python_bin,
            payload_src=payload_src,
            output=paths.op_benchmark_json,
            task=task,
            warmups=warmups,
            repeats=repeats,
            timeout_s=timeout_s,
            baseline_ms=baseline_ms,
            baseline_std_ms=baseline_std_ms,
            jit_debug_root=jit_debug_root,
            jit_verbose=jit_verbose,
        ),
    }


def write_harness_scripts(
    paths: RunPaths,
    *,
    benchmark_repo: Path,
    payload_src: Path,
    python_bin: str,
    task: str,
    warmups: int,
    repeats: int,
    timeout_s: float,
    baseline_ms: float | None,
    baseline_std_ms: float | None,
    jit_debug_root: Path | None,
    jit_verbose: bool,
) -> dict[str, list[str]]:
    commands = build_harness_commands(
        paths,
        payload_src=payload_src,
        python_bin=python_bin,
        task=task,
        warmups=warmups,
        repeats=repeats,
        timeout_s=timeout_s,
        baseline_ms=baseline_ms,
        baseline_std_ms=baseline_std_ms,
        jit_debug_root=jit_debug_root,
        jit_verbose=jit_verbose,
    )
    write_script(paths.canonical_script, benchmark_repo=benchmark_repo, phase="canonical", cmd=commands["canonical"])
    write_script(paths.app_script, benchmark_repo=benchmark_repo, phase="app_profile", cmd=commands["app_profile"])
    write_script(paths.op_script, benchmark_repo=benchmark_repo, phase="op_profile", cmd=commands["op_profile"])
    return commands


def write_command(path: Path, cmd: list[str]) -> None:
    path.write_text(" ".join(shlex.quote(part) for part in cmd) + "\n", encoding="utf-8")


def run_logged(cmd: list[str], *, cwd: Path | None, logs_dir: Path, stem: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    write_command(logs_dir / f"command_{stem}.txt", cmd)
    completed = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, env=env)
    (logs_dir / f"{stem}.stdout").write_text(completed.stdout or "", encoding="utf-8")
    (logs_dir / f"{stem}.stderr").write_text(completed.stderr or "", encoding="utf-8")
    (logs_dir / f"{stem}.status").write_text(f"{completed.returncode}\n", encoding="utf-8")
    return completed


def run_helper(main_func: Any, argv: list[str]) -> None:
    old_argv = sys.argv
    try:
        sys.argv = [old_argv[0], *argv]
        main_func()
    finally:
        sys.argv = old_argv


def find_required(root: Path, patterns: list[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for pattern in patterns:
        matches = sorted(path.relative_to(root).as_posix() for path in root.rglob(pattern) if path.is_file())
        found[pattern] = matches
    return found


def missing_required(root: Path, patterns: list[str]) -> list[str]:
    found = find_required(root, patterns)
    return [pattern for pattern, matches in found.items() if not matches]


def load_json_if_present(path: Path) -> Any | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def benchmark_failed(data: Any) -> bool:
    if not isinstance(data, dict):
        return True
    correctness = data.get("correctness")
    if isinstance(correctness, dict) and "passed" in correctness:
        correctness_ok = bool(correctness["passed"])
    else:
        correctness_ok = bool(correctness)
    return not bool(data.get("compiled")) or not correctness_ok or data.get("runtime") is None


def cann_version_candidates(msprof_bin: str) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path.resolve()
        if resolved not in seen:
            candidates.append(resolved)
            seen.add(resolved)

    msprof_path = shutil.which(msprof_bin) if not Path(msprof_bin).is_absolute() else msprof_bin
    if msprof_path:
        for parent in Path(msprof_path).resolve().parents:
            add(parent / "version.cfg")

    for key in CANN_VERSION_ROOT_KEYS:
        value = os.environ.get(key)
        if value:
            add(Path(value) / "version.cfg")
    return candidates


def collect_environment(logs_dir: Path, msprof_bin: str) -> None:
    version_text = ""
    for candidate in cann_version_candidates(msprof_bin):
        if candidate.is_file():
            version_text = candidate.read_text(encoding="utf-8", errors="replace")
            break
    if version_text:
        (logs_dir / "cann_version.cfg").write_text(version_text, encoding="utf-8")
    else:
        (logs_dir / "cann_version.cfg").write_text(
            "# version.cfg not found for msprof or Ascend environment roots\n",
            encoding="utf-8",
        )

    npu_smi = shutil.which("npu-smi")
    if npu_smi:
        completed = subprocess.run([npu_smi, "info"], capture_output=True, text=True)
        (logs_dir / "npu_smi_info.stdout").write_text(completed.stdout or "", encoding="utf-8")
        (logs_dir / "npu_smi_info.stderr").write_text(completed.stderr or "", encoding="utf-8")
        (logs_dir / "npu_smi_info.status").write_text(f"{completed.returncode}\n", encoding="utf-8")
    else:
        (logs_dir / "npu_smi_info.stdout").write_text("npu-smi not found\n", encoding="utf-8")
        (logs_dir / "npu_smi_info.status").write_text("127\n", encoding="utf-8")

    lines = []
    for key in ENV_KEYS:
        if key in os.environ:
            lines.append(f"{key}={os.environ[key]}")
    (logs_dir / "relevant_env.txt").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def msprof_app_command(msprof_bin: str, output_dir: Path, app_script: Path) -> list[str]:
    return [
        msprof_bin,
        f"--output={output_dir}",
        f"--application={app_script}",
        "--runtime-api=on",
        "--task-time=on",
        "--ai-core=on",
        "--aic-metrics=PipeUtilization",
        "--type=text",
        "--summary-format=csv",
    ]


def msprof_op_command(msprof_bin: str, output_dir: Path, op_script: Path, *, aic_metrics: str) -> list[str]:
    return [
        msprof_bin,
        "op",
        f"--output={output_dir}",
        f"--application={op_script}",
        f"--aic-metrics={aic_metrics}",
    ]


def harness_script_plan(paths: RunPaths, *, benchmark_repo: Path, commands: dict[str, list[str]]) -> dict[str, Any]:
    script_specs = {
        "canonical": (paths.canonical_script, "canonical", commands["canonical"]),
        "app_profile": (paths.app_script, "app_profile", commands["app_profile"]),
        "op_profile": (paths.op_script, "op_profile", commands["op_profile"]),
    }
    return {
        name: {
            "path": rel(paths.run_dir, path),
            "phase": phase,
            "command": cmd,
            "script": script_text(benchmark_repo=benchmark_repo, phase=phase, cmd=cmd).splitlines(),
        }
        for name, (path, phase, cmd) in script_specs.items()
    }


def expected_output_segments(paths: RunPaths, *, disable_op_profile: bool, disable_followup_collection: bool) -> dict[str, Any]:
    outputs: dict[str, Any] = {
        "app": {
            "enabled": True,
            "output_segment": rel(paths.run_dir, paths.reports_dir / "app"),
            "required_patterns": REQUIRED_APP_PATTERNS,
        },
        "op": {
            "enabled": not disable_op_profile,
            "output_segment": None if disable_op_profile else rel(paths.run_dir, paths.reports_dir / "op"),
            "required_patterns": [] if disable_op_profile else REQUIRED_OP_PATTERNS,
        },
        "followups": {},
    }
    if not disable_op_profile:
        outputs["followups"][FOLLOWUP_DEFAULT_ACTION_ID] = {
            "enabled": not disable_followup_collection,
            "conditional": True,
            "condition": f"analysis.summary.next_collection_actions contains {FOLLOWUP_DEFAULT_ACTION_ID}",
            "metric_scope": FOLLOWUP_DEFAULT_AIC_METRICS,
            "output_segment": rel(paths.run_dir, paths.reports_dir / "followups" / FOLLOWUP_DEFAULT_ACTION_ID),
            "required_patterns": REQUIRED_DEFAULT_FOLLOWUP_PATTERNS,
        }
        if disable_followup_collection:
            outputs["followups"][FOLLOWUP_DEFAULT_ACTION_ID]["disabled_reason"] = "--disable-followup-collection"
    return outputs


def build_command_plan(
    paths: RunPaths,
    *,
    benchmark_repo: Path,
    payload_src: Path,
    task: str,
    warmups: int,
    repeats: int,
    timeout_s: float,
    baseline_ms: float | None,
    baseline_std_ms: float | None,
    jit_debug_root: Path | None,
    python_bin: str,
    msprof_bin: str,
    disable_op_profile: bool,
    disable_followup_collection: bool,
    jit_verbose: bool,
    harness_commands: dict[str, list[str]],
    warnings: list[str],
) -> dict[str, Any]:
    app_cmd = msprof_app_command(msprof_bin, paths.reports_dir / "app", paths.app_script)
    op_cmd = None
    followup_records: list[dict[str, Any]] = []
    if not disable_op_profile:
        op_cmd = msprof_op_command(
            msprof_bin,
            paths.reports_dir / "op",
            paths.op_script,
            aic_metrics="PipeUtilization",
        )
        followup_record = {
            "action_id": FOLLOWUP_DEFAULT_ACTION_ID,
            "enabled": not disable_followup_collection,
            "conditional": True,
            "condition": f"analysis.summary.next_collection_actions contains {FOLLOWUP_DEFAULT_ACTION_ID}",
            "metric_scope": FOLLOWUP_DEFAULT_AIC_METRICS,
            "output_segment": rel(paths.run_dir, paths.reports_dir / "followups" / FOLLOWUP_DEFAULT_ACTION_ID),
        }
        if disable_followup_collection:
            followup_record["disabled_reason"] = "--disable-followup-collection"
        followup_records.append(followup_record)

    followup_commands = []
    if not disable_op_profile and not disable_followup_collection:
        followup_commands.append(
            {
                "action_id": FOLLOWUP_DEFAULT_ACTION_ID,
                "conditional": True,
                "condition": f"analysis.summary.next_collection_actions contains {FOLLOWUP_DEFAULT_ACTION_ID}",
                "command": msprof_op_command(
                    msprof_bin,
                    paths.reports_dir / "followups" / FOLLOWUP_DEFAULT_ACTION_ID,
                    paths.op_script,
                    aic_metrics=FOLLOWUP_DEFAULT_AIC_METRICS,
                ),
            }
        )

    return {
        "command_plan_schema_version": COMMAND_PLAN_SCHEMA_VERSION,
        "dry_run": True,
        "workflow": "TileLang benchmark profiling orchestrator command plan",
        "inputs": {
            "run_dir": str(paths.run_dir),
            "benchmark_repo": str(benchmark_repo),
            "payload_src": str(payload_src),
            "task": task,
            "warmups": warmups,
            "repeats": repeats,
            "timeout_s": timeout_s,
            "baseline_ms": baseline_ms,
            "baseline_std_ms": baseline_std_ms,
            "jit_debug_root": str(jit_debug_root) if jit_debug_root is not None else None,
            "jit_verbose": jit_verbose,
            "python_bin": python_bin,
            "msprof_bin": msprof_bin,
        },
        "profiles": {
            "app": {"enabled": True, "metric_scope": "PipeUtilization"},
            "op_pipe": {"enabled": not disable_op_profile, "metric_scope": None if disable_op_profile else "PipeUtilization"},
            "followups": followup_records,
        },
        "commands": {
            "benchmark": harness_commands["canonical"],
            "app_profile_benchmark": harness_commands["app_profile"],
            "op_profile_benchmark": None if disable_op_profile else harness_commands["op_profile"],
            "msprof_app": app_cmd,
            "msprof_op": op_cmd,
            "msprof_followups": followup_commands,
        },
        "expected_outputs": expected_output_segments(
            paths,
            disable_op_profile=disable_op_profile,
            disable_followup_collection=disable_followup_collection,
        ),
        "harness_scripts": harness_script_plan(paths, benchmark_repo=benchmark_repo, commands=harness_commands),
        "skipped_execution": [
            "write_harness_scripts",
            "collect_environment",
            "benchmark",
            "msprof_app",
            "msprof_op",
            "followup_collections",
            "analysis",
            "provenance",
            "timeline",
            "report",
        ],
        "warnings": warnings,
    }


def build_dry_run_command_plan(args: argparse.Namespace) -> dict[str, Any]:
    benchmark_repo = args.benchmark_repo.resolve()
    ensure_repo_shape(benchmark_repo)
    payload_src = resolve_payload(benchmark_repo, args.payload_src)
    existing_file(payload_src, "payload source")
    jit_debug_root = args.jit_debug_root.resolve() if args.jit_debug_root is not None else None

    paths = create_run_paths(args.run_dir.resolve())
    require_fresh_collection_run(paths)

    warnings: list[str] = []
    if jit_debug_root is not None and not jit_debug_root.exists():
        warnings.append(f"Optional JIT debug root missing: {args.jit_debug_root}")

    harness_commands = build_harness_commands(
        paths,
        payload_src=payload_src,
        python_bin=args.python_bin,
        task=args.task,
        warmups=args.warmups,
        repeats=args.repeats,
        timeout_s=args.timeout_s,
        baseline_ms=args.baseline_ms,
        baseline_std_ms=args.baseline_std_ms,
        jit_debug_root=jit_debug_root,
        jit_verbose=args.jit_verbose,
    )
    return build_command_plan(
        paths,
        benchmark_repo=benchmark_repo,
        payload_src=payload_src,
        task=args.task,
        warmups=args.warmups,
        repeats=args.repeats,
        timeout_s=args.timeout_s,
        baseline_ms=args.baseline_ms,
        baseline_std_ms=args.baseline_std_ms,
        jit_debug_root=jit_debug_root,
        python_bin=args.python_bin,
        msprof_bin=args.msprof_bin,
        disable_op_profile=args.disable_op_profile,
        disable_followup_collection=args.disable_followup_collection,
        jit_verbose=args.jit_verbose,
        harness_commands=harness_commands,
        warnings=warnings,
    )


def write_orchestrator_summary(
    paths: RunPaths,
    *,
    benchmark_repo: Path,
    payload_src: Path,
    task: str,
    warmups: int,
    repeats: int,
    timeout_s: float,
    baseline_ms: float | None,
    baseline_std_ms: float | None,
    disable_op_profile: bool,
    followups: list[dict[str, Any]],
    commands: dict[str, Any],
    artifacts: dict[str, Any],
    warnings: list[str],
) -> Path:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "workflow": "TileLang benchmark profiling orchestrator",
        "benchmark_repo": str(benchmark_repo),
        "payload_src": str(payload_src),
        "task": task,
        "warmups": warmups,
        "repeats": repeats,
        "timeout_s": timeout_s,
        "baseline_ms": baseline_ms,
        "baseline_std_ms": baseline_std_ms,
        "profiles": {
            "app": True,
            "op_pipe": not disable_op_profile,
            "followups": followups,
        },
        "commands": commands,
        "artifacts": artifacts,
        "warnings": warnings,
    }
    out = paths.analysis_dir / "tilelang_benchmark_profile_run.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def write_profile_mode_marker(
    paths: RunPaths,
    *,
    disable_op_profile: bool,
    followups: list[dict[str, Any]] | None = None,
) -> None:
    marker = {
        "schema_version": SCHEMA_VERSION,
        "workflow": "TileLang benchmark profiling orchestrator",
        "profiles": {
            "app": True,
            "op_pipe": not disable_op_profile,
            "followups": followups or [],
        },
    }
    out = paths.analysis_dir / "tilelang_benchmark_profile_run.json"
    out.write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_analysis_summary(paths: RunPaths) -> dict[str, Any]:
    data = load_json_if_present(paths.analysis_dir / "summary.json")
    return data if isinstance(data, dict) else {}


def followup_stem(action_id: str) -> str:
    return f"msprof_followup_{action_id}"


def run_default_metric_followup(
    paths: RunPaths,
    *,
    msprof_bin: str,
    benchmark_repo: Path,
    warnings: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    action_id = FOLLOWUP_DEFAULT_ACTION_ID
    output_dir = paths.reports_dir / "followups" / action_id
    cmd = msprof_op_command(
        msprof_bin,
        output_dir,
        paths.op_script,
        aic_metrics=FOLLOWUP_DEFAULT_AIC_METRICS,
    )
    completed = run_logged(
        cmd,
        cwd=benchmark_repo,
        logs_dir=paths.logs_dir,
        stem=followup_stem(action_id),
    )
    missing = missing_required(output_dir, REQUIRED_DEFAULT_FOLLOWUP_PATTERNS)
    if missing:
        raise RuntimeError(
            "msprof op Default follow-up artifacts missing under "
            f"{rel(paths.run_dir, output_dir)}: {', '.join(missing)}"
        )

    op_benchmark = load_json_if_present(paths.op_benchmark_json)
    if benchmark_failed(op_benchmark):
        warnings.append(
            "msprof op Default follow-up benchmark process returned non-zero or failed benchmark JSON; "
            "required Default follow-up artifacts were present, so profiler evidence was kept."
        )
    elif completed.returncode != 0:
        raise RuntimeError(
            "msprof op Default follow-up failed; see "
            f"{rel(paths.run_dir, paths.logs_dir / (followup_stem(action_id) + '.stderr'))}"
        )

    profile = {
        "action_id": action_id,
        "metric_scope": FOLLOWUP_DEFAULT_AIC_METRICS,
        "output_segment": rel(paths.run_dir, output_dir),
        "required_artifacts": REQUIRED_DEFAULT_FOLLOWUP_PATTERNS,
    }
    artifact = {
        "output_segment": profile["output_segment"],
        "required": find_required(output_dir, REQUIRED_DEFAULT_FOLLOWUP_PATTERNS),
    }
    return profile, {"action_id": action_id, "command": cmd, "artifacts": artifact}


def run_followup_collections(
    paths: RunPaths,
    *,
    args: argparse.Namespace,
    benchmark_repo: Path,
    warnings: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if args.disable_op_profile or args.disable_followup_collection:
        return [], [], {}

    summary = load_analysis_summary(paths)
    actions = summary.get("next_collection_actions")
    if not isinstance(actions, list):
        return [], [], {}

    profiles = []
    commands = []
    artifacts: dict[str, Any] = {}
    executed: set[str] = set()
    for action in actions:
        if not isinstance(action, dict):
            continue
        action_id = str(action.get("id") or "")
        if not action_id or action_id in executed:
            continue
        executed.add(action_id)
        if action_id != FOLLOWUP_DEFAULT_ACTION_ID:
            warnings.append(f"unsupported next collection action skipped: {action_id}")
            continue
        profile, command_record = run_default_metric_followup(
            paths,
            msprof_bin=args.msprof_bin,
            benchmark_repo=benchmark_repo,
            warnings=warnings,
        )
        profiles.append(profile)
        commands.append({"action_id": action_id, "command": command_record["command"]})
        artifacts[action_id] = command_record["artifacts"]
    return profiles, commands, artifacts


def orchestrate(args: argparse.Namespace) -> tuple[Path, list[str]]:
    benchmark_repo = args.benchmark_repo.resolve()
    ensure_repo_shape(benchmark_repo)
    payload_src = resolve_payload(benchmark_repo, args.payload_src)
    existing_file(payload_src, "payload source")
    if args.jit_debug_root is not None:
        jit_debug_root = args.jit_debug_root.resolve()
    else:
        jit_debug_root = None

    paths = create_run_paths(args.run_dir.resolve())
    require_fresh_collection_run(paths)
    ensure_layout(paths)

    commands = write_harness_scripts(
        paths,
        benchmark_repo=benchmark_repo,
        payload_src=payload_src,
        python_bin=args.python_bin,
        task=args.task,
        warmups=args.warmups,
        repeats=args.repeats,
        timeout_s=args.timeout_s,
        baseline_ms=args.baseline_ms,
        baseline_std_ms=args.baseline_std_ms,
        jit_debug_root=jit_debug_root,
        jit_verbose=args.jit_verbose,
    )

    warnings: list[str] = []
    collect_environment(paths.logs_dir, args.msprof_bin)

    canonical = run_logged([str(paths.canonical_script)], cwd=benchmark_repo, logs_dir=paths.logs_dir, stem="benchmark")
    if canonical.returncode != 0:
        raise RuntimeError(f"canonical benchmark failed; see {rel(paths.run_dir, paths.logs_dir / 'benchmark.stderr')}")
    existing_file(paths.benchmark_json, "canonical benchmark JSON")

    app_cmd = msprof_app_command(args.msprof_bin, paths.reports_dir / "app", paths.app_script)
    write_command(paths.logs_dir / "command_msprof.txt", app_cmd)
    app = run_logged(app_cmd, cwd=benchmark_repo, logs_dir=paths.logs_dir, stem="msprof_default")
    missing_app = missing_required(paths.reports_dir / "app", REQUIRED_APP_PATTERNS)
    if missing_app:
        raise RuntimeError(f"app-level msprof artifacts missing under reports/app: {', '.join(missing_app)}")
    app_benchmark = load_json_if_present(paths.app_benchmark_json)
    if benchmark_failed(app_benchmark):
        warnings.append(
            "app-level msprof benchmark process returned non-zero or failed benchmark JSON; "
            "required app profiler artifacts were present, so profiler evidence was kept."
        )
    elif app.returncode != 0:
        raise RuntimeError(f"app-level msprof failed; see {rel(paths.run_dir, paths.logs_dir / 'msprof_default.stderr')}")

    op_cmd: list[str] | None = None
    followup_profiles: list[dict[str, Any]] = []
    followup_commands: list[dict[str, Any]] = []
    followup_artifacts: dict[str, Any] = {}
    if not args.disable_op_profile:
        op_cmd = msprof_op_command(
            args.msprof_bin,
            paths.reports_dir / "op",
            paths.op_script,
            aic_metrics="PipeUtilization",
        )
        op = run_logged(op_cmd, cwd=benchmark_repo, logs_dir=paths.logs_dir, stem="msprof_op")
        missing_op = missing_required(paths.reports_dir / "op", REQUIRED_OP_PATTERNS)
        if missing_op:
            raise RuntimeError(f"msprof op artifacts missing under reports/op: {', '.join(missing_op)}")
        op_benchmark = load_json_if_present(paths.op_benchmark_json)
        if benchmark_failed(op_benchmark):
            warnings.append(
                "msprof op benchmark process returned non-zero or failed benchmark JSON; "
                "required op PipeUtilization artifacts were present, so profiler evidence was kept."
            )
        elif op.returncode != 0:
            raise RuntimeError(f"msprof op failed; see {rel(paths.run_dir, paths.logs_dir / 'msprof_op.stderr')}")

    write_profile_mode_marker(paths, disable_op_profile=args.disable_op_profile)
    run_helper(analyze_main, ["--run-dir", str(paths.run_dir)])
    followup_profiles, followup_commands, followup_artifacts = run_followup_collections(
        paths,
        args=args,
        benchmark_repo=benchmark_repo,
        warnings=warnings,
    )
    write_profile_mode_marker(
        paths,
        disable_op_profile=args.disable_op_profile,
        followups=followup_profiles,
    )
    write_manifest(paths.run_dir, build_manifest(paths.run_dir))
    run_helper(analyze_main, ["--run-dir", str(paths.run_dir)])
    run_helper(timeline_main, ["--run-dir", str(paths.run_dir)])
    _context_path, report_path, _workflow_path, prepare_warnings = prepare_profile_run(
        paths.run_dir,
        payload_src,
        paths.benchmark_json,
        jit_debug_root,
    )
    warnings.extend(prepare_warnings)

    artifacts = {
        "benchmark_json": rel(paths.run_dir, paths.benchmark_json),
        "app_benchmark_json": rel(paths.run_dir, paths.app_benchmark_json),
        "op_benchmark_json": None if args.disable_op_profile else rel(paths.run_dir, paths.op_benchmark_json),
        "harness": {
            "canonical": rel(paths.run_dir, paths.canonical_script),
            "app_profile": rel(paths.run_dir, paths.app_script),
            "op_profile": rel(paths.run_dir, paths.op_script),
        },
        "app_required": find_required(paths.reports_dir / "app", REQUIRED_APP_PATTERNS),
        "op_required": find_required(paths.reports_dir / "op", REQUIRED_OP_PATTERNS)
        if not args.disable_op_profile
        else {},
        "followups": followup_artifacts,
        "report": rel(paths.run_dir, report_path),
    }
    command_metadata = {
        "benchmark": commands["canonical"],
        "app_profile_benchmark": commands["app_profile"],
        "op_profile_benchmark": commands["op_profile"],
        "msprof_app": app_cmd,
        "msprof_op": op_cmd,
        "msprof_followups": followup_commands,
    }
    summary_path = write_orchestrator_summary(
        paths,
        benchmark_repo=benchmark_repo,
        payload_src=payload_src,
        task=args.task,
        warmups=args.warmups,
        repeats=args.repeats,
        timeout_s=args.timeout_s,
        baseline_ms=args.baseline_ms,
        baseline_std_ms=args.baseline_std_ms,
        disable_op_profile=args.disable_op_profile,
        followups=followup_profiles,
        commands=command_metadata,
        artifacts=artifacts,
        warnings=warnings,
    )
    run_helper(generate_report_main, ["--run-dir", str(paths.run_dir)])
    return summary_path, warnings


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--benchmark-repo", type=Path, required=True)
    ap.add_argument("--payload-src", type=Path, required=True)
    ap.add_argument("--task", default="svd", choices=["svd"])
    ap.add_argument("--warmups", type=int, default=0)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--timeout-s", type=float, default=300.0)
    ap.add_argument("--baseline-ms", type=float)
    ap.add_argument("--baseline-std-ms", type=float)
    ap.add_argument("--jit-debug-root", type=Path)
    ap.add_argument("--jit-verbose", action="store_true")
    ap.add_argument("--msprof-bin", default="msprof")
    ap.add_argument("--python-bin", default=sys.executable)
    ap.add_argument("--disable-op-profile", action="store_true")
    ap.add_argument("--disable-followup-collection", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print the collection command plan as JSON without running commands")
    return ap


def main() -> int:
    args = build_arg_parser().parse_args()
    if args.dry_run:
        try:
            command_plan = build_dry_run_command_plan(args)
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(command_plan, indent=2, sort_keys=True))
        return 0

    try:
        summary_path, warnings = orchestrate(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"wrote {summary_path}")
    print(f"wrote {args.run_dir.resolve() / 'REPORT.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
