"""Read explicit Executor exports without admitting them as natural benchmarks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .artifact_reader import read_json
from .caller_record import SUPPORTED_RECORD_SCHEMAS, record_reference, validate_record_reference
from .caller_validation import inspect_attachment, inspect_snapshots
from .evidence_binding import caller_artifact, record_locator, validate_caller_selection

CALLER_ARTIFACT = "analysis/caller_evidence.json"
SNAPSHOTS_ARTIFACT = "analysis/source_snapshots.json"
SNAPSHOT_MEANING = (
    "Run-local content checks. Identify the material stage when citing code: generated C/C++ "
    "can establish source loops, addresses and barriers; final instruction structure requires "
    "a matching compiled object. Neither static structure nor aggregate PMU proves runtime "
    "waits or the critical path. Use these observations to choose a discriminating, reversible "
    "experiment; correctness and formal timing remain separate from mechanism attribution.")


def _issue(issues: list[dict], artifact: str, field: str, reason: str) -> None:
    issues.append({"code": "caller_evidence", "source": {"artifact": artifact, "field": field},
                   "reason": reason})


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
    return value, issues


def load_source_snapshots(run_dir: Path) -> dict | None:
    """Optional diagnostic-only snapshots, separate from formal timing exports."""
    value, issues = _load(Path(run_dir), SNAPSHOTS_ARTIFACT)
    if value is None:
        return None
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        _issue(issues, SNAPSHOTS_ARTIFACT, "schema_version", "unsupported caller export version")
    snapshots = inspect_snapshots(Path(run_dir), value.get("snapshots", value), SNAPSHOTS_ARTIFACT, issues, issues)
    source = snapshots.get("source")
    if value.get("source_sha256") is not None and source and source.get("sha256") != value["source_sha256"]:
        _issue(issues, SNAPSHOTS_ARTIFACT, "snapshots.source.sha256", "source snapshot differs from declared implementation")
    issues.extend(value.get("issues", []) if isinstance(value.get("issues", []), list) else [])
    return {"artifact": SNAPSHOTS_ARTIFACT, "status": "partial" if issues else "verified",
            "snapshots": snapshots, "issues": issues,
            "meaning": SNAPSHOT_MEANING}


def load_caller_evidence(run_dir: Path, *, report_version: str | None = None,
                         measurement_record_id: str | None = None) -> dict | None:
    """Return sourced caller context. Problems remain local to this optional export."""
    root = Path(run_dir)
    validate_caller_selection(report_version, measurement_record_id)
    try:
        artifact = caller_artifact(root, report_version, measurement_record_id)
    except (OSError, ValueError) as exc:
        artifact = (record_locator(measurement_record_id) if measurement_record_id is not None
                    else f"analysis/caller_reports/{report_version}/caller_evidence.json"
                    if report_version is not None else CALLER_ARTIFACT)
        issues = []
        _issue(issues, artifact, "caller_binding", str(exc))
        return {"artifact": artifact, "status": "unavailable", "measurement": None,
                "snapshots": {}, "issues": issues,
                "meaning": "Optional caller binding is unavailable; independent raw evidence remains readable."}
    value, issues = _load(root, artifact)
    if value is None:
        if report_version is None and measurement_record_id is None:
            return None
        _issue(issues, artifact, "caller_binding", "requested caller attachment is unavailable")
        return {"artifact": artifact, "status": "unavailable", "measurement": None,
                "snapshots": {}, "issues": issues,
                "meaning": "The requested caller attachment is unavailable."}
    inspection = inspect_attachment(root, value, artifact)
    issues.extend(inspection.conflicts)
    issues.extend(inspection.gaps)
    measurement, identity, report = inspection.measurement, inspection.identity, inspection.report
    source_report, snapshots = inspection.source_report, inspection.snapshots
    if report_version is not None and (report is None or hashlib.sha256(json.dumps(
            report, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != report_version):
        _issue(issues, artifact, "source_report", "requested report version is unavailable or mismatched")
        # A partial legacy report is not context for a completed continuation.
        return {"artifact": artifact, "status": "unavailable", "measurement": None,
                "snapshots": {}, "issues": issues, "report_version": report_version,
                "meaning": "The explicitly requested formal report version could not be verified."}
    references = [container[key] for container, key in (
        (value, "measurement_record"),
        (report["metrics"] if report is not None else {}, "formal_measurement_record")) if key in container]
    if references or measurement_record_id is not None:
        try:
            if report is None:
                raise ValueError("formal measurement record requires a verified source report")
            if references:
                actual = [validate_record_reference(report, ref) for ref in references]
                if any(ref != actual[0] for ref in actual[1:]):
                    raise ValueError("caller manifest and source report reference disagree")
                matched = measurement_record_id is None or actual[0]["sha256"] == measurement_record_id
            else:
                # Pre-reference legacy exports can still be selected by either
                # explicitly requested, supported content identity.
                matched = any(record_reference(report, schema_version=version)["sha256"] == measurement_record_id
                              for version in SUPPORTED_RECORD_SCHEMAS)
            if not matched:
                raise ValueError("requested formal measurement record is unavailable or mismatched")
        except (ValueError, TypeError) as exc:
            _issue(issues, artifact, "measurement_record", str(exc))
            return {"artifact": artifact, "status": "unavailable", "measurement": None,
                    "snapshots": {}, "issues": issues,
                    **({"measurement_record_id": measurement_record_id} if measurement_record_id is not None else {}),
                    "meaning": "The formal measurement record could not be verified."}
    # A name match is insufficient. Keep an existing run's explicit source identity.
    try:
        context = read_json(root / "analysis/profile_context.json")
    except (OSError, ValueError):
        context = {}
    if isinstance(context, dict) and context.get("source_sha256") is not None:
        if context["source_sha256"] != identity.get("source_sha256"):
            _issue(issues, artifact, "identity.source_sha256", "export disagrees with current profile context")
    issues.extend(value.get("issues", []) if isinstance(value.get("issues", []), list) else [])
    return {"artifact": artifact, "status": "partial" if issues else "verified",
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
