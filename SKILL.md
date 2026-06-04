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
signals, then rank optimization directions by evidence.

## Quickstart

0. Create a fresh run directory:

```bash
PROFILE_RUN_DIR=profile/<run_name>
mkdir -p "$PROFILE_RUN_DIR"/{reports,logs,analysis}
PROFILE_RUN_DIR=$(realpath "$PROFILE_RUN_DIR")
```

1. Frame the profiling target: exact operator/kernel, input shape, tiling path,
   blockDim/core count behavior, dispatch path, and baseline.

2. Provide the application or harness entrypoint to profile. Prefer a
   standalone ACL/Ascend C harness when possible; otherwise use the original
   application when surrounding runtime behavior is part of the question.
   Keep source, build command, fixed inputs, tiling config, stream sync, and
   correctness checks with the run notes. See `reference/02-harness-guide.md`.

```bash
APPLICATION=path/to/run.sh
APPLICATION=$(realpath "$APPLICATION")
```

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

# Simulator for source/instruction/pipeline detail
msprof op simulator --output="$PROFILE_RUN_DIR/reports/sim" \
    --application="$APPLICATION" \
    --aic-metrics=PipeUtilization
```

Use exact command syntax from the installed CANN version and record the toolkit
version from `version.cfg` in the run report. See
`reference/03-collection.md`.

4. Parse outputs with helpers:

```bash
python3 helpers/generate_provenance.py --run-dir "$PROFILE_RUN_DIR"
python3 helpers/analyze_msprof_outputs.py --run-dir "$PROFILE_RUN_DIR"
python3 helpers/extract_simulator_hotspots.py --run-dir "$PROFILE_RUN_DIR"
python3 helpers/plot_timeline.py --run-dir "$PROFILE_RUN_DIR"
python3 helpers/generate_report.py --run-dir "$PROFILE_RUN_DIR"
```

Agent workflow after parsing:

- Treat `$PROFILE_RUN_DIR/analysis/summary.json` as the canonical structured
  source. Use `REPORT.md` as a readable rendering, not as the primary schema.
- Inspect `analysis_dimensions` to see which Ascend-native evidence families
  are available or insufficient.
- Use `optimization_directions` as inspection priorities only. Each direction
  cites exact artifacts and fields and is not a code-change instruction.
- Check `next_collection_actions` before proposing kernel changes. If a
  follow-up collection is listed, collect the recommended `--aic-metrics`
  evidence or explicitly state why it is unavailable.
- Generate code-change hypotheses only after corroborated profiler evidence
  exists across timing and relevant CANN metric artifacts.

Do not:

- diagnose from profiler stdout alone;
- claim a bottleneck from a single metric headline;
- import non-Ascend profiler terminology or labels.

When a run also has already-collected workload or correctness context, attach
it only after profiler outputs exist:

```bash
python3 helpers/prepare_tilelang_profile_run.py \
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
