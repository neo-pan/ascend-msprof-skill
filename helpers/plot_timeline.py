#!/usr/bin/env python3
"""Create a compact text timeline summary from Ascend profiler JSON."""
from __future__ import annotations

import argparse
from pathlib import Path

from ascend_profile_utils import analysis_dir, find_files, read_json


def collect_events(obj):
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for key in ["traceEvents", "events", "data"]:
            value = obj.get(key)
            if isinstance(value, list):
                return value
    return []


def event_time(event):
    for key in ["dur", "duration", "Duration"]:
        if key in event:
            try:
                return float(event[key])
            except Exception:
                return None
    return None


def event_name(event):
    return str(event.get("name") or event.get("Name") or event.get("cat") or event.get("category") or "<event>")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()

    run_dir = args.run_dir.resolve()
    paths = find_files(run_dir, ["msprof_*.json", "trace.json"])
    rows = []
    for path in paths:
        try:
            events = collect_events(read_json(path))
        except Exception as exc:
            rows.append((0.0, path.name, f"ERROR: {exc}"))
            continue
        for event in events:
            if not isinstance(event, dict):
                continue
            dur = event_time(event)
            if dur is None:
                continue
            rows.append((dur, path.name, event_name(event)))
    rows.sort(reverse=True)
    lines = ["# Timeline Summary", ""]
    if not paths:
        lines.append("No msprof_*.json or trace.json files found.")
    else:
        lines.append("| Duration | File | Event |")
        lines.append("|---:|---|---|")
        for dur, file_, name in rows[:args.top]:
            lines.append(f"| {dur:g} | {file_} | {name} |")
    out = analysis_dir(run_dir) / "timeline.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

