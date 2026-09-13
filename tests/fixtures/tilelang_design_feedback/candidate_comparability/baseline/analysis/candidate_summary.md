# Ascend Candidate Summary

Schema: `4.0`.

- candidate: `baseline` (<abs-path>/baseline)

## Performance Assessment

Eligibility: `incomplete`; comparison: `not_applicable`.

| Measurement | Value ms | Statistic | Samples | Source |
|---|---:|---|---:|---|
| candidate | n/a | n/a | n/a |  |

No comparative performance delta is available.
- `candidate.assessment`: benchmark_context_missing; baseline `n/a`, candidate `n/a`; `candidate: analysis/benchmark_context.json`

- Caller-provided records establish declared conditions, not the scientific validity of the measurement method.
- Only point estimates are evaluated; uncertainty, raw sample statistics and practical significance are not assessed.

## Mechanism Assessment

Coverage: `available`.

| Group | Status | Field A | Field B | Baseline | Candidate | Delta | Delta % | Sources / gaps |
|---|---|---|---|---:|---:|---:|---:|---|
| arithmetic_utilization | observed | n/a | aiv_vec_ratio | n/a | 1e-06 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/ArithmeticUtilization.csv (aiv_vec_ratio);  |
| l2_cache | observed | n/a | aic_total_hit_rate(%) | n/a | 100.0 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/L2Cache.csv (aic_total_hit_rate(%));  |
| resource_conflict | observed | n/a | aic_cube_wait_ratio | n/a | 0.0 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/ResourceConflictRatio.csv (aic_cube_wait_ratio);  |

### Profiler Compatibility

- candidate benchmark association: `missing`.
  Benchmark and profiler observations cannot explain the same performance change without a matching recorded implementation and workload.

## Evidence Questions

Status: `available`

| Question ID | Family | Question | Available Evidence | Missing Evidence | Blockers |
|---|---|---|---:|---:|---|
| `memory_cache` | `memory_cache` | Which memory/cache fields are available, and for which target scope? | 7 | 0 | none |
| `pipe_arithmetic` | `pipe_arithmetic` | Which Cube, Vector, Scalar or MTE fields are available, and for which target scope? | 5 | 0 | none |
| `opbasic_workload` | `opbasic_workload` | Which operator launch metadata and workload context are recorded? | 9 | 0 | none |
| `generated_context` | `generated_context` | Which generated source and simulator context can be associated with the on-device evidence? | 2 | 0 | none |

### memory_cache

- Question: Which memory/cache fields are available, and for which target scope?
- Available evidence:
  - `candidate: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/Memory.csv (headlines.memory.artifacts.observations.value; record=2; column=27; field=GM_to_L1_datas(KB); statistic=volume; unit=KB; metric=GM_to_L1_datas(KB))`
  - `candidate: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/Memory.csv (headlines.memory.artifacts.observations.value; record=2; column=31; field=L0C_to_L1_datas(KB); statistic=volume; unit=KB; metric=L0C_to_L1_datas(KB))`
  - `candidate: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/Memory.csv (headlines.memory.artifacts.observations.value; record=2; column=33; field=L0C_to_GM_datas(KB); statistic=volume; unit=KB; metric=L0C_to_GM_datas(KB))`
  - `candidate: memory_cache raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/Memory.csv (artifacts[7])`
  - `candidate: memory_cache raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/MemoryL0.csv (artifacts[8])`

### pipe_arithmetic

- Question: Which Cube, Vector, Scalar or MTE fields are available, and for which target scope?
- Available evidence:
  - `candidate: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/PipeUtilization.csv (headlines.pipe_utilization.artifacts.observations.value; record=2; column=6; field=aic_cube_ratio; statistic=ratio; unit=ratio; metric=aic_cube_ratio)`
  - `candidate: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/PipeUtilization.csv (headlines.pipe_utilization.artifacts.observations.value; record=23; column=8; field=aic_scalar_ratio; statistic=ratio; unit=ratio; metric=aic_scalar_ratio)`
  - `candidate: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/PipeUtilization.csv (headlines.pipe_utilization.artifacts.observations.value; record=2; column=10; field=aic_mte1_ratio; statistic=ratio; unit=ratio; metric=aic_mte1_ratio)`
  - `candidate: pipe_arithmetic raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/PipeUtilization.csv (artifacts[11])`
  - `candidate: pipe_arithmetic raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/ArithmeticUtilization.csv (artifacts[5])`

### opbasic_workload

- Question: Which operator launch metadata and workload context are recorded?
- Available evidence:
  - `candidate: work distribution summary signal: reports/app/PROF_000001_20260605155111872_JDEKRCNERPBNJEGA/mindstudio_profiler_output/task_time_20260605155140.csv (headlines.task_time.artifacts.observations.value; record=3; column=6; field=task_time(us); statistic=duration; unit=us; metric=task_time)`
  - `candidate: work distribution summary signal: reports/app/PROF_000001_20260605155111872_JDEKRCNERPBNJEGA/mindstudio_profiler_output/task_time_20260605155140.csv (headlines.task_time.artifacts.observations.value; record=5; column=6; field=task_time(us); statistic=duration; unit=us; metric=task_time)`
  - `candidate: work distribution summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/OpBasicInfo.csv (headlines.op_basic_info.artifacts.observations.value; record=2; column=3; field=Task Duration(us); statistic=duration; unit=us; metric=Task Duration(us))`
  - `candidate: work distribution raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/OpBasicInfo.csv (raw_artifact_index.artifacts[group=op_basic_info])`
  - `candidate: work distribution raw artifact: reports/op/OPPROF_20260605155158_TIDPSIUYBGPWXXNW/OpBasicInfo.csv (raw_artifact_index.artifacts[group=op_basic_info])`

### generated_context

- Question: Which generated source and simulator context can be associated with the on-device evidence?
- Available evidence:
  - `candidate: generated TileLang source context: analysis/tilelang_context.json (jit_debug)`
  - `candidate: on-device evidence required before source inspection: analysis/raw_artifact_index.json (artifacts[status=parsed])`

### Pending Collection Actions


- Metric observations describe the recorded scope; they do not establish a bottleneck or cause of speedup. Question status describes evidence availability, not experiment readiness.

## Inspection Targets


## Warnings
