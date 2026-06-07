# Agent Instructions

This repo packages a Codex skill and helper CLI for Ascend 910B
kernel/operator profiling.

## Rules

- Collect authoritative Ascend/CANN sources before writing or changing formal
  workflow, command, parser, or diagnosis guidance.
- Keep analysis Ascend-native. Do not import metric names or diagnostic labels
  from other accelerator profiling stacks.
- Preserve raw profiler outputs under `profile/<run>/reports/`; never mix runs.
- Prefer standalone ACL/Ascend C harnesses when profiling an isolated kernel is
  feasible.
- Cite exact artifacts and fields in every diagnosis.
- Keep local research and raw downloads under `local-notes/` or `downloads/`;
  they are intentionally ignored.

## Validation

Run after modifying docs, helpers, data files, or fixtures:

```bash
python3 scripts/validate.py
python3 -m unittest discover -s tests
```

## Humanize Workflow

For multi-step feature work, use the Humanize RLCR workflow:

1. Draft the implementation plan under `local-notes/`.
2. Start RLCR from that plan after completing the required plan-understanding
   pre-flight.
3. Keep `.humanize/` state local-only.
4. Commit only durable repo changes after validation and review pass.
