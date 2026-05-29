# Output Files

## Application-Level Files

- `op_summary_*.csv`: operator duration, call count, and dominant operators.
  Version note: official MindStudio 7.0.RC1 and CANN 8.3.RC1.alpha001
  `op_summary_*.csv` field tables document `Task Duration(us)`,
  `aicore_time(us)`, `total_cycles`, and exact wildcard fields such as
  `ai*_vec_time(us)`, `ai*_mac_time(us)`, `ai*_scalar_time(us)`,
  `ai*_scalar_ratio`, and `ai*_mte2_time(us)`; the local CANN
  `8.3.0.2.220:8.3.RC2` fixture keeps `aic_total_cycles`, `aic_mac_time(us)`,
  `aic_scalar_time(us)`, `aic_mte1_time(us)`, `aic_mte2_time(us)`,
  `aic_fixpipe_time(us)`, `aiv_total_cycles`, `aiv_vec_time(us)`,
  `aiv_scalar_time(us)`, `aiv_mte2_time(us)`, and `aiv_mte3_time(us)` in
  `reports/PROF_001/mindstudio_profiler_output/op_summary_001.csv`.
- `op_statistic_*.csv`: aggregate operator-type statistics.
- `task_time_*.csv`: device task timing.
- `api_statistic_*.csv`: host/runtime API cost.
- `msprof_*.json`: timeline events for host, runtime, streams, and operators.

## Operator-Level Files

- `OpBasicInfo.csv`: operator identity, shape/config metadata, execution info.
- `PipeUtilization.csv`: Cube, Vector, Scalar, MTE, or equivalent pipe usage.
- `ArithmeticUtilization.csv`: arithmetic utilization summaries.
- `Memory.csv`: memory movement summary.
- `MemoryL0.csv`: L0-related memory metrics.
- `MemoryUB.csv`: UB-related memory metrics.
- `ResourceConflictRatio.csv`: conflict and bank/resource pressure signals.
- `visualize_data.bin`: MindStudio Insight visualization artifact.

## Simulator Files

- `core*_code_exe.csv`: per-core source-line execution attribution.
- `core*_instr_exe.csv`: per-core instruction execution attribution.
- `trace.json`: pipeline/timeline detail.

Treat columns as version-sensitive. Helpers match likely column names and keep
raw records in `summary.json` for inspection.
