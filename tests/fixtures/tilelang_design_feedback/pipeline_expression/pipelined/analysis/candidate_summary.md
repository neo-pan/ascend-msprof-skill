# Ascend Candidate Summary

Schema: `2.0`.

- baseline: `serial` (<abs-path>/serial)
- candidate: `pipelined` (<abs-path>/pipelined)

## Performance Assessment

Eligibility: `incomplete`; comparison: `not_comparable`.

| Measurement | Value ms | Statistic | Samples | Source |
|---|---:|---|---:|---|
| baseline | n/a | n/a | n/a |  |
| candidate | n/a | n/a | n/a |  |

No comparative performance delta is available.
- `baseline.assessment`: benchmark_context_missing; baseline `n/a`, candidate `n/a`; `baseline: analysis/benchmark_context.json (assessment)`
- `candidate.assessment`: benchmark_context_missing; baseline `n/a`, candidate `n/a`; `candidate: analysis/benchmark_context.json (assessment)`

- Caller-provided records establish declared conditions, not the scientific validity of the measurement method.
- Only point estimates are evaluated; uncertainty, raw sample statistics and practical significance are not assessed.

## Mechanism Assessment

Coverage: `partial`.

| Group | Status | Field A | Field B | Baseline | Candidate | Delta | Delta % | Sources / gaps |
|---|---|---|---|---:|---:|---:|---:|---|
| op_summary | not_comparable | n/a | n/a | 92.6 | 96.16 | n/a | n/a | reports/app/PROF_000001_20260606121223051_GECRNPRPFIQLEHLA/mindstudio_profiler_output/op_summary_20260606121251.csv; reports/app/PROF_000001_20260606121448940_RGBHHJGBAJGRQEOB/mindstudio_profiler_output/op_summary_20260606121516.csv; field missing; metric_scope missing; target unverified; target ambiguous |
| op_statistic | not_comparable | n/a | n/a | 92.6 | 96.16 | n/a | n/a | reports/app/PROF_000001_20260606121223051_GECRNPRPFIQLEHLA/mindstudio_profiler_output/op_statistic_20260606121251.csv; reports/app/PROF_000001_20260606121448940_RGBHHJGBAJGRQEOB/mindstudio_profiler_output/op_statistic_20260606121516.csv; field missing; metric_scope missing; target unverified; target ambiguous |
| task_time | not_comparable | n/a | n/a | 95.24 | 98.4 | n/a | n/a | reports/app/PROF_000001_20260606121223051_GECRNPRPFIQLEHLA/mindstudio_profiler_output/task_time_20260606121251.csv; reports/app/PROF_000001_20260606121448940_RGBHHJGBAJGRQEOB/mindstudio_profiler_output/task_time_20260606121516.csv; field missing; metric_scope missing; target unverified; target ambiguous |
| api_statistic | not_comparable | n/a | n/a | 3096.0 | 9084.14 | n/a | n/a | reports/app/PROF_000001_20260606121223051_GECRNPRPFIQLEHLA/mindstudio_profiler_output/api_statistic_20260606121251.csv; reports/app/PROF_000001_20260606121448940_RGBHHJGBAJGRQEOB/mindstudio_profiler_output/api_statistic_20260606121516.csv; field missing; name mismatch; metric_scope missing; target unverified; target ambiguous |
| op_basic_info | not_comparable | Task Duration(us) | Task Duration(us) | 52.48 | 52.860001 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/OpBasicInfo.csv (Task Duration(us)); reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/OpBasicInfo.csv (Task Duration(us)); profiler.segment.followup:collect_default_metric_followup.output mismatch; profiler.segment.followup:collect_default_metric_followup.command missing; target unverified; target ambiguous |
| pipe_utilization | not_comparable | aic_mte2_ratio | aic_mte2_ratio | 0.266143 | 0.284904 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/PipeUtilization.csv (aic_mte2_ratio); reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/PipeUtilization.csv (aic_mte2_ratio); profiler.segment.followup:collect_default_metric_followup.output mismatch; profiler.segment.followup:collect_default_metric_followup.command missing; block_scope mismatch; target unverified; target ambiguous |
| arithmetic_utilization | not_comparable | aic_cube_ratio | aic_cube_ratio | 0.105385 | 0.104605 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/ArithmeticUtilization.csv (aic_cube_ratio); reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/ArithmeticUtilization.csv (aic_cube_ratio); profiler.segment.followup:collect_default_metric_followup.output mismatch; profiler.segment.followup:collect_default_metric_followup.command missing; block_scope mismatch; target unverified; target ambiguous |
| l2_cache | not_comparable | aic_total_hit_rate(%) | aic_total_hit_rate(%) | 97.960808 | 97.960808 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/L2Cache.csv (aic_total_hit_rate(%)); reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/L2Cache.csv (aic_total_hit_rate(%)); profiler.segment.followup:collect_default_metric_followup.output mismatch; profiler.segment.followup:collect_default_metric_followup.command missing; block_scope mismatch; target unverified; target ambiguous |
| memory | not_comparable | GM_to_L1_bw_usage_rate(%) | GM_to_L1_bw_usage_rate(%) | 5.286443 | 5.24844 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/Memory.csv (GM_to_L1_bw_usage_rate(%)); reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/Memory.csv (GM_to_L1_bw_usage_rate(%)); profiler.segment.followup:collect_default_metric_followup.output mismatch; profiler.segment.followup:collect_default_metric_followup.command missing; target unverified; target ambiguous |
| resource_conflict | not_comparable | aic_mte2_wait_ratio | aic_mte2_wait_ratio | 0.162244 | 0.162543 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/ResourceConflictRatio.csv (aic_mte2_wait_ratio); reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/ResourceConflictRatio.csv (aic_mte2_wait_ratio); profiler.segment.followup:collect_default_metric_followup.output mismatch; profiler.segment.followup:collect_default_metric_followup.command missing; block_scope mismatch; target unverified; target ambiguous |

