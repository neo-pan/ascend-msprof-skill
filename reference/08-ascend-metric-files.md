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
| What simulator synchronization event context was observed with ResourceConflictRatio enabled? | Sanitized fixture `tests/fixtures/real_resourceconflict_simulator_minimal/reports/OPPROF_001/simulator/trace.json` uppercase `SET_FLAG` / `WAIT_FLAG` B/E events and paired per-core `core*_instr_exe.csv` rows with `instr`, `call_count`, `cycles`, and `running_time(us)` |
| What PMSampling MTE throughput context was observed? | Sanitized fixture `tests/fixtures/real_pmsampling_simulator_minimal/reports/OPPROF_001/simulator/trace.json` counter events where `traceEvents[].pid` is `MTE Throughput`, `traceEvents[].ph` is `C`, `traceEvents[].name` is one of `GM_TO_L1`, `GM_TO_TOTAL`, `GM_TO_UB`, `L1_TO_GM`, `TOTAL_TO_GM`, `UB_TO_GM`, and `traceEvents[].args["throughput(MB/s)"]` is numeric |

Some metric modes expose useful summary text only in selected profiler stdout.
The analyzer currently copies only fixture-backed stdout sections into
`analysis/summary.json`: `stdout_sections.occupancy_summary` keeps `ordinal`
and raw `message`, while `stdout_sections.roofline_summary` keeps raw
`message`. Treat both as raw evidence, not as metric files or sourced headline
signals.

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

For PMSampling MTE throughput context, the official CANN 8.5 Memory Channel
Throughput Waveform reference names the six memory-channel labels and MB/s
unit. This skill currently extracts only raw, observed counter events from the
aggregate simulator `trace.json` selected by `select_trace_files()`; it does
not parse `visualize_data.bin`, infer a missing waveform, or assign diagnosis,
headline, bottleneck, or optimization semantics to the reported max/average
sample values.

For simulator synchronization event context, the official CANN 8.5 and
release-proximate CANN 8.3 `--aic-metrics` references list
`ResourceConflictRatio` as simulator-visible synchronization event instruction
detail. The local CANN `8.3.0.2.220:8.3.RC2` / Ascend 910B2 evidence gate
observed uppercase `SET_FLAG` and `WAIT_FLAG` events in existing simulator
`trace.json` and per-core `core*_instr_exe.csv` artifacts. This skill reports
only those raw event counts and CSV sums; it does not define or require a
`ResourceConflictRatio.csv` simulator artifact, parse `visualize_data.bin`,
infer a ratio schema, or assign diagnosis, headline, bottleneck, or
optimization semantics.
