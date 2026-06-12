# ascend-msprof-skill

A skill for building reproducible Ascend 910B profiling runs with CANN tools.
It uses Ascend-native artifacts: `msprof`, `msprof op`,
`msprof op simulator`, CANN CSV files, and timeline JSON.

## Scope

- Current validated baseline: Ascend 910B/910B2 with CANN
  `8.3.0.2.220:8.3.RC2`. Newer CANN versions require separate command and
  output validation before updating formal guidance.
- Record the actual device, driver, firmware, and CANN versions in every run.
- Ascend C kernels and custom operators first.
- CLI-first analysis. MindStudio Insight artifacts are preserved, but helpers
  parse public files written by CANN tools.

## Layout

```text
.
├── ARCHITECTURE.md
├── AGENTS.md
├── pyproject.toml
├── skills/ascend-msprof-skill/
├── src/ascend_msprof_skill/
├── scripts/
└── tests/fixtures/
```

The human-maintained Codex skill source lives under
`skills/ascend-msprof-skill/`. Wheel builds package that directory as
`ascend_msprof_skill/skill/` so the installed helper CLI can locate the same
release's skill resources.

Per-run profiling artifacts should live outside committed files:

```text
profile/<run_name>/
├── harness/
├── reports/
├── logs/
├── analysis/
└── REPORT.md
```

If a benchmark skill or calling agent has already produced a profile harness
manifest, keep benchmark-specific harness rendering in that layer and pass only
the concrete harness/application to this skill:

This skill profiles a supplied profile harness manifest or direct application
path; it does not create benchmark-specific harnesses.

```bash
ascend-msprof profile-harness \
  --run-dir profile/<run_name> \
  --manifest profile/<run_name>/harness/profile_harness.json \
  --verify-json profile/<run_name>/context/verify.json
```

`--verify-json` is optional. When supplied, it is rendered as workload,
correctness, and timing context from `analysis/profile_context.json`; diagnosis
and optimization directions still require profiler artifacts under `reports/`
and `analysis/summary.json`.
The helper supports `--preset triage`, `--preset default-depth`, and
`--preset full`. Omitting `--preset` uses `triage`: app-level `msprof` plus
`msprof op --aic-metrics=PipeUtilization`. `default-depth` adds a separate
Default metric follow-up segment, and `full` currently adds that same Default
segment plus optional simulator collection only when `--simulator` is supplied.

After a triage run, the helper can append the supported Default follow-up when
`analysis/summary.json` recommends `collect_default_metric_followup`:

```bash
ascend-msprof profile-harness \
  --run-dir profile/<run_name> \
  --follow-next-actions \
  --continue-from-summary
```

This continue mode reuses `analysis/profile_harness_run.json`, refuses to
overwrite existing follow-up output, and records run/skipped/blocked actions in
that workflow metadata. Other recommended actions are recorded as skipped until
the helper supports safe automation for them.

`--simulator` is optional and disabled by default. Enable it when source-line,
instruction, or pipeline attribution is worth the extra collection time; the
wrapper still keeps app-level `msprof` and `msprof op PipeUtilization` as the
default collection path. Optional simulator failures are recorded as warnings
while preserving app/op results for analysis and reporting.
Append `--simulator` to the `profile-harness` command for that extra collection,
and use `--simulator-timeout-s <seconds>` only with `--simulator`.

The direct application form is:

```bash
ascend-msprof profile-harness \
  --run-dir profile/<run_name> \
  --application path/to/run.sh
```

Set the profiled entrypoint explicitly before collection:

```bash
PROFILE_RUN_DIR=profile/<run_name>
APPLICATION=path/to/run.sh
mkdir -p "$PROFILE_RUN_DIR"/{reports,logs,analysis}
PROFILE_RUN_DIR=$(realpath "$PROFILE_RUN_DIR")
APPLICATION=$(realpath "$APPLICATION")

MSPROF_APP_CMD=(
  msprof
  --output="$PROFILE_RUN_DIR/reports/app"
  --application="$APPLICATION"
  --runtime-api=on
  --task-time=on
  --ai-core=on
  --aic-metrics=PipeUtilization
  --type=text
  --summary-format=csv
)
printf "%q " "${MSPROF_APP_CMD[@]}" > "$PROFILE_RUN_DIR/logs/command_msprof.txt"
printf "\n" >> "$PROFILE_RUN_DIR/logs/command_msprof.txt"
"${MSPROF_APP_CMD[@]}"

MSPROF_OP_CMD=(
  msprof
  op
  --output="$PROFILE_RUN_DIR/reports/op"
  --application="$APPLICATION"
  --aic-metrics=PipeUtilization
)
printf "%q " "${MSPROF_OP_CMD[@]}" > "$PROFILE_RUN_DIR/logs/command_msprof_op.txt"
printf "\n" >> "$PROFILE_RUN_DIR/logs/command_msprof_op.txt"
"${MSPROF_OP_CMD[@]}"
```

