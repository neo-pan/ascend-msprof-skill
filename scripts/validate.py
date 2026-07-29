#!/usr/bin/env python3
"""Validate the ascend-msprof-skill repository surface."""
from __future__ import annotations

import re
import sys
from posixpath import normpath
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SKILL_ROOT_REL = "skills/ascend-msprof-skill"
LEGACY_COMMITTED_SKILL_ROOT_REL = "src/ascend_msprof_skill/skill"


def skill_rel(path: str) -> str:
    return f"{SKILL_ROOT_REL}/{path}"


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
    "11-candidate-comparison-schema.md",
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
    "AGENTS.md",
    "ARCHITECTURE.md",
    "src/ascend_msprof_skill",
    "skills/ascend-msprof-skill",
    "scripts",
    "tests",
    "pyproject.toml",
]

COMMAND_DOC_PATHS = [
    "README.md",
    skill_rel("SKILL.md"),
    skill_rel("reference/01-workflow.md"),
    skill_rel("reference/03-collection.md"),
]
COMMAND_BASELINE_DOCS = ["README.md", skill_rel("SKILL.md"), skill_rel("reference/03-collection.md")]
CANONICAL_AGENT_COMMAND_DOC = skill_rel("reference/03-collection.md")
GUIDANCE_DOC_PATHS = [
    "README.md",
    "AGENTS.md",
    "ARCHITECTURE.md",
    skill_rel("SKILL.md"),
    skill_rel("ascend-910b-programming.md"),
    *[skill_rel(f"reference/{name}") for name in REQUIRED_REFERENCES],
]
WORKFLOW_DOC = skill_rel("reference/01-workflow.md")

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

REQUIRED_CANONICAL_COMMAND_TOKENS = [
    "MSPROF_APP_CMD=(",
    '--output="$PROFILE_RUN_DIR/reports/app"',
    "MSPROF_OP_CMD=(",
    '--output="$PROFILE_RUN_DIR/reports/op"',
    "MSPROF_FOLLOWUP_CMD=(",
    '--output="$PROFILE_RUN_DIR/reports/followups/collect_default_metric_followup"',
    "--aic-metrics=Default",
    "msprof op simulator",
    '--output="$PROFILE_RUN_DIR/reports/sim"',
]

REQUIRED_SKILL_ROUTES = [
    "reference/00-directory-layout.md",
    "reference/01-workflow.md",
    "reference/02-harness-guide.md",
    "reference/03-collection.md",
    "reference/04-output-files.md",
    "reference/05-analysis-dimensions.md",
    "reference/06-diagnosis-playbook.md",
    "reference/07-report-template.md",
    "reference/08-ascend-metric-files.md",
    "reference/09-common-issues.md",
    "reference/10-summary-schema.md",
    "reference/11-candidate-comparison-schema.md",
    "ascend-910b-programming.md",
]

REQUIRED_DRILLDOWN_TOKENS = [
    "analysis/summary.json",
    "analysis/candidate_summary.json",
    "analysis/compare_*.json",
    "target_identity",
    "metric_scope",
    "evidence_readiness",
    "warnings",
    "blocked claims",
    "next_collection_actions",
    "analysis_dimensions",
    "artifact",
    "field_ref",
    "analysis/raw_artifact_index.json",
    "sample_rows",
    "parser status",
    "row count",
    "evidence_relations[]",
    "every available family",
    "every material claim cites",
]

REQUIRED_CAPABILITY_TOKENS = [
    "supplied profile harness manifest or direct application",
    "`triage`",
    "`default-depth`",
    "`full`",
    "--follow-next-actions",
    "--continue-from-summary",
    "--simulator",
    "--simulator-timeout-s",
    "prepare-tilelang",
    "collect-tilelang",
    "summarize-candidate",
    "ascend-msprof compare",
    "REPORT.md",
    "Evidence Guardrails",
    "one run per directory",
    "exact artifact and field",
]

