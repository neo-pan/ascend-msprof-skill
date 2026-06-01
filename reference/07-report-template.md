# Final Report Template

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

**One-line read:** <main bottleneck and why>

## 2. Analysis

### Duration And Calls

### Pipe Utilization

### Memory Movement

### Conflicts

### Tiling And Core Balance

### Simulator Hotspots

## 3. Diagnosis

| Finding | Evidence | Impact |
|---|---|---|

## 4. Optimization Directions

1. <highest-impact change>
2. <next change>
3. <next change>

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

When `helpers/prepare_tilelang_profile_run.py` is used, it may also write
`analysis/tilelang_profile_run.json` to record workflow layout checks. Treat
that file as provenance for the preparation step, not as a profiler metric
source.

## Generated Excerpt Example

This abbreviated example is generated from
`tests/fixtures/real_cann_minimal/analysis/summary.json` with:

```bash
python3 helpers/generate_report.py --run-dir tests/fixtures/real_cann_minimal
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
  `analysis/timeline.txt`, `analysis/simulator_hotspots.txt`

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
python3 helpers/analyze_msprof_outputs.py --run-dir <run-dir>
python3 helpers/generate_report.py --run-dir <run-dir>
```
````
