# Analysis Dimensions

Use these dimensions after collecting profiler artifacts and before writing
diagnosis or optimization directions. Each dimension is evidence-first: cite
the exact artifact and field, then decide whether more corroboration is needed.

`ascend-msprof analyze` writes these dimensions to
`analysis/summary.json` under `analysis_dimensions`. Each signal keeps the
artifact path, summary field reference, raw field name when available, and
observed value when available.

The same `summary.json` also carries agent-facing `optimization_directions`
and, when justified by selected metric scope plus missing evidence,
`next_collection_actions`. Use directions as inspection priorities and next
collection actions as profiler follow-up work; neither field is a direct
kernel rewrite instruction.

## 1. Hot Path And Dispatch

Read `op_summary_*.csv`, `op_statistic_*.csv`, `task_time_*.csv`, and
`api_statistic_*.csv`.

Use this dimension to choose the operator, task, or host/runtime API that
deserves focused inspection. Duration-only evidence is enough to rank what to
inspect next, but it is not enough to prescribe a kernel code change.

## 2. Pipe And Arithmetic Mix

Read `PipeUtilization.csv`, `ArithmeticUtilization.csv`, and application
`op_summary_*.csv` AI Core fields such as `aic_*`, `aiv_*`, ratio, cycle, and
time columns when present.

Use this dimension to inspect whether Cube, Vector, Scalar/control, MTE, or
other AI Core pipe signals match the expected Ascend C execution path. Pair it
with timing evidence before turning it into an optimization direction.

## 3. Memory And Cache Movement

Read `Memory.csv`, `MemoryL0.csv`, `MemoryUB.csv`, and `L2Cache.csv`.

Use this dimension to inspect GM/UB/L0 movement, bandwidth, data volume,
usage-rate, time, cycle, MTE count, and L2 hit-rate fields. A cache or memory
headline alone is evidence, not a diagnosis; corroborate it with timing, pipe,
or simulator context before changing buffering, tile reuse, or DataCopy code.

## 4. Resource And UB Conflict

Read non-simulator `ResourceConflictRatio.csv`.

Use this dimension to inspect UB bank/resource conflict and wait-ratio signals.
Treat ratio fields as on-device investigation signals. They need timing and
another metric family, or simulator/source context, before becoming an
optimization direction.

## 5. Tiling And Core Balance

Read `OpBasicInfo.csv`, application task timing, workload shape metadata, and
simulator per-core artifacts when present.

Use this dimension to inspect operator identity, `Block Dim`, `Mix Block Dim`,
task duration, and per-core context. `Block Dim` is launch metadata; do not
infer core imbalance from it alone.

## 6. Source And Pipeline Context

Read simulator `core*_code_exe.csv`, `core*_instr_exe.csv`, `trace.json`, and
the derived `analysis/simulator_hotspots.json` model. Use PMSampling MTE
throughput counter events only as raw evidence when collected and parsed.

Use this dimension to locate source-line, instruction, and pipeline context
after an on-device timing or pipe/memory/resource signal has identified the
path worth inspecting. Simulator context increases specificity, but it does
not replace on-device evidence.
