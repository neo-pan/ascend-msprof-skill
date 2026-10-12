"""Replay actual 8.5.2 application/operator collections without device access."""
import csv
import hashlib
import io
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from tests.helpers_shared import unittest
from ascend_msprof_skill import analyze_msprof_outputs, generate_provenance, generate_report
from ascend_msprof_skill.run_evidence import RunEvidence
from ascend_msprof_skill.evidence_model import write_evidence_model


FIXTURE = Path(__file__).parent / 'fixtures/real_cann852_baseline'
DEFAULT_SEGMENT = 'followup:collect_default_metric_followup'


class Cann852BaselineTests(unittest.TestCase):
    def test_source_scope_keeps_pmu_evidence_without_claiming_source_attribution(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / 'source'
            shutil.copytree(FIXTURE / 'vector_source', run)
            result = write_evidence_model(run)
            self.assertEqual(result.summary.metric_scope.value, 'Default,Source')
            self.assertTrue(result.summary.headlines['pipe_utilization'].artifacts[0].observations)
            self.assertTrue(any('source-line or instruction attribution' in claim
                                for claim in result.summary.evidence_readiness.blocked_claims))
            self.assertEqual(result.summary.target_identity.status, 'match')
            next((run / 'reports').rglob('ResourceConflictRatio.csv')).unlink()
            incomplete = write_evidence_model(run).summary
            self.assertTrue(any(action.recommended_aic_metrics == ('Default,Source',)
                                and 'ResourceConflictRatio.csv' in action.required_artifacts
                                for action in incomplete.next_collection_actions))

    def test_memory_detail_enables_active_bandwidth_without_turning_na_into_zero(self):
        metrics = ('aic_mte1_active_bw(GB/s)', 'aic_mte2_active_bw(GB/s)')
        baseline = next((FIXTURE / 'cube/reports/followups').rglob('PipeUtilization.csv'))
        detail = next((FIXTURE / 'cube_memory_detail/reports/op').rglob('PipeUtilization.csv'))
        with baseline.open(newline='') as stream:
            baseline_first = next(csv.DictReader(stream))
        with detail.open(newline='') as stream:
            detail_first = next(csv.DictReader(stream))
        self.assertEqual((baseline_first['block_id'], baseline_first['sub_block_id']), ('0', 'cube0'))
        self.assertEqual((detail_first['block_id'], detail_first['sub_block_id']), ('0', 'cube0'))
        for metric, value in zip(metrics, ('244.098267', '37.883278')):
            self.assertEqual(baseline_first[metric], 'NA')
            self.assertEqual(detail_first[metric], value)
        for name, expected_present in [('cube', False), ('cube_memory_detail', True)]:
            with self.subTest(workload=name), tempfile.TemporaryDirectory() as temporary:
                run = Path(temporary) / name
                shutil.copytree(FIXTURE / name, run)
                result = write_evidence_model(run)
                observations = [item for artifact in result.summary.headlines['pipe_utilization'].artifacts
                                for item in artifact.observations if item.metric in metrics]
                self.assertEqual(bool(observations), expected_present)
                for item in observations:
                    self.assertGreater(item.value, 0)
                    self.assertEqual(item.unit, 'GB/s')
                    with (run / item.source.artifact).open(newline='') as stream:
                        rows = list(csv.reader(stream))
                    self.assertEqual(rows[item.source.record - 1][item.source.column - 1], item.raw_token)
                if expected_present:
                    self.assertEqual(result.summary.metric_scope.value, 'Default,MemoryDetail')
                    # A missing requested family must cause the combined scope
                    # to request recollection, instead of having no policy.
                    next((run / 'reports').rglob('PipeUtilization.csv')).unlink()
                    incomplete = write_evidence_model(run).summary
                    self.assertTrue(any(action.recommended_aic_metrics == ('Default,MemoryDetail',)
                                        and 'PipeUtilization.csv' in action.required_artifacts
                                        for action in incomplete.next_collection_actions))

    def test_basic_info_does_not_require_unrequested_metric_families(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / 'basic_info'
            shutil.copytree(FIXTURE / 'vector_basic', run)
            result = write_evidence_model(run)
            self.assertEqual(result.summary.metric_scope.value, 'BasicInfo')
            self.assertEqual(result.summary.target_identity.status, 'match')
            evidence = RunEvidence.load(run)
            caveats = evidence.report_caveats([], op_metric_scope_value='BasicInfo')
            for group in ('pipe_utilization', 'arithmetic_utilization', 'memory', 'resource_conflict', 'l2_cache'):
                self.assertFalse(any(f'missing {group}:' in item for item in caveats), caveats)
            self.assertEqual(result.summary.next_collection_actions, ())
            next((run / 'reports').rglob('OpBasicInfo.csv')).unlink()
            incomplete = write_evidence_model(run).summary
            self.assertTrue(any(action.recommended_aic_metrics == ('BasicInfo',)
                                and 'OpBasicInfo.csv' in action.required_artifacts
                                for action in incomplete.next_collection_actions))

    def test_original_csv_bytes_and_sanitized_receipts_match_origin(self):
        for run in sorted(path for path in FIXTURE.iterdir() if path.is_dir()):
            with self.subTest(workload=run.name):
                origin = json.loads((run / 'origin.json').read_text())
                self.assertEqual(origin['toolkit'], '8.5.2')
                for record in origin['files']:
                    data = (run / record['artifact']).read_bytes()
                    self.assertEqual(hashlib.sha256(data).hexdigest(), record['fixture_sha256'])
                    if record['artifact'].startswith('reports/'):
                        # Exact native header/metric values; no version replacement
                        # or synthetic rows are permitted in the new baseline.
                        self.assertEqual(record['source_sha256'], record['fixture_sha256'])
                    text = data.decode()
                    self.assertNotIn('Serial Number', text)
                    self.assertNotIn('MAC Address', text)

    def test_live_baseline_replays_analysis_target_coverage_and_report(self):
        for kind, kernel, pipe_metric, arithmetic_metric, memory_metric in [
            ('vector', 'biu_native_vector_kernel', 'aiv_vec_ratio',
             'aiv_vec_fp32_ratio', 'aiv_ub_read_bw_vector(GB/s)'),
            ('cube', 'biu_cube_matmul_kernel', 'aic_cube_ratio',
             'aic_cube_fp16_ratio', 'aic_l0a_read_bw(GB/s)'),
        ]:
            with self.subTest(workload=kind), tempfile.TemporaryDirectory() as temporary:
                run = Path(temporary) / kind
                shutil.copytree(FIXTURE / kind, run)
                # Offline replay must use the original environment capture.
                with (mock.patch('ascend_msprof_skill.generate_provenance.collect_environment') as collect,
                      mock.patch('sys.stdout', new_callable=io.StringIO)):
                    generate_provenance.main(['--run-dir', str(run)])
                    analyze_msprof_outputs.main(['--run-dir', str(run)])
                    generate_report.main(['--run-dir', str(run)])
                collect.assert_not_called()
                evidence = RunEvidence.load(run)
                provenance = evidence.provenance()
                self.assertEqual(provenance.cann_version.value, '8.5.2')
                self.assertEqual(provenance.cann_version.source.artifact, 'logs/toolkit_install.info')
                self.assertEqual(provenance.cann_version.source.field, 'version')
                self.assertTrue(all(item.name.value == '910B2' for item in provenance.hardware.devices))
                summary = evidence.summary()
                self.assertEqual(summary.target_identity.status, 'match')
                self.assertEqual(summary.profile_coverage.expected_total, 1)
                for segment in ('app', 'op', DEFAULT_SEGMENT):
                    coverage = summary.profile_coverage.segments[segment]
                    self.assertTrue(coverage.count_complete)
                    self.assertEqual(coverage.observed_total, 1)
                    self.assertEqual(summary.target_identity.segments[segment].status, 'match')
                self.assertTrue(summary.profile_coverage.segments[DEFAULT_SEGMENT].metric_coverage['memory'].complete)
                self.assertFalse(any('pipeline_sample_decode_failed' in warning for warning in summary.warnings))
                for group, metric in [('pipe_utilization', pipe_metric),
                                      ('arithmetic_utilization', arithmetic_metric),
                                      ('memory', memory_metric)]:
                    observations = [item for artifact in summary.headlines[group].artifacts
                                    for item in artifact.observations if item.metric == metric]
                    self.assertTrue(observations, metric)
                    self.assertTrue(any(item.value > 0 for item in observations), metric)
                    for observation in observations:
                        with (run / observation.source.artifact).open(newline='') as stream:
                            rows = list(csv.reader(stream))
                        self.assertEqual(rows[0][observation.source.column - 1], metric)
                        token = rows[observation.source.record - 1][observation.source.column - 1]
                        self.assertEqual(token, observation.raw_token)
                        self.assertEqual(float(token), observation.value)
                report = (run / 'REPORT.md').read_text()
                self.assertIn(kernel, report)
                self.assertIn('8.5.2', report)
                self.assertIn(pipe_metric, report)
                self.assertIn('No comparative performance delta is available.', report)
