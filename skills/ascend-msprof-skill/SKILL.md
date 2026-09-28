---
name: ascend-msprof-skill
description: Profile and diagnose Ascend 910B / CANN / Ascend C kernels and custom operators using msprof, msprof op, msprof op simulator, and CANN profiling CSV/JSON outputs. Use when the user asks about Ascend kernel profiling, msprof reports, 910B kernel bottlenecks, Ascend C operator optimization, CANN profiling, or Chinese variants like "910B kernel 为什么慢" and "帮我看 msprof 报告".
---

# Ascend 910B Profiling

Help the calling agent understand its Ascend kernel: locate important runtime
cost, connect evidence to source and workload, assess a mechanism, and identify
the next useful verification. Deliver a sourced answer, separating observations,
interpretations and unresolved alternatives. The caller owns kernel changes,
hypotheses, experiment verdicts and candidate selection.

Commands are validated with CANN `8.3.0.2.220:8.3.RC2` on Ascend 910B/910B2.
Check installed command syntax and output schemas before extending that baseline.
Keep terminology and diagnosis Ascend-native.

## Route The Task

| Situation | Entry and next step |
|---|---|
| Existing profiling run or caller-provided evidence paths | Read `analysis/reading_guide.md` for this run's limits and question routes. If absent, use `analysis/key_metrics.txt`. Follow [evidence navigation](reference/12-evidence-navigation.md) when selecting the authority, drilling into fields or handling partial evidence. |
| Need new evidence | Read [collection](reference/03-collection.md); for a supplied harness also read [harness guidance](reference/02-harness-guide.md). Use [workflow](reference/01-workflow.md) and [directory layout](reference/00-directory-layout.md) for a new end-to-end run. |
| Compare a baseline and candidate | Read [assessment inputs and outputs](reference/11-candidate-comparison-schema.md). Keep natural performance and profiler mechanism assessments independent; then follow each run's navigation for the relevant observations. |
| Interpret a signal or connect it to code | Read the relevant [analysis dimension](reference/05-analysis-dimensions.md), [metric definition](reference/08-ascend-metric-files.md) and [mechanism card](reference/06-diagnosis-playbook.md). Consult [Ascend programming context](ascend-910b-programming.md) for unfamiliar source terms. |
| Missing, failed or unfamiliar artifact | Read the affected section of [output files](reference/04-output-files.md), [summary schema](reference/10-summary-schema.md) or [common issues](reference/09-common-issues.md). Preserve valid partial evidence. |

Read only the selected branch's references. Read command recipes completely
before executing them. For a worked example of different segments, independent
maxima and a limited performance conclusion, see
[real serial/pipelined matmul](reference/13-real-matmul-walkthrough.md).

## 1. Frame The Question And Measurement

Identify the exact kernel/program, shape, dtype, tiling and launch path, source
version, baseline and the question being answered. Use run-local generated
entrypoints for target matching; TileLang-Ascend normally uses `main_kernel`
with an operator name such as `main_kernel_mix_aic`.

| Question | Measurement boundary |
|---|---|
| Did the implementation become faster? | Comparable caller-owned natural-launch benchmark after correctness, workload, protocol and environment checks. |
| Where is profiled application time spent? | Application `msprof` operator/task/API timing and timeline within recorded launch coverage. |
| What did the selected operator execute? | `msprof op`, its selected AI Core metric family and collection scope. |
| Which source/instruction/pipeline events were simulated? | `msprof op simulator`, kept separate from on-device time. |

Keep the caller/Executor's declared formal timing mode explicit. A field named
“duration” alone does not define its measurement boundary. Application-profile,
operator-profile and natural timings are not interchangeable. A partial operator
segment cannot establish whole-program timing or complete launch coverage.

Complete framing when the target/workload can be checked against observed
names and launches, and the measurement source can answer the stated question.

## 2. Reuse Or Collect

Reuse valid existing evidence first. For collection, keep one run per source
version, workload and profiling question; raw outputs belong under `reports/`,
commands and status receipts under `logs/`. Record live device, driver, firmware,
CANN and selected metric scope. Prefer a supplied harness or concrete application;
use a standalone ACL/Ascend C harness when isolation is feasible. The input is a
supplied profile harness manifest or direct application; harness rendering
belongs to the benchmark skill or calling agent. `--simulator` is optional.

