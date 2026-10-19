# Reading Evidence For A Kernel Decision

## Collection Failure And Source Gaps

Use `evidence --run-dir <run> --question collection` for retained collection
logs, BasicInfo values and viewer inputs. JSON `collection_diagnostics.issues`
keeps each raw log line/hash beside its recovery explanation; Markdown puts
this view first. This run-wide log view accepts no artifact, field, segment or
launch selectors. Use the operator questions for those numeric selections.
If collection failed before any analysis existed, the same entry reads logs
without writing derived files. `context.analysis_status=unavailable` explicitly
leaves numeric/target/formal checks unevaluated; inspect those records separately.

An instruction-sampling argument error explains the failed invocation while
the [closed BIU policy](14-pipeline-evidence.md) determines the recovery boundary.
Ordinary supported command errors remain repairable. No retry command is
inferred from an error string, and independent formal timing remains separate.

For Source, distinguish the reported debug-line/hotspot failure, the existing
unviewed binary, and the absence of numeric files in this package. A stdout
save message alone does not establish what was retained or exported. Inspect
the existing input through the [viewer route](15-cann852-capabilities.md) first;
when source-line mapping is still needed, a matching debug build and supported
collection may be necessary, without guaranteeing usable hotspots.

## Pipe Activity Is A Counter-Derived Quantity

`evidence --question pipe` carries the displayed fields' meaning, denominator
and aggregation/comparison limits next to their values (`field_limits` in JSON). Named
field selections and `joint-row`, including single-record reads, expose the
same registry through `field_definitions`. Markdown and caller reads use these
definitions; values, raw positions and existing `derived_pipe_quotients` stay
unchanged. These are additive read projections, not a new persisted schema.

Use `joint-row --list-fields` for the artifact's field inventory, or
`joint-row --record <n>` for a located record. Inventory cannot be combined
with record, field or scope selectors; conflicting modes return a usage error
with the correction. An inventory's parser issues do not verify a selected row.

