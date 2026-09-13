"""Standard-library decoding with loss-aware CSV structure checks."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

from .evidence_types import ParseIssue, SourceRef, csv_status


@dataclass(frozen=True)
class CsvRead:
    columns: tuple[str, ...]
    row_count: int
    sample_rows: tuple[dict[str, str], ...]
    issues: tuple[ParseIssue, ...]
    status: str


def read_csv(path: Path, artifact: str, consume: Callable[[tuple[str, ...], tuple[str, ...], int], None]) -> CsvRead:
    """Stream each structurally valid record once; keep at most five samples.

    Positions are CSV records (header is record 1), not physical text lines.
    Duplicate headers are reported before a mapping can discard a column.
    """
    columns: tuple[str, ...] = ()
    samples: list[dict[str, str]] = []
    issues: list[ParseIssue] = []
    count = 0
    try:
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.reader(stream, strict=True)
            columns = tuple(next(reader, ()))
            duplicates = {field for field in columns if columns.count(field) > 1}
            for field in sorted(duplicates):
                issues.append(ParseIssue(code="duplicate_header", source=SourceRef(
                    artifact=artifact, field=field, record=1, column=columns.index(field) + 1),
                    reason=f"duplicate CSV header: {field}", impact="structure"))
            for ordinal, cells in enumerate(reader, 2):
                if not cells:
                    continue
                count += 1
                if len(cells) != len(columns):
                    issues.append(ParseIssue(code="row_width", source=SourceRef(artifact=artifact, record=ordinal),
                        reason=f"CSV record has {len(cells)} cells; expected {len(columns)}", impact="structure"))
                    continue
                if not duplicates and len(samples) < 5:
                    samples.append(dict(zip(columns, cells)))
                consume(columns, tuple(cells), ordinal)
    except (OSError, UnicodeError, csv.Error) as exc:
        issues.append(ParseIssue(code="csv_decode", source=SourceRef(artifact=artifact), reason=str(exc), impact="decode"))
    return CsvRead(columns, count, tuple(samples), tuple(issues), csv_status(count, tuple(issues)))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"nonstandard JSON number: {value}")


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)


def decode_json(raw: bytes | str) -> Any:
    """Decode bytes already read for snapshot hashing, with the same JSON rules."""
    return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
