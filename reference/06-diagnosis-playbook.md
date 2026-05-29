# Diagnosis Playbook

Use this after extracting metrics. Each finding must cite the artifact and
field that produced it.

## MTE / DataCopy Bottleneck

Signals: high MTE utilization or memory files dominate on device; simulator
pipeline context shows relevant MTE instructions or flow categories to inspect.

First fixes: adjust tiling to improve reuse, increase copy/compute overlap,
review DataCopy granularity and alignment.

## Low Cube Utilization

Signals: GEMM-like kernel has low Cube usage while memory or MTE is busy.

First fixes: improve data feeding, review MatMul/TCube tiling, reduce format
conversion around the Cube path.

## Vector Or Scalar Dominance

Signals: Vector/Scalar pipe dominates a kernel expected to be Cube-heavy.

First fixes: inspect epilogue, indexing, format conversion, branches, and
fallback paths.

## UB Or Resource Conflict

Signals: high `ResourceConflictRatio.csv` values or simulator hotspots around
UB accesses.

First fixes: revise UB layout, alignment, buffering, and queue schedule.

## Pipeline Scheduling Inspection

Signals: on-device `op_summary_*.csv`, `task_time_*.csv`,
`PipeUtilization.csv`, or memory CSV fields show a timing or pipe-utilization
issue, and simulator artifacts provide pipeline context. In the sanitized
fixture
`tests/fixtures/real_simulator_minimal/reports/OPPROF_001/simulator/trace.json`,
use only observed fields such as `traceEvents[].ph`, `traceEvents[].dur`,
`traceEvents[].tid`, and flow `traceEvents[].cat`; do not treat them alone as
proof of poor overlap. The paired simulator CSV evidence in that fixture is
`tests/fixtures/real_simulator_minimal/reports/OPPROF_001/simulator/core3.veccore0/core3.veccore0_instr_exe.csv`
and the header-only
`tests/fixtures/real_simulator_minimal/reports/OPPROF_001/simulator/core3.veccore0/core3.veccore0_code_exe.csv`.

First fixes: increase buffering depth, use TPipe/TQue patterns correctly, and
balance stage granularity.

## Tiling/Core Imbalance

Signals: per-core simulator files show skew, tail work, or blockDim mismatch.

First fixes: retile work distribution, split large tail blocks, or add shape
specialization for hot paths.

## Host/Tiling Overhead

Signals: API/timeline files show high host or runtime overhead relative to
device task time.

First fixes: cache tiling where legal, reduce launch count, or fuse adjacent
small operators.
