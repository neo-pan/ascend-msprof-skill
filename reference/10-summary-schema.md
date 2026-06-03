# Summary Schema

`analysis/summary.json` is the canonical structured source for agents.
`REPORT.md` is an evidence-cited rendering of that source plus provenance and
TileLang context when present. Agents should read `summary.json` before using
the Markdown report for presentation.

`analysis/raw_artifact_index.json` is a separate audit file, not a
`summary.json` schema extension. It has
`raw_artifact_index_schema_version: "1.0"` and an `artifacts[]` array for
parser-visible raw inputs only.

## Top-Level Fields

- `analysis_schema_version`: stable analyzer contract version. Current value:
  `1.2`.
- `files`: grouped profiler artifacts and row/column summaries.
- `headlines`: one sourced headline per recognized artifact group when
  available.
- `stdout_sections`: raw parsed profiler stdout sections.
- `analysis_dimensions`: Ascend-native inspection dimensions and signals.
- `optimization_directions`: ranked inspection priorities generated only from
  sufficient profiler evidence.
- `next_collection_actions`: profiler collection follow-ups generated from a
  selected known metric scope and observed missing evidence.
- `metric_scope`: selected `--aic-metrics` value when it is discoverable from
  orchestrator metadata or command logs.
- `warnings`: missing or invalid evidence observed by the analyzer.

## Segment Metadata

Schema `1.2` adds additive source metadata so agents can distinguish evidence
from app, op, follow-up, simulator, or unknown collection segments without
changing artifact paths.

Segment values are:

- `app`
- `op`
- `followup:<action-id>`
- `simulator`
- `unknown`

The analyzer records `segment` and `metric_scope` on `files.<group>[]`,
`headlines.<group>`, `analysis_dimensions[].signals[]`, and
`optimization_directions[].evidence[]`. `metric_scope` is populated only when
the selected `--aic-metrics` scope is discoverable from existing command or
orchestrator metadata, or when a supported follow-up action defines it. App,
simulator, and unknown segments use `null` unless existing metadata proves a
scope.

## Stdout Sections

`stdout_sections` may contain `occupancy_summary`, `roofline_summary`, and
`performance_summary`. These sections preserve raw messages and sources. They
do not create headline metrics, diagnosis rows, optimization directions, or
code-change advice by themselves.

## Raw Artifact Index

`raw_artifact_index.json` records recognized CANN CSV groups, application
timeline `msprof_*.json`, simulator `trace.json` and `core*_*.csv`, and stdout
files that produced parsed `stdout_sections`. Each artifact record keeps:

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

## Comparison Artifacts

`helpers/compare_runs.py` writes derived comparison artifacts from existing
analysis files. It requires `analysis/summary.json` for both runs and may also
read `analysis/provenance.json`, `analysis/tilelang_context.json`, and
`analysis/raw_artifact_index.json` when present.

The JSON output is `analysis/compare_<a>_vs_<b>.json` with
`comparison_schema_version: "1.0"`. It contains:

- `runs`: sanitized baseline and candidate labels plus input artifact presence.
- `compatibility`: non-fatal checks for CANN version, hardware summary,
  profile command, metric scope, and profile output segments.
- `benchmark`: TileLang workload, runtime, correctness, payload, and JIT
  context comparisons when context files are present.
- `headlines`: headline values compared by group with segment, metric scope,
  field, artifact, delta, and delta percentage when numeric.
- `evidence`: summary warnings, next collection actions, and raw artifact
  index summaries.
- `warnings`: missing or invalid optional comparison inputs.

The Markdown output `analysis/compare_<a>_vs_<b>.md` is a rendering of the JSON
artifact. Comparison artifacts are audit/report setup evidence only; they do
not add profiler metric semantics or code-change guidance.

## Analysis Dimensions

`analysis_dimensions[]` records the six Ascend-native dimensions from
`reference/05-analysis-dimensions.md`. Each signal keeps:

- `artifact`
- `field`
- `field_ref`
- `signal`
- `value`
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

`helpers/profile_tilelang_benchmark_run.py` automatically consumes the
currently supported `collect_default_metric_followup` action unless
`--disable-followup-collection` is passed. The generated Default metric segment
is recorded in `analysis/tilelang_benchmark_profile_run.json` under
`profiles.followups` and remains under
`reports/followups/collect_default_metric_followup/`; the final
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
