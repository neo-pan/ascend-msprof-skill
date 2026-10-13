"""Pipeline diagnostics preserve partial evidence and refuse fabricated overlap."""
import hashlib
import json
import os
import shlex
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest import mock
from pydantic import ValidationError

from tests.helpers_shared import unittest
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.pipeline_evidence import build_pipeline_evidence, inspect_launcher, PipelineEvidence
from ascend_msprof_skill.cli import main as cli_main
from ascend_msprof_skill.profile_pipeline import main, pipeline_command
from ascend_msprof_skill.profile_harness import CommandExecutionResult
from ascend_msprof_skill._profile_target import normalize_target_contract
from ascend_msprof_skill.pipeline_timeline import render_simulator_svg

FIXTURES = Path(__file__).parent / "fixtures"
FAILURES = FIXTURES / "real_pipeline_failures_minimal"


class PipelineEvidenceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.run = self.root / "run"
        shutil.copytree(FIXTURES / "generic_profile_harness", self.run)

    def database(self, records):
        path = self.run / "reports/app/PROF_001/device_0/sqlite/biu_perf.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.execute('CREATE TABLE BiuCycles(timestamp NUMERIC, cycle_num INTEGER, unit_name TEXT)')
            connection.executemany('INSERT INTO BiuCycles VALUES(?,?,?)', records)
        return path

    def test_all_zero_capture_is_closed_and_preserves_other_timing(self):
        path = self.database([(0, 0, 'aic_core0_group0'), (0, 0, 'aiv_core25_group0')])
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        result = write_evidence_model(self.run)
        audit = build_pipeline_evidence(self.run)
        self.assertEqual(audit.samples, ())
        self.assertEqual(audit.device_instruction_sampling, 'closed')
        issue = next(item for item in audit.issues if item.code == 'device_instruction_sampling_closed')
        self.assertEqual(issue.source.artifact, path.relative_to(self.run).as_posix())
        self.assertEqual(issue.source_sha256, before)
        self.assertTrue(any('device_instruction_sampling_closed' in item for item in result.summary.warnings))
        self.assertTrue(result.summary.headlines['op_summary'].artifacts)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        self.assertFalse(path.with_name(path.name + '-journal').exists())

    def test_pipeline_model_cannot_readmit_historical_activity(self):
        self.database([(12, 40, 'aic_core0_group0'), (13, 20, 'aic_core0_group0')])
        audit = build_pipeline_evidence(self.run)
        payload = audit.model_dump(mode='json')
        payload['samples'] = [{'minimum_checks_passed': True, 'nonzero_activity_rows': 2}]
        with self.assertRaises(ValidationError):
            PipelineEvidence.model_validate(payload)
        self.assertEqual(audit.overlap_assessment, 'not_established')

    def test_corrupt_database_retains_valid_operator_evidence(self):
        path = self.database([])
        path.write_bytes(b'not a SQLite capture')
        result = write_evidence_model(self.run)
        self.assertTrue(result.summary.headlines['pipe_utilization'].artifacts)
        self.assertTrue(any('pipeline_sample_decode_failed' in item for item in result.summary.warnings))

    def test_ordinary_app_empty_biu_database_is_not_sampling_failure(self):
        source = next((FIXTURES / 'real_cann852_baseline/vector/reports').rglob('biu_perf.db'))
        path = self.run / 'reports/app/PROF_001/device_3/sqlite/biu_perf.db'
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)
        (self.run / 'logs/command_msprof.txt').write_text(
            'msprof --application=run.sh --runtime-api=on --task-time=on\n')
        audit = build_pipeline_evidence(self.run)
        self.assertEqual(audit.samples, ())
        self.assertEqual(audit.issues, ())
        self.assertEqual(path.read_bytes(), source.read_bytes())

    def test_explicit_sampling_is_closed_even_with_missing_biu_table(self):
        source = next((FIXTURES / 'real_cann852_baseline/vector/reports').rglob('biu_perf.db'))
        path = self.run / 'reports/app/PROF_001/device_3/sqlite/biu_perf.db'
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)
        for flag in ('--instr-profiling=on', '--instr-profiling on'):
            with self.subTest(flag=flag):
                (self.run / 'logs/command_msprof.txt').write_text(f'msprof --application=run.sh {flag}\n')
                audit = build_pipeline_evidence(self.run)
                self.assertEqual(audit.samples, ())
                self.assertIn('device_instruction_sampling_closed', {issue.code for issue in audit.issues})

    def test_explicit_sampling_without_any_database_is_closed(self):
        (self.run / 'logs/command_msprof.txt').write_text('msprof --instr-profiling=on\n')
        self.assertIn('device_instruction_sampling_closed',
                      {issue.code for issue in build_pipeline_evidence(self.run).issues})
        self.assertEqual(cli_main(['pipeline', '--run-dir', str(self.run)]), 2)

    def test_real_zero_exit_failures_are_sourced_without_discarding_metadata(self):
        log = self.run / 'logs/msprof_op.stdout'
        shutil.copyfile(FAILURES / 'timeline-detail-focused.stdout', log)
        (self.run / 'logs/msprof_op.result.json').write_text('{"status":"succeeded","process_returncode":0}')
        result = write_evidence_model(self.run)
        audit = build_pipeline_evidence(self.run)
        codes = {item.code for item in audit.issues}
        self.assertIn('timeline_detail_failed', codes)
        self.assertIn('kernel_argument_dump_failed', codes)
        self.assertTrue(result.summary.headlines['op_basic_info'].artifacts)
        for issue in audit.issues:
            self.assertEqual(issue.source.artifact, 'logs/msprof_op.stdout')
            self.assertTrue(log.read_text().splitlines()[issue.source.record - 1] in issue.message)
            self.assertEqual(issue.source_sha256, hashlib.sha256(log.read_bytes()).hexdigest())

    def test_real_failure_stages_remain_distinct(self):
        wanted = {'simulator-focused': 'simulator_library_load_failed',
                  'simulator-preserve-env': 'framework_simulator_api_failed',
                  'timeline-detail': 'target_not_selected', 'sampled': 'incompatible_collection_flags'}
        for name, code in wanted.items():
            with self.subTest(name=name):
                shutil.copyfile(FAILURES / (name + '.stdout'), self.run / 'logs/msprof_op.stdout')
                self.assertIn(code, {issue.code for issue in build_pipeline_evidence(self.run).issues})

    def test_launcher_preserves_library_injection_or_reports_override(self):
        app = self.root / 'launch.sh'
        app.write_text('#!/bin/sh\nexport LD_LIBRARY_PATH=/toolkit/lib\nexec python wrapper.py\n')
        self.assertEqual(len(inspect_launcher(app, self.run)), 1)
        app.write_text('#!/bin/sh\nexport LD_LIBRARY_PATH=/toolkit/lib:$LD_LIBRARY_PATH\nexec python wrapper.py\n')
        self.assertEqual(inspect_launcher(app, self.run), ())
        app.write_text('export LD_PRELOAD=/profiler/lib:${LD_PRELOAD:-}\n')
        self.assertEqual(inspect_launcher(app, self.run), ())

    def target(self):
        return normalize_target_contract({'target': {'kernel_selector': 'actual_fused_kernel*',
            'expected_launches': [{'name': 'actual_fused_kernel', 'count': 1}]}})

    def test_sampled_collection_is_closed_before_any_preflight_or_side_effect(self):
        root = self.root / 'closed'
        with (mock.patch('ascend_msprof_skill.profile_harness.load_manifest') as load,
              mock.patch('ascend_msprof_skill.profile_harness.SubprocessCommandRunner') as runner,
              mock.patch('ascend_msprof_skill.generate_provenance.collect_environment') as environment):
            code = cli_main(['profile-pipeline', '--run-dir', str(root),
                             '--manifest', str(self.root / 'missing.json'),
                             '--mode', 'sampled', '--sample-period', '300'])
        self.assertEqual(code, 2)
        load.assert_not_called()
        runner.assert_not_called()
        environment.assert_not_called()
        self.assertFalse(root.exists())

    def test_direct_command_builder_cannot_reopen_sampled_collection(self):
        for soc in (None, 'Ascend910B2', 'Ascend950'):
            with self.subTest(soc=soc), self.assertRaisesRegex(ValueError, 'device_instruction_sampling_closed'):
                pipeline_command(self.run, self.root / 'app.sh', self.target(),
                                 mode='sampled', soc_version=soc)

    def test_historical_nonzero_biu_is_closed_without_activity_admission(self):
        path = self.database([(12, 40, 'aic_core0_group0'), (13, 20, 'aic_core0_group0')])
        before = path.read_bytes()
        result = write_evidence_model(self.run)
        audit = json.loads((self.run / 'analysis/pipeline_evidence.json').read_text())
        self.assertEqual(audit['samples'], [])
        self.assertEqual(audit['device_instruction_sampling'], 'closed')
        self.assertIn('device_instruction_sampling_closed', {item['code'] for item in audit['issues']})
        self.assertTrue(result.summary.headlines['pipe_utilization'].artifacts)
        self.assertEqual(path.read_bytes(), before)

    def test_timeline_rejects_exported_biu_intervals_and_keeps_real_task(self):
        path = self.run / 'reports/app/PROF_001/mindstudio_profiler_output/msprof_biu.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        events = [
            {'name': 'process_name', 'ph': 'M', 'pid': 5, 'args': {'name': 'aic_core0_group0'}},
            {'name': 'thread_name', 'ph': 'M', 'pid': 5, 'tid': 0, 'args': {'name': 'Vector'}},
            {'name': '', 'ph': 'X', 'pid': 5, 'tid': 0, 'ts': 100, 'dur': 987654,
             'args': {'cycle_num': 99, 'ratio': 0.5}},
            {'name': 'biu_native_vector_kernel', 'ph': 'X', 'pid': 1000, 'ts': 100, 'dur': 25},
        ]
        path.write_text(json.dumps(events))
        before = path.read_bytes()
        self.assertEqual(cli_main(['pipeline', '--run-dir', str(self.run)]), 2)
        code = cli_main(['timeline', '--run-dir', str(self.run)])
        text = (self.run / 'analysis/timeline.txt').read_text()
        self.assertEqual(code, 2)
        self.assertIn('device_instruction_sampling_closed', text)
        self.assertNotIn('987654', text)
        self.assertIn('biu_native_vector_kernel', text)
        self.assertEqual(path.read_bytes(), before)

    def test_modes_avoid_incompatible_collection_flags(self):
        app = self.root / 'app.sh'
        detail = pipeline_command(self.run, app, self.target(), mode='timeline-detail')
        self.assertIn('--replay-mode=kernel', detail)
        self.assertNotIn('--replay-mode=application', detail)
        self.assertIn('--kernel-name=actual_fused_kernel*', detail)
        sim = pipeline_command(self.run, app, self.target(), mode='simulator', soc_version='Ascend910B2', core_id='0|31')
        self.assertIn('--aic-metrics=PipeUtilization,ResourceConflictRatio', sim)
        self.assertFalse(any('TimelineDetail' in item for item in sim))
        self.assertFalse(any('instr-profiling' in item for item in detail + sim))
        with self.assertRaises(ValueError):
            pipeline_command(self.run, app, self.target(), mode='simulator', sample_period=300,
                             soc_version='Ascend910B2')

    def manifest(self, app):
        path = self.root / 'manifest.json'
        path.write_text(json.dumps({'application': str(app), 'target': self.target().model_dump(mode='json')}))
        return path

    def test_simulator_override_is_blocked_before_launch(self):
        app = self.root / 'app.sh'
        app.write_text('export LD_LIBRARY_PATH=/toolkit/lib\n')
        with mock.patch('ascend_msprof_skill.profile_harness.SubprocessCommandRunner') as runner:
            code = main(['--run-dir', str(self.root / 'new'), '--manifest', str(self.manifest(app)),
                         '--mode', 'simulator', '--soc-version', 'Ascend910B2'])
        self.assertEqual(code, 2)
        runner.assert_not_called()
        self.assertTrue((self.root / 'new/logs/pipeline_preflight.json').exists())

    def test_zero_exit_detail_failure_reaches_cli_and_keeps_basic_info(self):
        app = self.root / 'app.sh'
        app.write_text('#!/bin/sh\nexec python wrapper.py\n')
        root = self.root / 'new'

        def run(command, **kwargs):
            if '--help' in command:
                return CommandExecutionResult('TimelineDetail --replay-mode --kernel-name --launch-count --warm-up', '', 0)
            folder = root / 'reports/op/OPPROF_001'
            folder.mkdir(parents=True)
            (folder / 'OpBasicInfo.csv').write_text('Op Name,Task Duration(us)\nactual_fused_kernel_mix_aic,30\n')
            return CommandExecutionResult((FAILURES / 'timeline-detail-focused.stdout').read_text(), '', 0)

        with (mock.patch('ascend_msprof_skill.profile_harness.SubprocessCommandRunner') as runner,
              mock.patch('ascend_msprof_skill.generate_provenance.collect_environment')):
            runner.return_value.run.side_effect = run
            code = main(['--run-dir', str(root), '--manifest', str(self.manifest(app)), '--mode', 'timeline-detail'])
        self.assertEqual(code, 1)
        result = json.loads((root / 'analysis/profile_pipeline_run.json').read_text())
        self.assertEqual(result['process_returncode'], 0)
        self.assertEqual(result['evidence_status'], 'blocked')
        self.assertTrue((root / 'reports/op/OPPROF_001/OpBasicInfo.csv').is_file())

    def test_active_modes_run_relative_harness_from_application_directory(self):
        harness = self.root / 'caller harness'
        harness.mkdir()
        app = harness / 'run.sh'
        app.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} wrapper.py\n')
        app.chmod(0o755)
        (harness / 'wrapper.py').write_text(
            'from pathlib import Path\nprint(Path("input.txt").read_text())\n')
        (harness / 'input.txt').write_text('relative companion and data loaded')
        manifest = harness / 'manifest.json'
        manifest.write_text(json.dumps({
            'application': 'run.sh', 'target': self.target().model_dump(mode='json')}))

        # Replace only the unavailable profiler: the real command runner must
        # execute this shell and the caller's relative Python/data accesses.
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        msprof = bin_dir / 'msprof'
        msprof.write_text(
            '#!/bin/sh\n'
            'for argument do\n'
            '  case "$argument" in\n'
            '    --help) echo "TimelineDetail '
            '--replay-mode --kernel-name --launch-count --warm-up --soc-version '
            'ResourceConflictRatio"; exit 0 ;;\n'
            '    --application=*) application=${argument#--application=} ;;\n'
            '  esac\n'
            'done\n'
            'exec "$application"\n')
        msprof.chmod(0o755)
        modes = {'timeline-detail': 'msprof_op', 'simulator': 'msprof_simulator'}
        with (mock.patch.dict(os.environ, {'PATH': str(bin_dir) + os.pathsep + os.environ['PATH']}),
              mock.patch('ascend_msprof_skill.generate_provenance.collect_environment')):
            for mode, stem in modes.items():
                with self.subTest(mode=mode):
                    root = self.root / ('new-' + mode)
                    arguments = ['--run-dir', str(root), '--manifest', str(manifest), '--mode', mode]
                    if mode == 'simulator':
                        arguments += ['--soc-version', 'Ascend910B2']
                    main(arguments)
                    result = json.loads((root / 'analysis/profile_pipeline_run.json').read_text())
                    stderr = (root / f'logs/{stem}.stderr').read_text()
                    self.assertEqual(result['process_returncode'], 0, stderr)
                    self.assertEqual(result['process_status'], 'succeeded')
                    self.assertEqual((root / f'logs/{stem}.stdout').read_text().strip(),
                                     'relative companion and data loaded')
                    # Launch success must not be mistaken for profiler evidence.
                    self.assertEqual(result['overlap_assessment'], 'not_established')

    def test_real_simulator_svg_retains_lanes_and_source(self):
        path = FIXTURES / 'real_simulator_minimal/reports/OPPROF_001/simulator/trace.json'
        obj = json.loads(path.read_text())
        svg = render_simulator_svg(obj['traceEvents'], 'reports/simulator/trace.json', hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertIn('core3.veccore0 / MTE2', svg)
        self.assertIn('core3.veccore0 / VECTOR', svg)
        self.assertIn('dur=0.154 us', svg)
        self.assertIn('Simulator time (us)', svg)
        self.assertIsNone(render_simulator_svg([{'ph': 'B', 'ts': 1}, {'ph': 'E', 'ts': 2}], 'trace.json', 'a'))
