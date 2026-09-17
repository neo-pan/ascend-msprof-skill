"""Operator CSV filename identity: canonical stem, optional 17-digit timestamp."""
from __future__ import annotations

import re
from typing import NamedTuple


class OperatorCsvName(NamedTuple):
    stem: str
    timestamp: str | None


_OPERATOR_CSV_NAME_RE = re.compile(
    r"^(?P<stem>[A-Za-z0-9]+)(?:_(?P<timestamp>[0-9]{17}))?\.csv$"
)
STEM_TO_GROUP = {
    "OpBasicInfo": "op_basic_info",
    "PipeUtilization": "pipe_utilization",
    "ArithmeticUtilization": "arithmetic_utilization",
    "L2Cache": "l2_cache",
    "Memory": "memory",
    "MemoryL0": "memory",
    "MemoryUB": "memory",
    "ResourceConflictRatio": "resource_conflict",
}
STEMS_BY_GROUP = {
    group: tuple(stem for stem, mapped in STEM_TO_GROUP.items() if mapped == group)
    for group in dict.fromkeys(STEM_TO_GROUP.values())
}


def parse_operator_csv_name(name: str) -> OperatorCsvName | None:
    """Parse ``Stem.csv`` or ``Stem_<17 digits>.csv``. Other shapes stay unknown."""
    match = _OPERATOR_CSV_NAME_RE.fullmatch(name)
    if match is None:
        return None
    return OperatorCsvName(stem=match.group("stem"), timestamp=match.group("timestamp"))


def operator_group_for_stem(stem: str) -> str | None:
    return STEM_TO_GROUP.get(stem)


def operator_group_for_name(name: str) -> str | None:
    parsed = parse_operator_csv_name(name)
    if parsed is None:
        return None
    return operator_group_for_stem(parsed.stem)