REQUIRED_DOCUMENT_SEMANTICS = {
    skill_rel("reference/03-collection.md"): [
        ("triage preset", "`--preset triage`"),
        ("default-depth preset", "`--preset default-depth`"),
        ("full preset", "`--preset full`"),
        ("omitted preset defaults to triage", "Omitting `--preset` uses `triage`"),
        (
            "full simulator condition",
            "`full` currently adds that same Default segment plus optional simulator collection "
            "only when `--simulator` is supplied.",
        ),
        ("summary continuation flag", "--continue-from-summary"),
        (
            "continuation metadata reuse",
            "This continue mode reuses `analysis/profile_harness_run.json`",
        ),
        ("continuation overwrite refusal", "refuses to overwrite existing follow-up output"),
        (
            "continuation action statuses",
            "records run/skipped/blocked actions in that workflow metadata",
        ),
        (
            "unsupported action handling",
            "Other recommended actions are recorded as skipped until the helper supports safe "
            "automation for them.",
        ),
    ],
    skill_rel("SKILL.md"): [
        (
            "missing-derived entry condition",
            "Apply the missing-derived exception only when the branch's primary derived JSON or "
            "`analysis/raw_artifact_index.json` is absent.",
        ),
        (
            "missing-derived disclosure",
            "Before opening raw evidence, state which derived or index artifact is missing.",
        ),
        (
            "missing-derived purpose bound",
            "Limit raw reads to diagnosing that blocker or a bounded, read-only interpretation",
        ),
        ("missing-derived exact citation", "cite each exact raw artifact and field used"),
        (
            "missing-derived claim gate",
            "Withhold optimization or code-change claims whose target, readiness, metric, "
            "correctness, or comparison gates depend on the missing artifact.",
        ),
    ],
}

MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)

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


def normalize_semantic_text(text: str) -> str:
    return " ".join(text.split())