### Profiler Compatibility

- `cann_version`: `match`; A `{'value': '8.3.0.2.220:8.3.RC2', 'source': {'artifact': 'logs/cann_version.cfg', 'field': 'toolkit_running_version'}}`, B `{'value': '8.3.0.2.220:8.3.RC2', 'source': {'artifact': 'logs/cann_version.cfg', 'field': 'toolkit_running_version'}}`.
- `hardware_summary`: `match`; A `{'value': '4 x 910B2; health OK', 'source': {'artifact': 'logs/npu_smi_info.stdout', 'field': 'NPU/Name/Health'}}`, B `{'value': '4 x 910B2; health OK', 'source': {'artifact': 'logs/npu_smi_info.stdout', 'field': 'NPU/Name/Health'}}`.
- `profile_command`: `match`; A `{'value': 'env ASCEND_RT_VISIBLE_DEVICES=0 ACL_OP_INIT_MODE=1 TL_ASCEND_DEBUG_INFO=1 TMPDIR=<abs-path> PYTHONPATH=<abs-path>:<abs-path>:<abs-path> PATH=<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path> msprof --output=reports/app --application=<abs-path> --runtime-api=on --task-time=on --ai-core=on --aic-metrics=PipeUtilization --type=text --summary-format=csv', 'source': {'artifact': 'logs/command_msprof.txt', 'field': 'command'}}`, B `{'value': 'env ASCEND_RT_VISIBLE_DEVICES=0 ACL_OP_INIT_MODE=1 TL_ASCEND_DEBUG_INFO=1 TMPDIR=<abs-path> PYTHONPATH=<abs-path>:<abs-path>:<abs-path> PATH=<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path>:<abs-path> msprof --output=reports/app --application=<abs-path> --runtime-api=on --task-time=on --ai-core=on --aic-metrics=PipeUtilization --type=text --summary-format=csv', 'source': {'artifact': 'logs/command_msprof.txt', 'field': 'command'}}`.
- `metric_scope`: `match`; A `{'value': 'PipeUtilization', 'source': {'artifact': 'logs/command_msprof_op.txt', 'field': '--aic-metrics'}}`, B `{'value': 'PipeUtilization', 'source': {'artifact': 'logs/command_msprof_op.txt', 'field': '--aic-metrics'}}`.
- `profile_output_segments`: `mismatch`; A `{'value': {'app': {'output': {'source': {'artifact': 'logs/command_msprof.txt', 'field': '--output'}, 'value': 'reports/app'}, 'resolved_output': {'source': {'artifact': 'logs/command_msprof.stdout', 'field': 'Data is saved in'}, 'value': 'reports/app/PROF_<sanitized>'}}, 'followups': {'collect_default_metric_followup': {'output': {'source': {'artifact': 'logs/command_msprof_followup_collect_default_metric_followup.txt', 'field': '--output'}, 'value': 'reports/followups/collect_default_metric_followup'}, 'resolved_output': {'source': {'artifact': 'reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR', 'field': 'existing_report_dir'}, 'value': 'reports/followups/collect_default_metric_followup/OPPROF_<sanitized>'}}}, 'op': {'output': {'source': {'artifact': 'logs/command_msprof_op.txt', 'field': '--output'}, 'value': 'reports/op'}}}, 'source': {'artifact': 'analysis/provenance.json', 'field': 'profile_output_segments'}}`, B `{'value': {'app': {'output': {'source': {'artifact': 'logs/command_msprof.txt', 'field': '--output'}, 'value': 'reports/app'}, 'resolved_output': {'source': {'artifact': 'logs/command_msprof.stdout', 'field': 'Data is saved in'}, 'value': 'reports/app/PROF_<sanitized>'}}, 'followups': {'collect_default_metric_followup': {'output': {'source': {'artifact': 'logs/command_msprof_followup_collect_default_metric_followup.txt', 'field': '--output'}, 'value': 'reports/followups/collect_default_metric_followup'}, 'resolved_output': {'source': {'artifact': 'reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX', 'field': 'existing_report_dir'}, 'value': 'reports/followups/collect_default_metric_followup/OPPROF_<sanitized>'}}}, 'op': {'output': {'source': {'artifact': 'logs/command_msprof_op.txt', 'field': '--output'}, 'value': 'reports/op'}}}, 'source': {'artifact': 'analysis/provenance.json', 'field': 'profile_output_segments'}}`.
- `workload.id`: `match`; A `tilelang-ascend/matmul_add/v1/controlled-1024x1024x1024-float16`, B `tilelang-ascend/matmul_add/v1/controlled-1024x1024x1024-float16`.
- `workload.shape`: `match`; A `[1024, 1024, 1024]`, B `[1024, 1024, 1024]`.
- `workload.dtype`: `match`; A `float16`, B `float16`.
- `workload.case_count`: `match`; A `1`, B `1`.
- baseline benchmark association: `missing`.
  Benchmark and profiler observations cannot explain the same performance change without a matching recorded implementation and workload.
