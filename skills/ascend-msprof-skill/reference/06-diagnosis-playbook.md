# Assessment Playbook

Use this after extracting `analysis/summary.json`. Answer the caller's profiling
question with observations, justified interpretations and explicit limits. Cite
an exact artifact and field for every material claim.

Readiness is not binary: a run can support a local kernel observation while
lacking coverage for a complete-program claim. State the scope and continue
with evidence that remains valid.

## Establish The Measurement Boundary

1. Check observed target identity and launch coverage. Metrics from an unbound
   target remain unbound. A focused kernel segment describes its subset; its
   missing complete-program coverage does not erase its local observations.
2. Identify the collection mode, metric scope, units and aggregation. Application,
   operator and simulator measurements have different boundaries. Their totals
   are not interchangeable performance measurements.
3. For a before/after assessment, use the recorded compatibility and workload
   checks. Describe incompatible observations separately; retain the reason a
   delta cannot be computed.
4. Use the natural-launch benchmark assessment to establish observed runtime
   differences. Profiler metrics assess mechanisms separately. Link them to the
   same implementation and workload before relating their changes.

`evidence_readiness` describes evidence availability. It does not certify a
bottleneck or an optimization experiment. `evidence_relations[]` links artifacts
that can be inspected together; a relation is not a causal explanation.

## Select Evidence For The Question

| Question | Evidence to inspect | Interpretation boundary |
|---|---|---|
| Where is application time spent? | `op_summary_*.csv`, `op_statistic_*.csv`, `task_time_*.csv`, `api_statistic_*.csv` | Distinguish per-call duration, total time and call count. A top row identifies recorded cost, not its cause. Complete-program claims need complete application coverage. |
| What pipe/arithmetic activity was recorded? | `PipeUtilization.csv`, `ArithmeticUtilization.csv` | Keep Cube, Vector, Scalar and MTE fields, units and scope distinct. A high or low ratio alone does not establish a bottleneck. |
| What memory/cache behavior was recorded? | `Memory.csv`, `MemoryL0.csv`, `MemoryUB.csv`, `L2Cache.csv` | Distinguish data volume, bandwidth, time and hit rate. Relate compatible pipe/timing evidence to a caller-supplied mechanism question. |
| What resource conflict was recorded? | On-device `ResourceConflictRatio.csv` plus corresponding timing/metric context | Interpret the documented field and denominator; a conflict signal alone does not establish its contribution to elapsed time. |
| What launch/work distribution was recorded? | `OpBasicInfo.csv`, task timing and workload metadata | `Block Dim` and `Mix Block Dim` are launch metadata, not proof of core imbalance. |
| Where does simulator activity map to source? | `core*_code_exe.csv`, `core*_instr_exe.csv`, `trace.json`, `analysis/simulator_hotspots.json` | Use recorded source/instruction/pipeline references. Simulator time does not replace on-device time. |
| Do several fields describe one core state? | Same-artifact `joint-row` for one CSV record | A joint row is one CSV record, not one PMU sample or simultaneous execution. Per-metric maxima may come from different records. |
| What volume moved, when counts are clear? | Memory `*_datas(KB)` plus core/launch scope | Sum or distribute only with an explicit count scope; do not invent totals across incompatible segments. |
| Did intervals overlap or stay idle? | Timestamps in one measurement mode (`ts`/`dur`/`pid`/`tid`) | `timeline` duration summaries are not interval-overlap analysis. Overlap is not proof of dependence or speedup source. |

Default to the short summary headlines. Expand into a joint row, scoped Memory
volume fields, or same-mode timestamp inspection only when the current question
needs that view. Cross-collection alignment can establish comparable conditions
when implementation, workload, launch, collection mode/segment, and replay
agree; it is not one simultaneous execution. Volume totals for a recognized Memory
field live on `artifacts[].field_populations[]` (`sum_over_rows` within one
file and `sub_block_id`); ratio observations carry same-record pipe times and
`pipe_time/core_time` quotients. Interval-overlap computation is still not a
helper API—inspect cited raw timestamps when that question arises. “Why it is
slow” and “what to change” stay with the caller and source.

