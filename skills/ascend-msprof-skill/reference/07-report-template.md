# Final Report Template

## Contents

- [Setup](#0-setup)
- [Headline Numbers](#1-headline-numbers)
- [Analysis](#2-analysis)
- [Diagnosis](#3-diagnosis)
- [Optimization Directions](#4-optimization-directions)
- [Confidence And Caveats](#5-confidence-and-caveats)
- [Reproduction](#6-reproduction)
- [Generated Excerpt Example](#generated-excerpt-example)

Save as `$PROFILE_RUN_DIR/REPORT.md`.

```markdown
# <kernel_or_operator> Ascend Profiling Report

**Target:** Ascend 910B
**CANN / driver / firmware:** <versions>
**Profile date:** YYYY-MM-DD
**Run directory:** `profile/<run_name>/`

## 0. Setup

- Harness/application:
- Workload shape and dtype:
- Tiling path and blockDim:
- Commands:
- Profile outputs: app/op `--output` paths and resolved profiler result
  directories when segmented provenance is available. Automatic Default
  follow-up collections render as `followups.<action_id>` output segments
  with their `reports/followups/<action_id>` output path and resolved
  `OPPROF_*` result directory when present.
- Raw artifacts:

## 1. Headline Numbers

| Metric | Value | Source |
|---|---:|---|
| Top operator duration | | `op_summary_*.csv` |
| Call count | | `op_summary_*.csv` |
| Top task duration | | `task_time_*.csv` |
| Dominant pipe | | `PipeUtilization.csv` |
| Top memory signal | | `Memory*.csv` |
| Top conflict signal | | `ResourceConflictRatio.csv` |

**One-line read:** <sourced timing/metric signal and what to inspect next>

## 2. Analysis

### Analysis Dimensions

### Evidence Readiness

### Evidence Relations

### Duration And Calls

### App/Op Correlation

### Pipe Utilization

### Memory Movement

### Conflicts

### Tiling And Core Balance

### Simulator Hotspots

## 3. Diagnosis

| Finding | Evidence | Impact |
|---|---|---|

## 4. Optimization Directions

1. <ranked direction title>
   - Action: <inspection or change direction>
   - Impact basis: <why this was ranked here>
   - Confidence: <low|medium|high>; effort: <low|medium|high>
   - Inspect code area: <code area from experiment_hint>
   - Next experiment: <one controlled experiment>
   - Expected profiler change: <support/refute signal to check>
   - Recollect artifacts: <artifact list>
   - Source context: <compact simulator hotspot references, when present>
   - Caveats: <hint caveats>
   - Evidence: <artifact and exact summary field references>
2. <next direction>
3. <next direction>

## 5. Confidence And Caveats

## 6. Reproduction
```

Keep the report short. Put large tables in `analysis/`.

`analysis/summary.json` can also contain fixture-backed raw stdout evidence
under `stdout_sections`. `occupancy_summary` preserves the section source,
section name, and messages with `ordinal` plus raw `message`.
`roofline_summary` preserves the section source, section name, and raw
`message` values. These sections can be shown as evidence tables, but they do
not generate headline numbers, diagnosis rows, or optimization directions.

When present, `analysis/tilelang_context.json` can be shown as a TileLang
benchmark context section. It cites workload id, shape, dtype, case count,
candidate runtime stats, correctness maxima, payload source, and optional JIT
config or debug artifact inventory. This benchmark context is evidence only
and does not generate Ascend profiler headline numbers, diagnosis rows, or
optimization directions by itself.

When both application-level and operator-level headlines are present,
`generate_report.py` can show an `App/Op Correlation` table in the analysis
section. It aligns only sourced evidence from `headlines.op_summary`,
`headlines.task_time`, `headlines.op_basic_info`, and
`headlines.pipe_utilization`, with artifact paths and exact `summary.json`
field references. It must not calculate app/op duration deltas, infer a
bottleneck, or generate optimization advice or diagnosis rows by itself.

`analysis/summary.json` is the canonical structured source; `REPORT.md` is an
evidence-cited rendering. `summary.json` can also contain
`analysis_schema_version`, `metric_scope`, `target_identity`,
`analysis_dimensions`, `evidence_readiness`, `evidence_relations`,
`optimization_directions`, and `next_collection_actions`. `target_identity` is
the target-alignment surface; use its status, observed `match_rule`, and
run-level confidence before trusting directions. `analysis_dimensions` records
the six Ascend-native inspection dimensions from
`reference/05-analysis-dimensions.md`. Each signal must include an artifact
path, summary field reference, raw field name when available, and observed
value when available. `evidence_readiness` is the evidence-quality surface, not
a kernel-quality score. `evidence_relations[]` is an optional set of mechanical
artifact links across corroborated timing, metric, and simulator evidence. The
report may render a concise `### Evidence Relations` table only when relations
exist, using the stored `summary.json` entries. Do not derive relations in the
report layer, and do not present them as performance-cause or root-cause
claims.
`optimization_directions` is an ordered list generated from analysis signals.
A concrete direction requires timing evidence plus at least one corroborating
CANN metric family; duration only produces a focused inspection direction.
Each direction renders its `id`, required artifacts, missing artifacts, stored
`experiment_hint` fields, and evidence IDs when present. The report renders
direction-level hints under each direction; do not add a top-level hint
section, derive hints in the report layer, or turn an expected profiler change
into a promised result. Single cache, memory, conflict, stdout, binary, or
App/Op Correlation signals remain evidence-only.

`next_collection_actions` is a collection-only model. Reports may render a
short `### Next Collection Actions` section, but these actions must not become
code-change advice. Use them to decide whether another `msprof op
--aic-metrics` collection is needed before kernel hypotheses.

Reports may render a concise `### Evidence Readiness` section from
`analysis/summary.json`. It should show the readiness level, available and
missing evidence families, preserved unparsed binary artifacts when present,
the next minimal collection action, and allowed versus blocked claims. Do not
render the full artifact contract table in `REPORT.md`; keep the complete
machine-readable contract in `analysis/summary.json` and
`analysis/raw_artifact_index.json`.

Reports may render `### Evidence Relations` only when
`summary.evidence_relations[]` is non-empty. Include relation kind, target,
confidence, role, evidence ids/artifacts/field refs, optional
`source_context_refs[]`, and the allowed/blocked interpretation boundary.
Timing-only, simulator-only, stdout-only, and binary-only runs should have no
relation rows.

Profiler stdout sections may appear under `stdout_sections`. The supported raw
sections are `occupancy_summary`, `roofline_summary`, and
`performance_summary`. `performance_summary.messages[]` keeps only `ordinal`,
raw `message`, and source path fields. Reports may render those messages as
Analysis evidence, but a pipe-utilization advisory direction requires timing
evidence and `PipeUtilization.csv` corroboration.

When `ascend-msprof prepare-tilelang` is used, it may also write
`analysis/tilelang_profile_run.json` to record workflow layout checks. Treat
that file as provenance for the preparation step, not as a profiler metric
source.

## Generated Excerpt Example

This abbreviated example is generated from
`tests/fixtures/real_cann_minimal/analysis/summary.json` with:

```bash
ascend-msprof report --run-dir tests/fixtures/real_cann_minimal
```

Keep generated fixture `REPORT.md` files uncommitted. Use this excerpt only as
the expected shape for concise, evidence-cited report text.

````markdown
# sanitized_operator_kernel Ascend Profiling Report

**Target:** Ascend 910B
**CANN / driver / firmware:** not recorded by this helper
**Profile date:** not recorded by this helper
**Run directory:** `real_cann_minimal`

## 0. Setup

- Raw artifacts: `reports/`
- Analysis artifacts: `analysis/summary.json`, `analysis/key_metrics.txt`,
  `analysis/timeline.txt`, `analysis/simulator_hotspots.json`,
  `analysis/simulator_hotspots.txt`

## 1. Headline Numbers

| Metric | Signal | Value | Source |
|---|---|---:|---|
| Top operator duration | sanitized_kernel | 42399.1 | `reports/PROF_001/mindstudio_profiler_output/op_summary_001.csv`; `headlines.op_summary.value; headlines.op_summary.field_kind=duration_or_time` |
| Dominant pipe signal | cube0 | 0 | `reports/OPPROF_001/PipeUtilization.csv`; `headlines.pipe_utilization.value; headlines.pipe_utilization.field_kind=utilization_or_ratio` |
| Top memory signal | vector0 / UB_to_GM_bw_usage_rate(%) | 0.357273 | `reports/OPPROF_001/Memory.csv`; `headlines.memory.value; headlines.memory.field=UB_to_GM_bw_usage_rate(%); headlines.memory.field_kind=memory_usage_rate` |

**One-line read:** Available sourced headline `Top operator duration` reports
`sanitized_kernel` = `42399.1`; source
`reports/PROF_001/mindstudio_profiler_output/op_summary_001.csv`;
`headlines.op_summary.value; headlines.op_summary.field_kind=duration_or_time`.

## 3. Diagnosis

| Finding | Evidence | Impact |
|---|---|---|
| Highest application-level operator duration: sanitized_kernel = 42399.1 | `reports/PROF_001/mindstudio_profiler_output/op_summary_001.csv`; `headlines.op_summary.value; headlines.op_summary.field_kind=duration_or_time` | Use this sourced signal to choose the next focused inspection step. |

## 5. Confidence And Caveats

- Confidence is limited to artifacts summarized in `analysis/summary.json`.
- No missing optional analysis artifacts were detected.

## 6. Reproduction

```bash
ascend-msprof analyze --run-dir <run-dir>
ascend-msprof report --run-dir <run-dir>
```

Generated reports should prefer `optimization_directions` when present. If an
older `summary.json` lacks the optional model fields, keep the legacy fallback:
inspect sourced diagnosis rows first, or collect missing profiler artifacts
when no diagnosis row exists.
````