- candidate benchmark association: `missing`.
  Benchmark and profiler observations cannot explain the same performance change without a matching recorded implementation and workload.

## Design Feedback

Status: `partial`

| Question ID | Family | Question | Available Evidence | Missing Evidence | Blockers |
|---|---|---|---:|---:|---|
| `memory_cache` | `memory_cache` | Which memory movement or cache fields support the next inspection? | 14 | 0 | profiler.segment.followup:collect_default_metric_followup.output mismatch, profiler.segment.followup:collect_default_metric_followup.command missing |
| `pipe_arithmetic` | `pipe_arithmetic` | Which Cube, Vector, Scalar or MTE fields support the next inspection? | 10 | 0 | profiler.segment.followup:collect_default_metric_followup.output mismatch, profiler.segment.followup:collect_default_metric_followup.command missing |
| `opbasic_workload` | `opbasic_workload` | Should the next inspection compare work distribution and launch shape context against the intended TileLang design variable? | 18 | 0 | profiler.segment.followup:collect_default_metric_followup.output mismatch, profiler.segment.followup:collect_default_metric_followup.command missing, profiler.segment.op.command missing |
| `generated_context` | `generated_context` | Can the generated TileLang context guide source inspection after on-device evidence is available? | 4 | 0 | none |

### memory_cache

