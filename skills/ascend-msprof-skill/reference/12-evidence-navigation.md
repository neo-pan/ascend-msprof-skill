# Reading Evidence For A Kernel Decision

## Entry And Layers

The deliverable is a sourced answer that helps the caller understand its kernel:
where runtime is spent, which mechanism the observations support, what remains
unresolved, and what evidence would resolve it. The caller owns code changes and
experiment selection. A file inventory or a ranked list of counters is not that answer.

For an existing run, use these layers. Move down only for the current question;
return to the scope checks whenever you switch run, sample, segment or target.

| Layer | Entry | What to obtain |
|---|---|---|
| Run and question | `analysis/reading_guide.md` | Actual identity, coverage, quality and claim limits; choose a question and follow its route. |
| Observations and interpretation | The cited `summary.json` subtree; optionally `key_metrics.txt` for a broad overview | Values with units, statistics, target/core scope, source record and parsing issues. Read the relevant [analysis dimension](05-analysis-dimensions.md), [metric definition](08-ascend-metric-files.md) or [mechanism card](06-diagnosis-playbook.md) when interpreting them. |
| Verification | Cited `raw_artifact_index.json` entry, operator `joint-row`, or exact raw application/simulator artifact | Verify a material claim, inspect same-record peers, resolve a population/tail or a parsing ambiguity. |

`reading_guide.md` and `key_metrics.txt` render the same run limits. The guide
routes by question; key_metrics is the observation overview and remains a valid
entry for existing integrations. Neither replaces the JSON authority. If the
guide is absent, use key_metrics and follow its references; regenerating a
navigation file is not a prerequisite for interpreting valid existing evidence.

JSON Pointer examples such as `summary.json#/headlines/pipe_utilization/artifacts/0`
identify a subtree; they are not shell commands. Pointers are relative to the
`analysis/` directory. Raw artifact paths are relative to the run directory.

## Self-Contained Question Reads

```bash
ascend-msprof evidence --run-dir "$PROFILE_RUN_DIR"
ascend-msprof evidence --run-dir "$PROFILE_RUN_DIR" --question pipe
ascend-msprof evidence --run-dir "$PROFILE_RUN_DIR" --question memory
ascend-msprof evidence --run-dir "$PROFILE_RUN_DIR" --question application-timing
```

The directory lists supported questions. Each result carries run gates, selected
segments, fresh normalized observations, support gaps and content-bound references.
Use `--segment` or `--artifact` to select an exact inventory entry. Artifact results
remain separate; the query does not combine launches or collection segments.
Default observation pages carry shared population, denominator and aggregation
limits for the displayed fields; use `--field` for their full definitions.
Support gaps distinguish unregistered wide-table columns from unregistered
`Metric` names in supported `Metric,Value` tables. Invalid known values remain
parsing issues, not missing semantic support. Timing tables retain the observed
API/task name alongside each duration statistic.
The default Markdown view presents the question result; `--format json` includes
the full input manifest and machine-readable references. Performance comparisons still use
`performance_assessment`; this reader does not assess natural timing or choose changes.

`RunEvidence.question_evidence()` reloads run context on every call, including
when the object predates a continuation or regenerated analysis. Snapshot checks
cover the reload and raw read; changed inputs require a retry on a stable run.
Other methods on the retained object still expose its originally loaded view.
Raw-reference position checks apply before pagination: an empty page can still
verify a valid position, while a wrong field or column is rejected on every page.

Pipe and Arithmetic are separate reading questions. A missing Arithmetic file
limits Arithmetic descriptions, while admitted Pipe observations remain readable.
`available_families` means numeric fields exist, not that attribution or a causal
claim passed. Apply `context` identity, coverage and measurement limits. Minimum
`evidence_readiness` is not an inventory of every diagnostic gap.

`unsupported_columns` locates existing raw values without registered semantics;
these remain audit context, not recognized diagnostic facts. Inspect `inventory_gaps`
before deciding a missing family requires collection: new files may need analysis.
Each question lists the reasons for families without admitted numeric observations
and the next existing operation. Recognized files outside the index route to
`analyze`; evidence outside the selection routes to a broader question read.
Indexed artifacts retain receipt exclusions, parsing issues and semantic support
gaps. `conditional_collection_actions` reuses summary actions whose required
artifacts match absent families. These are conditional options, not an execution
queue; read [collection](03-collection.md) before selecting one. Existing data with
missing parser support does not become interpretable by collecting it again.
For an operator artifact, select exact fields with repeatable `--field` to obtain
full matching counts and min/median/max, separated by recorded scope. The result
includes field definitions and preserves missing/invalid/unrecognized distinctions.
Percent distributions are not overall percentages; separate row denominators may differ.

