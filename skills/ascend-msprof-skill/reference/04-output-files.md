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
- `op_statistic_*.csv`: aggregate operator-type statistics. CANN
  9.0.0-beta.2 documentation names fields such as `Device_id`, `Model Name`,
  `OP Type`, `Core Type`, `Total Time(us)`, `Avg Time(us)`, `Min Time(us)`,
  and `Max Time(us)`; the local CANN `8.3.0.2.220:8.3.RC2` fixture preserves
  the observed application-level aggregate timing shape in
  `reports/PROF_001/mindstudio_profiler_output/op_statistic_001.csv`.
- `task_time_*.csv`: device task timing. Official MindStudio documentation
  describes task scheduling summaries and product/version-specific field
  tables; the local CANN `8.3.0.2.220:8.3.RC2` fixture preserves observed
  fields including `kernel_name`, `kernel_type`, `stream_id`, `task_id`,
  `task_time(us)`, `task_start(us)`, and `task_stop(us)`.
- `api_statistic_*.csv`: host/runtime API cost. CANN 8.2.RC1 documentation
  names fields such as `Device_id`, `Level`, `API Name`, `Time(us)`, `Count`,
  `Avg(us)`, `Min(us)`, `Max(us)`, and `Variance`; treat this as host/runtime
  timing context rather than standalone device bottleneck evidence.
- `msprof_*.json`: application-level timeline context for host/runtime,
  streams, and operators. Official documentation describes this file as a
  timeline summary opened in Chrome tracing and shown through CANN and Ascend
  Hardware regions; the local CANN `8.3.0.2.220:8.3.RC2` fixture preserves an
  observed top-level array of events with fields such as `name`, `pid`, `tid`,
  `ts`, `dur`, `ph`, and `args`. Treat it as timing context, not a standalone
  overlap formula, host/device causality model, or bottleneck label source.

## Operator-Level Files

- `OpBasicInfo.csv`: operator identity, launch/core-count context, duration,
  device/process context, and frequency context. Official field references name
  fields such as `Op Name`, `Op Type`, `Task Duration(us)`, `Block Dim`,
  `Mix Block Dim`, `Device ID`, `PID`, `Current Freq`, and `Rated Freq`; the
  local CANN `8.3.0.2.220:8.3.RC2` fixture preserves the observed fields in
  `reports/OPPROF_001/OpBasicInfo.csv`. Treat `Block Dim` as launch/context
  evidence, not standalone proof of core imbalance.
- `PipeUtilization.csv`: Cube, Vector, Scalar, MTE, or equivalent pipe usage.
- `ArithmeticUtilization.csv`: arithmetic utilization summaries.
- `L2Cache.csv`: L2 cache hit ratio artifact. Official CANN 8.0 `msprof op`
  docs name this file as the L2 cache hit ratio output; the local CANN
  `8.3.0.2.220:8.3.RC2` fixture preserves observed fields including
  `block_id`, `sub_block_id`, `aic_total_hit_rate(%)`, and
  `aiv_total_hit_rate(%)`. Treat the field set as fixture-backed for this
  baseline, not a cross-release schema guarantee.
- `Memory.csv`: memory movement summary.
- `MemoryL0.csv`: L0-related memory metrics.
- `MemoryUB.csv`: UB-related memory metrics.
- `ResourceConflictRatio.csv`: conflict and bank/resource pressure signals.
- `visualize_data.bin`: MindStudio Insight visualization artifact.

## Simulator Files

- `core*_code_exe.csv`: per-core source-line execution attribution.
- `core*_instr_exe.csv`: per-core instruction execution attribution.
- `trace.json`: pipeline/timeline detail.

## Selected Profiler Stdout

Some `msprof op` metric modes can print a short summary only to profiler
stdout. These snippets are not CANN output-file mappings and are not listed in
`data/output-files.yaml`. When fixture-backed, the analyzer copies them into
`analysis/summary.json` under `stdout_sections` as raw evidence:

- `stdout_sections.occupancy_summary`: source path, section name, and messages
  with `ordinal` plus raw `message`.
- `stdout_sections.roofline_summary`: source path, section name, and messages
  with raw `message`.
- `stdout_sections.performance_summary`: source path, section name, and
  messages with raw `ordinal`, raw `message`, and source path.

These stdout sections do not create headline metrics or diagnosis rows by
themselves. `stdout_sections.performance_summary` may contribute to the
corroborated pipe advisory only when timing evidence and `PipeUtilization.csv`
are also present; stdout-only evidence remains Analysis evidence.

## Structured Summary

`analysis/summary.json` is the canonical structured source for agents.
`REPORT.md` is a Markdown rendering. The current analyzer contract writes
`analysis_schema_version`, grouped `files`, `headlines`, `stdout_sections`,
`analysis_dimensions`, `optimization_directions`, `next_collection_actions`,
`evidence_readiness`, `metric_scope` when a selected `--aic-metrics` value is
discoverable, and `warnings`.

`evidence_readiness` summarizes whether the current run is `insufficient`,
`triage_only`, `directional`, or `actionable_experiment`. It lists available
and missing evidence families, allowed and blocked claims, compact segment
readiness, preserved unparsed binary artifacts, and recommended follow-ups. It
is an audit and collection-planning aid only; it does not change diagnosis,
candidate-summary verdicts, or comparison verdicts.

`analysis/raw_artifact_index.json` is a separate deterministic audit index for
parser-visible raw artifacts. It records recognized CANN CSV groups,
application-level `msprof_*.json`, simulator `trace.json` and `core*_*.csv`,
the stdout files that produced parsed `stdout_sections`, and preserved
unparsed binary profiler artifacts. Parser-visible records keep
run-dir-relative artifact paths, parser type, segment, metric scope, status,
columns, row counts, and small raw samples. Unparsed binary records use
`group: "unparsed_profiler_binary"`, `parser: "none"`, `status: "unparsed"`,
and `diagnosis_role: "not_used"`. They are not diagnosis sources by themselves
and do not add optimization directions, collection actions, or readiness
promotion.

`analysis/simulator_hotspots.json` is the structured simulator hotspot model.
It records parser status, ranked source/instruction rows, pipeline duration
context, flow categories, raw `SET_FLAG` / `WAIT_FLAG` counts and CSV sums, and
allowed PMSampling MTE throughput channels when simulator artifacts are
present. `analysis/simulator_hotspots.txt` is the optional Markdown rendering
for human inspection.

`optimization_directions[].evidence[]` keeps stable `evidence_id` values while
preserving `artifact`, `field`, `field_ref`, `signal`, and `value`. Directions
also carry `requires_artifacts` and `missing_artifacts`.

`next_collection_actions[]` contains profiler follow-up recommendations only.
Each action records an action `id`, `reason`, `recommended_aic_metrics`,
`required_artifacts`, cited `evidence`, and `confidence`. Do not turn these
actions into kernel code-change advice.

Known metric scopes are policy-gated for report caveats:
`PipeUtilization`, `Default`, `KernelScale`, `ResourceConflictRatio`,
`PMSampling`, `Occupancy`, and `Roofline`. Required artifacts still warn when
missing. Optional or out-of-scope metric family warnings may be suppressed only
for a known selected scope; unknown scopes preserve current warnings. See
`reference/10-summary-schema.md` for the full agent-facing contract.

Treat columns as version-sensitive. Helpers match likely column names and keep
raw records in `summary.json` for inspection.
