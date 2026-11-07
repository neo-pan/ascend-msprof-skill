"""Versioned caller-owned formal measurement records.

This positive schema separates measurement facts from host delivery metadata.
The record is a projection of a byte-bound source report; its reference is not
part of its own identity. New measurement semantics require a schema revision.
"""
from __future__ import annotations

import hashlib
import json

_REPORT_FIELDS = ("candidate_id", "status", "compile_ok", "runtime_ok", "correctness_ok",
                  "tolerance_passed", "latency_ms")
_METRIC_FIELDS = (
    "formal_measurement_mode", "latency_source", "profile_source_sha256", "precheck_source_sha256",
    "measurement_identity", "measurement_protocol", "device_program_duration_ms",
    "device_program_launches", "device_program_steady_state_skip", "device_program_profile_complete",
    "profile_collection", "correctness_receipt", "compilation_evidence",
)
_SAMPLE_FIELDS = (
    "attempt_index", "complete_sample_index", "artifact_dir", "status", "retained", "duration_ms",
    "profile_source_sha256", "profile_complete", "expected_rows", "observed_rows",
    "launch_durations_us", "steady_state_launch_indices", "launch_total_consistent",
    "kernel_durations_us", "kernel_duration_basis", "frequency_summary", "rejected_reason",
)


SUPPORTED_RECORD_SCHEMAS = (2, 1)
_COLLECTION_FIELDS = ("schema_version", "collection_id", "identity")


def measurement_record(report: dict, *, schema_version: int = 2) -> dict:
    """Select formal facts without hashing logs, query navigation or host bookkeeping."""
    if type(schema_version) is not int or schema_version not in SUPPORTED_RECORD_SCHEMAS:
        raise ValueError("unsupported formal measurement record schema")
    metrics = report.get("metrics", {})
    samples = metrics.get("device_program_profile_receipts", [])
    if not isinstance(samples, list) or any(not isinstance(sample, dict) for sample in samples):
        raise ValueError("formal measurement samples must be objects")
    measurement = {key: metrics.get(key) for key in _METRIC_FIELDS}
    if schema_version == 2 and measurement["profile_collection"] is not None:
        collection = measurement["profile_collection"]
        if not isinstance(collection, dict):
            raise ValueError("formal measurement collection must be an object")
        # The sealed sample set is already in samples. Episode/budget state is
        # delivery metadata; v1 intentionally retains its historical full object.
        measurement["profile_collection"] = {key: collection.get(key) for key in _COLLECTION_FIELDS}
    return {"schema_version": schema_version, "report": {key: report.get(key) for key in _REPORT_FIELDS},
            "measurement": measurement,
            "samples": [{key: sample.get(key) for key in _SAMPLE_FIELDS} for sample in samples]}


def record_reference(report: dict, *, schema_version: int = 2) -> dict:
    data = json.dumps(measurement_record(report, schema_version=schema_version), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"schema_version": schema_version, "sha256": hashlib.sha256(data).hexdigest()}


def validate_record_reference(report: dict, reference: object) -> dict:
    if not isinstance(reference, dict) or type(reference.get("schema_version")) is not int:
        raise ValueError("invalid formal measurement record reference")
    expected = record_reference(report, schema_version=reference["schema_version"])
    if reference != expected:
        raise ValueError("formal measurement record does not match the delivered report")
    return expected
