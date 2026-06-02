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
and raw `message`, `stdout_sections.roofline_summary` keeps raw `message`,
and `stdout_sections.performance_summary` keeps raw `ordinal`, `message`, and
source path fields. Treat these stdout sections as raw evidence, not as metric
files or sourced headline signals. A generated pipe-utilization advisory may
use `performance_summary` only when timing evidence and `PipeUtilization.csv`
are also present.

When a helper cannot recognize a column, inspect the raw CSV first. Update
helper alias lists such as `DURATION_ALIASES`, `NAME_ALIASES`, or
`UTIL_ALIASES` in `helpers/analyze_msprof_outputs.py` only when the new field
spelling is backed by an official source or a controlled fixture.

For application-level CSVs, use `op_summary_*.csv`, `op_statistic_*.csv`,
`task_time_*.csv`, and `api_statistic_*.csv` as triage and ranking evidence.
Official sources document exact field context for selected versions, but the
local CANN `8.3.0.2.220:8.3.RC2` fixture remains the behavior baseline for
helper/report output. The local fixture preserves `op_statistic_001.csv` fields
such as `OP Type`, `Core Type`, `Count`, `Total Time(us)`, `Avg Time(us)`,
`Min Time(us)`, `Max Time(us)`, and `Ratio(%)`; `task_time_001.csv` fields
such as `kernel_name`, `kernel_type`, `stream_id`, `task_id`,
`task_time(us)`, `task_start(us)`, and `task_stop(us)`; and
`api_statistic_001.csv` fields such as `Level`, `API Name`, `Time(us)`,
`Count`, `Avg(us)`, `Min(us)`, `Max(us)`, and `Variance`. Do not treat a
single application-level CSV headline as a standalone optimization diagnosis.

For application-level `msprof_*.json`, official sources describe the artifact
as a timeline summary opened in Chrome tracing and used for CANN and Ascend
Hardware timing context. The local CANN `8.3.0.2.220:8.3.RC2` fixture
`tests/fixtures/real_cann_minimal/reports/PROF_001/mindstudio_profiler_output/msprof_001.json`
preserves a top-level array of events with fields such as `name`, `pid`,
`tid`, `ts`, `dur`, `ph`, and `args`; the mock fixture preserves an object
wrapper with `traceEvents`. Helper timeline output is limited to
duration-ranked event extraction. Do not infer overlap formulas, host/device
causality, or automatic bottleneck labels from `msprof_*.json` alone.

For `OpBasicInfo.csv`, official sources name operator metadata and launch
context fields such as `Op Name`, `Op Type`, `Task Duration(us)`, `Block Dim`,
`Mix Block Dim`, `Device ID`, `PID`, `Current Freq`, and `Rated Freq`. The
local CANN `8.3.0.2.220:8.3.RC2` fixture preserves the same observed
operator-metadata shape in
`tests/fixtures/real_cann_minimal/reports/OPPROF_001/OpBasicInfo.csv`. Use
this file to identify the profiled operator and launch context before looking
at timing, pipe, memory, conflict, or simulator evidence. Do not infer core
imbalance or optimization direction from `Block Dim` alone.

For `L2Cache.csv`, official CANN 8.0 documentation names the artifact as the
`msprof op` L2 cache hit ratio output. The local CANN
`8.3.0.2.220:8.3.RC2` fixture
`tests/fixtures/real_l2cache_minimal/reports/OPPROF_001/L2Cache.csv`
preserves observed fields such as `block_id`, `sub_block_id`,
`aic_total_hit_rate(%)`, and `aiv_total_hit_rate(%)`; do not treat those fields
as a universal CANN schema without additional evidence.

For `PipeUtilization.csv`, official CANN documentation names time and ratio
fields for Cube, Vector, Scalar, fixpipe, MTE1, MTE2, MTE3, and ICache miss
context, with CANN 8.3 documentation also naming active-bandwidth fields. The
local CANN `8.3.0.2.220:8.3.RC2` fixtures
`tests/fixtures/real_cann_minimal/reports/OPPROF_001/PipeUtilization.csv` and
`tests/fixtures/real_default_vector_minimal/reports/OPPROF_001/PipeUtilization.csv`
preserve the observed `aic_*` / `aiv_*` split shape, including fields such as
`aic_cube_ratio`, `aic_scalar_ratio`, `aic_mte1_ratio`, `aic_mte2_ratio`,
`aic_mte3_ratio`, `aiv_vec_ratio`, `aiv_scalar_ratio`, `aiv_mte2_ratio`, and
`aiv_mte3_ratio`. Treat generated pipe headlines as raw investigation signals,
not automatic bottleneck labels. Do not rank active bandwidth, miss rate, time,
cycles, and ratio fields as one comparable signal, and do not infer an
optimization diagnosis from this file alone.

