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
PYTHON_BIN=<confirmed-benchmark-repo-python>
python3 helpers/profile_tilelang_benchmark_run.py --run-dir profile/<candidate> --benchmark-repo /data/code/ref/tilelang-ascend-benchmark --payload-src examples/kernel_payload_baseline.py --task svd --warmups 0 --repeats 1 --baseline-ms 1.0 --python-bin "$PYTHON_BIN"
python3 helpers/prepare_tilelang_profile_run.py --run-dir profile/<candidate> --payload-src path/to/kernel_payload.py --benchmark-json path/to/result.json --jit-debug-root path/to/tilelang-jit-debug
```

Analysis helpers write under `<run-dir>/analysis/` and tolerate missing
optional files with warnings. `generate_provenance.py` reads existing
`logs/` files and writes `analysis/provenance.json`, including structured
app/op profile output segments when the app-level `msprof` and `msprof op`
collections are both present. `generate_report.py` reads existing analysis,
runs the analyzer if `analysis/summary.json` is missing, and writes
`<run-dir>/REPORT.md`.

`analysis/summary.json` is the canonical structured evidence source for
agents. The analyzer writes `analysis_schema_version`, `analysis_dimensions`,
`optimization_directions`, and `next_collection_actions` when applicable. Use
`optimization_directions` as inspection priorities, then satisfy
`next_collection_actions` before proposing kernel changes. Do not diagnose from
stdout alone, do not claim a bottleneck from one metric headline, and do not
use non-Ascend profiling labels. See `reference/10-summary-schema.md`.

`collect_tilelang_context.py` records benchmark evidence for a profiled
TileLang candidate. It reads an existing benchmark result JSON and payload
source file, preserves the payload content and checksums in
`<run-dir>/analysis/tilelang_context.json`, and optionally inventories files
under a TileLang JIT debug directory. A missing `--jit-debug-root` path records
a warning but does not fail the command.

`profile_tilelang_benchmark_run.py` is the default wrapper for the current
`tilelang-ascend-benchmark` repo shape. It creates `<run-dir>/harness/`,
`logs/`, `reports/`, and `analysis/`, writes separate canonical/app/op benchmark
scripts, runs the canonical benchmark outside profiling, collects app-level
`msprof`, collects `msprof op --aic-metrics=PipeUtilization`, validates required
profiler artifacts, captures provenance logs, runs the analyzer/timeline
helpers, and writes `<run-dir>/REPORT.md`. Use a fresh run directory for each
orchestrated collection; the helper rejects existing benchmark/profile evidence
rather than deleting or overwriting raw profiler outputs. `--disable-op-profile`
skips op collection and required-op validation; it does not consume old
`reports/op` files. Before invoking this wrapper, confirm the benchmark
repository's Python interpreter and pass it explicitly with `--python-bin`; do
not rely on the helper process interpreter or record a fixed local virtualenv
path in reusable command notes.

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
│   ├── tilelang_benchmark_profile_run.json
│   ├── tilelang_context.json
│   └── tilelang_profile_run.json
└── REPORT.md
```

`tilelang_context.json` is report evidence only. It can explain the candidate
workload, runtime, correctness, payload source, JIT config, and debug artifact
inventory, but it does not create Ascend profiler diagnosis rows.

`profile_tilelang_benchmark_run.py` v1 collects app + PipeUtilization only.
Broader metric sets, simulator collection, Source, TimelineDetail,
MemoryDetail, and KernelScale parsing are explicit future extensions. The lower
level `prepare_tilelang_profile_run.py` does not wrap `msprof` or optimize
TileLang kernels.
