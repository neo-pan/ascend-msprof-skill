"""Read explicit Executor exports without admitting them as natural benchmarks."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, JsonValue, ValidationError

from .artifact_reader import read_json
from .evidence_binding import digest, safe_path
from .evidence_types import ArtifactPath, EvidenceFact

CALLER_ARTIFACT = "analysis/caller_evidence.json"
SNAPSHOTS_ARTIFACT = "analysis/source_snapshots.json"
SNAPSHOT_MEANING = (
    "Run-local content checks. Identify the material stage when citing code: generated C/C++ "
    "can establish source loops, addresses and barriers; final instruction structure requires "
    "a matching compiled object. Neither static structure nor aggregate PMU proves runtime "
    "waits or the critical path. Use these observations to choose a discriminating, reversible "
    "experiment; correctness and formal timing remain separate from mechanism attribution.")


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


def _snapshots(root: Path, value: object, artifact: str, issues: list[dict]) -> dict:
    if not isinstance(value, dict):
        _issue(issues, artifact, "snapshots", "expected snapshots object")
        return {"source": None, "generated": []}
    source = _file(root, value.get("source"), artifact, "snapshots.source", issues)
    if source is None:
        _issue(issues, artifact, "snapshots.source", "run-local source snapshot unavailable")
    generated = value.get("generated", [])
    if not isinstance(generated, list):
        _issue(issues, artifact, "snapshots.generated", "expected generated array")
        generated = []
    return {"source": source, "generated": [_file(root, item, artifact, f"snapshots.generated[{i}]", issues)
                                               for i, item in enumerate(generated)]}


def _load(root: Path, artifact: str) -> tuple[dict | None, list[dict]]:
    issues: list[dict] = []
    try:
        value = read_json(root / artifact)
    except FileNotFoundError:
        return None, issues
    except (OSError, ValueError) as exc:
        _issue(issues, artifact, "", str(exc))
        return {}, issues
    if not isinstance(value, dict):
        _issue(issues, artifact, "", "expected JSON object")
        return {}, issues
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        _issue(issues, artifact, "schema_version", "unsupported caller export version")
    return value, issues


def load_source_snapshots(run_dir: Path) -> dict | None:
    """Optional diagnostic-only snapshots, separate from formal timing exports."""
    value, issues = _load(Path(run_dir), SNAPSHOTS_ARTIFACT)
    if value is None:
        return None
    snapshots = _snapshots(Path(run_dir), value.get("snapshots", value), SNAPSHOTS_ARTIFACT, issues)
    source = snapshots.get("source")
    if value.get("source_sha256") is not None and source and source.get("sha256") != value["source_sha256"]:
        _issue(issues, SNAPSHOTS_ARTIFACT, "snapshots.source.sha256", "source snapshot differs from declared implementation")
    issues.extend(value.get("issues", []) if isinstance(value.get("issues", []), list) else [])
    return {"artifact": SNAPSHOTS_ARTIFACT, "status": "partial" if issues else "verified",
            "snapshots": snapshots, "issues": issues,
            "meaning": SNAPSHOT_MEANING}


def load_caller_evidence(run_dir: Path) -> dict | None:
    """Return sourced caller context. Problems remain local to this optional export."""
    root = Path(run_dir)
    value, issues = _load(root, CALLER_ARTIFACT)
    if value is None:
        return None
    if value.get("producer") != "kernel-agent":
        _issue(issues, CALLER_ARTIFACT, "producer", "unsupported caller producer")
    measurement = None
    try:
        measurement = CallerMeasurement.model_validate(value.get("measurement"))
    except ValidationError as exc:
        _issue(issues, CALLER_ARTIFACT, "measurement", str(exc))
    identity = value.get("identity") if isinstance(value.get("identity"), dict) else {}
    source_report = _file(root, value.get("source_report"), CALLER_ARTIFACT, "source_report", issues)
    snapshots = _snapshots(root, value.get("snapshots"), CALLER_ARTIFACT, issues)
    report = None
    if source_report and source_report["status"] == "verified":
        try:
            report = read_json(safe_path(root, source_report["path"]))
            if not isinstance(report, dict) or not isinstance(report.get("metrics"), dict):
                raise ValueError("source report must contain metrics")
        except (OSError, ValueError) as exc:
            _issue(issues, CALLER_ARTIFACT, "source_report", str(exc))
            report = None
    else:
        _issue(issues, CALLER_ARTIFACT, "source_report", "formal context requires a verified local report")
    if measurement is not None and report is not None:
        metrics = report["metrics"]
        protocol = metrics.get("measurement_protocol")
        protocol = protocol if isinstance(protocol, dict) else {}
        expected_aggregation = {"within_process": protocol.get("within_process_statistic"),
                                "across_process": protocol.get("across_process_statistic")}
        if measurement.aggregation != expected_aggregation:
            _issue(issues, CALLER_ARTIFACT, "measurement.aggregation", "aggregation disagrees with source report protocol")
        for key, expected in (("value", metrics.get("device_program_duration_ms")),
                              ("program_launches", metrics.get("device_program_launches")),
                              ("steady_state_skip", metrics.get("device_program_steady_state_skip"))):
            if getattr(measurement, key) != expected:
                _issue(issues, CALLER_ARTIFACT, f"measurement.{key}", "export disagrees with source report")
        if metrics.get("formal_measurement_mode") != "msprof_op":
            _issue(issues, CALLER_ARTIFACT, "measurement.mode", "source report does not declare msprof_op")
        if identity.get("candidate_id") != report.get("candidate_id"):
            _issue(issues, CALLER_ARTIFACT, "identity.candidate_id", "export disagrees with source report")
        if identity.get("source_sha256") != metrics.get("profile_source_sha256"):
            _issue(issues, CALLER_ARTIFACT, "identity.source_sha256", "export disagrees with source report")
        receipts = metrics.get("device_program_profile_receipts", [])
        if not isinstance(receipts, list):
            receipts = []
        sample_keys = ("attempt_index", "complete_sample_index", "status", "retained", "duration_ms",
            "profile_source_sha256", "profile_complete", "expected_rows", "observed_rows",
            "launch_durations_us", "steady_state_launch_indices", "launch_total_consistent",
            "kernel_durations_us", "kernel_duration_basis", "frequency_summary", "rejected_reason")
        expected_samples = [{key: item[key] for key in sample_keys if key in item}
                            for item in receipts if isinstance(item, dict)]
        if list(measurement.samples) != expected_samples:
            _issue(issues, CALLER_ARTIFACT, "measurement.samples", "process receipts disagree with source report")
        current = [item for item in receipts if isinstance(item, dict)
                   and item.get("attempt_index") == measurement.sample_index]
        if len(current) != 1 or current[0].get("duration_ms") != measurement.sample_duration_ms:
            _issue(issues, CALLER_ARTIFACT, "measurement.sample_duration_ms", "current sample does not match a unique report receipt")
        origin = value.get("origin")
        origin = origin if isinstance(origin, dict) else {}
        if origin.get("sample_attempt_index") != measurement.sample_index:
            _issue(issues, CALLER_ARTIFACT, "origin.sample_attempt_index", "current process differs from exported run binding")
        if origin.get("source_sha256") != identity.get("source_sha256"):
            _issue(issues, CALLER_ARTIFACT, "origin.source_sha256", "origin differs from declared implementation")
        if len(current) == 1 and current[0].get("artifact_dir"):
            declared_run = str(Path(current[0]["artifact_dir"]) / "profile/msprof_op")
            if origin.get("sample_profile_run_declared") != declared_run:
                _issue(issues, CALLER_ARTIFACT, "origin.sample_profile_run_declared", "current process workspace differs from source report")
        for key in ("measurement_identity", "measurement_protocol"):
            if identity.get(key) != metrics.get(key):
                _issue(issues, CALLER_ARTIFACT, f"identity.{key}", "export disagrees with source report")
        correctness = value.get("correctness")
        if not isinstance(correctness, dict) or any(correctness.get(key) != report.get(key)
                for key in ("status", "correctness_ok", "tolerance_passed")):
            _issue(issues, CALLER_ARTIFACT, "correctness", "export disagrees with source report")
        if isinstance(correctness, dict) and correctness.get("receipt") != metrics.get("correctness_receipt"):
            _issue(issues, CALLER_ARTIFACT, "correctness.receipt", "export disagrees with source report")
        compilation = metrics.get("compilation_evidence")
        compilation = compilation if isinstance(compilation, dict) else {}
        declared_generated = compilation.get("generated_sources", [])
        artifact_hashes = compilation.get("artifact_sha256", {})
        artifact_hashes = artifact_hashes if isinstance(artifact_hashes, dict) else {}
        generated = snapshots["generated"]
        if [item.get("original_path") if item else None for item in generated] != declared_generated:
            _issue(issues, CALLER_ARTIFACT, "snapshots.generated", "generated inventory differs from source report")
        for index, item in enumerate(generated):
            if item and item.get("sha256") != artifact_hashes.get(item.get("original_path")):
                _issue(issues, CALLER_ARTIFACT, f"snapshots.generated[{index}].sha256", "generated code hash differs from source report")
    source = snapshots.get("source")
    if source and source.get("sha256") != identity.get("source_sha256"):
        _issue(issues, CALLER_ARTIFACT, "snapshots.source.sha256", "source snapshot does not match declared implementation")
    # A name match is insufficient. Keep an existing run's explicit source identity.
    try:
        context = read_json(root / "analysis/profile_context.json")
    except (OSError, ValueError):
        context = {}
    if isinstance(context, dict) and context.get("source_sha256") is not None:
        if context["source_sha256"] != identity.get("source_sha256"):
            _issue(issues, CALLER_ARTIFACT, "identity.source_sha256", "export disagrees with current profile context")
    issues.extend(value.get("issues", []) if isinstance(value.get("issues", []), list) else [])
    return {"artifact": CALLER_ARTIFACT, "status": "partial" if issues else "verified",
            "measurement": measurement.model_dump(mode="json") if measurement else None,
            "identity": identity, "correctness": value.get("correctness"),
            "origin": value.get("origin"), "source_report": source_report, "snapshots": snapshots, "issues": issues,
            "meaning": "Caller-owned Executor msprof_op timing, not natural-launch performance. Verified means local content/report consistency only; it does not establish scientific validity or replace run gates. " + SNAPSHOT_MEANING}


def caller_context_lines(context: dict | None, *, heading: str = "Caller Executor Evidence") -> list[str]:
    if context is None:
        return []
    lines = ["", f"## {heading}", "", f"Export: `{context['artifact']}`; content status: `{context['status']}`."]
    measurement = context.get("measurement")
    if measurement:
        lines += [f"Formal metric: `{measurement['metric']}` = `{measurement['value']}` {measurement['unit']}; "
                  f"mode `{measurement['mode']}`; boundary `{measurement['boundary']}`.",
                  f"Current process sample `{measurement['sample_index']}`: `{measurement['sample_duration_ms']}` ms; "
                  f"captured launches `{measurement['program_launches']}`, scoring skip `{measurement['steady_state_skip']}`.",
                  f"Aggregation: `{measurement['aggregation']}`; process receipts: `{len(measurement['samples'])}`."]
    lines.append(context["meaning"])
    for issue in context["issues"]:
        lines.append(f"- {issue.get('reason', issue.get('message', issue))}")
    for ref in [context.get("source_report"), context["snapshots"].get("source"), *context["snapshots"].get("generated", [])]:
        if ref:
            lines.append(f"- `{ref.get('path', 'invalid reference')}`: `{ref['status']}`; SHA-256 `{ref.get('sha256', 'unavailable')}`.")
    return lines
