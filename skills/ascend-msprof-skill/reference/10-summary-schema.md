# Summary Schema

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
- `optimization_directions`: ranked inspection priorities generated only from
  sufficient profiler evidence.
- `next_collection_actions`: profiler collection follow-ups generated from a
  selected known metric scope and observed missing evidence.
- `evidence_readiness`: additive run-level readiness model. It summarizes
  which evidence families are available, which are missing, what claims are
  allowed or blocked, and the minimal follow-up recommendations. It does not
  change `optimization_directions`, candidate-summary verdicts, or comparison
  verdicts.
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
  `optimization_directions`.
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
audit, not a performance score and not a verdict. Current fields are:

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

## Comparison Artifacts

`ascend-msprof compare` writes derived comparison artifacts from existing
analysis files. It requires `analysis/summary.json` for both runs and may also
read `analysis/provenance.json`, `analysis/tilelang_context.json`, and
`analysis/raw_artifact_index.json` when present.

The JSON output is `analysis/compare_<a>_vs_<b>.json` with
`comparison_schema_version: "1.2"`. It contains:

- `runs`: sanitized baseline and candidate labels plus input artifact presence.
- `compatibility`: non-fatal checks for CANN version, hardware summary,
  profile command, metric scope, and profile output segments.
- `benchmark`: TileLang workload, runtime, correctness, payload, and JIT
  context comparisons when context files are present.
- `headlines`: headline values compared by group with segment, metric scope,
  field, artifact, delta, and delta percentage when numeric.
- `evidence`: summary warnings, next collection actions, and raw artifact
  index summaries.
- `design_feedback`: conservative TileLang design-question output with
  evidence citations, missing evidence, blockers, and next experiment text.
- `verdict`: conservative candidate-selection decision with `decision`,
  `policy`, `min_speedup_pct`, `can_compare`, compatibility details, runtime
  delta fields, and reasons. Payload and JIT differences are recorded as
  lineage/design differences inside the verdict compatibility block; they do
  not by themselves block comparison.
- `warnings`: missing or invalid optional comparison inputs.

The Markdown output `analysis/compare_<a>_vs_<b>.md` is a rendering of the JSON
artifact and includes a `## Design Feedback` section. Comparison artifacts are
audit/report setup evidence only; they do not add profiler metric semantics or
code-change guidance.

Baseline verdict decisions are:

- `promote`: workload and profiler compatibility pass, candidate correctness
  passed, profiler evidence is present for both runs, no required collection
  action is pending, and candidate mean runtime improves by at least
  `min_speedup_pct`.
- `reject`: candidate correctness failed, candidate compilation failed,
  candidate benchmark error is present, or comparable runtime regresses by at
  least `min_speedup_pct`.
- `inconclusive`: compatibility is missing or mismatched, runtime/evidence is
  missing, required collection remains pending, or runtime change is inside the
  threshold.

## Candidate Summary Artifacts

`ascend-msprof summarize-candidate` writes derived candidate feedback artifacts
from existing analysis files. It may read `analysis/summary.json`,
`analysis/provenance.json`, `analysis/tilelang_context.json`,
`analysis/raw_artifact_index.json`, and `analysis/simulator_hotspots.json`.
With `--baseline-run-dir`, it applies the same baseline verdict policy as
`ascend-msprof compare`. It does not collect new profiler data, run benchmark-side
tools, inspect benchmark source repos, or modify `reports/`.

`ascend-msprof profile-harness` is a collection helper for an already supplied
profile harness manifest or direct application path. It writes profiler command
logs, raw `reports/`, provenance, analysis artifacts, and
`analysis/profile_harness_run.json`. The workflow metadata includes an
additive `collection_plan` for the implicit `triage` collection currently run
by this helper: app timing plus operator `PipeUtilization`. This is audit
metadata only; it is not a `--preset` execution API. It also writes
`analysis/profile_context.json` for the supplied manifest/application and
optional verify JSON. Those fields are context/provenance for what was
profiled; profiler artifacts remain the source for diagnosis fields.

The JSON output is `analysis/candidate_summary.json` with
`candidate_summary_schema_version: "1.1"`. It contains:

- `run`: sanitized candidate label, run path, artifact presence, payload,
  workload, JIT, correctness, runtime, and profiler evidence readiness.
- `inspection_targets`: existing `optimization_directions` plus selected
  entries from `analysis/simulator_hotspots.json`, preserving evidence IDs,
  artifact paths, fields, field refs, and values. Targets are inspection
  records only, not automatic code rewrites.
- `design_feedback`: conservative TileLang design-question output with
  evidence citations, missing evidence, blockers, and next experiment text.
- `baseline`: optional sanitized baseline run context when
  `--baseline-run-dir` is provided.
- `verdict`: `keep`, `reject`, or `inconclusive` for a single run, or
  `promote`, `reject`, or `inconclusive` when a baseline is provided.
- `warnings`: missing or invalid optional input artifacts.

Single-run verdict decisions are:

- `keep`: correctness passed, runtime is recorded, profiler evidence is
  present, and no required collection action is pending.
- `reject`: candidate compilation failed, correctness failed, or benchmark
  error is present.
- `inconclusive`: required context, runtime, profiler evidence, or follow-up
  collection state is missing or pending.

Candidate summary Markdown includes a `## Design Feedback` section with the
same status and question IDs from JSON.

## Design Feedback Block

`design_feedback` is additive to candidate-summary and comparison artifacts.
It is not a new command, not a standalone `analysis/design_feedback.json`, and
not a parser or raw profiler schema extension.

The block shape is:

- `contract_version`: current value `1.0`.
- `status`: `ready`, `incomplete`, or `blocked`.
- `questions[]`: evidence-family design questions.

Each question contains:

- `id`: stable snake-case question identifier.
- `evidence_family`: tracked family such as `candidate_comparability`,
  `missing_evidence`, `memory_cache`, `pipe_arithmetic`, `opbasic_workload`,
  `pipeline_expression`, or `generated_context`.
- `question`: cautious design question.
- `related_design_variables[]`: task-agnostic design variables.
- `available_evidence[]`: cited artifact, field or field ref, source branch,
  and role.
- `missing_evidence[]`: cited absent artifact, field, context, or incompatible
  evidence needed before stronger feedback.
- `next_experiment`: one controlled collection or comparison step.
- `blocked_by[]`: compile, correctness, workload, provenance, raw index,
  on-device evidence, or compatibility blockers.

Design feedback text is limited to design questions, cited available evidence,
missing evidence, blockers, and next experiments. It does not change candidate
verdict behavior.

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

Every evidence item has a stable `evidence_id` plus the existing `artifact`,
`field`, `field_ref`, `signal`, and `value` fields. A direction is not a code
rewrite instruction. It identifies what to inspect next from corroborated
profiler evidence.

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
