# Real Example: Serial And Pipelined Matmul

## Question And Provenance

“Does adding pipeline annotations to this matmul improve performance, and what
can the collected counters tell us about the mechanism?”

This example uses preserved on-device runs from 2026-06-06, not invented
counter values. Repository fixtures are under
`tests/fixtures/tilelang_design_feedback/pipeline_expression/{serial,pipelined}`;
their manifest identifies the original controlled profile runs. Recorded
`analysis/provenance.json` → `cann_version.value` is
`8.3.0.2.220:8.3.RC2`. This is an offline replay of those records, not a new
measurement on the reader's machine. The installed skill includes this worked
interpretation; raw fixtures for replay live in the source repository.

Both generated programs use float16 1024×1024 buffers and launch 32 blocks.
In `tilelang-jit-debug/tilelang_jit_program_matmul_add.py`, the serial K loop
is `for kk in range(loop_k)`. The pipelined program has
`T.serial(loop_k, annotations={"num_stages": 3, "tl_cross_interval": 1})`.
This establishes a source difference; measured overlap still needs evidence.
`analysis/tilelang_context.json#/benchmark/metadata/pipeline_stages` also changes
`vec_proc` from 0 to 2 while `loop_k` changes from 0 to 3. This is not a controlled
K-loop-only change, so a timing difference cannot automatically be assigned to it.

## Layer 1: Select The Run And Claim

Open each regenerated `analysis/reading_guide.md`. Target names match, but the
original `op` segment's metric scope is unknown in the replayed records. The
Default follow-up is separately identified as
`followup:collect_default_metric_followup`, scope `Default`.
Use the per-artifact values even though top-level `metric_scope` is null.

There is no `analysis/benchmark_context.json` accepted by the current natural
benchmark contract. Legacy `tilelang_context.json` runtime values remain caller
context; they do not supply the missing eligibility record. The regenerated
comparison reports `performance_assessment.eligibility.status = incomplete`.
We can inspect local profiler observations and source changes, but cannot call
this an established natural-performance improvement.

## Layer 2: Read Timing Within Its Segment

Exact `OpBasicInfo.csv` roots, relative to the corresponding run:

| Run / segment | Raw directory |
|---|---|
| serial / op | `reports/op/OPPROF_20260606121252_MCHGUDCSIZSRIMGO` |
| pipelined / op | `reports/op/OPPROF_20260606121518_VFKVEPMXTKCMIAHS` |
| serial / Default follow-up | `reports/followups/collect_default_metric_followup/OPPROF_20260606121334_TZPHUMBSCSOLEEVR` |
| pipelined / Default follow-up | `reports/followups/collect_default_metric_followup/OPPROF_20260606121603_ZRTBAAERTRIHLDIX` |

Each file's record 2, field `Task Duration(us)`, records:

| Segment | Serial (us) | Pipelined (us) | Descriptive observation |
|---|---:|---:|---|
| op, metric scope unknown | 52.439999 | 52.259998 | Pipelined recorded a smaller operator duration. |
| Default follow-up | 52.480000 | 52.860001 | Pipelined recorded a larger operator duration. |

These are observations from distinct collection segments, with no repeated
natural comparison establishing an improvement. Choosing the favorable row
would change the answer without evidence. Retain both rows and the unresolved
collection/comparison conditions; do not average the two scopes or interpret
the small differences as statistical significance.

## Layer 3: Verify A Proposed Mechanism

Choose the guide's pipe question and open the serial `op` PipeUtilization
artifact, beside its OpBasicInfo file above. It has 96 rows across core classes.
Its maximum `aic_cube_ratio` and maximum `aic_mte2_ratio` occur on different blocks:

| CSV record | block_id / sub_block_id | aic_cube_ratio | aic_mte2_ratio |
|---|---|---:|---:|
| 8 | 2 / cube0 | 0.102457 | 0.262756 |
| 35 | 11 / cube0 | 0.095331 | 0.263045 |

Both ratios are dimensionless. For this file, reporting “Cube 0.102457 and
MTE2 0.263045 on one core” would combine different records. Use the guide's
concrete command with `--record 8` or `--record 35` to keep their peers together.
For a full distribution, request the two fields with `--scope sub_block_id=cube0`.
For a time-tail question, follow `core_time_distributions` first so maximum and
second-largest locations remain visible.

The [metric reference](08-ascend-metric-files.md)
explains recorded ratios and derived time quotients. A larger MTE2 activity
ratio than Cube activity is a description of these records; it alone establishes
neither memory bandwidth saturation nor a benefit from more pipeline stages.
Use the [pipeline mechanism card](06-diagnosis-playbook.md) to inspect the
source dataflow and alternatives. This fixture has no recorded simulator signals,
so a claim that simulation proved copy/compute overlap has no source here.

The guide's source-context route leads directly to `tilelang_context.json` →
`jit_debug` and `tilelang-jit-debug/tilelang_jit_compile_source_matmul_add.cpp`.
In the pipelined C++, lines 44–60 show preloads and three-slot rotation (`% 3`),
but also `PipeBarrier<PIPE_ALL>()` between the copies and GEMM (line 53) and after
GEMM (lines 59–60). That makes the emitted synchronization a concrete next
inspection target. These source locations do not measure overlap or prove
serialization; inspect emitted behavior or a corresponding pipeline trace to
distinguish those explanations.

## Deliverable To The Caller

A supported answer is:

> The generated K loop carries new pipeline annotations. Operator durations move
> in opposite directions in the op and Default segments (the four
> `OpBasicInfo.csv` record-2 `Task Duration(us)` cells above), and the current
> natural performance assessment is incomplete. Serial PipeUtilization records
> 8 and 35 show more recorded MTE2 activity than Cube activity, with different
> maxima locations. These facts do not establish that the change improved
> natural latency or increased overlap. Complete a comparable natural benchmark
> for the performance question; inspect generated scheduling or collect focused
> source/pipeline evidence only if resolving overlap is needed for the mechanism
> question.

The caller can use this answer to select its next experiment without losing
useful counters or inheriting an unsupported bottleneck label.

## Reproduce From The Source Repository

Copy preserved runs so derived outputs leave fixtures unchanged. No NPU collection
is needed for these commands; use the repository's configured Python environment.

```bash
mkdir -p local-notes/matmul-navigation
cp -R tests/fixtures/tilelang_design_feedback/pipeline_expression/serial local-notes/matmul-navigation/serial
cp -R tests/fixtures/tilelang_design_feedback/pipeline_expression/pipelined local-notes/matmul-navigation/pipelined
ascend-msprof analyze --run-dir local-notes/matmul-navigation/serial
ascend-msprof analyze --run-dir local-notes/matmul-navigation/pipelined
ascend-msprof compare --run-dir-a local-notes/matmul-navigation/serial --run-dir-b local-notes/matmul-navigation/pipelined
ascend-msprof joint-row --run-dir local-notes/matmul-navigation/serial --artifact reports/op/OPPROF_20260606121252_MCHGUDCSIZSRIMGO/PipeUtilization.csv --record 8
```

Use a fresh destination for each replay. `tests/test_evidence_navigation.py`
checks the cited cells, pointers, distribution routes, partial evidence and raw
hash preservation. These checks verify the evidence delivery; they do not certify
a kernel optimization or a repeated agent-behavior success rate.
