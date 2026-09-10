"""Shared helpers for parsing Ascend CANN profiling outputs."""
from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from typing import Any


def analysis_dir(run_dir: Path) -> Path:
    out = run_dir / "analysis"
    out.mkdir(parents=True, exist_ok=True)
    return out


def find_files(run_dir: Path, patterns: list[str]) -> list[Path]:
    roots = [run_dir / "reports", run_dir]
    seen: set[Path] = set()
    out: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for pattern in patterns:
            for path in root.rglob(pattern):
                if path.is_file() and path not in seen:
                    seen.add(path)
                    out.append(path)
    return sorted(out)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def first_present(row: dict[str, Any], aliases: list[str], default: Any = None) -> Any:
    if not row:
        return default
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    normalized = {normalized_key(str(k)): v for k, v in row.items()}
    for alias in aliases:
        key = alias.strip().lower()
        if key in lowered:
            return lowered[key]
        normalized_alias = normalized_key(alias)
        if normalized_alias in normalized:
            return normalized[normalized_alias]
    for alias in aliases:
        normalized_alias = normalized_key(alias)
        for key, value in normalized.items():
            if normalized_alias and normalized_alias in key:
                return value
    return default


def to_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value):
            return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def top_numeric_row(rows: list[dict[str, str]], value_aliases: list[str]) -> tuple[dict[str, str] | None, float | None]:
    best_row = None
    best_value = None
    for row in rows:
        value = to_float(first_present(row, value_aliases))
        if value is None:
            continue
        if best_value is None or value > best_value:
            best_row = row
            best_value = value
    return best_row, best_value


def summarize_csv(path: Path, max_rows: int = 5) -> dict[str, Any]:
    rows = read_csv_rows(path)
    return {
        "path": str(path),
        "columns": list(rows[0].keys()) if rows else [],
        "row_count": len(rows),
        "sample_rows": rows[:max_rows],
    }


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)
