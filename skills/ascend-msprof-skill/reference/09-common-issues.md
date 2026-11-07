# Common Issues

## Pipeline Collection Completed But No Usable Waveform

Read [pipeline evidence](14-pipeline-evidence.md). A zero process exit can
coexist with a skipped target, failed argument dump, simulator initialization
failure. Device instruction/BIU collection and activity analysis are closed;
historical files stay raw audit inventory, including nonzero samples.
`ascend-msprof pipeline --run-dir <run>` reports closure and supported
simulation failure stages with raw references. Preserve valid app/op evidence.

For `Addr info is null` / `Kernel context save failed` on a generated kernel,
read [TD-001: argument capture descriptions](18-timeline-detail-capture-defect.md).
It records the open 9.1 defect, the validated workaround and the build/launch
integration required for a lasting repair. Confirm the failing stage and
actual metadata before assigning that cause to a new run.

When only a saved subset is available, distinguish absent retained files from
absent original output. Follow the command's output path and success/failure
receipts to retrieve usable partial artifacts before deciding to rerun. A
saved status such as 124 needs the owning runner's timeout receipt to identify
the deadline and cleanup; a model-completion line alone does not certify the
whole segment. Keep any justified retry bounded and use the option supported
by that specific helper or profiler command.

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

### Caller report versions after continuation

Executor continuation can add `analysis/caller_reports/<version>/caller_evidence.json`
without replacing the original `analysis/caller_evidence.json`. Read the intended
formal context with `ascend-msprof evidence --run-dir <run> --report-version <version>`.
The version is the SHA-256 of the report object encoded with Python
`json.dumps(report, sort_keys=True, separators=(",", ":")).encode()`. The loader verifies
that content identity as well as the original report byte hash. Without a version,
the reader preserves the historical caller context; it never guesses the latest
report. Missing versions do not supply another report's timing. The selected caller
manifest and its local report/source bytes are part of the query snapshot binding.

New Executor reports carry `metrics.formal_measurement_record` (schema version 2
and SHA-256). Use `--measurement-record <sha256>` to retain the same formal context
after host acceptance adds delivery metadata. This selector is mutually exclusive
with `--report-version`. The positive schema in `caller_record.py` includes formal
status, timing, correctness, source/compilation identity, protocol, collection and
sample/launch facts; it excludes its own reference, logs and derived navigation.
Changes to formal semantics require a schema revision.

`analysis/caller_records/<sha256>.json` binds one immutable caller manifest by path
and byte hash. The reader checks the sealed source report bytes and reconstructs
the record identity. A missing locator may use the legacy caller only if its record
identity matches; a damaged locator or a different measurement cannot substitute
another report. Query snapshots bind the locator (including absence), manifest,
and captured bytes. Repeated attachment of the same record reuses the original
sealed representation even if the input report is reformatted or gains host metadata.
Historical `--report-version` and unselected legacy reads keep their existing meaning.

Schema 1 keeps its original projection and hash contract. Readers validate the
schema declared by each reference; unknown versions are unavailable. Schema 2
projects collection context to `schema_version`, `collection_id` and `identity`;
the sealed sample set is already represented by the sample records. Reopening a
completed collection does not change identity just because episode, prior-attempt
or remaining-budget metadata changes. Historical attachments keep their original
schema and bytes; publishing a new schema does not overwrite old locators.

Caller authentication is separate from snapshot dependency enumeration. A missing
manifest, damaged locator or mismatched manifest hash makes caller context locally
unavailable while ordinary all-launch questions retain independent raw facts.
The snapshot binds available locator bytes and safe local dependencies, including
missing files, and old bindings become stale when those inputs change. An explicit
caller selection requires verified caller context for scored/aggregate queries;
invalid caller data cannot silently substitute another scoring range. Writers
still reject damaged existing bindings rather than overwriting them.
