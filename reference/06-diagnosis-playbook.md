# Diagnosis Playbook

Use this after extracting metrics. Each finding must cite the artifact and
field that produced it.

## MTE / DataCopy Bottleneck

Signals: high MTE utilization, memory files dominate, trace shows copies not
hidden behind compute.

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

## Poor Pipeline Overlap

Signals: `trace.json` shows serialized copy and compute; pipe utilization has
large gaps.

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

