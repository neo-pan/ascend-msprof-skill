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
Profile -> Diagnose -> Plan
```

`skills/ascend-msprof-skill/SKILL.md` keeps the core workflow concise.
Detailed commands and interpretation rules live in that skill's `reference/`
directory. Deterministic extraction lives in the `ascend_msprof_skill` package
and is exposed through `ascend-msprof`.

## Source-First Rule

Do not add or materially change profiling guidance before collecting the
authoritative sources for that change. Official Ascend/CANN documentation is
the primary source for tool behavior, output files, command flags, and API
semantics. Local experiments and examples can validate behavior, but they do
not replace official references.

## Humanize Development

Use the Humanize RLCR loop for non-trivial changes: write a plan under
`local-notes/`, run the loop from that plan, and let Codex review gate the
implementation. The `.humanize/` runtime state and `local-notes/` plans are
local-only and must not be committed.

Small mechanical fixes can be made directly, but still run:

```bash
python3 scripts/validate.py
python3 -m unittest discover -s tests
python3 -m build
python3 scripts/check_dist_contents.py dist/*
```

## Evidence Rule

Every performance claim in a final report must cite a concrete profiling
artifact and field, such as `op_summary_*.csv` duration, `PipeUtilization.csv`
pipe usage, `Memory*.csv` bandwidth, `ResourceConflictRatio.csv` conflict
ratio, or simulator `core*_code_exe.csv` line timing.
