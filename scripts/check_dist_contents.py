#!/usr/bin/env python3
"""Audit built distribution artifacts for unintended content."""
from __future__ import annotations

import re
import sys
import tarfile
import zipfile
from pathlib import Path


FORBIDDEN_PATTERNS = [
    re.compile(r"(^|/)tests(/|$)"),
    re.compile(r"(^|/)tests/fixtures(/|$)"),
    re.compile(r"(^|/)profile(/|$)"),
    re.compile(r"(^|/)downloads(/|$)"),
    re.compile(r"(^|/)local-notes(/|$)"),
    re.compile(r"(^|/)\.humanize(/|$)"),
    re.compile(r"(^|/)\.codex(/|$)"),
    re.compile(r"(^|/)\.claude(/|$)"),
    re.compile(r"(^|/)PROF_[^/]*(/|$)"),
    re.compile(r"(^|/)OPPROF_[^/]*(/|$)"),
]

REQUIRED_WHEEL_PATHS = [
    "ascend_msprof_skill/cli.py",
    "ascend_msprof_skill/skill/SKILL.md",
    "ascend_msprof_skill/skill/ascend-910b-programming.md",
    "ascend_msprof_skill/skill/reference/01-workflow.md",
    "ascend_msprof_skill/skill/data/reference-sources.yaml",
    "ascend_msprof_skill/skill/assets/harness_template.cpp",
]

REQUIRED_SDIST_PATHS = [
    "README.md",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "scripts/check_dist_contents.py",
    "src/ascend_msprof_skill/cli.py",
    "skills/ascend-msprof-skill/SKILL.md",
    "skills/ascend-msprof-skill/ascend-910b-programming.md",
    "skills/ascend-msprof-skill/reference/01-workflow.md",
    "skills/ascend-msprof-skill/data/reference-sources.yaml",
    "skills/ascend-msprof-skill/assets/harness_template.cpp",
]


def names_for(path: Path) -> list[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as zf:
            return zf.namelist()
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as tf:
            return tf.getnames()
    raise ValueError(f"unsupported distribution artifact: {path}")


def logical_names(path: Path, names: list[str]) -> list[str]:
    normalized = [name.replace("\\", "/") for name in names]
    if not path.name.endswith(".tar.gz"):
        return normalized
    logical = []
    for name in normalized:
        parts = name.split("/", 1)
        logical.append(parts[1] if len(parts) == 2 else parts[0])
    return logical


def audit(path: Path) -> list[str]:
    errors: list[str] = []
    names = names_for(path)
    normalized = logical_names(path, names)
    for name in normalized:
        for pattern in FORBIDDEN_PATTERNS:
            if pattern.search(name):
                errors.append(f"{path}: forbidden path in distribution: {name}")
                break
    if path.suffix == ".whl":
        for name in normalized:
            if name.startswith("skills/"):
                errors.append(f"{path}: wheel must not expose top-level skill source path {name}")
        for required in REQUIRED_WHEEL_PATHS:
            if required not in normalized:
                errors.append(f"{path}: missing required wheel path {required}")
    elif path.name.endswith(".tar.gz"):
        for required in REQUIRED_SDIST_PATHS:
            if required not in normalized:
                errors.append(f"{path}: missing required sdist path {required}")
    return errors


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: check_dist_contents.py dist/*.whl dist/*.tar.gz", file=sys.stderr)
        return 2
    errors: list[str] = []
    for arg in args:
        try:
            errors.extend(audit(Path(arg)))
        except Exception as exc:
            errors.append(f"{arg}: {exc}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("dist contents: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
