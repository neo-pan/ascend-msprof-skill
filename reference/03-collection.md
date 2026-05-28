# Profile Collection Commands

Exact flags vary by CANN release. Always check the installed `msprof --help`.

## Application-Level Profile

Use this first when you need operator ranking or host/runtime timeline:

```bash
msprof --output="$PROFILE_RUN_DIR/reports/app" \
    "$PROFILE_RUN_DIR/harness/run.sh"
```

Expected output normally includes a `PROF_*` directory with
`mindstudio_profiler_output/`.

## Operator-Level Profile

Use `msprof op` when the target is one Ascend C/custom operator and you need AI
Core metrics:

```bash
msprof op --output="$PROFILE_RUN_DIR/reports/op" \
    "$PROFILE_RUN_DIR/harness/run.sh"
```

If the CANN version supports metric-set selection, record the selected
`--aic-metrics` value in the report.

## Simulator Profile

Use simulator output for source-line, instruction, and pipeline detail:

```bash
msprof op simulator --output="$PROFILE_RUN_DIR/reports/sim" \
    "$PROFILE_RUN_DIR/harness/run.sh"
```

Simulator output can differ from on-device timing. Use it for attribution and
pipeline shape, not as the final elapsed-time source.

