# Agent Instructions

This repo is a hybrid Codex skill and helper CLI package for Ascend 910B
kernel/operator profiling. The canonical skill source lives under
`skills/ascend-msprof-skill/`; wheel builds package it as
`ascend_msprof_skill/skill/`.

## Rules

- Collect authoritative Ascend/CANN sources before writing or changing formal
  workflow, command, parser, or diagnosis guidance.
- If `AGENTS.local.md` exists, read it for host-local setup notes. It is ignored
  by git and must not be committed.
- Keep analysis Ascend-native. Do not import metric names or diagnostic labels
  from other accelerator profiling stacks.
- Preserve raw profiler outputs under `profile/<run>/reports/`; never mix runs.
- Prefer standalone ACL/Ascend C harnesses when profiling an isolated kernel is
  feasible.
- Cite exact artifacts and fields in every diagnosis.
- Keep local research and raw downloads under `local-notes/` or `downloads/`;
  they are intentionally ignored.

## Practical Priorities

- Optimize for helping the calling agent understand real Ascend code: locate
  important runtime cost, connect profiler evidence to source and workload,
  assess an explanation, and identify the next useful verification.
- Ground implementation and review findings in an actual use case or a
  plausible collection failure. State the user-visible consequence before
  assigning priority. Block on failures of supported workflows or misleading
  timing, target attribution, or code interpretation. Treat synthetic extreme
  inputs without a plausible production path as non-blocking robustness work.
- Validate with representative kernel development records and real workloads.
  Exercise the path from source and collection through analysis to a useful
  answer; parser tests and internally consistent models alone do not establish
  that the skill helps a caller diagnose performance.
- Prefer small changes at the responsible boundary. Preserve useful partial
  evidence, reuse existing artifacts, and collect only what the current
  question needs. Add abstractions and validation rules when they solve a
  demonstrated workflow problem.
- Finish a review when the selected real-world questions have supported answers
  or specific, actionable evidence gaps. Record unrelated hardening separately;
  exhaustive edge-case coverage is not the completion criterion.

## Validation

Run after modifying docs, helpers, data files, or fixtures:

```bash
python3 scripts/validate.py
python3 -m unittest discover -s tests
```
