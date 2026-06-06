# TileLang Candidate Summary

- Candidate: `tilelang-controlled-matmul-add-serial-20260606` (<abs-path>/tilelang-controlled-matmul-add-serial-20260606)
- Schema: `1.0`
- Verdict: `keep`
- Policy: `single_run_v1`

## Verdict Reasons

- correctness passed, runtime is present, profiler evidence is present, and no required collection action is pending

## Workload And Runtime

| Field | Value |
|---|---|
| Workload id | `tilelang-ascend/matmul_add/v1/controlled-1024x1024x1024-float16` |
| Shape | `[1024,1024,1024]` |
| Dtype | `float16` |
| Case count | `1` |
| Mean runtime ms | 0.405888 |
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

## Warnings

No candidate summary warnings.
