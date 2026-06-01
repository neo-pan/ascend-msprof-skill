# Profiling Workflow

## Phase 0: Frame The Question

Record:

- exact kernel/operator name
- input shape and dtype
- tiling path and blockDim/core mapping
- harness or application entrypoint
- baseline for comparison
- question being answered

If shape or tiling controls dispatch, profile each active path separately.

## Phase 1: Environment Check

Capture:

```bash
which msprof
MSPROF_BIN=$(command -v msprof)
TOOLKIT_ROOT=$(cd "$(dirname "$MSPROF_BIN")/.." && pwd)
grep -E '^(toolkit|runtime|compiler|opp)_(running|installed)_version=' \
    "$TOOLKIT_ROOT/version.cfg" || true
npu-smi info || true
env | grep -E 'ASCEND|CANN|DDK|TOOLKIT|PYTHONPATH'
```

The CANN 8.3.RC2 `msprof` binary does not support a `--version` option; treat
`version.cfg` as the command-line version evidence. Use the installed CANN
documentation for exact command syntax.

## Phase 2: Build The Target

Prefer a standalone ACL/Ascend C harness when the kernel can be isolated. The
harness should fix inputs, tiling, launch configuration, stream sync, and output
validation.

Profile through the original app only when surrounding runtime behavior is part
of the question.

## Phase 3: Collect Profiles

Collect the minimal profile that answers the question:

- app-level `msprof` for operator and host/runtime timeline
- `msprof op` for operator-level AI Core metrics
- `msprof op simulator` for source, instruction, and pipeline detail

Write raw output only under `$PROFILE_RUN_DIR/reports/`.

## Phase 4: Extract Structured Data

Run:

```bash
python3 helpers/analyze_msprof_outputs.py --run-dir "$PROFILE_RUN_DIR"
python3 helpers/extract_simulator_hotspots.py --run-dir "$PROFILE_RUN_DIR"
python3 helpers/plot_timeline.py --run-dir "$PROFILE_RUN_DIR"
```

For the current `tilelang-ascend-benchmark` repo shape, use the orchestrator to
collect the benchmark and default profiles in one run:

```bash
python3 helpers/profile_tilelang_benchmark_run.py \
    --run-dir "$PROFILE_RUN_DIR" \
    --benchmark-repo /data/code/ref/tilelang-ascend-benchmark \
    --payload-src examples/kernel_payload_baseline.py \
    --task svd \
    --warmups 0 \
    --repeats 1 \
    --baseline-ms 1.0
```

The orchestrator writes distinct run-local benchmark scripts, runs the
canonical benchmark outside profiling, collects app-level `msprof`, collects
`msprof op --aic-metrics=PipeUtilization`, records logs/provenance, runs the
analysis helpers, and generates `REPORT.md`. The canonical benchmark result is
the only TileLang acceptance evidence; app-profile and op-profile benchmark
outputs are not used for acceptance.
Use a fresh `$PROFILE_RUN_DIR` for each orchestrated collection. The helper
refuses existing benchmark/profile evidence instead of deleting or overwriting
raw profiler outputs. `--disable-op-profile` skips op collection and required-op
validation; it does not consume old `reports/op` files.

When raw profiler output has already been collected under
`$PROFILE_RUN_DIR/reports/`, use the lower-level preparation helper to attach
benchmark context and generate the report:

```bash
python3 helpers/prepare_tilelang_profile_run.py \
    --run-dir "$PROFILE_RUN_DIR" \
    --payload-src path/to/kernel_payload.py \
    --benchmark-json path/to/result.json \
    --jit-debug-root path/to/tilelang-jit-debug
```

The TileLang benchmark result and payload are acceptance evidence only. Use
profiler CSV/JSON artifacts for Ascend diagnosis.

TileLang benchmark orchestration v1 collects app-level profiling and
PipeUtilization only. Broader metric sets and simulator collection are explicit
future extensions.

## Phase 5: Diagnose

Work through:

1. duration and call count
2. pipe utilization
3. memory movement
4. conflicts
5. tiling/core balance
6. simulator hotspots and pipeline context

## Phase 6: Report

Write `$PROFILE_RUN_DIR/REPORT.md`. Every claim must cite an artifact and field.
