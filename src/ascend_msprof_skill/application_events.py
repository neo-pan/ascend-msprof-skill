"""Per-invocation op_summary events; independent of representative timing maxima.

Field authority: reference-sources.yaml/op_summary_exact_fields_cann83rc1alpha001.
No clock alignment across artifacts or collections is assumed.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

from .artifact_reader import read_csv

TIME_FIELDS = ("Task Start Time(us)", "Task Duration(us)", "Task Wait Time(us)")


def read_application_events(path: Path, artifact: str, *, offset: int = 0, limit: int = 20) -> dict:
    if offset < 0 or limit < 1:
        raise ValueError("offset must be nonnegative and limit positive")
    events, issues = [], []

    def consume(columns, cells, record):
        if len(set(columns)) != len(columns):
            return
        row = dict(zip(columns, cells))
        times = {}
        for field in TIME_FIELDS:
            token = row.get(field)
            value = None
            try:
                number = Decimal(token.strip()) if token is not None else None
                if number is not None and number.is_finite() and number >= 0:
                    value = str(number)
            except InvalidOperation:
                pass
            times[field] = {"raw": token, "value": value, "unit": "us", "source": {
                "artifact": artifact, "record": record, "field": field,
                "column": columns.index(field) + 1 if field in columns else None}}
            if value is None:
                issues.append({"record": record, "field": field, "reason": "missing or invalid nonnegative time"})
        events.append({"record": record, "name": row.get("Op Name"),
            "scope": {key: row.get(key) for key in ("Device_id", "Stream ID", "Model ID", "Task ID")},
            "times": times})

    decoded = read_csv(path, artifact, consume)
    # Compare only one file, device and stream. Sort valid starts; never bridge an invalid event in that stream.
    grouped = {}
    for event in events:
        key = (event["scope"]["Device_id"], event["scope"]["Stream ID"])
        if all(value is not None and value.strip() and value.strip().lower() not in {"na", "n/a"} for value in key):
            grouped.setdefault(key, []).append(event)
    relations = []
    for scope, items in grouped.items():
        if decoded.issues or any(x["times"][field]["value"] is None for x in items for field in TIME_FIELDS[:2]):
            continue
        ordered = sorted(items, key=lambda x: (Decimal(x["times"][TIME_FIELDS[0]]["value"]), x["record"]))
        for left, right in zip(ordered, ordered[1:]):
            with localcontext() as ctx:
                ctx.prec = 50
                delta = (Decimal(right["times"][TIME_FIELDS[0]]["value"])
                         - Decimal(left["times"][TIME_FIELDS[0]]["value"])
                         - Decimal(left["times"][TIME_FIELDS[1]]["value"]))
            relations.append({"left_record": left["record"], "right_record": right["record"],
                "signed_end_to_start_us": str(delta), "kind": "overlap" if delta < 0 else "selected_event_interval",
                "scope": {"Device_id": scope[0], "Stream ID": scope[1]},
                "formula": "right.Task Start Time(us) - left.Task Start Time(us) - left.Task Duration(us)",
                "adjacency": "consecutive by start within this file's observed device/stream records",
                "sources": [left["times"][TIME_FIELDS[0]]["source"], left["times"][TIME_FIELDS[1]]["source"],
                            right["times"][TIME_FIELDS[0]]["source"]]})
    selected = events[offset:offset + limit]
    return {"clock_domain": "same op_summary artifact and recorded device/stream only; no cross-artifact alignment",
        "events": selected, "event_count": len(events), "offset": offset,
        "next_offset": offset + len(selected) if offset + len(selected) < len(events) else None,
        "relations": [r for r in relations if r["right_record"] in {x["record"] for x in selected}],
        "parser_status": decoded.status, "issues": issues + [x.model_dump(mode="json") for x in decoded.issues],
        "limitations": ["Task Duration includes scheduling to the accelerator, execution and completion response.",
            "An interval between two observed events does not prove stream inactivity, full-device idle or a host cause.",
            "Other events may be absent or overlap the interval. This is not natural-launch latency decomposition.",
            "Raw Task Wait Time is preserved independently; it is not substituted for the computed pair interval."]}
