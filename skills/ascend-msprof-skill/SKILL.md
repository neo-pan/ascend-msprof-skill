---
name: ascend-msprof-skill
description: Profile and diagnose Ascend 910B / CANN / Ascend C kernels and custom operators using msprof, msprof op, msprof op simulator, and CANN profiling CSV/JSON outputs. Use when the user asks about Ascend kernel profiling, msprof reports, 910B kernel bottlenecks, Ascend C operator optimization, CANN profiling, or Chinese variants like "910B kernel 为什么慢" and "帮我看 msprof 报告".
---

# Ascend 910B Profiling

Use this skill when profiling or diagnosing Ascend 910B kernels/operators with
CANN tools. The current command examples are validated for Ascend 910B/910B2
with CANN `8.3.0.2.220:8.3.RC2`; validate command syntax separately before
claiming support for newer CANN releases. The workflow is evidence-first:

```text
Profile -> Diagnose -> Plan
```

Do not guess bottlenecks. Collect or read profiler artifacts, extract structured
signals, then rank optimization directions by evidence. Prefer the higher-level
helpers over a bare profile/report loop when they fit the question: use
`summarize-candidate` for a single candidate that needs design feedback, use
`compare` for baseline-vs-candidate decisions, and follow
`next_collection_actions` before proposing code changes when required evidence
is missing.

## Quickstart

0. Create a fresh run directory:

```bash
PROFILE_RUN_DIR=profile/<run_name>
mkdir -p "$PROFILE_RUN_DIR"/{reports,logs,analysis}
PROFILE_RUN_DIR=$(realpath "$PROFILE_RUN_DIR")
```

1. Frame the profiling target: exact operator/kernel, input shape, tiling path,
   blockDim/core count behavior, dispatch path, and baseline.
   For TileLang-Ascend kernels, default the expected profiler target to
   `main_kernel` unless the generated JIT source shows a different `__global__
   __aicore__` entrypoint. App-level CANN CSVs usually report `main_kernel`;
   `msprof op` may report a suffixed form such as `main_kernel_mix_aic`, which
   the analyzer treats as the same target.

2. Provide the application or harness entrypoint to profile. Prefer a
   standalone ACL/Ascend C harness when possible; otherwise use the original
   application when surrounding runtime behavior is part of the question.
   Keep source, build command, fixed inputs, tiling config, stream sync, and
   correctness checks with the run notes. See `reference/02-harness-guide.md`.
   If a benchmark skill or calling agent supplies a profile harness manifest,
   consume that manifest or its concrete application path here; keep
   benchmark-specific harness rendering outside this skill. Put the expected
   target in manifest metadata when the caller knows it or when the generated
   kernel entrypoint differs from the TileLang default:

```json
{
  "metadata": {
    "expected_kernel_name": "main_kernel"
  }
}
```

```bash
APPLICATION=path/to/run.sh
APPLICATION=$(realpath "$APPLICATION")
```

For a supplied harness, the helper can run collection and analysis end to end:

```bash
ascend-msprof profile-harness \
    --run-dir "$PROFILE_RUN_DIR" \
    --manifest "$PROFILE_RUN_DIR/harness/profile_harness.json" \
    --verify-json "$PROFILE_RUN_DIR/context/verify.json"
```

`--verify-json` is optional context from the caller. It records workload,
correctness, and official timing under `analysis/profile_context.json` only;
do not use it as profiler evidence for bottleneck diagnoses.
`--simulator` is optional and disabled by default. Enable it only when
source-line, instruction, or pipeline attribution is needed; it can add
substantial runtime, and the helper treats simulator failures as nonfatal
warnings while keeping app/op evidence.
Append `--simulator` to the `profile-harness` command for that optional
collection. Use `--simulator-timeout-s <seconds>` only with `--simulator`.

3. Collect the right profiles:

```bash
# Application/model level
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

# Operator tuning on device
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

# Optional simulator for source/instruction/pipeline detail
msprof op simulator --output="$PROFILE_RUN_DIR/reports/sim" \
    --application="$APPLICATION" \
    --aic-metrics=PipeUtilization
```

Use exact command syntax from the installed CANN version and record the toolkit
version from `version.cfg` in the run report. See
`reference/03-collection.md`.

4. Parse outputs with helpers:

