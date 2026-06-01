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
from generate_provenance import build_manifest, write_manifest
from plot_timeline import main as timeline_main
from prepare_tilelang_profile_run import prepare_profile_run


SCHEMA_VERSION = 1
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
ENV_KEYS = [
    "ASCEND_HOME_PATH",
    "ASCEND_OPP_PATH",
    "ASCEND_TOOLKIT_HOME",
    "ASCEND_AICPU_PATH",
    "CANN_PATH",
    "DDK_PATH",
    "PYTHONPATH",
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


def collection_evidence_conflicts(paths: RunPaths, *, disable_op_profile: bool) -> list[str]:
    candidates = [
        paths.benchmark_json,
        paths.app_benchmark_json,
        paths.op_benchmark_json,
        paths.reports_dir / "app",
        paths.reports_dir / "op",
    ]

    conflicts: list[str] = []
    for candidate in candidates:
        for path in existing_files(candidate):
            conflicts.append(rel(paths.run_dir, path))
    return conflicts


def require_fresh_collection_run(paths: RunPaths, *, disable_op_profile: bool) -> None:
    conflicts = collection_evidence_conflicts(paths, disable_op_profile=disable_op_profile)
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


def write_script(path: Path, *, benchmark_repo: Path, phase: str, cmd: list[str]) -> None:
    quoted_cmd = " ".join(shlex.quote(part) for part in cmd)
    script = "\n".join(
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
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


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
    commands = {
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
    return not bool(data.get("compiled")) or not bool(data.get("correctness")) or data.get("runtime") is None


def collect_environment(logs_dir: Path, msprof_bin: str) -> None:
    msprof_path = shutil.which(msprof_bin) if not Path(msprof_bin).is_absolute() else msprof_bin
    version_text = ""
    if msprof_path:
        for parent in Path(msprof_path).resolve().parents:
            candidate = parent / "version.cfg"
            if candidate.is_file():
                version_text = candidate.read_text(encoding="utf-8", errors="replace")
                break
    if version_text:
        (logs_dir / "cann_version.cfg").write_text(version_text, encoding="utf-8")
    else:
        (logs_dir / "cann_version.cfg").write_text("# version.cfg not found for msprof\n", encoding="utf-8")

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


def msprof_op_command(msprof_bin: str, output_dir: Path, op_script: Path) -> list[str]:
    return [
        msprof_bin,
        "op",
        f"--output={output_dir}",
        f"--application={op_script}",
        "--aic-metrics=PipeUtilization",
    ]


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
        },
        "commands": commands,
        "artifacts": artifacts,
        "warnings": warnings,
    }
    out = paths.analysis_dir / "tilelang_benchmark_profile_run.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def write_profile_mode_marker(paths: RunPaths, *, disable_op_profile: bool) -> None:
    marker = {
        "schema_version": SCHEMA_VERSION,
        "workflow": "TileLang benchmark profiling orchestrator",
        "profiles": {
            "app": True,
            "op_pipe": not disable_op_profile,
        },
    }
    out = paths.analysis_dir / "tilelang_benchmark_profile_run.json"
    out.write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    require_fresh_collection_run(paths, disable_op_profile=args.disable_op_profile)
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
    if app.returncode != 0:
        raise RuntimeError(f"app-level msprof failed; see {rel(paths.run_dir, paths.logs_dir / 'msprof_default.stderr')}")
    missing_app = missing_required(paths.reports_dir / "app", REQUIRED_APP_PATTERNS)
    if missing_app:
        raise RuntimeError(f"app-level msprof artifacts missing under reports/app: {', '.join(missing_app)}")

    op_cmd: list[str] | None = None
    if not args.disable_op_profile:
        op_cmd = msprof_op_command(args.msprof_bin, paths.reports_dir / "op", paths.op_script)
        op = run_logged(op_cmd, cwd=benchmark_repo, logs_dir=paths.logs_dir, stem="msprof_op")
        missing_op = missing_required(paths.reports_dir / "op", REQUIRED_OP_PATTERNS)
        if missing_op:
            raise RuntimeError(f"msprof op artifacts missing under reports/op: {', '.join(missing_op)}")
        op_benchmark = load_json_if_present(paths.op_benchmark_json)
        if op.returncode != 0:
            if benchmark_failed(op_benchmark):
                warnings.append(
                    "msprof op benchmark process returned non-zero or failed JSON parsing; "
                    "required op PipeUtilization artifacts were present, so profiler evidence was kept."
                )
            else:
                raise RuntimeError(f"msprof op failed; see {rel(paths.run_dir, paths.logs_dir / 'msprof_op.stderr')}")

    write_manifest(paths.run_dir, build_manifest(paths.run_dir))
    run_helper(analyze_main, ["--run-dir", str(paths.run_dir)])
    run_helper(timeline_main, ["--run-dir", str(paths.run_dir)])
    write_profile_mode_marker(paths, disable_op_profile=args.disable_op_profile)
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
        "op_benchmark_json": rel(paths.run_dir, paths.op_benchmark_json),
        "harness": {
            "canonical": rel(paths.run_dir, paths.canonical_script),
            "app_profile": rel(paths.run_dir, paths.app_script),
            "op_profile": rel(paths.run_dir, paths.op_script),
        },
        "app_required": find_required(paths.reports_dir / "app", REQUIRED_APP_PATTERNS),
        "op_required": find_required(paths.reports_dir / "op", REQUIRED_OP_PATTERNS)
        if not args.disable_op_profile
        else {},
        "report": rel(paths.run_dir, report_path),
    }
    command_metadata = {
        "benchmark": commands["canonical"],
        "app_profile_benchmark": commands["app_profile"],
        "op_profile_benchmark": commands["op_profile"],
        "msprof_app": app_cmd,
        "msprof_op": op_cmd,
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
        commands=command_metadata,
        artifacts=artifacts,
        warnings=warnings,
    )
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
    return ap


def main() -> int:
    args = build_arg_parser().parse_args()
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
