# Ascend Candidate Summary

Schema: `4.0`.

- baseline: `baseline` (<abs-path>/baseline)
- candidate: `missing_raw_index_candidate` (<abs-path>/missing_raw_index_candidate)

## Performance Assessment

Eligibility: `incomplete`; comparison: `not_comparable`.

| Measurement | Value ms | Statistic | Samples | Source |
|---|---:|---|---:|---|
| baseline | n/a | n/a | n/a |  |
| candidate | n/a | n/a | n/a |  |

No comparative performance delta is available.
- `baseline.assessment`: benchmark_context_missing; baseline `n/a`, candidate `n/a`; `baseline: analysis/benchmark_context.json`
- `candidate.assessment`: benchmark_context_missing; baseline `n/a`, candidate `n/a`; `candidate: analysis/benchmark_context.json`

- Caller-provided records establish declared conditions, not the scientific validity of the measurement method.
- Only point estimates are evaluated; uncertainty, raw sample statistics and practical significance are not assessed.

## Mechanism Assessment

Coverage: `partial`.

| Group | Status | Field A | Field B | Baseline | Candidate | Delta | Delta % | Sources / gaps |
|---|---|---|---|---:|---:|---:|---:|---|
| op_summary | not_comparable | Task Duration(us) | Task Duration(us) | 83401.66 | 87139.38 | n/a | n/a | reports/app/PROF_000001_20260605155111872_JDEKRCNERPBNJEGA/mindstudio_profiler_output/op_summary_20260605155140.csv (Task Duration(us)); reports/app/PROF_000001_20260605161708478_FRJKORBPFMHQMGLA/mindstudio_profiler_output/op_summary_20260605161737.csv (Task Duration(us)); metric_scope missing |
| op_statistic | not_comparable | Total Time(us) | Total Time(us) | 249604.48 | 260794.52 | n/a | n/a | reports/app/PROF_000001_20260605155111872_JDEKRCNERPBNJEGA/mindstudio_profiler_output/op_statistic_20260605155140.csv (Total Time(us)); reports/app/PROF_000001_20260605161708478_FRJKORBPFMHQMGLA/mindstudio_profiler_output/op_statistic_20260605161737.csv (Total Time(us)); metric_scope missing |
| task_time | missing | n/a | n/a | n/a | n/a | n/a | n/a | ; headline missing |
| api_statistic | missing | n/a | n/a | n/a | n/a | n/a | n/a | ; headline missing |
| op_basic_info | missing | n/a | n/a | n/a | n/a | n/a | n/a | ; headline missing |
| pipe_utilization | missing | n/a | n/a | n/a | n/a | n/a | n/a | ; headline missing |
| arithmetic_utilization | not_comparable | aiv_vec_ratio | aic_cube_ratio | 1e-06 | 0.0 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/ArithmeticUtilization.csv (aiv_vec_ratio); reports/followups/collect_default_metric_followup/OPPROF_20260605170804_UKAXQCBEDBJAUNQY/ArithmeticUtilization.csv (aic_cube_ratio); profiler.segment.followup:collect_default_metric_followup.output mismatch; profiler.segment.followup:collect_default_metric_followup.command missing; field mismatch; name mismatch; block_scope mismatch |
| l2_cache | not_comparable | aic_total_hit_rate(%) | aic_total_hit_rate(%) | 100.0 | 100.0 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/L2Cache.csv (aic_total_hit_rate(%)); reports/followups/collect_default_metric_followup/OPPROF_20260605170804_UKAXQCBEDBJAUNQY/L2Cache.csv (aic_total_hit_rate(%)); profiler.segment.followup:collect_default_metric_followup.output mismatch; profiler.segment.followup:collect_default_metric_followup.command missing |
| memory | missing | n/a | n/a | n/a | n/a | n/a | n/a | ; headline missing |
| resource_conflict | not_comparable | aic_cube_wait_ratio | aic_cube_wait_ratio | 0.0 | 0.0 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/ResourceConflictRatio.csv (aic_cube_wait_ratio); reports/followups/collect_default_metric_followup/OPPROF_20260605170804_UKAXQCBEDBJAUNQY/ResourceConflictRatio.csv (aic_cube_wait_ratio); profiler.segment.followup:collect_default_metric_followup.output mismatch; profiler.segment.followup:collect_default_metric_followup.command missing |

