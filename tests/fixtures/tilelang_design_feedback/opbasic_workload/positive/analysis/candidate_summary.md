# Ascend Candidate Summary

Schema: `2.0`.

- baseline: `baseline` (<abs-path>/baseline)
- candidate: `positive` (<abs-path>/positive)

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
| op_summary | not_comparable | n/a | n/a | 83401.66 | 152720.02 | n/a | n/a | reports/app/PROF_000001_20260605155111872_JDEKRCNERPBNJEGA/mindstudio_profiler_output/op_summary_20260605155140.csv; reports/app/PROF_000001_20260605162026076_IANNQLNPDOAGQGHC/mindstudio_profiler_output/op_summary_20260605162053.csv; field missing; metric_scope missing; target unverified; target ambiguous |
| op_statistic | not_comparable | n/a | n/a | 249604.48 | 457503.84 | n/a | n/a | reports/app/PROF_000001_20260605155111872_JDEKRCNERPBNJEGA/mindstudio_profiler_output/op_statistic_20260605155140.csv; reports/app/PROF_000001_20260605162026076_IANNQLNPDOAGQGHC/mindstudio_profiler_output/op_statistic_20260605162053.csv; field missing; metric_scope missing; target unverified; target ambiguous |
| task_time | not_comparable | n/a | n/a | 83404.54 | 152722.9 | n/a | n/a | reports/app/PROF_000001_20260605155111872_JDEKRCNERPBNJEGA/mindstudio_profiler_output/task_time_20260605155140.csv; reports/app/PROF_000001_20260605162026076_IANNQLNPDOAGQGHC/mindstudio_profiler_output/task_time_20260605162053.csv; field missing; metric_scope missing; target unverified; target ambiguous |
| api_statistic | not_comparable | n/a | n/a | 249503.48 | 457373.77 | n/a | n/a | reports/app/PROF_000001_20260605155111872_JDEKRCNERPBNJEGA/mindstudio_profiler_output/api_statistic_20260605155140.csv; reports/app/PROF_000001_20260605162026076_IANNQLNPDOAGQGHC/mindstudio_profiler_output/api_statistic_20260605162053.csv; field missing; metric_scope missing; target unverified; target ambiguous |
| op_basic_info | not_comparable | Task Duration(us) | Task Duration(us) | 83096.421875 | 152401.3125 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/OpBasicInfo.csv (Task Duration(us)); reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ/OpBasicInfo.csv (Task Duration(us)); profiler.segment.followup:collect_default_metric_followup.output mismatch; profiler.segment.followup:collect_default_metric_followup.command missing; target unverified; target ambiguous |
| pipe_utilization | not_comparable | aiv_scalar_ratio | aiv_scalar_ratio | 0.16759 | 0.09142 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/PipeUtilization.csv (aiv_scalar_ratio); reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ/PipeUtilization.csv (aiv_scalar_ratio); profiler.segment.followup:collect_default_metric_followup.output mismatch; profiler.segment.followup:collect_default_metric_followup.command missing; name mismatch; block_scope mismatch; target unverified; target ambiguous |
| arithmetic_utilization | not_comparable | aiv_vec_ratio | aic_cube_ratio | 1e-06 | 0.0 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/ArithmeticUtilization.csv (aiv_vec_ratio); reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ/ArithmeticUtilization.csv (aic_cube_ratio); profiler.segment.followup:collect_default_metric_followup.output mismatch; profiler.segment.followup:collect_default_metric_followup.command missing; field mismatch; name mismatch; block_scope mismatch; target unverified; target ambiguous |
| l2_cache | not_comparable | aic_total_hit_rate(%) | aic_total_hit_rate(%) | 100.0 | 100.0 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/L2Cache.csv (aic_total_hit_rate(%)); reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ/L2Cache.csv (aic_total_hit_rate(%)); profiler.segment.followup:collect_default_metric_followup.output mismatch; profiler.segment.followup:collect_default_metric_followup.command missing; target unverified; target ambiguous |
| memory | not_comparable | L1_to_GM_bw_usage_rate(%)(estimate) | L1_to_GM_bw_usage_rate(%)(estimate) | 6e-06 | 3e-06 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/Memory.csv (L1_to_GM_bw_usage_rate(%)(estimate)); reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ/Memory.csv (L1_to_GM_bw_usage_rate(%)(estimate)); profiler.segment.followup:collect_default_metric_followup.output mismatch; profiler.segment.followup:collect_default_metric_followup.command missing; target unverified; target ambiguous |
| resource_conflict | not_comparable | aic_cube_wait_ratio | aic_cube_wait_ratio | 0.0 | 0.0 | n/a | n/a | reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/ResourceConflictRatio.csv (aic_cube_wait_ratio); reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ/ResourceConflictRatio.csv (aic_cube_wait_ratio); profiler.segment.followup:collect_default_metric_followup.output mismatch; profiler.segment.followup:collect_default_metric_followup.command missing; target unverified; target ambiguous |