For exact supported field spellings and version limits, consult the relevant
section of [the metric file reference](08-ascend-metric-files.md). Unknown fields
remain raw observations until their meaning is established for that version.
The helper retains located per-metric observations, not a complete distribution. Use the
raw index to locate supporting rows and read all rows only when the claim needs
an aggregation, distribution or absence check. Per-metric maxima may come from
different cores or CSV records; treat them as the same CSV record only after a
joint row confirms the same artifact and record:

```bash
ascend-msprof joint-row \
    --run-dir "$PROFILE_RUN_DIR" \
    --artifact reports/OPPROF_001/PipeUtilization.csv \
    --scope block_id=0 --scope sub_block_id=vector0
```

## Mechanism Cards

Use these Ascend-native cards after measurement boundaries are clear. Each card
keeps competing explanations open until a minimal verification distinguishes
them. Prefer the form: observed fields → source/workload conditions → optional
experiment with expected natural and mechanism changes → support / does not
support / still indistinguishable. Never turn a headline into a unique root
cause or a guaranteed code change.

### High `aiv_mte2_ratio` or `aiv_mte2_time(us)`

| | |
|---|---|
| Competing explanations | (1) MTE2 pipe occupies a large share of core cycles; (2) absolute MTE2 time is long while another pipe still dominates wall time; (3) sync or dependence must be verified separately; (4) measurement scope is a partial launch or unbound target. |
| Source / workload conditions | Caller supplies access pattern, reuse intent and whether the shape is representative. Distinguish input analysis, source derivation and profiler measurement. |
| Supporting evidence | Same-record joint view of `aiv_mte2_ratio`, `aiv_mte2_time(us)`, `aiv_time(us)`, and sibling pipe times/ratios; natural-launch timing for the same implementation/workload. |
| Refuting evidence | High ratio with low `aiv_mte2_time(us)` and short `aiv_time(us)`; maxima from different `block_id`/`record` values; incompatible app vs op scopes. |
| Minimal verification | `joint-row` for the cited core; if needed, compare a second shape or Default follow-up without changing the kernel. |
| Conditional directions | If the same addresses are re-read, test reuse; if MTE2 wait is hideable and buffer capacity allows, test pipeline adjustment. Each direction needs its own expected natural and mechanism change. |
| Expected if explanation holds | Clarifies whether MTE2 share, absolute time, or scope mismatch is the observation—not a saturation label. |
| Verdict vocabulary | Use support / does not support / still indistinguishable. Avoid uncalibrated confidence percentages or predicted speedups. |
| Explicit bans | Do **not** equate high MTE2 with GM bandwidth saturation. Do **not** auto-recommend double buffering or any other code change from this card alone. |

**Teaching example (not a measured conclusion):** high MTE2 ratio alone does not distinguish “too much movement”, “poor access organization”, and “insufficient compute overlap”. First reuse existing same-core times and volumes; only then open a timeline when overlap is the question. High MTE2 does not by itself require double buffering.

| Next evidence | Hypothesis worth testing | Smallest experiment |
|---|---|---|
| Source reloads the same addresses; input locality exists | Removable repeat movement | Change grouping or reuse; the claimed path volume should fall. |
| Volume looks necessary; access is fine-grained | Access organization limits throughput | Change layout or granularity only; volume stays similar. |
| Multi-tile independent stages look serial | Hideable stages | Keep the tile; test pipeline/buffer staging; volume stays similar. |

Each path still needs correctness and natural timing. If the candidate is faster but the predicted mechanism field does not move, keep the performance result and weaken the mechanism claim. This table is teaching data, not a measured run.

### High `aiv_mte2_active_bw(GB/s)` vs Memory `aiv_gm_to_ub_bw(GB/s)`

