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
version does not check samples or recompute statistics. It supports one case
only. It has no uncertainty input, practical threshold or significance decision.

## Sources and replay

`analysis/benchmark_context.json` has schema `"1.0"`, `imports[]`, the selected
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
It does not consult the external caller path, current device, toolkit or an old
derived assessment. Legacy `runtime`, `mean_ms` and `official_timing` remain raw
caller context and cannot supply the new performance contract.

## Shared result schema 2.0

`compare` writes `compare_<a>_vs_<b>.json` and `.md`; `summarize-candidate` writes
`candidate_summary.json` and `.md`. Outputs default to the candidate's
`analysis/`; `--out-dir` changes the destination. The corresponding
`comparison_schema_version` and `candidate_summary_schema_version` are `"2.0"`.

Both contain `runs`, `source_artifacts`, `lineage`, `warnings`,
`performance_assessment` and `mechanism_assessment`. Roles are `baseline` and
`candidate`. Source artifacts include consumed profiler JSON hashes and local
benchmark imports. Candidate summaries also retain `inspection_targets` from
existing directions and simulator records. These are inspection aids.

### Performance assessment

`contract_version: "1.0"`; `mode` is single_run or comparison.

- `eligibility`: eligible/incomplete/blocked, all checks and reasons, both
  values and artifact/field references. Missing evidence is incomplete;
  invalid evidence, conflicts, correctness failure and mismatches are blocked.
  Blocked takes precedence while retaining missing-evidence reasons.
- `measurements`: original normalized baseline/candidate records, conflicting
  records when relevant, sources and `authority: caller_provided`.
- `comparison`: not_applicable for one run; not_comparable when checks fail;
  observed_only for two eligible records. `observation` is null unless comparable.
- `limitations`: caller method validity and uncertainty are not certified.

An observation contains `delta_ms = candidate_ms - baseline_ms` and
`speedup_pct = 100 * (baseline_ms - candidate_ms) / baseline_ms`, statistic,
faster/slower/equal direction and source citations. Positive speedup means an
elapsed-time reduction, not a throughput increase. Report it as observed in
these caller measurements. There is no automatic candidate selection policy.

### Mechanism assessment

`contract_version: "1.0"`; coverage is missing/partial/available/blocked.
Coverage describes the listed evidence questions, not proof of a mechanism.
The block contains profiler compatibility diagnostics, workload checks,
headlines, evidence, questions, findings, pending actions and benchmark links.

Headline differences retain the existing CANN workload, target, block, field,
metric-scope, finite-number and supported-schema requirements. CANN versions
must describe a common component; conflicts and equal strings from different
components remain blocked. Commands and output metadata are checked for the
segment actually used by each observation. Full segment inventories and global
readiness are diagnostics, not blanket gates for all families.

An unsupported Unit/Units layout or unknown metric field cannot produce a
delta. Missing or mismatched evidence retains original values and reasons.
A zero profiler baseline permits an absolute difference but no percentage.
Application headlines without explicit field/scope metadata remain descriptive.
Historical profiler records retain these checks without requiring a new
natural measurement contract.

Each question retains its family, available/missing artifact and field evidence,
blockers and next experiment. Existing memory/cache, pipe/arithmetic, workload
and generated-source questions use their own required evidence. Unrelated
simulator/family additions or pending actions do not invalidate a supported
observation. An action without a known question scope remains a pending gap.
Findings are `metric_observation` or `inspection_hypothesis`, with an evidence
level; they do not establish the cause of an observed speedup.

Benchmark association requires the implementation ID to match a recorded
payload/application SHA-256 and the recorded workload to agree. Different
payload and harness hashes represent different objects; matching the measured
one establishes the subject link. A linked measurement can supply workload
context while retaining original profiler-context conflicts. Generated-code
hypotheses require correctness for the inspected implementation. An unlinked
benchmark pass cannot supply it. Association failures do not change independent
natural-performance eligibility or erase raw profiler observations.

Correctness usability is checked by the benchmark evidence module, including
the tested implementation, required correctness fields and registered sources.
A declared compile or correctness failure prevents use of that record's pass;
a timing failure or incomplete timing protocol does not. Independently recorded
historical correctness remains usable when no benchmark record can be linked.

Markdown renders these same blocks, performance first, without recalculating
differences. `## Design Feedback` renders the nested mechanism questions.
