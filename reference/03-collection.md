# Profile Collection Commands

These examples are validated against CANN `8.3.0.2.220:8.3.RC2` on Ascend
910B/910B2. Exact flags vary by CANN release; validate newer CANN releases
against the installed `msprof --help`, `msprof op --help`, and
`msprof op simulator --help` before changing formal guidance.

## Application-Level Profile

Use this first when you need operator ranking or host/runtime timeline:

```bash
msprof --output="$PROFILE_RUN_DIR/reports/app" \
    --application="$PROFILE_RUN_DIR/harness/run.sh" \
    --runtime-api=on \
    --task-time=on \
    --ai-core=on \
    --aic-metrics=PipeUtilization \
    --type=text \
    --summary-format=csv
```

Expected output normally includes a `PROF_*` directory with
`mindstudio_profiler_output/`. In CANN 8.3.RC2 help, the app-level flags above
are documented in `msprof --help`; cite the exact command and resulting
`PROF_*` files in the report.

## Operator-Level Profile

Use `msprof op` when the target is one Ascend C/custom operator and you need AI
Core metrics:

```bash
msprof op --output="$PROFILE_RUN_DIR/reports/op" \
    --application="$PROFILE_RUN_DIR/harness/run.sh" \
    --aic-metrics=PipeUtilization
```

The CANN 8.3.RC2 `msprof op --help` output documents `--application` and
`--aic-metrics`. Record the selected metric set in the report.

## Simulator Profile

Use simulator output for source-line, instruction, and pipeline detail:

```bash
msprof op simulator --output="$PROFILE_RUN_DIR/reports/sim" \
    --application="$PROFILE_RUN_DIR/harness/run.sh" \
    --aic-metrics=PipeUtilization
```

Simulator output can differ from on-device timing. Use it for attribution and
pipeline shape, not as the final elapsed-time source.