Observations and application events page per artifact using `--offset` / `--limit`.
Follow each `next_offset` with its exact artifact and question; event and timing
observation counts are separate. For core tails, use `core_time_distributions` and
its located records. Existing `joint-row` remains the row/scope selection interface.

Save a question result with `--format json > saved-question.json`, then verify its input snapshot:

```bash
ascend-msprof evidence --run-dir "$PROFILE_RUN_DIR" --verify saved-question.json
```

To verify one raw record, save its `reference` object instead. Verification checks
content and location; it does not establish collection admission, source identity or
scientific validity. A snapshot binds the queried inputs and report/log inventory
at read time; it is not a historical proof that an old summary was generated from
those raw bytes. Retain the recorded run gates and regenerate inconsistent analysis.
Adding a collection invalidates the old coverage snapshot while references to
unchanged raw bytes remain valid. Rewritten raw files return mismatch; changed
summary inputs return stale. No old array index is silently resolved against new data.
Historical content is not copied automatically; an unavailable snapshot must be
recovered from retained artifacts or explicitly treated as unavailable.
Default query results and snapshot verification also carry this boundary:
content binding does not prove that summary/index were generated from the current
raw bytes. Reanalyze after raw inputs change before using the derived context.

The application event view preserves every decoded invocation independently of
representative duration maxima. Start, duration and wait fields retain raw values
and source records. Decimal arithmetic computes signed end-to-start intervals only
within one `op_summary` file and a recorded device/stream, with no cross-file clock
alignment. Task Duration includes scheduling, accelerator execution and completion
response, as defined in the [official field reference](https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/83RC1alpha001/devaids/Profiling/atlasprofiling_16_0067.html).
Consecutive observed events do not establish stream inactivity, full-device idle,
a host cause or natural-launch latency decomposition. Raw Task Wait Time remains
a separate recorded field. Missing/invalid starts or durations prevent interval
construction in the affected stream; readable raw events remain available.

## Choose The Authority For The Claim

| Question | Authority and next read | Completion criterion |
|---|---|---|
| Did this implementation become faster? | `candidate_summary.json` / `compare_*.json` → `performance_assessment`, then `benchmark_context.json` and caller timing receipt | State eligibility, timing boundary, observed difference and its limits. A profiler duration is not natural-launch latency. |
| Where is profiled application time spent? | `summary.json` → application timing families; then exact timing row or application timeline | Identify the profiled hot path and launch coverage, keeping host API, device task and whole-program boundaries separate. |
| What work or movement did the selected kernel record? | Relevant operator family → observations + `same_record`; `field_populations` for volume/distribution | Cite target, segment, metric scope, raw field, unit and statistic; distinguish activity from the proposed limiting mechanism. |
| Is there a per-block tail? | PipeUtilization → `core_time_distributions`, then maximum/second-largest source records | Locate the tail and compare it to the full same-core-class population; retain missing/invalid cells and frequency context. |
| Which code could explain a signal? | Relevant mechanism card, caller source/JIT context; `simulator_hotspots.json` if source/pipeline evidence was collected | Connect a sourced observation to code, competing explanations and a discriminating verification. Source structure alone does not prove runtime overlap. |
| What does a paired profiler change mean? | `compare_*.json` → `mechanism_assessment`, both run summaries and exact paired artifacts | Check workload, identity, collection scope and pairing limits independently of natural timing; leave experiment success to the caller. |

Use `summarize-candidate` / `compare` to generate missing assessments from
existing runs; the [assessment contract](11-candidate-comparison-schema.md)
defines their inputs. A comparison's `blocked` question may still contain useful
local observations: read its `blocked_by`, `available_evidence` and
`missing_evidence`. Report the blocked paired claim and the supported local
facts separately.

Use the exact assessment file returned by the caller or the helper command.
When several candidate/comparison files coexist, check their `runs` and
`source_artifacts` paths and SHA-256 bindings against the intended inputs. A
wildcard match, newer modification time or higher schema version does not prove
freshness. Regenerate an assessment whose inputs cannot be bound to these runs.
Likewise, `evidence_readiness: available` records available evidence families;
it does not override unverified launch coverage or a blocked paired assessment.

