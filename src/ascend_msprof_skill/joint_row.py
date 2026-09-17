#!/usr/bin/env python3
"""Print recognized operator CSV fields for one joint record or scope."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ascend_profile_utils import rel
from .operator_evidence import derived_pipe_quotients as _derived_pipe_quotients
from .operator_evidence import joint_operator_row, operator_group_for_path


def derived_pipe_quotients(fields):
    """CLI/test adapter: same-row quotients as JSON-ready dicts."""
    return [item.model_dump(mode="json") for item in _derived_pipe_quotients(fields)]


def _parse_scope(items: list[str] | None) -> dict[str, str] | None:
    if not items:
        return None
    scope: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"scope entry must be key=value, got {item!r}")
        key, value = item.split("=", 1)
        scope[key] = value
    return scope


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--artifact", required=True, help="Run-relative operator CSV path")
    ap.add_argument("--group", help="Operator group; inferred from filename when omitted")
    ap.add_argument("--record", type=int, help="CSV record number (header is 1)")
    ap.add_argument("--scope", action="append", help="Scope filter key=value; repeatable")
    args = ap.parse_args(argv)

    run_dir = args.run_dir.resolve()
    path = (run_dir / args.artifact).resolve()
    try:
        path.relative_to(run_dir)
    except ValueError:
        raise SystemExit("artifact must stay under --run-dir") from None
    if not path.is_file():
        raise SystemExit(f"artifact not found: {args.artifact}")
    group = args.group or operator_group_for_path(path)
    if group is None:
        raise SystemExit("could not infer operator group; pass --group")
    try:
        row = joint_operator_row(
            path, rel(path, run_dir), group,
            record=args.record, scope=_parse_scope(args.scope),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    payload = {
        "artifact": row.artifact,
        "group": row.group,
        "record": row.record,
        "scope": dict(row.scope),
        "fields": [
            {
                "metric": item.metric,
                "value": item.value,
                "unit": item.unit,
                "statistic": item.statistic,
                "raw_token": item.raw_token,
                "column": item.column,
                "field_ref": (
                    f"joint_operator_row; record={item.source.record}; "
                    f"column={item.source.column}; field={item.source.field}"
                ),
            }
            for item in row.fields
        ],
        "derived_pipe_quotients": derived_pipe_quotients(row.fields),
        "unmapped_columns": list(row.unmatched),
        "issues": [
            {
                "code": issue.code,
                "reason": issue.reason,
                "impact": issue.impact,
                "field": issue.source.field,
                "record": issue.source.record,
                "column": issue.source.column,
            }
            for issue in row.issues
        ],
        "note": (
            "Joint row for one operator CSV record, not one PMU sample, "
            "simultaneous execution, pipeline overlap, or cause. Do not treat "
            "summary.json per-metric maxima as the same record unless they "
            "share this artifact and record. Cross-family fields require "
            "matching block/sub-block scope plus compatible implementation, "
            "workload, launch, collection mode/segment, and replay. Invalid "
            "cells are omitted and listed under issues with the same legality "
            "rules as summary parsing. derived_pipe_quotients are "
            "pipe_time/core_time from this row only; official CalRatio uses "
            "cycle or task-window denominators and may differ."
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
