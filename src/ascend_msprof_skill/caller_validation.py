"""Shared sealed-attachment validation, independent of selection and publication.

Missing optional captures are gaps. Invalid declarations, contradictory report
projections and broken declared bytes are conflicts. Producer observations and
live profile context do not authenticate or invalidate sealed attachment bytes.
Selection and formal record-reference authentication remain the callers'
responsibility, using caller_record; this inspection does not establish identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, JsonValue, ValidationError

from .artifact_reader import read_json
from .caller_projection import measurement_projection
from .evidence_binding import digest, safe_path
from .evidence_types import ArtifactPath, EvidenceFact


class CallerFile(EvidenceFact):
    path: ArtifactPath
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    original_path: str | None = None
    bytes: int | None = Field(default=None, ge=0)


class CallerMeasurement(EvidenceFact):
    mode: Literal["msprof_op"]
    boundary: Literal["executor_device_program_task_duration"]
    metric: Literal["device_program_duration_ms"]
    unit: Literal["ms"]
    value: FiniteFloat | None
    aggregation: dict[str, JsonValue]
    program_launches: int | None = Field(default=None, gt=0)
    steady_state_skip: int | None = Field(default=None, ge=0)
    sample_index: int | None = Field(default=None, ge=1)
    sample_duration_ms: FiniteFloat | None = None
    samples: Annotated[tuple[dict[str, JsonValue], ...], Field(strict=False)] = ()


def _issue(issues: list[dict], artifact: str, field: str, reason: str) -> None:
    issues.append({"code": "caller_evidence", "source": {"artifact": artifact, "field": field},
                   "reason": reason})


def _file(root: Path, value: object, artifact: str, field: str, issues: list[dict]) -> dict | None:
    if value is None:
        return None
    try:
        ref = CallerFile.model_validate(value)
        path = safe_path(root, ref.path)
        if (root / ref.path).is_symlink():
            raise ValueError("caller snapshot must not be a symlink")
    except (ValueError, TypeError) as exc:
        _issue(issues, artifact, field, str(exc))
        return {"status": "invalid"}
    try:
        status = "unavailable" if not path.is_file() else "verified" if digest(path) == ref.sha256 else "mismatch"
        if status == "verified" and ref.bytes is not None and path.stat().st_size != ref.bytes:
            status = "mismatch"
    except OSError as exc:
        _issue(issues, artifact, field, str(exc))
        status = "unavailable"
    if status != "verified":
        _issue(issues, artifact, field, f"local file {ref.path}: {status}")
    return {**ref.model_dump(mode="json"), "status": status}


def inspect_snapshots(root: Path, value: object, artifact: str, issues: list[dict],
                      gaps: list[dict]) -> dict:
    if not isinstance(value, dict):
        _issue(issues, artifact, "snapshots", "expected snapshots object")
        return {"source": None, "generated": []}
    source = _file(root, value.get("source"), artifact, "snapshots.source", issues)
    if source is None:
        _issue(gaps, artifact, "snapshots.source", "run-local source snapshot unavailable")
    generated = value.get("generated", [])
    if not isinstance(generated, list):
        _issue(issues, artifact, "snapshots.generated", "expected generated array")
        generated = []
    refs = []
    for i, item in enumerate(generated):
        if item is None:
            _issue(issues, artifact, f"snapshots.generated[{i}]", "expected file reference")
        refs.append(_file(root, item, artifact, f"snapshots.generated[{i}]", issues))
    return {"source": source, "generated": refs}


@dataclass
class AttachmentInspection:
    measurement: CallerMeasurement | None
    identity: dict
    report: dict | None
    source_report: dict | None
    snapshots: dict
    conflicts: list[dict]
    gaps: list[dict]

    def require_consistent(self) -> None:
        if self.conflicts:
            raise ValueError("caller attachment conflicts: " + "; ".join(
                f"{item['source']['field']}: {item['reason']}" for item in self.conflicts))


def inspect_attachment(root: Path, value: dict, artifact: str) -> AttachmentInspection:
    """Inspect one explicit manifest; never select, repair or publish artifacts."""
    issues: list[dict] = []
    gaps: list[dict] = []
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        _issue(issues, artifact, "schema_version", "unsupported caller export version")
    if value.get("producer") != "kernel-agent":
        _issue(issues, artifact, "producer", "unsupported caller producer")
    measurement = None
    try:
        measurement = CallerMeasurement.model_validate(value.get("measurement"))
    except ValidationError as exc:
        _issue(issues, artifact, "measurement", str(exc))
    identity = value.get("identity") if isinstance(value.get("identity"), dict) else {}
    if not isinstance(value.get("identity"), dict):
        _issue(issues, artifact, "identity", "expected identity object")
    source_report = _file(root, value.get("source_report"), artifact, "source_report", issues)
    snapshots = inspect_snapshots(root, value.get("snapshots"), artifact, issues, gaps)
    report = None
    if source_report and source_report["status"] == "verified":
        try:
            report = read_json(safe_path(root, source_report["path"]))
            if not isinstance(report, dict) or not isinstance(report.get("metrics"), dict):
                raise ValueError("source report must contain metrics")
        except (OSError, ValueError) as exc:
            _issue(issues, artifact, "source_report", str(exc))
            report = None
    else:
        _issue(issues, artifact, "source_report", "formal context requires a verified local report")
    if measurement is not None and report is not None:
        metrics = report["metrics"]
        expected = measurement_projection(report)
        for key in ("aggregation", "value", "program_launches", "steady_state_skip"):
            if getattr(measurement, key) != expected[key]:
                _issue(issues, artifact, f"measurement.{key}", "export disagrees with source report")
        if metrics.get("formal_measurement_mode") != "msprof_op":
            _issue(issues, artifact, "measurement.mode", "source report does not declare msprof_op")
        if identity.get("candidate_id") != report.get("candidate_id"):
            _issue(issues, artifact, "identity.candidate_id", "export disagrees with source report")
        if identity.get("source_sha256") != metrics.get("profile_source_sha256"):
            _issue(issues, artifact, "identity.source_sha256", "export disagrees with source report")
        receipts = metrics.get("device_program_profile_receipts", [])
        if not isinstance(receipts, list):
            receipts = []
        if list(measurement.samples) != expected["samples"]:
            _issue(issues, artifact, "measurement.samples", "process receipts disagree with source report")
        current = [item for item in receipts if isinstance(item, dict)
                   and item.get("attempt_index") == measurement.sample_index]
        if measurement.sample_index is None and measurement.sample_duration_ms is None:
            _issue(gaps, artifact, "measurement.sample_index", "current sample binding unavailable")
        elif len(current) != 1 or current[0].get("duration_ms") != measurement.sample_duration_ms:
            _issue(issues, artifact, "measurement.sample_duration_ms", "current sample does not match a unique report receipt")
        origin = value.get("origin")
        origin = origin if isinstance(origin, dict) else {}
        if origin.get("sample_attempt_index") != measurement.sample_index:
            _issue(issues, artifact, "origin.sample_attempt_index", "current process differs from exported run binding")
        if origin.get("source_sha256") != identity.get("source_sha256"):
            _issue(issues, artifact, "origin.source_sha256", "origin differs from declared implementation")
        if len(current) == 1 and current[0].get("artifact_dir"):
            declared_run = str(Path(current[0]["artifact_dir"]) / "profile/msprof_op")
            if origin.get("sample_profile_run_declared") != declared_run:
                _issue(issues, artifact, "origin.sample_profile_run_declared", "current process workspace differs from source report")
        for key in ("measurement_identity", "measurement_protocol"):
            if identity.get(key) != metrics.get(key):
                _issue(issues, artifact, f"identity.{key}", "export disagrees with source report")
        correctness = value.get("correctness")
        if not isinstance(correctness, dict) or any(correctness.get(key) != report.get(key)
                for key in ("status", "correctness_ok", "tolerance_passed")):
            _issue(issues, artifact, "correctness", "export disagrees with source report")
        if isinstance(correctness, dict) and correctness.get("receipt") != metrics.get("correctness_receipt"):
            _issue(issues, artifact, "correctness.receipt", "export disagrees with source report")
        compilation = metrics.get("compilation_evidence")
        compilation = compilation if isinstance(compilation, dict) else {}
        declared_generated = compilation.get("generated_sources", [])
        artifact_hashes = compilation.get("artifact_sha256", {})
        artifact_hashes = artifact_hashes if isinstance(artifact_hashes, dict) else {}
        generated = snapshots["generated"]
        if not isinstance(declared_generated, list) or any(not isinstance(path, str) for path in declared_generated):
            _issue(issues, artifact, "snapshots.generated", "source report has invalid generated inventory")
            declared_generated = []
        # Omitted captures are useful partial evidence. Present captures must be
        # an ordered subset: no extra, duplicated or reordered declarations.
        captured = [item.get("original_path") if item else None for item in generated]
        remaining = iter(declared_generated)
        if any(not any(path == declared for declared in remaining) for path in captured):
            _issue(issues, artifact, "snapshots.generated", "generated inventory differs from source report")
        elif captured != declared_generated:
            _issue(gaps, artifact, "snapshots.generated", "generated snapshots unavailable for part of the source report")
        for index, item in enumerate(generated):
            if item and item.get("sha256") != artifact_hashes.get(item.get("original_path")):
                _issue(issues, artifact, f"snapshots.generated[{index}].sha256", "generated code hash differs from source report")
    source = snapshots.get("source")
    if source and source.get("sha256") != identity.get("source_sha256"):
        _issue(issues, artifact, "snapshots.source.sha256", "source snapshot does not match declared implementation")
    return AttachmentInspection(measurement, identity, report, source_report, snapshots, issues, gaps)
