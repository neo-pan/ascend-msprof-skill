# CANN 8.5.2 workload comparison regression

Two real Ascend 910B2 vec-add collections from 2026-09-10, with shapes
`[128, 256]` and `[256, 256]`, float32, one correctness case. App/op/Default
were collected separately. These are local 8.5.2 format examples, not a
declaration of full 8.5.2 support or a natural-runtime speedup benchmark.

The fixture retains op and Default CSVs needed for the six headline groups,
their selected summary records, caller workload/target context, command and
status logs, and hardware/version evidence. App CSVs, JIT artifacts, unrelated
analysis, and profiler stdout are omitted. Absolute paths and profiler random
directory names are sanitized; PID is replaced by zero. Metric fields,
values, block identifiers, and workload values are preserved. CSV line
endings are normalized. Artifact references remain relative to each run.

`logs/toolkit_install.info` is historical metadata supplemented after these
collections, copied from the installed toolkit with `package_name` and
`version=8.5.2`; its installation path is redacted. It did not come from
automatic capture. The comment-only `cann_version.cfg` reproduces the original
missing version source. Tests remove the supplement to exercise that case.

Self-comparison checks the offline gates; it is not an independent measurement.
Tests that inject Unit/Units or rename a field are explicitly synthetic and
do not describe native CANN output.
