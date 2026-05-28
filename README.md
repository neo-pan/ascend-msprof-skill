# ascend-msprof-skill

A skill for building reproducible Ascend 910B profiling runs with CANN tools.
It uses Ascend-native artifacts: `msprof`, `msprof op`,
`msprof op simulator`, CANN CSV files, and timeline JSON.

## Scope

- Ascend 910B first; record the actual device, driver, firmware, and CANN
  versions in every run.
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
python3 helpers/extract_simulator_hotspots.py --run-dir profile/<run_name>
python3 helpers/plot_timeline.py --run-dir profile/<run_name>
```

## Validation

```bash
pip install -r requirements.txt
python3 scripts/validate.py
python3 -m unittest discover -s tests
```
