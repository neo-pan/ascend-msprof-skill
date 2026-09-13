# Candidate And Comparison Schemas

## Commands and inputs

`collect-benchmark` imports an existing caller JSON without running a benchmark
or profiler. It can create a benchmark-only run:

```bash
ascend-msprof collect-benchmark --run-dir profile/baseline --benchmark-json baseline.json
ascend-msprof collect-benchmark --run-dir profile/candidate --benchmark-json candidate.json
ascend-msprof compare --run-dir-a profile/baseline --run-dir-b profile/candidate
ascend-msprof summarize-candidate --run-dir profile/candidate --baseline-run-dir profile/baseline
```

Both evaluation commands accept existing run directories with natural benchmark
or profiler evidence, including either kind alone. Missing evidence produces a
structured assessment; a nonexistent run directory is an input error. Optional
profiler file errors retain their artifact locations in warnings.

The same top-level `assessment` object is accepted by TileLang
`--benchmark-json` and harness `--verify-json`. These adapters reference
`analysis/benchmark_context.json`; they retain their original payload, JIT and
caller context. An absent optional assessment does not stop profiling. Semantic
benchmark issues do not change profiler collection success. A fresh collection
still uses a fresh run; continue mode does not reimport the benchmark.

## Natural measurement contract 1.0

See `assets/benchmark-single-case.json` in the skill bundle for the complete
synthetic single-case input shape. Its values are fabricated contract examples, not a
measurement protocol recommendation or a performance result. A caller supplies:

| Group | Required contents |
|---|---|
| Identity | `contract_version: "1.0"`, `measurement_id`, producer name/version, timezone-qualified `collected_at` |
| Subject | `scope`, implementation `id` and `source`, explicit `build` settings object |
| Workload | `id`, `shape`, `dtype`, `case_count: 1`, semantic `parameters` object |
| Inputs / outputs | Nonempty named tensor lists: `name`, `shape`, `dtype`, `stride`, `layout`, `offset`; unique names, aligned by name |
| Input identity | `kind: digest` plus `sha256`, or `kind: generator` plus name/version/parameters/seed |
| Correctness | `status` pass/fail/error, `subject_id`, reference id/version, method, tolerances, `case_count: 1` |
| Protocol | `natural: true`, timer name/version, scope, synchronization, warmup count, cache/reuse/concurrency policies, sample unit, calls per sample, normalization, independence and execution order |
| Environment | Device model/stable id/count, driver version, actual execution `runtimes` by component including `cann`, control policy, collection-time source |
| Measurement | Positive finite `value_ms`, `statistic` mean/median, positive integer `sample_count` |

Each correctness record must name its own timed implementation. Failed stages
may additionally be recorded as `failure: {stage, message}`, where stage is
compile, correctness or timing. A profiler harness failure is separate from a
caller's natural measurement failure.

Both runs must agree on subject scope, workload, input/output descriptions and
input identity, correctness standard, protocol, environment conditions, and
statistic. Implementation/build/JIT changes are lineage, and sample counts may
differ. Empty build/semantic-parameter objects are explicit declarations, not
inferred defaults. Bool values are not durations, counts or offsets.

`measurement.samples_ms`, when supplied, stays in the raw caller snapshot; this
version does not check sample semantics or recompute statistics. The complete
source envelope must be standard JSON: duplicate keys and NaN/Infinity are
rejected, including inside samples. It supports one case
only. It has no uncertainty input, practical threshold or significance decision.

## Sources and replay

`analysis/benchmark_context.json` has schema `"2.0"`, `imports[]`, the selected
`measurement` or null, and validation `issues[]`. Each import names an immutable
run-local `context/benchmark-inputs/<sha256>.json` snapshot, its SHA-256 and the
entrypoints that imported it. The original bytes, including caller context,
are preserved.

The importer deduplicates equal normalized assessment records. Different
records produce a conflict and clear the selection, including records with the
same measurement ID. Missing fields are never combined across sources. A new
measurement uses a new run directory. Explicit import returns 0 for a valid
record, 1 for recorded semantic issues, or 2 for unreadable/invalid input JSON
or an absent required assessment. Optional imports retain semantic issues in
the adapter context.

