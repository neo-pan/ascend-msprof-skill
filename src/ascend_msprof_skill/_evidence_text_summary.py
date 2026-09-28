"""Text summary rendering for Evidence Model artifacts."""
from __future__ import annotations

from pathlib import Path

from .summary_types import Summary
from .operator_evidence import OperatorEvidence, OperatorObservation
from .application_timing import TimingEvidence, observation_field_ref, partition_declared_subject


def md_table_cell(value: object) -> str:
    return "" if value is None else str(value).replace("|", "\\|").replace("\n", " ")


def _scope_text(scope) -> str:
    return "; ".join(f"{key}={value}" for key, value in scope)


def collected_metric_scope_lines(summary: Summary) -> list[str]:
    rows = []
    for group, evidence in summary.headlines.items():
        for artifact in evidence.artifacts:
            if artifact.metric_scope is None:
                continue
            rows.append(
                f"- {group}: {artifact.artifact}; segment={artifact.segment}; "
                f"metric_scope={artifact.metric_scope}"
            )
    if not rows:
        return []
    first = summary.metric_scope
    header = ["## Collected Artifact Metric Scopes", ""]
    if first is not None:
        header.append(
            f"- First recorded `msprof op --aic-metrics` command: {first.value} "
            f"(`{first.artifact}`; `{first.field_ref}`). This top-level field is "
            f"that first command value, not the deepest collected scope."
        )
    header.append("- Per-artifact scopes below are the collected segment values.")
    header.append("")
    return header + rows + [""]


def same_record_lines(observation: OperatorObservation, *, indent: str = "    ") -> list[str]:
    lines = []
    if observation.same_record:
        peers = "; ".join(
            f"{cell.metric}={cell.value:g} {cell.unit} ({cell.statistic})"
            for cell in observation.same_record
        )
        lines.append(f"{indent}same-record: {peers}")
    if observation.derived_pipe_quotients:
        quotients = "; ".join(
            f"{item.numerator}/{item.denominator}={item.value:g}"
            + (f" recorded_ratio={item.recorded_ratio:g}" if item.recorded_ratio is not None else "")
            for item in observation.derived_pipe_quotients
        )
        lines.append(
            f"{indent}pipe_time/core_time: {quotients} "
            "(not CalRatio; not a headline replacement)"
        )
    return lines


def field_population_lines(summary: Summary | None) -> list[str]:
    if summary is None:
        return []
    rows = []
    for group, evidence in summary.headlines.items():
        if not isinstance(evidence, OperatorEvidence):
            continue
        for artifact in evidence.artifacts:
            for index, item in enumerate(artifact.field_populations):
                total = "n/a" if item.sum is None else f"{item.sum:g}"
                source = (
                    f"{artifact.artifact}; segment={artifact.segment}; "
                    f"metric_scope={artifact.metric_scope}; field_populations[{index}]"
                )
                rows.append([
                    item.metric, _scope_text(item.scope), item.statistic, item.valid_count,
                    f"{item.minimum:g}", f"{item.median:g}", f"{item.maximum:g}",
                    total, item.aggregation, source,
                ])
    if not rows:
        return []
    return [
        "### Field Populations",
        "",
        "Within each recorded file and core-class scope (`sub_block_id` retained, "
        "`block_id` dropped). Sum is only for volume / estimated_volume. "
        "Ratios, bandwidth, and percentages keep count/min/median/max and do not "
        "sum or form Σnum/Σden. These populations do not replace max-cell headlines "
        "or enter comparison pairing.",
        "",
        "| Field | Scope | Statistic | Valid cells | Min | Median | Max | Sum | Aggregation | Source |",
        "|---|---|---|---:|---:|---:|---:|---:|---|---|",
        *("| " + " | ".join(md_table_cell(cell) for cell in row) + " |" for row in rows),
        "",
    ]


def _observation_line(group: str, artifact, observation) -> str:
    return (
        f"  - {observation.name}: {observation.value:g} {observation.unit} "
        f"({observation.statistic}); {artifact.artifact}; "
        f"{observation_field_ref(group, observation)}"
    )


