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

Evidence delivery has three layers: `reading_guide.md` renders run limits and
question routes; the cited summary subtrees contain observations and scope;
the raw inventory and exact records support verification. `key_metrics.txt`
remains an observation overview for existing callers and links to the guide.
Both render the same identity, coverage and quality context. Navigation derives
no new assessment status and never infers an unknown metric scope from a filename.
The packaged real matmul walkthrough illustrates this contract using preserved
repository fixtures; raw fixtures remain outside distribution artifacts.

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

## Normalized Evidence

`artifact_reader` decodes CSV and JSON. Format-specific normalizers select fields,
units and source locations into strict Pydantic facts. Original files retain
unknown fields and invalid tokens. `Summary`, `RawArtifactIndex`, `SimulatorModel`,
`BenchmarkRecord` and the assessment envelopes own the normalized contracts.
`RunEvidence` loads these models and exposes typed views to assessment and rendering.

Target binding, scope, coverage, selection and comparison admission remain explicit
domain rules. Producers and validators share their pure derivations. Validators
also check the presence of required conditions when authorizing a numeric
comparison or benchmark link. Scientific record rules live in `benchmark_types`;
input normalization attaches citations, and assessment reuses the same rules.
Validators perform no file reads; raw-fixture replay verifies that recorded citations match
the original fields. A valid model alone cannot prove raw-file authenticity.

Serialization occurs at output boundaries with finite JSON values and no default
stringification. Published JSON schemas are generated from the models; Python
validators also check derived-state consistency. External component errors retain
independent valid facts and located issues. Invalid required normalized input fails
loading; invalid optional profiler input records a warning while natural benchmark
assessment remains independent. Old normalized versions require regeneration from
their sources. There is no production compatibility reader.

## Evidence Rule

Natural-performance observations cite the caller's run-local benchmark snapshot
and measurement field. Mechanism observations cite profiler artifacts and fields,
such as `PipeUtilization.csv`, `Memory*.csv` or simulator line timing. Associating
them requires matching workload and measured implementation evidence; neither
observation alone establishes causality.

## Question-level consumption

`RunEvidence.question_evidence()` organizes existing run gates and normalized readers
into question-sized results. `question_evidence.py` owns selection and presentation,
not a second eligibility policy: Pipe, Arithmetic, Memory and application-timing
reads retain identity, per-segment coverage and measurement limits. CLI `evidence`
and the kernel-agent question adapter use this same result. Existing assessments,
summary paths and `joint-row` retain their contracts.

`evidence_binding.py` binds raw references by artifact content and CSV location,
and derived reads by an input manifest and report/log inventory. Added collections
invalidate old coverage snapshots, not unchanged raw references. Bindings are made
at query time; they do not certify historical summary generation. `application_events.py`
adds a per-invocation view without replacing duration statistics or aligning clocks
across files. Explicit field definitions extend the shared `OP_FIELDS` semantics;
unregistered raw columns stay visible as support gaps.
