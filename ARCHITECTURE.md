# Architecture

This repository is the committed surface for a hybrid Ascend 910B profiling
package: a human-maintained Codex skill plus an installable helper CLI. It must
be usable without local notes, raw downloads, or machine-specific profiling
output.

## Commit Surface

Commit durable skill assets:

- `README.md`, `AGENTS.md`, and this file.
- `skills/ascend-msprof-skill/` canonical Codex skill source.
- `src/ascend_msprof_skill/` importable parsers and CLI.
- `scripts/` validation tooling.
- `tests/fixtures/` small mock profiling outputs.
- `artifacts/` only for curated, provenance-stable examples.

Do not commit raw `PROF_*`, `OPPROF_*`, one-off `profile/` runs, downloaded
docs, or local migration notes. Keep those under ignored local paths.
The wheel/sdist surface is stricter than the commit surface: wheels package
the canonical skill source as `ascend_msprof_skill/skill/`, and distributions
must exclude tests, fixtures, local notes, downloads, Humanize state, and raw
profiling runs.

## Build Logic

The skill follows a three-step performance workflow:

```text
Frame question -> Collect or reuse evidence -> Assess
```

`skills/ascend-msprof-skill/SKILL.md` keeps the core workflow concise.
Detailed commands and interpretation rules live in that skill's `reference/`
directory. Deterministic extraction lives in the `ascend_msprof_skill` package
and is exposed through `ascend-msprof`.

The package owns msprof usage, extraction, evidence scope and assessment. It
returns observations and conditional collection recipes. The caller owns
kernel changes, experiment planning and candidate selection; evidence availability
does not create an optimization hypothesis.

## Source-First Rule

Do not add or materially change profiling guidance before collecting the
authoritative sources for that change. Official Ascend/CANN documentation is
the primary source for tool behavior, output files, command flags, and API
semantics. Local experiments and examples can validate behavior, but they do
not replace official references.

## Validation

Validate changed helpers, docs and fixtures with the repository validation and
unittest commands in AGENTS.md. Audit wheel/sdist contents before delivery.

## Assessment Interface

`assess_run(candidate, baseline=None)` computes independent performance and
mechanism results from loaded `RunEvidence`. `benchmark_evidence` validates
caller records; the importer owns snapshots and writes. CLI and report code
render the shared assessment. Profiler extraction remains in the existing
evidence modules. No evaluation function samples the device or runs commands.

`BenchmarkEvidence.correctness()` exposes correctness usability and cited issues
using the same rules as measurement validation. Consumers establish the profiler
subject link separately; they do not interpret raw pass flags or issue field names.

## Evidence Rule

Natural-performance observations cite the caller's run-local benchmark snapshot
and measurement field. Mechanism observations cite profiler artifacts and fields,
such as `PipeUtilization.csv`, `Memory*.csv` or simulator line timing. Associating
them requires matching workload and measured implementation evidence; neither
observation alone establishes causality.
