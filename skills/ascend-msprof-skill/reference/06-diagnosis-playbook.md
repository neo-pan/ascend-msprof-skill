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
them. Never turn a headline into a code-change instruction.

### High `aiv_mte2_ratio` or `aiv_mte2_time(us)`

| | |
|---|---|
| Competing explanations | (1) MTE2 pipe occupies a large share of core cycles; (2) absolute MTE2 time is long while another pipe still dominates wall time; (3) scalar/IQ stall or sync makes MTE2 appear busy relative to short total cycles; (4) measurement scope is a partial launch or unbound target. |
| Supporting evidence | Same-record joint view of `aiv_mte2_ratio`, `aiv_mte2_time(us)`, `aiv_time(us)`, and sibling pipe times/ratios; natural-launch timing for the same implementation/workload. |
| Refuting evidence | High ratio with low `aiv_mte2_time(us)` and short `aiv_time(us)`; maxima from different `block_id`/`record` values; incompatible app vs op scopes. |
| Minimal verification | `joint-row` for the cited core; if needed, compare a second shape or Default follow-up without changing the kernel. |
| Expected if explanation holds | Clarifies whether MTE2 share, absolute time, or scope mismatch is the observation—not a saturation label. |
| Explicit bans | Do **not** equate high MTE2 with GM bandwidth saturation. Do **not** auto-recommend double buffering or any other code change from this card alone. |

### High `aiv_mte2_active_bw(GB/s)` vs Memory `aiv_gm_to_ub_bw(GB/s)`

| | |
|---|---|
| Competing explanations | (1) Active-window MTE2 throughput is high while the pipe is active; (2) task-window Memory bandwidth is high/low over the whole task duration; (3) fields come from different metric families or cores and are not comparable; (4) denominator/scope mismatch. |
| Supporting evidence | Semantics table in [metric files](08-ascend-metric-files.md); PipeUtilization `*_active_bw` and Memory `*_bw` / volume fields aligned by the same `block_id` / `sub_block_id` across their respective CSVs when both collections exist. `joint-row` is per-artifact and cannot merge Pipe and Memory into one CSV record. |
| Refuting evidence | Ranking active_bw against Memory bw or against ratios as one signal; missing Memory family treated as proof of pipe saturation. |
| Minimal verification | Confirm both fields' denominators and scopes; collect Memory only if the question needs task-window movement. |
| Expected if explanation holds | States which bandwidth window was measured; leaves unresolved cells unresolved. |
| Explicit bans | Do not convert either field into "% of peak DRAM" without a documented peak and matching window. |

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

## Tool And Artifact Sources

- [CANN 8.0 operator profiling and simulation](https://www.hiascend.com/document/detail/en/canncommercial/800/devaids/optool/atlasopdev_16_00851.html)
  documents the operator/simulator modes and their artifact roles.
- [MindStudio 7.0 Profiling Quick Start](https://www.hiascend.com/document/detail/en/mindstudio/700/TITools/Profiling/atlasprofiling_16_0005.html)
  documents application collection and timing/timeline output roles.

These sources establish tool roles, not a cross-version CSV schema. Exact field
handling remains limited to the documented and fixture-validated layouts in this
skill.
