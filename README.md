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
```

## Validation

```bash
pip install -r requirements.txt
python3 scripts/validate.py
python3 -m unittest discover -s tests
```
