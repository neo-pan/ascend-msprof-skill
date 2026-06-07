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
    "10-summary-schema.md",
]

REQUIRED_PACKAGE_MODULES = [
    "analyze_msprof_outputs.py",
    "ascend_profile_utils.py",
    "cli.py",
    "collect_tilelang_context.py",
    "compare_runs.py",
    "extract_simulator_hotspots.py",
    "generate_provenance.py",
    "generate_report.py",
    "plot_timeline.py",
    "profile_harness.py",
    "prepare_tilelang_profile_run.py",
    "summarize_candidate.py",
]

REQUIRED_SKILL_ASSETS = [
    "SKILL.md",
    "ascend-910b-programming.md",
    "assets/harness_template.cpp",
]

REQUIRED_CLI_COMMANDS = [
    "ascend-msprof analyze",
    "ascend-msprof compare",
    "ascend-msprof collect-tilelang",
    "ascend-msprof provenance",
    "ascend-msprof profile-harness",
    "ascend-msprof report",
    "ascend-msprof sim-hotspots",
    "ascend-msprof skill path",
    "ascend-msprof summarize-candidate",
    "ascend-msprof timeline",
    "ascend-msprof prepare-tilelang",
]

FORMAL_CONTENT_PATHS = [
    "README.md",
    "SKILL.md",
    "AGENTS.md",
    "ARCHITECTURE.md",
    "ascend-910b-programming.md",
    "reference",
    "src/ascend_msprof_skill",
    "scripts",
    "data",
    "tests",
    "pyproject.toml",
    "MANIFEST.in",
]

COMMAND_DOC_PATHS = [
    "README.md",
    "SKILL.md",
    "reference/01-workflow.md",
    "reference/03-collection.md",
]
COMMAND_BASELINE_DOCS = ["README.md", "SKILL.md", "reference/03-collection.md"]
APP_COMMAND_DOCS = ["SKILL.md", "reference/03-collection.md"]
GUIDANCE_DOC_PATHS = [
    "README.md",
    "SKILL.md",
    "AGENTS.md",
    "ARCHITECTURE.md",
    "ascend-910b-programming.md",
    *[f"reference/{name}" for name in REQUIRED_REFERENCES],
]

