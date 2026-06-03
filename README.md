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
├── harness/
├── reports/
├── analysis/
└── REPORT.md
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
PYTHON_BIN=<confirmed-benchmark-repo-python>
python3 helpers/profile_tilelang_benchmark_run.py --dry-run --run-dir profile/<candidate> --benchmark-repo /data/code/ref/tilelang-ascend-benchmark --payload-src examples/kernel_payload_baseline.py --task svd --warmups 0 --repeats 1 --baseline-ms 1.0 --python-bin "$PYTHON_BIN"
python3 helpers/profile_tilelang_benchmark_run.py --run-dir profile/<candidate> --benchmark-repo /data/code/ref/tilelang-ascend-benchmark --payload-src examples/kernel_payload_baseline.py --task svd --warmups 0 --repeats 1 --baseline-ms 1.0 --python-bin "$PYTHON_BIN"
python3 helpers/prepare_tilelang_profile_run.py --run-dir profile/<candidate> --payload-src path/to/kernel_payload.py --benchmark-json path/to/result.json
```

`compare_runs.py` treats `--run-dir-a` as the baseline and `--run-dir-b` as the
candidate. It writes structured JSON and Markdown comparison artifacts under
the candidate run's `analysis/` directory by default.

`analyze_msprof_outputs.py` writes `analysis/simulator_hotspots.json` as a
structured simulator source/pipeline model. `extract_simulator_hotspots.py`
writes the same JSON plus the optional Markdown
`analysis/simulator_hotspots.txt` for human inspection.

Use a fresh `profile/<candidate>` directory for
`profile_tilelang_benchmark_run.py`; it refuses existing benchmark/profile
evidence rather than overwriting raw profiler outputs. `--disable-op-profile`
skips op and follow-up collection plus required-op validation; it does not
consume old `reports/op` files. By default, Pipe-only orchestrator runs execute
the supported `collect_default_metric_followup` action and store its Default
metric output under `reports/followups/collect_default_metric_followup/`; pass
`--disable-followup-collection` to leave that recommendation pending. Before
invoking it, confirm the benchmark repository's Python interpreter and pass it
with `--python-bin`; do not rely on the helper process interpreter or record a
fixed local virtualenv path in reusable command notes.

Use `--dry-run` first when you need to review the exact benchmark, app-level
`msprof`, operator-level `msprof op`, and conditional Default follow-up
commands. Dry-run prints a JSON command plan to stdout, validates the same
fresh-run inputs, and does not create profiler logs, reports, analysis
artifacts, provenance, or `REPORT.md`; it is command-review evidence only, not
profiler evidence.

## Validation

```bash
pip install -r requirements.txt
python3 scripts/validate.py
python3 -m unittest discover -s tests
```
