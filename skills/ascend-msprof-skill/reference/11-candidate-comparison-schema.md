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
`comparison_schema_version: "1.3"`. It contains:

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
  and role.
- `missing_evidence[]`: cited absent artifact, field, context, or incompatible
  evidence needed before stronger feedback.
- `next_experiment`: one controlled collection or comparison step.
- `blocked_by[]`: compile, correctness, workload, provenance, raw index,
  on-device evidence, or compatibility blockers.

Design feedback text is limited to design questions, cited available evidence,
missing evidence, blockers, and next experiments. It does not change candidate
verdict behavior.
