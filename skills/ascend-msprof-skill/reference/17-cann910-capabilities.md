# CANN 9.1.0 Version And Capability Baseline

The current environment baseline is **CANN 9.1.0 / Ascend 910B2**. Read the A2
product rows in the official sources below. Installation identity, accepted
options, successful capture and helper parsing are separate checks. Historical
[8.5.2 validation](15-cann852-capabilities.md) and 8.3.RC2 fixtures keep their
original versions; they do not certify every 9.1.0 launch path.

## Version Identity

The [9.1.0 release notes](https://www.hiascend.com/doc_center/source/zh/CANNCommunityEdition/910/softwareinst/releasenote/9.1.0/release-notes.md)
list CANN Toolkit 9.1.0, MindStudio Toolkit 26.1.0 and simulator 9.1.0. Ops
packages can have a different compatible version. The
[operator profiler installation guide](https://www.hiascend.com/doc_center/source/zh/CANNCommunityEdition/910/devaids/optool/docs/zh/install_guide/msopprof_install_guide.md)
also permits independent profiler upgrades. Record these component identities
separately from toolkit identity and the loaded runtime.

Use the [environment capture recipe](03-collection.md) to save toolkit and
device/driver/firmware evidence. The checked 9.1.0 installation has no root
`version.cfg`; the existing `ascend_toolkit_install.info` fallback records its
`package_name` and `version` correctly. Preserve resolved tool paths, installed
help and the version output advertised by operator help (`msprof op --version`
on the checked installation). The application-level help has no version option.

For installations using `share/info`, retain `msprof/version.info`,
`mindstudio-opprof/version.info`, `runtime/version.info`,
`simulator/version.info` and relevant `ops_*/version.info` beneath that directory
as separate run-local log artifacts. The helper does not automatically snapshot
or compare these component files. Check them explicitly before reusing a run
after a component upgrade or comparing different installations; equal toolkit
versions alone are insufficient. Keep missing evidence explicit.

The release compatibility table includes HDK 25.5.X for CANN 9.1.X and excludes
HDK 25.0.X. It recommends HDK 26.0.RC1 for 9.1.0. Compatibility and recommended
pairing are different claims; neither supplies a host's actual firmware version.

## Capability Matrix

The initial 2026-11-05 review checked all three installed help entrypoints
and a native AIV reader smoke. A subsequent acceptance pass rebuilt native
Cube/Vector workloads with 9.1.0, supplied explicit target contracts, and
checked collection, correctness, target identity and launch counts separately.
Raw commands, environment receipts, source/binary identities and outputs remain
local. These checks do not establish a natural-performance comparison or a new
committed regression fixture.

| Feature | 9.1.0 evidence and boundary |
|---|---|
| Application timing, operator PipeUtilization and Default | Native Cube (one launch) and Vector (three launches) passed the profile-harness default-depth workflow. Target identity matched and app/op/Default coverage was complete at 1/1 and 3/3 respectively. These checks cover the declared workloads and launch paths. |
| MemoryDetail | Native Cube Default,MemoryDetail passed exact correctness, target matching and op coverage 1/1. Both AIC active-bandwidth fields have 24 numeric core rows with nonzero observations; MTE2 also contains zero cells. This validates collection and sourced parsing, not independent calibration of every counter. |
| Source | Native Vector Default,Source passed exact correctness and op coverage 1/1, retaining eight PMU CSV families and nonempty instrumentation/mapping/viewer products. The helper reads PMU fields; binary per-line hotspots and cache heatmaps remain outside validated decoding. |
| BasicInfo, KernelScale, Occupancy and Roofline | Listed in installed help; A2/A3 behavior remains documented. These separate modes were not revalidated on 9.1.0. |
| Explicit simulator PipeUtilization/ResourceConflictRatio | A reduced native pure-AIV workload passed correctness with 32 adds on logical parser core 0: 802 complete X events and 32 VADD intervals mapped to the Add source line. Four header `:0` records have unknown source lines; their metrics remain available. A separate native ACL driver of the unchanged TileLang MIX add library also passed correctness and produced 3,624 X events. Rebuilding the same source with `-g` produced 3,626 X events and mapped both selected VADD intervals to the generated Add line. This covers the tested add and selected lanes, not arbitrary MIX workloads or full vector-lane coverage. |
| Framework entry | A PyTorch/torch_npu + TileLang generated add kernel passed exact correctness and the default-depth workflow with two launches. App/op/Default target identity matched and coverage was complete at 2/2. This validates that generated-kernel entry, not arbitrary framework operators. |
| Framework TimelineDetail | The same TileLang entry failed kernel argument capture (`Addr info is null, can not dump`), then reported `TimelineDetail data collection failed`. Profiler process status was 0, but the helper returned 1 with blocked evidence. The failure also reproduces with one launch and native ACL allocations using the same library. Its ELF lacks the type 4 argument-size metadata consumed by the installed capture parser; see the diagnosis below. Explicit simulation succeeds separately and does not repair framework TimelineDetail. |
| Simulator PMSampling | The 9.1 guide restricts collection to Ascend 950, despite its appearance in generic installed help. Preserve historical counter-trace parsing; do not select it for new 910B2 collection. |
| Simulator Overhead | New installed-help option. The guide describes A2/A3 scalar overhead visualization with Insight 26.1.0 or newer; it spells the option `OverHead` in its table. No current live check or helper reader certifies these products. |
| PipeTimeline, instrTimeLine and PcSampling | The 9.1 onboard guide restricts them to Ascend 950. They are not 910B2 fallback routes. |
| Device instruction BIU | Remains [closed](14-pipeline-evidence.md#device-instruction-biu-route-closed); the version upgrade provides no new validity evidence. |

## Argument Capture Diagnosis And Recovery

This defect remains **open** as
[TD-001](18-timeline-detail-capture-defect.md), which owns the long-term repair
plan and closure criteria. The explicit simulator recovery below is a workaround.

For this generated add, `Addr info is null` refers to an empty input-parameter
description vector, not a null tensor address. The installed
[capture implementation](https://github.com/Ascend/msopcom/blob/d1564487d9c0b27033f6bb51b19b21bec7be6aa5/csrc/runtime/inject_helpers/ArgsContext.cpp#L64-L71)
checks that vector before copying input data. Its
[metadata parser](https://github.com/Ascend/msopcom/blob/d1564487d9c0b27033f6bb51b19b21bec7be6aa5/csrc/runtime/inject_helpers/KernelMetaDataParser.cpp#L61-L95)
reads type 4 argument descriptions. Both captured MIX metadata sections contain
types 1, 3, 16 and 17 but no type 4. Correct computation and ordinary PMU
collection do not require the same input-size information as argument capture.

The demonstrated recovery is a standalone ACL application loading the same
shared library, preserving its complete launch ABI and buffer lifetimes, run
through explicit simulator application mode. Preserve the profiler-injected
environment and verify numerical output as well as actual trace intervals.
Keep the original TimelineDetail result blocked; this is a separate simulation
route, not an automatic fallback or real-device latency measurement.

The unchanged library generated instruction intervals but lacked source-line
mapping. Rebuilding the same source with `-g` restored the generated Add line
in both selected vector lanes. Debug information and argument-size metadata
solve different problems: `-g` is not a TimelineDetail capture fix. A lasting
capture repair belongs in the generator/build/launch integration that supplies
input/output descriptions, with version-specific end-to-end validation. No
documented one-flag repair for this direct-launch path has been established.

For Source hotspot/cache inspection, the
[official consumption path](https://github.com/Ascend/msopprof/blob/56632dc4a944410c791538451dc2156a151bd105/docs/zh/user_guide/msopprof_user_guide.md#L259-L270)
is importing `visualize_data.bin` into MindStudio Insight. Successful capture
does not imply this helper can decode those binary views. Viewer inspection
and a helper binary decoder remain separate validation work.

## Target And Launch Coverage

Supply expected names/counts from the application or generated source before
collection, using the [harness contract](02-harness-guide.md). The helper
compares that contract with observed records; it does not infer intended launch
counts from whichever records happened to be collected. The native acceptance
checks exercised both flat single-launch and nested multi-launch operator
layouts. Advanced op-only probes intentionally lack app timing; their complete
op coverage does not make the whole-program app segment complete.

Offline counterfactual checks against the retained three-launch run kept
identity and coverage separate: expecting four launches or removing one launch
from the parsed operator inventory made coverage incomplete, while the matching
name stayed matched. A wrong expected name produced a mismatch; removing the
target contract left identity unverified and count completeness unknown. These
are controls on saved evidence, not additional live collections. The initial
reader-only smoke had no explicit contract and still cannot establish automatic
target/count coverage.

The framework acceptance derives the expected kernel name from the actual JIT
source and declares two launches before collection. Native simulator attribution
uses its trace and code/instruction CSVs; it does not manufacture ordinary
OpBasicInfo launch coverage for simulator-only output.

## Observed Schema Differences

Comparing the native AIV smoke with the retained 8.5.2 Vector fixture found:

- Application `op_summary` uses `Block Num` / `Mix Block Num` where the earlier
  artifact used `Block Dim` / `Mix Block Dim`. Operator `OpBasicInfo.csv` keeps
  its earlier headers. Application timing readers use the unchanged timing
  fields; typed operator launch metadata still comes from OpBasicInfo.
- `PipeUtilization.csv` adds scalar single/dual issue, stall and wait timing
  fields. These new fields remain raw evidence, without new typed metric or
  diagnosis support. The two AIC MTE1/MTE2 active-bandwidth headers are absent
  in this non-instrumented collection; their historical presence with NA is
  not a required schema rule.
- `ResourceConflictRatio.csv` omits the earlier `aiv_mte1_wait_ratio` column.
  Absence does not mean zero. The observed ArithmeticUtilization, L2Cache,
  Memory, MemoryL0 and MemoryUB headers match the retained Vector fixture.

The observed CSVs remain readable without a parser change. This check covers
one Vector workload and the requested metric scopes; Cube, instrumentation and
other launch paths can produce different fields.

## Commands, Replay And Output Interpretation

The [application options](https://www.hiascend.com/doc_center/source/zh/CANNCommunityEdition/910/devaids/Profiling/atlasprofiling_16_0010.html)
retain `--application` compatibility while recommending positional application
syntax; installed application help marks the old option for future removal.
The current recipes remain accepted. Keep `--type=text` for CSV/JSON readers;
`--type=db` supplies only the database. A future syntax migration needs command
construction and provenance tests together.

The [9.1 onboard guide](https://www.hiascend.com/doc_center/source/zh/CANNCommunityEdition/910/devaids/optool/docs/zh/user_guide/msopprof_user_guide.md)
states that kernel/range replay clears L2 and application replay does not.
Record replay mode, tool/harness warmup and input/cache policy explicitly.
This documents tool semantics; it does not establish a workload's measured
cache state or equate replay duration with natural timing.

The [operator field reference](https://www.hiascend.com/doc_center/source/zh/CANNCommunityEdition/910/devaids/optool/docs/zh/user_guide/msopprof_performance_data.md)
keeps A2/A3 `aic_cube_fops` and `aiv_vec_fops` as operation counts and requires
MemoryDetail instrumentation for AIC MTE1/MTE2 active bandwidth. Missing/NA
cells remain distinct from zero. The
[application field reference](https://www.hiascend.com/doc_center/source/zh/CANNCommunityEdition/910/devaids/Profiling/atlasprofiling_16_0067.html)
conditions output fields on product and collection level. Extend parsing only
when representative raw artifacts establish a schema change.

For simulator product restrictions and scalar overhead, use the
[9.1 simulator guide](https://www.hiascend.com/doc_center/source/zh/CANNCommunityEdition/910/devaids/optool/docs/zh/user_guide/msopprof_simulator_user_guide.md).
Simulation times, modeled cache behavior and source mapping remain separate
from measured device latency.