Evaluation rereads every registered local snapshot, checks its hash, and
validates the record. A missing or altered source prevents an eligible result.
The cached measurement and issues in the registration file are display outputs;
replay uses the registered snapshots. It does not consult the external caller
path, current device, toolkit or an old derived assessment. Legacy `runtime`, `mean_ms` and `official_timing` remain raw
caller context and cannot supply the new performance contract.

## Shared result schema 4.1

`compare` writes `compare_<a>_vs_<b>.json` and `.md`; `summarize-candidate` writes
`candidate_summary.json` and `.md`. Outputs default to the candidate's
`analysis/`; `--out-dir` changes the destination. The corresponding
`comparison_schema_version` and `candidate_summary_schema_version` are `"4.1"`.

Both contain `runs`, `source_artifacts`, `lineage`, `warnings`,
`performance_assessment` and `mechanism_assessment`. Roles are `baseline` and
`candidate`. Source artifacts include consumed profiler JSON hashes and local
benchmark imports. Candidate summaries also retain `inspection_targets` from
simulator records only, with measured source/instruction/pipeline context.

The generated contracts are `data/benchmark-context.schema.json`,
`data/run-assessment.schema.json`, `data/candidate-summary.schema.json` and
`data/comparison.schema.json`. They describe normalized outputs. The caller
input requirements remain the contract 1.0 table above.

Helpers retain validated models in memory and serialize them at JSON boundaries.
Unavailable components are null; their located issues explain missing or invalid
input. A bad timing/protocol field preserves independent correctness. A bad
sample count or statistic preserves a valid point estimate while blocking its
use in a comparison. Opaque settings stay JSON values; raw samples and unconsumed caller extensions
remain in the unchanged snapshot. Unknown fields in a persisted normalized model
are rejected.

TileLang and harness context writers replace non-finite caller values with null,
preserving finite sibling fields and list positions. Warnings identify the output
field and its raw source record; source files and hashes remain unchanged.
These context projections retain their own layouts, separate from the normalized
caller model and natural-measurement contract.

Regenerate old candidate/comparison output with `summarize-candidate` or `compare`
after their inputs load successfully. For an unsupported benchmark registration,
reimport the original caller input with `collect-benchmark` into a fresh run and
retain the old run. Cached measurement/issue fields do not replace snapshot replay.

### Performance assessment

`contract_version: "2.0"`; `mode` is single_run or comparison.

- `eligibility`: eligible/incomplete/blocked, all checks and reasons, both
  values and artifact/field references. Missing evidence is incomplete;
  invalid evidence, conflicts, correctness failure and mismatches are blocked.
  Blocked takes precedence while retaining missing-evidence reasons.
- `measurements`: partial normalized baseline/candidate records, conflicting
  records when relevant, sources and `authority: caller_provided`.
- `comparison`: not_applicable for one run; not_comparable when checks fail;
  observed_only for two eligible records. `observation` is null unless comparable.
- `limitations`: caller method validity and uncertainty are not certified.

Condition checks are projected from the measured records and checked again on
loading. Input diagnosis and performance admission share the scientific record
rules; correctness remains usable independently of timing. Snapshot decoding and
hash issues remain recorded external facts.

An observation contains `delta_ms = candidate_ms - baseline_ms` and
`speedup_pct = 100 * (baseline_ms - candidate_ms) / baseline_ms`, statistic,
faster/slower/equal direction and source citations. Positive speedup means an
elapsed-time reduction, not a throughput increase. Report it as observed in
these caller measurements. There is no automatic candidate selection policy.

### Mechanism assessment

`contract_version: "3.1"`; coverage is missing/partial/available/blocked.
Coverage describes the listed evidence questions, not proof of a mechanism.
The block contains profiler compatibility diagnostics, workload checks,
headlines, evidence, questions, findings, pending actions and benchmark links.
`evidence.<role>.inputs_present` records whether profiler inputs were present;
`evidence_present` retains the summary-plus-raw-inventory availability check.
Neither boolean authorizes a performance delta. Missing measurement quality is
null. Coverage and descriptive findings are checked against the same typed
facts used to produce them.

