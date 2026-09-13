# Ascend Candidate Summary

Schema: `4.0`.

- baseline: `serial` (<abs-path>/serial)
- candidate: `pipelined` (<abs-path>/pipelined)

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
| op_summary | not_comparable | Task Duration(us) | Task Duration(us) | 92.6 | 96.16 | n/a | n/a | reports/app/PROF_000001_20260606121223051_GECRNPRPFIQLEHLA/mindstudio_profiler_output/op_summary_20260606121251.csv (Task Duration(us)); reports/app/PROF_000001_20260606121448940_RGBHHJGBAJGRQEOB/mindstudio_profiler_output/op_summary_20260606121516.csv (Task Duration(us)); metric_scope missing |
| op_statistic | not_comparable | Total Time(us) | Total Time(us) | 92.6 | 96.16 | n/a | n/a | reports/app/PROF_000001_20260606121223051_GECRNPRPFIQLEHLA/mindstudio_profiler_output/op_statistic_20260606121251.csv (Total Time(us)); reports/app/PROF_000001_20260606121448940_RGBHHJGBAJGRQEOB/mindstudio_profiler_output/op_statistic_20260606121516.csv (Total Time(us)); metric_scope missing |
| task_time | missing | n/a | n/a | n/a | n/a | n/a | n/a | ; headline missing |
| api_statistic | missing | n/a | n/a | n/a | n/a | n/a | n/a | ; headline missing |
| op_basic_info | missing | n/a | n/a | n/a | n/a | n/a | n/a | ; headline missing |
| pipe_utilization | missing | n/a | n/a | n/a | n/a | n/a | n/a | ; headline missing |
| arithmetic_utilization | not_comparable | aic_cube_ratio | aic_cube_ratio | 0.105385 | 0.104605 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/ArithmeticUtilization.csv (aic_cube_ratio); reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/ArithmeticUtilization.csv (aic_cube_ratio); profiler.segment.followup:collect_default_metric_followup.output mismatch; profiler.segment.followup:collect_default_metric_followup.command missing; block_scope mismatch |
| l2_cache | not_comparable | aic_total_hit_rate(%) | aic_total_hit_rate(%) | 97.960808 | 97.960808 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/L2Cache.csv (aic_total_hit_rate(%)); reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/L2Cache.csv (aic_total_hit_rate(%)); profiler.segment.followup:collect_default_metric_followup.output mismatch; profiler.segment.followup:collect_default_metric_followup.command missing; block_scope mismatch |
| memory | missing | n/a | n/a | n/a | n/a | n/a | n/a | ; headline missing |
| resource_conflict | not_comparable | aic_mte2_wait_ratio | aic_mte2_wait_ratio | 0.162244 | 0.162543 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/ResourceConflictRatio.csv (aic_mte2_wait_ratio); reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/ResourceConflictRatio.csv (aic_mte2_wait_ratio); profiler.segment.followup:collect_default_metric_followup.output mismatch; profiler.segment.followup:collect_default_metric_followup.command missing; block_scope mismatch |

### Profiler Compatibility