## Install

For normal CLI use, install the Python package so the helper executable and its
runtime dependencies are available:

```bash
pip install ascend-msprof-skill
```

For source-tree development, install the package in editable mode so the
`ascend-msprof` console script is available:

```bash
pip install -e .
```

For private wheel delivery, build and install the wheel:

```bash
python3 -m build
pip install dist/ascend_msprof_skill-0.1.0-py3-none-any.whl
```

To register the Codex skill from a source checkout, use
`skills/ascend-msprof-skill/`. From an installed package, use
`ascend-msprof skill path` to print the packaged skill resource path.
Installing or registering only the skill directory does not install the Python
runtime helpers or make `ascend-msprof` executable.

## CLI Usage

```bash
ascend-msprof analyze --run-dir profile/<run_name>
ascend-msprof compare --run-dir-a profile/<baseline> --run-dir-b profile/<optimized>
ascend-msprof collect-tilelang --run-dir profile/<run_name> --payload-src path/to/kernel_payload.py --benchmark-json path/to/result.json
ascend-msprof sim-hotspots --run-dir profile/<run_name>
ascend-msprof provenance --run-dir profile/<run_name>
ascend-msprof profile-harness --run-dir profile/<run_name> --manifest profile/<run_name>/harness/profile_harness.json [--verify-json profile/<run_name>/context/verify.json] [--simulator]
ascend-msprof profile-harness --run-dir profile/<run_name> --follow-next-actions --continue-from-summary
ascend-msprof report --run-dir profile/<run_name>
ascend-msprof timeline --run-dir profile/<run_name>
ascend-msprof prepare-tilelang --run-dir profile/<candidate> --payload-src path/to/kernel_payload.py --benchmark-json path/to/result.json
ascend-msprof summarize-candidate --run-dir profile/<candidate> --baseline-run-dir profile/<baseline>
```

`ascend-msprof compare` treats `--run-dir-a` as the baseline and `--run-dir-b` as the
candidate. It writes structured JSON and Markdown comparison artifacts under
the candidate run's `analysis/` directory by default and records a conservative
top-level verdict.

`summarize_candidate.py` writes `analysis/candidate_summary.json` and
`analysis/candidate_summary.md` from existing run artifacts. It does not run
`msprof`, call benchmark-side tools, inspect benchmark source repos, or modify
`reports/`.

`analyze_msprof_outputs.py` writes `analysis/simulator_hotspots.json` as a
structured simulator source/pipeline model. `extract_simulator_hotspots.py`
writes the same JSON plus the optional Markdown
`analysis/simulator_hotspots.txt` for human inspection. For TileLang kernels,
set `TL_ASCEND_DEBUG_INFO=1` and `TMPDIR=profile/<run_name>/tilelang_tmp`
before launching the profiled application if simulator source-line output
should include run-local generated compile source snippets.

`analysis/summary.json` also includes `evidence_readiness`, an additive audit
of available evidence families, missing evidence, allowed or blocked claims,
recommended follow-ups, and preserved unparsed binary profiler artifacts.
`REPORT.md` renders a concise Evidence Readiness section. Treat it as a guide
for whether more profiler evidence is needed, not as a kernel-quality score or
candidate verdict.

Use a fresh `profile/<run_name>` directory for each collection. Preserve raw
profiler outputs under `reports/`, record profiler commands under `logs/`, and
run `ascend-msprof provenance` before report generation when command logs or
environment files are available.

The Codex skill bundle path is available with:

```bash
ascend-msprof skill path
```

Use that path when registering the installed package's skill resources with
Codex.

## Validation

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
python3 scripts/validate.py
python3 -m unittest discover -s tests
python3 -m build
python3 scripts/check_dist_contents.py dist/*
```
