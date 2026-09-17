# Common Issues

## `msprof` Not Found

Source the CANN environment script for the installed toolkit, then recheck
`which msprof`.

## Output Directory Has No Expected CSV Files

Confirm the target application actually launched the target operator and that
the selected profiling mode matches the question. Some files are emitted only by
`msprof op` or simulator mode.

## Simulator Timing Does Not Match Device Timing

Use simulator files for attribution, pipeline shape, and hotspots. Use on-device
`msprof` / `msprof op` output for elapsed-time claims.

## Version-Specific Columns

CANN can rename columns. Helpers use aliases and preserve raw rows, but final
reports should name the actual file and field used.

## Concurrent Profiling

Avoid running multiple profiling sessions on the same device unless the CANN
version explicitly supports it.

## Synthetic Shapes Hide The Bottleneck

For variable-shape workloads, profile representative real shapes. Uniform
synthetic shapes can hide core imbalance and tail effects.

## Op Family Missing After `--kernel-name`

When every expected operator family is absent and `target_identity` is
`missing_observed`, compare `profile_coverage.kernel_selector` (the
`msprof op --kernel-name` value) with profiler `Op Name` fields in command
logs and application timing CSVs. An empty observed-name list is an identity
and coverage fact. Do not treat it as a missing Default metric-scope
collection, and do not add a new collection action id. Fix the selector or
the declared names, then recollect the same intended scope.