def core_time_distribution_lines(summary: Summary | None) -> list[str]:
    if summary is None:
        return []
    evidence = summary.headlines.get("pipe_utilization")
    rows = []
    for artifact in evidence.artifacts if evidence is not None else ():
        for index, item in enumerate(artifact.core_time_distributions):
            def located(cell):
                if cell is None:
                    return "n/a"
                scope = "; ".join(f"{key}={value}" for key, value in cell.scope)
                return f"{cell.value:g}; {scope}; record={cell.source.record}; column={cell.source.column}"
            scope = "; ".join(f"{key}={value}" for key, value in item.scope)
            source = (f"{artifact.artifact}; segment={artifact.segment}; metric_scope={artifact.metric_scope}; "
                      f"core_time_distributions[{index}]")
            rows.append([item.metric, scope, item.valid_count, f"{item.median_us:g}",
                         located(item.maximum), located(item.second_largest), source])
    if not rows:
        return []
    return ["### Per-block Time Distributions", "",
            "Within each recorded file and sub-block scope; times are raw profiler microseconds, not natural latency. "
            "Counts include valid cells with block identifiers; inspect CSV issues for excluded rows. "
            "Second largest means the second cell (ties retained). Frequency caveats still apply.", "",
            "| Field | Scope | Valid cells | Median us | Maximum us / location | Second largest us / location | Source |",
            "|---|---|---:|---:|---|---|---|",
            *("| " + " | ".join(md_table_cell(cell) for cell in row) + " |" for row in rows), ""]


def evidence_context_lines(summary: Summary) -> list[str]:
    """Render the same claim boundaries in both human-facing entry points."""
    coverage = summary.profile_coverage
    identity = summary.target_identity
    readiness = summary.evidence_readiness
    lines = ["## Identity, Coverage and Limits", "",
             f"- target_identity: {identity.status}; expected: {', '.join(identity.expected.names) if identity.expected else 'undeclared'}",
             f"- profile_coverage.kernel_selector: {coverage.kernel_selector}",
             f"- {coverage.measurement_boundary}"]
    for name, segment in coverage.segments.items():
        ref = f"profile_coverage.segments.{name}"
        lines.append(f"- {ref}: identity={segment.target_identity.status}; "
                     f"scope={segment.target_scope.kind}; launches={segment.observed_total}/{segment.expected_total}; "
                     f"coverage={segment.completeness}")
        if segment.target_scope.kind == "focused_subset":
            lines.append(f"  - focused target: {segment.target_scope.model_dump(mode='json')}")
        for key in ("missing_counts", "over_counts", "extra_counts", "ambiguities"):
            value = getattr(segment, key)
            if value:
                lines.append(f"  - {key}: {value}")
        for family, item in segment.metric_coverage.items():
            lines.append(f"  - metric_coverage.{family}: {item.completeness}; "
                         f"launches={item.covered_launches}/{item.expected_launches}")
    lines.append(f"- evidence_readiness.level: {readiness.level}")
    lines.append("- Readiness describes the minimum profiling gate; an empty missing-family list does not mean every question has complete evidence.")
    for key in ("reasons", "allowed_claims", "blocked_claims",
                "available_evidence_families", "missing_evidence_families"):
        lines.append(f"- evidence_readiness.{key}: {'; '.join(getattr(readiness, key)) or 'none'}")
    frequency = summary.measurement_quality.frequency
    lines.append(f"- measurement_quality.frequency: {frequency.status}")
    for item in frequency.groups:
        lines.append(f"  - segment={item.segment}; target={item.target}; launches={item.launch_count}; "
                     f"current_mhz={item.current_frequencies_mhz}; rated_mhz={item.rated_frequencies_mhz}; "
                     f"below_rated={item.below_rated_launch_count}; mixed={item.mixed_frequency}")
    for warning in dict.fromkeys((*summary.warnings, *frequency.warnings)):
        lines.append(f"- warning: {warning}")
    return lines