- Question: Which memory movement or cache fields support the next inspection?
- Related design variables: `memory_movement, cache_context, metric_scope`
- Available evidence:
  - `baseline: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/Memory.csv (headlines.memory.value; headlines.memory.raw_row.GM_to_L1_bw_usage_rate(%); headlines.memory.field=GM_to_L1_bw_usage_rate(%); headlines.memory.field_kind=memory_usage_rate)`
  - `baseline: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/L2Cache.csv (headlines.l2_cache.value; headlines.l2_cache.raw_row.aic_total_hit_rate(%); headlines.l2_cache.field=aic_total_hit_rate(%); headlines.l2_cache.field_kind=l2_cache_hit_rate)`
  - `baseline: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/L2Cache.csv (headlines.l2_cache)`
  - `baseline: memory_cache raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/Memory.csv (artifacts[7])`
  - `baseline: memory_cache raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/MemoryL0.csv (artifacts[8])`
  - `candidate: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/Memory.csv (headlines.memory.value; headlines.memory.raw_row.GM_to_L1_bw_usage_rate(%); headlines.memory.field=GM_to_L1_bw_usage_rate(%); headlines.memory.field_kind=memory_usage_rate)`
  - `candidate: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/L2Cache.csv (headlines.l2_cache.value; headlines.l2_cache.raw_row.aic_total_hit_rate(%); headlines.l2_cache.field=aic_total_hit_rate(%); headlines.l2_cache.field_kind=l2_cache_hit_rate)`
  - `candidate: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/L2Cache.csv (headlines.l2_cache)`
  - `candidate: memory_cache raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/Memory.csv (artifacts[7])`
  - `candidate: memory_cache raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/MemoryL0.csv (artifacts[8])`
- Blocked by:
  - profiler.segment.followup:collect_default_metric_followup.output mismatch
  - profiler.segment.followup:collect_default_metric_followup.command missing
- Next experiment: Collect the missing Default family artifacts for the stated target and workload.

### pipe_arithmetic

- Question: Which Cube, Vector, Scalar or MTE fields support the next inspection?
- Related design variables: `pipe_mix, arithmetic_mix`
- Available evidence:
  - `baseline: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/PipeUtilization.csv (headlines.pipe_utilization.value; headlines.pipe_utilization.raw_row.aic_mte2_ratio; headlines.pipe_utilization.field=aic_mte2_ratio; headlines.pipe_utilization.field_kind=utilization_or_ratio)`
  - `baseline: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/ArithmeticUtilization.csv (headlines.arithmetic_utilization.value; headlines.arithmetic_utilization.raw_row.aic_cube_ratio; headlines.arithmetic_utilization.field=aic_cube_ratio; headlines.arithmetic_utilization.field_kind=utilization_or_ratio)`
  - `baseline: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/ArithmeticUtilization.csv (headlines.arithmetic_utilization)`
  - `baseline: pipe_arithmetic raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/PipeUtilization.csv (artifacts[11])`
  - `baseline: pipe_arithmetic raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/ArithmeticUtilization.csv (artifacts[5])`
  - `candidate: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/PipeUtilization.csv (headlines.pipe_utilization.value; headlines.pipe_utilization.raw_row.aic_mte2_ratio; headlines.pipe_utilization.field=aic_mte2_ratio; headlines.pipe_utilization.field_kind=utilization_or_ratio)`
  - `candidate: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/ArithmeticUtilization.csv (headlines.arithmetic_utilization.value; headlines.arithmetic_utilization.raw_row.aic_cube_ratio; headlines.arithmetic_utilization.field=aic_cube_ratio; headlines.arithmetic_utilization.field_kind=utilization_or_ratio)`
  - `candidate: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/ArithmeticUtilization.csv (headlines.arithmetic_utilization)`
  - `candidate: pipe_arithmetic raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/PipeUtilization.csv (artifacts[11])`
  - `candidate: pipe_arithmetic raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/ArithmeticUtilization.csv (artifacts[5])`
