"""Navigation must lead to usable evidence without upgrading its authority."""
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill._evidence_reading_guide import write_reading_guide
from ascend_msprof_skill.compare_runs import build_comparison
from tests.helpers_shared import fresh_real_run, fresh_op_basic_block_dim_with_timing_sim_run, write_minimal_app_timing


ROOT = Path(__file__).resolve().parent.parent


def hashes(run):
    return {str(path.relative_to(run)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (run / "reports").rglob("*") if path.is_file()}


class EvidenceNavigationTests(unittest.TestCase):
    def assert_pointers_resolve(self, run, guide):
        pointers = re.findall(r'`((?:summary|raw_artifact_index)\.json)#(/[^`\s]*)`', guide)
        self.assertTrue(pointers)
        documents = {name: json.loads((run / "analysis" / name).read_text())
                     for name in ("summary.json", "raw_artifact_index.json")}
        for name, pointer in pointers:
            value = documents[name]
            for part in pointer[1:].split('/'):
                part = part.replace('~1', '/').replace('~0', '~')
                value = value[int(part)] if isinstance(value, list) else value[part]

    def test_application_only_does_not_advertise_empty_operator_families(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            write_minimal_app_timing(run)
            artifacts = write_evidence_model(run)
            guide = artifacts.reading_guide_path.read_text()
            self.assertIn('[pipe_utilization](#family-pipe-utilization) — no admitted artifacts.', guide)
            self.assertNotIn('--artifact', guide)  # no operator query commands for application CSVs
            self.assertIn('not applicable (application timing)', guide)
            self.assert_pointers_resolve(run, guide)

    def test_unknown_operator_scope_and_tail_locations_survive_navigation(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = fresh_real_run(Path(tmp))
            # No recorded command: operator scope cannot be inferred from a filename.
            for path in (run / 'logs').glob('command*.txt'):
                path.unlink()
            artifacts = write_evidence_model(run)
            guide = artifacts.reading_guide_path.read_text()
            unknown_pipes = 0
            for evidence in artifacts.summary.headlines.values():
                for item in evidence.artifacts:
                    if item.group == 'pipe_utilization' and item.metric_scope is None:
                        unknown_pipes += 1
                        entry = guide.split(f'- Artifact: `{item.artifact}`', 1)[1].split('\n\n', 1)[0]
                        self.assertIn('metric scope: `unknown`', entry)
                        self.assertIn('core_time_distributions', entry)
            self.assertGreater(unknown_pipes, 0)
            self.assertIn('per-block time / maximum location / second largest:', artifacts.key_metrics_path.read_text())
            self.assert_pointers_resolve(run, guide)

    def test_empty_and_invalid_artifacts_keep_parser_status_and_no_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = fresh_real_run(Path(tmp))
            pipe = next((run / 'reports').rglob('PipeUtilization*.csv'))
            for content, status in [('block_id,sub_block_id,aiv_time(us)\n', 'empty'),
                                    ('block_id,sub_block_id,aiv_time(us)\n0,vector0,broken\n', 'parsed'),
                                    ('block_id,sub_block_id,aiv_time(us)\n0,vector0,1,extra\n', 'invalid')]:
                with self.subTest(status=status):
                    pipe.write_text(content)
                    artifacts = write_evidence_model(run)
                    guide = artifacts.reading_guide_path.read_text()
                    item = artifacts.summary.headlines['pipe_utilization'].artifacts[0]
                    self.assertEqual(item.status, status)
                    self.assertIn(f'{status}=1; 0 with numeric observations.', guide)
                    self.assertIn(f'parser: `{status}`', guide)
                    self.assert_pointers_resolve(run, guide)

    def test_simulator_route_is_outside_headlines_and_failed_receipts_exclude_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = fresh_op_basic_block_dim_with_timing_sim_run(Path(tmp))
            artifacts = write_evidence_model(run)
            dimension = next(d for d in artifacts.summary.analysis_dimensions if d.id == 'source_pipeline_context')
            self.assertTrue(dimension.signals)
            guide = artifacts.reading_guide_path.read_text()
            self.assertIn(f'Recorded signals: {len(dimension.signals)}; dimension status: `available`', guide)
            for signal in dimension.signals:
                self.assertIn(signal.artifact, guide)
            self.assert_pointers_resolve(run, guide)
            (run / 'logs').mkdir(exist_ok=True)
            (run / 'logs/msprof_simulator.result.json').write_text('{"status":"timeout"}')
            failed = write_evidence_model(run)
            dimension = next(d for d in failed.summary.analysis_dimensions if d.id == 'source_pipeline_context')
            self.assertFalse(dimension.signals)
            self.assertIn('excluded by collection receipt', failed.reading_guide_path.read_text())

    def test_rendering_preserves_machine_evidence_and_raw_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = fresh_real_run(Path(tmp))
            artifacts = write_evidence_model(run)
            paths = [artifacts.summary_path, artifacts.raw_artifact_index_path]
            before = [p.read_bytes() for p in paths]
            raw = hashes(run)
            write_reading_guide(artifacts.reading_guide_path, artifacts.summary, artifacts.raw_artifact_index)
            self.assertEqual(before, [p.read_bytes() for p in paths])
            self.assertEqual(raw, hashes(run))
            self.assertIn('[reading_guide.md](reading_guide.md)', artifacts.key_metrics_path.read_text())

    def test_real_matmul_walkthrough_keeps_scopes_records_and_performance_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = []
            durations = []
            for name in ('serial', 'pipelined'):
                run = Path(tmp) / name
                shutil.copytree(ROOT / 'tests/fixtures/tilelang_design_feedback/pipeline_expression' / name, run)
                before = hashes(run)
                artifacts = write_evidence_model(run)
                self.assertEqual(before, hashes(run))
                guide = artifacts.reading_guide_path.read_text()
                self.assert_pointers_resolve(run, guide)
                basic = artifacts.summary.headlines['op_basic_info'].artifacts
                self.assertEqual({a.metric_scope for a in basic}, {None, 'Default'})
                self.assertIn('metric scope: `unknown`', guide)
                self.assertIn('metric scope: `Default`', guide)
                durations.append({a.segment: next(o.value for o in a.observations if o.metric == 'Task Duration(us)') for a in basic})
                runs.append(run)
            self.assertEqual([d['op'] for d in durations], [52.439999, 52.259998])
            self.assertEqual([d['followup:collect_default_metric_followup'] for d in durations], [52.48, 52.860001])
            comparison = build_comparison(*runs)
            self.assertEqual(comparison.performance_assessment.eligibility.status, 'incomplete')
            pipe = next((runs[0] / 'reports/op').rglob('PipeUtilization.csv'))
            with pipe.open(newline='') as stream:
                records = list(csv.DictReader(stream))
            self.assertEqual([(records[n - 2]['block_id'], records[n - 2]['aic_cube_ratio'], records[n - 2]['aic_mte2_ratio'])
                              for n in (8, 35)], [('2', '0.102457', '0.262756'), ('11', '0.095331', '0.263045')])