- `cann_version`: `match`; A `8.3.0.2.220:8.3.RC2`, B `8.3.0.2.220:8.3.RC2`.
- `hardware_summary`: `match`; A `4 x 910B2; health OK`, B `4 x 910B2; health OK`.
- `profile_command`: `match`; A `env ASCEND_RT_VISIBLE_DEVICES=0 ACL_OP_INIT_MODE=1 TL_ASCEND_DEBUG_INFO=1 TMPDIR=<abs-path> PYTHONPATH=<abs-path>:<abs-path>:<abs-path> PATH=<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path> msprof --output=reports/app --application=<abs-path> --runtime-api=on --task-time=on --ai-core=on --aic-metrics=PipeUtilization --type=text --summary-format=csv`, B `env ASCEND_RT_VISIBLE_DEVICES=0 ACL_OP_INIT_MODE=1 TL_ASCEND_DEBUG_INFO=1 TMPDIR=<abs-path> PYTHONPATH=<abs-path>:<abs-path>:<abs-path> PATH=<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path> msprof --output=reports/app --application=<abs-path> --runtime-api=on --task-time=on --ai-core=on --aic-metrics=PipeUtilization --type=text --summary-format=csv`.
- `metric_scope`: `missing`; A `n/a`, B `n/a`.
- `profile_output_segments`: `mismatch`; A `app=OutputSegment(output=Sourced[str](value='reports/app', source=SourceRef(artifact='logs/command_msprof.txt', field='--output', record=None, column=None)), resolved_output=Sourced[str](value='reports/app/PROF_<sanitized>', source=SourceRef(artifact='logs/command_msprof.stdout', field='Data is saved in', record=None, column=None)), status=None) op=OutputSegment(output=Sourced[str](value='reports/op', source=SourceRef(artifact='logs/command_msprof_op.txt', field='--output', record=None, column=None)), resolved_output=None, status=None) simulator=None followups={'collect_default_metric_followup': OutputSegment(output=Sourced[str](value='reports/followups/collect_default_metric_followup', source=SourceRef(artifact='logs/command_msprof_followup_collect_default_metric_followup.txt', field='--output', record=None, column=None)), resolved_output=Sourced[str](value='reports/followups/collect_default_metric_followup/OPPROF_<sanitized>', source=SourceRef(artifact='reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR', field='existing_report_dir', record=None, column=None)), status=None)}`, B `app=OutputSegment(output=Sourced[str](value='reports/app', source=SourceRef(artifact='logs/command_msprof.txt', field='--output', record=None, column=None)), resolved_output=Sourced[str](value='reports/app/PROF_<sanitized>', source=SourceRef(artifact='logs/command_msprof.stdout', field='Data is saved in', record=None, column=None)), status=None) op=OutputSegment(output=Sourced[str](value='reports/op', source=SourceRef(artifact='logs/command_msprof_op.txt', field='--output', record=None, column=None)), resolved_output=None, status=None) simulator=None followups={'collect_default_metric_followup': OutputSegment(output=Sourced[str](value='reports/followups/collect_default_metric_followup', source=SourceRef(artifact='logs/command_msprof_followup_collect_default_metric_followup.txt', field='--output', record=None, column=None)), resolved_output=Sourced[str](value='reports/followups/collect_default_metric_followup/OPPROF_<sanitized>', source=SourceRef(artifact='reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX', field='existing_report_dir', record=None, column=None)), status=None)}`.
- `workload.id`: `match`; A `tilelang-ascend/matmul_add/v1/controlled-1024x1024x1024-float16`, B `tilelang-ascend/matmul_add/v1/controlled-1024x1024x1024-float16`.
- `workload.shape`: `match`; A `[1024, 1024, 1024]`, B `[1024, 1024, 1024]`.
- `workload.dtype`: `match`; A `float16`, B `float16`.
- `workload.case_count`: `match`; A `1`, B `1`.
- baseline benchmark association: `missing`.
  Benchmark and profiler observations cannot explain the same performance change without a matching recorded implementation and workload.
- candidate benchmark association: `missing`.
  Benchmark and profiler observations cannot explain the same performance change without a matching recorded implementation and workload.

## Evidence Questions

Status: `partial`

| Question ID | Family | Question | Available Evidence | Missing Evidence | Blockers |
|---|---|---|---:|---:|---|
| `memory_cache` | `memory_cache` | Which memory/cache fields are available, and for which target scope? | 14 | 0 | profiler.segment.followup:collect_default_metric_followup.output mismatch, profiler.segment.followup:collect_default_metric_followup.command missing |
| `pipe_arithmetic` | `pipe_arithmetic` | Which Cube, Vector, Scalar or MTE fields are available, and for which target scope? | 10 | 0 | profiler.segment.followup:collect_default_metric_followup.output mismatch, profiler.segment.followup:collect_default_metric_followup.command missing |
| `opbasic_workload` | `opbasic_workload` | Which operator launch metadata and workload context are recorded? | 18 | 0 | profiler.segment.followup:collect_default_metric_followup.output mismatch, profiler.segment.followup:collect_default_metric_followup.command missing, profiler.segment.op.command missing |
| `generated_context` | `generated_context` | Which generated source and simulator context can be associated with the on-device evidence? | 4 | 0 | none |

