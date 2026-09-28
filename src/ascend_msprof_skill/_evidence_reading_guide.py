"""Question-based navigation over existing evidence, without new diagnosis facts."""
from __future__ import annotations

from pathlib import Path
import shlex

from ._evidence_signals import DIMENSION_GROUPS
from ._evidence_text_summary import evidence_context_lines
from .operator_evidence import OperatorEvidence
from .summary_types import Summary, RawArtifactIndex


_QUESTIONS = {
    "hot_path_dispatch": "Where is profiled application time spent?",
    "pipe_arithmetic_mix": "What work is recorded on Cube / Vector / Scalar / MTE?",
    "memory_cache_movement": "What memory movement and cache activity were recorded?",
    "resource_conflict": "Which resource conflict counters were recorded?",
    "tiling_core_balance": "Which launch configuration or per-block tail needs inspection?",
    "source_pipeline_context": "Which simulated source / instruction / pipeline events were recorded?",
}


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _code(value: object) -> str:
    # Raw names can contain Markdown delimiters; retain them without breaking layout.
    text = str(value).replace("\n", " ")
    fence = "`"
    while fence in text:
        fence += "`"
    return f"{fence} {text} {fence}" if "`" in text else f"{fence}{text}{fence}"


def write_reading_guide(path: Path, summary: Summary, index: RawArtifactIndex) -> None:
    """Write an entry point whose routes preserve scope and parser/admission limits."""
    lines = [
        "# Evidence Reading Guide", "",
        "Read the run limits below, choose your question, then follow its evidence route.",
        "This guide locates evidence; it does not rank bottlenecks or select kernel changes.",
        "All paths are relative to the run unless stated otherwise. JSON pointers below are relative to `analysis/`.",
        "`summary.json` is the derived authority; `raw_artifact_index.json` inventories parsing; raw reports retain every row.",
        "For an overview of recorded values, open [key_metrics.txt](key_metrics.txt).", "",
        *evidence_context_lines(summary), "",
        "Limits above come from `summary.json#/target_identity`, `/profile_coverage`,",
        "`/evidence_readiness`, `/measurement_quality` and `/warnings`.",
        "Identity match checks recorded target names; it is not proof of source/benchmark association.",
        "Read the relevant segment's target scope and metric coverage before attributing a local observation to the whole program.",
        "Unknown metric scope stays unknown. The top-level `metric_scope` is only the first recorded command;",
        "use each artifact's scope below. A missing family limits claims that require it; other evidence remains usable.", "",
        "## 1. Choose The Question", "",
        "### Did the candidate become faster?", "",
        "Use `candidate_summary.json` or `compare_*.json` → `performance_assessment` for natural timing eligibility and observations;",
        "use their independent `mechanism_assessment` for profiler evidence. Generate these with `summarize-candidate` / `compare` if needed.",
        "Use the exact assessment path returned to the caller. If several files exist, check `runs`, `source_artifacts` and their SHA-256 bindings",
        "against the intended inputs; a filename, modification time or higher schema version does not establish freshness. Regenerate an unbound assessment.",
        "Caller/Executor timing keeps its declared measurement boundary. Operator or simulator duration is not natural-launch latency.",
        "If natural timing is absent, report that gap and continue any supported local profiler analysis.", "",
    ]
    lines.extend(["### What source and caller context belong to this run?", "",
                  "Source/JIT context is independent of simulator availability. Verify its implementation binding before connecting code to observations.",
                  "`summary.json#/analysis_context` records consumed target/workload context and its issues."])
    for name, fields in (
        ("tilelang_context.json", "`sources`, `jit_debug`, `benchmark.workload`, `benchmark.metadata`; legacy `benchmark.candidate` timing is caller context"),
        ("profile_context.json", "application/source identity, `profile_harness`, `verify_context`; caller verification is separate from profiler evidence"),
        ("benchmark_context.json", "registered benchmark inputs and snapshots; use the assessment's eligibility checks before a performance claim"),
    ):
        if (path.parent / name).is_file():
            lines.append(f"- Present: [{name}]({name}) → {fields}. File presence alone is not validity or association.")
        else:
            lines.append(f"- `{name}`: absent; use the caller's source/measurement receipt if provided and keep its authority explicit.")
    lines.append("")
    groups_by_dimension = {identifier: groups for identifier, _, groups in DIMENSION_GROUPS}
    for number, dimension in enumerate(summary.analysis_dimensions):
        lines.extend([
            f"### {_QUESTIONS.get(dimension.id, dimension.title)}", "",
            f"- Recorded signals: {len(dimension.signals)}; dimension status: `{dimension.status}`.",
            f"- Details: `summary.json#/analysis_dimensions/{number}` (`{dimension.id}`).",
        ])
        for group in groups_by_dimension.get(dimension.id, ()):
            artifacts = summary.headlines[group].artifacts
            observed = sum(bool(item.observations) for item in artifacts)
            states = ", ".join(f"{state}={sum(item.status == state for item in artifacts)}"
                               for state in ("parsed", "empty", "invalid") if any(item.status == state for item in artifacts))
            lines.append(f"- [{group}](#family-{group.replace('_', '-')}) — "
                         + (f"{len(artifacts)} artifact(s), {states}; {observed} with numeric observations."
                            if artifacts else "no admitted artifacts."))
        if dimension.id == "hot_path_dispatch":
            lines.append("- Inspect timing observations, statistics, units and launch coverage in the cited summary artifacts. "
                         "Host API and device timings have different boundaries; `joint-row` handles operator CSVs only.")
        elif dimension.id == "tiling_core_balance":
            lines.append("- Open [PipeUtilization](#family-pipe-utilization) `core_time_distributions` for median, maximum, second largest and their block/record locations; "
                         "`field_populations` or field-only min/max cannot locate a tail. Launch Block Dim alone does not establish imbalance.")
        elif dimension.id == "source_pipeline_context":
            lines.append("- Open `simulator_hotspots.json` for parser status, source/instruction ranks and pipeline context. "
                         "Its raw files are inventoried below, outside `headlines`. Simulation time is separate from on-device time.")
        else:
            lines.append("- Open the relevant family's observations and same-record peers; use `field_populations` for all-core distributions.")
        lines.append("")
    lines.extend(["A dimension's `available` status means it contains recorded signals, not that a causal explanation is established.",
                  "Partial/invalid files can retain useful cells; inspect their issues. Raw column presence alone does not establish a valid metric.",
                  "", "## 2. Open The Evidence", "",
                  "Each entry binds a summary route to its raw inventory. Read observations with their unit, statistic, target/core scope and source record.",
                  "CSV record numbers include the header as record 1. Operator maxima for different fields may come from different records.", ""])
    indexed = {(item.group, item.artifact): number for number, item in enumerate(index.artifacts)}
    listed = set()
    for group, evidence in summary.headlines.items():
        lines.extend([f"### Family {group.replace('_', '-')}", ""])
        if not evidence.artifacts:
            lines.extend(["No admitted artifacts for this family. See the raw inventory below for excluded collections, if any.", ""])
        for number, artifact in enumerate(evidence.artifacts):
            listed.add((group, artifact.artifact))
            pointer = f"summary.json#/headlines/{_pointer_token(group)}/artifacts/{number}"
            metric_scope = artifact.metric_scope or ("unknown" if isinstance(evidence, OperatorEvidence) else "not applicable (application timing)")
            lines.extend([
                f"- Artifact: {_code(artifact.artifact)}",
                f"  - Segment: {_code(artifact.segment)}; metric scope: {_code(metric_scope)}; parser: `{artifact.status}`; rows: {artifact.row_count}.",
                f"  - Summary: `{pointer}` → `observations`, `issues`.",
            ])
            inventory_number = indexed.get((group, artifact.artifact))
            if inventory_number is not None:
                lines.append(f"  - Inventory: `raw_artifact_index.json#/artifacts/{inventory_number}` → `columns`, `warnings`, `sample_rows` (samples are not a distribution).")
            else:
                lines.append("  - Inventory entry missing; resolve summary/index disagreement before relying on this artifact.")
            if isinstance(evidence, OperatorEvidence):
                if artifact.field_populations:
                    lines.append(f"  - Population: `{pointer}/field_populations` (separate core-class scopes).")
                if artifact.core_time_distributions:
                    lines.append(f"  - Tail and locations: `{pointer}/core_time_distributions`.")
                command = shlex.join(["ascend-msprof", "joint-row", "--run-dir", str(path.parent.parent),
                                      "--artifact", artifact.artifact, "--list-fields"])
                lines.extend(["  - Discover exact fields:", "", "    ```bash", f"    {command}", "    ```"])
            lines.append("")
    lines.extend(["### Other Indexed Artifacts", "",
                  "Inventory presence is not admission to diagnosis. Failed collection receipts exclude their segments even if a file parses.",
                  "Unparsed binaries are audit inventory only; stdout requires corroboration. Timeline and simulator files have separate models.", ""])
    for number, item in enumerate(index.artifacts):
        if (item.group, item.artifact) in listed:
            continue
        admission = "excluded by collection receipt" if not summary.collection_receipts.allows(item.segment) else "consult model/status; inventory only"
        lines.append(f"- {_code(item.artifact)}: group={_code(item.group)}; segment={_code(item.segment)}; "
                     f"metric_scope={_code(item.metric_scope or 'not recorded')}; parser=`{item.status}`; "
                     f"rows={item.row_count}; {admission}; `raw_artifact_index.json#/artifacts/{number}`.")
    for warning in index.warnings:
        lines.append(f"- Inventory warning: {warning}")
    lines.extend(["", "## 3. Verify A Material Claim", "",
                  "For an operator CSV, replace `--list-fields` in its command with one of:", "",
                  "- `--field '<exact field>'` (repeatable): full matching min/median/max and valid/missing/invalid counts per scope.",
                  "- `--record <csv-record>`: same-record peers for a located observation, including its source context.",
                  "- `--field '<exact field>' --records --limit 5`: raw rows; follow `next_command` until the needed population is covered.",
                  "- Add `--scope sub_block_id=<id>` or `--scope block_id=<id>` to narrow that file's population.", "",
                  "For a tail claim, follow `core_time_distributions` before selecting its record. Across metric files, align block/sub-block identity and collection scope;",
                  "`joint-row` neither merges artifacts nor establishes simultaneous sampling. Raw time quotients do not replace recorded ratios.",
                  "For application timing, read the summary observation and cited raw row; for simulator evidence, follow `simulator_hotspots.json` source references.",
                  "Use `summary.json#/evidence_relations` for mechanical links, not cause. Stop with a sourced answer or a specific gap for this question.",
                  "", "## Conditional Collection", "",
                  "Select a follow-up only if the current claim needs its evidence. These actions are not a task queue.", ""])
    for number, action in enumerate(summary.next_collection_actions):
        lines.append(f"- `{action.id}` [{action.necessity}]: {action.reason}; "
                     f"unlocks: {', '.join(action.unlocks_claims) or 'none'}; `summary.json#/next_collection_actions/{number}`.")
    if not summary.next_collection_actions:
        lines.append("None recorded.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
