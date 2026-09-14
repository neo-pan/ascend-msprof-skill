"""Whole-chain regressions for assessment admission and numeric consumption."""
import contextlib
import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pydantic import ValidationError
from tests import test_assessment_normalization as assessments
from tests import test_headline_comparison as headlines
from ascend_msprof_skill.assessment_types import (
    CandidateSummary, ComparisonSummary, HeadlineComparison, MechanismAssessment,
    PerformanceAssessment, RunAssessment, mechanism_coverage, mechanism_findings,
)
from ascend_msprof_skill.compare_runs import build_comparison
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.extract_simulator_hotspots import render_markdown as render_simulator
from ascend_msprof_skill.generate_report import build_report
from ascend_msprof_skill.plot_timeline import main as timeline
from ascend_msprof_skill.run_evidence import RunEvidence
from ascend_msprof_skill.simulator_hotspot_model import build_simulator_hotspot_model
from ascend_msprof_skill.simulator_types import SimulatorModel
from ascend_msprof_skill.summarize_candidate import build_candidate_summary, render_markdown


class NormalizationAuditRegressions(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def fixture(self, cls):
        case = cls()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_headline_forms_are_bound_to_the_parent_mode(self):
        case = self.fixture(headlines.HeadlineComparisonTests)
        single = build_candidate_summary(case.candidate)
        paired = build_comparison(case.baseline, case.candidate)
        row = next(r for r in paired.mechanism_assessment.headlines if r.numeric)
        changed = row.model_dump(mode='json')
        changed.update(status='changed', delta=0.0, delta_pct=0.0)
        changed['b']['value'] = 0.7
        changed['delta'] = 0.7 - row.a.value
        changed['delta_pct'] = changed['delta'] / abs(row.a.value) * 100
        unavailable = row.model_dump(mode='json')
        unavailable.update(status='not_comparable', numeric=False, delta=None, delta_pct=None,
                           comparison_reasons=['field mismatch'])
        unavailable['b']['field'] = 'other'
        paired_rows = [row, HeadlineComparison.model_validate(changed),
                       HeadlineComparison.model_validate(unavailable),
                       next(r for r in paired.mechanism_assessment.headlines if r.status == 'missing')]
        observed = single.mechanism_assessment.headlines[0]
        for parent, rows in ((single, paired_rows), (paired, [observed])):
            for transplanted in rows:
                with self.subTest(mode=parent.mechanism_assessment.mode, status=transplanted.status):
                    HeadlineComparison.model_validate(transplanted.model_dump(mode='json'))
                    payload = parent.model_dump(mode='json')
                    mechanism = payload['mechanism_assessment']
                    # Preserve all existing composition rules except the run mode.
                    source = paired.mechanism_assessment
                    mechanism['compatibility'] = source.compatibility.model_dump(mode='json')
                    mechanism['workload_checks'] = [c.model_dump(mode='json') for c in source.workload_checks]
                    mechanism['headlines'] = [transplanted.model_dump(mode='json')]
                    findings = mechanism_findings((transplanted,))
                    mechanism['findings'] = [f.model_dump(mode='json') for f in findings]
                    own = parent.mechanism_assessment
                    mechanism['coverage'] = mechanism_coverage(
                        own.evidence, own.questions, source.workload_checks, source.compatibility, findings)
                    with self.assertRaisesRegex(ValidationError, 'headline.*mode'):
                        type(parent).model_validate(payload)
        for model in (single, paired):
            self.assertEqual(type(model).model_validate_json(model.model_dump_json()), model)

    def linked_runs(self):
        case = self.fixture(assessments.AssessmentNormalizationTests)
        raw = b'# measured implementation\n'
        subject = hashlib.sha256(raw).hexdigest()
        case.data['assessment']['subject']['implementation']['id'] = subject
        case.data['assessment']['correctness']['subject_id'] = subject
        for run in (case.a, case.b):
            case.write(run)
            (run / 'payload.py').write_bytes(raw)
            (run / 'analysis/tilelang_context.json').write_text(json.dumps({
                'sources': {'payload': {'artifact': 'payload.py', 'sha256': subject}}, 'benchmark': {}}))
        return case

    def test_association_copies_agree_with_each_roles_embedded_record(self):
        case = self.linked_runs()
        for original in (build_candidate_summary(case.b), build_comparison(case.a, case.b)):
            for role in original.mechanism_assessment.evidence:
                for field, replacement in (('benchmark_subject', 'different-subject'),
                        ('benchmark_workload.id', 'different-workload'),
                        ('benchmark_workload.shape', [256, 128]),
                        ('benchmark_workload.dtype', 'float16'), ('benchmark_workload.case_count', 2)):
                    payload = original.model_dump(mode='json')
                    link = next(a for a in payload['mechanism_assessment']['benchmark_association'] if a['role'] == role)
                    check = next(c for c in link['checks'] if c['id'] == field)
                    check['benchmark'] = check['profiler'] = replacement
                    if field.startswith('benchmark_workload.'):
                        for observation in check['sources']:
                            observation['value'] = replacement
                    # The leaf checks, mechanism and natural performance remain legal.
                    MechanismAssessment.model_validate(payload['mechanism_assessment'])
                    PerformanceAssessment.model_validate(payload['performance_assessment'])
                    with self.subTest(role=role, field=field), self.assertRaisesRegex(
                            ValidationError, 'association.*record'):
                        type(original).model_validate(payload)
                    with self.assertRaises(ValidationError):
                        RunAssessment.model_validate({k: payload[k] for k in
                            ('performance_assessment', 'mechanism_assessment')})

    def test_record_mutations_and_missing_record_cannot_retain_link(self):
        case = self.linked_runs()
        original = build_candidate_summary(case.b)
        for field in ('workload', 'subject'):
            payload = original.model_dump(mode='json')
            record = payload['performance_assessment']['measurements']['candidate']['record']
            if field == 'workload':
                record['workload']['id'] = 'other'
            else:
                record['subject']['implementation']['id'] = 'other'
                record['correctness']['subject_id'] = 'other'
            PerformanceAssessment.model_validate(payload['performance_assessment'])
            with self.subTest(field=field), self.assertRaisesRegex(ValidationError, 'association.*record'):
                CandidateSummary.model_validate(payload)
        missing = build_candidate_summary(self.root).model_dump(mode='json')
        missing['mechanism_assessment']['benchmark_association'] = original.model_dump(mode='json')[
            'mechanism_assessment']['benchmark_association']
        MechanismAssessment.model_validate(missing['mechanism_assessment'])
        with self.assertRaisesRegex(ValidationError, 'association.*record'):
            CandidateSummary.model_validate(missing)

    def test_either_subject_match_remains_sufficient_without_file_reads(self):
        case = self.linked_runs()
        payload = build_candidate_summary(case.b).model_dump(mode='json')
        checks = payload['mechanism_assessment']['benchmark_association'][0]['checks']
        mismatch = copy.deepcopy(next(c for c in checks if c['id'] == 'benchmark_subject'))
        mismatch.update(profiler='different-harness', status='mismatch')
        checks.append(mismatch)
        with mock.patch.object(Path, 'open', side_effect=AssertionError('unexpected file read')):
            model = CandidateSummary.model_validate(payload)
            self.assertEqual(model.mechanism_assessment.benchmark_association[0].status, 'linked')
            self.assertEqual(CandidateSummary.model_validate_json(model.model_dump_json()), model)
            self.assertIn('## Evidence Questions', render_markdown(model))

    def test_unreadable_source_path_preserves_simulator_metrics_and_summary(self):
        (self.root / 'loop.cpp').symlink_to('loop.cpp')
        for filename in ('bad\0.cpp', 'x' * 300 + '.cpp', 'loop.cpp'):
            with self.subTest(filename=repr(filename)):
                path = self.write('reports/OPPROF_001/simulator/core0_code_exe.csv',
                                  f'code,call_count,running_time(us)\n{filename}:1,2,3\n')
                raw = path.read_bytes()
                result = write_evidence_model(self.root)
                model = SimulatorModel.model_validate_json(result.simulator_model.model_dump_json())
                row = model.source_lines[0]
                self.assertEqual(row.primary_metric.value, 3)
                self.assertEqual({m.field: m.value for m in row.metrics}, {'call_count': 2, 'running_time(us)': 3})
                self.assertEqual(row.source_context.status, 'unreadable')
                self.assertEqual(row.source_context.source_file, filename)
                self.assertEqual(row.source_context.line, 1)
                self.assertTrue(row.source_context.reason)
                self.assertEqual(row.identity_source.record, 2)
                self.assertEqual(path.read_bytes(), raw)
                self.assertIsNotNone(RunEvidence.load(self.root).summary())

    def test_source_stat_and_read_errors_stay_local(self):
        self.write('reports/OPPROF_001/simulator/core0_code_exe.csv',
                   'code,call_count,running_time(us)\nkernel.cpp:1,2,3\n')
        source = self.write('kernel.cpp', 'void kernel() {}\n')
        for operation in ('stat', 'read_text'):
            original = getattr(Path, operation)
            def fail(path, *args, **kwargs):
                if path == source:
                    raise PermissionError('source access denied')
                return original(path, *args, **kwargs)
            with self.subTest(operation=operation), mock.patch.object(Path, operation, fail):
                model = build_simulator_hotspot_model(self.root)
            self.assertEqual(model.source_lines[0].source_context.status, 'unreadable')
            self.assertEqual(model.source_lines[0].primary_metric.value, 3)

    def test_bad_stdout_ordinals_preserve_siblings_timing_and_located_warnings(self):
        limit = getattr(sys, 'get_int_max_str_digits', lambda: 0)()
        if not limit:
            self.skipTest('interpreter has no integer string conversion limit')
        self.write('reports/app/PROF_001/op_summary_001.csv', 'Op Name,Task Duration(us)\nkernel,3\n')
        for section, stem, key in (('Occupancy', 'msprof_occupancy', 'occupancy_summary'),
                                   ('Performance', 'msprof_op', 'performance_summary')):
            for sibling in (False, True):
                with self.subTest(section=section, sibling=sibling):
                    path = self.write(f'logs/{stem}.stdout', f'[INFO] {section} Summary Report:\n'
                        + '9' * (limit + 1) + ') invalid ordinal\n'
                        + ('2) valid observation\n' if sibling else ''))
                    raw = path.read_bytes()
                    result = write_evidence_model(self.root)
                    loaded = RunEvidence.load(self.root).summary()
                    self.assertEqual(loaded.headlines['op_summary'].observation.value, 3)
                    messages = getattr(loaded.stdout_sections, key)
                    self.assertEqual([m.message for m in messages.messages] if messages else [],
                                     ['valid observation'] if sibling else [])
                    self.assertTrue(any(f'logs/{stem}.stdout:2' in w and 'ordinal' in w and section in w
                                        for w in loaded.warnings))
                    self.assertEqual(loaded.warnings, result.summary.warnings)
                    self.assertIn(f'logs/{stem}.stdout:2', build_report(loaded, self.root))
                    self.assertEqual(path.read_bytes(), raw)
            fallback = self.write('logs/msprof_z_valid.stdout', f'[INFO] {section} Summary Report:\n3) fallback observation\n')
            path.write_text(f'[INFO] {section} Summary Report:\n' + '9' * (limit + 1) + ') bad\n')
            loaded = write_evidence_model(self.root).summary
            self.assertEqual(getattr(loaded.stdout_sections, key).source, 'logs/msprof_z_valid.stdout')
            fallback.unlink()
            path.unlink()

    def test_timeline_rejects_non_numeric_or_nonfinite_durations_with_exact_paths(self):
        for wrapper in ('', 'traceEvents', 'events', 'data'):
            for field in ('dur', 'duration', 'Duration'):
                for token in ('1e309', '"NaN"', 'true', '"3"', '1' + '0' * 400):
                    with self.subTest(wrapper=wrapper, field=field, token=token[:20]):
                        events = '[{"name":"bad","ph":"X","tid":0,"' + field + '":' + token + '},' + \
                                 '{"name":"valid","ph":"X","tid":0,"dur":3},{"name":"instant","ph":"i"}]'
                        path = self.write('reports/OPPROF_001/simulator/trace.json',
                                          '{"' + wrapper + '":' + events + '}' if wrapper else events)
                        raw = path.read_bytes()
                        with contextlib.redirect_stdout(io.StringIO()):
                            timeline(['--run-dir', str(self.root), '--top', '1'])
                        rendered = (self.root / 'analysis/timeline.txt').read_text()
                        self.assertIn('| 3 | trace.json | valid |', rendered)
                        self.assertNotIn('| bad |', rendered)
                        self.assertIn(f'{wrapper}[0].{field}', rendered)
                        self.assertIn('reports/OPPROF_001/simulator/trace.json', rendered)
                        self.assertNotIn('[2]', rendered)
                        if wrapper in ('', 'traceEvents') and field == 'dur':
                            model = build_simulator_hotspot_model(self.root)
                            self.assertEqual([row.value for row in model.pipeline_events], [3])
                            self.assertIn(f'{wrapper}[0].dur', [issue.source.field for item in model.inputs
                                                              for issue in item.issues])
                        self.assertEqual(path.read_bytes(), raw)

    def test_timeline_keeps_valid_aliases_and_diagnostics_outside_top_limit(self):
        self.write('reports/OPPROF_001/simulator/trace.json', json.dumps({'traceEvents': [
            {'name': 'largest', 'dur': 3.5}, {'name': 'duration_alias', 'duration': 2},
            {'name': 'uppercase_alias', 'Duration': 1}, {'name': 'zero', 'dur': 0},
            {'name': 'invalid_first_alias', 'dur': True, 'duration': 100},
        ]}))
        self.write('reports/app/PROF_001/msprof_broken.json', '{')
        for top in (1, 10):
            with self.subTest(top=top), contextlib.redirect_stdout(io.StringIO()):
                timeline(['--run-dir', str(self.root), '--top', str(top)])
            rendered = (self.root / 'analysis/timeline.txt').read_text()
            self.assertIn('| 3.5 | trace.json | largest |', rendered)
            self.assertIn('traceEvents[4].dur', rendered)
            self.assertIn('reports/app/PROF_001/msprof_broken.json: ERROR:', rendered)
            self.assertNotIn('| invalid_first_alias |', rendered)
            self.assertNotIn('| msprof_broken.json |', rendered)
            if top == 10:
                for value, name in ((2, 'duration_alias'), (1, 'uppercase_alias'), (0, 'zero')):
                    self.assertIn(f'| {value} | trace.json | {name} |', rendered)

    def test_accepted_integers_survive_json_and_text_consumers(self):
        for kind in ('simulator', 'operator'):
            for number in (8, 10**400):
                with self.subTest(kind=kind, digits=len(str(number))):
                    if kind == 'simulator':
                        path = self.write('reports/OPPROF_001/simulator/core0_code_exe.csv',
                            f'code,call_count,cycles,running_time(us)\nkernel.cpp:1,{number},{number},3\n')
                        model = build_simulator_hotspot_model(self.root)
                        loaded = SimulatorModel.model_validate_json(model.model_dump_json())
                        rendered = render_simulator(loaded, 20)
                        self.assertIn('running_time(us): 3 us', rendered)
                    else:
                        path = self.write('reports/op/OPPROF_001/OpBasicInfo.csv',
                            f'Op Name,Block Dim,Task Duration(us)\nkernel,{number},3\n')
                        summary = write_evidence_model(self.root).summary
                        loaded = type(summary).model_validate_json(summary.model_dump_json())
                        rendered = build_report(loaded, self.root)
                        self.assertEqual(loaded.headlines['op_basic_info'].observation.value, 3)
                    self.assertIn(str(number), rendered)
                    path.unlink()
