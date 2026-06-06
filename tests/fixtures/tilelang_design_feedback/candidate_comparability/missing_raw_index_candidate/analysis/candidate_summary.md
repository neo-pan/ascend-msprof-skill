# TileLang Candidate Summary

- Candidate: `tilelang-controlled-tile-shape-20260605` (<abs-path>/tilelang-controlled-tile-shape-20260605)
- Schema: `1.0`
- Verdict: `reject`
- Policy: `baseline_v1`

## Verdict Reasons

- candidate mean runtime regresses by 4.50502%

## Workload And Runtime

| Field | Value |
|---|---|
| Workload id | `tilelang-ascend/svd/v1/official-256x32x32-fp32-cases3` |
| Shape | `[256,32,32]` |
| Dtype | `float32` |
| Case count | `3` |
| Mean runtime ms | 87.4194 |
| Correctness passed | `True` |
| Compiled | `True` |

## Profiler Evidence

- Evidence present: `True`
- Parsed raw artifacts: 15
- Pending collection actions: 0

## Inspection Targets

| Source | ID | Rank | Evidence |
|---|---|---:|---|
| `optimization_directions` | `inspect_pipe_arithmetic_mix` | `1` | `ev_01_opsummary_taskdurationus, ev_02_pipeutilization_aivscalarratio, ev_03_arithmeticutilization_aiccuberatio` |
| `optimization_directions` | `inspect_memory_movement` | `2` | `ev_01_opsummary_taskdurationus, ev_02_pipeutilization_aivscalarratio, ev_03_memory_l1togmbwusagerateestimate, ev_04_l2cache_aictotalhitrate` |
| `optimization_directions` | `inspect_resource_conflict` | `3` | `ev_01_opsummary_taskdurationus, ev_02_resourceconflict_aiccubewaitratio, ev_03_pipeutilization_aivscalarratio, ev_04_arithmeticutilization_aiccuberatio` |

## Baseline Comparison

- Baseline: `tilelang-controlled-baseline-20260605` (<abs-path>/tilelang-controlled-baseline-20260605)
- Can compare: `True`
- Baseline mean ms: 83.6509
- Candidate mean ms: 87.4194
- Candidate speedup pct: -4.50502

## Warnings

No candidate summary warnings.
