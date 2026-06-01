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
mkdir -p "$PROFILE_RUN_DIR"/{harness,reports,analysis}
```

1. Frame the profiling target: exact operator/kernel, input shape, tiling path,
   blockDim/core count behavior, dispatch path, and baseline.

2. Build a standalone ACL/Ascend C harness when possible. Keep source, build
   command, fixed inputs, tiling config, stream sync, and correctness checks
   under `$PROFILE_RUN_DIR/harness/`. See `reference/02-harness-guide.md`.

3. Collect the right profiles:

```bash
# Application/model level
msprof --output="$PROFILE_RUN_DIR/reports/app" \
    --application="$PROFILE_RUN_DIR/harness/run.sh" \
    --runtime-api=on \
    --task-time=on \
    --ai-core=on \
    --aic-metrics=PipeUtilization \
    --type=text \
    --summary-format=csv

# Operator tuning on device
msprof op --output="$PROFILE_RUN_DIR/reports/op" \
    --application="$PROFILE_RUN_DIR/harness/run.sh" \
    --aic-metrics=PipeUtilization

# Simulator for source/instruction/pipeline detail
msprof op simulator --output="$PROFILE_RUN_DIR/reports/sim" \
    --application="$PROFILE_RUN_DIR/harness/run.sh" \
    --aic-metrics=PipeUtilization
```

Use exact command syntax from the installed CANN version and record the toolkit
version from `version.cfg` in the run report. See
`reference/03-collection.md`.

4. Parse outputs with helpers:

```bash
python3 helpers/analyze_msprof_outputs.py --run-dir "$PROFILE_RUN_DIR"
python3 helpers/extract_simulator_hotspots.py --run-dir "$PROFILE_RUN_DIR"
python3 helpers/plot_timeline.py --run-dir "$PROFILE_RUN_DIR"
```

For the current `tilelang-ascend-benchmark` repo shape, profile a TileLang
benchmark candidate with the orchestrator helper:

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

The orchestrator runs the benchmark once outside profiling for canonical
acceptance evidence, then collects app-level `msprof` plus `msprof op
--aic-metrics=PipeUtilization`, captures run logs, runs analysis helpers, and
writes `REPORT.md`. v1 intentionally collects only app + PipeUtilization; wider
metric sets and simulator collection are future extensions.

For a TileLang kernel/candidate with already collected profiler outputs under
`reports/`, use the lower-level artifact preparation helper:

```bash
python3 helpers/prepare_tilelang_profile_run.py \
    --run-dir "$PROFILE_RUN_DIR" \
    --payload-src path/to/kernel_payload.py \
    --benchmark-json path/to/result.json \
    --jit-debug-root path/to/tilelang-jit-debug
```

This records benchmark/runtime/correctness context as evidence only. It does
not run scoring, invoke `msprof`, modify the payload, optimize TileLang code, or
write raw profiler outputs under `reports/`.

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

## Critical Rules

- Keep one run per directory. Never reuse or mix run outputs.
- Preserve raw `PROF_*` and `OPPROF_*` trees.
- Prefer real workload shapes over arbitrary synthetic tensors.
- Treat file schemas as version-sensitive; report the CANN version.
- Use `ascend-910b-programming.md` only for optimization context, not as a
  replacement for profiler evidence.
