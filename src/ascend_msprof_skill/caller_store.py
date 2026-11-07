"""Immutable caller attachment storage, independent of collection/measurement policy.

Selection, validation and publication are one operation under a short run-local
lock. Readers never see a partially written manifest. Historical orphan evidence
is not staging and is never removed or rebuilt by this module.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Callable, Iterator

from .artifact_reader import decode_json
from .caller_record import record_reference, validate_record_reference
from .caller_validation import inspect_attachment
from .evidence_binding import record_caller_artifact, record_locator, safe_path


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _target(root: Path, relative: str) -> Path:
    path = root / relative
    safe_path(root, relative)
    if path.is_symlink():
        raise ValueError("caller publication target must not be a symlink")
    return path


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never unlink the lock inode: waiters may already hold a descriptor to it.
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _manifest_record(root: Path, target: Path, *, schema_version: int = 2) -> tuple[dict, dict]:
    payload = decode_json(target.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError("caller manifest must be an object")
    ref = payload["source_report"]
    data = safe_path(root, ref["path"]).read_bytes()
    if _digest(data) != ref["sha256"]:
        raise ValueError("existing caller evidence hash mismatch")
    report = decode_json(data)
    if not isinstance(report, dict) or not isinstance(report.get("metrics"), dict):
        raise ValueError("sealed source report must be an object with metrics")
    carried = report.get("metrics", {}).get("formal_measurement_record")
    has_carried = "formal_measurement_record" in report["metrics"]
    reference = (validate_record_reference(report, payload["measurement_record"])
                 if "measurement_record" in payload else
                 validate_record_reference(report, carried) if has_carried else record_reference(report, schema_version=schema_version))
    if has_carried and validate_record_reference(report, carried) != reference:
        raise ValueError("caller manifest and source report reference disagree")
    return reference, payload


def _verify(root: Path, target: Path, record: dict, original_run: Path) -> None:
    reference, payload = _manifest_record(root, target, schema_version=record["schema_version"])
    if reference != record:
        raise ValueError("profile already binds a different formal report")
    origin = payload.get("origin")
    if not isinstance(origin, dict) or origin.get("sample_profile_run") != str(original_run):
        raise ValueError("profile already binds a different sample origin")
    inspect_attachment(root, payload, str(target.relative_to(root))).require_consistent()


class CallerAttachmentStore:
    def __init__(self, run_dir: Path):
        self.root = run_dir.resolve()

    @staticmethod
    def output_lock(output: Path):
        return _lock(output.parent / ("." + output.name + ".export.lock"))

    def _damaged_owner(self, manifest: Path, fallback_report: Path, record: dict) -> str:
        """Only a surviving valid locator can establish ownership of damaged data.

        Unverified declarations can veto recovery, never authorize a new binding.
        This distinction matters for pre-reference reports and compound faults.
        """
        try:
            payload = decode_json(manifest.read_bytes())
        except (OSError, ValueError):
            payload = None
        if isinstance(payload, dict) and payload.get("measurement_record") == record:
            return "current"
        report_path = fallback_report
        if isinstance(payload, dict) and isinstance(payload.get("source_report"), dict):
            try:
                report_path = safe_path(self.root, payload["source_report"]["path"])
            except (ValueError, KeyError, TypeError):
                return "unknown"
        try:
            report = decode_json(report_path.read_bytes())
            # This is only a veto, not authentication of the damaged source report.
            if record_reference(report, schema_version=record["schema_version"]) == record:
                return "current"
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
        owners = []
        index = _target(self.root, "analysis/caller_records")
        if index.is_dir():
            for path in index.glob("*.json"):
                try:
                    locator = decode_json(path.read_bytes())
                    if (not isinstance(locator, dict) or type(locator.get("schema_version")) is not int
                            or locator["schema_version"] != 1
                            or locator.get("record_sha256") != path.stem
                            or record_locator(path.stem) != str(path.relative_to(self.root))
                            or not isinstance(locator.get("sha256"), str)
                            or len(locator["sha256"]) != 64
                            or any(c not in "0123456789abcdef" for c in locator["sha256"])):
                        continue
                    if safe_path(self.root, locator["artifact"]) == manifest:
                        owners.append(path.stem)
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        if record["sha256"] in owners:
            return "current"
        return "other" if len(owners) == 1 else "unknown"

    def _select(self, records: tuple[dict, ...], version: str, prefer_versioned: bool) -> tuple[str, str, dict]:
        # An existing current locator is authoritative, including when damaged.
        for record in records:
            located = record_caller_artifact(self.root, record["sha256"])
            if located is not None:
                return located, str(Path(located).parent), record
        recovered = self._unindexed_attachment(records)
        if recovered is not None:
            relative, record = recovered
            return relative, str(Path(relative).parent), record
        record = records[0]
        prefix = f"analysis/caller_reports/{version}"
        relative = f"{prefix}/caller_evidence.json"
        legacy = _target(self.root, "analysis/caller_evidence.json")
        legacy_dir = _target(self.root, "analysis/caller")
        occupied = legacy.exists() or (legacy_dir.exists() and any(legacy_dir.iterdir()))
        return ((relative, prefix, record) if prefer_versioned or occupied else
                ("analysis/caller_evidence.json", "analysis/caller", record))

    def _unindexed_attachment(self, records: tuple[dict, ...]) -> tuple[str, dict] | None:
        """Recover one exact record, never a latest report version.

        Only writers without a locator inspect historical attachment metadata.
        Queries and indexed reuse are direct lookups. Raw CSV is never scanned.
        """
        legacy = _target(self.root, "analysis/caller_evidence.json")
        legacy_dir = _target(self.root, "analysis/caller")
        candidates = []
        if legacy.exists() or (legacy_dir.exists() and any(legacy_dir.iterdir())):
            candidates.append((legacy, legacy_dir / "source-report.json"))
        versions = _target(self.root, "analysis/caller_reports")
        if versions.is_dir():
            for directory in versions.iterdir():
                if directory.is_dir() and any(directory.iterdir()):
                    relative = str((directory / "caller_evidence.json").relative_to(self.root))
                    candidates.append((_target(self.root, relative), directory / "source-report.json"))
        matches: list[list[str]] = [[] for _ in records]
        for target, source_report in candidates:
            try:
                # Explicit manifest/report references always retain their schema.
                # Only pre-reference data may be interpreted in a candidate schema.
                for index, record in enumerate(records):
                    reference, _ = _manifest_record(self.root, target,
                        schema_version=record["schema_version"])
                    if reference == record:
                        matches[index].append(str(target.relative_to(self.root)))
                        break
            except (OSError, ValueError, KeyError, TypeError):
                if any(self._damaged_owner(target, source_report, record) != "other" for record in records):
                    raise ValueError("caller snapshots exist without a manifest or valid binding; inspection required")
        for record, paths in zip(records, matches):
            if len(paths) > 1:
                raise ValueError("multiple unindexed caller attachments claim the same formal record")
            if paths:
                return paths[0], record
        return None

    def _publish_locator(self, target: Path, record: dict) -> None:
        path = _target(self.root, record_locator(record["sha256"]))
        value = {"schema_version": 1, "record_sha256": record["sha256"],
                 "artifact": str(target.relative_to(self.root)), "sha256": _digest(target.read_bytes())}
        if path.exists():
            if decode_json(path.read_bytes()) != value:
                raise ValueError("formal measurement record already binds a different caller attachment")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".caller-record-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(value, indent=2) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.link(name, path)
            _sync_directory(path.parent)
        finally:
            Path(name).unlink(missing_ok=True)

    def publish(self, *, records: tuple[dict, ...], report_version: str, original_run: Path,
                build: Callable[[Path, str, str, dict], Path], prefer_versioned: bool = False) -> Path:
        lock = _target(self.root, "analysis/.caller-publication.lock")
        with _lock(lock):
            relative, prefix, record = self._select(records, report_version, prefer_versioned)
            target = _target(self.root, relative)
            if target.exists():
                _verify(self.root, target, record, original_run)
                self._publish_locator(target, record)
                return target
            destination = _target(self.root, prefix)
            if destination.exists() and any(destination.iterdir()):
                raise ValueError("caller snapshots exist without a manifest; refusing to overwrite evidence")
            with tempfile.TemporaryDirectory(prefix=".caller-stage-", dir=lock.parent) as temporary:
                staging = Path(temporary)
                staged_manifest = build(staging, prefix, relative, record)
                _verify(staging, staged_manifest, record, original_run)
                for file in staging.rglob("*"):
                    if file.is_file():
                        with file.open("rb") as stream:
                            os.fsync(stream.fileno())
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.rename(staging / prefix, destination)
                # Versioned manifests move atomically with their data. Legacy has
                # an external compatibility manifest, published only when complete.
                if not target.exists():
                    try:
                        os.link(staged_manifest, target)
                    except BaseException:
                        # Only our just-created, still-unpublished directory is owned.
                        if not target.exists():
                            shutil.rmtree(destination)
                        raise
                _sync_directory(destination.parent)
                self._publish_locator(target, record)
                return target
