# Summary Schema

`analysis/summary.json` is the canonical structured source for agents.
`REPORT.md` is an evidence-cited rendering of that source plus provenance and
TileLang context when present. Agents should read `summary.json` before using
the Markdown report for presentation.

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
