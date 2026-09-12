# Profiling Workflow

## Contents

- [Phase 0: Frame The Question](#phase-0-frame-the-question)
- [Phase 1: Environment Check](#phase-1-environment-check)
- [Phase 2: Build The Target](#phase-2-build-the-target)
- [Phase 3: Collect Profiles](#phase-3-collect-profiles)
- [Phase 4: Extract Structured Data](#phase-4-extract-structured-data)
- [Phase 5: Diagnose](#phase-5-diagnose)
- [Phase 6: Report](#phase-6-report)

## Phase 0: Frame The Question

Record:

- exact kernel/operator name
- input shape and dtype
- tiling path and blockDim/core mapping
- harness or application entrypoint
- baseline for comparison
- question being answered

If shape or tiling controls dispatch, profile each active path separately.

For TileLang-Ascend payloads, the generated Ascend C entrypoint is normally
`main_kernel`; app-level CANN artifacts usually show `main_kernel`, while
`msprof op` may show a suffixed operator such as `main_kernel_mix_aic`. Default
the expected target to `main_kernel` unless the run-local JIT source shows a
different `__global__ __aicore__` function name.

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

The CANN 8.3.RC2 `msprof` binary does not support a `--version` option.
Preserve version evidence before collection using the explicit
`provenance --collect-env` recipe in `reference/03-collection.md` (automatic
with `profile-harness`). It supports saved running-version fields and the
verified toolkit install-info fallback. Plain `provenance` is offline.
Use the installed CANN documentation for exact command syntax.

## Phase 2: Build The Target

Prefer a standalone ACL/Ascend C harness when the kernel can be isolated. The
harness should fix inputs, tiling, launch configuration, stream sync, and output
validation.

Profile through the original app only when surrounding runtime behavior is part
of the question.

When a benchmark skill or calling agent has already produced a profile harness
manifest, keep benchmark-specific harness rendering in that layer. This skill
consumes the supplied manifest or concrete application path and then owns only
`msprof` collection, analysis, and reporting:

The supported handoff is a supplied profile harness manifest or direct
application path.

```bash
ascend-msprof profile-harness \
    --run-dir "$PROFILE_RUN_DIR" \
    --manifest "$PROFILE_RUN_DIR/harness/profile_harness.json" \
    --verify-json "$PROFILE_RUN_DIR/context/verify.json"
```

The optional `--verify-json` input is caller-provided correctness and official
timing context. Reports render it from `analysis/profile_context.json`; it is
not profiler evidence and must not support bottleneck diagnoses without
`reports/` artifacts.
When a manifest is available and the target is known, set
`metadata.expected_kernel_name` (or `metadata.expected_op_name`) so the analyzer
can verify that profiler headlines refer to the intended target. For
TileLang-Ascend, `main_kernel` is the default and does not need to be repeated
unless the generated entrypoint differs.
`--simulator` is optional and adds `msprof op simulator` collection for
source, instruction, and pipeline detail. It is disabled by default because it
can add substantial runtime; app-level `msprof` and `msprof op PipeUtilization`
remain the default collection path.
Append `--simulator` to the `profile-harness` command for that optional
collection. Use `--simulator-timeout-s <seconds>` only with `--simulator`.

Record the entrypoint as an application path before collection:

```bash
APPLICATION=path/to/run.sh
APPLICATION=$(realpath "$APPLICATION")
```

## Phase 3: Collect Profiles

Collect the minimal profile that answers the question:

- app-level `msprof` for operator and host/runtime timeline
- `msprof op` for operator-level AI Core metrics
- optional `msprof op simulator` for source, instruction, and pipeline detail

Write raw output only under `$PROFILE_RUN_DIR/reports/`.

Before manual collection, read `reference/03-collection.md` completely and use
its canonical recorded-command recipes for app, op, follow-up, and simulator
segments. Complete collection only when every attempted command has a matching
log/status record and all raw outputs remain under the current run's
`reports/` segment.

## Phase 4: Extract Structured Data

Run:

```bash
ascend-msprof provenance --run-dir "$PROFILE_RUN_DIR"
ascend-msprof analyze --run-dir "$PROFILE_RUN_DIR"
ascend-msprof sim-hotspots --run-dir "$PROFILE_RUN_DIR"
ascend-msprof timeline --run-dir "$PROFILE_RUN_DIR"
ascend-msprof report --run-dir "$PROFILE_RUN_DIR"
```

For TileLang kernels, set `TL_ASCEND_DEBUG_INFO=1` and
`TMPDIR="$PROFILE_RUN_DIR/tilelang_tmp"` before launching the profiled
application when simulator source-line output should be enriched with
run-local generated compile source snippets.

When raw profiler output has already been collected under
`$PROFILE_RUN_DIR/reports/`, use the lower-level preparation helper only when
you need to attach optional workload/correctness context:

```bash
ascend-msprof prepare-tilelang \
    --run-dir "$PROFILE_RUN_DIR" \
    --payload-src path/to/kernel_payload.py \
    --benchmark-json path/to/result.json \
    --jit-debug-root path/to/tilelang-jit-debug
```

Workload context is not profiler evidence. Use profiler CSV/JSON artifacts for
Ascend diagnosis.

## Phase 5: Diagnose

Start from the structured artifacts, not the rendered report alone:

```bash
ascend-msprof summarize-candidate --run-dir "$PROFILE_RUN_DIR"
```

When a comparable baseline exists, compare the two profiled run directories
to assess their observations:

```bash
ascend-msprof compare \
    --run-dir-a profile/<baseline> \
    --run-dir-b profile/<candidate>

ascend-msprof summarize-candidate \
    --run-dir profile/<candidate> \
    --baseline-run-dir profile/<baseline>
```

`--run-dir-a` is the baseline and `--run-dir-b` is the candidate. The comparison
artifacts are derived evidence for performance and mechanism assessment;
they contain independent natural-performance and mechanism assessments.
Natural measurement import and comparison conditions are defined in
[the assessment contract](11-candidate-comparison-schema.md). Candidate selection
remains with the caller.

Select the dimensions relevant to the question and cite the exact artifact fields:

1. duration and call count
2. pipe utilization
3. memory movement
4. conflicts
5. tiling/core balance
6. simulator hotspots and pipeline context

Use `analysis/summary.json`, `analysis/candidate_summary.json`, and
`analysis/compare_*.json` as the primary machine-readable sources. The Markdown
files are review aids. Select a `next_collection_actions` follow-up only when
its fields are needed for the current question. Reuse compatible existing
evidence and state any unresolved gap when collection is unavailable. A missing profile, harness failure, or
environment failure is collection evidence only; do not present it as a kernel
bottleneck.

## Phase 6: Report

Write `$PROFILE_RUN_DIR/REPORT.md`. Every claim must cite an artifact and field.
For candidate selection, also cite the generated `candidate_summary` or
`compare` artifact when available, and separate profiler diagnosis from any
benchmark-owned acceptance decision.