### Profiler Compatibility

- `cann_version`: `match`; A `8.3.0.2.220:8.3.RC2`, B `8.3.0.2.220:8.3.RC2`.
- `hardware_summary`: `match`; A `4 x 910B2; health OK`, B `4 x 910B2; health OK`.
- `profile_command`: `match`; A `msprof --output=reports/app --application=<abs-path> --runtime-api=on --task-time=on --ai-core=on --aic-metrics=PipeUtilization --type=text --summary-format=csv`, B `msprof --output=reports/app --application=<abs-path> --runtime-api=on --task-time=on --ai-core=on --aic-metrics=PipeUtilization --type=text --summary-format=csv`.
- `metric_scope`: `missing`; A `n/a`, B `n/a`.
- `profile_output_segments`: `mismatch`; A `app=OutputSegment(output=Sourced[str](value='reports/app', source=SourceRef(artifact='logs/command_msprof.txt', field='--output', record=None, column=None)), resolved_output=None, status=None) op=OutputSegment(output=Sourced[str](value='reports/op', source=SourceRef(artifact='logs/command_msprof_op.txt', field='--output', record=None, column=None)), resolved_output=None, status=None) simulator=None followups={'collect_default_metric_followup': OutputSegment(output=Sourced[str](value='reports/followups/collect_default_metric_followup', source=SourceRef(artifact='logs/command_msprof_followup_collect_default_metric_followup.txt', field='--output', record=None, column=None)), resolved_output=Sourced[str](value='reports/followups/collect_default_metric_followup/OPPROF_<sanitized>', source=SourceRef(artifact='reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI', field='existing_report_dir', record=None, column=None)), status=Sourced[str](value='0', source=SourceRef(artifact='logs/msprof_followup_collect_default_metric_followup.status', field='exit_status', record=None, column=None)))}`, B `app=OutputSegment(output=Sourced[str](value='reports/app', source=SourceRef(artifact='logs/command_msprof.txt', field='--output', record=None, column=None)), resolved_output=None, status=None) op=OutputSegment(output=Sourced[str](value='reports/op', source=SourceRef(artifact='logs/command_msprof_op.txt', field='--output', record=None, column=None)), resolved_output=None, status=None) simulator=None followups={'collect_default_metric_followup': OutputSegment(output=Sourced[str](value='reports/followups/collect_default_metric_followup', source=SourceRef(artifact='logs/command_msprof_followup_collect_default_metric_followup.txt', field='--output', record=None, column=None)), resolved_output=Sourced[str](value='reports/followups/collect_default_metric_followup/OPPROF_<sanitized>', source=SourceRef(artifact='reports/followups/collect_default_metric_followup/OPPROF_20260605170804_UKAXQCBEDBJAUNQY', field='existing_report_dir', record=None, column=None)), status=Sourced[str](value='0', source=SourceRef(artifact='logs/msprof_followup_collect_default_metric_followup.status', field='exit_status', record=None, column=None)))}`.
- `workload.id`: `match`; A `tilelang-ascend/svd/v1/official-256x32x32-fp32-cases3`, B `tilelang-ascend/svd/v1/official-256x32x32-fp32-cases3`.
- `workload.shape`: `match`; A `[256, 32, 32]`, B `[256, 32, 32]`.
- `workload.dtype`: `match`; A `float32`, B `float32`.
- `workload.case_count`: `match`; A `3`, B `3`.
- baseline benchmark association: `missing`.
  Benchmark and profiler observations cannot explain the same performance change without a matching recorded implementation and workload.
- candidate benchmark association: `missing`.
  Benchmark and profiler observations cannot explain the same performance change without a matching recorded implementation and workload.

