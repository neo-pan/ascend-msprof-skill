---
name: ascend-msprof-skill
description: Profile and diagnose Ascend 910B / CANN / Ascend C kernels and custom operators using msprof, msprof op, msprof op simulator, and CANN profiling CSV/JSON outputs. Use when the user asks about Ascend kernel profiling, msprof reports, 910B kernel bottlenecks, Ascend C operator optimization, CANN profiling, or Chinese variants like "910B kernel 为什么慢" and "帮我看 msprof 报告".
---

# Ascend 910B Profiling

Use this skill for Ascend 910B/910B2 profiling with CANN tools. The current
commands are validated with CANN `8.3.0.2.220:8.3.RC2`; validate command syntax
and output schemas before claiming support for a newer release.

Follow the evidence-first sequence:

```text
Profile -> Diagnose -> Plan
```

Collect or read profiler artifacts, extract structured signals, and rank only
the directions that the evidence supports. Complete each step against its stated
criterion before moving forward.

## Route The Task

Read only the references selected by the current branch, but read each selected
reference completely before acting:

| Task branch | Required context |
|---|---|
| End-to-end profiling | Read [directory layout](reference/00-directory-layout.md), [workflow](reference/01-workflow.md), and [collection](reference/03-collection.md). |
| Supplied harness or direct application | Read [harness guidance](reference/02-harness-guide.md) and [collection](reference/03-collection.md). |
| Analyze an existing run | Read [output files](reference/04-output-files.md), [analysis dimensions](reference/05-analysis-dimensions.md), and [summary schema](reference/10-summary-schema.md). |
| Diagnose a supported signal | Read [diagnosis playbook](reference/06-diagnosis-playbook.md) after identifying the relevant analysis dimension. |
| Interpret an unfamiliar field or metric scope | Read [metric file index](reference/08-ascend-metric-files.md); use raw fields only when the installed CANN version or a controlled fixture supports them. |
| Inspect simulator evidence | Read the simulator sections in [collection](reference/03-collection.md), [output files](reference/04-output-files.md), and [summary schema](reference/10-summary-schema.md). |
| Summarize or compare candidates | Read [candidate and comparison schemas](reference/11-candidate-comparison-schema.md) plus the single-run [summary schema](reference/10-summary-schema.md). |
| Generate or review a report | Read the [report template](reference/07-report-template.md). |
| Resolve collection or parsing failures | Read [common issues](reference/09-common-issues.md) and the relevant collection/output reference. |
| Translate evidence into Ascend C ideas | Read [Ascend 910B programming context](ascend-910b-programming.md) only after corroborated profiler evidence identifies a path. |

## 1. Frame The Target

Record the exact operator/kernel, input shape and dtype, tiling path,
blockDim/core mapping, dispatch path, application or supplied harness, and
baseline.

For TileLang-Ascend, expect `main_kernel` unless run-local JIT source names a
different `__global__ __aicore__` entrypoint. Treat an `msprof op` name such as
`main_kernel_mix_aic` as the known suffixed form of `main_kernel`.

Complete this step when the intended target and workload are explicit enough to
check against profiler-observed names and launch metadata.

## 2. Collect A Fresh Run

Create one run directory per kernel version, shape, tiling path, and profiling
question. Preserve raw outputs under `reports/` and commands/environment under
`logs/`.

Prefer a supplied profile harness manifest or direct application:

```bash
PROFILE_RUN_DIR=profile/<run_name>
mkdir -p "$PROFILE_RUN_DIR"/{reports,logs,analysis}
PROFILE_RUN_DIR=$(realpath "$PROFILE_RUN_DIR")

ascend-msprof profile-harness \
    --run-dir "$PROFILE_RUN_DIR" \
    --manifest "$PROFILE_RUN_DIR/harness/profile_harness.json" \
    --verify-json "$PROFILE_RUN_DIR/context/verify.json"
```

`--verify-json` is optional caller context. It records workload, correctness,
and official timing in `analysis/profile_context.json`; it is not profiler
evidence for bottleneck diagnosis.

Use this timing authority for performance decisions:

1. Use the caller-owned natural-launch benchmark to decide actual runtime,
   acceptance, and promotion after correctness and workload comparability pass.
   Prefer repeated runs and the caller's declared statistic; profiler durations
   do not replace it.
2. Use a complete application profile to rank end-to-end hot paths and inspect
   host/runtime/launch structure for the profiled program.
3. Use an operator profile to explain a selected operator with AI Core metrics.
   Interpret its duration only within a compatible operator collection scope.

Treat collection modes as different measurement boundaries. Compare durations
only when command, workload, launch set, warmup/replay behavior, and metric scope
are compatible. Do not derive a speedup or regression from application-profile
versus `msprof op` totals. When an operator segment covers only part of a
multi-kernel program, block complete-program timing and role-coverage claims.

Use `triage` by default: app-level `msprof` plus `msprof op
--aic-metrics=PipeUtilization`. Use `default-depth` to add a separate Default
metric segment. Use `full` for the same Default segment and append `--simulator`
only when source/instruction/pipeline attribution is needed. `--simulator` is optional.
Its failure remains a warning while app/op evidence is preserved. Use
`--simulator-timeout-s` only with `--simulator`.

When `next_collection_actions` requests the supported Default follow-up, run:

```bash
ascend-msprof profile-harness \
    --run-dir "$PROFILE_RUN_DIR" \
    --follow-next-actions \
    --continue-from-summary \
    --follow-action collect_default_metric_followup
```

Only `blocking` actions run without explicit selection. Default depth is
`hypothesis_required`; select it only when it unlocks the current hypothesis.
Add `--follow-target-json <target.json>` to focus it on a declared target
subset. Focused coverage remains local to that segment and cannot become
complete-program coverage authority. The helper gives focused Default
collection a deterministic separate segment and output path, leaving the
canonical follow-up path available for a later complete-program collection.

Add `--summarize-candidate` to an initial or continue command to write candidate
summary artifacts after analysis without recollecting or modifying raw reports.

For manual app/op/simulator collection, read
[reference/03-collection.md](reference/03-collection.md) completely and use its
recorded-command recipes. Keep benchmark-specific harness rendering in the
benchmark skill or calling agent.

Complete this step when every attempted segment has a command/status record,
raw outputs remain separated by segment, and the expected target is available
for identity checking. For a manifest with an explicit `target`, collection is
complete only when `profile_coverage` accounts for every declared launch and
the metric family needed by the inspection direction covers every relevant
expected launch.

## 3. Extract Structured Evidence

Run the applicable helpers after collection:

```bash
ascend-msprof provenance --run-dir "$PROFILE_RUN_DIR"
ascend-msprof analyze --run-dir "$PROFILE_RUN_DIR"
ascend-msprof sim-hotspots --run-dir "$PROFILE_RUN_DIR"
ascend-msprof timeline --run-dir "$PROFILE_RUN_DIR"
ascend-msprof report --run-dir "$PROFILE_RUN_DIR"
```

When already-collected TileLang workload or correctness context belongs with the
run, attach it without changing raw reports:

```bash
ascend-msprof prepare-tilelang \
    --run-dir "$PROFILE_RUN_DIR" \
    --payload-src path/to/kernel_payload.py \
    --benchmark-json path/to/result.json \
    --jit-debug-root path/to/tilelang-jit-debug
```

Use `ascend-msprof collect-tilelang` when only TileLang context collection is
needed. Neither helper runs scoring, invokes `msprof`, modifies payload code, or
turns benchmark context into profiler evidence.

Complete this step when the required derived JSON exists or its absence is
recorded as a collection/parsing blocker.

## 4. Follow The Evidence Drill-Down

Use this sequence for every diagnosis, candidate summary, comparison, or report:

1. Start from the branch's primary machine source:
   - single run: `analysis/summary.json`;
   - single candidate: `analysis/candidate_summary.json`, then its run summary;
   - comparison: `analysis/compare_*.json`, then both run summaries.
   Treat Markdown as a rendering, not the primary schema.
