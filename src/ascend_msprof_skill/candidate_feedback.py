"""Render validated assessment facts without parsing or recomputing evidence."""
from __future__ import annotations

from collections import Counter

from .assessment_types import EvidenceCitation, EvidenceQuestion, RunAssessment
from .benchmark_types import BenchmarkCitation


def md_escape(value: object) -> str:
    return 'n/a' if value is None else str(value).replace('|', '\\|')


def evidence_label(item: EvidenceCitation | BenchmarkCitation) -> str:
    source = item.source if isinstance(item, EvidenceCitation) else None
    field_ref = item.field_ref or (item.field if isinstance(item, EvidenceCitation) else None)
    prefix = ': '.join(part for part in (source, item.role) if part)
    body = item.artifact or 'n/a'
    if field_ref:
        body += f' ({field_ref})'
    return f'{prefix}: {body}' if prefix else body


def markdown_evidence_sample(items: tuple[EvidenceCitation, ...], limit_per_source: int = 5) -> list[EvidenceCitation]:
    selected = []
    counts: Counter[str] = Counter()
    for item in items:
        source = item.source or 'unknown'
        if counts[source] < limit_per_source:
            selected.append(item)
            counts[source] += 1
    return selected


def render_evidence_questions_markdown(status: str, questions: tuple[EvidenceQuestion, ...]) -> list[str]:
    lines = ['## Evidence Questions', '', f'Status: `{status}`', '']
    if not questions:
        return [*lines, 'No evidence questions recorded.']
    lines.extend(['| Question ID | Family | Question | Available Evidence | Missing Evidence | Blockers |',
                  '|---|---|---|---:|---:|---|'])
    for question in questions:
        lines.append(f'| `{md_escape(question.id)}` | `{md_escape(question.evidence_family)}` | '
                     f'{md_escape(question.question)} | {len(question.available_evidence)} | {len(question.missing_evidence)} | '
                     f'{md_escape(", ".join(question.blocked_by) if question.blocked_by else "none")} |')
    for question in questions:
        lines.extend(['', f'### {md_escape(question.id)}', '', f'- Question: {md_escape(question.question)}'])
        for title, evidence in (('Available', question.available_evidence), ('Missing', question.missing_evidence)):
            if evidence:
                lines.append(f'- {title} evidence:')
                lines.extend(f'  - `{md_escape(evidence_label(item))}`' for item in markdown_evidence_sample(evidence))
        if question.blocked_by:
            lines.extend(['- Blocked by:', *(f'  - {md_escape(blocker)}' for blocker in question.blocked_by)])
    return lines


def render_assessment_markdown(result: RunAssessment) -> list[str]:
    performance, mechanism = result.performance_assessment, result.mechanism_assessment
    lines = ['## Performance Assessment', '',
             f'Eligibility: `{performance.eligibility.status}`; comparison: `{performance.comparison.status}`.', '',
             '| Measurement | Value ms | Statistic | Samples | Source |', '|---|---:|---|---:|---|']
    for role, evidence in (('baseline', performance.measurements.baseline), ('candidate', performance.measurements.candidate)):
        if evidence is None:
            continue
        measurement = evidence.record.measurement if evidence.record else None
        sources = '; '.join(evidence_label(source) for source in evidence.sources)
        values = (measurement.value_ms, measurement.statistic, measurement.sample_count) if measurement else (None, None, None)
        lines.append(f'| {role} | {md_escape(values[0])} | {md_escape(values[1])} | {md_escape(values[2])} | {md_escape(sources)} |')
    observation = performance.comparison.observation
    if observation:
        lines.extend(['', f'Observed in these caller-provided measurements: `{observation.direction}`; delta `{observation.delta_ms:.6g} ms`; elapsed-time reduction `{observation.speedup_pct:.6g}%`.',
                      'Sources: ' + '; '.join(f'`{md_escape(evidence_label(source))}`' for source in observation.sources)])
    else:
        lines.extend(['', 'No comparative performance delta is available.'])
    for check in performance.eligibility.checks:
        if check.status not in {'match', 'not_applicable'}:
            lines.append(f'- `{md_escape(check.id)}`: {md_escape(check.reason_code)}; baseline `{md_escape(check.baseline)}`, candidate `{md_escape(check.candidate)}`; ' +
                         '; '.join(f'`{md_escape(evidence_label(source))}`' for source in check.sources))
    lines.extend(['', *(f'- {text}' for text in performance.limitations), '', '## Mechanism Assessment', '',
                  f'Coverage: `{mechanism.coverage}`.', '',
                  'Observations are listed by metric, not ranked by importance. The calling agent selects the evidence relevant to its question.', '',
                  '| Group | Status | Field A | Field B | Baseline | Candidate | Delta | Delta % | Sources / gaps |',
                  '|---|---|---|---|---:|---:|---:|---:|---|'])
    for row in mechanism.headlines:
        a, b = row.a, row.b or row.candidate
        sources = '; '.join(evidence_label(EvidenceCitation(artifact=item.artifact, field_ref=item.field_ref or item.field)) for item in (a, b) if item and item.artifact)
        reasons = '; '.join(row.comparison_reasons)
        lines.append(f'| {row.group} | {row.status} | {md_escape(a.field if a else None)} | {md_escape(b.field if b else None)} | '
                     f'{md_escape(a.value if a else None)} | {md_escape(b.value if b else None)} | {md_escape(row.delta)} | {md_escape(row.delta_pct)} | {md_escape(sources + "; " + reasons)} |')
    lines.extend(['', '### Profiler Compatibility', ''])
    for check in mechanism.compatibility.checks:
        lines.append(f'- `{check.id}`: `{check.status}`; A `{md_escape(check.a.value)}`, B `{md_escape(check.b.value)}`.')
    for check in mechanism.workload_checks:
        lines.append(f'- `{check.id}`: `{check.status}`; A `{md_escape(check.a)}`, B `{md_escape(check.b)}`.')
    for association in mechanism.benchmark_association:
        lines.append(f'- {association.role} benchmark association: `{association.status}`.')
        if association.limitation:
            lines.append(f'  {association.limitation}')
    lines.extend(['', *render_evidence_questions_markdown(mechanism.coverage, mechanism.questions), '', '### Pending Collection Actions', ''])
    lines.extend(f'- {action.role}: `{action.id}` ({action.necessity}); {action.reason}.' for action in mechanism.pending_actions)
    lines.extend(['', *(f'- {text}' for text in mechanism.limitations)])
    return lines
