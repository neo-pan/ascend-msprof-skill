# Pipeline Evidence: Collection, Quality and Visualization

Use this branch for Cube/Vector/MTE timing, apparent bubbles, instruction
timeline failures, or sampled pipeline activity. The focused command shapes and
failure diagnostics were exercised with an actual TileLang DFT kernel on CANN
8.5.2 / Ascend 910B2. That probe did not obtain a usable waveform or instruction
trace. CANN 8.5.2 is now the environment baseline; this negative probe remains
a launch-path-specific result. See the [capability matrix](15-cann852-capabilities.md)
for feature validation rather than assuming every route succeeds.

A separate native standalone pure-AIV probe on the current baseline succeeded
with a reduced 32-add workload, `--soc-version=Ascend910B2`, logical
`--core-id=0`, and `PipeUtilization,ResourceConflictRatio`. It produced correct
output and `core0.veccore0` trace, source-code and instruction CSV artifacts.
This establishes a working native simulation path for that workload. It does
not resolve the earlier framework argument-capture or all-zero device BIU
samples, and does not certify simulator PMSampling. The reduced simulation
workload differs from the 4096-add device workload; their durations are not a
performance comparison.

## Distinguish Sampling Modes

The [CANN 8.5 system collection reference](https://www.hiascend.com/document/detail/en/canncommercial/850/devaids/profiling/atlasprofiling_16_0012.html)
and [simulator waveform reference](https://www.hiascend.com/document/detail/en/canncommercial/850/devaids/optool/atlasopdev_16_0160.html)
describe three different measurements:

| Mode | Sampling scope | What it can establish |
|---|---|---|
| Application `--aic-mode=sample-based` with `--aic-freq` | System activity at 1–100 Hz | Coarse AI Core/Vector utilization, not a per-kernel instruction timeline. |
| Application `--instr-profiling=on` | 300–30000 cycle windows; A2/A3 single-operator scenario | Window activity/counters; requires nonzero usable samples, target scope and clocks. |
| Simulator `PMSampling` | Simulated memory-channel throughput for all cores; `--core-id` does not select this data | Simulated throughput waveforms, separate from device activity and latency. |

## Choose The Evidence

| Question | Route | Interpretation |
| --- | --- | --- |
| Which pipeline is active within sampled windows on the device? | `profile-pipeline --mode sampled` | Activity counts within clock-cycle windows; exact instruction intervals and overlap are unresolved. |
| Can the framework kernel capture produce an instruction chart? | `profile-pipeline --mode timeline-detail` | TimelineDetail depends on simulation and successful kernel argument capture. |
| Which instructions and synchronization events execute in simulation? | `profile-pipeline --mode simulator` | Simulation intervals; separate from device latency. |

[CANN 8.5 msProf documentation](https://www.hiascend.com/document/detail/en/canncommercial/850/devaids/optool/atlasopdev_16_0082.html)
documents TimelineDetail's simulation configuration, limited framework calling
scenarios, and incompatibility with application/range replay. Explicit simulator
metrics are a separate set; ResourceConflictRatio includes synchronization
event details. The helper checks installed help before collection.

## Supply The Actual Target And Entry

Use a caller-owned [harness manifest](02-harness-guide.md) with `application`,
optional `implementation`, and `target.kernel_selector` / `expected_launches`.
Read the generated entrypoint or bound profiler observations to populate the
target. Current TileLang callers can generate task-specific names rather than
`main_kernel`. A name default is not evidence that a target was collected.
Use the generated base entrypoint for `expected_launches`: app timing can report
that base while `msprof op` adds a core suffix such as `_mix_aic`. The selector
can select the observed op name or its prefix; the existing target matcher
recognizes core suffixes on observed names, not arbitrary reverse aliases.

For simulation routes, retain the environment injected by msprof. A shell
launcher that resets `LD_LIBRARY_PATH` or `LD_PRELOAD` can hide the simulator
libraries. The focused helper blocks recognized literal overrides and records
the launcher path, digest and diagnostic in `logs/pipeline_preflight.json`.
It leaves caller files unchanged. Use a run-local entry that invokes the same
application while preserving the injected variables. Binary launchers and
indirect shell behavior still require checking the resulting logs.

Device selection, correctness precheck and device scheduling remain with the
caller, as in `profile-harness`. Each command below needs a fresh run directory:

```bash
ascend-msprof profile-pipeline --run-dir profile/sampled \
    --manifest harness/profile_harness.json --mode sampled \
    --sample-period 300 --timeout-s 180

ascend-msprof profile-pipeline --run-dir profile/detail \
    --manifest harness/profile_harness.json --mode timeline-detail \
    --core-id 0 --timeout-s 180

ascend-msprof profile-pipeline --run-dir profile/simulator \
    --manifest harness/profile_harness.json --mode simulator \
    --soc-version Ascend910B2 --core-id '0|31' --timeout-s 180
```

The selected core IDs are examples, not representative-core guarantees. Check
the workload's core mapping before selecting them. Simulator logical parser
IDs are not automatically physical AIC IDs or CSV `block_id` values; confirm
the mapping from actual trace lanes and launch records. Sampling accepts 300–30000
cycles (default 1000), omits conflicting runtime-api/task-time options, and
profiles the supplied application's launch scope. TimelineDetail uses kernel
replay. Explicit simulator collection selects PipeUtilization and
ResourceConflictRatio. No mode silently falls back to a different mode.

## Inspect Completion And Data Quality

`analyze` automatically writes `analysis/pipeline_evidence.json` and surfaces
its issues in summary warnings and reading guidance. For focused inspection:

```bash
ascend-msprof pipeline --run-dir profile/sampled
```

This artifact retains diagnostic codes, source log lines and sampled database
digests. `BiuCycles` is inspected with a read-only SQLite connection: record
count, core lanes, distinct timestamps, nonzero timestamps and nonzero activity
rows. Empty, constant-zero or undecodable samples remain unusable for pipeline
claims. Passing these minimum checks establishes neither target/launch binding
nor aligned cross-core clocks or exact overlap. The inspection does not modify
the raw database. A normal application profile can emit an empty
`biu_perf.db` even when instruction sampling was not requested; that placeholder
is not a failed sampling attempt. An explicit sampling request with missing
`BiuCycles` remains a collection gap.

Read `analysis/profile_pipeline_run.json` separately from the process receipt.
The focused CLI returns 1 for known evidence failures, 2 for preflight/setup
failures, and 0 when no blocking issue was identified; 0 still requires target,
coverage and artifact inspection. `inspect_target_and_coverage` is not a verdict
that an instruction trace was obtained. Raw per-process results retain their
actual return codes. Existing valid app/op metadata remains available when an
optional instruction capture fails.

| Observed diagnostic | Next useful check |
| --- | --- |
| `target_not_selected` | Compare the skipped name with the declared selector and other collected targets; unrelated skipped kernels do not invalidate a collected target. |
| `kernel_argument_dump_failed`, `timeline_detail_failed` | Inspect framework launch/capture compatibility and saved arguments; OpBasicInfo or an opaque binary alone does not supply an instruction timeline. |
| `simulator_library_load_failed` | Check selected simulator libraries and launcher environment. |
| `framework_simulator_api_failed`, `profiled_application_failed` | Locate whether framework initialization failed before kernel execution; consider a caller-owned ACL or actual-binary config route. |
| `unusable_pipeline_samples` | Inspect timestamp/counter quality; all-zero data is not evidence of idle pipelines. |

## Render Obtained Instruction Intervals

```bash
ascend-msprof timeline --run-dir profile/simulator --svg
```

The source-repository fixture
`tests/fixtures/real_cann852_simulator_minimal/` preserves the successful
native probe's trace, code/instruction CSVs and sanitized source. Its 32 `VADD`
complete events map to the kernel's Add source line, supporting instruction and
source attribution in that simulation. Some other source rows have unavailable
line numbers; keep those local mapping gaps instead of inferring locations.
Source-line and instruction cycles/times have different attribution scopes and
cannot be added together or used as natural elapsed time.

The text duration ranking remains available. SVGs use valid complete `X`
instruction events from each admitted simulator trace, preserve raw pid/tid
lanes, cite source SHA256 and timestamps, and normalize the displayed origin
within that file. `analysis/timeline_svg_index.json` lists the separate outputs.
Trace files are not merged onto an assumed shared clock. B/E and flow records
are not paired into invented wait durations. A trace without complete intervals
produces no SVG.

Sampled counters stay window activity rather than contiguous bars. To explain
bubble hiding, first verify the actual source dependencies and overlapping
intervals; a fused launch or simultaneous aggregate utilization is insufficient.
Source-level global barriers can separate Vector preparation and Cube compute.
The renderer does not calculate overlap percentages or establish causality.
