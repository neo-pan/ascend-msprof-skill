#!/usr/bin/env python3
"""Print recognized operator CSV fields for one joint record or scope."""
from __future__ import annotations

import argparse
import json
import shlex
from statistics import median
from pathlib import Path

from .ascend_profile_utils import rel
from .operator_evidence import derived_pipe_quotients as _derived_pipe_quotients
from .operator_evidence import (joint_operator_row, operator_group_for_path, normalize_operator,
    parse_operator_row_metrics, OP_FIELDS, SCOPE_FIELDS, MISSING_TOKENS, _population_scope)
from .artifact_reader import read_csv


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


def field_query_entries(run_dir: Path) -> list[dict]:
    """Commands and artifact scope, without duplicating metric semantics in callers."""
    index = json.loads((run_dir / "analysis/raw_artifact_index.json").read_text())
    entries = []
    for item in index["artifacts"]:
        if item.get("group") not in OP_FIELDS or item.get("parser") != "csv":
            continue
        command = ["ascend-msprof", "joint-row", "--run-dir", str(run_dir),
                   "--artifact", item["artifact"], "--list-fields"]
        entries.append({"artifact": item["artifact"], "segment": item.get("segment"),
                        "metric_scope": item.get("metric_scope"), "record_count": item.get("row_count"),
                        "command": shlex.join(command)})
    return entries


