# Profile Directory Layout

Create a new run directory for every profiling question:

```bash
PROFILE_RUN_DIR=profile/<run_name>
mkdir -p "$PROFILE_RUN_DIR"/{harness,reports,logs,analysis}
```

Do not reuse a run for a new kernel version, shape, tiling path, or profiling
question.

## Standard Layout

```text
profile/<run_name>/
├── harness/
│   ├── profile_harness.json
│   ├── <op>_harness.cpp
│   ├── build.sh
│   └── run.sh
├── reports/
│   ├── PROF_.../
│   ├── OPPROF_.../
│   └── sim/
├── logs/
│   ├── command_msprof.txt
│   ├── command_msprof_op.txt
│   ├── cann_version.cfg
│   └── relevant_env.txt
├── analysis/
│   ├── summary.json
│   ├── profile_harness_run.json
│   ├── tilelang_context.json
│   ├── tilelang_profile_run.json
│   ├── key_metrics.txt
│   ├── simulator_hotspots.json
│   ├── simulator_hotspots.txt
│   └── timeline.txt
└── REPORT.md
```

`harness/` stores a caller-provided profile harness manifest and/or runnable
application when available. `reports/` stores raw profiler output. `logs/`
stores commands, environment captures, and profiler stdout/status files used
for provenance. `analysis/` stores derived summaries. `REPORT.md` is the
user-facing conclusion.

`analysis/tilelang_context.json` is optional derived evidence for runs that
profile a TileLang candidate. It stores the benchmark result, payload source
content and checksums, and optional JIT debug artifact inventory without
modifying `reports/`.

`analysis/tilelang_profile_run.json` is optional workflow metadata written by
`ascend-msprof prepare-tilelang`. It records which derived artifacts were
created and whether an existing `reports/` directory was present before
preparation.

`analysis/profile_harness_run.json` is optional workflow metadata written by
`ascend-msprof profile-harness`. It records which supplied manifest/application,
profiler commands, and derived artifacts were used.

`analysis/profile_context.json` is optional context written by
`ascend-msprof profile-harness`. It records the supplied manifest/application
and optional verify JSON as workload, correctness, and timing context only.
Profiler diagnoses still cite `reports/` artifacts and
`analysis/summary.json`.

## Do Not Store

- Dataset files; reference them by absolute path.
- Raw downloads from documentation sites.
- Outputs from unrelated profiling runs.
- Build intermediates unless they are needed for reproduction.