### memory_cache

- Question: Which memory/cache fields are available, and for which target scope?
- Available evidence:
  - `baseline: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/Memory.csv (headlines.memory.artifacts.observations.value; record=2; column=27; field=GM_to_L1_datas(KB); statistic=volume; unit=KB; metric=GM_to_L1_datas(KB))`
  - `baseline: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/Memory.csv (headlines.memory.artifacts.observations.value; record=2; column=31; field=L0C_to_L1_datas(KB); statistic=volume; unit=KB; metric=L0C_to_L1_datas(KB))`
  - `baseline: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/Memory.csv (headlines.memory.artifacts.observations.value; record=2; column=33; field=L0C_to_GM_datas(KB); statistic=volume; unit=KB; metric=L0C_to_GM_datas(KB))`
  - `baseline: memory_cache raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/Memory.csv (artifacts[7])`
  - `baseline: memory_cache raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/MemoryL0.csv (artifacts[8])`
  - `candidate: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/Memory.csv (headlines.memory.artifacts.observations.value; record=2; column=27; field=GM_to_L1_datas(KB); statistic=volume; unit=KB; metric=GM_to_L1_datas(KB))`
  - `candidate: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/Memory.csv (headlines.memory.artifacts.observations.value; record=2; column=31; field=L0C_to_L1_datas(KB); statistic=volume; unit=KB; metric=L0C_to_L1_datas(KB))`
  - `candidate: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/Memory.csv (headlines.memory.artifacts.observations.value; record=2; column=33; field=L0C_to_GM_datas(KB); statistic=volume; unit=KB; metric=L0C_to_GM_datas(KB))`
  - `candidate: memory_cache raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/Memory.csv (artifacts[7])`
  - `candidate: memory_cache raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/MemoryL0.csv (artifacts[8])`
- Blocked by:
  - profiler.segment.followup:collect_default_metric_followup.output mismatch
  - profiler.segment.followup:collect_default_metric_followup.command missing

### pipe_arithmetic

- Question: Which Cube, Vector, Scalar or MTE fields are available, and for which target scope?
- Available evidence:
  - `baseline: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/PipeUtilization.csv (headlines.pipe_utilization.artifacts.observations.value; record=26; column=6; field=aic_cube_ratio; statistic=ratio; unit=ratio; metric=aic_cube_ratio)`
  - `baseline: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/PipeUtilization.csv (headlines.pipe_utilization.artifacts.observations.value; record=20; column=8; field=aic_scalar_ratio; statistic=ratio; unit=ratio; metric=aic_scalar_ratio)`
  - `baseline: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/PipeUtilization.csv (headlines.pipe_utilization.artifacts.observations.value; record=32; column=10; field=aic_mte1_ratio; statistic=ratio; unit=ratio; metric=aic_mte1_ratio)`
  - `baseline: pipe_arithmetic raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/PipeUtilization.csv (artifacts[11])`
  - `baseline: pipe_arithmetic raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/ArithmeticUtilization.csv (artifacts[5])`
  - `candidate: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/PipeUtilization.csv (headlines.pipe_utilization.artifacts.observations.value; record=32; column=6; field=aic_cube_ratio; statistic=ratio; unit=ratio; metric=aic_cube_ratio)`
  - `candidate: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/PipeUtilization.csv (headlines.pipe_utilization.artifacts.observations.value; record=20; column=8; field=aic_scalar_ratio; statistic=ratio; unit=ratio; metric=aic_scalar_ratio)`
  - `candidate: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/PipeUtilization.csv (headlines.pipe_utilization.artifacts.observations.value; record=14; column=10; field=aic_mte1_ratio; statistic=ratio; unit=ratio; metric=aic_mte1_ratio)`
  - `candidate: pipe_arithmetic raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/PipeUtilization.csv (artifacts[11])`
  - `candidate: pipe_arithmetic raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/ArithmeticUtilization.csv (artifacts[5])`
