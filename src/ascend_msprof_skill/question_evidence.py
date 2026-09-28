"""Question-sized views over RunEvidence and the existing operator readers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex

from .artifact_reader import read_csv
from .evidence_binding import CONTRACT_VERSION, raw_reference, snapshot, verify_reference, safe_path
from .joint_row import select_records
from .operator_evidence import OP_FIELDS, META_FIELDS, SCOPE_FIELDS, normalize_operator
from .run_evidence import RunEvidence

# Reading questions are independent of paired-mechanism assessment questions.
QUESTIONS = {
    "pipe": ("Which pipe activities were recorded?", ("pipe_utilization",)),
    "arithmetic": ("Which arithmetic activities were recorded?", ("arithmetic_utilization",)),
    "memory": ("Which memory movements and cache fields were recorded?", ("memory", "l2_cache")),
    "application-timing": ("Which application tasks and intervals were recorded?", ("op_summary", "task_time", "api_statistic", "op_statistic")),
}


def question_routes(run_dir: Path) -> list[dict]:
    return [{"id": key, "question": title, "command": shlex.join([
        "ascend-msprof", "evidence", "--run-dir", str(run_dir), "--question", key])}
        for key, (title, _) in QUESTIONS.items()]


def _context(run: RunEvidence, segments: set[str]) -> dict:
    summary = run.summary()
    return {
        "target_identity": summary.target_identity.model_dump(mode="json"),
        "profile_coverage": {"explicit_target": summary.profile_coverage.explicit_target,
            "segments": {key: value.model_dump(mode="json") for key, value in summary.profile_coverage.segments.items()
                         if key in segments}},
        "measurement_quality": summary.measurement_quality.model_dump(mode="json"),
        "readiness": {"meaning": "Minimum profiling readiness, not completeness for this question.",
            "level": summary.evidence_readiness.level,
            "minimum_gate_missing": list(summary.evidence_readiness.missing_evidence_families),
            "allowed_claims": list(summary.evidence_readiness.allowed_claims),
            "blocked_claims": list(summary.evidence_readiness.blocked_claims)},
        "analysis_context": summary.analysis_context.model_dump(mode="json"),
        "limitations": [
            "Use the recorded identity and coverage gates before attributing observations to the requested target.",
            "Name identity does not establish source/benchmark association. Natural performance uses the separate performance assessment.",
            "Independent maxima can come from different records. Recorded activity does not by itself prove a bottleneck.",
            "Each collection segment has its own measurement boundary; no cross-segment simultaneous sampling is implied."],
        "load_warnings": run.warnings(),
    }


def read_question(run: RunEvidence, question: str | None = None, *, segment: str | None = None,
                  artifact: str | None = None, fields: list[str] | None = None,
                  offset: int = 0, limit: int = 20) -> dict:
    """Reuse validated run decisions; selected CSV values are normalized from bound raw inputs."""
    if question is not None and question not in QUESTIONS:
        raise ValueError(f"unknown question: {question}; choose from {', '.join(QUESTIONS)}")
    if offset < 0 or limit < 1:
        raise ValueError("offset must be nonnegative and limit positive")
    if fields and (question is None or artifact is None):
        raise ValueError("field selection requires a question and an exact artifact")
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
    root = run.run_dir.resolve()
    selection = {"question": question, "segment": segment, "artifact": artifact,
                 "fields": fields or [], "offset": offset, "limit": limit}
    binding = snapshot(root, [item.artifact for item in entries], selection=selection)
    context = _context(run, {item.segment for item in entries})
    summary = run.summary()
    facts, inventory = [], []
    for entry in entries:
        admitted = summary.collection_receipts.allows(entry.segment)
        path = safe_path(root, entry.artifact)
        base = {"artifact": entry.artifact, "group": entry.group, "segment": entry.segment,
                "metric_scope": entry.metric_scope, "admitted": admitted,
                "reference": raw_reference(root, entry.artifact) if path.is_file() else None}
        if not path.is_file():
            inventory.append({**base, "reason": "raw artifact unavailable; regenerate from preserved inputs before using cached observations"})
            continue
        if not admitted:
            inventory.append({**base, "reason": "excluded by collection receipt; raw audit only"})
            continue
        if entry.group in OP_FIELDS:
            normalized = normalize_operator(path, entry.artifact, entry.group, entry.segment, entry.metric_scope)
            decoded = read_csv(path, entry.artifact, lambda *_: None)
            known = {name.lower() for name in OP_FIELDS[entry.group]}
            metadata = {name.lower() for name in (*META_FIELDS, *SCOPE_FIELDS)}
            unsupported = [name for name in decoded.columns if name.lower() not in known | metadata]
            inventory.append({**base, "parser_status": normalized.status,
                              "numeric_observations": len(normalized.observations),
                              "unsupported_columns": unsupported,
                              "support_note": "Unregistered columns retain raw values for audit, not normalized diagnostic meaning."})
            if question is None:
                continue
            if fields:
                facts.append({**base, "selection": select_records(root, entry.artifact, entry.group,
                              fields, summary_only=True), "field_definitions": _definitions(entry.group, fields),
                              "core_time_distributions": _tails(normalized, fields)})
                continue
            observations = normalized.observations
            shown = observations[offset:offset + limit]
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

                "distribution_command": shlex.join(["ascend-msprof", "evidence", "--run-dir", str(root),
                    "--question", question, "--artifact", entry.artifact, "--field", shown[0].metric]) if shown else None,
                "record_command": shlex.join(["ascend-msprof", "joint-row", "--run-dir", str(root),
                    "--artifact", entry.artifact, "--record", str(shown[0].source.record)]) if shown else None,
                "core_time_distributions": _tails(normalized, ["aic_time(us)", "aiv_time(us)"])})
        else:
            from .application_timing import normalize_timing
            normalized = normalize_timing(path, entry.artifact, entry.group, entry.segment, entry.metric_scope)
            inventory.append({**base, "parser_status": normalized.status,
                              "numeric_observations": len(normalized.observations)})
            if question is not None:
                if fields:
                    raise ValueError("--field selects operator fields; application-timing returns events and timing statistics")
                timing = normalized.model_dump(mode="json")
                observations = timing.pop("observations")
                shown = observations[offset:offset + limit]
                for observation in shown:
                    observation["reference"] = {**base["reference"], **observation["source"], "kind": "raw"}
                events = _events(path, entry, offset, limit) if entry.group == "op_summary" else None
                if events:
                    for event in events["events"]:
                        event["reference"] = {**base["reference"], "record": event["record"]}
                    for relation in events["relations"]:
                        relation["references"] = [{**base["reference"], **source, "kind": "raw"} for source in relation["sources"]]
                facts.append({**base, "timing": {**timing, "observations": shown},
                              "observation_count": len(observations), "offset": offset,
                              "next_offset": offset + len(shown) if offset + len(shown) < len(observations) else None,
                              "events": events})
    available = {item["group"] for item in inventory if item["admitted"] and item.get("numeric_observations", 0)}
    questions = [{**route, "available_families": [g for g in QUESTIONS[route["id"]][1] if g in available],
                  "families_without_numeric_observations": [g for g in QUESTIONS[route["id"]][1] if g not in available]}
                 for route in question_routes(root) if question is None or route["id"] == question]
    related = [{"artifact": name, "present": (root / name).is_file(), "purpose": purpose,
                "meaning": "Not evaluated by this query. Presence alone is not validity; use the assessment input bindings and eligibility checks."}
               for name, purpose in (
                   ("analysis/candidate_summary.json", "performance_assessment: natural measurement eligibility; mechanism_assessment: independent profiler assessment"),
                   ("analysis/benchmark_context.json", "Registered natural measurement inputs; absence of timing in this query does not imply absence of benchmark evidence"),
                   ("analysis/profile_context.json", "Caller source/verification context"),
                   ("analysis/tilelang_context.json", "Source/JIT and legacy caller context; null legacy timing does not override registered benchmark evidence"))]
    current = snapshot(root, [item.artifact for item in entries], selection=selection)
    if current != binding:
        raise ValueError("inputs changed during query; retry on a stable run")
    return {"question_evidence_version": CONTRACT_VERSION, "run_dir": str(root),
            "question": question, "selection": {"segment": segment, "artifact": artifact, "fields": fields or []},
            "binding": binding, "context": context, "related_evidence": related, "questions": questions, "inventory": inventory, "facts": facts,
            "inventory_gaps": [name for name in binding["members"] if name.startswith("reports/")
                               and name not in {item.artifact for item in index}],
            "range": {"offset": offset, "limit_per_artifact": limit,
                      "note": "Follow each next_offset with the same question and exact artifact. Field summaries cover all matching rows."}}


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


def _field_limits(group: str, fields: list[str]) -> list[dict]:
    """Group identical interpretation limits for the displayed fields only."""
    limits = []
    for definition in _definitions(group, list(dict.fromkeys(fields))):
        constraints = {key: definition[key] for key in ("population", "denominator", "aggregation")
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
    identity = context['target_identity']
    lines = ['# Question Evidence', '', f"Run: {code(result['run_dir'])}",
        f"Question: {code(result['question'] or 'directory')}; selection: {code(json.dumps(result['selection']))}",
        f"Input snapshot: {code(result['binding']['sha256'])}. Content binding is not diagnosis eligibility.", '',
        '## Run Limits', '', f"Target identity: {code(identity['status'])}; confidence: {code(identity['confidence'])}.",
        f"Expected: {code(json.dumps(identity['expected'], ensure_ascii=False))}",
        f"Observed: {code(json.dumps(identity['observed'], ensure_ascii=False))}"]
    for segment, coverage in context['profile_coverage']['segments'].items():
        lines.extend([f"- Segment {code(segment)}: count_complete={coverage['count_complete']}; "
                      f"observed={coverage['observed_total']}, expected={coverage['expected_total']}.",
            f"  Target scope: {code(json.dumps(coverage['target_scope'], ensure_ascii=False))}",
            f"  Missing/over/extra: {code(json.dumps({key: coverage[key] for key in ('missing_counts', 'over_counts', 'extra_counts')}))}",
            f"  Metric coverage: {code(json.dumps({key: value['complete'] for key, value in coverage['metric_coverage'].items()}))}",
            f"  Segment target identity: {code(json.dumps(coverage['target_identity'], ensure_ascii=False))}",
            f"  Ambiguities: {code(json.dumps(coverage['ambiguities'], ensure_ascii=False))}"])
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
    for item in result['related_evidence']:
        lines.append(f"- {code(item['artifact'])}: {item['purpose']}; presence={item['present']}. {item['meaning']}")
    lines.extend(['', '## Selected Evidence', ''])
    facts = {item['artifact']: item for item in result['facts']}
    for item in result['inventory']:
        lines.extend([f"### {item['group']}: {item['artifact']}", '',
            f"Segment={code(item['segment'])}; metric scope={code(item['metric_scope'])}; admitted={item['admitted']}."])
        if item['reference']:
            lines.append('Raw SHA-256: ' + code(item['reference']['sha256']))
        if item.get('reason'):
            lines.append(item['reason'])
        if item.get('unsupported_columns'):
            lines.append('Unregistered raw columns (audit only): ' + ', '.join(code(x) for x in item['unsupported_columns']))
        fact = facts.get(item['artifact'])
        if not fact:
            continue
        if 'selection' in fact:
            lines.extend(['', 'Full matching field populations (separate scopes):', '', '```json',
                json.dumps({'selection': fact['selection'], 'definitions': fact['field_definitions'],
                            'core_time_distributions': fact['core_time_distributions']}, ensure_ascii=False, indent=2), '```'])
            continue
        observations = fact.get('observations', fact.get('timing', {}).get('observations', []))
        if fact.get("timing"):
            lines.append("Timing observations are representative statistics, not a full API breakdown; verify the bound raw artifact for all rows.")
        lines.extend(['', f"Observation page: offset={fact['offset']}, total={fact['observation_count']}, next_offset={fact['next_offset']}.",
            '', '| Field | Value | Unit / statistic | Scope | CSV record / column |', '|---|---:|---|---|---|'])
        for value in observations:
            source = value['source']
            lines.append('| ' + ' | '.join(cell(x) for x in (source.get('field') or value['metric'], value['value'],
                value['unit'] + ' / ' + value['statistic'], value['scope'],
                f"{source.get('record')} / {source.get('column')}")) + ' |')
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
        'Follow per-artifact next_offset with the same question and exact --artifact. Event and observation pages have separate totals.',
        'Default tails show AIC/AIV core time; select another exact --field for its duration tail or population. For exact operator peers use the record command. Full raw data remains available.', ''])
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
    parser.add_argument("--verify", type=Path, help="Saved raw reference, input snapshot, or question result JSON")
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            reference = json.loads(args.verify.read_text())
            result = verify_reference(args.run_dir, reference.get("binding", reference), offset=args.offset, limit=args.limit)
        else:
            result = RunEvidence.load(args.run_dir).question_evidence(args.question, segment=args.segment,
                artifact=args.artifact, fields=args.fields, offset=args.offset, limit=args.limit)
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "unavailable", "error": str(exc)}))
        return 1
    print(render_question(result) if args.format == "markdown" else json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status", "verified") == "verified" else 1
