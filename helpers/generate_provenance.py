#!/usr/bin/env python3
"""Generate a run provenance manifest from existing Ascend profiling logs."""
from __future__ import annotations

import argparse
import json
import re
import shlex
from collections.abc import Iterable
from pathlib import Path
from typing import Any


EXPECTED_LOGS = [
    "cann_version.cfg",
    "npu_smi_info.stdout",
    "command_msprof.txt",
    "relevant_env.txt",
]
PRIMARY_PROFILER_STEMS = ["msprof_default", "msprof", "command_msprof", "msprof_op"]
AUXILIARY_PROFILER_MARKERS = ["help", "export", "retry", "validation", "round"]
SENSITIVE_PATH_RE = re.compile(r"(?<!>)(?P<path>/(?!/)[^\s:|,)<>'\"]+)")
PLACEHOLDER_PATH_RE = re.compile(r"<abs-path>(?:/[^\s:|,)<>'\"]+)*")
PROF_RANDOM_RE = re.compile(r"\b((?:OP)?PROF)_\d{8,}(?:_\d+)?_[A-Z0-9]{8,}\b")
TIMESTAMP_RE = re.compile(r"\b(20\d\d-\d\d-\d\d \d\d:\d\d:\d\d)\b")
APP_OP_PROFILE_OUTPUTS = ["reports/app", "reports/op"]


def rel_source(run_dir: Path, path: Path) -> str:
    return path.relative_to(run_dir).as_posix()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def read_command(path: Path) -> str:
    parts = []
    for raw_line in read_text(path).splitlines():
        line = raw_line.strip().removesuffix("\\").strip()
        if line:
            parts.append(line)
    return " ".join(parts)


def redact_path(match: re.Match[str]) -> str:
    raw_path = match.group("path")
    if "/reports/" in raw_path:
        suffix = raw_path.split("/reports/", 1)[1]
        sanitized_suffix = PROF_RANDOM_RE.sub(r"\1_<sanitized>", suffix)
        return f"reports/{sanitized_suffix}"
    return "<abs-path>"


def redact_text(text: str) -> str:
    placeholders = []

    def protect_placeholder(match: re.Match[str]) -> str:
        placeholder = match.group(0)
        if "/reports/" in placeholder:
            suffix = placeholder.split("/reports/", 1)[1]
            sanitized_suffix = PROF_RANDOM_RE.sub(r"\1_<sanitized>", suffix)
            placeholder = f"reports/{sanitized_suffix}"
        placeholders.append(placeholder)
        return f"__ASCEND_PROVENANCE_PLACEHOLDER_{len(placeholders) - 1}__"

    text = PLACEHOLDER_PATH_RE.sub(protect_placeholder, text)
    text = SENSITIVE_PATH_RE.sub(redact_path, text)
    text = PROF_RANDOM_RE.sub(r"\1_<sanitized>", text)
    for index, placeholder in enumerate(placeholders):
        text = text.replace(f"__ASCEND_PROVENANCE_PLACEHOLDER_{index}__", placeholder)
    return text


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


def is_auxiliary_profiler_log(path: Path) -> bool:
    stem = path.stem.lower()
    return any(marker in stem for marker in AUXILIARY_PROFILER_MARKERS)


def non_auxiliary_profiler_stems(paths: Iterable[Path]) -> list[str]:
    return sorted({path.stem for path in paths if not is_auxiliary_profiler_log(path)})


def selected_profiler_paths(logs_dir: Path) -> tuple[list[Path], list[Path]]:
    stdout_by_stem = {path.stem: path for path in logs_dir.glob("msprof*.stdout")}
    stdout_by_stem.update({path.stem: path for path in logs_dir.glob("command_msprof.stdout")})
    status_by_stem = {path.stem: path for path in logs_dir.glob("msprof*.status")}
    status_by_stem.update({path.stem: path for path in logs_dir.glob("command_msprof.status")})

    selected_stems = [stem for stem in PRIMARY_PROFILER_STEMS if stem in stdout_by_stem]
    if not selected_stems:
        selected_stems = non_auxiliary_profiler_stems(stdout_by_stem.values())
    if not selected_stems:
        selected_stems = [stem for stem in PRIMARY_PROFILER_STEMS if stem in status_by_stem]
    if not selected_stems:
        selected_stems = non_auxiliary_profiler_stems(status_by_stem.values())

    stdout_paths = [stdout_by_stem[stem] for stem in selected_stems if stem in stdout_by_stem]
    status_paths = [status_by_stem[stem] for stem in selected_stems if stem in status_by_stem]
    return stdout_paths, status_paths


