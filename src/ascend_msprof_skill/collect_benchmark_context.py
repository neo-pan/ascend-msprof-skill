"""Import caller natural benchmark evidence without executing a benchmark or profiler."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .benchmark_evidence import ARTIFACT, BenchmarkEvidence, digest_bytes, load_registration, read_imports
from .artifact_reader import decode_json
from .benchmark_types import BenchmarkSource


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def import_benchmark(run_dir: Path, input_path: Path, *, entrypoint: str = "collect-benchmark", optional: bool = False) -> BenchmarkEvidence | None:
    raw = input_path.read_bytes()
    data = decode_json(raw)
    if not isinstance(data, dict):
        raise ValueError("benchmark JSON must be an object")
    if "assessment" not in data:
        if optional:
            return None
        raise ValueError("benchmark JSON requires assessment")
    path = run_dir / ARTIFACT
    path.resolve().relative_to(run_dir.resolve())
    imports: list[BenchmarkSource] = []
    if path.exists():
        context = load_registration(path)
        imports = list(context.imports)
    digest = digest_bytes(raw)
    artifact = f"context/benchmark-inputs/{digest}.json"
    snapshot = run_dir / artifact
    snapshot.resolve().relative_to(run_dir.resolve())
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    new_snapshot = None
    try:
        with snapshot.open("xb") as stream:
            stream.write(raw)
        new_snapshot = (artifact, raw, data)
    except FileExistsError:
        pass  # read_imports checks existing bytes; an altered snapshot stays invalid.
    existing = next((s for s in imports if s.artifact == artifact), None)
    if existing is None:
        imports.append(BenchmarkSource(artifact=artifact, sha256=digest, entrypoints=(entrypoint,)))
    else:
        imports[imports.index(existing)] = BenchmarkSource(artifact=artifact, sha256=digest,
            entrypoints=tuple(sorted(set((*existing.entrypoints, entrypoint)))))
    evidence = read_imports(run_dir, tuple(imports), new_snapshot=new_snapshot)
    atomic_json(path, evidence.as_context().model_dump(mode="json"))
    return evidence


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--benchmark-json", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        evidence = import_benchmark(args.run_dir.resolve(), args.benchmark_json)
    except (OSError, ValueError) as exc:
        ap.error(str(exc))
    print(f"wrote {args.run_dir / ARTIFACT}")
    for item in evidence.issues:
        print(f"{item.id}: {item.reason_code}")
    return 1 if evidence.issues else 0