CANN83_VERSION = "8.3.0.2.220:8.3.RC2"
REQUIRED_APP_FLAGS = [
    "--application=",
    "--runtime-api=on",
    "--task-time=on",
    "--ai-core=on",
    "--aic-metrics=PipeUtilization",
    "--type=text",
    "--summary-format=csv",
]
REQUIRED_COMMAND_LOGS = ["command_msprof.txt", "command_msprof_op.txt"]
REQUIRED_COMMAND_SETUP = [
    'PROFILE_RUN_DIR=$(realpath "$PROFILE_RUN_DIR")',
    'APPLICATION=$(realpath "$APPLICATION")',
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

MSPROF_VERSION_COMMAND = "msprof " + "--version"
LOCAL_EVIDENCE_NAME = "triton" + "-bo-framework"

COMMAND_DOC_FORBIDDEN_PATTERNS = [
    ("retired-helper-command", re.compile(r"python3\s+helpers/[^`\s]+\.py")),
    ("unsupported-msprof-version-command", re.compile(re.escape(MSPROF_VERSION_COMMAND))),
    ("cann-9-validation-claim", re.compile(r"\bCANN\s+9(?:\.1(?:\.0(?:-beta\.1)?)?)?\b")),
    ("local-evidence-project", re.compile(re.escape(LOCAL_EVIDENCE_NAME))),
    (
        "positional-msprof-application",
        re.compile(
            r"msprof(?:\s+op(?:\s+simulator)?)?\s+--output=[^\n]*"
            r"(?:\n\s*)?\"\$PROFILE_RUN_DIR/harness/run\.sh\""
        ),
    ),
    (
        "placeholder-msprof-application",
        re.compile(r"msprof(?:\s+op(?:\s+simulator)?)?\s+--output=[^\n]*(?:<app>|\[args\])"),
    ),
]

GUIDANCE_FORBIDDEN_PATTERNS = [
    ("local-benchmark-repo-path", re.compile(re.escape(_REF_ROOT + "tilelang-ascend-benchmark") + r"\b")),
    ("baseline-payload-name", re.compile(r"\bkernel_payload_baseline\.py\b")),
    ("benchmark-repo-arg", re.compile(r"--benchmark-repo\b")),
    ("old-benchmark-helper", re.compile(r"\bprofile_tilelang_benchmark_run\.py\b")),
    ("benchmark-renderer-command", re.compile(r"\brender-profile-harness\b")),
    ("benchmark-profile-command", re.compile(r"\btilelang-ascend-benchmark\s+profile\b")),
]

SOURCE_BOUNDARY_FORBIDDEN_PATTERNS = [
    ("benchmark-renderer-command", re.compile(r"\brender-profile-harness\b")),
    ("benchmark-profile-command", re.compile(r"\btilelang-ascend-benchmark\s+profile\b")),
    ("benchmark-repo-arg", re.compile(r"--benchmark-repo\b")),
    ("local-benchmark-repo-path", re.compile(re.escape(_REF_ROOT + "tilelang-ascend-benchmark") + r"\b")),
    ("old-benchmark-helper", re.compile(r"\bprofile_tilelang_benchmark_run\.py\b")),
]

FIXTURE_STALE_NAME_PATTERNS = [
    ("baseline-payload-name", re.compile(r"\bkernel_payload_baseline\.py\b")),
]

REQUIRED_GENERIC_PROFILE_HARNESS_FIXTURE = [
    "harness/profile_harness.json",
    "harness/run.sh",
    "logs/command_msprof.txt",
    "logs/command_msprof_op.txt",
    "reports/app/PROF_001/mindstudio_profiler_output/op_summary_001.csv",
    "reports/op/OPPROF_001/PipeUtilization.csv",
    "analysis/summary.json",
    "analysis/profile_harness_run.json",
    "analysis/profile_context.json",
]


def read_rel(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def line_for(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def require_text(errors: list[str], rel: str, text: str, needle: str, message: str) -> None:
    if needle not in text:
        errors.append(f"{rel}: {message}")


def validate_command_docs(errors: list[str]) -> None:
    docs = {rel: read_rel(rel) for rel in sorted(set(COMMAND_DOC_PATHS + GUIDANCE_DOC_PATHS))}

    require_text(
        errors,
        "README.md",
        docs["README.md"],
        "Ascend 910B/910B2",
        "must state the Ascend 910B/910B2 validated baseline",
    )
    for rel in COMMAND_BASELINE_DOCS:
        require_text(
            errors,
            rel,
            docs[rel],
            CANN83_VERSION,
            f"must state CANN {CANN83_VERSION} as the validated command baseline",
        )

    require_text(
        errors,
        "reference/01-workflow.md",
        docs["reference/01-workflow.md"],
        "version.cfg",
        "must capture toolkit version evidence from version.cfg",
    )

    for rel in APP_COMMAND_DOCS:
        text = docs[rel]
        for flag in REQUIRED_APP_FLAGS:
            require_text(errors, rel, text, flag, f"must include app-level msprof flag {flag}")

    for rel in COMMAND_DOC_PATHS:
        require_text(
            errors,
            rel,
            docs[rel],
            "$APPLICATION",
            "must start collection examples from an existing application path",
        )
        for log_name in REQUIRED_COMMAND_LOGS:
            require_text(errors, rel, docs[rel], log_name, f"must record profiler command log {log_name}")
        for setup in REQUIRED_COMMAND_SETUP:
            require_text(errors, rel, docs[rel], setup, f"must include provenance-safe command setup {setup}")

    for rel in ["README.md", "SKILL.md", "reference/01-workflow.md"]:
        require_text(
            errors,
            rel,
            docs[rel],
            "profile harness manifest",
            "must describe profiling a supplied profile harness manifest",
        )
        require_text(
            errors,
            rel,
            docs[rel],
            "benchmark skill or calling agent",
            "must keep benchmark-specific harness rendering owned by the benchmark skill or calling agent",
        )

    formal_text = "\n".join(f"\n# {rel}\n{docs[rel]}" for rel in COMMAND_DOC_PATHS)
    for label, pattern in COMMAND_DOC_FORBIDDEN_PATTERNS:
        match = pattern.search(formal_text)
        if match:
            errors.append(f"formal command docs:{line_for(formal_text, match.start())}: forbidden {label}")

    guidance_text = "\n".join(f"\n# {rel}\n{docs[rel]}" for rel in GUIDANCE_DOC_PATHS)
    for label, pattern in GUIDANCE_FORBIDDEN_PATTERNS:
        match = pattern.search(guidance_text)
        if match:
            errors.append(f"formal guidance docs:{line_for(guidance_text, match.start())}: forbidden {label}")


def validate_packaged_skill_sync(errors: list[str]) -> None:
    pairs = [
        ("SKILL.md", "src/ascend_msprof_skill/skill/SKILL.md"),
        ("ascend-910b-programming.md", "src/ascend_msprof_skill/skill/ascend-910b-programming.md"),
    ]
    pairs.extend(
        (f"reference/{name}", f"src/ascend_msprof_skill/skill/reference/{name}")
        for name in REQUIRED_REFERENCES
    )
    pairs.extend(
        (f"data/{name}", f"src/ascend_msprof_skill/skill/data/{name}")
        for name in ["reference-sources.yaml", "output-files.yaml"]
    )
    for root_rel, packaged_rel in pairs:
        root_text = read_rel(root_rel)
        packaged_text = read_rel(packaged_rel)
        if root_text != packaged_text:
            errors.append(f"{packaged_rel} is out of sync with {root_rel}")


def audit_source_boundary_text(rel: str, text: str) -> list[str]:
    errors = []
    for label, pattern in SOURCE_BOUNDARY_FORBIDDEN_PATTERNS:
        match = pattern.search(text)
        if match:
            errors.append(f"{rel}:{line_for(text, match.start())}: forbidden source-boundary token {label}")
    return errors


def validate_source_boundary(errors: list[str]) -> None:
    source_root = ROOT / "src" / "ascend_msprof_skill"
    packaged_skill_root = source_root / "skill"
    for path in sorted(candidate for candidate in source_root.rglob("*") if candidate.is_file()):
        if packaged_skill_root in path.parents:
            continue
        if path.suffix in {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".pdf"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        errors.extend(audit_source_boundary_text(path.relative_to(ROOT).as_posix(), text))


def fixture_has_legacy_marker(path: Path, fixtures_root: Path) -> bool:
    for parent in [path.parent, *path.parents]:
        if parent == fixtures_root.parent:
            break
        if (parent / "LEGACY_COMPATIBILITY.md").exists():
            return True
        if parent == fixtures_root:
            break
    return False


def validate_fixture_stale_names(errors: list[str], fixtures_root: Path | None = None) -> None:
    fixtures_root = fixtures_root or ROOT / "tests" / "fixtures"
    if not fixtures_root.exists():
        return
    for path in sorted(candidate for candidate in fixtures_root.rglob("*") if candidate.is_file()):
        if path.name == "LEGACY_COMPATIBILITY.md":
            continue
        if path.suffix in {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".pdf"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in FIXTURE_STALE_NAME_PATTERNS:
            match = pattern.search(text)
            if match and not fixture_has_legacy_marker(path, fixtures_root):
                rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()
                errors.append(f"{rel}:{line_for(text, match.start())}: unmarked stale fixture token {label}")


def validate_generic_profile_harness_fixture(errors: list[str]) -> None:
    fixture_root = ROOT / "tests" / "fixtures" / "generic_profile_harness"
    for rel in REQUIRED_GENERIC_PROFILE_HARNESS_FIXTURE:
        if not (fixture_root / rel).exists():
            errors.append(f"missing generic profile harness fixture artifact tests/fixtures/generic_profile_harness/{rel}")


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
        if not (ROOT / "src" / "ascend_msprof_skill" / "skill" / "reference" / name).exists():
            errors.append(f"missing packaged skill reference/{name}")
    for name in REQUIRED_PACKAGE_MODULES:
        if not (ROOT / "src" / "ascend_msprof_skill" / name).exists():
            errors.append(f"missing package module {name}")
    for name in REQUIRED_SKILL_ASSETS:
        if not (ROOT / "src" / "ascend_msprof_skill" / "skill" / name).exists():
            errors.append(f"missing packaged skill asset {name}")

    for data_file in ["reference-sources.yaml", "output-files.yaml"]:
        path = ROOT / "data" / data_file
        if not path.exists():
            errors.append(f"missing data/{data_file}")
            continue
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"data/{data_file}: {exc}")

    validate_packaged_skill_sync(errors)
    validate_source_boundary(errors)
    validate_fixture_stale_names(errors)
    validate_generic_profile_harness_fixture(errors)

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for command in REQUIRED_CLI_COMMANDS:
        if command not in readme:
            errors.append(f"README.md does not mention {command}")

    validate_command_docs(errors)

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
                    line = line_for(text, match.start())
                    errors.append(f"{path.relative_to(ROOT)}:{line}: forbidden formal-content token {label}")

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print("validate: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
