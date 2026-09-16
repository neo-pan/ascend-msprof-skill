# Summary Schema

## Contents

- [Top-Level Fields](#top-level-fields)
- [Segment Metadata](#segment-metadata)
- [Profile Coverage](#profile-coverage)
- [Stdout Sections](#stdout-sections)
- [Evidence Readiness](#evidence-readiness)
- [Evidence Relations](#evidence-relations)
- [Raw Artifact Index](#raw-artifact-index)
- [Simulator Hotspot Model](#simulator-hotspot-model)
- [Analysis Dimensions](#analysis-dimensions)
- [Next Collection Actions](#next-collection-actions)
- [Metric Scope Policy](#metric-scope-policy)

`analysis/summary.json` is the canonical structured source for agents.
`REPORT.md` is an evidence-cited rendering of that source plus provenance and
TileLang context when present. Agents should read `summary.json` before using
the Markdown report for presentation.

`analysis/raw_artifact_index.json` is a separate audit file, not a
`summary.json` schema extension. It has
`raw_artifact_index_schema_version: "1.1"` and an `artifacts[]` array for
parser-visible raw inputs plus preserved unparsed binary profiler artifacts.

The complete generated contracts are `data/summary.schema.json`
and `data/raw-artifact-index.schema.json`.
They describe normalized structure; model loading also checks selection,
coverage and derived-state consistency without rereading raw files.

When an old or invalid derived file fails loading, preserve that error separately
from missing evidence. Regenerate profiler summaries/indexes with `analyze` and
provenance with `provenance` from the run's saved sources. These commands do not
reconstruct unsupported historical target declarations or collection receipts;
resolve those input problems before making claims that depend on them.

## Top-Level Fields

- `analysis_schema_version`: stable analyzer contract version. Current value:
  `5.1`.
- `headlines`: application timing and operator groups contain validated
  per-artifact observations and a legacy `primary` uniqueness record. OpBasicInfo also carries
  sourced metadata. Multiple candidate scopes retain facts without a unique headline.
- `stdout_sections`: raw parsed profiler stdout sections.
- `collection_receipts`: consumed execution results and located parsing issues,
  shared by segment admission and consistency checks.
- `analysis_context`: consumed workflow executions, declared target, metadata
  target names, sourced workload records and issues. Identity, segment binding
  and readiness reasons share these facts.
- `analysis_dimensions`: Ascend-native inspection dimensions and signals.
- `evidence_readiness`: additive run-level readiness model. It summarizes
  which evidence families are available, which are missing, what claims are
  allowed or blocked, and the minimal follow-up recommendations. It does not
  change natural-performance assessments.
- `evidence_relations`: additive mechanical links across corroborated evidence
  families. Relations can connect timing plus metric artifacts, or timing plus
  metric plus simulator context. They are not performance-cause, root-cause,
  or code-change claims and do not change readiness or natural-performance assessments.
- `next_collection_actions`: profiler collection follow-ups generated from a
  selected known metric scope and observed missing evidence.
- `metric_scope`: selected `--aic-metrics` value when it is discoverable from
  command logs.
- `measurement_quality`: current/rated frequency distributions with exact
  `OpBasicInfo` citations. These warnings are context only and do not change
  readiness, sample inclusion, or natural-performance assessments.
- `target_identity`: expected-vs-observed operator identity check. Expected
  targets come from `analysis/profile_context.json` or
  `analysis/tilelang_context.json` fields such as `expected_kernel_name`,
  `expected_op_name`, `target_kernel_name`, or `target_op_name`. TileLang
  context can infer expected `main_kernel`, with the actual framework field
  cited and `inferred: true`. Invalid target-name values remain issues rather
  than being converted to names. Observed names come from
  `op_basic_info` metadata and `op_summary` / `task_time` observations.
  Aggregate operator-type labels and `N/A` task placeholders are not kernel identities.
  Status values are `match`, `mismatch`, `partial_mismatch`,
  `missing_observed`, `unverified`, or `missing`. Mismatch statuses block attribution to the intended target. Observed records include `match_rule` when an
  expected target exists: `exact`, `known_suffix`, or `unmatched`. Run-level
  `confidence` is `high` only when all matched records name the same exact
  target, `medium` for accepted suffix matches or multiple distinct exact
  observed targets, `low` for unverified observed targets, and `blocked` for
  mismatch, partial mismatch, or missing observed targets. This is the public
  target-alignment surface; do not add a separate target-alignment object.
- `warnings`: missing or invalid evidence observed by the analyzer.

The complete envelope requires every headline group, with an empty `artifacts`
array when no artifact from that group is admitted. Artifact presence and usable
metrics are separate facts. Runtime run location is held by the loader; the
envelope has no `run_dir` or duplicate `files` inventory.

## Profile Coverage

Profile coverage schema `1.1` is the launch-count, duration, and
per-launch metric-family coverage surface; `target_identity` remains the only
name-alignment vocabulary. Only an explicit manifest `target` enables verified
count completeness and coverage-driven readiness.

Top-level fields include `explicit_target`, `kernel_selector`,
`expected_total`, normalized `expected_counts`, dynamic `segments`,
`selected_segments_by_family`, and `measurement_boundary`. Segment entries
record their counting authority, expected and observed counts,
`missing_counts`, `over_counts`, `extra_counts`, `count_complete`, total and
per-target duration, source artifacts, ambiguities, and operator
`metric_coverage` when applicable. Each segment also records its target scope
and segment-local target identity. Focused segments cannot populate
complete-program `selected_segments_by_family` authority.

Unavailable or overflowing duration aggregates are `null`; finite observations
and authoritative launch counts remain independent. An aggregation overflow
retains a located `aggregate_overflow` issue in the timing artifact.

App counts come only from each parsed row of the single `op_summary_*.csv` in
the single recorded `PROF_*` tree; `Calls` never contributes. Operator and
follow-up counts come only from one parsed one-row `OpBasicInfo` for each
supported launch key: either a nested `(segment, OPPROF root, kernel directory,
launch directory)` key, or, under the strict single-launch conditions below, a
flat `(segment, OPPROF root)` key. Metric CSVs cover that key but never add
launches. The `memory` family requires exactly one non-empty `Memory`,
`MemoryL0`, and `MemoryUB` artifact per expected launch.

App and operator segment totals are different measurement boundaries and must
not be reported as a direct performance delta. Legacy identity-only or
target-absent runs may expose observed audit coverage, but it is unverified and
does not change their established readiness or relation behavior.

## Segment Metadata

Schema `1.2` added additive source metadata so agents can distinguish evidence
from app, op, follow-up, simulator, or unknown collection segments without
changing artifact paths.

Schema `1.3` adds a structured simulator hotspot model artifact at
`analysis/simulator_hotspots.json`. The source/pipeline analysis dimension
records `model_artifact: "analysis/simulator_hotspots.json"` when the analyzer
generates the model. Simulator-derived signals remain raw source and pipeline
context with `segment: "simulator"` and `metric_scope: null`; they do not create
diagnosis rows or standalone simulator-only code-change directions.

Segment values are:

- `app`
- `op`
- `followup:<segment-id>`; focused Default collection uses a deterministic
  segment id distinct from the canonical action id.
- `simulator`
- `unknown`

The analyzer records `segment` and `metric_scope` on
`headlines.<group>.artifacts[]`, `analysis_dimensions[].signals[]`, and
`evidence_relations[].evidence[]`. `metric_scope` is populated only when
the selected `--aic-metrics` scope is discoverable from existing command logs,
or when a supported follow-up action defines it. App, simulator, and unknown
segments use `null` unless existing command evidence proves a scope.

## Provenance

`analysis/provenance.json` uses schema version `2`; its generated contract is
`data/provenance.schema.json`. Recorded values carry
their original artifact and field. Runtime run-directory paths are supplied by
the command, rather than persisted in this manifest.

`cann_version` records component evidence and selects a value only when those
sources agree. Conflicts retain their evidence with a null selected value.
Version comparison also requires a shared recorded component. An invalid
collection-environment receipt leaves version identity unavailable while valid
hardware and component facts remain recorded.

Report and comparison loaders validate the same current contract. Missing
provenance and invalid present provenance are distinct; optional invalid
provenance adds a warning without invalidating independent natural measurements.

## Caller Context

`analysis/profile_context.json` and `analysis/tilelang_context.json` retain
caller-provided context. Loaders normalize the consumed workload, source identity,
JIT inventory, correctness flags and timing fields once; report and comparison
views use those facts with the original context field references. Invalid fields
produce located warnings while healthy fields remain available. Arbitrary JIT
configuration and metadata remain uninterpreted JSON.

These context timing values describe the caller's records. Natural-performance
eligibility comes from the independent benchmark assessment contract described in
[input and assessment schemas](11-candidate-comparison-schema.md).

## Stdout Sections

`stdout_sections` may contain `occupancy_summary`, `roofline_summary`, and
`performance_summary`. Each present section records its source log, section
name, and original CANN messages. Occupancy and Performance messages retain
their integer ordinal; RoofLine messages are unnumbered. Message attribution
comes from the enclosing section's `source`. These statements do not create
headline metrics, bottleneck findings or code-change advice by themselves.

## Evidence Readiness

`evidence_readiness` is additive to the analyzer schema. It is a run-readiness
audit, not a performance score or candidate-selection decision. It is the evidence-quality
surface; do not add an `evidence_quality` alias. Current fields are:

- `schema_version`: `2.0`.
- `level`: `insufficient`, `partial`, or `available` for single-run analysis.
  This describes evidence availability, not experiment readiness. Comparison readiness is
  reserved for comparison artifacts, not `ascend-msprof analyze`.
- `reasons[]`: concise reasons for the selected level.
- `available_evidence_families[]`: families such as `app_timing`,
  `operator_metadata`, `pipe_utilization`, `arithmetic_utilization`,
  `memory_cache`, `resource_conflict`, `simulator_source_pipeline`, or raw
  stdout summary families.
- `missing_evidence_families[]`: missing high-level families such as
  `app_timing` or `operator_metric`. Source context is needed only for questions
  that require source attribution.
- `allowed_claims[]`: supported profiler claims, such as ranking the
  application hot path or describing recorded AI Core pipe fields.
- `blocked_claims[]`: claims blocked by missing evidence, such as source-line
  attribution without simulator/source artifacts.
- `recommended_followups[]`: recommendations only. They reuse existing
  `next_collection_actions` when present or provide minimal collection
  suggestions; they do not execute collection.
- `segments[]`: compact per-segment readiness entries with `segment`,
  `metric_scope`, `status`, and `missing_required_artifacts`.
- `unparsed_binary_artifacts[]`: preserved binary profiler artifacts from the
  raw artifact index, including their segment, known role, and
  `diagnosis_role: "not_used"`.

`available_evidence_families` is a run-wide inventory, not complete-program
claim authority. For an explicit target, interpret a family together with its
`segments[]` scope and `profile_coverage.selected_segments_by_family`; a
complete scope-local segment can support its recorded target subset without
becoming complete-program evidence.

Readiness levels describe the evidence inventory:

- `insufficient`: no usable timing/metric evidence in the relevant readiness surface.
- `partial`: some evidence is present, but timing, metrics, identity or declared
  coverage is incomplete. Read the per-family and per-segment facts for usable subsets.
- `available`: timing and at least one operator metric family are present without
  a known target mismatch. For an explicit target, application launch counts and
  the selected operator metric family's per-launch coverage must also be complete.

Availability establishes neither root cause nor experiment quality. Workload,
correctness and natural measurement comparability remain independent assessment
checks. Simulator collection is optional; missing simulator context alone does
not lower readiness. Without an explicit target, count completeness is unverified.

The app-level timing contract recognizes `op_summary_*.csv`, `task_time_*.csv`,
`op_statistic_*.csv`, and `api_statistic_*.csv`. Each corresponding
`headlines.<group>` contains `group`, `artifacts[]`, and `primary`:

- `artifacts[]` records the raw path, segment, columns, row count, bounded raw
  samples, decode status, issues, and representative `observations[]` by scope
  and statistic. `op_summary` also records row-based launch counts; `Calls` is
  not a launch multiplier.
- A successful observation has a finite `value`, explicit `unit` and
  `statistic`, the original `raw_token`, subject `name`, recorded `scope`, and
  `source` with the actual artifact, field, CSV record and column. CSV records
  count from the header at 1, including records containing quoted newlines.
- `primary` records candidate source references, the selected reference (or
  null), and `reason`: `selected`, `no_valid_observation`, `multiple_scopes`, or `multiple_observations`.
  All available statistics remain candidates; only a sole candidate resolves
  `selected`. Multiple fields in one scope use `multiple_observations`;
  `multiple_scopes` denotes distinct artifact/collection scopes. This record
  does not choose the answer's main evidence. Timing readiness checks actual
  scope uniqueness independently of this record.

The generated `data/application-timing.schema.json` describes these strict
Pydantic facts. Unknown fields remain in raw files and samples;
unsupported numeric fields are not guessed. Duplicate headings, malformed row
widths, conflicting aliases, and invalid numeric tokens produce located issues.
Valid subsets remain visible even when structure errors prevent complete launch
counting. JSON loading rejects duplicate keys and nonstandard numeric constants;
old normalized summary versions require reanalysis of the original artifacts.
At loading, timing artifacts are checked against the admitted raw index paths,
groups, segments and inventory metadata. Paths must stay relative to the run.
When the optional raw index is unavailable, the loader records that inventory
consistency cannot be checked; it does not reread raw CSVs to establish it.

The report, key metrics, dimensions and comparison facts use these observations.
A group with multiple candidate scopes retains its observations and reports the
ambiguity instead of claiming timing is absent. Without an explicit target, an
app segment whose observations span unresolved artifact/collection scopes is
`ambiguous_timing`. Multiple statistics within one scope do not cause ambiguity.
Aggregate operator-type and host/runtime API statistics retain their meaning;
neither is an individual device task duration.

File presence alone does not establish timing availability. Without an explicit
target, an app segment with recognized files but no parsed finite timing value
has status `no_usable_timing`; `missing_required_artifacts` remains empty because
the files are present. Inspect the raw index and cells to distinguish empty,
unreadable and invalid-value inputs. Target coverage is checked separately.

### Operator CSV facts

Operator groups use the same `group`, `artifacts[]`, and `primary` structure.
`data/operator-evidence.schema.json` is generated from the Pydantic model.
All recognized operator CSVs are decoded once; inventory, launch identity,
coverage and frequency context consume the resulting facts.

- `OpBasicInfo` records text and strict integer metadata separately from numeric
  observations. `Block Dim` is launch metadata, and `Current Freq` / `Rated Freq`
  are frequency observations in MHz. None is a task duration. Blank or `N/A`
  metadata stays unavailable; malformed integers produce located issues.
  Each retained metadata observation carries its subject `name` (null when
  unavailable), so deduplication does not lose the name used by report signals.
- Pipe/arithmetic/conflict `_ratio` fields retain their dimensionless ratio
  scale. Fields explicitly labeled `(%)` retain percent scale. Bandwidth, KB
  volume, estimated volume and microsecond durations remain distinct.
- Each file retains one representative maximum per recognized metric and
  recorded device/process scope, with its original core, CSV record and column.
  Full core distributions remain in the original CSV. A representative maximum
  does not establish imbalance or a bottleneck.
- PipeUtilization also recognizes fixture-backed and msopprof-documented
  microsecond pipe times (`aic_time(us)`, `aic_cube_time(us)`,
  `aic_scalar_time(us)`, `aic_mte1_time(us)`, `aic_mte2_time(us)`,
  `aic_mte3_time(us)`, `aic_fixpipe_time(us)`, `aiv_time(us)`,
  `aiv_vec_time(us)`, `aiv_scalar_time(us)`, `aiv_mte2_time(us)`,
  `aiv_mte3_time(us)`), active-bandwidth fields
  (`aic_mte1_active_bw(GB/s)`, `aic_mte2_active_bw(GB/s)`,
  `aic_mte3_active_bw(GB/s)`, `aic_fixpipe_active_bw(GB/s)`,
  `aiv_mte2_active_bw(GB/s)`, `aiv_mte3_active_bw(GB/s)`), and
  `aic_icache_miss_rate` / `aiv_icache_miss_rate` as dimensionless ratios.
  Active bandwidth stays distinct from Memory-family bandwidth.
  `artifacts[].core_time_distributions[]` summarizes recognized duration fields
  per file and recorded scope excluding `block_id`, retaining device/process and
  sub-block separation. It records `valid_count`, `median_us`, `maximum` and
  `second_largest` located observations (null for a singleton). Ties retain two
  cells. Only valid nonnegative cells with numeric block IDs and a sub-block ID
  contribute; CSV issues and raw rows remain available. These are cell
  distributions, not launch counts, natural latency, or frequency-normalized
  values. Reports, candidate Markdown and key metrics render the same facts.
  Cycle-count columns such as `aic_total_cycles` remain raw until explicitly
  mapped.
- Per-metric maxima and distribution extrema are located cells, not a joint
  execution state. Before treating several fields as co-occurring **within one
  operator CSV**, confirm they share the same artifact and CSV `record` (via
  `ascend-msprof joint-row` or the `joint_operator_row` helper). Different
  `block_id` / `sub_block_id` / `record` values remain separate observations.
  Cross-family co-occurrence uses matching scope keys across separate files;
  it is outside a single joint-row result. Skill aggregation retains one
  unweighted maximum cell per metric and does not compute Σnum/Σden.
- A supported `Metric,Value` layout records the actual numeric `Value` cell
  as `source` and the `Metric` label cell as `metric_source`. The label must match
  an explicit supported field; unfamiliar labels are not inferred by substring.
  Frequency quality identifies observations by `metric` in either supported
  layout and cites the original numeric cell; existing launch-scope checks apply.
- Every non-frequency metric observation remains a candidate, independent of
  magnitude or unit family. Frequency remains measurement-quality context.
  Reports expose all observations and their block/sub-block locations.
  A coverage-selected segment can constrain the report/comparison view without
  deleting other collected facts. No cross-metric maximum selects a headline.

The field definitions follow the references in `data/reference-sources.yaml`.
The [official msopprof implementation](https://github.com/Ascend/msopprof/tree/80dae2e3701d14e191d2d461eb6be8aab714d89d/csrc/op_profiling/profiling/device/data_parse)
also confirms the 910B headers and numeric scales: `CalRatio` divides cycles
without multiplying by 100, and time calculations divide cycles by the recorded
frequency to produce microseconds. Support remains limited to explicitly mapped
fields exercised by the raw fixtures.

## Evidence Relations

`evidence_relations[]` records corroborated cross-family artifact links. It is
empty when no supported relation exists and must stay empty for timing-only,
simulator-only, stdout-only, or binary-only runs. Relations are explanatory
only: they cite artifacts that can be inspected together and explicitly block
performance-cause or root-cause interpretation by themselves.

Supported `kind` values are:

- `timing_plus_pipe`
- `timing_plus_arithmetic`
- `timing_plus_memory_cache`
- `timing_plus_resource_conflict`
- `timing_metric_plus_simulator_source`
- `timing_metric_plus_simulator_instruction`
- `timing_metric_plus_simulator_trace`

Each relation contains:

- `id`: stable relation id for the run.
- `kind`: relation kind from the supported list above.
- `target`: the aligned profiled target when available, otherwise the timing
  signal name.
- `confidence`: copied from `target_identity.confidence` when it is `high`,
  `medium`, or `low`; blocked target identity prevents relation emission.
- `role`: concise relation role, such as mechanical timing-to-pipe artifact
  link.
- `evidence[]`: sourced observations selected by the shared per-artifact scope
  rules. For explicit targets, each metric family contributes observations
  from its coverage-selected segment. Multiple scopes remain separate
  references; the relation does not aggregate their values into one headline.
- `allowed_interpretation`: what the relation permits an agent to inspect
  together.
- `blocked_interpretation`: what the relation must not be used to claim.
- `source_context_refs[]`: optional references into
  `analysis/simulator_hotspots.json` for simulator-backed relations.

Do not derive relation targets from `analysis/raw_artifact_index.json`.
Unparsed `.bin` artifacts are never diagnosis evidence and never create
relations.

## Raw Artifact Index

`raw_artifact_index.json` records recognized CANN CSV groups, application
timeline `msprof_*.json`, simulator `trace.json` and `core*_*.csv`, stdout
files that produced parsed `stdout_sections`, and preserved unparsed binary
profiler artifacts. Parser-visible artifact records keep:

- `artifact`: run-dir-relative path.
- `group`: analyzer group such as `op_summary`, `app_timeline`,
  `simulator_trace`, `simulator_csv`, or a `stdout_*_summary` group.
- `parser`: `csv`, `json`, or `stdout`.
- `segment`: `app`, `op`, `followup:<action-id>`, `simulator`, or `unknown`.
- `metric_scope`: selected op/follow-up scope, otherwise `null`.
- `status`: `parsed`, `empty`, or `invalid`.
- `columns`: CSV columns, otherwise empty.
- `row_count`: CSV row count, JSON event count, or stdout message count.
- `sample_rows`: first parsed CSV rows, JSON events, or stdout messages.
- `warnings`: artifact-local parser warnings.

Recognized onboard operator CSVs may use the exact canonical filename or the
canonical stem followed by `_` and exactly 17 decimal timestamp digits. When a
supported nested `OPPROF_*/<kernel>/<launch>/` path is available, records also
include the canonical stem, launch ordinal/key, and OPPROF/kernel/launch path
metadata. When that launch key has exactly one parsed one-row `OpBasicInfo`, its
target name and normalized target name are attached to every recognized sibling
record for that launch.

An explicit initial `op` target or a persisted follow-up target (either a
focused subset or the complete program) with `expected_total == 1` may also
receive one stable launch key when all recognized operator CSVs are flat under
exactly one `OPPROF_*` root and exactly one parsed one-row `OpBasicInfo` matches
the target by the existing exact or known-suffix rule. Multiple roots,
keyed/flat mixtures, multiple, empty, invalid, or multi-row `OpBasicInfo`, and
target mismatch remain unkeyed and fail closed. Proper focused subsets remain
segment-local and do not populate complete-program
`selected_segments_by_family` authority, while a verified single-launch
complete-program segment retains complete-program authority.

Follow-up target authority is admitted only for the canonical complete-program
segment or a succeeded supported focused action whose persisted selection is a
valid program subset. Unsupported, failed, or unbound follow-up segments remain
`observed_run` and cannot populate `selected_segments_by_family`.

When an app, op, simulator, or supported follow-up result receipt exists, its
segment contributes derived evidence only when the receipt status is
`succeeded`. `collection_receipts.records` stores each present recognized
receipt's `segment`, run-relative `artifact`, `status`, and `issue`. Valid
execution statuses are `succeeded`, `failed`, `core_dump`, and `timeout`.
A malformed receipt has `status: null` and a located `issue`; duplicate JSON
keys and invalid status values exclude that segment. Excluded artifacts remain
in the raw artifact index. Missing receipts have no record and impose no
receipt gate; absence does not prove successful collection.

Headline, stdout, coverage and simulator selection share one receipt read per
analysis. Required loading rejects retained facts excluded by current receipts,
including when the optional raw index is absent. Assessment loading records
invalid profiler evidence while preserving independent natural measurements.

Malformed JSON appears as an `invalid` raw-index record and raw-index warning
without adding new summary semantics. Unsupported simulator JSON shapes are `invalid`; application JSON inventory follows its own format rules.

Unparsed binary artifact records use `group: "unparsed_profiler_binary"`,
`parser: "none"`, `status: "unparsed"`, `size_bytes`, `known_role`,
`diagnosis_role: "not_used"`, and `notes`. Known roles include MindStudio
visualization artifacts such as `visualize_data.bin`, simulator visualization
artifacts, internal `dump/DeviceProf*.bin`, internal `dump/duration.bin`, and
kernel object binaries. These records preserve auditability only; they must not
raise readiness, enable claims, create headlines, or feed diagnosis.

## Simulator Hotspot Model

The generated `data/simulator.schema.json` describes the
persisted fields. `analysis/simulator_hotspots.json` uses
`simulator_hotspot_model_schema_version: "2.0"`. It records admitted simulator
CSV and trace facts:

- `inputs[]`: artifact path, kind, parser status, row/event count, columns,
  bounded raw samples, located issues and trace presentation metadata.
- `selected_trace_artifacts[]`: aggregate traces or per-core traces selected
  independently within each simulator collection. They are never added together.
- `source_lines[]` and `instructions[]`: per-artifact source/instruction identity,
  record counts and separate metrics for exact `call_count`, `cycles`, and
  `running_time(us)` fields. Counts and cycles are integers; time is in microseconds.
  Each metric records its complete `total` when available, a finite `maximum`
  with its raw token and source, valid record positions, and total record count.
  Missing/invalid contributors or overflow leave the total null while preserving
  a valid maximum. Source rows may carry a run-local source snippet and context tags.
  Unrepresentable integer tokens produce local issues. Invalid counts or source
  line numbers preserve independent running-time evidence and the original code token.
- `pipeline_events[]`: per-artifact/process/thread duration totals and maxima in
  microseconds, valid and observed event counts, and the maximum's event source.
  `displayTimeUnit` controls presentation and does not determine numeric duration units.
- `flow_categories[]`: raw flow category event counts with a located source.
- `sync_events[]`: raw `SET_FLAG`/`WAIT_FLAG` B/E trace-record counts. CSV
  instruction metrics remain in `instructions[]`; these counts are not combined
  into a call count, paired wait interval, or synchronization cost.
- `mte_throughput[]`: per-artifact/channel maximum, average and sample count for
  the confirmed `throughput(MB/s)` field, with the maximum's event source.
- `warnings[]`: parser and missing-input notes.

Unknown fields remain raw evidence. Consumers use the normalized metrics and
explicit statistics; they do not rediscover aliases or reread simulator CSV/JSON.
`analysis/simulator_hotspots.txt` renders the same model for human inspection.

## Analysis Dimensions

`analysis_dimensions[]` records the six Ascend-native dimensions from
`reference/05-analysis-dimensions.md`. Each signal keeps:

- `artifact`
- `field`
- `field_ref`
- `signal`
- `value`
- optional `evidence_id`
- optional launch metadata fields such as `tiling_field` and `tiling_value`

## Next Collection Actions

`next_collection_actions[]` appears only when a known selected metric scope
and missing evidence justify follow-up collection. Every action keeps:

- `id`
- `reason`
- `recommended_aic_metrics`
- `required_artifacts`
- `evidence`
- `confidence`
- `necessity`: required; `blocking`, `optional`, or `question_required`.
- `unlocks_claims[]`
- `target_scope`
- `estimated_cost`: estimated launches, metric scopes, and segment count.

These actions are conditional collection recipes. A pending action is relevant
only to claims requiring its missing fields and target scope; it does not block
independent conclusions or require filling every metric family.

Missing-artifact evidence cites `headlines.<group>.artifacts`; warning prose is
display context. The loader checks actions and readiness follow-ups against the
same derivation used by the analyzer. A present but invalid artifact retains its
parser issue rather than becoming an absent file.

For the currently supported `collect_default_metric_followup` action, explicitly
select the `question_required` action, then collect
the generated Default metric segment under
`reports/followups/collect_default_metric_followup/` and record the command in
`logs/command_msprof_followup_collect_default_metric_followup.txt`; the final
`analysis/summary.json` should then have an empty `next_collection_actions`
array when complete-program Default artifacts are present. A focused follow-up
uses a deterministic separate segment/output/log identity and may leave the
complete-program action pending and collectable.

A focused target JSON selection must be count-bounded by the persisted program
target and must not match an unselected target. Its segment records
independent identity and coverage; if the normalized selection is a proper
subset, its segment remains excluded from complete-program selected-segment
authority, while if it exactly matches the complete one-target, one-launch
program, its derived segment scope is complete_program and follows the verified
single-launch authority rule documented above.

## Metric Scope Policy

The analyzer/report policy recognizes these `--aic-metrics` values:
`PipeUtilization`, `Default`, `KernelScale`, `ResourceConflictRatio`,
`PMSampling`, `Occupancy`, and `Roofline`.

`metric_scope` records the command value, artifact, and `--aic-metrics` field
reference. The shared metric-scope policy defines required and optional
artifacts, stdout sections, and report caveat behavior; a copy of that policy
is not persisted in each summary. Missing required artifacts remain caveats. Optional
or out-of-scope metric families can be suppressed as report caveats only when
the selected known scope explicitly allows that behavior.

Unknown scopes keep current analyzer warnings and report caveats. They do not
generate next-collection actions.

## Independent Assessments

The profiler summary schema remains unchanged. Candidate and comparison schema
2.0 separate natural performance from mechanism observations. The sole natural
measurement carrier is `analysis/benchmark_context.json`; missing new benchmark
records leave performance incomplete while profiler inspection remains usable.
See [input and assessment schemas](11-candidate-comparison-schema.md).

## Caller-selected emphasis

The legacy `headlines` key stores evidence families, not an importance ranking.
The calling agent selects the answer's main observations using its question,
source code and measurement boundaries. Generated reports do not select a
one-line conclusion. Metric order is stable presentation order.

Located references include `aggregation=maximum_observed_cell`, the raw field's
unit/statistic, and recorded scope including block/sub-block where available.
This aggregation describes the retained cell among observations of the same
field and scope; it is not a program total, distribution or bottleneck judgment.
For example, the largest `Min Time(us)` cell remains a minimum reported for
that named row; it is not the minimum across the entire file.

Schema 5.1 changes the legacy candidate-selection semantics. Regenerate a 5.0
summary and raw index together with `ascend-msprof analyze --run-dir <run>`,
then regenerate candidate/comparison artifacts. This reuses preserved inputs;
no profiler recollection is required. Invalid target declarations remain a
separate input error.