def select_records(run_dir: Path, artifact: str, group: str, requested: list[str], *,
                   scope: dict[str, str] | None = None, offset: int = 0, limit: int = 5,
                   summary_only: bool = False) -> dict:
    """Select named fields; counts/distributions describe the full matching population."""
    path = (run_dir / artifact).resolve()
    path.relative_to(run_dir.resolve())
    if not requested or offset < 0 or limit < 1:
        raise ValueError("provide fields, nonnegative offset and positive limit")
    requested = list(dict.fromkeys(requested))
    known = {key.lower(): value for key, value in OP_FIELDS[group].items()}
    wanted = {key.lower(): value for key, value in (scope or {}).items()}
    index_path = run_dir / "analysis/raw_artifact_index.json"
    index = json.loads(index_path.read_text()) if index_path.is_file() else {}
    entry = next((item for item in index.get("artifacts", []) if item["artifact"] == artifact), {})
    groups, rows, issues = {}, [], []
    field_values = {}
    matched = 0

    def consume(columns, cells, ordinal):
        nonlocal matched
        row_scope = tuple((name, cells[i]) for i, name in enumerate(columns)
                          if name.lower() in {key.lower() for key in SCOPE_FIELDS})
        scope_map = {key.lower(): value for key, value in row_scope}
        if any(scope_map.get(key) != value for key, value in wanted.items()):
            return
        group_scope = _population_scope(row_scope)
        stats = groups.setdefault(group_scope, {"scope": dict(group_scope), "matched_records": 0,
            "fields": {field: {"valid": 0, "missing": 0, "invalid": 0, "unrecognized": 0,
                                "missing_column": 0} for field in requested}})
        stats["matched_records"] += 1
        parsed, row_issues, _ = parse_operator_row_metrics(group, artifact, columns, cells, ordinal)
        issues.extend(issue.model_dump(mode="json") for issue in row_issues)
        values = {item.metric.lower(): item for item in parsed}
        lower = [name.lower() for name in columns]
        selected = {}
        for field in requested:
            key = field.lower()
            positions = [i for i, name in enumerate(lower) if name == key]
            if not positions and lower.count("metric") == 1 and lower.count("value") == 1:
                if cells[lower.index("metric")].lower() == key:
                    positions = [lower.index("value")]
            item = values.get(key)
            token = cells[positions[0]] if positions else None
            if item is not None:
                state = "valid"
                field_values.setdefault((group_scope, field), []).append(item.value)
            elif not positions:
                state = "missing"
                stats["fields"][field]["missing_column"] += 1
            elif key not in known:
                state = "unrecognized"
            elif all(cells[i].strip().lower() in MISSING_TOKENS for i in positions):
                state = "missing"
            else:
                state = "invalid"
            stats["fields"][field][state] += 1
            selected[field] = {"state": state, "value": item.value if item else None,
                               "raw": token, "column": positions[0]+1 if positions else None}
        if not summary_only and offset <= matched < offset + limit:
            rows.append({"record": ordinal, "scope": dict(row_scope), "fields": selected})
        matched += 1

    decoded = read_csv(path, artifact, consume)
    issues = [issue.model_dump(mode="json") for issue in decoded.issues] + issues
    normalized = normalize_operator(path, artifact, group, entry.get("segment", "unknown"), entry.get("metric_scope"))
    existing = {json.dumps(issue, sort_keys=True) for issue in issues}
    for issue in normalized.issues:
        payload = issue.model_dump(mode="json")
        if json.dumps(payload, sort_keys=True) not in existing:
            issues.append(payload)
    # Reuse full-artifact populations only when the filter does not narrow their core rows.
    populations = [] if "block_id" in wanted else list(normalized.field_populations)
    returned_scopes = {_population_scope(tuple(row["scope"].items())) for row in rows}
    shown_groups = []
    for key, stats in groups.items():
        if key not in returned_scopes:
            continue
        distributions = [item.model_dump(mode="json") for item in populations
                         if item.scope == key and item.metric.lower() in {f.lower() for f in requested}]
        stats["field_populations"] = distributions
        stats["distribution_scope"] = "full_matching_group" if distributions else "raw_records_only"
        stats["returned_records"] = sum(_population_scope(tuple(row["scope"].items())) == key for row in rows)
        shown_groups.append(stats)
    next_offset = offset + len(rows) if offset + len(rows) < matched else None
    command = ["ascend-msprof", "joint-row", "--run-dir", str(run_dir), "--artifact", artifact,
               "--records", "--group", group, "--limit", str(limit)]
    for field in requested:
        command.extend(["--field", field])
    for key, value in (scope or {}).items():
        command.extend(["--scope", f"{key}={value}"])
    summary_groups = []
    for key, stats in groups.items():
        fields = {}
        for field, counts in stats["fields"].items():
            values = field_values.get((key, field), [])
            fields[field] = {**counts, "minimum": min(values) if values else None,
                             "median": median(values) if values else None,
                             "maximum": max(values) if values else None}
        summary_groups.append({"scope": dict(key), "matched_records": stats["matched_records"],
                               "fields": fields})
    if summary_only:
        return {"run_dir": str(run_dir), "artifact": artifact, "operator_group": group,
                "segment": entry.get("segment", "unknown"), "metric_scope": entry.get("metric_scope", "unknown"),
                "fields": [{"name": field, "unit": known.get(field.lower(), (None,))[0]}
                           for field in requested],
                "scope_filter": scope or {}, "matched_records": matched,
                "groups": summary_groups, "summary_complete": True,
                "parser_status": decoded.status, "issues": issues,
                "records_command": shlex.join(command),
                "range_note": "Statistics cover all valid matching cells, separately per scope; no cross-sample aggregation."}
    return {
        "run_dir": str(run_dir), "artifact": artifact, "operator_group": group,
        "segment": entry.get("segment", "unknown"), "metric_scope": entry.get("metric_scope", "unknown"),
        "fields": [{"name": field, "unit": known.get(field.lower(), (None,))[0],
                    "recognized": field.lower() in known} for field in requested],
        "artifact_records": decoded.row_count, "matched_records": matched,
        "group_count": len(groups), "returned_group_count": len(shown_groups),
        "offset": offset, "returned_records": len(rows), "complete": len(rows) == matched,
        "groups": shown_groups, "records": rows, "issues": issues,
        "parser_status": decoded.status,
        "next_command": shlex.join(command + ["--offset", str(next_offset)]) if next_offset is not None else None,
        "range_note": "Record numbers include header=1. Counts cover all matching records; only displayed groups "
                      "are included. field_populations retain their original metric and scope; other fields are raw selections.",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--artifact", required=True, help="Run-relative operator CSV path")
    ap.add_argument("--group", help="Operator group; inferred from filename when omitted")
    ap.add_argument("--record", type=int, help="CSV record number (header is 1)")
    ap.add_argument("--scope", action="append", help="Scope filter key=value; repeatable")
    ap.add_argument("--list-fields", action="store_true", help="List fields and units before selecting records")
    ap.add_argument("--records", action="store_true", help="Select a page of records, grouped by compatible scope")
    ap.add_argument("--field", action="append", help="Exact field name; repeatable")
    ap.add_argument("--offset", type=int, default=0, help="Matching-record offset")
    ap.add_argument("--limit", type=int, default=5, help="Maximum displayed records; counts use all matches")
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
    if args.list_fields:
        decoded = read_csv(path, rel(path, run_dir), lambda columns, cells, ordinal: None)
        known = {name.lower(): spec for name, spec in OP_FIELDS[group].items()}
        fields = [{"name": name, "unit": known.get(name.lower(), (None,))[0],
                   "recognized": name.lower() in known} for name in decoded.columns]
        available = [item["name"] for item in fields if item["recognized"]]
        command = ["ascend-msprof", "joint-row", "--run-dir", str(run_dir),
                   "--artifact", args.artifact, "--group", group]
        for field in available[:2]:
            command.extend(["--field", field])
        print(json.dumps({"run_dir": str(run_dir), "artifact": args.artifact,
                          "record_count": decoded.row_count, "fields": fields,
                          "example_selection": shlex.join(command) if available else None,
                          "issues": [issue.model_dump(mode="json") for issue in decoded.issues]}))
        return 0
    if args.records or args.field:
        if args.record is not None or not args.field:
            ap.error("--records requires --field and cannot use --record")
        try:
            payload = select_records(run_dir, rel(path, run_dir), group, args.field,
                                     scope=_parse_scope(args.scope), offset=args.offset, limit=args.limit,
                                     summary_only=not args.records)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return 0
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