### Profiler Compatibility

- `cann_version`: `match`; A `{'value': '8.3.0.2.220:8.3.RC2', 'source': {'artifact': 'logs/cann_version.cfg', 'field': 'toolkit_running_version'}}`, B `{'value': '8.3.0.2.220:8.3.RC2', 'source': {'artifact': 'logs/cann_version.cfg', 'field': 'toolkit_running_version'}}`.
- `hardware_summary`: `match`; A `{'value': '4 x 910B2; health OK', 'source': {'artifact': 'logs/npu_smi_info.stdout', 'field': 'NPU/Name/Health'}}`, B `{'value': '4 x 910B2; health OK', 'source': {'artifact': 'logs/npu_smi_info.stdout', 'field': 'NPU/Name/Health'}}`.
- `profile_command`: `match`; A `{'value': 'msprof --output=reports/app --application=<abs-path> --runtime-api=on --task-time=on --ai-core=on --aic-metrics=PipeUtilization --type=text --summary-format=csv', 'source': {'artifact': 'logs/command_msprof.txt', 'field': 'command'}}`, B `{'value': 'msprof --output=reports/app --application=<abs-path> --runtime-api=on --task-time=on --ai-core=on --aic-metrics=PipeUtilization --type=text --summary-format=csv', 'source': {'artifact': 'logs/command_msprof.txt', 'field': 'command'}}`.
- `metric_scope`: `match`; A `{'value': 'PipeUtilization', 'source': {'artifact': 'logs/command_msprof_op.txt', 'field': '--aic-metrics'}}`, B `{'value': 'PipeUtilization', 'source': {'artifact': 'logs/command_msprof_op.txt', 'field': '--aic-metrics'}}`.
- `profile_output_segments`: `mismatch`; A `{'value': {'app': {'output': {'source': {'artifact': 'logs/command_msprof.txt', 'field': '--output'}, 'value': 'reports/app'}}, 'followups': {'collect_default_metric_followup': {'output': {'source': {'artifact': 'logs/command_msprof_followup_collect_default_metric_followup.txt', 'field': '--output'}, 'value': 'reports/followups/collect_default_metric_followup'}, 'resolved_output': {'source': {'artifact': 'reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI', 'field': 'existing_report_dir'}, 'value': 'reports/followups/collect_default_metric_followup/OPPROF_<sanitized>'}, 'status': {'source': {'artifact': 'logs/msprof_followup_collect_default_metric_followup.status', 'field': 'exit_status'}, 'value': '0'}}}, 'op': {'output': {'source': {'artifact': 'logs/command_msprof_op.txt', 'field': '--output'}, 'value': 'reports/op'}}}, 'source': {'artifact': 'analysis/provenance.json', 'field': 'profile_output_segments'}}`, B `{'value': {'app': {'output': {'source': {'artifact': 'logs/command_msprof.txt', 'field': '--output'}, 'value': 'reports/app'}}, 'followups': {'collect_default_metric_followup': {'output': {'source': {'artifact': 'logs/command_msprof_followup_collect_default_metric_followup.txt', 'field': '--output'}, 'value': 'reports/followups/collect_default_metric_followup'}, 'resolved_output': {'source': {'artifact': 'reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ', 'field': 'existing_report_dir'}, 'value': 'reports/followups/collect_default_metric_followup/OPPROF_<sanitized>'}, 'status': {'source': {'artifact': 'logs/msprof_followup_collect_default_metric_followup.status', 'field': 'exit_status'}, 'value': '0'}}}, 'op': {'output': {'source': {'artifact': 'logs/command_msprof_op.txt', 'field': '--output'}, 'value': 'reports/op'}}}, 'source': {'artifact': 'analysis/provenance.json', 'field': 'profile_output_segments'}}`.
- `workload.id`: `match`; A `tilelang-ascend/svd/v1/official-256x32x32-fp32-cases3`, B `tilelang-ascend/svd/v1/official-256x32x32-fp32-cases3`.
- `workload.shape`: `match`; A `[256, 32, 32]`, B `[256, 32, 32]`.
- `workload.dtype`: `match`; A `float32`, B `float32`.
- `workload.case_count`: `match`; A `3`, B `3`.
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
  - `baseline: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/Memory.csv (headlines.memory.value; headlines.memory.raw_row.L1_to_GM_bw_usage_rate(%)(estimate); headlines.memory.field=L1_to_GM_bw_usage_rate(%)(estimate); headlines.memory.field_kind=memory_usage_rate)`
  - `baseline: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/L2Cache.csv (headlines.l2_cache.value; headlines.l2_cache.raw_row.aic_total_hit_rate(%); headlines.l2_cache.field=aic_total_hit_rate(%); headlines.l2_cache.field_kind=l2_cache_hit_rate)`
  - `baseline: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/L2Cache.csv (headlines.l2_cache)`
  - `baseline: memory_cache raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/Memory.csv (artifacts[7])`
  - `baseline: memory_cache raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/MemoryL0.csv (artifacts[8])`
  - `candidate: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ/Memory.csv (headlines.memory.value; headlines.memory.raw_row.L1_to_GM_bw_usage_rate(%)(estimate); headlines.memory.field=L1_to_GM_bw_usage_rate(%)(estimate); headlines.memory.field_kind=memory_usage_rate)`
  - `candidate: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ/L2Cache.csv (headlines.l2_cache.value; headlines.l2_cache.raw_row.aic_total_hit_rate(%); headlines.l2_cache.field=aic_total_hit_rate(%); headlines.l2_cache.field_kind=l2_cache_hit_rate)`
  - `candidate: memory_cache summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ/L2Cache.csv (headlines.l2_cache)`
  - `candidate: memory_cache raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ/Memory.csv (artifacts[7])`
  - `candidate: memory_cache raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ/MemoryL0.csv (artifacts[8])`
