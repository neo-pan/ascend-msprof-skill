#!/usr/bin/env python3
"""Create a compact text timeline summary from Ascend profiler JSON."""
from __future__ import annotations

import argparse
from pathlib import Path

from ._profiler_segments import (
    app_timeline_segment,
)
from .collection_receipts import load_collection_receipts
from .ascend_profile_utils import analysis_dir, find_files, read_json, rel, to_float

DURATION_FIELDS = ('dur', 'duration', 'Duration')


def _event_container(obj):
    if isinstance(obj, list):
        return obj, ''
    if isinstance(obj, dict):
        for key in ["traceEvents", "events", "data"]:
            value = obj.get(key)
            if isinstance(value, list):
                return value, key
    return [], ''


def collect_events(obj):
    return _event_container(obj)[0]


def event_time(event):
    for key in DURATION_FIELDS:
        if key in event:
            value = event[key]
            return to_float(value) if type(value) in (int, float) else None
    return None


def event_name(event):
    return str(event.get("name") or event.get("Name") or event.get("cat") or event.get("category") or "<event>")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args(argv)

    run_dir = args.run_dir.resolve()
    receipts = load_collection_receipts(run_dir)
    paths = [
        path
        for path in find_files(run_dir, ["msprof_*.json", "trace.json"])
        if not path.name.endswith(".result.json")
        and receipts.allows(
            "simulator"
            if path.name == "trace.json"
            else app_timeline_segment(rel(path, run_dir)),
        )
    ]
    rows = []
    notes = []
    for path in paths:
        artifact = rel(path, run_dir)
        try:
            events, event_path = _event_container(read_json(path))
        except (OSError, ValueError) as exc:
            notes.append(f'{artifact}: ERROR: {exc}')
            continue
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            dur = event_time(event)
            if dur is None:
                field = next((key for key in DURATION_FIELDS if key in event), None)
                if field is not None:
                    notes.append(f'{artifact}: {event_path}[{index}].{field}: '
                                 'invalid_number (expected a finite JSON number)')
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
    if notes:
        lines.extend(['', '## Parsing Notes', *[f'- {note}' for note in notes]])
    out = analysis_dir(run_dir) / "timeline.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
