#!/usr/bin/env python3
"""Collect TileLang benchmark context for an existing profiling run."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
ABS_PATH_RE = re.compile(r"(?P<prefix>^|[\s=([{\"':])(?P<path>/(?!/)[^\s:|,)<>'\"]+)")
MAX_INVENTORY_ITEMS = 200


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel_or_name(run_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(run_dir.resolve()).as_posix()
    except ValueError:
        return path.name


def sanitize_text(value: str) -> str:
    return ABS_PATH_RE.sub(lambda match: f"{match.group('prefix')}<abs-path>", value)


def sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return value


def first_present(mapping: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        value = mapping.get(name)
        if value not in (None, "", []):
            return value
    return None


def nested_first(mapping: dict[str, Any], names: list[str]) -> Any:
    metadata = mapping.get("metadata")
    if isinstance(metadata, dict):
        value = first_present(metadata, names)
        if value not in (None, "", []):
            return value
    return first_present(mapping, names)


def infer_case_count(data: dict[str, Any]) -> int | None:
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        explicit = first_present(metadata, ["case_count", "num_cases", "cases_count", "workload_cases"])
        if isinstance(explicit, int):
            return explicit
        cases_int = metadata.get("cases")
        if isinstance(cases_int, int):
            return cases_int
        cases = metadata.get("cases")
        if isinstance(cases, list):
            return len(cases)
    for key in ["cases", "results"]:
        value = data.get(key)
        if isinstance(value, list):
            return len(value)
    return 1


def numeric_correctness_maxima(correctness: Any) -> list[dict[str, Any]]:
    maxima = []

    def visit(value: Any, path: list[str]) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, [*path, str(key)])
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, [*path, str(index)])
            return
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return
        key_path = ".".join(path)
        key_lower = key_path.lower()
        if "max" in key_lower or "error" in key_lower or "diff" in key_lower:
            maxima.append({"field": key_path, "value": value})

    visit(correctness, [])
    return sorted(maxima, key=lambda item: item["field"])


def normalize_benchmark(data: dict[str, Any]) -> dict[str, Any]:
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    correctness = data.get("correctness")
    correctness_maxima = numeric_correctness_maxima(correctness)
    metadata_maxima = numeric_correctness_maxima(metadata)
    maxima_by_field = {item["field"]: item for item in [*correctness_maxima, *metadata_maxima]}
    runtime_stats = data.get("runtime_stats")
    runtime = data.get("runtime")
    ref_runtime = data.get("ref_runtime")
    speedup = data.get("speedup")

    return {
        "workload": {
            "id": sanitize_value(
                nested_first(data, ["workload_id", "id", "case_id", "name", "operator", "op_name"])
            ),
            "shape": sanitize_value(
                nested_first(data, ["workload_shape", "shape", "shapes", "input_shape", "problem_shape"])
            ),
            "dtype": sanitize_value(
                nested_first(data, ["workload_dtype", "dtype", "dtypes", "input_dtype", "data_type"])
            ),
            "case_count": infer_case_count(data),
        },
        "candidate": {
            "compiled": data.get("compiled"),
            "runtime": sanitize_value(runtime),
            "runtime_stats": sanitize_value(runtime_stats),
            "ref_runtime": sanitize_value(ref_runtime),
            "speedup": sanitize_value(speedup),
            "error": sanitize_value(data.get("error")),
        },
        "correctness": {
            "raw": sanitize_value(correctness),
            "maxima": sorted(maxima_by_field.values(), key=lambda item: item["field"]),
        },
        "metadata": sanitize_value(metadata),
        "jit_config": sanitize_value(
            first_present(metadata, ["jit_config", "tilelang_config", "config", "compile_config"])
        ),
    }


def file_record(run_dir: Path, path: Path, *, include_content: bool = False) -> dict[str, Any]:
    record: dict[str, Any] = {
        "artifact": rel_or_name(run_dir, path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }
    if include_content:
        record["content"] = read_text(path)
    return record


def inventory_jit_debug(run_dir: Path, root: Path | None, warnings: list[str]) -> dict[str, Any] | None:
    if root is None:
        return None
    if not root.exists():
        warnings.append(f"Optional JIT debug root missing: {root.name}")
        return {"provided": root.name, "found": False, "artifacts": []}
    if not root.is_dir():
        warnings.append(f"Optional JIT debug root is not a directory: {root.name}")
        return {"provided": root.name, "found": False, "artifacts": []}

    artifacts = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        if len(artifacts) >= MAX_INVENTORY_ITEMS:
            warnings.append(f"JIT debug inventory truncated at {MAX_INVENTORY_ITEMS} files.")
            break
        artifacts.append(
            {
                "artifact": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "provided": rel_or_name(run_dir, root),
        "found": True,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


def collect_context(
    run_dir: Path,
    payload_src: Path,
    benchmark_json: Path,
    jit_debug_root: Path | None,
) -> dict[str, Any]:
    warnings: list[str] = []
    with benchmark_json.open(encoding="utf-8") as f:
        benchmark = json.load(f)
    if not isinstance(benchmark, dict):
        raise ValueError("benchmark JSON must contain a top-level object")

    context = {
        "schema_version": SCHEMA_VERSION,
        "sources": {
            "benchmark_json": file_record(run_dir, benchmark_json),
            "payload": file_record(run_dir, payload_src, include_content=True),
        },
        "benchmark": normalize_benchmark(benchmark),
        "jit_debug": inventory_jit_debug(run_dir, jit_debug_root, warnings),
        "warnings": warnings,
    }
    return context


def write_context(run_dir: Path, context: dict[str, Any]) -> Path:
    analysis_dir = run_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    out = analysis_dir / "tilelang_context.json"
    out.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def existing_file(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    if not path.is_file():
        raise ValueError(f"{label} is not a file: {path}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--payload-src", type=Path, required=True)
    ap.add_argument("--benchmark-json", type=Path, required=True)
    ap.add_argument("--jit-debug-root", type=Path)
    args = ap.parse_args(argv)

    run_dir = args.run_dir.resolve()
    payload_src = args.payload_src.resolve()
    benchmark_json = args.benchmark_json.resolve()
    jit_debug_root = args.jit_debug_root.resolve() if args.jit_debug_root else None

    try:
        if not run_dir.exists():
            raise FileNotFoundError(f"run directory not found: {run_dir}")
        existing_file(payload_src, "payload source")
        existing_file(benchmark_json, "benchmark JSON")
        context = collect_context(run_dir, payload_src, benchmark_json, jit_debug_root)
        out = write_context(run_dir, context)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for warning in context.get("warnings", []):
        print(f"warning: {warning}", file=sys.stderr)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