- Blocked by:
  - profiler.segment.followup:collect_default_metric_followup.output mismatch
  - profiler.segment.followup:collect_default_metric_followup.command missing
- Next experiment: Collect matching pipe and arithmetic artifacts for the stated target and workload.

### opbasic_workload

- Question: Should the next inspection compare work distribution and launch shape context against the intended TileLang design variable?
- Related design variables: `work_distribution, block_dim, shape_specialization, tail_work`
- Available evidence:
  - `baseline: work distribution summary signal: reports/app/PROF_000001_20260606121223051_GECRNPRPFIQLEHLA/mindstudio_profiler_output/task_time_20260606121251.csv (headlines.task_time.value; headlines.task_time.raw_row.task_time(us); headlines.task_time.field_kind=duration_or_time)`
  - `baseline: work distribution summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/OpBasicInfo.csv (headlines.op_basic_info.value; headlines.op_basic_info.first_row.Task Duration(us); headlines.op_basic_info.field=Task Duration(us); headlines.op_basic_info.field_kind=basic_info)`
  - `baseline: work distribution summary signal: reports/app/PROF_000001_20260606121223051_GECRNPRPFIQLEHLA/mindstudio_profiler_output/task_time_20260606121251.csv (headlines.task_time.value; headlines.task_time.raw_row.task_time(us); headlines.task_time.field_kind=duration_or_time)`
  - `baseline: work distribution raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR/OpBasicInfo.csv (raw_artifact_index.artifacts[group=op_basic_info])`
  - `baseline: work distribution raw artifact: reports/op/OPPROF_20260606121252_MCHGUDCSIZSRIMGO/OpBasicInfo.csv (raw_artifact_index.artifacts[group=op_basic_info])`
  - `candidate: work distribution summary signal: reports/app/PROF_000001_20260606121448940_RGBHHJGBAJGRQEOB/mindstudio_profiler_output/task_time_20260606121516.csv (headlines.task_time.value; headlines.task_time.raw_row.task_time(us); headlines.task_time.field_kind=duration_or_time)`
  - `candidate: work distribution summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/OpBasicInfo.csv (headlines.op_basic_info.value; headlines.op_basic_info.first_row.Task Duration(us); headlines.op_basic_info.field=Task Duration(us); headlines.op_basic_info.field_kind=basic_info)`
  - `candidate: work distribution summary signal: reports/app/PROF_000001_20260606121448940_RGBHHJGBAJGRQEOB/mindstudio_profiler_output/task_time_20260606121516.csv (headlines.task_time.value; headlines.task_time.raw_row.task_time(us); headlines.task_time.field_kind=duration_or_time)`
  - `candidate: work distribution raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX/OpBasicInfo.csv (raw_artifact_index.artifacts[group=op_basic_info])`
  - `candidate: work distribution raw artifact: reports/op/OPPROF_20260606121518_VFKVEPMXTKCMIAHS/OpBasicInfo.csv (raw_artifact_index.artifacts[group=op_basic_info])`
- Blocked by:
  - profiler.segment.followup:collect_default_metric_followup.output mismatch
  - profiler.segment.followup:collect_default_metric_followup.command missing
  - profiler.segment.op.command missing
- Next experiment: Collect OpBasicInfo.csv with matching TileLang workload context, then compare block/work-distribution fields against the intended design variable.

### generated_context

- Question: Can the generated TileLang context guide source inspection after on-device evidence is available?
- Related design variables: `generated_source_context, jit_configuration, source_inspection_context`
- Available evidence:
  - `baseline: generated TileLang source context: analysis/tilelang_context.json (jit_debug)`
  - `baseline: on-device evidence required before source inspection: analysis/raw_artifact_index.json (artifacts[status=parsed])`
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
