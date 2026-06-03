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

`profile_tilelang_benchmark_run.py` is the default wrapper for the current
`tilelang-ascend-benchmark` repo shape. It creates `<run-dir>/harness/`,
`logs/`, `reports/`, and `analysis/`, writes separate canonical/app/op benchmark
scripts, runs the canonical benchmark outside profiling, collects app-level
`msprof`, collects `msprof op --aic-metrics=PipeUtilization`, validates required
profiler artifacts, runs the analyzer, and automatically executes the supported
`collect_default_metric_followup` action when Pipe-only evidence asks for
Default metrics. The follow-up writes raw profiler output under
`reports/followups/collect_default_metric_followup/`, validates
`OpBasicInfo.csv`, `PipeUtilization.csv`, `ArithmeticUtilization.csv`,
`Memory.csv`, `MemoryL0.csv`, `MemoryUB.csv`, and
`ResourceConflictRatio.csv`, then regenerates provenance, analysis, timeline,
and `<run-dir>/REPORT.md`. Use `--disable-followup-collection` to leave the
Pipe-only `next_collection_actions` recommendation pending. Use a fresh run
directory for each orchestrated collection; the helper rejects existing
benchmark/profile evidence rather than deleting or overwriting raw profiler
outputs. `--disable-op-profile` skips op and follow-up collection plus
required-op validation; it does not consume old `reports/op` files. Before
invoking this wrapper, confirm the benchmark repository's Python interpreter
and pass it explicitly with `--python-bin`; do not rely on the helper process
interpreter or record a fixed local virtualenv path in reusable command notes.

Pass `--dry-run` to print the orchestrator command plan as JSON without running
the benchmark, `msprof`, `npu-smi`, analyzer, provenance, timeline, follow-up,
or report steps. The dry-run plan includes the benchmark argv, intended harness
script content, app/op profiler commands, conditional Default follow-up command,
and expected output segments, but it does not create run artifacts and must not
be treated as profiler evidence.

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
│   ├── tilelang_benchmark_profile_run.json
│   ├── tilelang_context.json
│   └── tilelang_profile_run.json
└── REPORT.md
```

`tilelang_context.json` is report evidence only. It can explain the candidate
workload, runtime, correctness, payload source, JIT config, and debug artifact
inventory, but it does not create Ascend profiler diagnosis rows.

`profile_tilelang_benchmark_run.py` collects app + PipeUtilization first and
can run one Default metric follow-up from `next_collection_actions`. Simulator
collection, Source, TimelineDetail, MemoryDetail, recursive follow-up loops,
and KernelScale parsing are explicit future extensions. The lower level
`prepare_tilelang_profile_run.py` does not wrap `msprof` or optimize TileLang
kernels.
