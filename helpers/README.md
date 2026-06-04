# Helpers

Reusable parsers for Ascend CANN profiling output.

```bash
python3 helpers/analyze_msprof_outputs.py --run-dir profile/<run>
python3 helpers/compare_runs.py --run-dir-a profile/<a> --run-dir-b profile/<b>
python3 helpers/collect_tilelang_context.py --run-dir profile/<run> --payload-src path/to/kernel_payload.py --benchmark-json path/to/result.json --jit-debug-root path/to/tilelang-jit-debug
python3 helpers/extract_simulator_hotspots.py --run-dir profile/<run>
python3 helpers/generate_provenance.py --run-dir profile/<run>
python3 helpers/generate_report.py --run-dir profile/<run>
python3 helpers/plot_timeline.py --run-dir profile/<run>
python3 helpers/prepare_tilelang_profile_run.py --run-dir profile/<candidate> --payload-src path/to/kernel_payload.py --benchmark-json path/to/result.json --jit-debug-root path/to/tilelang-jit-debug
```

Analysis helpers write under `<run-dir>/analysis/` and tolerate missing
optional files with warnings. `generate_provenance.py` fills missing
environment logs under `logs/`, reads existing profiler command/status logs,
and writes `analysis/provenance.json`, including structured app/op profile
output segments when the app-level `msprof` and `msprof op` collections are
both present. `generate_report.py` reads existing analysis, runs the analyzer
if `analysis/summary.json` is missing, and writes `<run-dir>/REPORT.md`.

`compare_runs.py` reads two existing `analysis/summary.json` files plus
optional `analysis/provenance.json`, `analysis/tilelang_context.json`, and
`analysis/raw_artifact_index.json`. It writes
`analysis/compare_<a>_vs_<b>.json` and `.md` under the candidate run by
default, or under `--out-dir` when provided. Treat `--run-dir-a` as the
baseline and `--run-dir-b` as the candidate. Compatibility mismatches are
recorded as comparison warnings, not as hard failures.

`analysis/summary.json` is the canonical structured evidence source for
agents. The analyzer also writes `analysis/raw_artifact_index.json`, a
deterministic audit index of parser-visible raw artifacts under the run, and
`analysis/simulator_hotspots.json`, a structured simulator model when simulator
artifacts are present or absent. The analyzer writes `analysis_schema_version`,
`analysis_dimensions`, `optimization_directions`, and
`next_collection_actions` when applicable. Use `optimization_directions` as
inspection priorities, then satisfy `next_collection_actions` before proposing
kernel changes. Do not diagnose from stdout alone, simulator context alone, or
one metric headline; do not claim bottlenecks or use non-Ascend profiling
labels. See `reference/10-summary-schema.md`.

`collect_tilelang_context.py` records benchmark evidence for a profiled
TileLang candidate. It reads an existing benchmark result JSON and payload
source file, preserves the payload content and checksums in
`<run-dir>/analysis/tilelang_context.json`, and optionally inventories files
under a TileLang JIT debug directory. A missing `--jit-debug-root` path records
a warning but does not fail the command.

`prepare_tilelang_profile_run.py` is the lower-level wrapper for an existing
TileLang kernel/candidate profiling run. It creates/checks
`<run-dir>/analysis/` and `reports/`, calls the context collector, generates
`<run-dir>/REPORT.md`, and writes
`<run-dir>/analysis/tilelang_profile_run.json`. When `reports/` already exists,
the helper verifies that no raw report file changed during preparation.

Expected layout after collection:

```text
profile/<run>/
├── reports/
├── analysis/
│   ├── summary.json
│   ├── raw_artifact_index.json
│   ├── tilelang_context.json
│   └── tilelang_profile_run.json
└── REPORT.md
```

`tilelang_context.json` is report evidence only. It can explain the candidate
workload, runtime, correctness, payload source, JIT config, and debug artifact
inventory, but it does not create Ascend profiler diagnosis rows.

The lower level `prepare_tilelang_profile_run.py` does not wrap `msprof` or
optimize TileLang kernels.
