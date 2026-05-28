# Analysis Dimensions

## 1. Duration And Call Count

Find dominant operators and tasks from `op_summary_*.csv`,
`op_statistic_*.csv`, and `task_time_*.csv`.

## 2. Pipe Utilization

Read `PipeUtilization.csv`. Decide whether Cube, Vector, Scalar/control, or
MTE/DataCopy limits the workload.

## 3. Memory Movement

Read `Memory.csv`, `MemoryL0.csv`, and `MemoryUB.csv`. Check whether GM/UB/L0
traffic explains elapsed time or pipe starvation.

## 4. Conflicts

Read `ResourceConflictRatio.csv`. High conflict ratios can indicate UB bank
conflicts, resource contention, or queue/pipeline pressure.

## 5. Tiling And Core Balance

Use `OpBasicInfo.csv`, simulator per-core files, and workload shape. Check
blockDim, per-core work, tail blocks, and variable-shape imbalance.

## 6. Simulator Hotspots

Use `core*_code_exe.csv`, `core*_instr_exe.csv`, and `trace.json` to identify
source lines, instructions, and pipeline regions that dominate execution.

