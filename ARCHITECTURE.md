# Architecture

This repository is the committed surface for an Ascend 910B profiling skill.
It must be usable without local notes, raw downloads, or machine-specific
profiling output.

## Commit Surface

Commit durable skill assets:

- `SKILL.md`, `README.md`, `AGENTS.md`, and this file.
- `ascend-910b-programming.md` for compact hardware/programming context.
- `reference/` workflow documents.
- `helpers/` reusable parsers and templates.
- `scripts/` validation tooling.
- `data/` controlled source and output-file indexes.
- `tests/fixtures/` small mock profiling outputs.
- `artifacts/` only for curated, provenance-stable examples.

Do not commit raw `PROF_*`, `OPPROF_*`, one-off `profile/` runs, downloaded
docs, or local migration notes. Keep those under ignored local paths.

## Build Logic

The skill follows a three-step performance workflow:

```text
Profile -> Diagnose -> Plan
```

`SKILL.md` keeps the core workflow concise. Detailed commands and interpretation
rules live in `reference/`. Deterministic extraction lives in `helpers/`.

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
```

## Evidence Rule

Every performance claim in a final report must cite a concrete profiling
artifact and field, such as `op_summary_*.csv` duration, `PipeUtilization.csv`
pipe usage, `Memory*.csv` bandwidth, `ResourceConflictRatio.csv` conflict
ratio, or simulator `core*_code_exe.csv` line timing.