- Blocked by:
  - profiler.segment.followup:collect_default_metric_followup.output mismatch
  - profiler.segment.followup:collect_default_metric_followup.command missing
- Next experiment: Collect the missing Default family artifacts for the stated target and workload.

### pipe_arithmetic

- Question: Which Cube, Vector, Scalar or MTE fields support the next inspection?
- Related design variables: `pipe_mix, arithmetic_mix`
- Available evidence:
  - `baseline: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/PipeUtilization.csv (headlines.pipe_utilization.value; headlines.pipe_utilization.raw_row.aiv_scalar_ratio; headlines.pipe_utilization.field=aiv_scalar_ratio; headlines.pipe_utilization.field_kind=utilization_or_ratio)`
  - `baseline: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/ArithmeticUtilization.csv (headlines.arithmetic_utilization.value; headlines.arithmetic_utilization.raw_row.aiv_vec_ratio; headlines.arithmetic_utilization.field=aiv_vec_ratio; headlines.arithmetic_utilization.field_kind=utilization_or_ratio)`
  - `baseline: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/ArithmeticUtilization.csv (headlines.arithmetic_utilization)`
  - `baseline: pipe_arithmetic raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/PipeUtilization.csv (artifacts[11])`
  - `baseline: pipe_arithmetic raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/ArithmeticUtilization.csv (artifacts[5])`
  - `candidate: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ/PipeUtilization.csv (headlines.pipe_utilization.value; headlines.pipe_utilization.raw_row.aiv_scalar_ratio; headlines.pipe_utilization.field=aiv_scalar_ratio; headlines.pipe_utilization.field_kind=utilization_or_ratio)`
  - `candidate: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ/ArithmeticUtilization.csv (headlines.arithmetic_utilization.value; headlines.arithmetic_utilization.raw_row.aic_cube_ratio; headlines.arithmetic_utilization.field=aic_cube_ratio; headlines.arithmetic_utilization.field_kind=utilization_or_ratio)`
  - `candidate: pipe_arithmetic summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ/ArithmeticUtilization.csv (headlines.arithmetic_utilization)`
  - `candidate: pipe_arithmetic raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ/PipeUtilization.csv (artifacts[11])`
  - `candidate: pipe_arithmetic raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ/ArithmeticUtilization.csv (artifacts[5])`