def validate_command_docs(errors: list[str], docs: dict[str, str] | None = None) -> None:
    if docs is None:
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
        WORKFLOW_DOC,
        docs[WORKFLOW_DOC],
        "version.cfg",
        "must capture toolkit version evidence from version.cfg",
    )

    canonical_text = docs[CANONICAL_AGENT_COMMAND_DOC]
    for flag in REQUIRED_APP_FLAGS:
        require_text(
            errors,
            CANONICAL_AGENT_COMMAND_DOC,
            canonical_text,
            flag,
            f"must include app-level msprof flag {flag}",
        )
    require_text(
        errors,
        CANONICAL_AGENT_COMMAND_DOC,
        canonical_text,
        "$APPLICATION",
        "must start collection examples from an existing application path",
    )
    for log_name in REQUIRED_COMMAND_LOGS:
        require_text(
            errors,
            CANONICAL_AGENT_COMMAND_DOC,
            canonical_text,
            log_name,
            f"must record profiler command log {log_name}",
        )
    for setup in REQUIRED_COMMAND_SETUP:
        require_text(
            errors,
            CANONICAL_AGENT_COMMAND_DOC,
            canonical_text,
            setup,
            f"must include provenance-safe command setup {setup}",
        )
    for token in REQUIRED_CANONICAL_COMMAND_TOKENS:
        require_text(
            errors,
            CANONICAL_AGENT_COMMAND_DOC,
            canonical_text,
            token,
            f"must preserve canonical collection recipe token {token}",
        )

    # README remains user-facing command documentation. Agent-facing workflow
    # and entrypoint docs only need an explicit route to the canonical recipe.
    rel = "README.md"
    require_text(errors, rel, docs[rel], "$APPLICATION", "must document an existing application path")
    for log_name in REQUIRED_COMMAND_LOGS:
        require_text(errors, rel, docs[rel], log_name, f"must record profiler command log {log_name}")
    for setup in REQUIRED_COMMAND_SETUP:
        require_text(errors, rel, docs[rel], setup, f"must include provenance-safe command setup {setup}")

    for rel in ["README.md", skill_rel("SKILL.md"), WORKFLOW_DOC]:
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
        require_text(
            errors,
            rel,
            docs[rel],
            "`--simulator` is optional",
            "must describe profile-harness simulator collection as optional",
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


def validate_skill_contract(errors: list[str], docs: dict[str, str]) -> None:
    rel = skill_rel("SKILL.md")
    text = docs[rel]
    for route in REQUIRED_SKILL_ROUTES:
        require_text(errors, rel, text, f"]({route})", f"must directly route agents to {route}")
    for token in REQUIRED_DRILLDOWN_TOKENS:
        require_text(errors, rel, text, token, f"must preserve evidence drill-down anchor {token}")
    for token in REQUIRED_CAPABILITY_TOKENS:
        require_text(errors, rel, text, token, f"must preserve capability anchor {token}")
    for document_rel, requirements in REQUIRED_DOCUMENT_SEMANTICS.items():
        if document_rel not in docs:
            errors.append(f"{document_rel}: missing document-specific semantic contract source")
            continue
        normalized = normalize_semantic_text(docs[document_rel])
        for label, phrase in requirements:
            require_text(
                errors,
                document_rel,
                normalized,
                phrase,
                f"must preserve semantic contract: {label}",
            )


def validate_markdown_links(errors: list[str], docs: dict[str, str]) -> None:
    """Reject broken local Markdown links using an in-memory documentation map."""
    anchors_by_rel: dict[str, set[str]] = {}
    for rel, content in docs.items():
        anchors: set[str] = set()
        slug_counts: dict[str, int] = {}
        for heading in MARKDOWN_HEADING_RE.findall(content):
            slug = re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")
            suffix = slug_counts.get(slug, 0)
            slug_counts[slug] = suffix + 1
            anchors.add(slug if suffix == 0 else f"{slug}-{suffix}")
        anchors_by_rel[rel] = anchors

    for rel, content in docs.items():
        source_dir = str(Path(rel).parent).replace("\\", "/")
        for match in MARKDOWN_LINK_RE.finditer(content):
            raw_target = match.group(1).strip()
            if raw_target.startswith(("http://", "https://", "mailto:")):
                continue
            path_and_query, separator, fragment = raw_target.partition("#")
            target = path_and_query.split("?", 1)[0]
            resolved = rel if not target else normpath(f"{source_dir}/{target}")
            if resolved not in docs:
                errors.append(
                    f"{rel}:{line_for(content, match.start())}: broken Markdown link {raw_target}"
                )
            elif separator and fragment not in anchors_by_rel[resolved]:
                errors.append(
                    f"{rel}:{line_for(content, match.start())}: broken Markdown anchor {raw_target}"
                )


def audit_source_boundary_text(rel: str, text: str) -> list[str]:
    errors = []
    for label, pattern in SOURCE_BOUNDARY_FORBIDDEN_PATTERNS:
        match = pattern.search(text)
        if match:
            errors.append(f"{rel}:{line_for(text, match.start())}: forbidden source-boundary token {label}")
    return errors


def validate_source_boundary(errors: list[str]) -> None:
    source_root = ROOT / "src" / "ascend_msprof_skill"
    for path in sorted(candidate for candidate in source_root.rglob("*") if candidate.is_file()):
        if path.suffix in {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".pdf"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        errors.extend(audit_source_boundary_text(path.relative_to(ROOT).as_posix(), text))


def validate_skill_layout(errors: list[str]) -> None:
    legacy_skill_root = ROOT / LEGACY_COMMITTED_SKILL_ROOT_REL
    if legacy_skill_root.exists():
        errors.append(
            f"{LEGACY_COMMITTED_SKILL_ROOT_REL} must not be committed; "
            f"use canonical skill source {SKILL_ROOT_REL}"
        )


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
    skill_root = ROOT / SKILL_ROOT_REL
    skill_docs = {
        path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(skill_root.rglob("*.md"))
    }
    validate_skill_layout(errors)
    try:
        fm = frontmatter(skill_root / "SKILL.md")
        if not fm.get("name") or not fm.get("description"):
            errors.append(f"{skill_rel('SKILL.md')} frontmatter must include name and description")
    except Exception as exc:
        errors.append(f"{skill_rel('SKILL.md')}: {exc}")

    for name in REQUIRED_REFERENCES:
        if not (skill_root / "reference" / name).exists():
            errors.append(f"missing {skill_rel(f'reference/{name}')}")
    for name in REQUIRED_PACKAGE_MODULES:
        if not (ROOT / "src" / "ascend_msprof_skill" / name).exists():
            errors.append(f"missing package module {name}")
    for name in REQUIRED_SKILL_ASSETS:
        if not (skill_root / name).exists():
            errors.append(f"missing packaged skill asset {name}")

    for data_file in ["reference-sources.yaml", "output-files.yaml"]:
        path = skill_root / "data" / data_file
        if not path.exists():
            errors.append(f"missing {skill_rel(f'data/{data_file}')}")
            continue
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{skill_rel(f'data/{data_file}')}: {exc}")

    validate_source_boundary(errors)
    validate_fixture_stale_names(errors)
    validate_generic_profile_harness_fixture(errors)
    validate_skill_contract(errors, skill_docs)
    validate_markdown_links(errors, skill_docs)

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
