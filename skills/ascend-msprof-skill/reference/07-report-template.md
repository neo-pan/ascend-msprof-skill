# Assessment Report Template

Save as `$PROFILE_RUN_DIR/REPORT.md`. Keep the answer tied to the current
question; put large tables in `analysis/`. Machine JSON is the primary evidence
source and Markdown is its rendering.

```markdown
# <kernel_or_operator> Ascend Profiling Report

## 0. Setup

- Question and intended target:
- Observed target and launch coverage:
- Workload shape, dtype and launch metadata:
- Device, driver, firmware and CANN versions:
- Commands, metric scope and output directories:

## Performance Assessment

- Comparable natural-launch benchmark observations, with exact source fields:
- Correctness, workload, protocol and environment checks:
- Observed difference, or the specific reason no comparison is available:

## Mechanism Assessment

- Relevant profiler observations and comparison checks:
- Relationship to the measured implementation/workload, if established:
- Available evidence, missing fields, scope limits and unresolved explanations:

## 1. Headline Numbers

| Metric / raw field / unit | Value | Target / segment / aggregation | Source |
|---|---:|---|---|

## 2. Analysis

Include relevant coverage, analysis dimensions, evidence readiness, mechanical
relations and simulator context. Attribute raw CANN stdout messages to their
source. List collection actions only with the question and gap they address.

## 3. Observations

| Observation | Evidence | Interpretation boundary |
|---|---|---|

## 4. Assessment Limits

## 5. Reproduction
```

## Rendering Rules

- Render `performance_assessment` and `mechanism_assessment` using
  [the result contract](11-candidate-comparison-schema.md). Show a runtime delta
  only when the natural-performance assessment contains one. A single run has
  no comparative speedup. Profiler durations are separate observations.
- Use `target_identity`, `profile_coverage`, `measurement_quality`,
  `evidence_readiness`, warnings and blocked claims to qualify each conclusion.
  Readiness is evidence availability, not a kernel-quality or experiment score.
- Preserve expected/observed launch counts, per-target durations, metric-family
  completeness and app/operator measurement-boundary warnings. A local segment
  supports its recorded subset even when complete-program coverage is absent.
- `analysis_dimensions` organizes sourced signals. Largest headline values and
  dimension order do not prescribe optimization priority. A generic generated
  report is a descriptive evidence summary; the calling agent answers the
  specific performance question from the relevant evidence.
- `evidence_relations[]` are stored mechanical links, not causal findings. When
  present, render their kind, target, confidence, roles, evidence IDs, artifacts,
  field references and optional `source_context_refs[]`. Derive no new relations
  in the report layer.
- An App/Op Correlation table aligns sourced application and operator records.
  It does not compute speedup from those different measurement boundaries.
- `next_collection_actions` are conditional collection recipes. State their
  `necessity`, `unlocks_claims`, `target_scope` and actual missing evidence.
  A pending action need not be executed to answer an independent question.
- `stdout_sections.occupancy_summary`, `roofline_summary` and
  `performance_summary` preserve source paths and raw messages. CANN advice
  remains attributed tool output; it is not the report's recommendation.
- Binary artifacts such as `visualize_data.bin`, `DeviceProf*.bin` and
  `duration.bin` are audit inventory only. Missing optional simulator output
  does not invalidate on-device observations.
- `analysis/tilelang_context.json` and `analysis/profile_context.json` contain
  caller-provided workload, correctness, runtime and implementation context.
  They do not create profiler metrics. `analysis/tilelang_profile_run.json`
  records preparation provenance only.
- Cite simulator source/instruction/pipeline records directly from
  `analysis/simulator_hotspots.json` and their raw artifacts. Preserve simulator
  limitations rather than turning source context into a proposed kernel edit.

Conclude when the current question has a supported answer or a specific,
explained evidence gap. Report code-change hypotheses only as caller-supplied
questions being evaluated; the helper generates no optimization ranking,
experiment prescription or promised performance improvement.
