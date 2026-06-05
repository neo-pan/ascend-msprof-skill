# Ascend 910B Programming Notes

This is a compact companion reference for profiling reports. It is not a
replacement for official CANN documentation.

## Mental Model

Ascend C custom operators normally split responsibilities between:

- host-side tiling and launch preparation
- device-side AI Core kernel implementation

Performance diagnosis should connect profiler signals back to these decisions:
tiling shape, blockDim/core mapping, memory movement, queue depth, and compute
pipeline use.

## AI Core Concepts To Track

- **Cube path:** matrix/tensor compute. Low Cube utilization in a GEMM-like
  kernel usually points to tiling, data feeding, or pipeline scheduling issues.
- **Vector path:** elementwise/reduction work. Unexpected Vector dominance may
  indicate format conversion, scalar fallback, or poorly fused epilogues.
- **Scalar/control path:** address generation and control. High scalar pressure
  can be a symptom of complex indexing or branch-heavy kernels.
- **MTE/DataCopy path:** GM/UB/L0 transfers. MTE bottlenecks often mean memory
  movement is not hidden behind compute.
- **UB and local memories:** UB capacity, alignment, and bank behavior strongly
  shape achievable throughput.

## Optimization Themes

- Use profiling data to decide whether the kernel is compute limited, transfer
  limited, conflict limited, or imbalanced.
- Improve tiling only after confirming which pipe or memory level limits the
  measured workload.
- For pipeline kernels, inspect simulator pipeline context alongside on-device
  timing and pipe metrics before changing queue depth or stage granularity.
- For variable shapes, check per-core balance and tail work before tuning small
  instruction-level effects.
