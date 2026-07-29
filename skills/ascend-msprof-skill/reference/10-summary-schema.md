# Summary Schema

## Contents

- [Top-Level Fields](#top-level-fields)
- [Segment Metadata](#segment-metadata)
- [Stdout Sections](#stdout-sections)
- [Evidence Readiness](#evidence-readiness)
- [Evidence Relations](#evidence-relations)
- [Raw Artifact Index](#raw-artifact-index)
- [Simulator Hotspot Model](#simulator-hotspot-model)
- [Analysis Dimensions](#analysis-dimensions)
- [Optimization Directions](#optimization-directions)
- [Next Collection Actions](#next-collection-actions)
- [Metric Scope Policy](#metric-scope-policy)

`analysis/summary.json` is the canonical structured source for agents.
`REPORT.md` is an evidence-cited rendering of that source plus provenance and
TileLang context when present. Agents should read `summary.json` before using
the Markdown report for presentation.

`analysis/raw_artifact_index.json` is a separate audit file, not a
`summary.json` schema extension. It has
`raw_artifact_index_schema_version: "1.0"` and an `artifacts[]` array for
parser-visible raw inputs plus preserved unparsed binary profiler artifacts.

## Top-Level Fields

- `analysis_schema_version`: stable analyzer contract version. Current value:
  `1.3`.
- `files`: grouped profiler artifacts and row/column summaries.
- `headlines`: one sourced headline per recognized artifact group when
  available.
- `stdout_sections`: raw parsed profiler stdout sections.
- `analysis_dimensions`: Ascend-native inspection dimensions and signals.
- `evidence_readiness`: additive run-level readiness model. It summarizes
  which evidence families are available, which are missing, what claims are
  allowed or blocked, and the minimal follow-up recommendations. It does not
  change `optimization_directions`, candidate-summary verdicts, or comparison
  verdicts.
- `evidence_relations`: additive mechanical links across corroborated evidence
  families. Relations can connect timing plus metric artifacts, or timing plus
  metric plus simulator context. They are not performance-cause, root-cause,
  or code-change claims and do not change readiness, ranking, candidate
  summaries, or comparison verdicts.
- `optimization_directions`: ranked inspection priorities generated only from
  sufficient profiler evidence.
- `next_collection_actions`: profiler collection follow-ups generated from a
  selected known metric scope and observed missing evidence.
- `metric_scope`: selected `--aic-metrics` value when it is discoverable from
  command logs.
- `target_identity`: expected-vs-observed operator identity check. Expected
  targets come from `analysis/profile_context.json` or
  `analysis/tilelang_context.json` fields such as `expected_kernel_name`,
  `expected_op_name`, `target_kernel_name`, or `target_op_name`. TileLang
  context can infer expected `main_kernel`. Observed names come from headline
  `op_basic_info`, `op_summary`, `op_statistic`, and `task_time` records.
  Status values are `match`, `mismatch`, `partial_mismatch`,
  `missing_observed`, `unverified`, or `missing`. Mismatch statuses suppress
  `optimization_directions`. Observed records include `match_rule` when an
  expected target exists: `exact`, `known_suffix`, or `unmatched`. Run-level
  `confidence` is `high` only when all matched records name the same exact
  target, `medium` for accepted suffix matches or multiple distinct exact
  observed targets, `low` for unverified observed targets, and `blocked` for
  mismatch, partial mismatch, or missing observed targets. This is the public
  target-alignment surface; do not add a separate target-alignment object.
- `warnings`: missing or invalid evidence observed by the analyzer.

## Segment Metadata

Schema `1.2` added additive source metadata so agents can distinguish evidence
from app, op, follow-up, simulator, or unknown collection segments without
changing artifact paths.

Schema `1.3` adds a structured simulator hotspot model artifact at
`analysis/simulator_hotspots.json`. The source/pipeline analysis dimension
records `model_artifact: "analysis/simulator_hotspots.json"` when the analyzer
generates the model. Simulator-derived signals remain raw source and pipeline
context with `segment: "simulator"` and `metric_scope: null`; they do not create
diagnosis rows or standalone simulator-only code-change directions.

Segment values are:

- `app`
- `op`
- `followup:<action-id>`
- `simulator`
- `unknown`

The analyzer records `segment` and `metric_scope` on `files.<group>[]`,
`headlines.<group>`, `analysis_dimensions[].signals[]`, and
`optimization_directions[].evidence[]`. `metric_scope` is populated only when
the selected `--aic-metrics` scope is discoverable from existing command logs,
or when a supported follow-up action defines it. App, simulator, and unknown
segments use `null` unless existing command evidence proves a scope.

## Stdout Sections

`stdout_sections` may contain `occupancy_summary`, `roofline_summary`, and
`performance_summary`. These sections preserve raw messages and sources. They
do not create headline metrics, diagnosis rows, optimization directions, or
code-change advice by themselves.

## Evidence Readiness

`evidence_readiness` is additive to the analyzer schema. It is a run-readiness
audit, not a performance score and not a verdict. It is the evidence-quality
surface; do not add an `evidence_quality` alias. Current fields are:

- `schema_version`: current value `1.0`.
- `level`: `insufficient`, `triage_only`, `directional`, or
  `actionable_experiment` for single-run analysis. Comparison readiness is
  reserved for comparison artifacts, not `ascend-msprof analyze`.
- `reasons[]`: concise reasons for the selected level.
- `available_evidence_families[]`: families such as `app_timing`,
  `operator_metadata`, `pipe_utilization`, `arithmetic_utilization`,
  `memory_cache`, `resource_conflict`, `simulator_source_pipeline`, or raw
  stdout summary families.
- `missing_evidence_families[]`: missing high-level families such as
  `app_timing`, `operator_metric`, or `source_or_workload_context`.
- `allowed_claims[]`: supported profiler claims, such as ranking the
  application hot path or first AI Core pipe inspection direction.
- `blocked_claims[]`: claims blocked by missing evidence, such as source-line
  attribution without simulator/source artifacts.
- `recommended_followups[]`: recommendations only. They reuse existing
  `next_collection_actions` when present or provide minimal collection
  suggestions; they do not execute collection.
- `segments[]`: compact per-segment readiness entries with `segment`,
  `metric_scope`, `status`, and `missing_required_artifacts`.
- `unparsed_binary_artifacts[]`: preserved binary profiler artifacts from the
  raw artifact index, including their segment, known role, and
  `diagnosis_role: "not_used"`.

Readiness levels are conservative:

- `insufficient`: missing parser-visible timing and metric evidence.
- `triage_only`: enough evidence to decide what to collect or inspect next,
  but not enough to justify kernel changes.
- `directional`: timing plus at least one parser-visible operator metric
  family can rank optimization directions.
- `actionable_experiment`: timing plus relevant operator metrics and either
  simulator/source context or recorded workload/shape context can support a
  focused next kernel experiment.

The app-level timing contract lives with the metric-scope policies and requires
at least one parser-visible timing artifact among `op_summary_*.csv`,
`task_time_*.csv`, `op_statistic_*.csv`, or `api_statistic_*.csv`.

## Evidence Relations

`evidence_relations[]` records corroborated cross-family artifact links. It is
empty when no supported relation exists and must stay empty for timing-only,
simulator-only, stdout-only, or binary-only runs. Relations are explanatory
only: they cite artifacts that can be inspected together and explicitly block
performance-cause or root-cause interpretation by themselves.

Supported `kind` values are:

- `timing_plus_pipe`
- `timing_plus_arithmetic`
- `timing_plus_memory_cache`
- `timing_plus_resource_conflict`
- `timing_metric_plus_simulator_source`
- `timing_metric_plus_simulator_instruction`
- `timing_metric_plus_simulator_trace`

Each relation contains:

- `id`: stable relation id for the run.
- `kind`: relation kind from the supported list above.
- `target`: the aligned profiled target when available, otherwise the timing
  signal name.
- `confidence`: copied from `target_identity.confidence` when it is `high`,
  `medium`, or `low`; blocked target identity prevents relation emission.
- `role`: concise relation role, such as mechanical timing-to-pipe artifact
  link.
- `evidence[]`: exact artifacts and summary fields, using the same evidence
  item shape as `optimization_directions[].evidence[]`.
- `allowed_interpretation`: what the relation permits an agent to inspect
  together.
- `blocked_interpretation`: what the relation must not be used to claim.
- `source_context_refs[]`: optional references into
  `analysis/simulator_hotspots.json` for simulator-backed relations.

Do not derive relation targets from `analysis/raw_artifact_index.json`.
Unparsed `.bin` artifacts are never diagnosis evidence and never create
relations.

## Raw Artifact Index

`raw_artifact_index.json` records recognized CANN CSV groups, application
timeline `msprof_*.json`, simulator `trace.json` and `core*_*.csv`, stdout
files that produced parsed `stdout_sections`, and preserved unparsed binary
profiler artifacts. Parser-visible artifact records keep:

- `artifact`: run-dir-relative path.
- `group`: analyzer group such as `op_summary`, `app_timeline`,
  `simulator_trace`, `simulator_csv`, or a `stdout_*_summary` group.
- `parser`: `csv`, `json`, or `stdout`.
- `segment`: `app`, `op`, `followup:<action-id>`, `simulator`, or `unknown`.
- `metric_scope`: selected op/follow-up scope, otherwise `null`.
- `status`: `parsed`, `empty`, or `invalid`.
- `columns`: CSV columns, otherwise empty.
- `row_count`: CSV row count, JSON event count, or stdout message count.
- `sample_rows`: first parsed CSV rows, JSON events, or stdout messages.
- `warnings`: artifact-local parser warnings.

Malformed JSON appears as an `invalid` raw-index record and raw-index warning
without adding new summary semantics. Unsupported JSON shapes are `empty`.

Unparsed binary artifact records use `group: "unparsed_profiler_binary"`,
`parser: "none"`, `status: "unparsed"`, `size_bytes`, `known_role`,
`diagnosis_role: "not_used"`, and `notes`. Known roles include MindStudio
visualization artifacts such as `visualize_data.bin`, simulator visualization
artifacts, internal `dump/DeviceProf*.bin`, internal `dump/duration.bin`, and
kernel object binaries. These records preserve auditability only; they must not
raise readiness, enable claims, create headlines, or feed diagnosis.

## Simulator Hotspot Model

`analysis/simulator_hotspots.json` records
`simulator_hotspot_model_schema_version: "1.1"` and structured context from
simulator `core*_code_exe.csv`, `core*_instr_exe.csv`, and `trace.json`
artifacts when present. The model contains:

- `inputs[]`: run-dir-relative artifact path, parser status, row/event count,
  CSV columns, and artifact-local warnings.
- `source_lines[]`: ranked source-line rows when `core*_code_exe.csv` rows have
  numeric timing, cycle, or count fields. Rows may include `source_context`
  with a run-local source snippet and conservative context tags when the
  referenced source file is inside the profiling run directory.
- `instructions[]`: ranked instruction rows preserving `instr`, `pipe`,
  `call_count`, `cycles`, `running_time(us)`, `artifact`, `field_ref`, and
  stable `evidence_id`.
- `pipeline_events[]`: aggregate duration context from simulator trace events.
- `flow_categories[]`: raw flow category counts from `traceEvents[].name ==
  "flow"` and `traceEvents[].cat`.
- `sync_events[]`: raw `SET_FLAG` / `WAIT_FLAG` trace-event counts plus
  per-core instruction CSV sums.
- `mte_throughput[]`: raw PMSampling MTE throughput samples for the
  source-backed channels GM_TO_L1, GM_TO_TOTAL, GM_TO_UB, L1_TO_GM,
  TOTAL_TO_GM, and UB_TO_GM.
- `warnings[]`: malformed, missing, unsupported, or empty-artifact notes.

`analysis/simulator_hotspots.txt` is an optional Markdown rendering of the
same model for human inspection.

## Analysis Dimensions

`analysis_dimensions[]` records the six Ascend-native dimensions from
`reference/05-analysis-dimensions.md`. Each signal keeps:

- `artifact`
- `field`
- `field_ref`
- `signal`
- `value`
- optional `evidence_id`
- optional launch metadata fields such as `tiling_field` and `tiling_value`

## Optimization Directions

`optimization_directions[]` is an ordered inspection-priority list. Every item
keeps:

- `id`
- `rank`
- `title`
- `action`
- `impact_basis`
- `confidence`
- `effort`
- `requires_artifacts`
- `missing_artifacts`
- `evidence[]`
- optional `experiment_hint`

Every evidence item has a stable `evidence_id` plus the existing `artifact`,
`field`, `field_ref`, `signal`, and `value` fields. A direction is not a code
rewrite instruction. It identifies what to inspect next from corroborated
profiler evidence.

When present, `experiment_hint` is additive and does not affect direction
eligibility, rank, confidence, or evidence gates. It keeps:

- `inspect_code_area`: the code area to inspect next.
- `next_experiment`: one controlled experiment to try.
- `expected_profiler_change`: profiler movement that would support or refute
  the experiment; this is a hypothesis, not a promised result.
- `recollect_artifacts`: profiler artifacts to recollect for the comparison.
- `caveats`: conservative limits for using the hint.
- optional `source_context`: at most three lightweight references from the
  already parsed simulator hotspot model.

Each `source_context[]` entry keeps only:

- `artifact`
- `field_ref`
- `role`
- optional `signal`
- optional `value`

`source_context` references `analysis/simulator_hotspots.json`; it is
inspection context only and does not replace on-device timing plus metric
corroboration.

## Next Collection Actions

`next_collection_actions[]` appears only when a known selected metric scope
and missing evidence justify follow-up collection. Every action keeps:

- `id`
- `reason`
- `recommended_aic_metrics`
- `required_artifacts`
- `evidence`
- `confidence`

These actions are collection recommendations only. They must not be converted
into code-change actions.

For the currently supported `collect_default_metric_followup` action, collect
the generated Default metric segment under
`reports/followups/collect_default_metric_followup/` and record the command in
`logs/command_msprof_followup_collect_default_metric_followup.txt`; the final
`analysis/summary.json` should then have an empty `next_collection_actions`
array when the required Default artifacts are present.

## Metric Scope Policy

The analyzer/report policy recognizes these `--aic-metrics` values:
`PipeUtilization`, `Default`, `KernelScale`, `ResourceConflictRatio`,
`PMSampling`, `Occupancy`, and `Roofline`.

For known scopes, policy records expected required artifacts, optional
artifacts, stdout sections, and report caveat behavior in `metric_scope.policy`
when a scope is detected. Missing required artifacts remain caveats. Optional
or out-of-scope metric families can be suppressed as report caveats only when
the selected known scope explicitly allows that behavior.

Unknown scopes keep current analyzer warnings and report caveats. They do not
generate next-collection actions.
