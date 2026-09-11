# Candidate And Comparison Schemas

## Contents

- [Comparison Artifacts](#comparison-artifacts)
- [Candidate Summary Artifacts](#candidate-summary-artifacts)
- [Design Feedback Block](#design-feedback-block)

## Comparison Artifacts

`ascend-msprof compare` writes derived comparison artifacts from existing
analysis files. It requires `analysis/summary.json` for both runs and may also
read `analysis/provenance.json`, `analysis/tilelang_context.json`, and
`analysis/raw_artifact_index.json` when present.

The JSON output is `analysis/compare_<a>_vs_<b>.json` with
`comparison_schema_version: "1.5"`. It contains:

- `runs`: sanitized baseline and candidate labels plus input artifact presence.
- `compatibility`: non-fatal checks for CANN version, hardware summary,
  profile command, metric scope, and profile output segments. All checks must
  match before headline deltas are computed; a failed check does not prevent
  writing the comparison artifacts.
- `benchmark`: TileLang workload, runtime, correctness, payload, and JIT
  context comparisons when context files are present.
- `workload_checks`: required `workload.id`, `shape`, `dtype`, and `case_count`
  checks, with both values and all caller context observations under
  `sources.a`/`sources.b` (`value`, `source.artifact`, `source.field_ref`).
  These are the same checks used by candidate verdict compatibility.
- `headlines`: headline values compared by group with segment, metric scope,
  field, artifact, target identity, block scope, and `comparison_reasons[]`.
  Deltas are computed only for comparable finite numeric values.
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

CANN version checks require matching values from the same component, identified
by `source.artifact` and `source.field`. Toolkit `version` in install-info and
`toolkit_running_version` in cfg describe the same component. Equal runtime
and toolkit strings alone produce `component_mismatch`; an unknown component
source produces `missing`. Both headline deltas and candidate verdicts use this gate.
Comparison selects a component recorded by both runs, preferring toolkit, then
runtime, compiler, and OPP. Additional evidence must agree with its run's version
value; selected source references are retained, as is any recorded conflict status.

Headline comparison requires identical non-empty `field`, `field_kind`, `name`,
`segment`, and `metric_scope`, plus the same single confirmed expected target.
`target_identity` comes from the headline's segment when segment identities
exist; otherwise it uses the run identity. `block_scope` carries existing
`blockid`/`subblockid` values from the selected raw row, with normalized keys.
Missing raw rows have a null block scope; rows without block columns have an
empty scope. Both scopes must be present and equal. No missing metadata or
field/unit equivalence is inferred.

Since 1.5, all four workload fields must be present and match before headline
deltas are computed. Conflicting caller contexts within either run produce
`workload.<field> conflict`; different runs produce `workload.<field> mismatch`;
one-sided or two-sided absence produces `workload.<field> missing`. Matching
observations from different sources are accepted and retain every citation.
Candidate summary `run.workload_evidence` also retains these observations for
single-run inspection; conflicted fields have no selected workload value.
Old summaries are not backfilled: raw values remain readable without caller
context, but deltas are unavailable. Payload/JIT identity, correctness, and
natural benchmark duration are not additional headline requirements. Target,
block and profiler checks remain independent. The verdict policy remains
`baseline_v1`, including its existing correctness and readiness requirements.

Headline `schema_issues` carry unsupported-layout reasons and artifact/field
citations. An independent `Unit`/`Units` column is an unsupported layout, even
if both runs use it. Unknown op metric fields selected by a broad alias remain
visible but cannot produce deltas. Only the fixture-covered exact field
vocabulary is accepted; units are not stripped or converted and bare ratios
are not interpreted by value range. Independent-unit-column examples are
synthetic, not observed CANN regressions.

If both headlines exist but comparison requirements fail, their original
values remain visible with `status: "not_comparable"`, `numeric: false`, null
`delta`/`delta_pct`, and reasons. A missing headline keeps `status: "missing"`.
Comparable rows use `same` or `changed` and an empty reasons list; a zero
baseline permits an absolute delta but no percentage. Current application
timing headlines also lack an explicit `field` and usually a metric scope, so
they retain their values without deltas even after reanalysis. Markdown shows
both field names and the reasons. These gates do not change benchmark field
comparisons or the candidate verdict policy.

The Markdown output `analysis/compare_<a>_vs_<b>.md` is a rendering of the JSON
artifact and includes a `## Design Feedback` section. Comparison artifacts are
audit/report setup evidence only; they do not add profiler metric semantics or
code-change guidance.

Baseline verdict decisions are:

- `promote`: workload and profiler compatibility pass, candidate correctness
  passed, profiler evidence is present for both runs, no required collection
  action is pending, and candidate runtime using the compatible selected
  statistic improves by at least
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
`analysis/profile_harness_run.json`. The workflow metadata includes the
selected `collection_plan` preset. Omitting `--preset` uses `triage`: app
timing plus operator `PipeUtilization`; `default-depth` adds a separate Default
metric follow-up segment; `full` includes the Default segment and only records
simulator when `--simulator` is supplied. It also writes
`analysis/profile_context.json` for the supplied manifest/application and
optional verify JSON. Those fields are context/provenance for what was
profiled; profiler artifacts remain the source for diagnosis fields.
With `--summarize-candidate`, the harness writes candidate-summary artifacts
after analysis from existing derived/context files without recollection.

The JSON output is `analysis/candidate_summary.json` with
`candidate_summary_schema_version: "1.2"`. It contains:

- `source_artifacts.summary`: the `analysis/summary.json` artifact path and
  SHA-256 consumed to build this candidate summary.
- `run`: sanitized candidate label, run path, artifact presence, payload,
  workload, JIT, correctness, runtime, and profiler evidence readiness.
  Runtime includes selected `value_ms`, `statistic`, samples, authority, and
  latency source; `mean_ms` is reserved for a true or legacy mean.
  `context_sources` records the artifact, field ref, and evidence role selected
  for each projected field.
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

- `contract_version`: current value `1.1`.
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
  role, segment, metric scope, and target scope when known. Scope-local
  evidence remains usable only for that recorded target scope.
- `missing_evidence[]`: cited absent artifact, field, context, incompatible
  evidence, or missing target-scope coverage needed before stronger feedback.
  When a parsed scope-local artifact exists, describe a complete-program gap
  as missing complete-program coverage rather than claiming the artifact is
  absent.
- `next_experiment`: one controlled collection or comparison step.
- `blocked_by[]`: compile, correctness, workload, provenance, raw index,
  on-device evidence, or compatibility blockers.

Design feedback text is limited to design questions, cited available evidence,
missing evidence, blockers, and next experiments. It does not change candidate
verdict behavior.
