# CANN 8.5.2 Capability Baseline

The active environment baseline is **CANN 8.5.2 / Ascend 910B2**. An environment
baseline identifies the tool/hardware combination to validate; it does not make
every advertised metric or framework capture path usable. Retain original
CANN `8.3.0.2.220:8.3.RC2` identities on historical fixtures and walkthroughs.

For each feature, separate four facts: official documentation for the product,
installed help accepting the option, usable live output for a named launch path,
and helper parsing of the observed fields. CANN 8.5.0 documentation below is
release-proximate guidance; actual 8.5.2 artifacts govern output support.

## Capability Matrix

| Feature | Documentation / 8.5.2 help | Live-output and helper boundary |
|---|---|---|
| Application timing + operator PipeUtilization | A2 documented; installed help accepts the triage flags | Live-verified on 2026-10-11 with standalone native Ascend C Vector and Cube workloads; retained application/op CSVs cover target/launch checks and registered fields. Each new launch path still needs its own check. |
| Operator Default | A2 documented; help accepts it | Live-verified as a separate segment on both native workloads, including MemoryL0/MemoryUB and the other expected families. Current 8.5.2 raw fixtures complement historical regression coverage. Instrumentation-only fields remain conditional. |
| Arithmetic FOPS | A2/A3 field table defines Cube and Vector operation counts | Saved 8.5.2 / 910B2 DFT launches verify typed `aic_cube_fops` and `aiv_vec_fops` queries and scored distributions by kernel/family/core/block. Other-core NA remains missing. Unit is FLOP, without a time denominator; these distributions do not establish natural performance or a program score. |
| MemoryDetail | A2/A3 documented; help accepts it; includes Default; range replay excluded | Live-verified on the native Cube workload with Default,MemoryDetail: eight CSV families and numeric AIC MTE1/MTE2 active bandwidth. Default alone emitted those headers with NA values. Preserve unregistered fields/binaries as raw evidence. |
| Source | A2/A3 documented; help accepts it; range replay excluded | Native Vector Default,Source completed with eight Default CSVs and raw binary/mapping products. PMU fields are readable; per-line hotspots/cache heatmaps are not validated or decoded by the helper. Compile with `-g`; keep each field's origin below. |
| BasicInfo | Documented; help accepts it | Live-verified on the native Vector workload: basic metadata without PMU families. The BasicInfo scope accepts that absence; metadata does not establish performance. |
| KernelScale | A2/A3 documented; help accepts it | Requires source instrumentation with MetricsProfStart/Stop. The selected region is not whole-kernel timing. |
| Occupancy / Roofline | Documented; help accepts them | Preserve tool stdout as attributed guidance. Occupancy describes inter-core differences. Roofline labels and thresholds remain tool/version heuristics. |
| Device instruction BIU sampling | **Closed** for the supported 910B2/A2/A3 scope | `profile-pipeline --mode sampled` returns 2 immediately. Historical BIU artifacts are raw audit only, including nonzero files; see [closure basis](14-pipeline-evidence.md#device-instruction-biu-route-closed). |
| TimelineDetail | Documented; op help accepts it | Simulation-dependent kernel capture. Existing framework probes failed argument capture; command success alone does not certify instruction intervals. |
| Explicit simulator PipeUtilization + ResourceConflictRatio | Installed simulator help lists these separately from onboard metrics | Live-verified on a reduced native pure-AIV workload with 32 adds and logical core 0: correct output, complete VADD intervals with Add-line mapping, and code/instruction CSVs. Existing readers parse these artifacts. Source/instruction attribution remains separate from device timing; unrepresentable source lines stay unresolved. |
| Simulator PMSampling | Installed simulator help lists it; 8.5 documentation describes memory throughput waveforms | Historical counter-trace coverage remains available; the new native instruction probe did not request PMSampling and does not certify it. |

The official [8.5 operator tool overview](https://www.hiascend.com/doc_center/source/en/CANNCommunityEdition/850/devaids/optool/atlasopdev_16_0082.html)
provides the product/metric/replay tables. Read [pipeline evidence](14-pipeline-evidence.md)
for the BIU closure and supported simulation failure-stage checks. One successful workload does not
certify every framework, device state or metric combination.

The current baseline records are retained under
`tests/fixtures/real_cann852_baseline/` in the source repository, with raw CSV
bytes, same-collection environment receipts and per-file origins. Fixtures are
excluded from installed distributions. They validate the named formats and
launch paths, not every advertised capability or a natural-runtime speedup.
Historical reduced fixtures may omit artifacts; such omissions do not establish
a release-level missing-file rule. The separate
`tests/fixtures/real_cann852_simulator_minimal/` retains the bounded native
simulator trace/CSV/source evidence; it does not validate full-chip or
application-timeline alignment.

## On-Demand Native Operator Probes

Use this manual route when BasicInfo, AIC active bandwidth or Source mapping
answers a specific question. Select one metric set per **fresh** run:
`BasicInfo`, `Default,MemoryDetail`, or `Default,Source`. The latter two explicitly
retain Default PMU families alongside the requested extra evidence. Check the
matrix for the demonstrated success/failure boundary; these are not extra
triage requirements.

Compile the matching binary with `-g` for source mapping, then verify correctness
before profiling. Set the selector from the actual generated entrypoint and
confirm one selected launch in the resulting metadata. This recipe deliberately
uses application replay and zero tool warmup; record harness warmup and cache
conditions as described below.

```bash
PROFILE_RUN_DIR=profile/<new_probe_name>
APPLICATION=$(realpath path/to/run.sh)
METRIC_SET=BasicInfo
KERNEL_SELECTOR='actual_generated_prefix*'
mkdir -p "$PROFILE_RUN_DIR"/{reports,logs,analysis}
PROFILE_RUN_DIR=$(realpath "$PROFILE_RUN_DIR")
ascend-msprof provenance --collect-env --run-dir "$PROFILE_RUN_DIR"

MSPROF_PROBE_CMD=(
    msprof op
    --output="$PROFILE_RUN_DIR/reports/op"
    --application="$APPLICATION"
    --aic-metrics="$METRIC_SET"
    --kernel-name="$KERNEL_SELECTOR"
    --launch-count=1
    --warm-up=0
    --replay-mode=application
)
printf "%q " "${MSPROF_PROBE_CMD[@]}" > "$PROFILE_RUN_DIR/logs/command_msprof_op.txt"
printf "\n" >> "$PROFILE_RUN_DIR/logs/command_msprof_op.txt"
printf "%s\n" "$(dirname "$APPLICATION")" > "$PROFILE_RUN_DIR/logs/msprof_op.cwd"
if (
    cd "$(dirname "$APPLICATION")" && "${MSPROF_PROBE_CMD[@]}"
) > "$PROFILE_RUN_DIR/logs/msprof_op.stdout" 2> "$PROFILE_RUN_DIR/logs/msprof_op.stderr"; then
    PROBE_STATUS=0
else
    PROBE_STATUS=$?
fi
printf "%s\n" "$PROBE_STATUS" > "$PROFILE_RUN_DIR/logs/msprof_op.status"
ascend-msprof provenance --run-dir "$PROFILE_RUN_DIR"
ascend-msprof analyze --run-dir "$PROFILE_RUN_DIR"
```

The application-directory working directory preserves relative companion
files. Keep input/source identity and caller target/launch context alongside
the command. Inspect actual headers and instrumentation logs after completion;
a zero process status is insufficient evidence of Source or MemoryDetail data.
Unknown Source binaries remain raw inventory. The native Default,Source probe
produced `dump/aicore_binary.o`, `fdata`, `kernel0.extra.0`,
`kernel0Stub.o.bbbmap.0` and `visualize_data.bin`, alongside Default CSVs.
Those files establish raw output generation, not parsed source-line timing or
a validated cache heatmap. `fdata` and `bbbmap` can contain text counts and
block/offset mappings; that alone establishes neither a stable public schema
nor per-line measured latency.

For a Source question, first open the existing `visualize_data.bin` with an
official viewer and record its version, input hash and observed source/PC
mapping. The [MindStudio Insight 26.1.0 operator-tuning guide](https://github.com/Ascend/msinsight/blob/26.1.0/docs/en/user_guide/operator_tuning.md)
describes Source/Cache views for this input. It does not certify exact 8.5.2
compatibility or a Source CSV exporter. Extend automated parsing only after a
supported exporter or stable schema, representative output and viewer
cross-check are available. If the viewer is unavailable, preserve the input
and the specific validation gap; do not recollect to recover an absent viewer.

BasicInfo intentionally cannot answer
pipe/memory-performance questions.

## Field Prerequisites And Data Origins

The [8.5 PipeUtilization A2/A3 table](https://www.hiascend.com/doc_center/source/en/canncommercial/850/devaids/optool/atlasopdev_16_0099.html)
requires dynamic instrumentation for `aic_mte1_active_bw(GB/s)` (L1 to L0A/L0B)
and `aic_mte2_active_bw(GB/s)` (GM to L1/L0A/L0B). Request `MemoryDetail` only
when that question needs them. Without instrumentation, fields may be omitted
or present as NA. The 8.5.2 native Cube validation produced the headers with
NA under Default; Default,MemoryDetail produced numeric values for the same
AIC block. This tests field availability, not a before/after performance
improvement. That observed representation refines the 8.5.0 documentation's
missing-column description. Check the actual command and instrumentation
receipts before distinguishing not requested, failed and unparsed. Preserve
missing/NA separately from numeric zero. Keep active-window bandwidth separate from task/core-window
Memory bandwidth and retain its scope and denominator.

[Operator Code Hot Spot Map](https://www.hiascend.com/doc_center/source/en/CANNCommunityEdition/850/devaids/optool/atlasopdev_16_0088.html)
and [Cache Heatmap](https://www.hiascend.com/doc_center/source/en/CANNCommunityEdition/850/devaids/optool/atlasopdev_16_0158.html)
distinguish the following origins:

| Data | Origin and permitted interpretation |
|---|---|
| Kernel-level L2 hit in Details | Device measurement with the recorded request scope. |
| Onboard Source execution counts and GM Process Bytes | Instrumented execution/count data linked by PC/source mapping; not measured per-line latency. |
| Source-line/instruction L2 hits and cache heatmap | Tool cache model; keep separate from kernel-level measured hits. |
| Source Timeline | Tool simulation; not an on-device instruction timeline. |
| Simulator cycles, GPR, UB conflicts and Vector utilization | Simulator attribution; not natural device performance. |

`-g` supplies debug mapping rather than a hardware timing guarantee. Verify that
the generated source and binary match the run. The documented hotspot/cache
maps exclude MC2/LCCL. Unknown output schemas remain raw rather than acquiring
hardware-measurement status from the `msprof op` command name.

## Replay, Warmup And Cache Protocol

Save the selected replay mode, tool warmup, harness warmup, input reuse/rotation,
cache policy, launch count and Current/Rated Freq alongside each segment.
PMU families can require multiple replays: even one CSV row need not describe
one simultaneous execution. Distinguish replay duration from the caller's
natural-launch benchmark.

CANN 8.5 documents kernel, application and range replay, with metric-specific
restrictions. The existing focused target recipe uses application replay and
`--warm-up=0` to preserve its launch contract; record any warmup inside the
harness. Short kernels can remain below their intended frequency state. Retain
frequency context rather than silently changing counts or normalizing time.

The [pinned official implementation](https://github.com/Ascend/msopprof/blob/80dae2e3701d14e191d2d461eb6be8aab714d89d/docs/en/development_guide/architecture.md)
describes kernel replay with memory backup/restore, warmup and L2 clearing,
and application replay collecting a PMU round per process while retaining
preceding-operator cache context. That source is newer than this baseline.
Treat those cache details as a versioned explanation to verify against the
installed implementation or a controlled experiment, not an established 8.5.2
cache protocol. The natural benchmark must declare its own cache conditions.

## Product And Version Isolation

Read the **A2** rows for Ascend 910B2. The [pinned newer msopprof guide](https://github.com/Ascend/msopprof/blob/80dae2e3701d14e191d2d461eb6be8aab714d89d/docs/en/user_guide/msopprof_user_guide.md)
limits `PipeTimeline`, `instrTimeLine` and `PcSampling` to Ascend 950; they are
absent from the checked 8.5.2 operator help. They are not fallback recipes for
910B2. Newer PMSampling support tables also differ from 8.5 documentation;
keep version, product, mode and observed artifacts together instead of deleting
valid historical evidence or assuming support from a newer table.

Static platform capacity, available runtime resources and measured frequency
are separate facts. See [910B programming context](../ascend-910b-programming.md)
for launch semantics, capacity accounting and source checks. A useful baseline
validation records device/driver/firmware/toolkit identity, correctness, target
coverage, each command receipt and exact usable/failed artifacts; expanding
parser support additionally needs representative raw headers and regression tests.
