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
optional files with warnings. `generate_provenance.py` reads existing
`logs/` files and writes `analysis/provenance.json`. `generate_report.py` reads
existing analysis, runs the analyzer if `analysis/summary.json` is missing, and
writes `<run-dir>/REPORT.md`.

`collect_tilelang_context.py` records benchmark evidence for a profiled
TileLang candidate. It reads an existing benchmark result JSON and payload
source file, preserves the payload content and checksums in
`<run-dir>/analysis/tilelang_context.json`, and optionally inventories files
under a TileLang JIT debug directory. A missing `--jit-debug-root` path records
a warning but does not fail the command.

`prepare_tilelang_profile_run.py` is the workflow wrapper for a generic
TileLang kernel/candidate. It creates/checks `<run-dir>/analysis/` and
`reports/`, calls the context collector, generates `<run-dir>/REPORT.md`, and
writes `<run-dir>/analysis/tilelang_profile_run.json`. When `reports/` already
exists, the helper verifies that no raw report file changed during preparation.

Expected layout after collection:

```text
profile/<run>/
├── reports/
├── analysis/
│   ├── summary.json
│   ├── tilelang_context.json
│   └── tilelang_profile_run.json
└── REPORT.md
```

`tilelang_context.json` is report evidence only. It can explain the candidate
workload, runtime, correctness, payload source, JIT config, and debug artifact
inventory, but it does not create Ascend profiler diagnosis rows. This helper
does not wrap `msprof`, orchestrate profiler collection, parse Source,
TimelineDetail, MemoryDetail, or KernelScale outputs, or optimize TileLang
kernels.
