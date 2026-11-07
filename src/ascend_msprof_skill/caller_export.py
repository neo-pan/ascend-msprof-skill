"""Explicit, source-bound exports of Executor profiling evidence.

This module copies existing receipts and bytes. It never collects, scores a new
measurement, or turns the Executor's profiler metric into natural latency.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from dataclasses import dataclass

from .artifact_reader import decode_json
from .caller_projection import measurement_projection
from .caller_store import CallerAttachmentStore
import shutil


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def formal_report_version(report: dict) -> str:
    """Content identity independent of report JSON whitespace and key ordering."""
    return _sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode())


def formal_measurement_record(report: dict) -> dict:
    """Return the stable caller contract reference, verifying one already carried."""
    from ascend_msprof_skill.caller_record import record_reference, validate_record_reference
    reference = report.get("metrics", {}).get("formal_measurement_record")
    return (validate_record_reference(report, reference) if "formal_measurement_record" in report.get("metrics", {})
            else record_reference(report))


def _existing_record_reference(report: dict, run_dir: Path) -> dict | None:
    from ascend_msprof_skill.evidence_binding import record_locator, safe_path
    from ascend_msprof_skill.caller_record import SUPPORTED_RECORD_SCHEMAS, record_reference
    for version in SUPPORTED_RECORD_SCHEMAS:
        reference = record_reference(report, schema_version=version)
        if safe_path(run_dir, record_locator(reference["sha256"])).exists():
            return reference
    return None


def caller_query_options(report: dict, run_dir: Path | None = None) -> dict:
    """New reports carry a stable record; historical reports retain exact version reads."""
    if "formal_measurement_record" in report.get("metrics", {}):
        return {"measurement_record_id": formal_measurement_record(report)["sha256"]}
    if run_dir is not None and (reference := _existing_record_reference(report, run_dir)) is not None:
        return {"measurement_record_id": reference["sha256"]}
    return {"report_version": formal_report_version(report)}


def _records_for_run(report: dict, run_dir: Path) -> tuple[dict, ...]:
    """Explicit references and existing locators fix the schema; otherwise defer
    historical attachment selection to the store, with v2 preferred for new data.

    The locator hint also preserves the original run's schema on explicit export.
    It does not require source attachments to be reusable in a new export root.
    """
    from .caller_record import SUPPORTED_RECORD_SCHEMAS, record_reference
    if "formal_measurement_record" in report.get("metrics", {}):
        return (formal_measurement_record(report),)
    reference = _existing_record_reference(report, run_dir)
    if reference is not None:
        return (reference,)
    return tuple(record_reference(report, schema_version=version) for version in SUPPORTED_RECORD_SCHEMAS)


def _relocate(path: Path, mappings: tuple[tuple[Path, Path], ...]) -> Path:
    path = path.expanduser().absolute()
    for old, new in mappings:
        try:
            return new / path.relative_to(old)
        except ValueError:
            pass
    return path


def _issue(issues: list[dict], code: str, message: str) -> None:
    issues.append({"code": code, "message": message})


def _local_target(root: Path, relative: str) -> Path:
    if Path(relative).is_absolute():
        raise ValueError("export paths must be run-relative")
    target = root / relative
    if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"export target escapes profile run: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _is_formal_report(metrics: dict) -> bool:
    protocol = metrics.get("measurement_protocol")
    metric = protocol.get("metric") if isinstance(protocol, dict) else metrics.get("latency_source")
    return metrics.get("formal_measurement_mode") == "msprof_op" and metric == "device_program_duration_ms"


def _copy_snapshot(*, root: Path, source: Path, relative: str,
                   expected_sha256: str | None, issues: list[dict], kind: str,
                   original_path: str | None = None) -> dict | None:
    try:
        data = source.read_bytes()
    except OSError as exc:
        _issue(issues, f"{kind}_unavailable", f"{source}: {exc}")
        return None
    digest = _sha256(data)
    if not expected_sha256 or digest != expected_sha256:
        _issue(issues, f"{kind}_hash_mismatch",
               f"{source}: expected {expected_sha256}, observed {digest}; not bound")
        return None
    target = _local_target(root, relative)
    if target.exists() and target.read_bytes() != data:
        raise ValueError(f"snapshot already contains different bytes: {target}")
    target.write_bytes(data)
    return {"path": relative, "sha256": digest, "bytes": len(data),
            "original_path": original_path or str(source)}


def snapshot_profile_sources(run_dir: Path, *, source_path: Path, source_sha256: str,
                             generated_sources: list[Path] | None = None) -> dict:
    """Preserve the exact workspace bytes with a profile, before paths can move."""
    manifest = run_dir / "analysis/source_snapshots.json"
    if manifest.exists():
        previous = decode_json(manifest.read_bytes())
        if previous.get("source_sha256") != source_sha256:
            raise ValueError("profile already contains snapshots for a different source")
        snapshots = previous["snapshots"]
        generated = snapshots["generated"]
        if [item["original_path"] for item in generated] != [str(p) for p in generated_sources or []]:
            raise ValueError("profile already contains a different generated-source set")
        bindings = ([snapshots["source"]] if snapshots.get("source") else []) + generated
        for item in bindings:
            saved = _local_target(run_dir, item["path"])
            if _sha256(saved.read_bytes()) != item["sha256"]:
                raise ValueError("existing profile snapshot hash mismatch")
            original = Path(item["original_path"])
            if original.exists() and _sha256(original.read_bytes()) != item["sha256"]:
                raise ValueError("workspace products changed after profile snapshot")
        if snapshots.get("source") and snapshots["source"]["original_path"] != str(source_path):
            raise ValueError("profile already contains a different source declaration")
        return previous
    issues: list[dict] = []
    snapshots = {"source": _copy_snapshot(
        root=run_dir, source=source_path, relative="analysis/sources/source" + source_path.suffix,
        expected_sha256=source_sha256, issues=issues, kind="source"), "generated": []}
    for index, path in enumerate(generated_sources or [], 1):
        # These are the just-captured workspace products, not a historical declaration.
        try:
            digest = _sha256(path.read_bytes())
        except OSError as exc:
            _issue(issues, "generated_unavailable", f"{path}: {exc}")
            continue
        item = _copy_snapshot(root=run_dir, source=path,
            relative=f"analysis/sources/generated/{index:03d}-{path.name}",
            expected_sha256=digest, issues=issues, kind="generated")
        if item:
            snapshots["generated"].append(item)
    if not snapshots["generated"]:
        _issue(issues, "generated_sources_missing", "no generated workspace sources were captured")
    payload = {"schema_version": 1, "source_sha256": source_sha256,
               "snapshots": snapshots, "issues": issues}
    target = _local_target(run_dir, "analysis/source_snapshots.json")
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _sample_profile_run(receipt: dict) -> Path | None:
    # This is the Executor's explicit sample workspace, not a directory-number guess.
    artifact = receipt.get("artifact_dir")
    if isinstance(artifact, str) and artifact:
        return Path(artifact) / "profile/msprof_op"
    analysis = receipt.get("profile_analysis")
    summary = analysis.get("summary") if isinstance(analysis, dict) else None
    return Path(summary).parent.parent if isinstance(summary, str) and summary else None


def _preserved_input(run_dir: Path, original: Path, expected_sha256: str | None,
                     kind: str, report_version: str, record_id: str) -> Path:
    """Recover missing workspace bytes from existing, hash-bound local snapshots."""
    if original.exists() or expected_sha256 is None:
        return original
    from ascend_msprof_skill.evidence_binding import record_caller_artifact
    selected = record_caller_artifact(run_dir, record_id)
    manifests = ([selected] if selected else []) + [
        f"analysis/caller_reports/{report_version}/caller_evidence.json",
        "analysis/caller_evidence.json", "analysis/source_snapshots.json"]
    for manifest in manifests:
        try:
            snapshots = decode_json((run_dir / manifest).read_bytes())["snapshots"]
            if not isinstance(snapshots, dict):
                continue
            refs = [snapshots.get("source")] if kind == "source" else snapshots.get("generated", [])
            for ref in refs:
                if not isinstance(ref, dict) or ref.get("sha256") != expected_sha256:
                    continue
                relative = Path(ref["path"])
                path = (run_dir / relative).resolve()
                if not relative.is_absolute() and path.is_relative_to(run_dir) and path.is_file():
                    # _copy_snapshot verifies the actual bytes against this report.
                    return path
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return original


@dataclass(frozen=True)
class _Report:
    path: Path
    raw: bytes
    value: dict
    version: str

    @classmethod
    def load(cls, path: Path) -> "_Report":
        raw = path.read_bytes()
        value = decode_json(raw)
        if not isinstance(value, dict) or not isinstance(value.get("metrics"), dict):
            raise ValueError("formal report must be an object with metrics")
        if not _is_formal_report(value["metrics"]):
            raise ValueError("report is not an Executor msprof_op device-program measurement")
        formal_measurement_record(value)
        return cls(path, raw, value, formal_report_version(value))


def write_caller_evidence(*, report_path: Path, run_dir: Path,
                          original_run_dir: Path | None = None,
                          source_path: Path | None = None,
                          path_mappings: tuple[tuple[Path, Path], ...] = (),
                          origin_kind: str = "executor", versioned: bool = False) -> Path:
    """Publish one sample; layout choice and recovery belong to the store.

    versioned is retained as a first-publication layout preference for older callers.
    It never bypasses validation of an existing record.
    """
    return _publish(_Report.load(report_path), run_dir, original_run_dir=original_run_dir,
                    source_path=source_path, path_mappings=path_mappings,
                    origin_kind=origin_kind, versioned=versioned)


def _publish(report: _Report, run_dir: Path, *, original_run_dir: Path | None = None,
             source_path: Path | None = None,
             path_mappings: tuple[tuple[Path, Path], ...] = (),
             origin_kind: str = "executor", versioned: bool = False) -> Path:
    run_dir = run_dir.resolve()
    original_run = (original_run_dir or run_dir).resolve()
    records = _records_for_run(report.value, original_run)
    def build(staging: Path, prefix: str, relative: str, record: dict) -> Path:
        return _build_attachment(report, staging, prefix, relative, record,
            context_run=run_dir, original_run=original_run, source_path=source_path,
            path_mappings=path_mappings, origin_kind=origin_kind)
    return CallerAttachmentStore(run_dir).publish(records=records, report_version=report.version,
        original_run=original_run, build=build, prefer_versioned=versioned)


def _build_attachment(prepared: _Report, run_dir: Path, prefix: str, relative: str,
                      record: dict, *, context_run: Path, original_run: Path,
                      source_path: Path | None, path_mappings: tuple[tuple[Path, Path], ...],
                      origin_kind: str) -> Path:
    report, report_bytes, report_path = prepared.value, prepared.raw, prepared.path
    report_version = prepared.version
    metrics = report["metrics"]
    protocol_record = metrics.get("measurement_protocol")
    target = _local_target(run_dir, relative)
    issues: list[dict] = []
    receipts = metrics.get("device_program_profile_receipts", [])
    projection = measurement_projection(report)
    matches = [receipt for receipt in receipts if isinstance(receipt, dict)
               and (path := _sample_profile_run(receipt)) is not None
               and _relocate(path, path_mappings).resolve() == original_run]
    sample = matches[0] if len(matches) == 1 else None
    if sample is None:
        _issue(issues, "sample_binding_unavailable",
               "profile run does not match exactly one report sample workspace")
    expected_sha = metrics.get("profile_source_sha256")
    if sample is not None and sample.get("profile_source_sha256") != expected_sha:
        _issue(issues, "sample_source_mismatch", "sample source SHA-256 differs from formal report")
    context_path = context_run / "analysis/profile_context.json"
    if context_path.is_file():
        context = decode_json(context_path.read_bytes())
        if context.get("source_sha256") not in (None, expected_sha):
            _issue(issues, "profile_source_mismatch", "profile context source differs from formal report")
    compilation = metrics.get("compilation_evidence", {})
    compilation = compilation if isinstance(compilation, dict) else {}
    correctness_receipt = metrics.get("correctness_receipt")
    declared_hashes = {
        "precheck_source_sha256": metrics.get("precheck_source_sha256"),
        "compilation.source_sha256": compilation.get("source_sha256"),
        "correctness_receipt.precheck_source_sha256": (
            correctness_receipt.get("precheck_source_sha256")
            if isinstance(correctness_receipt, dict) else None),
    }
    for label, value in declared_hashes.items():
        if value is not None and value != expected_sha:
            _issue(issues, "source_binding_mismatch", f"{label} differs from formal profile source SHA-256")
    declared_source = (Path(compilation["source_path"]) if compilation.get("source_path") else
                       Path(compilation["execution_attempt"]) / "kernel.py"
                       if compilation.get("execution_attempt") else original_run.parent.parent / "kernel.py")
    actual_source = source_path or _preserved_input(original_run,
        _relocate(declared_source, path_mappings), expected_sha, "source", report_version, record["sha256"])
    snapshots = {"source": _copy_snapshot(
        root=run_dir, source=actual_source, relative=f"{prefix}/source" + actual_source.suffix,
        expected_sha256=expected_sha, issues=issues, kind="source",
        original_path=str(declared_source) if source_path is None else str(source_path)), "generated": []}
    artifact_hashes = compilation.get("artifact_sha256", {})
    for index, original in enumerate(compilation.get("generated_sources", []), 1):
        path = _preserved_input(original_run, _relocate(Path(original), path_mappings),
                                artifact_hashes.get(original), "generated", report_version, record["sha256"])
        item = _copy_snapshot(root=run_dir, source=path,
            relative=f"{prefix}/generated/{index:03d}-{path.name}",
            expected_sha256=artifact_hashes.get(original), issues=issues, kind="generated",
            original_path=original)
        if item:
            snapshots["generated"].append(item)
    if not compilation.get("generated_sources"):
        _issue(issues, "generated_sources_missing", "report contains no captured generated sources")
    raw_report_relative = f"{prefix}/source-report.json"
    raw_report = _local_target(run_dir, raw_report_relative)
    with raw_report.open("xb") as stream:
        stream.write(report_bytes)
    payload = {
        "schema_version": 1, "producer": "kernel-agent", "measurement_record": record,
        "measurement": {
            "mode": "msprof_op", "boundary": "executor_device_program_task_duration",
            "metric": "device_program_duration_ms", "unit": "ms",
            **projection,
            "sample_index": sample.get("attempt_index") if sample else None,
            "sample_duration_ms": sample.get("duration_ms") if sample else None,
        },
        "correctness": {"status": report.get("status"),
            "correctness_ok": report.get("correctness_ok"),
            "tolerance_passed": report.get("tolerance_passed"),
            "receipt": metrics.get("correctness_receipt")},
        "identity": {"candidate_id": report.get("candidate_id"), "source_sha256": expected_sha,
            "measurement_identity": metrics.get("measurement_identity"),
            "measurement_protocol": protocol_record},
        "source_report": {"path": raw_report_relative, "sha256": _sha256(report_bytes),
                          "bytes": len(report_bytes), "original_path": str(report_path.resolve())},
        "snapshots": snapshots,
        "origin": {"kind": origin_kind, "sample_profile_run": str(original_run),
                   "sample_profile_run_declared": str(_sample_profile_run(sample)) if sample else None,
                   "path_mappings": [{"from": str(old), "to": str(new)} for old, new in path_mappings],
                   "source_sha256": expected_sha,
                   "sample_attempt_index": sample.get("attempt_index") if sample else None},
        "issues": issues,
    }
    with target.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, indent=2) + "\n")
    return target


def attach_formal_profile_evidence(report_path: Path) -> list[Path]:
    """Publish immutable report versions; attempt every reported existing sample.

    The legacy manifest keeps its original meaning. Continuation reports use a
    content-addressed namespace and readers select the bound report explicitly.
    A failed optional attachment never prevents other samples from publishing.
    """
    prepared = _Report.load(report_path)
    paths, errors = [], []
    for receipt in prepared.value["metrics"].get("device_program_profile_receipts", []):
        run = _sample_profile_run(receipt)
        if run is None or not run.is_dir():
            continue
        try:
            paths.append(_publish(prepared, run))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{run}: {exc}")
    if errors:
        raise ValueError("caller evidence attachment failed: " + "; ".join(errors))
    return paths


def export_profile_evidence(*, report_path: Path, profile_run: Path, output_dir: Path,
                            source_path: Path | None = None,
                            path_mappings: tuple[tuple[Path, Path], ...] = ()) -> Path:
    """Copy a historical profile and bind an explicitly supplied report, without edits."""
    report_path = report_path.expanduser().resolve(strict=True)
    profile_run = profile_run.expanduser().resolve(strict=True)
    output_dir = output_dir.expanduser().resolve()
    if (output_dir == profile_run or output_dir.is_relative_to(profile_run)
            or profile_run.is_relative_to(output_dir) or report_path.is_relative_to(output_dir)
            or (source_path is not None and source_path.resolve().is_relative_to(output_dir))):
        raise ValueError("export output must not overlap any input")
    if output_dir.exists():
        raise ValueError("export output must be a new directory")
    prepared = _Report.load(report_path)
    # Historical caller attachments remain in the input; export selects this report.
    def ignore_caller(directory, names):
        return ({"caller_evidence.json", "caller", "caller_reports", "caller_records",
                 ".caller-publication.lock"} & set(names)
                | {name for name in names if name.startswith(".caller-stage-")}
                if Path(directory) == profile_run / "analysis" else set())
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".profile-export-", dir=output_dir.parent) as temporary:
        staging = Path(temporary) / "profile"
        shutil.copytree(profile_run, staging, ignore=ignore_caller)
        target = _publish(prepared, staging, original_run_dir=profile_run,
            source_path=source_path, path_mappings=path_mappings,
            origin_kind="explicit_report_export")
        # A cooperating exporter must not replace an existing final directory.
        with CallerAttachmentStore.output_lock(output_dir):
            if output_dir.exists() or output_dir.is_symlink():
                raise ValueError("export output must be a new directory")
            os.rename(staging, output_dir)
        return output_dir / target.relative_to(staging)
