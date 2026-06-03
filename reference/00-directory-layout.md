# Profile Directory Layout

Create a new run directory for every profiling question:

```bash
PROFILE_RUN_DIR=profile/<run_name>
mkdir -p "$PROFILE_RUN_DIR"/{harness,reports,analysis}
```

Do not reuse a run for a new kernel version, shape, tiling path, or profiling
question.

## Standard Layout

```text
profile/<run_name>/
├── harness/
│   ├── <op>_harness.cpp
│   ├── build.sh
│   └── run.sh
├── reports/
│   ├── PROF_.../
│   ├── OPPROF_.../
│   └── sim/
├── analysis/
│   ├── summary.json
│   ├── tilelang_context.json
│   ├── tilelang_profile_run.json
│   ├── key_metrics.txt
│   ├── simulator_hotspots.json
│   ├── simulator_hotspots.txt
│   └── timeline.txt
└── REPORT.md
```

`reports/` stores raw profiler output. `analysis/` stores derived summaries.
`REPORT.md` is the user-facing conclusion.

`analysis/tilelang_context.json` is optional derived evidence for runs that
profile a TileLang candidate. It stores the benchmark result, payload source
content and checksums, and optional JIT debug artifact inventory without
modifying `reports/`.

`analysis/tilelang_profile_run.json` is optional workflow metadata written by
`helpers/prepare_tilelang_profile_run.py`. It records which derived artifacts
were created and whether an existing `reports/` directory was present before
preparation.

## Do Not Store

- Dataset files; reference them by absolute path.
- Raw downloads from documentation sites.
- Outputs from unrelated profiling runs.
- Build intermediates unless they are needed for reproduction.
