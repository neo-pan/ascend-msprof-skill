#!/usr/bin/env python3
"""Validate the ascend-msprof-skill repository surface."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_REFERENCES = [
    "00-directory-layout.md",
    "01-workflow.md",
    "02-harness-guide.md",
    "03-collection.md",
    "04-output-files.md",
    "05-analysis-dimensions.md",
    "06-diagnosis-playbook.md",
    "07-report-template.md",
    "08-ascend-metric-files.md",
    "09-common-issues.md",
]

REQUIRED_HELPERS = [
    "analyze_msprof_outputs.py",
    "compare_runs.py",
    "extract_simulator_hotspots.py",
    "plot_timeline.py",
    "ascend_profile_utils.py",
    "harness_template.cpp",
]

FORMAL_CONTENT_PATHS = [
    "README.md",
    "SKILL.md",
    "AGENTS.md",
    "ARCHITECTURE.md",
    "ascend-910b-programming.md",
    "reference",
    "helpers",
    "scripts",
    "data",
    "tests",
]

_LEGACY_CLI_LOWER = "n" + "cu"
_LEGACY_SKILL = _LEGACY_CLI_LOWER + "-report-skill"
_LEGACY_WIKI = "Kernel" + "Wiki"
_REF_ROOT = "/" + "data/code/ref/"

FORMAL_LEAK_PATTERNS = [
    ("legacy-skill-name", re.compile(r"\b" + re.escape(_LEGACY_SKILL) + r"\b", re.IGNORECASE)),
    ("legacy-skill-path", re.compile(re.escape(_REF_ROOT + _LEGACY_SKILL) + r"\b")),
    ("legacy-wiki-name", re.compile(r"\b" + re.escape(_LEGACY_WIKI) + r"(?:-Ascend)?\b")),
    ("legacy-wiki-path", re.compile(re.escape(_REF_ROOT + _LEGACY_WIKI) + r"(?:-Ascend)?\b")),
    ("legacy-arch-100", re.compile(r"\b" + "sm" + r"_?100\b", re.IGNORECASE)),
    ("legacy-arch-90", re.compile(r"\b" + "sm" + r"_?90\b", re.IGNORECASE)),
    ("legacy-device", re.compile(r"\b" + "B" + r"200\b")),
    ("legacy-arch-name", re.compile(r"\b" + "Black" + r"well\b", re.IGNORECASE)),
    ("legacy-profiler", re.compile(r"\b" + "N" + r"sight\b", re.IGNORECASE)),
    ("legacy-cli", re.compile(r"\b" + "N" + r"CU\b|\b" + "n" + r"cu\b")),
    ("legacy-language", re.compile(r"\b" + "CU" + r"DA\b")),
]


def frontmatter(path: Path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise ValueError("missing YAML frontmatter")
    return yaml.safe_load(match.group(1))


def main() -> int:
    errors = []
    try:
        fm = frontmatter(ROOT / "SKILL.md")
        if not fm.get("name") or not fm.get("description"):
            errors.append("SKILL.md frontmatter must include name and description")
    except Exception as exc:
        errors.append(f"SKILL.md: {exc}")

    for name in REQUIRED_REFERENCES:
        if not (ROOT / "reference" / name).exists():
            errors.append(f"missing reference/{name}")
    for name in REQUIRED_HELPERS:
        if not (ROOT / "helpers" / name).exists():
            errors.append(f"missing helpers/{name}")

    for data_file in ["reference-sources.yaml", "output-files.yaml"]:
        path = ROOT / "data" / data_file
        if not path.exists():
            errors.append(f"missing data/{data_file}")
            continue
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"data/{data_file}: {exc}")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for helper in REQUIRED_HELPERS:
        if helper.endswith(".py") and helper not in readme and helper != "ascend_profile_utils.py":
            errors.append(f"README.md does not mention {helper}")

    for rel in FORMAL_CONTENT_PATHS:
        root = ROOT / rel
        if root.is_dir():
            paths = [p for p in root.rglob("*") if p.is_file()]
        elif root.is_file():
            paths = [root]
        else:
            continue
        for path in paths:
            if path.suffix in {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".pdf"}:
                continue
            if path.relative_to(ROOT) == Path("scripts/validate.py"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for label, pattern in FORMAL_LEAK_PATTERNS:
                match = pattern.search(text)
                if match:
                    line = text.count("\n", 0, match.start()) + 1
                    errors.append(f"{path.relative_to(ROOT)}:{line}: forbidden formal-content token {label}")

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print("validate: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
