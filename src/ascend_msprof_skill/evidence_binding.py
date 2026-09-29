"""Content bindings for question results and raw CSV references, without storage."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .artifact_reader import read_csv

CONTRACT_VERSION = "1.0"


def safe_path(run_dir: Path, artifact: str) -> Path:
    path = (run_dir / artifact).resolve()
    path.relative_to(run_dir.resolve())
    if Path(artifact).is_absolute() or ".." in Path(artifact).parts:
        raise ValueError("reference must use a run-relative artifact")
    return path


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def raw_reference(run_dir: Path, artifact: str, *, record: int | None = None,
                  field: str | None = None, column: int | None = None) -> dict:
    return {"kind": "raw", "artifact": artifact, "sha256": digest(safe_path(run_dir, artifact)),
            "record": record, "field": field, "column": column}


def _members(run_dir: Path) -> list[str]:
    # Inventory changes affect absence/coverage claims, not unchanged raw references.
    return sorted(str(p.relative_to(run_dir)) for folder in ("reports", "logs")
                  for p in (run_dir / folder).rglob("*") if p.is_file())


def snapshot(run_dir: Path, artifacts: list[str], *, selection: dict | None = None) -> dict:
    inputs = set(artifacts)
    inputs.update(f"analysis/{name}.json" for name in (
        "summary", "raw_artifact_index", "provenance", "profile_context", "tilelang_context", "simulator_hotspots",
        "benchmark_context", "candidate_summary"))
    inputs.update(str(p.relative_to(run_dir)) for p in (run_dir / "logs").rglob("*") if p.is_file())
    files = {name: digest(path) if path.is_file() else None
             for name in sorted(inputs) for path in [safe_path(run_dir, name)]}
    payload = {"contract_version": CONTRACT_VERSION, "selection": selection or {},
               "files": files, "members": _members(run_dir)}
    return {"kind": "snapshot", **payload,
            "sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()}


def verify_reference(run_dir: Path, reference: dict, *, offset: int = 0, limit: int = 20) -> dict:
    """Check raw content independently of a derived snapshot; never upgrade admission."""
    if offset < 0 or limit < 1:
        raise ValueError("offset must be nonnegative and limit positive")
    if reference.get("kind") == "snapshot":
        if reference.get("contract_version") != CONTRACT_VERSION:
            return {"status": "stale", "reason": "query contract changed"}
        current = snapshot(run_dir, list(reference["files"]), selection=reference.get("selection"))
        return {"status": "verified" if current == reference else "stale",
                "reference": reference, "current_sha256": current["sha256"],
                "meaning": "Input snapshot binding only; not scientific or source identity validation."}
    if reference.get("kind") is None and "artifact" in reference:
        reference = {"kind": "raw", **reference}
    if reference.get("kind") != "raw":
        raise ValueError("reference kind must be raw or snapshot")
    path = safe_path(run_dir, reference["artifact"])
    if not path.is_file():
        return {"status": "unavailable", "reference": reference}
    if not reference.get("sha256"):
        return {"status": "unbound", "reference": reference}
    if digest(path) != reference["sha256"]:
        return {"status": "mismatch", "reference": reference}
    rows = []
    matched = 0
    record = reference.get("record")
    if record is not None and (not isinstance(record, int) or record < 2):
        raise ValueError("CSV data records start at 2")

    def consume(columns, cells, ordinal):
        nonlocal matched
        if record is not None and ordinal != record:
            return
        matched += 1
        column, field = reference.get("column"), reference.get("field")
        if column is not None and (not 1 <= column <= len(columns) or (field and columns[column - 1] != field)):
            raise ValueError("reference column/field disagrees with bound CSV")
        if field is not None and field not in columns:
            raise ValueError("reference field absent from bound CSV")
        if not offset <= matched - 1 < offset + limit:
            return
        rows.append({"record": ordinal, "cells": [
            {"column": i, "field": name, "raw": value}
            for i, (name, value) in enumerate(zip(columns, cells), 1)]})

    decoded = read_csv(path, reference["artifact"], consume)
    # Catch mutation during the read as well as before it.
    if digest(path) != reference["sha256"]:
        return {"status": "mismatch", "reference": reference}
    return {"status": "verified" if matched else "unavailable", "reference": reference,
            "parser_status": decoded.status, "issues": [x.model_dump(mode="json") for x in decoded.issues],
            "records": rows, "matched_records": matched, "offset": offset,
            "next_offset": offset + len(rows) if offset + len(rows) < matched else None,
            "meaning": "Bound raw cells for audit; this verification does not establish collection admission or target attribution."}
