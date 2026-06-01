#!/usr/bin/env python3
"""Prepare a generic TileLang kernel profiling run for evidence reporting."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from collect_tilelang_context import collect_context, existing_file, sha256_file, write_context
from generate_report import build_report, load_or_create_summary, load_provenance, load_tilelang_context


SCHEMA_VERSION = 1


def file_inventory(root: Path) -> dict[str, dict[str, Any]] | None:
    if not root.exists():
        return None
    if not root.is_dir():
        raise ValueError(f"reports path is not a directory: {root}")

    inventory = {}
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        rel = path.relative_to(root).as_posix()
        inventory[rel] = {
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
    return inventory


def changed_report_paths(
    before: dict[str, dict[str, Any]] | None,
    after: dict[str, dict[str, Any]] | None,
) -> list[str]:
    if before is None:
        return sorted(after or {})
    if after is None:
        return ["<reports-directory-removed>"]

    paths = sorted(set(before) | set(after))
    changed = []
    for path in paths:
        if before.get(path) != after.get(path):
            changed.append(path)
    return changed


def rel_display(run_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(run_dir.resolve()).as_posix()
    except ValueError:
        return path.name


def write_workflow_summary(
    run_dir: Path,
    *,
    reports_existed: bool,
    reports_created: bool,
    context_path: Path,
    report_path: Path,
    warnings: list[str],
) -> Path:
    analysis_dir = run_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    out = analysis_dir / "tilelang_profile_run.json"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "workflow": "TileLang kernel profiling workflow",
        "artifacts": {
            "reports": {
                "artifact": "reports/",
                "existed_before_prepare": reports_existed,
                "created_by_prepare": reports_created,
                "modified_by_prepare": False,
            },
            "tilelang_context": rel_display(run_dir, context_path),
            "report": rel_display(run_dir, report_path),
        },
        "warnings": warnings,
    }
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def prepare_profile_run(
    run_dir: Path,
    payload_src: Path,
    benchmark_json: Path,
    jit_debug_root: Path | None = None,
) -> tuple[Path, Path, Path, list[str]]:
    existing_file(payload_src, "payload source")
    existing_file(benchmark_json, "benchmark JSON")

    warnings: list[str] = []
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "analysis").mkdir(parents=True, exist_ok=True)

    reports_dir = run_dir / "reports"
    reports_existed = reports_dir.exists()
    before_reports = file_inventory(reports_dir)
    reports_created = False
    if before_reports is None:
        reports_dir.mkdir(parents=True)
        reports_created = True
        warnings.append("Created empty reports/ directory; place raw profiler outputs there.")

    context = collect_context(run_dir, payload_src, benchmark_json, jit_debug_root)
    warnings.extend(context.get("warnings", []))
    context_path = write_context(run_dir, context)

    summary = load_or_create_summary(run_dir)
    provenance = load_provenance(run_dir)
    tilelang_context = load_tilelang_context(run_dir)
    report_path = run_dir / "REPORT.md"
    report_path.write_text(build_report(summary, run_dir, provenance, tilelang_context), encoding="utf-8")

    after_reports = file_inventory(reports_dir)
    changed = changed_report_paths(before_reports, after_reports)
    if changed:
        preview = ", ".join(changed[:10])
        if len(changed) > 10:
            preview = f"{preview}, ..."
        raise RuntimeError(f"reports/ changed during TileLang run preparation: {preview}")

    workflow_path = write_workflow_summary(
        run_dir,
        reports_existed=reports_existed,
        reports_created=reports_created,
        context_path=context_path,
        report_path=report_path,
        warnings=warnings,
    )
    return context_path, report_path, workflow_path, warnings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--payload-src", type=Path, required=True)
    ap.add_argument("--benchmark-json", type=Path, required=True)
    ap.add_argument("--jit-debug-root", type=Path)
    args = ap.parse_args()

    run_dir = args.run_dir.resolve()
    payload_src = args.payload_src.resolve()
    benchmark_json = args.benchmark_json.resolve()
    jit_debug_root = args.jit_debug_root.resolve() if args.jit_debug_root else None

    try:
        context_path, report_path, workflow_path, warnings = prepare_profile_run(
            run_dir,
            payload_src,
            benchmark_json,
            jit_debug_root,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"wrote {context_path}")
    print(f"wrote {report_path}")
    print(f"wrote {workflow_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