- Blocked by:
  - profiler.segment.followup:collect_default_metric_followup.output mismatch
  - profiler.segment.followup:collect_default_metric_followup.command missing

### opbasic_workload

- Question: Which operator launch metadata and workload context are recorded?
- Available evidence:
  - `baseline: work distribution summary signal: reports/app/PROF_000001_20260606121223051_GECRNPRPFIQLEHLA/mindstudio_profiler_output/task_time_20260606121251.csv (headlines.task_time.artifacts.observations.value; record=3; column=6; field=task_time(us); statistic=duration; unit=us; metric=task_time)`
  - `baseline: work distribution summary signal: reports/app/PROF_000001_20260606121223051_GECRNPRPFIQLEHLA/mindstudio_profiler_output/task_time_20260606121251.csv (headlines.task_time.artifacts.observations.value; record=5; column=6; field=task_time(us); statistic=duration; unit=us; metric=task_time)`
  - `baseline: work distribution summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/OpBasicInfo.csv (headlines.op_basic_info.artifacts.observations.value; record=2; column=3; field=Task Duration(us); statistic=duration; unit=us; metric=Task Duration(us))`
  - `baseline: work distribution raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/OpBasicInfo.csv (raw_artifact_index.artifacts[group=op_basic_info])`
  - `baseline: work distribution raw artifact: reports/op/OPPROF_20260606121252_MCHGUDCSIZSRIMGO/OpBasicInfo.csv (raw_artifact_index.artifacts[group=op_basic_info])`
  - `candidate: work distribution summary signal: reports/app/PROF_000001_20260606121448940_RGBHHJGBAJGRQEOB/mindstudio_profiler_output/task_time_20260606121516.csv (headlines.task_time.artifacts.observations.value; record=3; column=6; field=task_time(us); statistic=duration; unit=us; metric=task_time)`
  - `candidate: work distribution summary signal: reports/app/PROF_000001_20260606121448940_RGBHHJGBAJGRQEOB/mindstudio_profiler_output/task_time_20260606121516.csv (headlines.task_time.artifacts.observations.value; record=5; column=6; field=task_time(us); statistic=duration; unit=us; metric=task_time)`
  - `candidate: work distribution summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/OpBasicInfo.csv (headlines.op_basic_info.artifacts.observations.value; record=2; column=3; field=Task Duration(us); statistic=duration; unit=us; metric=Task Duration(us))`
  - `candidate: work distribution raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/OpBasicInfo.csv (raw_artifact_index.artifacts[group=op_basic_info])`
  - `candidate: work distribution raw artifact: reports/op/OPPROF_20260606121518_VFKVEPMXTKCMIAHS/OpBasicInfo.csv (raw_artifact_index.artifacts[group=op_basic_info])`
- Blocked by:
  - profiler.segment.followup:collect_default_metric_followup.output mismatch
  - profiler.segment.followup:collect_default_metric_followup.command missing
  - profiler.segment.op.command missing

### generated_context

- Question: Which generated source and simulator context can be associated with the on-device evidence?
- Available evidence:
  - `baseline: generated TileLang source context: analysis/tilelang_context.json (jit_debug)`
  - `baseline: on-device evidence required before source inspection: analysis/raw_artifact_index.json (artifacts[status=parsed])`
  - `candidate: generated TileLang source context: analysis/tilelang_context.json (jit_debug)`
  - `candidate: on-device evidence required before source inspection: analysis/raw_artifact_index.json (artifacts[status=parsed])`

### Pending Collection Actions


- Metric observations describe the recorded scope; they do not establish a bottleneck or cause of speedup. Question status describes evidence availability, not experiment readiness.

## Inspection Targets


## Warnings
