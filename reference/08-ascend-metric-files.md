# Ascend Metric File Index

This skill uses a file-to-question index rather than a fixed metric-name list.
CANN output schemas vary by release.

| Question | Primary Files |
|---|---|
| Which operator dominates? | `op_summary_*.csv`, `op_statistic_*.csv` |
| Which task dominates? | `task_time_*.csv` |
| Is host/runtime overhead relevant? | `api_statistic_*.csv`, `msprof_*.json` |
| Which AI Core pipe is hot? | `PipeUtilization.csv` |
| Is arithmetic utilization low? | `ArithmeticUtilization.csv` |
| Is memory movement limiting? | `Memory.csv`, `MemoryL0.csv`, `MemoryUB.csv` |
| Are conflicts significant? | `ResourceConflictRatio.csv` |
| Which source line is hot? | `core*_code_exe.csv` |
| Which instruction is hot? | `core*_instr_exe.csv` |
| Is copy/compute overlap poor? | `trace.json` |

When a helper cannot recognize a column, inspect the raw CSV first. Update
helper alias lists such as `DURATION_ALIASES`, `NAME_ALIASES`, or
`UTIL_ALIASES` in `helpers/analyze_msprof_outputs.py` only when the new field
spelling is backed by an official source or a controlled fixture.
