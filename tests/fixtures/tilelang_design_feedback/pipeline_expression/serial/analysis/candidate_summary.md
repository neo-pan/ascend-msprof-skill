# Ascend Candidate Summary

Schema: `2.0`.

- candidate: `serial` (<abs-path>/serial)

## Performance Assessment

Eligibility: `incomplete`; comparison: `not_applicable`.

| Measurement | Value ms | Statistic | Samples | Source |
|---|---:|---|---:|---|
| candidate | n/a | n/a | n/a |  |

No comparative performance delta is available.
- `candidate.assessment`: benchmark_context_missing; baseline `n/a`, candidate `n/a`; `candidate: analysis/benchmark_context.json (assessment)`

- Caller-provided records establish declared conditions, not the scientific validity of the measurement method.
- Only point estimates are evaluated; uncertainty, raw sample statistics and practical significance are not assessed.

## Mechanism Assessment

Coverage: `available`.

| Group | Status | Field A | Field B | Baseline | Candidate | Delta | Delta % | Sources / gaps |
|---|---|---|---|---:|---:|---:|---:|---|

### Profiler Compatibility

- candidate benchmark association: `missing`.
  Benchmark and profiler observations cannot explain the same performance change without a matching recorded implementation and workload.

## Design Feedback

Status: `available`

| Question ID | Family | Question | Available Evidence | Missing Evidence | Blockers |
|---|---|---|---:|---:|---|
| `memory_cache` | `memory_cache` | Which memory movement or cache fields support the next inspection? | 7 | 0 | none |
| `pipe_arithmetic` | `pipe_arithmetic` | Which Cube, Vector, Scalar or MTE fields support the next inspection? | 5 | 0 | none |
| `opbasic_workload` | `opbasic_workload` | Should the next inspection compare work distribution and launch shape context against the intended TileLang design variable? | 9 | 0 | none |
| `generated_context` | `generated_context` | Can the generated TileLang context guide source inspection after on-device evidence is available? | 2 | 0 | none |

### memory_cache

- Question: Which memory movement or cache fields support the next inspection?
- Related design variables: `memory_movement, cache_context, metric_scope`
- Available evidence:
  - `candidate: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/Memory.csv (headlines.memory.value; headlines.memory.raw_row.GM_to_L1_bw_usage_rate(%); headlines.memory.field=GM_to_L1_bw_usage_rate(%); headlines.memory.field_kind=memory_usage_rate)`
  - `candidate: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/L2Cache.csv (headlines.l2_cache.value; headlines.l2_cache.raw_row.aic_total_hit_rate(%); headlines.l2_cache.field=aic_total_hit_rate(%); headlines.l2_cache.field_kind=l2_cache_hit_rate)`
  - `candidate: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/L2Cache.csv (headlines.l2_cache)`
  - `candidate: memory_cache raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/Memory.csv (artifacts[7])`
  - `candidate: memory_cache raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/MemoryL0.csv (artifacts[8])`
- Next experiment: Collect the missing Default family artifacts for the stated target and workload.

### pipe_arithmetic

- Question: Which Cube, Vector, Scalar or MTE fields support the next inspection?
- Related design variables: `pipe_mix, arithmetic_mix`
- Available evidence:
  - `candidate: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/PipeUtilization.csv (headlines.pipe_utilization.value; headlines.pipe_utilization.raw_row.aic_mte2_ratio; headlines.pipe_utilization.field=aic_mte2_ratio; headlines.pipe_utilization.field_kind=utilization_or_ratio)`
  - `candidate: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/ArithmeticUtilization.csv (headlines.arithmetic_utilization.value; headlines.arithmetic_utilization.raw_row.aic_cube_ratio; headlines.arithmetic_utilization.field=aic_cube_ratio; headlines.arithmetic_utilization.field_kind=utilization_or_ratio)`
  - `candidate: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/ArithmeticUtilization.csv (headlines.arithmetic_utilization)`
  - `candidate: pipe_arithmetic raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/PipeUtilization.csv (artifacts[11])`
  - `candidate: pipe_arithmetic raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/ArithmeticUtilization.csv (artifacts[5])`
- Next experiment: Collect matching pipe and arithmetic artifacts for the stated target and workload.

### opbasic_workload

- Question: Should the next inspection compare work distribution and launch shape context against the intended TileLang design variable?
- Related design variables: `work_distribution, block_dim, shape_specialization, tail_work`
- Available evidence:
  - `candidate: work distribution summary signal: reports/app/PROF_000001_20260606121223051_GECRNPRPFIQLEHLA/mindstudio_profiler_output/task_time_20260606121251.csv (headlines.task_time.value; headlines.task_time.raw_row.task_time(us); headlines.task_time.field_kind=duration_or_time)`
  - `candidate: work distribution summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/OpBasicInfo.csv (headlines.op_basic_info.value; headlines.op_basic_info.first_row.Task Duration(us); headlines.op_basic_info.field=Task Duration(us); headlines.op_basic_info.field_kind=basic_info)`
  - `candidate: work distribution summary signal: reports/app/PROF_000001_20260606121223051_GECRNPRPFIQLEHLA/mindstudio_profiler_output/task_time_20260606121251.csv (headlines.task_time.value; headlines.task_time.raw_row.task_time(us); headlines.task_time.field_kind=duration_or_time)`
  - `candidate: work distribution raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/OpBasicInfo.csv (raw_artifact_index.artifacts[group=op_basic_info])`
  - `candidate: work distribution raw artifact: reports/op/OPPROF_20260606121252_MCHGUDCSIZSRIMGO/OpBasicInfo.csv (raw_artifact_index.artifacts[group=op_basic_info])`
- Next experiment: Collect OpBasicInfo.csv with matching TileLang workload context, then compare block/work-distribution fields against the intended design variable.

### generated_context

- Question: Can the generated TileLang context guide source inspection after on-device evidence is available?
- Related design variables: `generated_source_context, jit_configuration, source_inspection_context`
- Available evidence:
  - `candidate: generated TileLang source context: analysis/tilelang_context.json (jit_debug)`
  - `candidate: on-device evidence required before source inspection: analysis/raw_artifact_index.json (artifacts[status=parsed])`
- Next experiment: Pair the generated TileLang source context with parsed on-device profiler artifacts before using it to guide source inspection.

### Pending Collection Actions


- Metric observations and inspection hypotheses do not establish a cause of speedup.

## Inspection Targets

- `inspect_pipe_arithmetic_mix`: `None` (optimization_directions).
- `inspect_memory_movement`: `None` (optimization_directions).
- `inspect_resource_conflict`: `None` (optimization_directions).

## Warnings