| | |
|---|---|
| Competing explanations | (1) Active-window MTE2 throughput is high while the pipe is active; (2) Memory bandwidth is high/low over `CalBandwidthFp`'s chosen window (task duration or core time); (3) fields come from different metric families or cores and are not comparable; (4) denominator/scope mismatch. |
| Supporting evidence | Semantics table in [metric files](08-ascend-metric-files.md); PipeUtilization `*_active_bw` and Memory `*_bw` / volume fields aligned by the same `block_id` / `sub_block_id` across their respective CSVs when both collections exist. `joint-row` is per-artifact and cannot merge Pipe and Memory into one CSV record. |
| Refuting evidence | Ranking active_bw against Memory bw or against ratios as one signal; missing Memory family treated as proof of pipe saturation. |
| Minimal verification | Confirm both fields' denominators and scopes; collect Memory only if the question needs Memory-family movement over `CalBandwidthFp`'s chosen window. |
| Expected if explanation holds | States which bandwidth window was measured; leaves unresolved cells unresolved. |
| Explicit bans | Do not convert either field into "% of peak DRAM" without a documented peak and matching window. |

### Suspected repeat movement or weak movement/compute overlap

| | |
|---|---|
| Competing explanations | (1) The same payload is moved more than once; (2) movement and compute do not overlap enough to hide wait; (3) volume is large but each byte is necessary; (4) scope/aggregation mixes cores or launches. |
| Source / workload conditions | Buffer lifetimes, tile reuse, and input locality come from the caller. Mark each claim as input analysis, source derivation, or profiler measurement. |
| Supporting evidence | Same-record pipe times plus Memory volumes for matching `block_id`/`sub_block_id`; natural timing for the same subject; timestamps within one mode when overlap is claimed. |
| Refuting evidence | High MTE2 ratio alone; duration-rank treated as overlap; cross-mode timeline merge. |
| Minimal verification | Joint row and volume fields first; open timestamps only if overlap remains the undecided question. |
| Conditional directions | If evidence shows repeat reads, test reuse; if wait is hideable and capacity allows, test pipeline/buffer staging. State inapplicable cases (for example capacity already bound, or locality already fully used). |
| Expected if explanation holds | Mechanism fields move in the predicted direction **and** natural timing is assessed separately after correctness. |
| Explicit bans | Do not emit a bottleneck score that mixes ratios, volumes and overlap into one rank. |

### Suspected scalar / control overhead

| | |
|---|---|
| Competing explanations | (1) Scalar pipe time is large relative to useful Vector/Cube work; (2) recorded core time is short, so the ratio is not the runtime story; (3) FLOWCTRL wait or other sync must be verified separately from Scalar instructions; (4) source address derivation or reduction organization, not Scalar occupancy, is the question; (5) unbound or partial target. |
| Source / workload conditions | Caller supplies whether source has fine-grained loops, repeated address math, or a reduction whose order or accumulation type matters. Distinguish Scalar instructions from FLOWCTRL waits. |
| Supporting evidence | Joint view of `aiv_scalar_time(us)` / `aic_scalar_time(us)`, sibling compute pipe times, and `aiv_time(us)` / `aic_time(us)` on one record. |
| Refuting evidence | High scalar ratio with tiny absolute scalar time; maxima from different records treated as one state; a FLOWCTRL wait treated as Scalar arithmetic. |
| Minimal verification | Same-record joint row; optionally a second workload that changes control or reduction intensity without changing the payload size. |
| Conditional directions | If absolute scalar time dominates and source shows per-element address math or a serial reduction, the caller may test hoisting, batching, or a different legal reduction organization, then re-check correctness. If the ratio is high only because total time is tiny, do not treat it as the runtime story. Unrolling can raise instruction-fetch pressure. |
| Explicit bans | Do not prescribe a specific Ascend C rewrite from scalar ratio alone. Do not treat a Vector-ratio rise as success. |

### Ratio improves while natural runtime worsens