def write_text_summary(out_path: Path, summary: Summary) -> None:
    """Render observations with their scope, and link the question-based entry."""
    coverage = summary.profile_coverage
    lines = ["# Ascend msprof Observations", "", f"Run: {out_path.parent.parent}",
             "Navigation: [reading_guide.md](reading_guide.md) — choose a question and its evidence route.",
             "Machine authority: summary.json; raw_artifact_index.json. References below are summary fields.",
             "Metric order is not an optimization priority. Select relevant evidence using the current question.",
             "", *evidence_context_lines(summary)]
    lines.extend(["", "## Recorded Observations",
                  "Operator observations use maximum_observed_cell per metric/scope; maxima can come from different records. "
                  "Application observations retain their recorded statistic and aggregation."])
    for group, evidence in summary.headlines.items():
        lines.append(f"### {group}: {len(evidence.artifacts)} file(s)")
        for index, artifact in enumerate(evidence.artifacts):
            lines.append(f"- artifact: {artifact.artifact}; segment={artifact.segment}; "
                         f"metric_scope={artifact.metric_scope}; parser={artifact.status}; rows={artifact.row_count}")
            if isinstance(evidence, (TimingEvidence, OperatorEvidence)):
                observations = artifact.observations
                partitions = [("", observations)]
                if isinstance(evidence, TimingEvidence):
                    declared, extras = partition_declared_subject(observations, coverage, name=lambda item: item.name)
                    partitions = [("declared target:", declared), ("extra launches:", extras)] if extras else [("", declared)]
                for label, items in partitions:
                    if label:
                        lines.append(f"  - {label}")
                    for observation in items:
                        lines.append(f"  - {observation.name}: {observation.value:g} {observation.unit} "
                                     f"({observation.statistic}); record={observation.source.record}; "
                                     f"column={observation.source.column}; field={observation.source.field}; "
                                     f"metric={observation.metric}; {_scope_text(observation.scope)}")
                if isinstance(evidence, OperatorEvidence):
                    for metadata in artifact.metadata:
                        lines.append(f"  - {metadata.source.field}: {metadata.value}; "
                                     f"record={metadata.source.record}; column={metadata.source.column}")
                    if artifact.core_time_distributions:
                        lines.append(f"  - per-block time / maximum location / second largest: "
                                     f"headlines.{group}.artifacts[{index}].core_time_distributions")
                    if artifact.field_populations:
                        lines.append(f"  - distribution: headlines.{group}.artifacts[{index}].field_populations")
            else:
                lines.append(f"  - details: headlines.{group}.artifacts[{index}]")
    for dimension in summary.analysis_dimensions:
        if dimension.id == "source_pipeline_context" and dimension.signals:
            lines.extend(["", "## Simulator Source/Pipeline Context",
                          "First recorded signals; full set: analysis_dimensions[source_pipeline_context].signals."])
            for signal in dimension.signals[:5]:
                lines.append(f"- {signal.signal} = {signal.value}; {signal.artifact}; {signal.field_ref}")
    stdout_sections = summary.stdout_sections
    occupancy = stdout_sections.occupancy_summary
    if occupancy:
        lines.append("")
        lines.append("## Occupancy Summary")
        lines.append("")
        lines.append("| Ordinal | Message | Source |")
        lines.append("|---:|---|---|")
        source = occupancy.source
        for message in occupancy.messages:
            lines.append(
                f"| {md_table_cell(message.ordinal)} | "
                f"{md_table_cell(message.message)} | "
                f"{md_table_cell(source)} |"
            )
    roofline = stdout_sections.roofline_summary
    if roofline:
        lines.append("")
        lines.append("## RoofLine Summary")
        lines.append("")
        lines.append("| Message | Source |")
        lines.append("|---|---|")
        source = roofline.source
        for message in roofline.messages:
            lines.append(
                f"| {md_table_cell(message.message)} | "
                f"{md_table_cell(source)} |"
            )
    performance = stdout_sections.performance_summary
    if performance:
        lines.append("")
        lines.append("## CANN Performance Summary")
        lines.append("")
        lines.append("| Ordinal | Message | Source |")
        lines.append("|---:|---|---|")
        source = performance.source
        for message in performance.messages:
            lines.append(
                f"| {md_table_cell(message.ordinal)} | "
                f"{md_table_cell(message.message)} | "
                f"{md_table_cell(source)} |"
            )
    lines.extend(["", "## Drill Down",
                  "- summary.json: target_identity, profile_coverage, measurement_quality, evidence_readiness; "
                  "headlines, analysis_dimensions, evidence_relations and next_collection_actions.",
                  "- raw_artifact_index.json: parser status, columns and row count for each artifact. "
                  "sample_rows locate fields; use populations or complete CSV for a distribution.",
                  "- Same-record fields: ascend-msprof joint-row --run-dir <run> --artifact <artifact> --record <record>.",
                  "  Record/column references above locate observations; same_record and derived_pipe_quotients "
                  "remain in summary.json. A joint row does not establish overlap or cause."])
    for action in summary.next_collection_actions:
        lines.append(f"- Conditional collection: {action.id} [{action.necessity}]; {action.reason}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
