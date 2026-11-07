"""Content bindings for question results and raw CSV references, without storage."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .artifact_reader import read_csv, read_json

CONTRACT_VERSION = "1.0"
GENERATION_LIMIT = ("This query does not verify that summary/index were generated from the current raw bytes. "
                    "Reanalyze after raw files change; verified content binding is not target attribution or diagnosis eligibility.")


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


def record_locator(record_id: str) -> str:
    if len(record_id) != 64 or any(c not in "0123456789abcdef" for c in record_id):
        raise ValueError("measurement_record_id must be a lowercase SHA-256")
    return f"analysis/caller_records/{record_id}.json"


def record_caller_artifact(run_dir: Path, record_id: str, *, verify_hash: bool = True) -> str | None:
    """Resolve one immutable record locator, without scanning report versions."""
    path = safe_path(run_dir, record_locator(record_id))
    if not path.exists():
        return None
    value = read_json(path)
    if (not isinstance(value, dict) or type(value.get("schema_version")) is not int
            or value["schema_version"] != 1 or value.get("record_sha256") != record_id):
        raise ValueError("invalid caller record locator")
    artifact = value.get("artifact")
    if not isinstance(artifact, str):
        raise ValueError("invalid caller record locator artifact")
    target = safe_path(run_dir, artifact)
    if verify_hash and digest(target) != value.get("sha256"):
        raise ValueError("caller record locator manifest hash mismatch")
    return artifact


def validate_caller_selection(report_version: str | None, measurement_record_id: str | None) -> None:
    """Invalid query arguments are distinct from damaged optional artifacts."""
    if measurement_record_id is not None:
        if report_version is not None:
            raise ValueError("select either a report version or a measurement record")
        record_locator(measurement_record_id)
    if report_version is not None and (len(report_version) != 64
            or any(c not in "0123456789abcdef" for c in report_version)):
        raise ValueError("report_version must be a lowercase SHA-256")


def caller_artifact(run_dir: Path, report_version: str | None = None,
                    measurement_record_id: str | None = None, *, verify_hash: bool = True) -> str:
    """Select a requested report version, falling back only to the legacy file.

    The caller reader checks the report's content identity before using fallback.
    No implicit latest version is selected for historical queries.
    """
    validate_caller_selection(report_version, measurement_record_id)
    if measurement_record_id is not None:
        artifact = record_caller_artifact(run_dir, measurement_record_id, verify_hash=verify_hash)
        if artifact is not None:
            return artifact
    if report_version is not None:
        relative = f"analysis/caller_reports/{report_version}/caller_evidence.json"
        if safe_path(run_dir, relative).exists():
            return relative
    return "analysis/caller_evidence.json"


def _caller_inputs(run_dir: Path, report_version: str | None = None,
                   measurement_record_id: str | None = None) -> set[str]:
    """Bind optional caller manifests and their local bytes; never follow external origins."""
    validate_caller_selection(report_version, measurement_record_id)
    inputs = {"analysis/source_snapshots.json"}
    try:
        # Enumerate safe dependencies even when their bytes fail authentication.
        inputs.add(caller_artifact(run_dir, report_version, measurement_record_id, verify_hash=False))
    except (OSError, ValueError):
        # Bind the damaged locator itself below; do not substitute another caller.
        pass
    if measurement_record_id is not None:
        inputs.add(record_locator(measurement_record_id))
    if report_version is not None:
        inputs.add(f"analysis/caller_reports/{report_version}/caller_evidence.json")
    for artifact in tuple(inputs):
        try:
            payload = read_json(run_dir / artifact)
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        snapshots = payload.get("snapshots", payload)
        if not isinstance(snapshots, dict):
            snapshots = {}
        generated = snapshots.get("generated", [])
        refs = [payload.get("source_report"), snapshots.get("source")]
        refs.extend(generated if isinstance(generated, list) else [])
        for ref in refs:
            if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
                continue
            try:
                safe_path(run_dir, ref["path"])
            except (ValueError, OSError):
                # The consumer reports an invalid reference locally, preserving PMU reads.
                continue
            inputs.add(ref["path"])
    return inputs


def snapshot(run_dir: Path, artifacts: list[str], *, selection: dict | None = None) -> dict:
    inputs = set(artifacts)
    optional = _caller_inputs(run_dir, (selection or {}).get("report_version"),
                              (selection or {}).get("measurement_record_id"))
    inputs.update(f"analysis/{name}.json" for name in (
        "summary", "raw_artifact_index", "provenance", "profile_context", "tilelang_context", "simulator_hotspots",
        "benchmark_context", "candidate_summary"))
    inputs.update(str(p.relative_to(run_dir)) for p in (run_dir / "logs").rglob("*") if p.is_file())
    files = {}
    for name in sorted(inputs | optional):
        try:
            path = safe_path(run_dir, name)
            files[name] = digest(path) if path.is_file() else None
        except (OSError, ValueError):
            if name in inputs:
                raise
            files[name] = None
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
        try:
            current = snapshot(run_dir, list(reference["files"]), selection=reference.get("selection"))
        except (OSError, ValueError) as exc:
            return {"status": "stale", "reference": reference, "reason": f"snapshot inputs unavailable: {exc}"}
        return {"status": "verified" if current == reference else "stale",
                "reference": reference, "current_sha256": current["sha256"],
                "meaning": "Input snapshot binding only. " + GENERATION_LIMIT}
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
