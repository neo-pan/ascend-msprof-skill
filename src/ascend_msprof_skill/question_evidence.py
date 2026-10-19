"""Question-sized views over RunEvidence and the existing operator readers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex

from .evidence_binding import CONTRACT_VERSION, GENERATION_LIMIT, raw_reference, snapshot, verify_reference, safe_path
from ._evidence_artifacts import recognized_group_files
from ._evidence_readiness import describe_readiness_claim
from ._profiler_segments import segment_for_relpath
from .metric_scope_policy import missing_artifact_labels
from .joint_row import select_records
from .operator_evidence import OP_FIELDS, normalize_operator, operator_support_gaps
from .run_evidence import RunEvidence
from .collection_context import SamplingContext
from .coverage_types import declared_launches_present
from ._evidence_text_summary import sampling_context_lines
from .scoped_operator_evidence import select_launches, aggregate_launches as aggregate_operator_launches
from .caller_evidence import load_caller_evidence, load_source_snapshots, caller_context_lines
from .pipeline_evidence import collection_diagnostics

# Reading questions are independent of paired-mechanism assessment questions.
QUESTIONS = {
    "pipe": ("Which pipe activities were recorded?", ("pipe_utilization",)),
    "arithmetic": ("Which arithmetic activities were recorded?", ("arithmetic_utilization",)),
    "memory": ("Which memory movements and cache fields were recorded?", ("memory", "l2_cache")),
    "application-timing": ("Which application tasks and intervals were recorded?", ("op_summary", "task_time", "api_statistic", "op_statistic")),
    "collection": ("What failed, what remains usable, and which recovery is supported?", ("op_basic_info",)),
}


def question_routes(run_dir: Path) -> list[dict]:
    return [{"id": key, "question": title, "command": shlex.join([
        "ascend-msprof", "evidence", "--run-dir", str(run_dir), "--question", key])}
        for key, (title, _) in QUESTIONS.items()]


def _context(run: RunEvidence, segments: set[str]) -> dict:
    summary = run.summary()
    # Caller sampling is descriptive, not a persisted target/coverage decision.
    # Read the already loaded context within the snapshot boundary, including
    # runs whose analysis predates sampling support. Selection is a separate opt-in.
    analysis_context = summary.analysis_context.model_dump(mode="json")
    analysis_context.pop("sampling", None)
    analysis_context["issues"] = [issue for issue in analysis_context["issues"]
                                  if not issue["code"].startswith("sampling_")]
    caller = run.profile_context()
    if caller is not None:
        if caller.sampling is not None:
            analysis_context["sampling"] = caller.sampling.model_dump(mode="json")
        analysis_context["issues"].extend(issue.model_dump(mode="json") for issue in caller.issues
                                          if issue.code.startswith("sampling_"))
    result = {
        "target_identity": summary.target_identity.model_dump(mode="json"),
        "profile_coverage": {"explicit_target": summary.profile_coverage.explicit_target,
            "segments": {key: value.model_dump(mode="json") for key, value in summary.profile_coverage.segments.items()
                         if key in segments}},
        "measurement_quality": summary.measurement_quality.model_dump(mode="json"),
        "readiness": {"meaning": summary.evidence_readiness.scope_note,
            "level": summary.evidence_readiness.level,
            "minimum_gate_missing": list(summary.evidence_readiness.missing_evidence_families),
            "allowed_claims": list(summary.evidence_readiness.allowed_claims),
            "blocked_claims": [describe_readiness_claim(claim) for claim in summary.evidence_readiness.blocked_claims]},
        "analysis_context": analysis_context,
        "limitations": [
            GENERATION_LIMIT,
            "Use the recorded identity and coverage gates before attributing observations to the requested target.",
            "Name identity does not establish source/benchmark association. Natural performance uses the separate performance assessment.",
            "Independent maxima can come from different records. Recorded activity does not by itself prove a bottleneck.",
            "Each collection segment has its own measurement boundary; no cross-segment simultaneous sampling is implied."],
        "load_warnings": run.warnings(),
    }
    for key, loader in (("caller_evidence", load_caller_evidence), ("source_snapshots", load_source_snapshots)):
        value = loader(run.run_dir)
        if value is not None:
            result[key] = value
    return result


def _application_question_scope(summary, inventory: list[dict], timings: dict) -> list[dict]:
    """Project existing segment identity onto selected, freshly read artifacts.

    Receipt admission remains independent of target attribution. Coverage fields
    describe the segment, never the selected page or a benchmark launch phase.
    """
    scopes = []
    for segment in sorted({item["segment"] for item in inventory if item["group"] in QUESTIONS["application-timing"][1]}):
        coverage = summary.profile_coverage.segments.get(segment)
        identity = summary.target_identity.segments.get(segment)
        matched_names = {item.name for item in identity.observed if item.status == "match"} if identity else set()
        artifacts = []
        for item in inventory:
            if item["segment"] != segment or item["group"] not in QUESTIONS["application-timing"][1]:
                continue
            timing = timings.get(item["artifact"])
            usable = bool(item["admitted"] and timing and timing.observations)
            names = sorted({observation.name for observation in timing.observations
                            if observation.name in matched_names}) if usable else []
            target_values = bool(names and identity.status == "match"
                                 and item["group"] in {"op_summary", "task_time"}
                                 and not any(issue.impact == "scope" for issue in timing.issues))
            claims = ["describe recorded artifact statistics"] if usable else []
            if target_values:
                claims.append("describe recorded target task values")
            artifacts.append({"artifact": item["artifact"], "group": item["group"],
                "numeric_observations": item.get("numeric_observations", 0),
                "target_names": names if target_values else [], "allowed_claims": claims,
                "limitation": ("Only the listed target names are attributable; other rows remain context."
                    if target_values else "Target attribution is not established for these statistics.")})
        scopes.append({"question": "application-timing", "segment": segment,
            "target_identity": identity.model_dump(mode="json") if identity else None,
            "coverage_scope": "Recorded segment; not selected artifact/page or benchmark phase",
            "declared_launches_present": declared_launches_present(coverage) if coverage else False,
            "count_complete": coverage.count_complete if coverage else None,
            "extra_counts": dict(coverage.extra_counts) if coverage else {},
            "artifacts": artifacts,
            "blocked_claims": ["rank complete-program hot paths", "infer operator PMU or pipeline overlap",
                "attribute API/type totals to the selected kernel", "establish source/benchmark binding or natural performance"],
            "limitations": ["Task values describe the observed subset; segment count coverage does not certify every timing cell.",
                "Intervals require valid events in the same artifact/device/stream time domain; they do not establish idle time or host cause.",
                "Missing operator metrics do not block these application descriptions; run-level readiness remains separate."]})
    return scopes


def _launch_sampling(context: dict) -> dict | None:
    """Use sourced caller declarations without rewriting a historical profile context."""
    profile = context["analysis_context"].get("sampling")
    caller = context.get("caller_evidence")
    if not caller or caller["status"] != "verified" or not caller.get("measurement"):
        return profile
    measurement = caller["measurement"]
    fields = ("program_launches", "steady_state_skip")
    if profile:
        for key in fields:
            if profile.get(key) is not None and measurement.get(key) is not None and profile[key] != measurement[key]:
                raise ValueError(f"caller export and profile sampling disagree on {key}; resolve declarations before selecting launches")
        if all(profile.get(key) is not None for key in fields):
            return profile
    return {"source": {"artifact": caller["artifact"], "field": "measurement"},
            **{key: measurement[key] for key in fields},
            "scope": "Explicit Executor export of the caller's scoring range; not natural benchmark admission."}


def read_question(run: RunEvidence, question: str | None = None, *, segment: str | None = None,
                  artifact: str | None = None, fields: list[str] | None = None,
                  offset: int = 0, limit: int = 20, launch_scope: str = "all",
                  aggregate_launches: bool = False) -> dict:
    """Reuse validated run decisions; selected CSV values are normalized from bound raw inputs."""
    return read_question_from_dir(run.run_dir, question, segment=segment, artifact=artifact,
                                  fields=fields, offset=offset, limit=limit, launch_scope=launch_scope,
                                  aggregate_launches=aggregate_launches)


def read_question_from_dir(run_dir: Path, question: str | None = None, *, segment: str | None = None,
                           artifact: str | None = None, fields: list[str] | None = None,
                           offset: int = 0, limit: int | None = 20,
                           include_next_steps: bool = True, launch_scope: str = "all",
                           aggregate_launches: bool = False) -> dict:
    """Load once inside the binding boundary. None limit exports all normalized
    observations for callers that paginate delivery; event detail remains a
    separate bounded read. Navigation can omit unused collection suggestions.
    """
    if question is not None and question not in QUESTIONS:
        raise ValueError(f"unknown question: {question}; choose from {', '.join(QUESTIONS)}")
    if offset < 0 or (limit is not None and limit < 1):
        raise ValueError("offset must be nonnegative and limit positive")
    if fields and (question is None or (artifact is None and not aggregate_launches)):
        raise ValueError("field selection requires a question and an exact artifact")
    if launch_scope not in {"all", "scored"}:
        raise ValueError("launch_scope must be all or scored")
    scoped = launch_scope != "all" or aggregate_launches
    if question == 'collection' and (scoped or segment or artifact or fields):
        raise ValueError('collection reads run-local logs and BasicInfo; use an operator question for field/launch/segment selection')
    if scoped and (question is None or question == "application-timing"):
        raise ValueError("launch selection and aggregation require an operator question: pipe, arithmetic or memory")
    # A retained RunEvidence may predate a continuation or regenerated analysis.
    # Reload inside the binding boundary rather than stamping cached gates with
    # current disk hashes. Other RunEvidence readers retain their loaded view.
    root = Path(run_dir).resolve()
    context_binding = snapshot(root, [])
    if question == 'collection' and not (root / 'analysis/summary.json').is_file():
        # Argument/launch failures can precede every report and derived file.
        # Read their logs without manufacturing RunEvidence or writing analysis.
        diagnostics = collection_diagnostics(root)
        if snapshot(root, []) != context_binding:
            raise ValueError('inputs changed during collection query; retry on a stable run')
        return {'question_evidence_version': CONTRACT_VERSION, 'run_dir': str(root),
                'question': question, 'selection': {'segment': None, 'artifact': None, 'fields': []},
                'binding': context_binding, 'collection_diagnostics': diagnostics,
                'context': {'analysis_status': 'unavailable', 'limitations': [
                    'No summary is present. Target, coverage, numeric reports and formal timing have not been evaluated by this log-only query. '
                    'Read retained raw/formal records separately; analyze existing reports if numeric navigation is needed.']},
                'facts': [], 'inventory': [], 'related_evidence': [], 'questions': [], 'inventory_gaps': []}
    run = RunEvidence.load(root)
    index = run.raw_artifacts()
    if not run.raw_artifact_summary().present:
        raise ValueError("raw_artifact_index.json required; regenerate analysis")
    groups = QUESTIONS[question][1] if question else tuple(dict.fromkeys(g for _, gs in QUESTIONS.values() for g in gs))
    entries = [item for item in index if item.group in groups
               and (segment is None or item.segment == segment)
               and (artifact is None or item.artifact == artifact)]
    if artifact is not None and not entries:
        raise ValueError("artifact is outside the selected question/segment inventory")
    if segment is not None and not any(item.segment == segment for item in index):
        raise ValueError("segment is not in this run's inventory")
    selection = {"question": question, "segment": segment, "artifact": artifact,
                 "fields": fields or [], "offset": offset, "limit": limit}
    bound_artifacts = [item.artifact for item in entries]
    viewer_entries = [item for item in index
                      if item.group == 'unparsed_profiler_binary'
                      and item.artifact and Path(item.artifact).name == 'visualize_data.bin'
                      and (segment is None or item.segment == segment)
                      and (artifact is None or item.artifact == artifact)]
    bound_artifacts.extend(item.artifact for item in viewer_entries)
    if scoped:
        selection.update(launch_scope=launch_scope, aggregate_launches=aggregate_launches)
        # BasicInfo establishes launch completeness independently of PMU. Its
        # raw availability is consulted below, so bind it inside the query too.
        bound_artifacts.extend(item.artifact for item in index if item.group == "op_basic_info"
                               and (segment is None or item.segment == segment))
    binding = snapshot(root, bound_artifacts, selection=selection)
    if (context_binding["members"] != binding["members"]
            or any(binding["files"].get(name) != value for name, value in context_binding["files"].items())):
        raise ValueError("inputs changed during query load; retry on a stable run")
    context = _context(run, {item.segment for item in entries})
    if question == "collection":
        # Read-time definitions of our derived fields, not hardware counter semantics.
        # Keep these once per question; summary values and bindings stay unchanged.
        context["profile_coverage"]["count_semantics"] = {
            "expected_total": "Sum of caller-declared target.expected_launches counts; null without a declared target.",
            "observed_total": "Sum of parsed launch counts under the segment's counting_authority.",
            "counting_authority": "Applies to observed_total only; expected_total is independent of report parsing.",
        }
    summary = run.summary()
    launch_selection = None
    if scoped:
        entries, launch_selection = select_launches(entries, index, _launch_sampling(context),
            launch_scope, run_dir=root, groups=groups, receipts=summary.collection_receipts,
            segment=segment, artifact=artifact, declared_coverage=summary.profile_coverage)
    facts, inventory = [], []
    timings = {}
    for entry in entries:
        admitted = summary.collection_receipts.allows(entry.segment)
        path = safe_path(root, entry.artifact)
        base = {"artifact": entry.artifact, "group": entry.group, "segment": entry.segment,
                "metric_scope": entry.metric_scope, "admitted": admitted,
                "reference": raw_reference(root, entry.artifact) if path.is_file() else None}
        if not path.is_file():
            inventory.append({**base, "reason": "raw artifact unavailable; regenerate from preserved inputs before using cached observations",
                              "next_step": "Restore preserved raw inputs, then analyze; cached observations are not a substitute."})
            continue
        if not admitted:
            inventory.append({**base, "reason": "excluded by collection receipt; raw audit only",
                              "next_step": "Inspect this segment's collection receipt and logs before deciding whether to retry collection."})
            continue
        if entry.group in OP_FIELDS:
            normalized = normalize_operator(path, entry.artifact, entry.group, entry.segment, entry.metric_scope)
            inventory.append({**base, "parser_status": normalized.status,
                              "numeric_observations": len(normalized.observations),
                              **operator_support_gaps(path, entry.artifact, entry.group),
                              "support_note": "Unregistered columns or metric names retain raw values for audit, not normalized diagnostic meaning."})
            if inventory[-1]['unsupported_columns'] or inventory[-1]['unsupported_metrics']:
                inventory[-1]['next_step'] = ('Consult the field source/definition for missing semantic support; '
                                              'collecting the same layout again does not add parser support.')
            if question is None:
                continue
            if fields:
                selected = select_records(root, entry.artifact, entry.group, fields, summary_only=True)
                definitions = _definitions(entry.group, fields)
                facts.append({**base, "selection": selected, "field_definitions": definitions,
                              "field_availability": _field_availability(selected, definitions),
                              "core_time_distributions": _tails(normalized, fields)})
                continue
            observations = normalized.observations
            shown = observations[offset:None if limit is None else offset + limit]
            details = []
            for item in shown:
                data = _observation(item)
                data["reference"] = {**base["reference"], **item.source.model_dump(mode="json"), "kind": "raw"}
                details.append(data)
            facts.append({**base, "parser_status": normalized.status,
                "launch_name": normalized.launch_name, "row_count": normalized.row_count,
                "issues": [x.model_dump(mode="json") for x in normalized.issues],
                "observations": details, "field_limits": _field_limits(entry.group, [item.metric for item in shown]),
                "observation_count": len(observations), "offset": offset,
                "next_offset": offset + len(shown) if offset + len(shown) < len(observations) else None,

                "distribution_command": shlex.join([
                    "ascend-msprof", *(["joint-row"] if question == "collection" else ["evidence", "--question", question]),
                    "--run-dir", str(root), "--artifact", entry.artifact, "--field", shown[0].metric]) if shown else None,
                "record_command": shlex.join(["ascend-msprof", "joint-row", "--run-dir", str(root),
                    "--artifact", entry.artifact, "--record", str(shown[0].source.record)]) if shown else None,
                "core_time_distributions": _tails(normalized, ["aic_time(us)", "aiv_time(us)"])})
        else:
            from .application_timing import normalize_timing
            normalized = normalize_timing(path, entry.artifact, entry.group, entry.segment, entry.metric_scope)
            timings[entry.artifact] = normalized
            inventory.append({**base, "parser_status": normalized.status,
                              "numeric_observations": len(normalized.observations)})
            if question is not None:
                if fields:
                    raise ValueError("--field selects operator fields; application-timing returns events and timing statistics")
                timing = normalized.model_dump(mode="json")
                observations = timing.pop("observations")
                shown = observations[offset:None if limit is None else offset + limit]
                for observation in shown:
                    observation["reference"] = {**base["reference"], **observation["source"], "kind": "raw"}
                events = _events(path, entry, offset, limit) if entry.group == "op_summary" and limit is not None else None
                if events:
                    for event in events["events"]:
                        event["reference"] = {**base["reference"], "record": event["record"]}
                    for relation in events["relations"]:
                        relation["references"] = [{**base["reference"], **source, "kind": "raw"} for source in relation["sources"]]
                facts.append({**base, "timing": {**timing, "observations": shown},
                              "observation_count": len(observations), "offset": offset,
                              "next_offset": offset + len(shown) if offset + len(shown) < len(observations) else None,
                              "events": events})
    if question in (None, "application-timing"):
        context["question_scope"] = _application_question_scope(summary, inventory, timings)
    available = {item["group"] for item in inventory if item["admitted"] and item.get("numeric_observations", 0)}
    questions = [{**route, "available_families": [g for g in QUESTIONS[route["id"]][1] if g in available],
                  "families_without_numeric_observations": [g for g in QUESTIONS[route["id"]][1] if g not in available]}
                 for route in question_routes(root) if question is None or route["id"] == question]
    if include_next_steps:
        for item in questions:
            item.update(_question_next_steps(run, item, index, inventory, segment, artifact))
    related = [{"artifact": name, "present": (root / name).is_file(), "purpose": purpose,
                "meaning": "Not evaluated by this query. Presence alone is not validity; use the assessment input bindings and eligibility checks."}
               for name, purpose in (
                   ("analysis/candidate_summary.json", "performance_assessment: natural measurement eligibility; mechanism_assessment: independent profiler assessment"),
                   ("analysis/benchmark_context.json", "Registered natural measurement inputs; absence of timing in this query does not imply absence of benchmark evidence"),
                   ("analysis/profile_context.json", "Caller source/verification context"),
                   ("analysis/tilelang_context.json", "Source/JIT and legacy caller context; null legacy timing does not override registered benchmark evidence"))]
    for entry in viewer_entries:
        path = safe_path(root, entry.artifact)
        related.append({'artifact': entry.artifact, 'present': path.is_file(),
            'segment': entry.segment, 'metric_scope': entry.metric_scope,
            'reference': raw_reference(root, entry.artifact) if path.is_file() else None,
            'purpose': 'Existing visualization input; inspect with the official viewer when this question needs Source/Cache information',
            'meaning': ('Contents, target binding and viewer compatibility remain unverified. '
                'Preserve this input and inspect its collection receipt/mode before opening it; '
                'record viewer version, input hash and observed mapping. An unavailable viewer is a viewing gap, '
                'not a reason to repeat collection. See reference/15-cann852-capabilities.md. '
                'Presence does not supply missing numeric families or invalidate independent CSV facts.')})
    aggregation = (aggregate_operator_launches(root, entries, summary.collection_receipts, launch_selection,
                   fields=fields, offset=offset, limit=limit) if aggregate_launches else None)
    diagnostics = collection_diagnostics(root) if question == 'collection' else None
    current = snapshot(root, bound_artifacts, selection=selection)
    if current != binding:
        raise ValueError("inputs changed during query; retry on a stable run")
    result = {"question_evidence_version": CONTRACT_VERSION, "run_dir": str(root),
            "question": question, "selection": {"segment": segment, "artifact": artifact, "fields": fields or [],
                **({"launch_scope": launch_scope, "aggregate_launches": aggregate_launches} if scoped else {})},
            "binding": binding, "context": context, "related_evidence": related, "questions": questions, "inventory": inventory, "facts": facts,
            "inventory_gaps": [name for name in binding["members"] if name.startswith("reports/")
                               and name not in {item.artifact for item in index}],
            "range": {"offset": offset, "limit_per_artifact": limit,
                      "note": "Follow each next_offset with the same question and exact artifact. Field summaries cover all matching rows."}}
    if launch_selection is not None:
        result["launch_selection"] = launch_selection
    if aggregation is not None:
        result["launch_aggregation"] = aggregation
    if diagnostics is not None:
        result['collection_diagnostics'] = diagnostics
    return result


def _question_next_steps(run, question, index, inventory, segment, artifact) -> dict:
    """Route observed gaps to existing operations, without authorizing collection."""
    gaps, absent = [], set()
    analyze = shlex.join(["ascend-msprof", "analyze", "--run-dir", str(run.run_dir)])
    indexed = {item.artifact for item in index}
    for group in question['families_without_numeric_observations']:
        entries = [item for item in inventory if item['group'] == group]
        unindexed = [str(path.relative_to(run.run_dir)) for path in recognized_group_files(run.run_dir, group)
                     if str(path.relative_to(run.run_dir)) not in indexed
                     and (segment is None or segment_for_relpath(str(path.relative_to(run.run_dir)), group) == segment)
                     and (artifact is None or str(path.relative_to(run.run_dir)) == artifact)]
        gap = {'family': group, 'artifacts': [item['artifact'] for item in entries]}
        if unindexed:
            gap.update(reason='Recognized raw files are outside the analysis index; availability is not yet assessed.',
                       artifacts=unindexed, next_step='Analyze preserved inputs before considering collection.', command=analyze)
        elif entries:
            # Each artifact already carries receipt admission, support gaps and parser state.
            gap.update(reason='Indexed artifacts have no admitted numeric observations in this selection.',
                       next_step='Inspect the listed artifact reasons, receipt admission, support gaps and parsing issues first.')
        elif any(item.group == group for item in index):
            gap.update(reason='This family exists outside the selected artifact/segment.',
                       next_step='Broaden the selection if this question needs that evidence.', command=question['command'])
        else:
            absent.add(group)
            gap.update(reason='No indexed or recognized raw artifact for this family in the selected scope.',
                       next_step='Collect only if the current claim needs this family; consult the recorded actions and collection guide.')
            if question['id'] != 'application-timing' and any(
                    item.group == 'unparsed_profiler_binary' and item.artifact
                    and Path(item.artifact).name == 'visualize_data.bin'
                    and (segment is None or item.segment == segment)
                    and (artifact is None or item.artifact == artifact)
                    and safe_path(run.run_dir, item.artifact).is_file() for item in index):
                gap['next_step'] = ('Inspect the existing viewer input listed under related evidence and its receipt first. '
                    'Its fields and target are unverified; select supported collection only if the question still needs '
                    'unavailable evidence. Repeating the same command does not establish CSV export or parser support.')
        gaps.append(gap)
    actions = [{**action.model_dump(mode='json'), 'source': f'analysis/summary.json#/next_collection_actions/{number}'}
               for number, action in enumerate(run.next_collection_actions())
               if set(missing_artifact_labels(tuple(absent))).intersection(action.required_artifacts)]
    return {'gaps': gaps, 'conditional_collection_actions': actions,
            'action_note': ('Existing run-level actions filtered by absent families; not an execution queue. '
                'Their recorded necessity applies to the run-level gate, not automatically to this question. '
                'Check preserved inputs and the current claim before selecting an action; read reference/03-collection.md.')}


def _observation(value) -> dict:
    data = value.model_dump(mode="json")
    return {key: data[key] for key in ("metric", "value", "unit", "statistic", "name", "scope", "source", "raw_token") if key in data}


def _tails(normalized, fields: list[str]) -> list[dict]:
    selected = {name.lower() for name in fields}
    return [{"metric": x.metric, "scope": list(x.scope), "valid_count": x.valid_count,
             "median_us": x.median_us, "maximum": _observation(x.maximum),
             "second_largest": _observation(x.second_largest) if x.second_largest else None}
            for x in normalized.core_time_distributions if x.metric.lower() in selected]


def _definitions(group: str, fields: list[str]) -> list[dict]:
    from .operator_evidence import field_definition
    return [field_definition(group, name) for name in fields]


def _field_availability(selection: dict, definitions: list[dict]) -> list[dict]:
    """Explain existing cell counts, without inferring a missing value's cause.

    Receipt admission has already been checked. These notes neither admit new
    facts nor create executable collection actions; the selected population and
    shared field definition remain the sources of counts and prerequisites.
    """
    notes = []
    for number, group in enumerate(selection['groups']):
        for field, counts in group['fields'].items():
            definition = next(item for item in definitions if item['name'].lower() == field.lower())
            prerequisite = definition.get('collection_prerequisite')
            if not definition['recognized']:
                reason = 'Field definition is unknown; retain raw values and positions.'
                step = 'Verify this producer/version and field definition; repeating collection does not add parser support.'
            elif counts['valid']:
                reason = 'Numeric evidence is available in this scope; reuse the valid cells.'
                step = 'Use the recorded population and raw references. Missing or invalid sibling cells remain excluded; this does not establish complete launch coverage.'
            elif counts['invalid']:
                reason = 'No valid numeric cells; invalid tokens or parsing issues require inspection.'
                step = 'Inspect the selected raw records and issues before considering collection.'
            elif prerequisite and str(group['scope'].get('sub_block_id', '')).lower().startswith('vector'):
                reason = 'This AIV row does not supply the requested AIC field; missing is not zero.'
                step = 'Inspect matching AIC rows if the target has an AIC component; this AIV row does not justify extra collection.'
            else:
                reason = 'No numeric evidence in this scope; missing columns and NA are not zero and do not identify a cause.'
                step = 'Inspect raw records, core applicability, recorded scope and collection receipts; the cause remains unresolved.'
                if prerequisite:
                    modes = {mode.strip().lower() for mode in (selection.get('metric_scope') or '').split(',')}
                    if prerequisite['metric_mode'].lower() in modes:
                        step += ' MemoryDetail is recorded as requested; inspect instrumentation results before proposing a retry.'
                    else:
                        step += (' If this question requires an AIC numeric value and matching evidence is absent, '
                                 'check the capability reference for a targeted MemoryDetail collection; '
                                 'scope alone does not prove instrumentation failed or was not requested.')
            notes.append({'field': field, 'scope': group['scope'],
                          'counts_source': {'group_index': number, 'field': field},
                          'reason': reason, 'next_step': step})
    return notes


def _field_limits(group: str, fields: list[str]) -> list[dict]:
    """Group identical interpretation limits for the displayed fields only."""
    limits = []
    for definition in _definitions(group, list(dict.fromkeys(fields))):
        keys = ("meaning", "population", "denominator", "aggregation", "comparison") if group == "pipe_utilization" else ("population", "denominator", "aggregation")
        constraints = {key: definition[key] for key in keys
                       if key in definition}
        if not constraints:
            continue
        existing = next((item for item in limits if item["constraints"] == constraints), None)
        if existing is None:
            limits.append({"fields": [definition["name"]], "constraints": constraints})
        else:
            existing["fields"].append(definition["name"])
    return limits


def _events(path, entry, offset, limit):
    from .application_events import read_application_events
    return read_application_events(path, entry.artifact, offset=offset, limit=limit)


def render_question(result: dict) -> str:
    """Readable projection; full bindings and optional row details remain addressable."""
    if 'question_evidence_version' not in result:
        return '# Reference Verification\n\n```json\n' + json.dumps(result, ensure_ascii=False, indent=2) + '\n```\n'
    def code(value):
        return '`' + str(value).replace('`', "'").replace('\n', ' ') + '`'
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    context = result['context']
    diagnostic_lines = []
    if result.get('collection_diagnostics'):
        diagnostics = result['collection_diagnostics']
        diagnostic_lines = ['## Collection Diagnostics', '', diagnostics['policy_source'], diagnostics['scope_note'], '']
        for issue in diagnostics['issues']:
            diagnostic_lines.extend([f"- {code(issue['code'])}: {code(issue['source']['artifact'])}:{issue['source']['record']} "
                         f"sha256={code(issue['source_sha256'])}. {issue['message']}",
                         f"  Recovery ({issue['recovery']['route']}): {issue['recovery']['next_step']}"])
    if context.get('analysis_status') == 'unavailable':
        return '\n'.join(['# Question Evidence', '', f"Run: {code(result['run_dir'])}",
            f"Input snapshot: {code(result['binding']['sha256'])}", '', *diagnostic_lines, '',
            *context['limitations'], ''])
    identity = context['target_identity']
    lines = ['# Question Evidence', '', f"Run: {code(result['run_dir'])}",
        f"Question: {code(result['question'] or 'directory')}; selection: {code(json.dumps(result['selection']))}",
        f"Input snapshot: {code(result['binding']['sha256'])}. Content binding is not diagnosis eligibility.", '',
        '## Run Limits', '', f"Run-level target identity: {code(identity['status'])}; confidence: {code(identity['confidence'])}.",
        f"Expected: {code(json.dumps(identity['expected'], ensure_ascii=False))}",
        f"Observed: {code(json.dumps(identity['observed'], ensure_ascii=False))}"]
    scope_lines = []
    for scope in context.get('question_scope', []):
        scope_lines.extend(['## Application Question Scope', '',
            f"Segment={code(scope['segment'])}; name identity={code(scope['target_identity']['status'] if scope['target_identity'] else 'unverified')}; "
            f"declared_launches_present={scope['declared_launches_present']}; count_complete={scope['count_complete']}.",
            scope['coverage_scope'] + f"; extras={code(scope['extra_counts'])}.", ''])
        for item in scope['artifacts']:
            scope_lines.append(f"- {code(item['artifact'])}: " + '; '.join(item['allowed_claims'] or ['raw audit only'])
                + f"; target names={code(item['target_names'])}. " + item['limitation'])
        scope_lines.extend(['- Blocked in this question scope: ' + '; '.join(scope['blocked_claims']),
                            *('- ' + value for value in scope['limitations']), ''])
    lines[6:6] = scope_lines
    lines[6:6] = diagnostic_lines + [''] if diagnostic_lines else []
    for field, meaning in context['profile_coverage'].get('count_semantics', {}).items():
        lines.append(f"- Coverage {code(field)}: {meaning}")
    for segment, coverage in context['profile_coverage']['segments'].items():
        lines.extend([f"- Segment {code(segment)}: count_complete={coverage['count_complete']}; "
                      f"observed={coverage['observed_total']}, expected={coverage['expected_total']}.",
            f"  Target scope: {code(json.dumps(coverage['target_scope'], ensure_ascii=False))}",
            f"  Missing/over/extra: {code(json.dumps({key: coverage[key] for key in ('missing_counts', 'over_counts', 'extra_counts')}))}",
            f"  Metric coverage: {code(json.dumps({key: value['complete'] for key, value in coverage['metric_coverage'].items()}))}",
            f"  Segment target identity: {code(json.dumps(coverage['target_identity'], ensure_ascii=False))}",
            f"  Ambiguities: {code(json.dumps(coverage['ambiguities'], ensure_ascii=False))}"])
    sampling = context['analysis_context'].get('sampling')
    lines.extend(['', *sampling_context_lines(SamplingContext.model_validate(sampling) if sampling else None)])
    lines.extend(caller_context_lines(context.get('caller_evidence')))
    if context.get('source_snapshots'):
        lines.extend(caller_context_lines(context['source_snapshots'], heading='Run-Local Code Snapshots'))
    for issue in context['analysis_context']['issues']:
        lines.append('Context issue: ' + code(json.dumps(issue, ensure_ascii=False)))
    if 'launch_selection' in result:
        selected = result['launch_selection']
        lines.extend(['', '## Selected Launch Scope', '',
            f"Caller-declared scope={code(selected['scope'])}; expected numeric launch indices={code(selected['expected_launch_indices'])}.",
            f"Included artifacts={len(selected['included_artifacts'])}; excluded artifacts={len(selected['excluded_artifacts'])}."])
        for coverage in selected['coverage']:
            lines.append('Launch coverage: ' + code(json.dumps(coverage, ensure_ascii=False)))
        lines.extend('- ' + text for text in selected['limitations'])
    if 'launch_aggregation' in result:
        aggregate = result['launch_aggregation']
        lines.extend(['', '## Across-Launch Operator Groups', '', aggregate['range_note'],
            f"Group page offset={aggregate['offset']}; total={aggregate['group_count']}; next_offset={aggregate['next_offset']}.", '',
            '| Family / field | Target / kernel | Scope | Unit / statistic | Count | Min / median / max | Complete / missing launches |',
            '|---|---|---|---|---:|---|---|'])
        for group in aggregate['groups']:
            lines.append('| ' + ' | '.join(cell(value) for value in (
                group['canonical_stem'] + ' / ' + group['metric'],
                str(group['target_name']) + ' / ' + group['kernel_directory'], group['scope'],
                group['unit'] + ' / ' + group['statistic'], group['count'],
                [group['minimum'], group['median'], group['maximum']],
                str(group['complete']) + ' / ' + str(group['missing_launch_indices']))) + ' |')
        lines.append('The JSON retains each raw cell value, launch index, source record/column, content reference and excluded-cell reason.')
        for issue in aggregate['issues']:
            lines.append('Aggregation issue: ' + code(json.dumps(issue, ensure_ascii=False)))
    lines.extend(['', 'Minimum readiness: ' + code(context['readiness']['level']) + '. ' + context['readiness']['meaning']])
    for key in ('allowed_claims', 'blocked_claims'):
        lines.append(f"- {key}: " + '; '.join(context['readiness'][key]))
    lines.extend(['- ' + text for text in context['limitations']])
    lines.extend(['- Load warning: ' + text for text in context['load_warnings']])
    lines.extend(['', 'Measurement quality: ' + code(json.dumps(context['measurement_quality'], ensure_ascii=False)),
                  '', '## Questions And Related Evidence', ''])
    for question in result['questions']:
        lines.extend([f"- {question['question']} Numeric families: {code(question['available_families'])}; "
                      f"without numeric observations: {code(question['families_without_numeric_observations'])}.",
                      '  ' + code(question['command'])])
        for gap in question.get('gaps', []):
            lines.append(f"  - {code(gap['family'])}: {gap['reason']} {gap['next_step']}"
                         + (' ' + code(gap['command']) if gap.get('command') else ''))
        for action in question.get('conditional_collection_actions', []):
            lines.append(f"  - Conditional action {code(action['id'])} [{action['necessity']}]: {action['reason']} "
                         + code(action['source']))
        if question.get('conditional_collection_actions'):
            lines.append('  ' + question['action_note'])
    for item in result['related_evidence']:
        lines.append(f"- {code(item['artifact'])}: {item['purpose']}; presence={item['present']}. {item['meaning']}")
        if item.get('reference'):
            lines.append(f"  Segment={code(item['segment'])}; metric scope={code(item['metric_scope'])}; "
                         f"raw SHA-256={code(item['reference']['sha256'])}.")
    lines.extend(['', '## Selected Evidence', ''])
    facts = {item['artifact']: item for item in result['facts']}
    for item in result['inventory']:
        lines.extend([f"### {item['group']}: {item['artifact']}", '',
            f"Segment={code(item['segment'])}; metric scope={code(item['metric_scope'])}; admitted={item['admitted']}."])
        if item['reference']:
            lines.append('Raw SHA-256: ' + code(item['reference']['sha256']))
        if item.get('reason'):
            lines.append(item['reason'])
        if item.get('next_step'):
            lines.append('Next step: ' + item['next_step'])
        if item.get('unsupported_columns'):
            lines.append('Unregistered raw columns (audit only): ' + ', '.join(code(x) for x in item['unsupported_columns']))
        if item.get('unsupported_metrics'):
            lines.append('Unregistered metric names (audit only): ' + ', '.join(code(x) for x in item['unsupported_metrics']))
        fact = facts.get(item['artifact'])
        if not fact:
            continue
        if 'selection' in fact:
            lines.extend(['', 'Full matching field populations (separate scopes):', '', '```json',
                json.dumps({'selection': fact['selection'], 'definitions': fact['field_definitions'],
                            'core_time_distributions': fact['core_time_distributions']}, ensure_ascii=False, indent=2), '```'])
            for note in fact.get('field_availability', []):
                lines.append(f"- {code(note['field'])}; scope={code(note['scope'])}: {note['reason']} {note['next_step']}")
            continue
        observations = fact.get('observations', fact.get('timing', {}).get('observations', []))
        if fact.get("timing"):
            lines.append("Timing observations are representative statistics, not a full API breakdown; verify the bound raw artifact for all rows.")
        timing = bool(fact.get('timing'))
        lines.extend(['', f"Observation page: offset={fact['offset']}, total={fact['observation_count']}, next_offset={fact['next_offset']}.",
            '', ('| Name ' if timing else '') + '| Field | Value | Unit / statistic | Scope | CSV record / column |',
            ('|---' if timing else '') + '|---|---:|---|---|---|'])
        for value in observations:
            source = value['source']
            columns = ([value.get('name') or '(unnamed)'] if timing else []) + [
                (source.get('field') or value['metric']) if timing else value['metric'], value['value'],
                value['unit'] + ' / ' + value['statistic'], value['scope'],
                f"{source.get('record')} / {source.get('column')}"]
            lines.append('| ' + ' | '.join(cell(x) for x in columns) + ' |')
        for restriction in fact.get('field_limits', []):
            lines.extend(['', 'Limits for ' + ', '.join(code(name) for name in restriction['fields'])
                          + ': ' + ' '.join(restriction['constraints'].values())])
        for issue in fact.get('issues', fact.get('timing', {}).get('issues', [])):
            lines.append('Issue: ' + code(json.dumps(issue, ensure_ascii=False)))
        for population in fact.get('core_time_distributions', []):
            tails = {key: {'value': population[key]['value'], 'source': population[key]['source']}
                     for key in ('maximum', 'second_largest') if population.get(key)}
            lines.append('Core-time distribution: ' + code(json.dumps({**population, **tails}, ensure_ascii=False)))
        if fact.get('distribution_command'):
            lines.extend(['', 'Full field counts/distributions (replace or repeat --field):', code(fact['distribution_command'])])
        if fact.get('record_command'):
            lines.extend(['', 'Same-record peers (replace --record):', code(fact['record_command'])])
        events = fact.get('events')
        if events:
            lines.extend(['', f"Events: offset={events['offset']}, total={events['event_count']}, next_offset={events['next_offset']}.",
                          events['clock_domain']])
            for event in events['events']:
                lines.append(f"- Record {event['record']} {code(event['name'])}; scope={code(event['scope'])}; "
                    + '; '.join(f"{field}={value['raw']}" for field, value in event['times'].items()))
            for relation in events['relations']:
                lines.append(f"- Records {relation['left_record']} → {relation['right_record']}: "
                    f"{relation['signed_end_to_start_us']} us ({relation['kind']}); {relation['formula']}; {relation['adjacency']}.")
            lines.extend('- ' + text for text in events['limitations'])
            lines.extend('Event issue: ' + code(json.dumps(issue, ensure_ascii=False)) for issue in events['issues'])
        lines.append('')
    gaps = result['inventory_gaps']
    lines.extend(['## Further Reading And Verification', '',
        f"{len(gaps)} report files are outside the index; these may be binary/metadata files, not missing diagnostic CSVs.",
        'Use `--format json` to save the complete result, including the input manifest, references and inventory paths.',
        'Save a raw `reference` or the full JSON result and use `--verify <file.json>` to check its binding.',
        ('For collection, follow next_offset using --offset and --limit without --artifact; pagination applies to each artifact. '
         'Use the joint-row commands above for a particular artifact, field or record.'
         if result.get('question') == 'collection' else
         'Follow per-artifact next_offset with the same question and exact --artifact. Event and observation pages have separate totals.'),
        ('Full raw data remains available.' if result.get('question') == 'collection' else
         'Default tails show AIC/AIV core time; select another exact --field for its duration tail or population. For exact operator peers use the record command. Full raw data remains available.'), ''])
    return '\n'.join(lines)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--question", choices=tuple(QUESTIONS))
    parser.add_argument("--segment")
    parser.add_argument("--artifact")
    parser.add_argument("--field", action="append", dest="fields")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--launch-scope", choices=("all", "scored"), default="all",
                        help="Opt-in caller-declared scored numeric launch range; all preserves the original raw view")
    parser.add_argument("--aggregate-launches", action="store_true",
                        help="Describe like-for-like raw cells across selected launches; offset/limit also page complete aggregation groups")
    parser.add_argument("--verify", type=Path, help="Saved raw reference, input snapshot, or question result JSON")
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            reference = json.loads(args.verify.read_text())
            result = verify_reference(args.run_dir, reference.get("binding", reference), offset=args.offset, limit=args.limit)
        else:
            result = read_question_from_dir(args.run_dir, args.question, segment=args.segment,
                artifact=args.artifact, fields=args.fields, offset=args.offset, limit=args.limit,
                launch_scope=args.launch_scope, aggregate_launches=args.aggregate_launches)
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "unavailable", "error": str(exc)}))
        return 1
    print(render_question(result) if args.format == "markdown" else json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status", "verified") == "verified" else 1