def selected_msprof_command_paths(logs_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in logs_dir.glob("command_msprof*.txt")
        if path.is_file() and not is_auxiliary_profiler_log(path)
    )


def command_output_value(command: str) -> str | None:
    try:
        args = shlex.split(command)
    except ValueError:
        args = command.split()
    for index, arg in enumerate(args):
        if arg.startswith("--output="):
            return arg.split("=", 1)[1]
        if arg == "--output" and index + 1 < len(args):
            return args[index + 1]
    return None


def redact_profile_output_value(value: str) -> str:
    if value.startswith("reports/"):
        return PROF_RANDOM_RE.sub(r"\1_<sanitized>", value)
    return redact_text(value)


def add_profile_output(
    manifest: dict[str, Any],
    *,
    value: str,
    artifact: str,
    field: str,
    app_op_only_when_existing: bool = False,
) -> None:
    redacted = redact_profile_output_value(value)
    if app_op_only_when_existing and manifest.get("profile_outputs") and redacted not in APP_OP_PROFILE_OUTPUTS:
        return
    outputs = manifest.setdefault("profile_outputs", [])
    if any(item.get("value") == redacted for item in outputs):
        return
    item = sourced(redacted, artifact, field)
    outputs.append(item)
    if "profile_output" not in manifest:
        manifest["profile_output"] = item


def infer_profile_outputs_from_commands(manifest: dict[str, Any], run_dir: Path) -> None:
    for path in selected_msprof_command_paths(run_dir / "logs"):
        command = read_command(path)
        if not command:
            continue
        output = command_output_value(command)
        if output:
            add_profile_output(
                manifest,
                value=output,
                artifact=rel_source(run_dir, path),
                field="--output",
                app_op_only_when_existing=True,
            )


def infer_profile_outputs_from_reports(manifest: dict[str, Any], run_dir: Path) -> None:
    for name in ["app", "op"]:
        path = run_dir / "reports" / name
        if path.is_dir() and any(candidate.is_file() for candidate in path.rglob("*")):
            add_profile_output(
                manifest,
                value=rel_source(run_dir, path),
                artifact=rel_source(run_dir, path),
                field="existing_report_dir",
            )


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
    selected = next(((field, values[field]) for field in preferred_fields if values.get(field)), None)
    if selected:
        selected_field, version = selected
        manifest["cann_version"] = sourced(version, artifact, selected_field)
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

    command = read_command(path)
    if command:
        manifest["profile_command"] = sourced(redact_text(command), rel_source(run_dir, path), "command")
    else:
        warnings.append("logs/command_msprof.txt was empty; profiler command not recorded.")


def add_profiler_status(manifest: dict[str, Any], run_dir: Path, warnings: list[str]) -> None:
    logs_dir = run_dir / "logs"
    stdout_paths, status_paths = selected_profiler_paths(logs_dir)
    if not stdout_paths and not status_paths:
        infer_profile_outputs_from_commands(manifest, run_dir)
        infer_profile_outputs_from_reports(manifest, run_dir)
        warnings.append("Missing profiler stdout/status logs; profile date and exit status not recorded.")
        return

    for path in stdout_paths:
        text = read_text(path)
        match = TIMESTAMP_RE.search(text)
        if match and "profile_date" not in manifest:
            manifest["profile_date"] = sourced(match.group(1), rel_source(run_dir, path), "first_timestamp")
        for saved_match in re.finditer(r"Profiling results saved in\s+(.+)", text):
            add_profile_output(
                manifest,
                value=saved_match.group(1).strip(),
                artifact=rel_source(run_dir, path),
                field="Profiling results saved in",
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
    infer_profile_outputs_from_commands(manifest, run_dir)
    infer_profile_outputs_from_reports(manifest, run_dir)


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
    for path in selected_msprof_command_paths(logs_dir):
        source = rel_source(run_dir, path)
        if source not in manifest["sources"]:
            manifest["sources"].append(source)
    stdout_paths, status_paths = selected_profiler_paths(logs_dir)
    for path in [*stdout_paths, *status_paths]:
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