## Evidence Questions

Status: `partial`

| Question ID | Family | Question | Available Evidence | Missing Evidence | Blockers |
|---|---|---|---:|---:|---|
| `memory_cache` | `memory_cache` | Which memory/cache fields are available, and for which target scope? | 7 | 4 | missing memory_cache profiler evidence, profiler.segment.followup:collect_default_metric_followup.output mismatch, profiler.segment.followup:collect_default_metric_followup.command missing |
| `pipe_arithmetic` | `pipe_arithmetic` | Which Cube, Vector, Scalar or MTE fields are available, and for which target scope? | 5 | 2 | missing pipe_arithmetic profiler evidence, profiler.segment.followup:collect_default_metric_followup.output mismatch, profiler.segment.followup:collect_default_metric_followup.command missing |
| `opbasic_workload` | `opbasic_workload` | Which operator launch metadata and workload context are recorded? | 16 | 1 | missing opbasic_workload profiler evidence, profiler.segment.followup:collect_default_metric_followup.output mismatch, profiler.segment.followup:collect_default_metric_followup.command missing, profiler.segment.op.command missing |
| `generated_context` | `generated_context` | Which generated source and simulator context can be associated with the on-device evidence? | 3 | 1 | missing on-device profiler evidence |

### memory_cache

- Question: Which memory/cache fields are available, and for which target scope?
- Available evidence:
  - `baseline: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/Memory.csv (headlines.memory.artifacts.observations.value; record=2; column=27; field=GM_to_L1_datas(KB); statistic=volume; unit=KB; metric=GM_to_L1_datas(KB))`
  - `baseline: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/Memory.csv (headlines.memory.artifacts.observations.value; record=2; column=31; field=L0C_to_L1_datas(KB); statistic=volume; unit=KB; metric=L0C_to_L1_datas(KB))`
  - `baseline: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/Memory.csv (headlines.memory.artifacts.observations.value; record=2; column=33; field=L0C_to_GM_datas(KB); statistic=volume; unit=KB; metric=L0C_to_GM_datas(KB))`
  - `baseline: memory_cache raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/Memory.csv (artifacts[7])`
  - `baseline: memory_cache raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/MemoryL0.csv (artifacts[8])`
- Missing evidence:
  - `candidate: memory_cache artifact is missing: Memory.csv`
  - `candidate: memory_cache artifact is missing: MemoryL0.csv`
  - `candidate: memory_cache artifact is missing: MemoryUB.csv`
  - `candidate: memory_cache artifact is missing: L2Cache.csv`
- Blocked by:
  - missing memory_cache profiler evidence
  - profiler.segment.followup:collect_default_metric_followup.output mismatch
  - profiler.segment.followup:collect_default_metric_followup.command missing

### pipe_arithmetic

- Question: Which Cube, Vector, Scalar or MTE fields are available, and for which target scope?
- Available evidence:
  - `baseline: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/PipeUtilization.csv (headlines.pipe_utilization.artifacts.observations.value; record=2; column=6; field=aic_cube_ratio; statistic=ratio; unit=ratio; metric=aic_cube_ratio)`
  - `baseline: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/PipeUtilization.csv (headlines.pipe_utilization.artifacts.observations.value; record=23; column=8; field=aic_scalar_ratio; statistic=ratio; unit=ratio; metric=aic_scalar_ratio)`
  - `baseline: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/PipeUtilization.csv (headlines.pipe_utilization.artifacts.observations.value; record=2; column=10; field=aic_mte1_ratio; statistic=ratio; unit=ratio; metric=aic_mte1_ratio)`
  - `baseline: pipe_arithmetic raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/PipeUtilization.csv (artifacts[11])`
  - `baseline: pipe_arithmetic raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/ArithmeticUtilization.csv (artifacts[5])`
- Missing evidence:
  - `candidate: pipe_arithmetic artifact is missing: PipeUtilization.csv`
  - `candidate: pipe_arithmetic artifact is missing: ArithmeticUtilization.csv`
