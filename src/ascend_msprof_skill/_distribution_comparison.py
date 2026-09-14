"""Located distribution projections; no cell pairing or performance deltas."""
from __future__ import annotations

from .assessment_types import (ComparisonHeadline, DistributionObservation, DistributionComparison,
    HeadlineIssue, headline_comparison_reasons, mechanism_common_blockers, segment_check_blockers)
from .evidence_types import SourceRef
from ._headline_comparison import segment_checks
from .run_evidence import RunEvidence


def observations(run: RunEvidence) -> list[DistributionObservation]:
    summary = run.summary()
    evidence = summary.headlines.get('pipe_utilization') if summary else None
    if evidence is None:
        return []
    result = []
    for artifact_index, artifact in enumerate(evidence.artifacts):
        identity = run.target_identity()
        if identity is not None and identity.segments:
            identity = identity.segments.get(artifact.segment)
        names = identity.expected.names if identity and identity.expected else ()
        coverage = run.profile_coverage()
        segment = coverage.segments.get(artifact.segment) if coverage else None
        family = segment.metric_coverage.get('pipe_utilization') if segment else None
        issues = [HeadlineIssue(reason=issue.reason, source=issue.source) for issue in artifact.issues]
        if segment is None or not segment.count_complete or family is None or not family.complete:
            issues.append(HeadlineIssue(reason='distribution launch coverage incomplete',
                source=SourceRef(artifact='analysis/summary.json', field=f'profile_coverage.segments.{artifact.segment}')))
        for index, item in enumerate(artifact.core_time_distributions):
            context = ComparisonHeadline(present=True, name=names[0] if len(names) == 1 else artifact.launch_name,
                value=item.median_us, field=item.metric, field_kind='core_time_distribution',
                artifact=artifact.artifact, segment=artifact.segment, metric_scope=artifact.metric_scope,
                field_ref=f'headlines.pipe_utilization.artifacts[{artifact_index}].core_time_distributions[{index}]',
                unit=item.maximum.unit, statistic='median', aggregation='per_file_valid_block_cells',
                scope=dict(item.scope), block_scope={}, target_identity=identity, schema_issues=tuple(issues))
            result.append(DistributionObservation(context=context, summary=item))
    return result


def distribution_key(item: DistributionObservation) -> tuple:
    c = item.context
    return c.name, c.field, c.unit, c.segment, c.metric_scope, tuple(sorted(c.scope.items()))


def compare_distributions(candidate: RunEvidence, baseline: RunEvidence | None, workload_checks, compatibility):
    right = observations(candidate)
    if baseline is None:
        return tuple(DistributionComparison(status='observed', candidate=item,
            reasons=tuple(headline_comparison_reasons(item.context, item.context))) for item in right)
    left = observations(baseline)
    common = mechanism_common_blockers(workload_checks, compatibility, require_complete=True)
    rows = []
    # Repeated launches remain separate observations even if their metadata agrees.
    keys = dict.fromkeys(distribution_key(item) for item in (*left, *right))
    for key in keys:
        a = [item for item in left if distribution_key(item) == key]
        b = [item for item in right if distribution_key(item) == key]
        if len(a) != 1 or len(b) != 1:
            reason = 'distribution scope ambiguous' if len(a) > 1 or len(b) > 1 else 'matching distribution missing'
            rows.extend(DistributionComparison(status='unpaired', baseline=item, reasons=(reason,)) for item in a)
            rows.extend(DistributionComparison(status='unpaired', candidate=item, reasons=(reason,)) for item in b)
            continue
        checks = tuple(segment_checks(baseline, candidate, a[0].context.segment))
        reasons = tuple(dict.fromkeys([*common, *segment_check_blockers(checks, a[0].context.segment),
            *headline_comparison_reasons(a[0].context, b[0].context)]))
        rows.append(DistributionComparison(status='unpaired' if reasons else 'paired',
            baseline=a[0], candidate=b[0], reasons=reasons, checks=checks))
    return tuple(rows)
