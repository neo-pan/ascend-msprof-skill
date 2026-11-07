"""Shared display projection of caller-owned formal measurement facts.

This projection does not define the versioned measurement record identity.
"""
from __future__ import annotations


_SAMPLE_FIELDS = (
    "attempt_index", "complete_sample_index", "status", "retained", "duration_ms",
    "profile_source_sha256", "profile_complete", "expected_rows", "observed_rows",
    "launch_durations_us", "steady_state_launch_indices", "launch_total_consistent",
    "kernel_durations_us", "kernel_duration_basis", "frequency_summary", "rejected_reason",
)


def measurement_projection(report: dict) -> dict:
    """Project report values; protocol keys take precedence even when null.

    Missing protocol keys retain historical metrics fallbacks. Missing sample
    fields stay absent, rather than acquiring a value or a new interpretation.
    """
    metrics = report.get("metrics", {})
    protocol = metrics.get("measurement_protocol")
    protocol = protocol if isinstance(protocol, dict) else {}
    receipts = metrics.get("device_program_profile_receipts", [])
    receipts = receipts if isinstance(receipts, list) else []
    return {
        "value": metrics.get("device_program_duration_ms"),
        "aggregation": {
            "within_process": protocol.get("within_process_statistic"),
            "across_process": protocol.get("across_process_statistic"),
        },
        "program_launches": protocol.get("launches_per_process", metrics.get("device_program_launches")),
        "steady_state_skip": protocol.get("steady_state_skip", metrics.get("device_program_steady_state_skip")),
        "samples": [{key: item[key] for key in _SAMPLE_FIELDS if key in item}
                    for item in receipts if isinstance(item, dict)],
    }
