"""Collect TimelineDetail or simulator evidence; device BIU sampling is closed."""
from __future__ import annotations

import argparse
import math
import re
import subprocess
from pathlib import Path

from . import evidence_model, generate_provenance, profile_harness
from ._profile_target import TargetSelection, normalize_target_contract
from .pipeline_evidence import (
    INSTRUCTION_SAMPLING_CLOSED_CODE, INSTRUCTION_SAMPLING_CLOSED_MESSAGE,
    build_pipeline_evidence, inspect_launcher,
)


def pipeline_command(run_dir: Path, application: Path, target: TargetSelection, *,
                     mode: str, sample_period: int = 1000, soc_version: str | None = None,
                     core_id: str | None = None) -> list[str]:
    if mode == "sampled":
        raise ValueError(f"{INSTRUCTION_SAMPLING_CLOSED_CODE}: {INSTRUCTION_SAMPLING_CLOSED_MESSAGE}")
    if mode not in {"timeline-detail", "simulator"}:
        raise ValueError("unknown pipeline collection mode")
    if sample_period != 1000:
        raise ValueError("sample-period belongs to the closed sampled mode")
    command = ["msprof", "op"]
    if mode == "simulator":
        if not soc_version or not re.fullmatch(r'[A-Za-z0-9_-]+', soc_version):
            raise ValueError("simulator mode requires an explicit --soc-version")
        command += ["simulator", f"--soc-version={soc_version}",
                    "--aic-metrics=PipeUtilization,ResourceConflictRatio"]
    else:
        command += ["--aic-metrics=TimelineDetail", "--replay-mode=kernel", "--warm-up=0"]
    command += [f"--output={run_dir / ('reports/sim' if mode == 'simulator' else 'reports/op')}",
                f"--application={application}", f"--kernel-name={target.kernel_selector}",
                f"--launch-count={target.launch_count}"]
    if core_id is not None:
        if not re.fullmatch(r'[0-9]+(?:\|[0-9]+)*', core_id):
            raise ValueError("core-id must contain numeric IDs separated by |")
        command.append(f"--core-id={core_id}")
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--mode", choices=["sampled", "timeline-detail", "simulator"], required=True,
                        help="timeline-detail or simulator; legacy sampled requests are rejected")
    parser.add_argument("--sample-period", type=int, default=1000, help=argparse.SUPPRESS)
    parser.add_argument("--soc-version", help="installed simulator product, required for simulator mode")
    parser.add_argument("--core-id", help="selected simulation core IDs, separated by |")
    parser.add_argument("--timeout-s", type=float, default=180, help="whole command wall limit in seconds")
    args = parser.parse_args(argv)
    run_dir = args.run_dir.expanduser().resolve()
    manifest_path = args.manifest.expanduser().resolve()
    try:
        # Reject before manifest reads, directory creation, help/env probes or
        # execution. Keep the legacy spelling only to explain the closure.
        if args.mode == "sampled":
            raise ValueError(f"{INSTRUCTION_SAMPLING_CLOSED_CODE}: {INSTRUCTION_SAMPLING_CLOSED_MESSAGE}")
        if not math.isfinite(args.timeout_s) or args.timeout_s <= 0:
            raise ValueError("timeout-s must be finite and positive")
        if args.sample_period != 1000:
            raise ValueError("sample-period belongs to the closed sampled mode")
        if args.mode == "timeline-detail" and args.soc_version:
            raise ValueError("soc-version applies to explicit simulator mode")
        manifest = profile_harness.load_manifest(manifest_path)
        application = profile_harness.application_from_manifest(manifest_path, manifest)
        target = normalize_target_contract(manifest)
        if target is None:
            raise ValueError("manifest must declare the actual kernel selector and expected_launches")
        command = pipeline_command(run_dir, application, target, mode=args.mode,
            sample_period=args.sample_period, soc_version=args.soc_version, core_id=args.core_id)
        profile_harness.ensure_fresh_collection_run(run_dir)
        for folder in ["reports", "logs", "analysis"]:
            (run_dir / folder).mkdir(parents=True, exist_ok=True)
        profile_harness.ProfileHarnessArtifacts(run_dir).write_profile_context(
            manifest_path=manifest_path, manifest=manifest, application=application,
            verify_json_path=None, verify_json=None, target_selection=target)
        overrides = inspect_launcher(application, run_dir)
        profile_harness.write_json_artifact(run_dir / "logs/pipeline_preflight.json", {
            "application": {"path": str(application),
                "sha256": profile_harness.collect_tilelang_context.sha256_file(application),
                "environment_overrides": [issue.model_dump(mode="json") for issue in overrides]},
            "mode": args.mode, "command": command,
            "status": "blocked" if overrides else "checking_installed_capabilities",
        })
        if overrides:
            raise ValueError(overrides[0].message)
        help_command = ["msprof", "op"] + (
            ["simulator", "--help"] if args.mode == "simulator" else ["--help"])
        runner = profile_harness.SubprocessCommandRunner()
        help_result = runner.run(help_command, cwd=run_dir, timeout_s=min(15, args.timeout_s))
        help_text = help_result.stdout + help_result.stderr
        (run_dir / "logs/pipeline_help.stdout").write_text(help_text, encoding="utf-8")
        required = {"timeline-detail": ["TimelineDetail", "--replay-mode", "--kernel-name", "--launch-count", "--warm-up"],
                    "simulator": ["--soc-version", "--kernel-name", "--launch-count", "ResourceConflictRatio"]}[args.mode]
        if args.core_id is not None:
            required.append("--core-id")
        missing = [option for option in required if option not in help_text]
        if help_result.returncode != 0 or missing:
            raise ValueError(f"installed msprof help is unsuccessful or does not advertise {missing}")
        generate_provenance.collect_environment(run_dir / "logs")
        stem = {"timeline-detail": "msprof_op", "simulator": "msprof_simulator"}[args.mode]
        command_name = f"command_{stem}.txt"
        result = profile_harness.run_logged(command, run_dir, command_name=command_name,
            log_stem=stem, cwd=application.parent, timeout_s=args.timeout_s, fatal=False, runner=runner)
        generate_provenance.main(["--run-dir", str(run_dir)])
        evidence_model.write_evidence_model(run_dir)
        pipeline = build_pipeline_evidence(run_dir)
        failed = result.status != "succeeded" or any(
            issue.code != "target_not_selected" for issue in pipeline.issues)
        profile_harness.write_json_artifact(run_dir / "analysis/profile_pipeline_run.json", {
            "mode": args.mode, "process_status": result.status,
            "process_returncode": result.returncode,
            "evidence_status": "blocked" if failed else "inspect_target_and_coverage",
            "pipeline_evidence": "analysis/pipeline_evidence.json",
            "overlap_assessment": "not_established",
        })
        print(f"wrote {run_dir / 'analysis/pipeline_evidence.json'}")
        return 1 if failed else 0
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"pipeline collection: {exc}")
        return 2
