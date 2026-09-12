# Assessment Playbook

Use this after extracting `analysis/summary.json`. Answer the caller's profiling
question with observations, justified interpretations and explicit limits. Cite
an exact artifact and field for every material claim.

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
The helper's headline is a selected row, not a complete distribution. Use the
raw index to locate supporting rows and read all rows only when the claim needs
an aggregation, distribution or absence check.

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

## Tool And Artifact Sources

- [CANN 8.0 operator profiling and simulation](https://www.hiascend.com/document/detail/en/canncommercial/800/devaids/optool/atlasopdev_16_00851.html)
  documents the operator/simulator modes and their artifact roles.
- [MindStudio 7.0 Profiling Quick Start](https://www.hiascend.com/document/detail/en/mindstudio/700/TITools/Profiling/atlasprofiling_16_0005.html)
  documents application collection and timing/timeline output roles.

These sources establish tool roles, not a cross-version CSV schema. Exact field
handling remains limited to the documented and fixture-validated layouts in this
skill.
