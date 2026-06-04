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
├── SKILL.md
├── ARCHITECTURE.md
├── AGENTS.md
├── ascend-910b-programming.md
├── reference/
├── helpers/
├── scripts/
├── data/
└── tests/fixtures/
```

Per-run profiling artifacts should live outside committed files:

```text
profile/<run_name>/
├── reports/
├── logs/
├── analysis/
└── REPORT.md
```

Set the profiled entrypoint explicitly before collection:

```bash
PROFILE_RUN_DIR=profile/<run_name>
APPLICATION=path/to/run.sh
mkdir -p "$PROFILE_RUN_DIR"/{reports,logs,analysis}

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

## Helper Usage

```bash
python3 helpers/analyze_msprof_outputs.py --run-dir profile/<run_name>
python3 helpers/compare_runs.py --run-dir-a profile/<baseline> --run-dir-b profile/<optimized>
python3 helpers/collect_tilelang_context.py --run-dir profile/<run_name> --payload-src path/to/kernel_payload.py --benchmark-json path/to/result.json
python3 helpers/extract_simulator_hotspots.py --run-dir profile/<run_name>
python3 helpers/generate_provenance.py --run-dir profile/<run_name>
python3 helpers/generate_report.py --run-dir profile/<run_name>
python3 helpers/plot_timeline.py --run-dir profile/<run_name>
python3 helpers/prepare_tilelang_profile_run.py --run-dir profile/<candidate> --payload-src path/to/kernel_payload.py --benchmark-json path/to/result.json
```

`compare_runs.py` treats `--run-dir-a` as the baseline and `--run-dir-b` as the
candidate. It writes structured JSON and Markdown comparison artifacts under
the candidate run's `analysis/` directory by default.

`analyze_msprof_outputs.py` writes `analysis/simulator_hotspots.json` as a
structured simulator source/pipeline model. `extract_simulator_hotspots.py`
writes the same JSON plus the optional Markdown
`analysis/simulator_hotspots.txt` for human inspection.

Use a fresh `profile/<run_name>` directory for each collection. Preserve raw
profiler outputs under `reports/`, record profiler commands under `logs/`, and
run `generate_provenance.py` before report generation when command logs or
environment files are available.

## Validation

```bash
pip install -r requirements.txt
python3 scripts/validate.py
python3 -m unittest discover -s tests
```