| | |
|---|---|
| Competing explanations | (1) Profiler ratio moved for a subset that does not dominate end-to-end time; (2) correctness/workload/protocol/environment changed; (3) host/runtime or launch coverage changed; (4) mechanism improved but another path regressed. |
| Supporting evidence | Natural-launch `performance_assessment` checks; application coverage; pipe and Memory fields for the claimed path, co-located by matching `block_id` / `sub_block_id` (or same-artifact `joint-row` within one CSV). |
| Refuting evidence | Using profiler duration alone as speedup; ignoring failed correctness or workload mismatch. |
| Minimal verification | Re-run comparable natural timing after correctness passes; only then relate mechanism fields. |
| Expected if explanation holds | Keeps natural performance and mechanism assessments separate; names the remaining competing cause. |

### Same event duration, different overlap (timeline)

| | |
|---|---|
| Competing explanations | (1) Two events have similar durations but different `ts`/`pid`/`tid` overlap; (2) application and simulator events must not be compared as one timeline; (3) duration summary was mistaken for interval analysis. |
| Supporting evidence | `analysis/timeline.txt` Event Duration Summary sections and retained `ts`/`dur`/`pid`/`tid`/`ph`. |
| Refuting evidence | Mixing Application and Simulator rows by duration; inferring dependency from duration rank alone. |
| Minimal verification | Inspect timestamps within one source section; open the cited `msprof_*.json` or `trace.json` event index. |
| Expected if explanation holds | Overlap claims only when timestamps within one measurement mode support them. |

### Suspected Cube tiling, supply, or output cost

| | |
|---|---|
| Competing explanations | (1) tile, K-split or padding changes how much Cube work and fill is issued; (2) MTE1/MTE2 supply or Fixpipe output, not Cube math, dominates the cited core; (3) a low Cube ratio is a small-matrix or elsewhere-bound observation; (4) AIC/AIV or launch-scope mismatch. |
| Source / workload conditions | Caller supplies matrix shape/dtype, tile and padding, and whether the shape is representative. Distinguish source tiling from profiler cells. |
| Supporting evidence | Same-record Cube time/ratio with MTE1/MTE2/Fixpipe siblings on one AIC record; ArithmeticUtilization Cube instruction or fops fields when collected; Memory volumes for the claimed path; natural timing for the same subject. |
| Refuting evidence | Low `aic_cube_ratio` treated as unused peak; maxima from different records treated as one tile state; MFU or FLOP labels substituted for the recorded Cube field. |
| Minimal verification | Joint row on the cited AIC record; keep Cube, supply and output fields distinct. |
| Conditional directions | If source tiling and volumes show excess fill or re-fetch, the caller may test a different legal tile or K split. If Cube time is already small versus core time, do not treat utilization as the runtime story. |
| Explicit bans | Do not prescribe a unique tile size from one ratio. Do not treat Cube activity, MAC activity and MFU as interchangeable. |

### Suspected UB layout or resource conflict

| | |
|---|---|
| Competing explanations | (1) UB bank, bank-group or resource conflict stalls Vector/Scalar access; (2) the wait is producer or sync, not layout; (3) MemoryUB Vector/Scalar bandwidth describes on-chip access, not HBM saturation; (4) conflict fields and pipe times come from different records or collections. |
| Source / workload conditions | Caller supplies UB layout, stride and whether a conflict field was collected for this version and mode. |
| Supporting evidence | On-device `ResourceConflictRatio.csv` with the documented field and denominator; MemoryUB Vector/Scalar bandwidth when that family exists; same-record pipe times for the cited AIV record. |
| Refuting evidence | Summing conflict percentages as one stall; treating a layout sketch as proof of bank conflict; using a conflict ratio as HBM saturation. |
| Minimal verification | Confirm the conflict field, core class and record; collect MemoryUB only if on-chip access is the question. |
| Conditional directions | If a named conflict field and the layout agree, the caller may test stride, padding or address distribution and then re-check natural timing. Extra padding that lowers a ratio can still be slower. |
| Explicit bans | Do not prescribe a UB rewrite from a conflict headline alone. Do not add conflict percentages across kinds. |

