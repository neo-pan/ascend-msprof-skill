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

Expected layout after collection:

```text
profile/<run>/
├── reports/
├── analysis/
│   ├── summary.json
│   └── tilelang_context.json
└── REPORT.md
```

`tilelang_context.json` is report evidence only. It can explain the candidate
workload, runtime, correctness, payload source, JIT config, and debug artifact
inventory, but it does not create Ascend profiler diagnosis rows. This helper
does not wrap `msprof`, orchestrate profiler collection, parse Source,
TimelineDetail, MemoryDetail, or KernelScale outputs, or optimize TileLang
kernels.
