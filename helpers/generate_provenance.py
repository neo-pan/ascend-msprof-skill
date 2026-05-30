#!/usr/bin/env python3
"""Generate a run provenance manifest from existing Ascend profiling logs."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


EXPECTED_LOGS = [
    "cann_version.cfg",
    "npu_smi_info.stdout",
    "command_msprof.txt",
    "relevant_env.txt",
]
PROFILER_LOG_PATTERNS = ["msprof*.stdout", "msprof*.status", "command_msprof.status"]
SENSITIVE_PATH_RE = re.compile(r"(?P<path>(?:/data|/home|/root|/tmp|/var/tmp)/[^\s:|,)]+)")
PROF_RANDOM_RE = re.compile(r"\b((?:OP)?PROF)_\d{8,}(?:_\d+)?_[A-Z0-9]{8,}\b")
TIMESTAMP_RE = re.compile(r"\b(20\d\d-\d\d-\d\d \d\d:\d\d:\d\d)\b")


def rel_source(run_dir: Path, path: Path) -> str:
    return path.relative_to(run_dir).as_posix()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def redact_text(text: str) -> str:
    text = SENSITIVE_PATH_RE.sub("<abs-path>", text)
    return PROF_RANDOM_RE.sub(r"\1_<sanitized>", text)


def sourced(value: Any, artifact: str, field: str) -> dict[str, Any]:
    return {"value": value, "source": {"artifact": artifact, "field": field}}


def parse_key_values(path: Path) -> dict[str, str]:
    values = {}
    for raw_line in read_text(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("[]")
    return values


def add_cann_version(manifest: dict[str, Any], run_dir: Path, warnings: list[str]) -> None:
    path = run_dir / "logs" / "cann_version.cfg"
    if not path.exists():
        warnings.append("Missing logs/cann_version.cfg; CANN version not recorded.")
        return

    values = parse_key_values(path)
    artifact = rel_source(run_dir, path)
    preferred_fields = [
        "toolkit_running_version",
        "runtime_running_version",
        "compiler_running_version",
        "opp_running_version",
    ]
    version = next((values[field] for field in preferred_fields if values.get(field)), None)
    if version:
        manifest["cann_version"] = sourced(version, artifact, "toolkit_running_version")
    else:
        warnings.append("logs/cann_version.cfg did not contain a recognized running version field.")
    manifest["cann_components"] = {
        key: sourced(value, artifact, key)
        for key, value in sorted(values.items())
        if key.endswith("_running_version")
    }


def add_hardware(manifest: dict[str, Any], run_dir: Path, warnings: list[str]) -> None:
    path = run_dir / "logs" / "npu_smi_info.stdout"
    if not path.exists():
        warnings.append("Missing logs/npu_smi_info.stdout; hardware summary not recorded.")
        return

    devices = []
    pattern = re.compile(r"^\|\s*(\d+)\s+(910\S*)\s+\|\s+([A-Za-z]+)\s+\|")
    for raw_line in read_text(path).splitlines():
        match = pattern.match(raw_line)
        if match:
            devices.append(
                {
                    "npu": match.group(1),
                    "name": match.group(2),
                    "health": match.group(3),
                }
            )
    artifact = rel_source(run_dir, path)
    if not devices:
        warnings.append("logs/npu_smi_info.stdout did not contain recognized NPU rows.")
        return

    unique_names = sorted({device["name"] for device in devices})
    summary = f"{len(devices)} x {', '.join(unique_names)}"
    health_states = sorted({device["health"] for device in devices})
    if health_states:
        summary = f"{summary}; health {', '.join(health_states)}"
    manifest["hardware"] = {
        "summary": sourced(summary, artifact, "NPU/Name/Health"),
        "devices": [
            {
                "npu": sourced(device["npu"], artifact, "NPU"),
                "name": sourced(device["name"], artifact, "Name"),
                "health": sourced(device["health"], artifact, "Health"),
            }
            for device in devices
        ],
    }


def add_command(manifest: dict[str, Any], run_dir: Path, warnings: list[str]) -> None:
    path = run_dir / "logs" / "command_msprof.txt"
    if not path.exists():
        warnings.append("Missing logs/command_msprof.txt; profiler command not recorded.")
        return

    command = " ".join(line.strip() for line in read_text(path).splitlines() if line.strip())
    if command:
        manifest["profile_command"] = sourced(redact_text(command), rel_source(run_dir, path), "command")
    else:
        warnings.append("logs/command_msprof.txt was empty; profiler command not recorded.")


def add_profiler_status(manifest: dict[str, Any], run_dir: Path, warnings: list[str]) -> None:
    logs_dir = run_dir / "logs"
    stdout_paths = sorted(logs_dir.glob("msprof*.stdout"))
    status_paths = sorted(logs_dir.glob("msprof*.status")) + sorted(logs_dir.glob("command_msprof.status"))
    if not stdout_paths and not status_paths:
        warnings.append("Missing profiler stdout/status logs; profile date and exit status not recorded.")
        return

    for path in stdout_paths:
        text = read_text(path)
        match = TIMESTAMP_RE.search(text)
        if match and "profile_date" not in manifest:
            manifest["profile_date"] = sourced(match.group(1), rel_source(run_dir, path), "first_timestamp")
        saved_match = re.search(r"Profiling results saved in\s+(.+)", text)
        if saved_match and "profile_output" not in manifest:
            manifest["profile_output"] = sourced(
                redact_text(saved_match.group(1).strip()),
                rel_source(run_dir, path),
                "Profiling results saved in",
            )
    if stdout_paths and "profile_date" not in manifest:
        newest = max(stdout_paths, key=lambda candidate: candidate.stat().st_mtime)
        manifest["profile_date"] = sourced(
            newest.stat().st_mtime_ns,
            rel_source(run_dir, newest),
            "file_mtime_ns",
        )
        warnings.append("Profiler stdout did not contain a timestamp; used log file mtime_ns.")

    statuses = []
    for path in status_paths:
        status = read_text(path).strip()
        if status:
            statuses.append(sourced(status, rel_source(run_dir, path), "exit_status"))
    if statuses:
        manifest["profiler_status"] = statuses


def add_environment(manifest: dict[str, Any], run_dir: Path, warnings: list[str]) -> None:
    path = run_dir / "logs" / "relevant_env.txt"
    if not path.exists():
        warnings.append("Missing logs/relevant_env.txt; relevant environment not recorded.")
        return

    allowed_keys = ["ASCEND_HOME_PATH", "ASCEND_OPP_PATH"]
    values = parse_key_values(path)
    artifact = rel_source(run_dir, path)
    env = {
        key: sourced(redact_text(values[key]), artifact, key)
        for key in allowed_keys
        if values.get(key)
    }
    path_like_keys = [key for key in values if key not in allowed_keys]
    manifest["environment"] = {
        "selected": env,
        "omitted_keys": sourced(sorted(path_like_keys), artifact, "omitted_keys"),
    }
    if path_like_keys:
        warnings.append("Omitted path-like environment values from logs/relevant_env.txt.")


def build_manifest(run_dir: Path) -> dict[str, Any]:
    logs_dir = run_dir / "logs"
    warnings = []
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_dir": redact_text(run_dir.as_posix()),
        "sources": [],
        "warnings": warnings,
    }
    if not logs_dir.exists():
        warnings.append("Missing logs/ directory; provenance is incomplete.")
    for name in EXPECTED_LOGS:
        path = logs_dir / name
        if path.exists():
            manifest["sources"].append(rel_source(run_dir, path))
    for pattern in PROFILER_LOG_PATTERNS:
        for path in sorted(logs_dir.glob(pattern)):
            source = rel_source(run_dir, path)
            if source not in manifest["sources"]:
                manifest["sources"].append(source)

    add_cann_version(manifest, run_dir, warnings)
    add_hardware(manifest, run_dir, warnings)
    add_command(manifest, run_dir, warnings)
    add_profiler_status(manifest, run_dir, warnings)
    add_environment(manifest, run_dir, warnings)
    manifest["sources"].sort()
    return manifest


def write_manifest(run_dir: Path, manifest: dict[str, Any]) -> Path:
    analysis_dir = run_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    out = analysis_dir / "provenance.json"
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    args = ap.parse_args()

    run_dir = args.run_dir.resolve()
    out = write_manifest(run_dir, build_manifest(run_dir))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