For `ArithmeticUtilization.csv`, official CANN 8.0 documentation names
fields such as `block_id`, `sub_block_id`, `aic_time(us)`,
`aic_total_cycles`, `aic_cube_ratio`, `aic_cube_fp16_ratio`,
`aic_cube_int8_ratio`, `aic_cube_fops`, `aic_cube_total_instr_number`,
`aic_cube_fp_instr_number`, `aic_cube_int_instr_number`, `aiv_time(us)`,
`aiv_total_cycles`, `aiv_vec_ratio`, `aiv_vec_fp32_ratio`,
`aiv_vec_fp16_ratio`, `aiv_vec_int32_ratio`, `aiv_vec_int16_ratio`,
`aiv_vec_misc_ratio`, and `aiv_vec_fops`. The local CANN
`8.3.0.2.220:8.3.RC2` fixtures
`tests/fixtures/real_cann_minimal/reports/OPPROF_001/ArithmeticUtilization.csv`
and
`tests/fixtures/real_default_vector_minimal/reports/OPPROF_001/ArithmeticUtilization.csv`
preserve that observed `aic_*` / `aiv_*` shape. Treat the generated arithmetic
headline as a raw ratio signal only; do not rank FLOP counts, instruction
counts, cycle counts, or time fields against ratio fields, and do not infer an
optimization diagnosis from this file alone.

For `Memory.csv`, official CANN 8.0 documentation names fields such as
`aic_l1_read_bw(GB/s)`, `aic_l1_write_bw(GB/s)`,
`aic_main_mem_read_bw(GB/s)`, `aic_main_mem_write_bw(GB/s)`,
`aiv_ub_to_gm_bw(GB/s)`, `aiv_gm_to_ub_bw(GB/s)`, MTE instruction-count and
ratio fields, data-volume fields such as `GM_to_UB_datas(KB)`, and bandwidth
usage-rate fields such as `UB_to_GM_bw_usage_rate(%)`. Official CANN 8.0
documentation for `MemoryL0.csv` names L0A/L0B/L0C read/write bandwidth
fields, and `MemoryUB.csv` names UB read/write bandwidth fields for
Vector/Scalar lanes in the documented product family. The local CANN
`8.3.0.2.220:8.3.RC2` fixtures
`tests/fixtures/real_cann_minimal/reports/OPPROF_001/Memory.csv`,
`tests/fixtures/real_cann_minimal/reports/OPPROF_001/MemoryL0.csv`,
`tests/fixtures/real_cann_minimal/reports/OPPROF_001/MemoryUB.csv`, and the
matching `tests/fixtures/real_default_vector_minimal/reports/OPPROF_001/`
Memory-family files preserve the observed local shape. Treat generated memory
headlines as raw investigation signals grouped by compatible unit families:
usage rate, bandwidth, and volume. Do not rank bandwidth, volume, MTE ratios,
cycles, and time as one comparable signal, and do not infer an optimization
diagnosis from a memory headline without corroborating timing, pipe,
arithmetic, conflict, or simulator evidence.

For non-simulator `ResourceConflictRatio.csv`, official MindStudio profiling
field context includes vector conflict-ratio fields such as
`vec_bankgroup_cflt_ratio`, `vec_bank_cflt_ratio`, and
`vec_resc_cflt_ratio`. The local CANN `8.3.0.2.220:8.3.RC2` fixtures
`tests/fixtures/real_cann_minimal/reports/OPPROF_001/ResourceConflictRatio.csv`
and
`tests/fixtures/real_default_vector_minimal/reports/OPPROF_001/ResourceConflictRatio.csv`
preserve observed fields such as `aic_cube_wait_ratio`,
`aic_mte1_wait_ratio`, `aiv_vec_total_cflt_ratio`,
`aiv_vec_bankgroup_cflt_ratio`, `aiv_vec_bank_cflt_ratio`,
`aiv_vec_resc_cflt_ratio`, `aiv_vec_mte_cflt_ratio`,
`aiv_vec_wait_ratio`, and `aiv_mte3_wait_ratio`. Treat these values as
on-device CSV ratio evidence. Do not map them to simulator synchronization
event counts, do not infer a simulator `ResourceConflictRatio.csv` artifact,
and do not make a diagnosis from this file without corroborating timing, pipe,
memory, or simulator evidence.

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