Default `triage` collects application timing and `msprof op
--aic-metrics=PipeUtilization`. Choose `default-depth` when Default fields are
needed. `full` adds that same Default segment; simulator collection still
requires `--simulator`. See [collection recipes](reference/03-collection.md)
for initial, focused and continuation commands, implementation/environment checks
and optional simulator timeouts.

Treat `next_collection_actions` as conditional evidence requests, not a task
queue. `question_required` actions need explicit selection, for example
`--follow-action collect_default_metric_followup`, only when the question needs
those fields. Missing one family narrows that claim without erasing other facts.

Complete collection when each attempted segment has a command/status receipt,
raw outputs are separated, and target/metric launch coverage is accounted for or
the specific gap is recorded. Preserve app/op evidence if optional simulation fails.

## 3. Read The Evidence In Layers

For preserved raw reports, generate the navigation and evidence model:

```bash
ascend-msprof provenance --run-dir "$PROFILE_RUN_DIR"
ascend-msprof analyze --run-dir "$PROFILE_RUN_DIR"
```

Then follow this order:

1. **Run limits:** read `reading_guide.md` (or existing `key_metrics.txt`). Check
   `target_identity`, `profile_coverage`, per-artifact `metric_scope`,
   `evidence_readiness`, `measurement_quality`, `warnings` and blocked claims.
   Keep unbound observations unbound. Name match is not source/benchmark binding.
2. **Question and observations:** use `ascend-msprof evidence --run-dir "$PROFILE_RUN_DIR"`
   to discover question reads with scope, limits and bound references; use `--question pipe`,
   `arithmetic`, `memory` or `application-timing` for the selected branch. Existing routes into `summary.json`
   → `analysis_dimensions` / `headlines` remain valid. Keep artifact, field, unit, statistic,
   segment and target/core scope together. Read `issues` before using affected cells.
   `candidate_summary.json` and `compare_*.json` are the authorities for assessments.
3. **Verification:** follow `raw_artifact_index.json` and the exact source record.
   Operator `joint-row` supports same-record inspection and full matching field
   summaries; `core_time_distributions` locates tails. `sample_rows` only locates
   fields. Use [field selection](reference/04-output-files.md#field-selection) for
   commands and [navigation rules](reference/12-evidence-navigation.md) for
   application/simulator routes and missing-derived exceptions.

Unknown metric scope remains unknown. Independent maxima may come from different
blocks. `evidence_relations` are mechanical associations, not causal claims.
Keep stdout as corroborating context and `.bin` files as audit inventory only.
Frequency variation is quality context; it does not authorize deleting samples
or normalizing timings. Reuse verified fields from unchanged artifacts.

Complete the read when the question has a sourced answer or a specific actionable
gap, with each limitation that could change the answer. Unrelated missing families
need no drill-down or collection.

## 4. Assess And Deliver

Use the relevant [mechanism card](reference/06-diagnosis-playbook.md) to connect
observed activity to source and competing explanations. A high ratio or a
co-occurring signal alone establishes neither a bottleneck nor a preferred change.
Keep a useful partial observation even when a broader comparison is blocked.

```bash
ascend-msprof summarize-candidate --run-dir "$PROFILE_RUN_DIR"
ascend-msprof compare --run-dir-a profile/<baseline> --run-dir-b profile/<candidate>
```

For an optimization experiment, answer “observed faster?” and “supports the
mechanism hypothesis?” separately. `observed_only` or `descriptive` findings do
not decide experiment success. Use the caller's hypothesis/expected-change text
and [caller experiment collaboration](reference/06-diagnosis-playbook.md#caller-experiment-collaboration);
helpers produce observations, coverage, comparability and evidence gaps.

Deliver the answer with decisive artifact/field citations, interpretation,
alternatives and the smallest useful verification. Use the
[report template](reference/07-report-template.md) for `$PROFILE_RUN_DIR/REPORT.md`;
`ascend-msprof report` renders existing evidence. Keep source edits and candidate
selection in the caller's record. For kernel-agent sample paths and Executor
measurement context, see [caller integration](reference/12-evidence-navigation.md#caller-integration-kernel-agent).
