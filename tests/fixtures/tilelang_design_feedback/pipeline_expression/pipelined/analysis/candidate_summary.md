# TileLang Candidate Summary

- Candidate: `tilelang-controlled-matmul-add-pipelined-20260606` (<abs-path>/tilelang-controlled-matmul-add-pipelined-20260606)
- Schema: `1.0`
- Verdict: `promote`
- Policy: `baseline_v1`

## Verdict Reasons

- candidate mean runtime improves by 4.89058%

## Workload And Runtime

| Field | Value |
|---|---|
| Workload id | `tilelang-ascend/matmul_add/v1/controlled-1024x1024x1024-float16` |
| Shape | `[1024,1024,1024]` |
| Dtype | `float16` |
| Case count | `1` |
| Mean runtime ms | 0.386038 |
| Correctness passed | `True` |
| Compiled | `True` |

## Profiler Evidence

- Evidence present: `True`
- Parsed raw artifacts: 15
- Pending collection actions: 0

## Inspection Targets

| Source | ID | Rank | Evidence |
|---|---|---:|---|
| `optimization_directions` | `inspect_pipe_arithmetic_mix` | `1` | `ev_01_opsummary_taskdurationus, ev_02_pipeutilization_aicmte2ratio, ev_03_arithmeticutilization_aiccuberatio` |
| `optimization_directions` | `inspect_memory_movement` | `2` | `ev_01_opsummary_taskdurationus, ev_02_pipeutilization_aicmte2ratio, ev_03_memory_gmtol1bwusagerate, ev_04_l2cache_aictotalhitrate` |
| `optimization_directions` | `inspect_resource_conflict` | `3` | `ev_01_opsummary_taskdurationus, ev_02_resourceconflict_aicmte2waitratio, ev_03_pipeutilization_aicmte2ratio, ev_04_arithmeticutilization_aiccuberatio` |

## Baseline Comparison

- Baseline: `tilelang-controlled-matmul-add-serial-20260606` (<abs-path>/tilelang-controlled-matmul-add-serial-20260606)
- Can compare: `True`
- Baseline mean ms: 0.405888
- Candidate mean ms: 0.386038
- Candidate speedup pct: 4.89058

## Warnings

No candidate summary warnings.