2. Check `target_identity`, `profile_coverage`, `metric_scope`, `evidence_readiness`,
   `measurement_quality`, `warnings`,
   blocked claims, and `next_collection_actions` before interpreting metrics.
   A mismatched, partially mismatched, or missing observed target blocks
   optimization directions.
3. Inventory every available evidence family from readiness, headlines, and
   `analysis_dimensions`. Mark each family internally as decisive,
   corroborating, non-decisive, or blocked so a quiet family is not forgotten.
4. Select the dimensions that answer the user's question. Follow their
   `artifact`, `field_ref`, raw field, segment, and metric scope into
   `analysis/raw_artifact_index.json`.
5. Confirm parser status, columns, row count, and segment in the raw index before
   opening a cited raw artifact. Use `sample_rows` to locate fields only, never
   as a complete distribution or proof that another row is absent.
6. Apply the missing-derived exception only when the branch's primary derived
   JSON or `analysis/raw_artifact_index.json` is absent. Before opening raw
   evidence, state which derived or index artifact is missing. Limit raw reads
   to diagnosing that blocker or a bounded, read-only interpretation; cite each
   exact raw artifact and field used. Withhold optimization or code-change
   claims whose target, readiness, metric, correctness, or comparison gates
   depend on the missing artifact.
7. Open only cited raw artifacts needed to verify a material claim. Expand to a
   complete file or adjacent evidence family when exact aggregation requires all
   rows, parser/schema status is invalid or ambiguous, or two sourced signals
   conflict. State that reason when expanding.
8. Use `evidence_relations[]` to inspect corroborated artifacts together. Treat
   them as mechanical links, not cause, root-cause, or code-change claims.

The drill-down is complete only when every available family has been accounted
for, every warning or blocker that could change the answer has been surfaced,
and every material claim cites an exact artifact and field. Present decisive,
corroborating, and blocking evidence; omit non-decisive detail unless it prevents
a misleading conclusion.

## 5. Diagnose Or Compare

Use the Ascend-native dimensions: duration/calls, Cube/Vector/Scalar/MTE pipe
mix, GM/L2/L1/L0/UB movement, UB/resource conflicts, tiling/core balance, and
simulator source/instruction/pipeline context.

Use `optimization_directions` as inspection priorities, not rewrite
instructions. Follow required `next_collection_actions` before proposing kernel
changes, or state why collection is unavailable. Form a code-change hypothesis
only after timing and the relevant metric family are corroborated.

For one candidate:

```bash
ascend-msprof summarize-candidate --run-dir profile/<candidate>
```

For a baseline and candidate:

```bash
ascend-msprof compare \
    --run-dir-a profile/<baseline> \
    --run-dir-b profile/<candidate>

ascend-msprof summarize-candidate \
    --run-dir profile/<candidate> \
    --baseline-run-dir profile/<baseline>
```

Treat `--run-dir-a` as baseline and `--run-dir-b` as candidate. Keep profiler
diagnosis separate from caller-owned correctness, official timing, reward, and
promotion policy.

## 6. Report

Write `$PROFILE_RUN_DIR/REPORT.md`. Cite concrete CSV/JSON artifacts and fields
for every performance claim. Include the target/readiness gate, decisive and
corroborating evidence, blockers/caveats, ranked inspection directions, required
follow-ups, and reproduction details.

## Evidence Guardrails

- Keep one run per directory and preserve all raw `PROF_*` and `OPPROF_*` trees.
- Prefer real workload shapes and report the actual device, driver, firmware,
  CANN version, and selected metric scope.
- Use application timing to rank hot paths; require operator metrics before a
  kernel optimization claim.
- Treat stdout summaries as raw context that needs CSV/timing corroboration.
- Keep `.bin` artifacts such as `visualize_data.bin`, `DeviceProf*.bin`, and
  `duration.bin` as audit inventory with no diagnosis role.
- Treat file schemas as version-sensitive and inspect an unrecognized raw field
  before extending aliases or guidance.
- Treat current/rated frequency distributions as measurement-quality context.
  Surface below-rated or mixed-frequency launches, but do not delete samples,
  normalize timing, or change readiness/verdict from frequency alone.
- Keep terminology and diagnosis Ascend-native.