Per-metric differences retain the existing CANN workload, target, block, field,
metric-scope, finite-number and supported-schema requirements. CANN versions
must describe a common component; conflicts and equal strings from different
components remain blocked. Commands and output metadata are checked for the
segment actually used by each observation. Full segment inventories and global
readiness are diagnostics, not blanket gates for all families.

A numeric metric comparison requires each workload check (`id`, `shape`, `dtype`,
`case_count`), CANN version and hardware-summary check, and the observation segment's
output/command checks exactly once and matching. Workload values and statuses
must agree with their observations. Empty or duplicate required checks cannot
authorize a delta. Single-run and unavailable comparisons do not need fabricated
checks to satisfy these requirements.

A benchmark link requires all four workload checks exactly once and matching,
plus a matching implementation subject. Payload and harness are distinct subject
sources; matching either one establishes the subject link.

An unsupported Unit/Units layout or unknown metric field cannot produce a
delta. Missing or mismatched evidence retains original values and reasons.
A zero profiler baseline permits an absolute difference but no percentage.
Application headlines without explicit field/scope metadata remain descriptive.
Historical profiler records retain these checks without requiring a new
natural measurement contract.

Each question retains its family, available/missing artifact and field
evidence, status and blockers. No design variables or next experiment are
generated. Existing memory/cache, pipe/arithmetic, workload
and generated-source questions use their own required evidence. Unrelated
simulator/family additions or pending actions do not invalidate a supported
observation. An action without a known question scope remains a pending gap.
Findings are `metric_observation` only, with an evidence
level; they do not establish the cause of an observed speedup.

Benchmark association requires the implementation ID to match a recorded
payload/application SHA-256 and the recorded workload to agree. Different
payload and harness hashes represent different objects; matching the measured
one establishes the subject link. A linked measurement can supply workload
context while retaining original profiler-context conflicts. Correctness failure
blocks natural-performance eligibility but does not hide independently recorded
generated-source or profiler evidence. Association failures do not change independent
natural-performance eligibility or erase raw profiler observations.

Correctness usability is checked by the benchmark evidence module, including
the tested implementation, required correctness fields and registered sources.
A declared compile or correctness failure prevents use of that record's pass;
a timing failure or incomplete timing protocol does not. A valid timing stage
retains this meaning even if its required message is missing or invalid; the
message issue still prevents an eligible performance assessment. Independently recorded
historical correctness remains usable when no benchmark record can be linked.

Markdown renders these same blocks, performance first, without recalculating
differences. `## Design Feedback` renders the nested mechanism questions.

### Per-metric observations

The legacy `mechanism_assessment.headlines[]` now lists per-metric observations
or comparisons; it is not one selected maximum per family. Each present side
retains `field_ref`, `unit`, `statistic`, `aggregation` and recorded `scope`,
including block/sub-block where present. The caller chooses which observations
answer its question.

Compare pairs the same named field only when each run provides a unique
observation for that field in the family, then applies the existing gates plus
unit, statistic, aggregation and compatible scope. Process IDs remain
provenance and are not required to be identical across runs. Different fields are listed
separately with `matching metric missing`; multiple launch observations remain
visible with `metric scope ambiguous`, without arbitrary pairing or deltas.
An extremum moving to a different block retains both values and blocks the
cell comparison. It does not establish a regression.

Schema 4.1 / mechanism contract 3.1 add these comparison semantics and located
references. Regenerate old outputs from current summaries using the existing
commands. Natural-performance assessment and its contract remain unchanged.

Single-run rows with missing interpretation context use `unassessed`, retaining
the original value, location and `comparison_reasons`. For example, a multi-
kernel target declaration does not erase its per-launch observations merely
because the single-target comparison gate cannot admit them. These rows create
no mechanism finding or numeric delta; inspect their target and scope before
using them in an explanation.
