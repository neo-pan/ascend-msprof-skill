"""Shared helpers for parsing Ascend CANN profiling outputs."""
from __future__ import annotations

import csv
import json
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


def first_present(row: dict[str, Any], aliases: list[str], default: Any = None) -> Any:
    if not row:
        return default
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for alias in aliases:
        key = alias.strip().lower()
        if key in lowered:
            return lowered[key]
    for key, value in lowered.items():
        for alias in aliases:
            if alias.strip().lower() in key:
                return value
    return default


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


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

