"""Shared helpers for parsing Ascend CANN profiling outputs."""
from __future__ import annotations

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


def read_json(path: Path) -> Any:
    from .artifact_reader import read_json as decode_json
    return decode_json(path)


def normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


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


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)
