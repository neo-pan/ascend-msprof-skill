"""Caller-owned natural measurements: validation and offline evidence reading."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ARTIFACT = "analysis/benchmark_context.json"
CONTRACT_VERSION = "1.0"


def json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def digest_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def semantic_key(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)


def get(record: Any, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(record, dict):
            return None
        record = record.get(part)
    return record


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def integer(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def number(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def source_ref(source: dict[str, Any], field: str = "") -> dict[str, Any]:
    return {"artifact": source["artifact"], "sha256": source.get("sha256"),
            "field_ref": "assessment" + (f".{field}" if field else "")}


def issue(field: str, status: str, reason: str, source: dict[str, Any], value: Any = None) -> dict[str, Any]:
    return {"id": field, "status": status, "reason_code": reason,
            "value": json_safe(value), "sources": [source_ref(source, field)]}


def _correctness_issues(record: Any, source: dict[str, Any]) -> list[dict[str, Any]]:
    """One rule for correctness, shared by measurement validation and partial use."""
    issues = []
    fields = (
        ("correctness", lambda v: isinstance(v, dict)),
        ("correctness.reference", lambda v: isinstance(v, dict)),
        ("correctness.subject_id", nonempty),
        ("subject.implementation.id", nonempty),
        ("correctness.reference.id", nonempty),
        ("correctness.reference.version", nonempty),
        ("correctness.method", nonempty),
        ("correctness.tolerances", lambda v: isinstance(v, dict)),
        ("correctness.case_count", lambda v: type(v) is int and v == 1),
        ("correctness.status", lambda v: v in ("pass", "fail", "error")),
    )
    for field, predicate in fields:
        value = get(record, field)
        if value is None:
            issues.append(issue(field, "missing", "required_field_missing", source))
        elif not predicate(value):
            issues.append(issue(field, "invalid", "invalid_value", source, value))
    status = get(record, "correctness.status")
    if status in ("fail", "error"):
        issues.append(issue("correctness.status", "invalid", "correctness_failed", source, status))
    subject, tested = get(record, "subject.implementation.id"), get(record, "correctness.subject_id")
    if subject is not None and tested is not None and subject != tested:
        issues.append(issue("correctness.subject_id", "mismatch", "correctness_subject_mismatch", source, tested))
    tolerances = get(record, "correctness.tolerances")
    if isinstance(tolerances, dict) and any(not number(v) or v < 0 for v in tolerances.values()):
        issues.append(issue("correctness.tolerances", "invalid", "invalid_tolerance", source, tolerances))
    # A timing failure does not undo correctness. Earlier or unspecified failures
    # cannot establish a successful correctness check for this implementation.
    if isinstance(record, dict) and "failure" in record and get(record, "failure.stage") != "timing":
        issues.append(issue("failure", "invalid", "measurement_stage_failed", source, record["failure"]))
    return issues


def validate_measurement(value: Any, source: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Validate the supported contract; samples remain solely in the raw snapshot."""
    issues: list[dict[str, Any]] = []
    if not isinstance(value, dict):
        return None, [issue("", "missing" if value is None else "invalid", "assessment_object_required", source, value)]
    record = dict(value)
    if isinstance(record.get("measurement"), dict):
        record["measurement"] = {k: v for k, v in record["measurement"].items() if k != "samples_ms"}

    def require(path: str, predicate, reason: str = "invalid_value") -> Any:
        item = get(record, path)
        if item is None:
            issues.append(issue(path, "missing", "required_field_missing", source))
        elif not predicate(item):
            issues.append(issue(path, "invalid", reason, source, item))
        return item

    for path in ("producer", "subject", "subject.implementation", "workload", "protocol", "protocol.timer", "environment", "environment.device", "measurement"):
        require(path, lambda v: isinstance(v, dict))
    require("contract_version", lambda v: v == CONTRACT_VERSION, "unsupported_contract")
    for path in ("measurement_id", "producer.name", "producer.version", "subject.scope",
                 "subject.implementation.source", "workload.id", "workload.dtype",
                 "protocol.timer.name", "protocol.timer.version", "protocol.scope", "protocol.synchronization",
                 "protocol.cache_policy", "protocol.reuse_policy", "protocol.concurrency", "protocol.sample_unit",
                 "protocol.normalization", "protocol.independence", "protocol.execution_order",
                 "environment.device.model", "environment.device.id", "environment.driver_version", "environment.source"):
        require(path, nonempty)

    def timestamp(v: Any) -> bool:
        if not nonempty(v):
            return False
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).tzinfo is not None
        except ValueError:
            return False

    require("collected_at", timestamp)
    for path in ("subject.build", "workload.parameters", "environment.control_policy"):
        require(path, lambda v: isinstance(v, dict))
    require("workload.shape", lambda v: isinstance(v, list) and all(integer(n, 1) for n in v))
    require("workload.case_count", lambda v: type(v) is int and v == 1, "only_single_case_supported")
    issues.extend(_correctness_issues(record, source))
    require("protocol.natural", lambda v: v is True, "natural_measurement_required")
    require("protocol.warmup", integer)
    require("protocol.calls_per_sample", lambda v: integer(v, 1))
    require("environment.device.count", lambda v: integer(v, 1))
    require("environment.runtimes", lambda v: isinstance(v, dict) and nonempty(v.get("cann")) and all(nonempty(k) and nonempty(n) for k, n in v.items()))
    require("measurement.value_ms", lambda v: number(v) and v > 0)
    require("measurement.statistic", lambda v: v in ("mean", "median"))
    require("measurement.sample_count", lambda v: integer(v, 1))

    for group in ("inputs", "outputs"):
        tensors = require(group, lambda v: isinstance(v, list) and bool(v))
        if not isinstance(tensors, list):
            continue
        names = set()
        for i, tensor in enumerate(tensors):
            prefix = f"{group}[{i}]"
            if not isinstance(tensor, dict):
                issues.append(issue(prefix, "invalid", "tensor_object_required", source, tensor))
                continue
            fields = {
                "name": nonempty, "dtype": nonempty, "layout": nonempty,
                "shape": lambda v: isinstance(v, list) and all(integer(n, 1) for n in v),
                "stride": lambda v: isinstance(v, list) and all(integer(n) for n in v),
                "offset": integer,
            }
            for field, predicate in fields.items():
                item = tensor.get(field)
                if item is None or not predicate(item):
                    issues.append(issue(f"{prefix}.{field}", "missing" if item is None else "invalid", "invalid_tensor_field", source, item))
            name = tensor.get("name")
            if nonempty(name):
                if name in names:
                    issues.append(issue(f"{prefix}.name", "invalid", "duplicate_tensor_name", source, name))
                names.add(name)
            if isinstance(tensor.get("shape"), list) and isinstance(tensor.get("stride"), list) and len(tensor["shape"]) != len(tensor["stride"]):
                issues.append(issue(prefix, "invalid", "stride_rank_mismatch", source, tensor))
        if all(isinstance(t, dict) and nonempty(t.get("name")) for t in tensors):
            record[group] = sorted(tensors, key=lambda t: t["name"])

    identity = require("input_identity", lambda v: isinstance(v, dict))
    if isinstance(identity, dict):
        kind = require("input_identity.kind", lambda v: v in ("digest", "generator"))
        if kind == "digest":
            require("input_identity.sha256", lambda v: isinstance(v, str) and len(v) == 64 and all(c in "0123456789abcdef" for c in v))
        elif kind == "generator":
            for path in ("input_identity.name", "input_identity.version"):
                require(path, nonempty)
            require("input_identity.parameters", lambda v: isinstance(v, dict))
            require("input_identity.seed", integer)
    if "failure" in record:
        require("failure.stage", lambda v: v in ("compile", "correctness", "timing"))
        require("failure.message", nonempty)
        if get(record, "failure.stage") == "timing":
            issues.append(issue("failure", "invalid", "measurement_stage_failed", source, record["failure"]))

    def check_finite(item: Any, path: str) -> None:
        if isinstance(item, float) and not math.isfinite(item):
            issues.append(issue(path, "invalid", "nonfinite_value", source, item))
        elif isinstance(item, dict):
            for key, child in item.items():
                check_finite(child, f"{path}.{key}" if path else key)
        elif isinstance(item, list):
            for i, child in enumerate(item):
                check_finite(child, f"{path}[{i}]")

    check_finite(record, "")
    return json_safe(record), issues


