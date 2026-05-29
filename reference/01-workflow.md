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
