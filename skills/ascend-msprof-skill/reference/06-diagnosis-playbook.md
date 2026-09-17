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
| Do several fields describe one core state? | Same-artifact `joint-row` for one CSV record | Per-metric maxima may come from different records; co-occurrence needs a joint row. |
| What volume moved, when counts are clear? | Memory `*_datas(KB)` plus core/launch scope | Sum or distribute only with an explicit count scope; do not invent totals across incompatible segments. |
| Did intervals overlap or stay idle? | Timestamps in one measurement mode (`ts`/`dur`/`pid`/`tid`) | `timeline` duration summaries are not interval-overlap analysis. Overlap is not proof of dependence or speedup source. |

Default to the short summary headlines. Expand into a joint row, scoped Memory
volume fields, or same-mode timestamp inspection only when the current question
needs that view. Cross-collection alignment can establish comparable conditions;
it is not one simultaneous execution. Volume totals for a recognized Memory
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
different cores or CSV records; treat them as co-occurring only after a joint
row confirms the same artifact and record:

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
| Competing explanations | (1) MTE2 pipe occupies a large share of core cycles; (2) absolute MTE2 time is long while another pipe still dominates wall time; (3) scalar/IQ stall or sync makes MTE2 appear busy relative to short total cycles; (4) measurement scope is a partial launch or unbound target. |
| Source / workload conditions | Caller supplies access pattern, reuse intent and whether the shape is representative. Distinguish input analysis, source derivation and profiler measurement. |
| Supporting evidence | Same-record joint view of `aiv_mte2_ratio`, `aiv_mte2_time(us)`, `aiv_time(us)`, and sibling pipe times/ratios; natural-launch timing for the same implementation/workload. |
| Refuting evidence | High ratio with low `aiv_mte2_time(us)` and short `aiv_time(us)`; maxima from different `block_id`/`record` values; incompatible app vs op scopes. |
| Minimal verification | `joint-row` for the cited core; if needed, compare a second shape or Default follow-up without changing the kernel. |
| Conditional directions | If the same addresses are re-read, test reuse; if MTE2 wait is hideable and buffer capacity allows, test pipeline adjustment. Each direction needs its own expected natural and mechanism change. |
| Expected if explanation holds | Clarifies whether MTE2 share, absolute time, or scope mismatch is the observation—not a saturation label. |
| Verdict vocabulary | Use support / does not support / still indistinguishable. Avoid uncalibrated confidence percentages or predicted speedups. |
| Explicit bans | Do **not** equate high MTE2 with GM bandwidth saturation. Do **not** auto-recommend double buffering or any other code change from this card alone. |

**Teaching example (not a measured conclusion):** high MTE2 ratio alone does not distinguish “too much movement”, “poor access organization”, and “insufficient compute overlap”. First reuse existing same-core times and volumes; only then open a timeline when overlap is the question.

### High `aiv_mte2_active_bw(GB/s)` vs Memory `aiv_gm_to_ub_bw(GB/s)`

| | |
|---|---|
| Competing explanations | (1) Active-window MTE2 throughput is high while the pipe is active; (2) task-window Memory bandwidth is high/low over the whole task duration; (3) fields come from different metric families or cores and are not comparable; (4) denominator/scope mismatch. |
| Supporting evidence | Semantics table in [metric files](08-ascend-metric-files.md); PipeUtilization `*_active_bw` and Memory `*_bw` / volume fields aligned by the same `block_id` / `sub_block_id` across their respective CSVs when both collections exist. `joint-row` is per-artifact and cannot merge Pipe and Memory into one CSV record. |
| Refuting evidence | Ranking active_bw against Memory bw or against ratios as one signal; missing Memory family treated as proof of pipe saturation. |
| Minimal verification | Confirm both fields' denominators and scopes; collect Memory only if the question needs task-window movement. |
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
| Competing explanations | (1) Scalar pipe time is large relative to useful Vector/Cube work; (2) short total cycles inflate scalar ratio; (3) sync or IQ stall masquerades as scalar cost; (4) unbound or partial target. |
| Supporting evidence | Joint view of `aiv_scalar_time(us)` / `aic_scalar_time(us)`, sibling compute pipe times, and `aiv_time(us)` / `aic_time(us)` on one record. |
| Refuting evidence | High scalar ratio with tiny absolute scalar time; maxima from different records treated as one state. |
| Minimal verification | Same-record joint row; optionally a second workload that changes control intensity without changing the payload size. |
| Conditional directions | If absolute scalar time dominates and source shows heavy per-element control, test batching or restructuring control flow. If ratio is high only because total time is tiny, do not treat it as the runtime story. |
| Explicit bans | Do not prescribe a specific Ascend C rewrite from scalar ratio alone. |

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
- Same-record co-occurrence: `joint-row`. Across Pipe/Memory families, align
  matching `block_id` / `sub_block_id`; do not force same kernel-name pairing
  after fusion or rename.

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
