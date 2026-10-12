"""Render complete simulator instruction intervals without merging trace clocks."""
from __future__ import annotations

import math
from html import escape


def render_simulator_svg(events: list, artifact: str, sha256: str) -> str | None:
    intervals = []
    for number, event in enumerate(events):
        if not isinstance(event, dict) or event.get("ph") != "X":
            continue
        ts, duration = event.get("ts"), event.get("dur")
        if (type(ts) not in (int, float) or type(duration) not in (int, float)
                or not math.isfinite(ts) or not math.isfinite(duration) or duration <= 0
                or not math.isfinite(ts + duration)):
            continue
        if "pid" not in event or "tid" not in event:
            continue
        intervals.append((ts, duration, str(event["pid"]), str(event["tid"]),
                          str(event.get("name", "<instruction>")), number))
    if not intervals:
        return None
    lanes = sorted({(event[2], event[3]) for event in intervals})
    lane_ids = {lane: number for number, lane in enumerate(lanes)}
    start = min(event[0] for event in intervals)
    end = max(event[0] + event[1] for event in intervals)
    span = end - start
    if not math.isfinite(span) or span <= 0:
        return None
    width, left, plot_width, top, step = 1400, 300, 1060, 110, 34
    height = top + len(lanes) * step + 100
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="white"/>',
             '<g font-family="sans-serif" fill="#14243a">',
             '<text x="20" y="28" font-size="20">Simulator instruction timeline</text>',
             f'<text x="20" y="52" font-size="11">Source: {escape(artifact)}</text>',
             f'<text x="20" y="70" font-size="11">SHA256: {sha256}</text>',
             '<text x="20" y="90" font-size="12">Complete X events only; simulation time is separate from device latency. No cross-file clock merge or overlap percentage.</text>']
    for (pid, tid), number in lane_ids.items():
        y = top + number * step
        parts += [f'<text x="20" y="{y + 18}" font-size="12">{escape(pid)} / {escape(tid)}</text>',
                  f'<line x1="{left}" x2="{left + plot_width}" y1="{y + 25}" y2="{y + 25}" stroke="#dce2ec"/>']
    colors = {"CUBE": "#2968be", "VECTOR": "#a04daf", "MTE1": "#179c86",
              "MTE2": "#179c86", "MTE3": "#179c86", "SCALAR": "#b97821"}
    for ts, duration, pid, tid, name, number in intervals:
        x = left + (ts - start) * plot_width / span
        y = top + lane_ids[(pid, tid)] * step + 4
        bar_width = duration * plot_width / span
        color = colors.get(tid.upper(), "#55718d")
        title = f'{name}; ts={ts:g} us; dur={duration:g} us; traceEvents[{number}]'
        parts.append(f'<rect x="{x:.5f}" y="{y}" width="{bar_width:.5f}" height="20" fill="{color}"><title>{escape(title)}</title></rect>')
    axis_y = top + len(lanes) * step + 15
    for number in range(6):
        x = left + plot_width * number / 5
        label = span * number / 5
        parts.append(f'<text x="{x:.2f}" y="{axis_y}" text-anchor="middle" font-size="12">{label:.4g}</text>')
    parts += [f'<text x="{left}" y="{axis_y + 28}" font-size="13">Simulator time (us), relative to {start:g} us in this trace</text>',
              f'<text x="20" y="{axis_y + 54}" font-size="12">B/E and flow records are not converted into wait durations. Lanes retain raw pid/tid; representative-core and target binding remain caller checks.</text>',
              '</g></svg>']
    return "\n".join(parts) + "\n"
