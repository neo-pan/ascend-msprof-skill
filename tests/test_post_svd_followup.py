"""Regression boundaries from the SVD natural/app/op workflow."""
import json
from pathlib import Path
import tempfile
from unittest import mock

from tests.helpers_shared import unittest, fresh_target_identity_run
from ascend_msprof_skill.assessment_types import (ComparisonHeadline, DistributionObservation,
    DistributionComparison, CompatibilitySide, CompatibilityCheck, CandidateSummary, headline_comparison_reasons)
from ascend_msprof_skill.identity_types import ExpectedTarget, _identity
from ascend_msprof_skill.operator_evidence import normalize_operator
from ascend_msprof_skill.profile_harness import ensure_fresh_collection_run
from ascend_msprof_skill.summarize_candidate import write_candidate_summary, build_candidate_summary, render_markdown
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.compare_runs import build_comparison
from ascend_msprof_skill.run_evidence import RunEvidence


class PostSvdFollowupTests(unittest.TestCase):
    def identity(self):
        return _identity(ExpectedTarget(names=('kernel',), artifact='context/target.json', field_ref='name'),
            [dict(name='kernel', group='op_basic_info', artifact='reports/op/OpBasicInfo.csv', field_ref='Op Name')])

    def app(self, **changes):
        values = dict(present=True, name='kernel', value=12.0, field='Task Duration(us)', field_kind='timing_duration',
                      segment='app', metric_scope=None, unit='us', statistic='duration', aggregation='maximum_observed_cell',
                      scope={'Device_id':'0'}, block_scope={}, target_identity=self.identity())
        values.update(changes)
        return ComparisonHeadline(**values)

    def test_application_null_scope_is_not_an_operator_scope_exemption(self):
        a = self.app()
        self.assertEqual(headline_comparison_reasons(a, a), [])
        for changes, reason in (({'segment':'op'},'metric_scope missing'),
                                ({'field':'Unknown Duration(us)'},'metric_scope missing'),
                                ({'field_kind':'duration'},'metric_scope missing'),
                                ({'metric_scope':'Default'},'metric_scope missing'),
                                ({'unit':'ms'},'unit mismatch'),
                                ({'name':'other'},'name mismatch'),
                                ({'target_identity':None},'target unverified')):
            with self.subTest(changes=changes):
                self.assertIn(reason, headline_comparison_reasons(a,self.app(**changes)))
        self.assertIn('metric_scope mismatch', headline_comparison_reasons(
            self.app(segment='op', metric_scope='Default'), self.app(segment='op', metric_scope='PipeUtilization')))

    def test_distribution_keeps_moved_maximum_without_pairing_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'PipeUtilization.csv'
            def observation(block, maximum):
                path.write_text(f'block_id,sub_block_id,aiv_time(us)\n0,vector0,750\n{block},vector0,{maximum}\n')
                d=normalize_operator(path,'reports/op/PipeUtilization.csv','pipe_utilization','op','PipeUtilization').core_time_distributions[0]
                c=self.app(segment='op', metric_scope='PipeUtilization', field=d.metric,
                           field_kind='core_time_distribution', statistic='median', aggregation='per_file_valid_block_cells',
                           value=d.median_us, scope=dict(d.scope), artifact=d.maximum.source.artifact)
                return DistributionObservation(context=c, summary=d)
            a,b=observation(255,68190.74),observation(1,9399.58)
            side=CompatibilitySide(value='recorded',source=None)
            checks=tuple(CompatibilityCheck(id=f'segment.op.{key}',title=key,status='match',a=side,b=side) for key in ('command','output'))
            row=DistributionComparison(status='paired',baseline=a,candidate=b,checks=checks)
            loaded = DistributionComparison.model_validate_json(row.model_dump_json())
            self.assertEqual(loaded.baseline.summary, row.baseline.summary)
            self.assertEqual(loaded.candidate.summary, row.candidate.summary)
            self.assertEqual(dict(row.baseline.summary.maximum.scope)['block_id'],'255')
            self.assertEqual(dict(row.candidate.summary.maximum.scope)['block_id'],'1')
            self.assertNotIn('delta',row.model_dump())
            with self.assertRaises(ValueError):
                DistributionComparison(status='paired',baseline=a,candidate=b,checks=())

    def test_multiple_files_are_unpaired_and_invalid_cells_remain_located(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=fresh_target_identity_run(Path(tmp))
            raw='block_id,sub_block_id,aiv_time(us)\n0,vector0,750\n255,vector0,68190\n2,vector0,N/A\n'
            for folder in ('OPPROF_001','OPPROF_002'):
                path=run/'reports'/folder/'PipeUtilization.csv'
                path.parent.mkdir(exist_ok=True)
                path.write_text(raw)
            write_evidence_model(run)
            result=build_comparison(run,run)
            rows=result.mechanism_assessment.distributions
            self.assertEqual(len(rows),4)
            self.assertTrue(all(row.status=='unpaired' and 'distribution scope ambiguous' in row.reasons for row in rows))
            for row in rows:
                side=row.baseline or row.candidate
                self.assertEqual(side.summary.valid_count,2)
                self.assertTrue(side.context.schema_issues)
                self.assertEqual(side.summary.maximum.source.record,3)

    def test_context_registration_is_fresh_but_results_are_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp); analysis=run/'analysis';analysis.mkdir()
            for name in ('tilelang_context.json','benchmark_context.json'):
                (analysis/name).write_text('{}')
            ensure_fresh_collection_run(run)
            (analysis/'summary.json').write_text('{}')
            with self.assertRaisesRegex(RuntimeError,'fresh run'):
                ensure_fresh_collection_run(run)

    def test_single_run_rendering_uses_the_loaded_machine_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=fresh_target_identity_run(Path(tmp),app_observed='main_kernel')
            pipe=run/'reports/OPPROF_001/PipeUtilization.csv'
            pipe.write_text('block_id,sub_block_id,aiv_time(us)\n0,vector0,750\n255,vector0,68190\n')
            write_evidence_model(run)
            with mock.patch.object(RunEvidence,'load_assessment',wraps=RunEvidence.load_assessment) as load:
                json_path,md_path=write_candidate_summary(run)
                self.assertEqual(load.call_count,1)
            result=CandidateSummary.model_validate_json(json_path.read_text())
            self.assertTrue(result.mechanism_assessment.distributions)
            self.assertEqual(md_path.read_text(),render_markdown(result))
            self.assertLess(md_path.read_text().index('## Per-block Time Distributions'),md_path.read_text().index('## Warnings'))
