# Analysis Dimensions

## 1. Duration And Call Count

Find dominant operators and tasks from `op_summary_*.csv`,
`op_statistic_*.csv`, and `task_time_*.csv`. Use `msprof_*.json` as
application timeline context for host/runtime and stream timing, but
corroborate it with CSV or simulator evidence before making bottleneck or
overlap claims.

## 2. Pipe Utilization

Read `PipeUtilization.csv`. Decide whether Cube, Vector, Scalar/control, or
MTE/DataCopy limits the workload.

## 3. Memory Movement

Read `Memory.csv`, `MemoryL0.csv`, and `MemoryUB.csv`. Check whether GM/UB/L0
traffic explains elapsed time or pipe starvation.

## 4. Conflicts

Read `ResourceConflictRatio.csv`. High conflict ratios are on-device
investigation signals for possible UB bank conflicts, resource contention, or
queue/pipeline pressure. Corroborate them with timing, pipe, memory, or
simulator evidence before turning them into a diagnosis.

## 5. Tiling And Core Balance

Use `OpBasicInfo.csv`, simulator per-core files, and workload shape. Check
blockDim, per-core work, tail blocks, and variable-shape imbalance.
`OpBasicInfo.csv` is launch and operator metadata; corroborate `Block Dim`
with elapsed time, per-core simulator files, or workload shape before making a
core-balance diagnosis.

## 6. Simulator Hotspots

Use `core*_code_exe.csv`, `core*_instr_exe.csv`, and `trace.json` as
simulator context for source-line, instruction, and pipeline inspection. The
sanitized CANN `8.3.0.2.220:8.3.RC2` fixture
`tests/fixtures/real_simulator_minimal/reports/OPPROF_001/simulator/trace.json`
shows explicit-duration pipeline events through `traceEvents[].ph`,
`traceEvents[].dur`, and `traceEvents[].tid`, plus flow categories through
`traceEvents[].cat`. Treat this as simulator evidence only; pair it with
on-device elapsed-time or pipe/memory CSV evidence before making a diagnosis.
