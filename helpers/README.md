# Helpers

Reusable parsers for Ascend CANN profiling output.

```bash
python3 helpers/analyze_msprof_outputs.py --run-dir profile/<run>
python3 helpers/compare_runs.py --run-dir-a profile/<a> --run-dir-b profile/<b>
python3 helpers/extract_simulator_hotspots.py --run-dir profile/<run>
python3 helpers/plot_timeline.py --run-dir profile/<run>
```

All helpers write under `<run-dir>/analysis/` and tolerate missing optional
files with warnings.