@dataclass(frozen=True)
class BenchmarkEvidence:
    record: dict[str, Any] | None = None
    records: tuple[dict[str, Any], ...] = ()
    sources: tuple[dict[str, Any], ...] = ()
    issues: tuple[dict[str, Any], ...] = ()

    def correctness(self) -> tuple[bool, list[dict[str, Any]]]:
        """Usable correctness for this record; profiler subject linkage is separate."""
        # Registered source and contract failures affect every use of the record.
        issues = [item for item in self.issues if item["id"] in {"", "imports", "contract_version"}]
        if self.record is None or not self.sources:
            return False, list(self.issues)
        if issues:
            return False, issues
        for source in self.sources:
            issues.extend(_correctness_issues(self.record, source))
        return not issues, issues

    def as_context(self) -> dict[str, Any]:
        return {"schema_version": CONTRACT_VERSION, "imports": list(self.sources),
                "measurement": self.record if not self.issues else None,
                "issues": list(self.issues)}

    def as_measurement(self) -> dict[str, Any]:
        return {"record": self.record, "conflicting_records": list(self.records) if len(self.records) > 1 else [],
                "sources": [source_ref(s) for s in self.sources], "authority": "caller_provided"}


def read_imports(run_dir: Path, imports: list[Any]) -> BenchmarkEvidence:
    records: dict[str, dict[str, Any]] = {}
    issues = []
    sources = []
    if not imports:
        issues.append(issue("imports", "missing", "benchmark_import_missing", {"artifact": ARTIFACT}))
    for entry in imports:
        if not isinstance(entry, dict) or not nonempty(entry.get("artifact")):
            issues.append(issue("imports", "invalid", "invalid_source", {"artifact": ARTIFACT}, entry))
            continue
        source = dict(entry)
        sources.append(source)
        path = run_dir / source["artifact"]
        try:
            # Evidence replay is confined to the run, including symlink resolution.
            path.resolve().relative_to(run_dir.resolve())
            raw = path.read_bytes()
            if digest_bytes(raw) != source.get("sha256"):
                issues.append(issue("", "conflict", "source_digest_mismatch", source))
                continue
            data = json.loads(raw)
        except (OSError, ValueError) as exc:
            issues.append(issue("", "invalid", "source_unreadable", source, str(exc)))
            continue
        record, validation = validate_measurement(data.get("assessment") if isinstance(data, dict) else data, source)
        issues.extend(validation)
        if record is not None:
            records[semantic_key(record)] = record
    if len(records) > 1:
        issues.append({"id": "measurement", "status": "conflict", "reason_code": "conflicting_measurements",
                       "value": list(records.values()), "sources": [source_ref(s) for s in sources]})
    unique = tuple(records.values())
    return BenchmarkEvidence(unique[0] if len(unique) == 1 else None, unique, tuple(sources), tuple(issues))


def load_benchmark(run_dir: Path) -> BenchmarkEvidence:
    path = run_dir / ARTIFACT
    if not path.exists():
        return BenchmarkEvidence(issues=(issue("", "missing", "benchmark_context_missing", {"artifact": ARTIFACT}),))
    try:
        context = json.loads(path.read_bytes())
        if not isinstance(context, dict) or context.get("schema_version") != CONTRACT_VERSION or not isinstance(context.get("imports"), list):
            raise ValueError("unsupported or invalid benchmark context")
    except (OSError, ValueError) as exc:
        return BenchmarkEvidence(issues=(issue("", "invalid", "benchmark_context_invalid", {"artifact": ARTIFACT}, str(exc)),))
    return read_imports(run_dir, context["imports"])