Pipe time is counter-derived aggregate activity, not a timestamp interval;
the recorded ratio can use a different denominator from `pipe_time/core_time`.
Read the [versioned semantics](08-ascend-metric-files.md#versioned-metric-semantics)
for the pinned producer implementation. A ratio sum above one is arithmetic
on reported aggregates, not an interval-overlap measurement. The timestamp
path remains available when the actual question requires interval relations.
For inspection priorities and experiments, use the existing
[mechanism reference](06-diagnosis-playbook.md#from-aggregate-activity-to-inspection-priorities).

## A Selected Field Has No Number

Use `evidence --question pipe --artifact <run-relative PipeUtilization.csv>
--field 'aic_mte2_active_bw(GB/s)' --format json` for an AIC active-bandwidth
question. These bandwidth fields live in PipeUtilization, not the Memory file
family. Select an exact artifact from the existing question inventory first.

Field selections expose shared `field_definitions` and additive
`field_availability` notes. Each note's `counts_source.group_index` and `field`
locate the existing `selection.groups` counts; scope and raw content references
stay with the fact. CLI Markdown renders the same notes, and
`RunEvidence.question_evidence()` returns them to callers. There is no new
persisted model, schema, admission state or executable collection action.

Read the counts before the conditional guidance:

- Valid cells, including zero: reuse their scoped population; missing siblings
  remain missing and do not certify full launch coverage.
- Unrecognized fields: inspect the producer's definition. Recollection cannot
  add semantic support to the parser.
- Invalid cells: follow raw records and parser issues before deciding to retry.
- Missing cells/columns: NA alone does not identify the cause. AIV rows do not
  supply an AIC field. For matching AIC rows, inspect metric scope, command and
  instrumentation receipts. If MemoryDetail was requested, inspect that attempt
  before repeating it. Otherwise consult the [capability prerequisites](15-cann852-capabilities.md#field-prerequisites-and-data-origins)
  only if the question needs the number and matching evidence is absent.

The AIC MTE1/MTE2 prerequisite is specific to msprof and the documented/observed
platforms in the shared definition. An identically named npu-compute column does
not inherit it. A failed segment remains raw audit only under the existing
receipt contract; these notes do not readmit its facts. Other segments and
independent natural measurements retain their own admission.

## Entry And Layers

The deliverable is a sourced answer that helps the caller understand its kernel:
where runtime is spent, which mechanism the observations support, what remains
unresolved, and what evidence would resolve it. The caller owns code changes and
experiment selection. A file inventory or a ranked list of counters is not that answer.

For an existing run, use these layers. Move down only for the current question;
return to the scope checks whenever you switch run, sample, segment or target.

| Layer | Entry | What to obtain |
|---|---|---|
| Run and question | Bound question context, or `analysis/reading_guide.md` | Actual identity, coverage, quality and claim limits; choose a question and follow its route. |
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
remain separate by default. Explicit launch aggregation below summarizes repeated
observations within their recorded kernel, collection and core scope.
Default observation pages carry the registered population, denominator and
aggregation limits for the displayed fields; `--field` adds scoped statistics
and registered field metadata. Consult [versioned metric semantics](08-ascend-metric-files.md#versioned-metric-semantics)
when interpreting a field's formula or normalization; the query does not establish
the installed collector's calculation branch.
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

For application timing (also directory reads), `context.question_scope` is an
additive list of segment-local scopes, rendered before run limits in Markdown.
Its `target_identity` reuses the existing segment name identity; the original
`context.target_identity` and `context.readiness` retain run-level semantics.
Each scope's `artifacts` lists only selected files, with `allowed_claims` and
`target_names` derived from admitted, currently readable numeric observations.
Receipt `admitted` still means receipt admission, not target attribution.
A matched target may permit “describe recorded target task values” even without
op metrics. Missing or excess launches limit the description to the observed
subset. `declared_launches_present`, `count_complete` and `extra_counts` describe
the full recorded segment, not the selected artifact/page or benchmark phase.
API/type statistics permit artifact descriptions only; their totals are not
selected-kernel time. Extras remain context, and this descriptive question scope
never grants complete-program ranking, PMU, source binding or natural-performance
claims. Interval claims retain the event reader's same-file/device/stream and
valid-time requirements. Run-level collection suggestions are conditional on the
question needing them; missing op metrics alone do not require new collection
for an app task description.

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
includes registered field metadata and preserves missing/invalid/unrecognized distinctions.
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

Kernel-agent's bound `./evidence question` supplies source/sample identity,
coverage, quality and claim limits with the selected observations. Use that
context when it covers the question; follow its detail references when more
context is needed. If question reads are unavailable, start from the supplied
per-sample `profile_analysis` paths (`key_metrics`, `summary`, `raw_artifact_index`);
`reading_guide.md` is beside key_metrics. Preserve sample and source identities
across these routes. A guide from another sample cannot replace those receipts.

`./evidence fields` provides field names, units and scoped statistics in
`result.groups`. For formulas and normalization, use the versioned metric
semantics linked above.

Executor owns its measurement protocol and formal metric. Keep that recorded
mode and boundary in the answer; a metric named `device_program_duration_ms`
alone does not say whether it is natural-launch or profiler timing. The skill's
natural performance assessment consumes its explicit benchmark contract.
Caller-selected official timing and local profiler mechanism observations may
both be useful, but answer different questions. Missing application timing limits
elapsed-time, gap and overlap claims; it does not invalidate a caller's declared
sum of operator Task Durations. Read that metric's aggregation and sampling from
the formal report, rather than inferring an application timeline from the sum.

When `analysis/profile_context.json` supplies `sampling.program_launches`,
`sampling.steady_state_skip` or `sampling.scope`, the helper preserves those
caller declarations and their source in `analysis_context.sampling`. Question
JSON/Markdown reads the current caller record within its input binding, including
runs whose summary predates sampling support; regenerated reading guides show
the same distinction. For example, 23 captured launches with 3 skipped for
Executor timing still leave the first 3 launches' PMU observations readable.
The caller scope describes that timing subset; it neither filters artifacts nor
establishes a validated benchmark. Missing fields remain absent. Invalid fields
produce local context issues without discarding valid PMU observations.

### Explicit Executor Exports And Local Code

Kernel-agent can attach `analysis/caller_evidence.json` to each formal profile run.
Its `measurement` distinguishes the report's aggregate `value` from the current
process's `sample_duration_ms`, and preserves the recorded mode, boundary, launch
count, skip and process receipts. `identity`, `correctness` and `source_report`
retain the caller's context and original report bytes. A missing old protocol stays
missing. Read these as caller-owned formal `msprof_op` Task Duration evidence;
they do not supply the natural benchmark contract required by `compare`.

For an existing Executor report, use kernel-agent's explicit export command:

```bash
python -m kernel_agent.cli export-profile-evidence \
  --report <report.json> --profile-run <existing-profile-run> --output <new-profile-run>
```

The output is a new copy. Supply `--source <kernel.py>` when needed and
`--path-map <old-root>=<retained-root>` for an explicit historical relocation;
the exporter checks declared hashes. Keep each independent process's profile in
its own output run, even when their caller aggregate value is shared.

`snapshots.source` and `snapshots.generated[]` point to run-relative original
bytes with SHA-256 and their original locations. Diagnostic-only profiles can
provide the same code inventory in `analysis/source_snapshots.json` without
formal timing. Question JSON exposes `context.caller_evidence` and
`context.source_snapshots`; Markdown shows formal timing and local file checks.
`verified` describes local content/report consistency, not correctness certification
or causal attribution. Missing or mismatched code stays a local issue while PMU
remains readable. Referenced reports and code snapshots participate in the query
input binding, so moving the whole run preserves verification and editing its
code invalidates a saved question. External `original_path` values are audit
origins; the reader does not reopen them.

Cite the material stage beside the code location. A loop or barrier in generated
C/C++ establishes that source structure; inspect a matching compiled object to
check final instructions or unrolling. Runtime waiting and critical-path claims
need evidence that distinguishes them from other work. Use the
[mechanism checks](06-diagnosis-playbook.md#from-aggregate-activity-to-inspection-priorities)
to choose a small experiment from a static observation.

### Existing Viewer Inputs

Question reads list an indexed `visualize_data.bin` in `related_evidence`, with
its segment, metric scope and content hash. Its contents and target binding are
still unverified; missing numeric families stay missing. Check the collection
receipt and use the [Source viewer route](15-cann852-capabilities.md) before
deciding whether the current question needs more collection. A missing viewer
or parser does not become available by repeating the original command. Existing
independent CSV and formal timing facts remain usable within their own scope.

### Scoring Range And Repeated PMU Observations

Use an explicit range when relating PMU observations to Executor's scoring subset:

```bash
ascend-msprof evidence --run-dir "$PROFILE_RUN_DIR" --question pipe \
  --launch-scope scored --aggregate-launches --field 'aic_time(us)' --format json
```

`scored` selects numeric launch indices from the recorded skip through the recorded
program launch count. A verified explicit caller export can supply these declarations
when an old profile context lacks them; conflicting declarations require resolution.
Selection uses launch identity, not filename timestamp, lexicographic order or page
size. Invalid/missing declarations leave this selection unavailable instead of
silently falling back to all launches. Default reads still expose all captured PMU.
If one kernel executes several times per program and invocation ordinals cannot
be mapped to program launches, that kernel's scored statistics are excluded with
an explicit mapping conflict; the reader does not guess the grouping.

`launch_selection` records selected and excluded artifacts and BasicInfo/PMU
coverage. `launch_aggregation` reports min/median/max and valid/missing/invalid
counts across those launches, separately for collection root, segment, metric scope,
kernel, family, field, unit and recorded row scope, including block and sub-block.
Each contributing cell retains its raw location and hash. Missing launches or
duplicate same-launch cells narrow that group; a field's readable partial median
does not establish full scoring coverage. A run containing only cold-launch PMU
has no scored median. Repeated launch counts are not independent process counts.
Percentage medians describe the recorded percentages' distribution; they are
not an overall utilization or ratio of summed denominators. PMU aggregation never
replaces median of per-launch whole-program Task Duration sums or the caller's
aggregation across independent processes. `offset`/`limit` page displayed groups,
not the launch population used to compute each group's statistics.

Hypothesis, expected change,
correctness verdict and candidate selection stay in the caller's experiment record.

For a complete worked route through real data, read
[serial/pipelined matmul](13-real-matmul-walkthrough.md), especially when different
collection segments suggest different timing directions or independent maxima
appear to describe one core.
