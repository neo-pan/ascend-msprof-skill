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
| What L2 cache hit-rate fields are present? | `L2Cache.csv` |
| Is memory movement limiting? | `Memory.csv`, `MemoryL0.csv`, `MemoryUB.csv` |
| Are conflicts significant? | `ResourceConflictRatio.csv` |
| Which source line is hot? | `core*_code_exe.csv` |
| Which instruction is hot? | `core*_instr_exe.csv` |
| What simulator pipeline context should I inspect? | Sanitized fixture `tests/fixtures/real_simulator_minimal/reports/OPPROF_001/simulator/trace.json` fields `traceEvents[].ph`, `traceEvents[].dur`, `traceEvents[].tid`, flow `traceEvents[].cat`; paired `core*_code_exe.csv` and `core*_instr_exe.csv` |

When a helper cannot recognize a column, inspect the raw CSV first. Update
helper alias lists such as `DURATION_ALIASES`, `NAME_ALIASES`, or
`UTIL_ALIASES` in `helpers/analyze_msprof_outputs.py` only when the new field
spelling is backed by an official source or a controlled fixture.

For `L2Cache.csv`, official CANN 8.0 documentation names the artifact as the
`msprof op` L2 cache hit ratio output. The local CANN
`8.3.0.2.220:8.3.RC2` fixture
`tests/fixtures/real_l2cache_minimal/reports/OPPROF_001/L2Cache.csv`
preserves observed fields such as `block_id`, `sub_block_id`,
`aic_total_hit_rate(%)`, and `aiv_total_hit_rate(%)`; do not treat those fields
as a universal CANN schema without additional evidence.
