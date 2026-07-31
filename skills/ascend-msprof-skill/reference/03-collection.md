# Profile Collection Commands

## Contents

- [Application-Level Profile](#application-level-profile)
- [Operator-Level Profile](#operator-level-profile)
- [Simulator Profile](#simulator-profile)

These examples are validated against CANN `8.3.0.2.220:8.3.RC2` on Ascend
910B/910B2. Exact flags vary by CANN release; validate newer CANN releases
against the installed `msprof --help`, `msprof op --help`, and
`msprof op simulator --help` before changing formal guidance.

Before running the examples, start from an existing application path and make
the run directory absolute so recorded profiler commands preserve run-internal
`reports/...` paths in provenance:

```bash
PROFILE_RUN_DIR=profile/<run_name>
APPLICATION=path/to/run.sh
mkdir -p "$PROFILE_RUN_DIR"/{reports,logs,analysis}
PROFILE_RUN_DIR=$(realpath "$PROFILE_RUN_DIR")
APPLICATION=$(realpath "$APPLICATION")
```

If a benchmark skill or calling agent supplies a profile harness manifest,
the generic wrapper can run the app/op collection against that supplied
application:

```bash
ascend-msprof profile-harness \
    --run-dir "$PROFILE_RUN_DIR" \
    --manifest "$PROFILE_RUN_DIR/harness/profile_harness.json" \
    --verify-json "$PROFILE_RUN_DIR/context/verify.json"
```

The helper supports `--preset triage`, `--preset default-depth`, and
`--preset full`. Omitting `--preset` uses `triage`: app-level `msprof` plus
`msprof op --aic-metrics=PipeUtilization`. `default-depth` adds a separate
Default metric follow-up segment, and `full` currently adds that same Default
segment plus optional simulator collection only when `--simulator` is supplied.

After a triage run, the helper can append the supported Default follow-up when
`analysis/summary.json` recommends `collect_default_metric_followup`:

```bash
ascend-msprof profile-harness \
    --run-dir "$PROFILE_RUN_DIR" \
    --follow-next-actions \
    --continue-from-summary
```

This continue mode reuses `analysis/profile_harness_run.json`, refuses to
overwrite existing follow-up output, and records run/skipped/blocked actions in
that workflow metadata. Other recommended actions are recorded as skipped until
the helper supports safe automation for them.

The wrapper profiles only the supplied manifest/application. It does not own
benchmark-specific harness rendering. `--verify-json` is optional caller
context and is written to `analysis/profile_context.json` for workload,
correctness, and timing context only; profiler diagnoses still cite `reports/`
artifacts and `analysis/summary.json`.
For a declared single-kernel or multi-launch target, include the collection and
coverage contract at the top level of the supplied manifest:

```json
{
  "application": "run_application.sh",
  "target": {
    "kernel_selector": "main_kernel*",
    "expected_launches": [
      {"name": "main_kernel", "count": 1}
    ]
  }
}
```

The helper validates this contract before invoking `msprof`, derives
`--launch-count` from the expected counts, and applies the selector, count,
`--warm-up=0`, and application replay behavior to onboard op and supported
Default follow-up collection. Continue mode reuses the persisted target and
does not reconstruct it from the summary. Existing `expected_kernel_name` and
`expected_kernel_names` metadata remains supported for identity only; it does
not change collection or enable count completeness.

The analyzer compares the declared names with the authoritative observed names
from the app `op_summary_*.csv` and per-launch `OpBasicInfo` records. For
TileLang-Ascend kernels, TileLang context implies
expected `main_kernel` by default unless the generated JIT source names a
different `__global__ __aicore__` entrypoint; `main_kernel_mix_aic` from
`msprof op` is treated as matching `main_kernel`.
`--simulator` is optional and disabled by default. Use it when source,
instruction, or pipeline attribution is needed; simulator collection can add
substantial runtime. If optional simulator collection fails, the wrapper records
the failure as a warning and continues analysis/report generation from app/op
artifacts.
Append `--simulator` to the `profile-harness` command for that optional
collection. Use `--simulator-timeout-s <seconds>` only with `--simulator`.

## Application-Level Profile

Use this first when you need operator ranking or host/runtime timeline:

```bash
MSPROF_APP_CMD=(
    msprof
    --output="$PROFILE_RUN_DIR/reports/app"
    --application="$APPLICATION"
    --runtime-api=on
    --task-time=on
    --ai-core=on
    --aic-metrics=PipeUtilization
    --type=text
    --summary-format=csv
)
printf "%q " "${MSPROF_APP_CMD[@]}" > "$PROFILE_RUN_DIR/logs/command_msprof.txt"
printf "\n" >> "$PROFILE_RUN_DIR/logs/command_msprof.txt"
"${MSPROF_APP_CMD[@]}"
```

Expected output normally includes a `PROF_*` directory with
`mindstudio_profiler_output/`. In CANN 8.3.RC2 help, the app-level flags above
are documented in `msprof --help`; cite the exact command and resulting
`PROF_*` files in the report.

## Operator-Level Profile

Use `msprof op` when the target is one Ascend C/custom operator and you need AI
Core metrics:

```bash
MSPROF_OP_CMD=(
    msprof
    op
    --output="$PROFILE_RUN_DIR/reports/op"
    --application="$APPLICATION"
    --aic-metrics=PipeUtilization
)
printf "%q " "${MSPROF_OP_CMD[@]}" > "$PROFILE_RUN_DIR/logs/command_msprof_op.txt"
printf "\n" >> "$PROFILE_RUN_DIR/logs/command_msprof_op.txt"
"${MSPROF_OP_CMD[@]}"
```

The CANN 8.3.RC2 `msprof op --help` output documents `--application` and
`--aic-metrics`. Record the selected metric set in the report.

Use `PipeUtilization` as the starter metric when the immediate question is
which AI Core pipe dominates. For broader metric sets, first check the
installed `msprof op --help`: official CANN 8.x references also list values
such as `Default`, `KernelScale`, `ResourceConflictRatio`, `PMSampling`,
`Occupancy`, and `Roofline`, but availability and meaning vary by CANN release
and product.
Do not assume the helpers parse a newly selected metric output unless that
file is already listed in `data/output-files.yaml` or covered by a controlled
fixture. Some `msprof op` metric information can appear only in selected
profiler stdout rather than in a CSV or JSON artifact; the analyzer extracts
only stdout sections that already have controlled fixture coverage.

When `analysis/summary.json` recommends a supported Default metric follow-up,
collect it as a separate raw output segment in the same run:

```bash
MSPROF_FOLLOWUP_CMD=(
    msprof
    op
    --output="$PROFILE_RUN_DIR/reports/followups/collect_default_metric_followup"
    --application="$APPLICATION"
    --aic-metrics=Default
)
printf "%q " "${MSPROF_FOLLOWUP_CMD[@]}" \
    > "$PROFILE_RUN_DIR/logs/command_msprof_followup_collect_default_metric_followup.txt"
printf "\n" >> "$PROFILE_RUN_DIR/logs/command_msprof_followup_collect_default_metric_followup.txt"
"${MSPROF_FOLLOWUP_CMD[@]}"
```

The follow-up is part of the same run but a distinct raw output segment. It
must contain `OpBasicInfo.csv`, `PipeUtilization.csv`,
`ArithmeticUtilization.csv`, `Memory.csv`, `MemoryL0.csv`, `MemoryUB.csv`, and
`ResourceConflictRatio.csv`. Record the follow-up command under
`logs/command_msprof_followup_collect_default_metric_followup.txt` before
regenerating provenance, analysis, timeline, and report artifacts.

## Simulator Profile

Use optional simulator output for source-line, instruction, and pipeline
detail:

```bash
msprof op simulator --output="$PROFILE_RUN_DIR/reports/sim" \
    --application="$APPLICATION" \
    --aic-metrics=PipeUtilization
```

Simulator output can differ from on-device timing. Use it for attribution and
pipeline shape, not as the final elapsed-time source.

Simulator `--aic-metrics` choices are separate from onboard `msprof op`
choices. In the validated CANN 8.3.RC2 help, simulator metrics include
`PipeUtilization`, `ResourceConflictRatio`, and `PMSampling`, with
`PipeUtilization` required. Keep simulator analysis tied to the generated
simulator artifacts rather than carrying over onboard metric assumptions.
