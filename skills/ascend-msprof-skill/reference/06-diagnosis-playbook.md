# Diagnosis Playbook

Use this after extracting `analysis/summary.json`. Every diagnosis or
optimization direction must cite the artifact and field that produced it.

## Evidence Gating

- Duration-only evidence can choose the next focused inspection target.
- Concrete code directions require timing evidence plus at least one
  corroborating CANN metric family.
- App/Op Correlation aligns evidence only; it does not generate diagnosis rows
  or optimization directions.
- Occupancy and RoofLine stdout summaries are raw evidence sections. They do
  not create directions unless corroborated by profiler CSV or simulator
  artifacts.
- Simulator evidence increases source or pipeline specificity, but it does not
  replace on-device timing evidence.

## Hot Path Focus

Signals: `op_summary_*.csv`, `op_statistic_*.csv`, `task_time_*.csv`, or
`api_statistic_*.csv` identifies the dominant operator, task, or API time.

Direction: inspect that path first. Keep the action as focused inspection until
another CANN metric family explains what to inspect inside the kernel or host
path.

## Pipe And Arithmetic Mix

Signals: timing evidence plus `PipeUtilization.csv` and
`ArithmeticUtilization.csv` point to a specific AI Core pipe or arithmetic
family.

Direction: inspect whether the pipe/arithmetic mix matches the intended
Ascend C path before changing tiling, compute code, or epilogue handling.

## Memory And Data Movement

Signals: timing evidence plus `PipeUtilization.csv` and `Memory.csv`,
`MemoryL0.csv`, `MemoryUB.csv`, or `L2Cache.csv`.

Direction: inspect GM/UB/L0 movement, DataCopy granularity, buffering, and tile
reuse. Do not recommend a memory rewrite from a memory headline alone.

## UB Or Resource Conflict

Signals: timing evidence plus `ResourceConflictRatio.csv`, corroborated by
pipe/arithmetic evidence or simulator source context.

Direction: inspect UB layout, queue schedule, alignment, and conflicting
resource usage around the timed path.

## Tiling And Core Balance

Signals: timing evidence plus `OpBasicInfo.csv` and simulator per-core context
or workload shape evidence.

Direction: inspect `Block Dim`, `Mix Block Dim`, per-core timing, and shape
specialization before changing work distribution.

## Source And Pipeline Context

Signals: on-device timing or pipe/memory/resource evidence plus simulator
`core*_code_exe.csv`, `core*_instr_exe.csv`, or `trace.json`.

Direction: use simulator source, instruction, and pipeline context to locate
the code region to inspect. Keep the report tied to observed artifact fields
instead of unsupported overlap formulas.

## Experiment Hints

`optimization_directions[].experiment_hint` is a recollection-backed next
experiment for an already generated direction. Treat it as a way to inspect one
code area, change one variable, recollect the cited artifacts, and check whether
the profiler movement supports or refutes the hypothesis.

The hint is not a code-change instruction and does not create a direction by
itself. Simulator `source_context` may make the inspection area more specific,
but it does not replace on-device timing evidence or the metric-family gates
above.