```bash
ascend-msprof provenance --run-dir "$PROFILE_RUN_DIR"
ascend-msprof analyze --run-dir "$PROFILE_RUN_DIR"
ascend-msprof sim-hotspots --run-dir "$PROFILE_RUN_DIR"
ascend-msprof timeline --run-dir "$PROFILE_RUN_DIR"
ascend-msprof report --run-dir "$PROFILE_RUN_DIR"
```

Agent workflow after parsing:

- Treat `$PROFILE_RUN_DIR/analysis/summary.json` as the canonical structured
  source. Use `REPORT.md` as a readable rendering, not as the primary schema.
- Check `evidence_readiness` to see whether the run is `insufficient`,
  `triage_only`, `directional`, or `actionable_experiment`. Use it to decide
  whether more profiler evidence is needed; do not treat it as a kernel-quality
  score or candidate verdict.
- Inspect `analysis_dimensions` to see which Ascend-native evidence families
  are available or insufficient.
- Use `optimization_directions` as inspection priorities only. Each direction
  cites exact artifacts and fields and is not a code-change instruction.
- Check `next_collection_actions` before proposing kernel changes. If a
  follow-up collection is listed, collect the recommended `--aic-metrics`
  evidence or explicitly state why it is unavailable.
- For a single profiled candidate, run `ascend-msprof summarize-candidate` to
  produce `analysis/candidate_summary.json` and Markdown design feedback before
  deciding the next kernel experiment.
- For two profiled candidates, run `ascend-msprof compare --run-dir-a
  profile/<baseline> --run-dir-b profile/<candidate>`. Treat `--run-dir-a` as
  the baseline and `--run-dir-b` as the candidate. Use the generated comparison
  artifacts to explain operator/task duration, API overhead, pipe utilization,
  memory/cache/resource conflicts, core balance, or launch/synchronization
  movement.
- Generate code-change hypotheses only after corroborated profiler evidence
  exists across timing and relevant CANN metric artifacts.

Do not:

- diagnose from profiler stdout alone;
- claim a bottleneck from a single metric headline;
- use profiler output as correctness, official timing, speedup, reward, or
  promotion evidence when a caller has a separate benchmark or validation
  contract;
- import non-Ascend profiler terminology or labels.

When a run also has already-collected workload or correctness context, attach
it only after profiler outputs exist:

```bash
ascend-msprof prepare-tilelang \
    --run-dir "$PROFILE_RUN_DIR" \
    --payload-src path/to/kernel_payload.py \
    --benchmark-json path/to/result.json \
    --jit-debug-root path/to/tilelang-jit-debug
```

This records workload/runtime/correctness context as evidence only. It does not
run scoring, invoke `msprof`, modify payload code, optimize kernels, or write
raw profiler outputs under `reports/`.

5. Diagnose with Ascend-specific dimensions:

- operator/task duration and invocation count
- Cube / Vector / Scalar / MTE pipe utilization
- GM/L2/L1/L0/UB memory movement
- UB bank/resource conflicts
- tiling, blockDim, core balance, and tail effects
- simulator source-line, instruction, and pipeline hotspots

6. Write `$PROFILE_RUN_DIR/REPORT.md` using `reference/07-report-template.md`.
Every claim must cite a concrete CSV/JSON artifact and field.

## File Index

- `reference/00-directory-layout.md`: run directory contract
- `reference/01-workflow.md`: end-to-end checklist
- `reference/02-harness-guide.md`: standalone harness guidance
- `reference/03-collection.md`: `msprof` command recipes
- `reference/04-output-files.md`: output files and meanings
- `reference/05-analysis-dimensions.md`: diagnosis dimensions
- `reference/06-diagnosis-playbook.md`: signal -> cause -> fix
- `reference/07-report-template.md`: final report shape
- `reference/08-ascend-metric-files.md`: file-to-question index
- `reference/09-common-issues.md`: common failures and caveats
- `reference/10-summary-schema.md`: `analysis/summary.json` agent contract

## Critical Rules

- Keep one run per directory. Never reuse or mix run outputs.
- Preserve raw `PROF_*` and `OPPROF_*` trees.
- Prefer real workload shapes over arbitrary synthetic tensors.
- Treat file schemas as version-sensitive; report the CANN version.
- Use `ascend-910b-programming.md` only for optimization context, not as a
  replacement for profiler evidence.
