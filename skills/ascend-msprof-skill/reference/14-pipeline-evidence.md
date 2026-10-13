# Pipeline Evidence: PMU, Simulation and BIU Closure

Use application/operator PMU for Cube/Vector/MTE task timing and utilization.
Use TimelineDetail or explicit simulation for instruction intervals and source
attribution. Keep simulated time separate from device latency. The supported
CANN 8.5.2 / Ascend 910B2 baseline does not certify every framework capture path;
see the [capability matrix](15-cann852-capabilities.md).

## Device Instruction BIU Route: Closed

This skill closes device instruction BIU collection and activity analysis for
its supported 910B2/A2/A3 scope. `profile-pipeline --mode sampled` returns **2** immediately,
before environment probing, run-directory creation or collector
execution. It has no force override or retry action. Preserve historical instr
and BIU artifacts as raw audit inventory only; **even nonzero BIU data produces
no pipeline activity evidence**, timing, utilization or overlap conclusion.
Existing app/op PMU remains usable within its own target and metric scope.

The basis is [Ascend/msprof issue 130](https://gitcode.com/Ascend/msprof/issues/130),
[final project reply, comment 188803618](https://gitcode.com/api/v5/repos/Ascend/msprof/issues/130/comments?per_page=100)
on **2026-09-09**. After tests in multiple A2/A3 environments, the reply reports
no effective A3 data and data only on A2 device 0, but also states that the
hardware team considers the data unsuitable for analysis. It attributes the
inconsistency to underlying software feature settings, advises users against
continued use, and does not recommend investing in a fix. The closed issue
therefore supplies no released repair. The original report used A3, driver
25.5.1 and CANN 8.5.0/9.1.0; its final A2/A3 assessment is a product-level reason
for this skill's closure, not proof of one root cause on every 8.5.2 host.
The API identifies the project reply author as `Seanesmhxocism` / `wangzixuan`;
it does not independently certify that person's vendor role.

The issue's device 0 is not a physical-card-0 guarantee. The adjacent
[official CANN 8.5.0 ASCEND_RT_VISIBLE_DEVICES reference](https://www.hiascend.com/doc_center/source/zh/canncommercial/850/maintenref/envvar/envref_07_0028.html)
defines logical IDs and remapped visible indices and excludes Profiling use
with that variable. This is adjacent-version guidance, not an 8.5.2-specific
page. Target binding or removing the variable does not establish BIU reliability.
Changing periods, wrappers or cards is not a recovery workflow. Reopening the
route requires new, product-specific support and measurement-validity evidence,
followed by an explicit implementation change; collection has no bypass.

## Choose Supported Evidence

| Question | Route | Interpretation |
| --- | --- | --- |
| How much task time does each pipeline use? | Ordinary app/op timing and PipeUtilization | Retain target, core, statistic and denominator; aggregate ratios do not establish overlap. |
| What is coarse device activity? | Application `--aic-mode=sample-based` with `--aic-freq` | System activity at 1–100 Hz, separate from closed instruction BIU sampling. |
| Can the framework kernel capture produce an instruction chart? | `profile-pipeline --mode timeline-detail` | TimelineDetail depends on simulation and successful kernel argument capture. |
| Which instructions and synchronization events execute in simulation? | `profile-pipeline --mode simulator` | Simulation intervals, separate from device latency. |
| What memory throughput does the simulator model? | Simulator `PMSampling` | Simulated all-core throughput; `--core-id` does not select this data. |

The [CANN 8.5 system collection reference](https://www.hiascend.com/document/detail/en/canncommercial/850/devaids/profiling/atlasprofiling_16_0012.html)
and [simulator waveform reference](https://www.hiascend.com/document/detail/en/canncommercial/850/devaids/optool/atlasopdev_16_0160.html)
distinguish ordinary sampling and simulator PMSampling. The BIU closure does
not remove either route. Their existing product/version validation still applies.

[CANN 8.5 msProf documentation](https://www.hiascend.com/document/detail/en/canncommercial/850/devaids/optool/atlasopdev_16_0082.html)
documents TimelineDetail's simulation configuration, limited framework calling
scenarios, and incompatibility with application/range replay. Explicit simulator
metrics are a separate set; ResourceConflictRatio includes synchronization
event details. The helper checks installed help for these supported routes.

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
caller, as in `profile-harness`; follow
[application device binding](03-collection.md#bind-the-application-device).
Each command below needs a fresh run directory:

```bash
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
the mapping from actual trace lanes and launch records. TimelineDetail uses
kernel replay. Explicit simulator collection selects PipeUtilization and
ResourceConflictRatio. No mode silently falls back to a different mode.

If capture fails, distinguish argument/context dump, injected-library loading,
and framework initialization in the saved logs. A clearly unsupported runtime
API before the kernel is not missing instruction activity. Prefer a standalone
ACL harness with the matching ELF, full ABI and buffer lifetimes when feasible;
do not patch framework initialization APIs one by one. Export can parse an
existing simulator dump but cannot create a failed capture.

For MIX coverage, start with a dependency-complete producer/consumer/barrier
group and retain all required lanes. `--core-id` selects parsed logical cores;
it does not remove executing producers. Only expand to the actual workload or
PMSampling when the question requires it. Stop on the first unsupported API,
missing required lane or bounded timeout; a reduced workload certifies only
its own simulation. None of these routes establishes real-device MIX overlap.

## Inspect Completion And Simulation Evidence

`analyze` writes schema 2 `analysis/pipeline_evidence.json` with
`device_instruction_sampling: closed` and an empty `samples` list. Historical
BIU requests or populated BIU tables produce `device_instruction_sampling_closed`
and source hashes, without activity or timestamp statistics. Summary warnings
and reading guidance retain this closure. For supported simulation inspection:

```bash
ascend-msprof pipeline --run-dir profile/simulator
```

The artifact retains collection-stage diagnostics and source log references.
Historical BIU files remain an audit inventory governed by the closure above,
not an activity input. A normal application profile's empty `biu_perf.db`
placeholder without a sampling request or BIU tables does not turn successful
app/op PMU into a failed BIU attempt. `ascend-msprof pipeline` returns 2 when
it encounters retired BIU evidence; supported simulation diagnostics retain
their existing return behavior.
`timeline` also excludes exported device BIU lanes and their synthetic intervals
from duration rankings and SVGs, returning 2 when it encounters them. Ordinary
application tasks and actual simulator intervals remain available.

Read `analysis/profile_pipeline_run.json` separately from the process receipt.
Supported collection routes return 1 for known evidence failures, 2 for
preflight/setup failures, and 0 when no blocking issue was identified; 0 still
requires target, coverage and artifact inspection. `inspect_target_and_coverage`
is not a verdict that an instruction trace was obtained. Raw per-process
results retain their actual return codes. Valid app/op metadata remains
available when optional simulation fails.

| Observed diagnostic | Next useful check |
| --- | --- |
| `target_not_selected` | Compare the skipped name with the declared selector and other collected targets; unrelated skipped kernels do not invalidate a collected target. |
| `kernel_argument_dump_failed`, `timeline_detail_failed` | Inspect framework launch/capture compatibility and saved arguments; OpBasicInfo or an opaque binary alone does not supply an instruction timeline. |
| `simulator_library_load_failed` | Check selected simulator libraries and launcher environment. |
| `framework_simulator_api_failed`, `profiled_application_failed` | Locate whether framework initialization failed before kernel execution; consider a caller-owned ACL or actual-binary config route. |

## Render Obtained Instruction Intervals

```bash
ascend-msprof timeline --run-dir profile/simulator --svg
```

The source-repository fixture
`tests/fixtures/real_cann852_simulator_minimal/` preserves a successful native
pure-AIV probe on CANN 8.5.2 / Ascend 910B2 with logical core 0 and
PipeUtilization,ResourceConflictRatio. Its correct 32-add output, trace and
code/instruction CSVs establish that simulation path only. Its 32 `VADD`
complete events map to the kernel's Add source line. Other source rows with
unavailable line numbers remain unresolved. The probe does not certify full
MIX capture or simulator PMSampling. Its reduced workload differs from the
4096-add device workload, so their durations are not a performance comparison.
Source-line and instruction cycles/times have different attribution scopes and
cannot be added together or used as natural elapsed time.

The text duration ranking remains available. SVGs use valid complete `X`
instruction events from each admitted simulator trace, preserve raw pid/tid
lanes, cite source SHA256 and timestamps, and normalize the displayed origin
within that file. `analysis/timeline_svg_index.json` lists the separate outputs.
Trace files are not merged onto an assumed shared clock. B/E and flow records
are not paired into invented wait durations. A trace without complete intervals
produces no SVG.

To explain bubble hiding, verify actual source dependencies and overlapping
simulation intervals within their stated scope; a fused launch or simultaneous
aggregate utilization is insufficient. Source-level global barriers can separate
Vector preparation and Cube compute. The renderer does not calculate overlap
percentages or establish causality.