### Suspected multi-core tail

| | |
|---|---|
| Competing explanations | (1) same-class cores have different work and a slow core repeats; (2) start offset or wait, not payload size, makes one core late; (3) `Block Dim` / `Mix Block Dim` are launch metadata, not effective parallelism; (4) AIC and AIV tails are mixed into one story. |
| Source / workload conditions | Caller supplies the work assignment and whether the same `block_id` still owns the same region after a change. |
| Supporting evidence | `core_time_distributions` and scoped volume populations within one core class; OpBasicInfo launch metadata; natural launch time for the same subject. |
| Refuting evidence | Mixing cube and vector populations; treating the slowest cell as wall time; using a later run's matching `block_id` as the same work role. |
| Minimal verification | Keep AIC/AIV populations separate; compare distribution, total work and launch time together. |
| Conditional directions | If the same-class spread matches uneven work, the caller may rebalance tiles or handle a tail separately. More cores can add contention on a small input. |
| Explicit bans | Do not maximize core count from `Block Dim` alone. Do not treat one tail cell as the operator duration. |

### Suspected fusion, intermediates, or host dispatch

| | |
|---|---|
| Competing explanations | (1) several kernels belong to one semantic module and move intermediates that a fused form could avoid; (2) host/API or CANN gaps, not those kernels, dominate the wall; (3) fusion changes launch count and buffer pressure together; (4) old kernel names are paired 1:1 with a renamed or fused launch. |
| Source / workload conditions | Caller names the semantic module and whether intermediates must remain visible. Compare the same module boundary, not a sum of unmatched kernels. |
| Supporting evidence | Application `op_summary` / `task_time` / `api_statistic` for dispatch and gaps; launch counts; Memory volumes for claimed intermediate paths; natural timing of the same module. |
| Refuting evidence | Summing pre-fusion task durations as the fused wall; forcing same kernel-name pairing after fusion or rename; treating fewer launches as automatic speedup. |
| Minimal verification | State the module boundary first; keep natural timing and mechanism fields on that boundary. |
| Conditional directions | If intermediates and dispatch are the question, compare fused and unfused forms of the same module. Fusion can reduce stores or launches and can also add sync or buffer pressure. |
| Explicit bans | Do not treat a host gap as device idle without a source. Do not emit a fusion prescription from launch count alone. |

### Suspected L2 / cache or benchmark-cache bias

| | |
|---|---|
| Competing explanations | (1) L2 hit-rate fields describe the collected read/write/total requests, not saved bytes; (2) the benchmark reuses a small working set that the target scene does not; (3) a streaming access can be fast with a low hit rate; (4) cold and hot cache results are different scopes. |
| Source / workload conditions | Caller states cache policy, warmup and whether the input is reused or rotated. Mark each claim as input analysis or profiler measurement. |
| Supporting evidence | `L2Cache.csv` hit-rate fields with their documented request scope; Memory volumes for the claimed path; natural timing under the same cache policy. |
| Refuting evidence | Low hit rate treated as unused reuse; selecting the more favorable of cold/hot cache; using L2 hit rate as an ICache or HBM result. |
| Minimal verification | Compare candidates under one stated cache policy; keep L2 data-hit fields separate from ICache miss fields. |
| Conditional directions | If deployment rotates inputs, measure both a reused set and a rotated or larger set. Warmup should reach the intended state, not invent reuse the target does not have. |
| Explicit bans | Do not treat hit rate as a benefit function or a required code change. Do not hide one cache regime behind the other. |

## Resolve Only Relevant Gaps

- Distinguish a missing file from an empty/invalid file, parsed metrics without
  identity binding, and metrics available only for a subset. Use raw-index
  parser status, target identity and per-segment coverage to identify the gap.
- Select a collection recipe only if it supplies evidence needed by the current
  question. Complete compatible evidence can be reused. Consult
  [collection](03-collection.md) for recorded app/op/simulator recipes.