Use the guide's source/caller-context route even when no simulator was collected.
`tilelang_context.json` can contain payload sources, `jit_debug`, workload and
legacy benchmark context; `profile_context.json` can bind the application and
caller verification. Keep file presence separate from source identity and
eligibility. Generated scheduling is inspectable without a simulator trace;
measured pipeline overlap still needs appropriate runtime evidence.

## Keep Limits Beside The Observation

Check `target_identity`, `profile_coverage`, per-artifact `metric_scope`,
`evidence_readiness`, `measurement_quality`, `warnings` and collection receipts
before attribution. Top-level identity and each segment's identity are distinct:
a focused follow-up can cover only a subset. `count_complete` is exclusive;
unmatched extras stay in `extra_counts` and do not make name identity a mismatch.
Name alignment alone does not bind a profiler run to a benchmark implementation.

Unknown operator metric scope remains unknown even when its filename is familiar.
Application timing has its own measurement boundary, not an inferred operator
metric scope. Empty headline dictionaries and files with only column names do
not establish observed metrics. A parsed file can still contain invalid cells;
read `issues` for the field used. Excluded collection segments and unparsed
binaries can appear in the inventory without supporting diagnosis.

For `missing_observed` identity, inspect the recorded target name and kernel
selector (`msprof op --kernel-name`); collecting Default is not the general fix.
Treat missing-family follow-ups as conditional on the question. A usable
PipeUtilization observation remains usable when ArithmeticUtilization is absent.

## Verify Only What The Claim Needs

For operator CSVs, use [field selection](04-output-files.md#field-selection).
`--field` returns full matching statistics; `--record` returns same-record
context. `--field ... --records` pages raw rows. Follow `next_command` for the
population needed by the claim; `sample_rows` only locates fields.

A field's min/median/max does not locate its maximum or second-largest block.
Use `core_time_distributions` for that question, then the selected record.
Independent maxima can belong to different blocks. `joint-row` operates on one
operator CSV; it neither merges metric families nor establishes simultaneous
sampling. Across files, retain segment/launch identity and align `block_id` /
`sub_block_id`. Derived time/core-time quotients do not replace recorded ratios.

For application CSVs, inspect the summary timing observations and the cited raw
row directly. For simulator evidence, follow the simulator model's parser status
and source references. `joint-row` is not the reader for these two branches.
Use `evidence_relations[]` to inspect mechanically linked evidence together;
links alone establish neither cause nor a code-change recommendation.

Apply the missing-derived exception only when the branch's primary derived JSON or
`analysis/raw_artifact_index.json` is absent. Before opening raw evidence, state
which derived or index artifact is missing. Limit raw reads to diagnosing that
blocker or a bounded, read-only interpretation; cite each exact raw artifact and
field used. Withhold optimization or code-change claims whose target, readiness,
metric, correctness, or comparison gates depend on the missing artifact.
Regenerate from preserved artifacts where supported. Expand to a complete raw
file when aggregation needs all rows, parsing is ambiguous or sourced observations
conflict; state that reason.

Stop when the question has a supported answer or a specific evidence gap, each
material claim has an artifact and field, and the limitations that could change
the answer are explicit. Unrelated missing families do not require collection.

## Caller Integration: Kernel-Agent

Kernel-agent hands the caller per-sample `profile_analysis` paths (`key_metrics`,
`summary`, `raw_artifact_index`) together with source identity, measurement status
and sample retention context. Start from the relevant sample's supplied paths;
`reading_guide.md` is beside its key_metrics file and is linked there. Preserve
sample and source identities when using its evidence interface or the skill CLI.
A reading guide from another sample is not a substitute for those receipts.

Executor owns its measurement protocol and formal metric. Keep that recorded
mode and boundary in the answer; a metric named `device_program_duration_ms`
alone does not say whether it is natural-launch or profiler timing. The skill's
natural performance assessment consumes its explicit benchmark contract.
Caller-selected official timing and local profiler mechanism observations may
both be useful, but answer different questions. Hypothesis, expected change,
correctness verdict and candidate selection stay in the caller's experiment record.

For a complete worked route through real data, read
[serial/pipelined matmul](13-real-matmul-walkthrough.md), especially when different
collection segments suggest different timing directions or independent maxima
appear to describe one core.
