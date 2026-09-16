#!/usr/bin/env python3
"""Create a compact event-duration summary from Ascend profiler JSON."""
from __future__ import annotations

import argparse
from pathlib import Path

from ._profiler_segments import (
    APP_SEGMENT,
    SIMULATOR_SEGMENT,
    UNKNOWN_SEGMENT,
    app_timeline_segment,
    segment_for_relpath,
)
from .collection_receipts import load_collection_receipts
from .ascend_profile_utils import analysis_dir, find_files, read_json, rel, to_float

DURATION_FIELDS = ('dur', 'duration', 'Duration')
SOURCE_ORDER = (APP_SEGMENT, SIMULATOR_SEGMENT, UNKNOWN_SEGMENT)
SOURCE_TITLES = {
    APP_SEGMENT: "Application",
    SIMULATOR_SEGMENT: "Simulator",
    UNKNOWN_SEGMENT: "Unknown source",
}


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
            return key, (to_float(value) if type(value) in (int, float) else None)
    return None, None


def event_name(event):
    return str(event.get("name") or event.get("Name") or event.get("cat") or event.get("category") or "<event>")


def _source_mode(artifact: str, path: Path) -> str:
    if path.name == "trace.json" or "simulator" in Path(artifact).parts:
        return SIMULATOR_SEGMENT
    segment = app_timeline_segment(artifact)
    if segment == APP_SEGMENT:
        return APP_SEGMENT
    classified = segment_for_relpath(artifact, "app_timeline")
    if classified == APP_SEGMENT:
        return APP_SEGMENT
    if classified == SIMULATOR_SEGMENT:
        return SIMULATOR_SEGMENT
    return UNKNOWN_SEGMENT


def _cell(value) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


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
    grouped: dict[str, list[tuple]] = {key: [] for key in SOURCE_ORDER}
    notes = []
    for path in paths:
        artifact = rel(path, run_dir)
        source = _source_mode(artifact, path)
        try:
            events, event_path = _event_container(read_json(path))
        except (OSError, ValueError) as exc:
            notes.append(f'{artifact}: ERROR: {exc}')
            continue
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            field, dur = event_time(event)
            if field is None:
                continue
            if dur is None:
                notes.append(f'{artifact}: {event_path}[{index}].{field}: '
                             'invalid_number (expected a finite JSON number)')
                continue
            location = f'{event_path}[{index}]' if event_path else f'[{index}]'
            grouped[source].append((
                dur, field, artifact, location, event_name(event),
                event.get("ts"), event.get("pid"), event.get("tid"), event.get("ph"),
            ))
    lines = [
        "# Event Duration Summary",
        "",
        "Events are ranked by duration within each measurement source. "
        "This is an event-duration summary, not interval overlap or dependency analysis.",
        "",
    ]
    if not paths:
        lines.append("No msprof_*.json or trace.json files found.")
    else:
        for source in SOURCE_ORDER:
            rows = grouped[source]
            if not rows:
                continue
            rows.sort(key=lambda item: item[0], reverse=True)
            lines.append(f"## {SOURCE_TITLES[source]}")
            lines.append("")
            lines.append("| Duration | Duration field | Unit | Artifact | Event index | Event | ts | pid | tid | ph |")
            lines.append("|---:|---|---|---|---|---|---:|---|---|---|")
            for dur, field, artifact, location, name, ts, pid, tid, ph in rows[:args.top]:
                lines.append(
                    f"| {dur:g} | {_cell(field)} | unspecified | {_cell(artifact)} | "
                    f"{_cell(location)} | {_cell(name)} | {_cell(ts)} | {_cell(pid)} | "
                    f"{_cell(tid)} | {_cell(ph)} |"
                )
            lines.append("")
    if notes:
        lines.extend(['## Parsing Notes', *[f'- {note}' for note in notes], ''])
    out = analysis_dir(run_dir) / "timeline.txt"
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