- Blocked by:
  - missing pipe_arithmetic profiler evidence
  - profiler.segment.followup:collect_default_metric_followup.output mismatch
  - profiler.segment.followup:collect_default_metric_followup.command missing

### opbasic_workload

- Question: Which operator launch metadata and workload context are recorded?
- Available evidence:
  - `baseline: work distribution summary signal: reports/app/PROF_000001_20260605155111872_JDEKRCNERPBNJEGA/mindstudio_profiler_output/task_time_20260605155140.csv (headlines.task_time.artifacts.observations.value; record=3; column=6; field=task_time(us); statistic=duration; unit=us; metric=task_time)`
  - `baseline: work distribution summary signal: reports/app/PROF_000001_20260605155111872_JDEKRCNERPBNJEGA/mindstudio_profiler_output/task_time_20260605155140.csv (headlines.task_time.artifacts.observations.value; record=5; column=6; field=task_time(us); statistic=duration; unit=us; metric=task_time)`
  - `baseline: work distribution summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/OpBasicInfo.csv (headlines.op_basic_info.artifacts.observations.value; record=2; column=3; field=Task Duration(us); statistic=duration; unit=us; metric=Task Duration(us))`
  - `baseline: work distribution raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/OpBasicInfo.csv (raw_artifact_index.artifacts[group=op_basic_info])`
  - `baseline: work distribution raw artifact: reports/op/OPPROF_20260605155158_TIDPSIUYBGPWXXNW/OpBasicInfo.csv (raw_artifact_index.artifacts[group=op_basic_info])`
  - `candidate: work distribution summary signal: reports/app/PROF_000001_20260605161708478_FRJKORBPFMHQMGLA/mindstudio_profiler_output/task_time_20260605161737.csv (headlines.task_time.artifacts.observations.value; record=3; column=6; field=task_time(us); statistic=duration; unit=us; metric=task_time)`
  - `candidate: work distribution summary signal: reports/app/PROF_000001_20260605161708478_FRJKORBPFMHQMGLA/mindstudio_profiler_output/task_time_20260605161737.csv (headlines.task_time.artifacts.observations.value; record=5; column=6; field=task_time(us); statistic=duration; unit=us; metric=task_time)`
  - `candidate: work distribution summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170804_UKAXQCBEDBJAUNQY/OpBasicInfo.csv (headlines.op_basic_info.artifacts.observations.value; record=2; column=3; field=Task Duration(us); statistic=duration; unit=us; metric=Task Duration(us))`
  - `candidate: workload context: analysis/tilelang_context.json (benchmark.workload.id)`
  - `candidate: workload context: analysis/tilelang_context.json (benchmark.workload.shape)`
- Missing evidence:
  - `candidate: opbasic_workload artifact is missing: OpBasicInfo.csv`
- Blocked by:
  - missing opbasic_workload profiler evidence
  - profiler.segment.followup:collect_default_metric_followup.output mismatch
  - profiler.segment.followup:collect_default_metric_followup.command missing
  - profiler.segment.op.command missing

### generated_context

- Question: Which generated source and simulator context can be associated with the on-device evidence?
- Available evidence:
  - `baseline: generated TileLang source context: analysis/tilelang_context.json (jit_debug)`
  - `baseline: on-device evidence required before source inspection: analysis/raw_artifact_index.json (artifacts[status=parsed])`
  - `candidate: generated TileLang source context: analysis/tilelang_context.json (jit_debug)`
- Missing evidence:
  - `candidate: on-device evidence is required before source inspection: analysis/raw_artifact_index.json (artifacts[status=parsed])`
- Blocked by:
  - missing on-device profiler evidence

### Pending Collection Actions


- Metric observations describe the recorded scope; they do not establish a bottleneck or cause of speedup. Question status describes evidence availability, not experiment readiness.

## Inspection Targets


## Warnings

- candidate: raw_artifact_index unavailable; timing artifact inventory consistency cannot be checked