- Blocked by:
  - profiler.segment.followup:collect_default_metric_followup.output mismatch
  - profiler.segment.followup:collect_default_metric_followup.command missing
- Next experiment: Collect matching pipe and arithmetic artifacts for the stated target and workload.

### opbasic_workload

- Question: Should the next inspection compare work distribution and launch shape context against the intended TileLang design variable?
- Related design variables: `work_distribution, block_dim, shape_specialization, tail_work`
- Available evidence:
  - `baseline: work distribution summary signal: reports/app/PROF_000001_20260605155111872_JDEKRCNERPBNJEGA/mindstudio_profiler_output/task_time_20260605155140.csv (headlines.task_time.value; headlines.task_time.raw_row.task_time(us); headlines.task_time.field_kind=duration_or_time)`
  - `baseline: work distribution summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/OpBasicInfo.csv (headlines.op_basic_info.value; headlines.op_basic_info.first_row.Task Duration(us); headlines.op_basic_info.field=Task Duration(us); headlines.op_basic_info.field_kind=basic_info)`
  - `baseline: work distribution summary signal: reports/app/PROF_000001_20260605155111872_JDEKRCNERPBNJEGA/mindstudio_profiler_output/task_time_20260605155140.csv (headlines.task_time.value; headlines.task_time.raw_row.task_time(us); headlines.task_time.field_kind=duration_or_time)`
  - `baseline: work distribution raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170714_RYQFPTCBYWBFCNBI/OpBasicInfo.csv (raw_artifact_index.artifacts[group=op_basic_info])`
  - `baseline: work distribution raw artifact: reports/op/OPPROF_20260605155158_TIDPSIUYBGPWXXNW/OpBasicInfo.csv (raw_artifact_index.artifacts[group=op_basic_info])`
  - `candidate: work distribution summary signal: reports/app/PROF_000001_20260605162026076_IANNQLNPDOAGQGHC/mindstudio_profiler_output/task_time_20260605162053.csv (headlines.task_time.value; headlines.task_time.raw_row.task_time(us); headlines.task_time.field_kind=duration_or_time)`
  - `candidate: work distribution summary signal: reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ/OpBasicInfo.csv (headlines.op_basic_info.value; headlines.op_basic_info.first_row.Task Duration(us); headlines.op_basic_info.field=Task Duration(us); headlines.op_basic_info.field_kind=basic_info)`
  - `candidate: work distribution summary signal: reports/app/PROF_000001_20260605162026076_IANNQLNPDOAGQGHC/mindstudio_profiler_output/task_time_20260605162053.csv (headlines.task_time.value; headlines.task_time.raw_row.task_time(us); headlines.task_time.field_kind=duration_or_time)`
  - `candidate: work distribution raw artifact: reports/followups/collect_default_metric_followup/OPPROF_20260605170903_CLWARYOPBOUDLKUZ/OpBasicInfo.csv (raw_artifact_index.artifacts[group=op_basic_info])`
  - `candidate: work distribution raw artifact: reports/op/OPPROF_20260605162103_VFYJVRZACJBSNWAK/OpBasicInfo.csv (raw_artifact_index.artifacts[group=op_basic_info])`
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
