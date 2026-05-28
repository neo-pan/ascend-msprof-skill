#!/usr/bin/env python3
"""Compare two analyzed Ascend profiling runs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ascend_profile_utils import analysis_dir


def load_summary(run_dir: Path) -> dict:
    path = run_dir / "analysis" / "summary.json"
    if not path.exists():
        raise SystemExit(f"missing {path}; run analyze_msprof_outputs.py first")
    return json.loads(path.read_text(encoding="utf-8"))


def value(summary: dict, group: str):
    item = summary.get("headlines", {}).get(group) or {}
    return item.get("value")


def fmt(v):
    return "n/a" if v is None else f"{float(v):.6g}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir-a", type=Path, required=True)
    ap.add_argument("--run-dir-b", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()

    a = load_summary(args.run_dir_a)
    b = load_summary(args.run_dir_b)
    groups = [
        "op_summary",
        "task_time",
        "pipe_utilization",
        "arithmetic_utilization",
        "resource_conflict",
    ]
    lines = ["# Ascend Run Comparison", ""]
    lines.append(f"A: {a['run_dir']}")
    lines.append(f"B: {b['run_dir']}")
    lines.append("")
    lines.append("| Signal | A | B | Delta |")
    lines.append("|---|---:|---:|---:|")
    for group in groups:
        av = value(a, group)
        bv = value(b, group)
        delta = None if av is None or bv is None else float(bv) - float(av)
        lines.append(f"| {group} | {fmt(av)} | {fmt(bv)} | {fmt(delta)} |")

    out_dir = args.out_dir or analysis_dir(args.run_dir_b.resolve())
    out = out_dir / f"compare_{args.run_dir_a.name}_vs_{args.run_dir_b.name}.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