- Missing simulator or other unrelated families do not prevent a bounded answer
  from existing evidence. State what cannot be assessed and why.
- Preserve CANN stdout advice as attributed raw messages. Verify any factual
  claim used in the answer against CSV/timing evidence. Preserved `.bin` files
  have an audit role only; they do not supply parsed metric or diagnosis evidence.

## Complete The Assessment

Report the answer, supporting fields and scope, competing explanations that the
measurements cannot distinguish, and any specific gap preventing a conclusion.
For a caller-supplied hypothesis, distinguish supporting, contradicting and
inconclusive observations. A refuted hypothesis is an informative result;
profiler field movement does not by itself establish a runtime improvement.
Leave kernel changes, experiment priority and candidate selection to the caller.
End with the smallest verification that would distinguish competing
explanations; never turn a headline into a code-change instruction.

## Caller Experiment Collaboration

Helpers compare natural benchmarks and profiler mechanisms. They do not accept
hypothesis, code-change, expected-change or experiment-verdict inputs, and they
do not rank candidates. The calling agent owns the experiment story.

Before treating a change as tested, the caller should hold this **experiment
record** (notes or conversation are enough; it is not a helper schema). It is
not a 1:1 map onto the report checklist below:

1. Hypothesis under test.
2. Code or configuration change (file/symbol/intent).
3. Expected natural change and expected mechanism field changes, stated
   separately.
4. Correctness contract shared by baseline and candidate.
5. Actual results after measurement (filled by the caller from helper output),
   plus what remains unexplained.

Answer these two questions separately in every write-up:

- Was this run observed faster on the comparable natural benchmark?
- Does the profiler evidence support, contradict, or leave open the mechanism
  hypothesis?

Missing simulator or other unrelated families does not invalidate an eligible
natural observation. Point estimates in the comparison contract remain point
estimates; repeats and multi-case checks stay with the caller.

Request evidence with the existing commands only:

- Natural runtime: `collect-benchmark` with aligned `assessment` records, then
  `compare` / `summarize-candidate` → `performance_assessment`.
- Mechanism: regenerate derived summaries when needed, then compare →
  `mechanism_assessment`.
- Same-record identity: `joint-row`. Across Pipe/Memory families, align
  matching `block_id` / `sub_block_id` only when implementation, workload,
  launch, collection mode/segment, and replay are compatible; do not force
  same kernel-name pairing after fusion or rename.

Reading rules for caller write-ups:

- Mechanism movement does not establish natural speedup; natural speedup does
  not establish the mechanism hypothesis.
- `evidence_level: descriptive` and comparison `observed_only` are observations,
  not causal or significance decisions. Point-estimate limitations forbid
  claiming a stable verified win without caller-owned repeats.
- `incomplete`, `blocked` or correctness/subject mismatch means conditions are
  unmet, not that the optimization failed. Implementation-fingerprint or CANN
  mismatch on continue likewise means start a new run, not “optimization failed”.
- A contradicted hypothesis is a useful result; update the hypothesis instead of
  collecting unrelated metrics.

When reporting an experiment, assemble the separate **Caller Experiment
Diagnosis** checklist in the [report template](07-report-template.md) (verified
observations, competing explanations, missing check, caller-owned proposed
change, measured natural/mechanism updates). If the caller omitted the
experiment record, say so; do not invent the caller-owned proposed-change or
measured-update items in the helper's voice.

## Tool And Artifact Sources

- [CANN 8.0 operator profiling and simulation](https://www.hiascend.com/document/detail/en/canncommercial/800/devaids/optool/atlasopdev_16_00851.html)
  documents the operator/simulator modes and their artifact roles.
- [MindStudio 7.0 Profiling Quick Start](https://www.hiascend.com/document/detail/en/mindstudio/700/TITools/Profiling/atlasprofiling_16_0005.html)
  documents application collection and timing/timeline output roles.

These sources establish tool roles, not a cross-version CSV schema. Exact field
handling remains limited to the documented and fixture-validated layouts in this
skill.
