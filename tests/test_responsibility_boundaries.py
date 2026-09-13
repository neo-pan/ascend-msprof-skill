"""Regressions across normalization, persisted admission and report projection."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError
from tests import test_headline_comparison as headlines
from tests import test_assessment_normalization as assessments
from ascend_msprof_skill.assessment_types import ComparisonSummary, BenchmarkAssociation, CandidateSummary
from ascend_msprof_skill.compare_runs import build_comparison
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.run_evidence import RunEvidence
from ascend_msprof_skill.simulator_hotspot_model import build_simulator_hotspot_model
from ascend_msprof_skill.simulator_types import SimulatorModel
from ascend_msprof_skill.profile_harness import ProfileHarnessArtifacts, load_verify_json
from ascend_msprof_skill.prepare_tilelang_profile_run import prepare_profile_run
from ascend_msprof_skill.summarize_candidate import build_candidate_summary
from ascend_msprof_skill.collect_tilelang_context import sanitize_value
from ascend_msprof_skill.generate_report import build_report


class ResponsibilityBoundaryTests(unittest.TestCase):
    def fixture(self, cls):
        case = cls()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def test_persisted_workload_checks_follow_observations_and_values(self):
        case = self.fixture(headlines.HeadlineComparisonTests)
        original = case.comparison()
        for mutation in ('value', 'observations', 'both', 'conflict', 'missing_side'):
            payload = copy.deepcopy(original)
            check = payload['mechanism_assessment']['workload_checks'][0]
            if mutation in ('value', 'both'):
                check['b'] = 'other'
            if mutation in ('observations', 'both'):
                check['sources']['b'][0]['value'] = 'other'
            if mutation == 'conflict':
                observation = copy.deepcopy(check['sources']['b'][0])
                observation['value'] = 'other'
                check['sources']['b'].append(observation)
            if mutation == 'missing_side':
                del check['sources']['b']
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                ComparisonSummary.model_validate(payload)

    def test_numeric_requires_each_scope_check_once(self):
        case = self.fixture(headlines.HeadlineComparisonTests)
        original = case.comparison()
        for group in ('workload', 'compatibility', 'segment'):
            for mutation in ('empty', 'delete', 'duplicate', 'wrong_segment'):
                if mutation == 'wrong_segment' and group != 'segment':
                    continue
                payload = copy.deepcopy(original)
                mechanism = payload['mechanism_assessment']
                checks = (mechanism['workload_checks'] if group == 'workload' else
                          mechanism['compatibility']['checks'] if group == 'compatibility' else
                          headlines.pipe_row(payload)['checks'])
                if mutation == 'empty':
                    checks.clear()
                    if group == 'compatibility':
                        mechanism['compatibility']['status'] = 'not_applicable'
                elif mutation == 'delete':
                    checks.pop(0)
                elif mutation == 'duplicate':
                    checks.append(copy.deepcopy(checks[0]))
                else:
                    checks[0]['id'] = 'segment.app.output'
                with self.subTest(group=group, mutation=mutation), self.assertRaises(ValidationError):
                    ComparisonSummary.model_validate(payload)

    def test_association_values_and_workload_observations_authorize_link(self):
        source = {'artifact': 'analysis/profile_context.json', 'field_ref': 'benchmark.workload.id'}
        checks = [{'id': 'benchmark_subject', 'status': 'match', 'benchmark': 'one', 'profiler': 'one',
                   'sources': [source]}]
        checks += [{'id': f'benchmark_workload.{field}', 'status': 'match', 'benchmark': 'one',
                    'profiler': 'one', 'sources': [{'value': 'one', 'source': source}]}
                   for field in ('id', 'shape', 'dtype', 'case_count')]
        payload = {'role': 'candidate', 'status': 'linked', 'checks': checks, 'limitation': None}
        BenchmarkAssociation.model_validate(payload)
        for index in range(len(checks)):
            changed = copy.deepcopy(payload)
            changed['checks'][index]['profiler'] = 'another'
            with self.subTest(index=index), self.assertRaises(ValidationError):
                BenchmarkAssociation.model_validate(changed)
        for mutation in ('duplicate', 'missing', 'conflict'):
            changed = copy.deepcopy(payload)
            if mutation == 'duplicate':
                changed['checks'].append(copy.deepcopy(checks[-1]))
            elif mutation == 'missing':
                changed['checks'][-1]['sources'] = []
            else:
                changed['checks'][-1]['sources'].append({'value': 'other', 'source': source})
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                BenchmarkAssociation.model_validate(changed)
        # An unrelated harness mismatch does not undo a matching payload.
        payload['checks'].append({**checks[0], 'profiler': 'harness', 'status': 'mismatch'})
        BenchmarkAssociation.model_validate(payload)

    def test_performance_conditions_are_projected_from_records(self):
        case = self.fixture(assessments.AssessmentNormalizationTests)
        case.write(case.a)
        case.write(case.b)
        original = build_comparison(case.a, case.b).model_dump(mode='json')
        for mutation in ('value', 'consistent_but_wrong_values', 'delete', 'duplicate', 'numeric_type'):
            payload = copy.deepcopy(original)
            checks = payload['performance_assessment']['eligibility']['checks']
            check = next(item for item in checks if item['id'] == 'workload.id')
            if mutation == 'value':
                check['candidate'] = 'other'
            elif mutation == 'consistent_but_wrong_values':
                check['candidate'] = check['baseline'] = 'other'
            elif mutation == 'delete':
                checks.remove(check)
            elif mutation == 'duplicate':
                checks.append(copy.deepcopy(check))
            else:
                check = next(item for item in checks if item['id'] == 'workload.case_count')
                check['candidate'] = True
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                ComparisonSummary.model_validate(payload)
        payload = copy.deepcopy(original)
        payload['performance_assessment']['eligibility']['checks'].reverse()
        ComparisonSummary.model_validate(payload)

    def test_scientific_record_conditions_block_generation_and_forged_eligibility(self):
        case = self.fixture(assessments.AssessmentNormalizationTests)
        for mutation in ('contract', 'workload_cases', 'natural', 'correctness', 'subject', 'correctness_cases',
                         'duplicate_input', 'duplicate_output', 'timing_failure', 'compile_failure'):
            data = copy.deepcopy(case.data)
            record = data['assessment']
            if mutation == 'contract':
                record['contract_version'] = 'other'
            elif mutation == 'workload_cases':
                record['workload']['case_count'] = 2
            elif mutation == 'natural':
                record['protocol']['natural'] = False
            elif mutation == 'correctness':
                record['correctness']['status'] = 'fail'
            elif mutation == 'subject':
                record['correctness']['subject_id'] = 'other'
            elif mutation == 'correctness_cases':
                record['correctness']['case_count'] = 2
            elif mutation.startswith('duplicate_'):
                field = 'inputs' if mutation == 'duplicate_input' else 'outputs'
                record[field].append(copy.deepcopy(record[field][0]))
            else:
                record['failure'] = {'stage': 'timing' if mutation == 'timing_failure' else 'compile', 'message': 'failed'}
            run = case.root / mutation
            case.write(run, data)
            payload = build_candidate_summary(run).model_dump(mode='json')
            self.assertEqual(payload['performance_assessment']['eligibility']['status'], 'blocked')
            payload['performance_assessment']['eligibility'] = {'status': 'eligible', 'checks': [], 'reasons': []}
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                CandidateSummary.model_validate(payload)

    def test_context_projection_is_independent_of_warning_collection(self):
        raw = {'samples': [1, float('inf'), 3], 'correctness': True, 'nested': {'bad': float('-inf')}}
        warnings = []
        expected = {'samples': [1, None, 3], 'correctness': True, 'nested': {'bad': None}}
        self.assertEqual(sanitize_value(raw), expected)
        self.assertEqual(sanitize_value(raw, warnings), expected)
        self.assertTrue(any('samples[1]' in warning for warning in warnings))
        self.assertTrue(any('nested.bad' in warning for warning in warnings))

    def test_paired_duplicate_tensor_names_preserve_blocked_assessment(self):
        case = self.fixture(assessments.AssessmentNormalizationTests)
        for field in ('inputs', 'outputs'):
            for duplicate_side in ('baseline', 'candidate', 'both'):
                for differing_values in (False, True):
                    with self.subTest(field=field, duplicate_side=duplicate_side, differing_values=differing_values):
                        pair = case.root / f'{field}-{duplicate_side}-{differing_values}'
                        for role in ('baseline', 'candidate'):
                            data = copy.deepcopy(case.data)
                            first = data['assessment'][field][0]
                            second = copy.deepcopy(first)
                            if differing_values:
                                second['shape'][0] += 1
                            if duplicate_side not in (role, 'both'):
                                second['name'] += '_other'
                            data['assessment'][field] = [first, second]
                            case.write(pair / role, data)
                        for model in (build_comparison(pair / 'baseline', pair / 'candidate'),
                                      build_candidate_summary(pair / 'candidate', pair / 'baseline')):
                            performance = model.performance_assessment
                            self.assertEqual(performance.eligibility.status, 'blocked')
                            self.assertEqual(performance.comparison.status, 'not_comparable')
                            self.assertIsNone(performance.comparison.observation)
                            self.assertTrue(any(check.reason_code == 'duplicate_tensor_name'
                                                for check in performance.eligibility.checks))
                            self.assertEqual(type(model).model_validate_json(model.model_dump_json()), model)
                            if duplicate_side == 'both' and differing_values:
                                # Same IDs can describe distinct facts; replacing one by
                                # its sibling must not satisfy the expected multiplicity.
                                payload = model.model_dump(mode='json')
                                checks = payload['performance_assessment']['eligibility']['checks']
                                repeated = [i for i, check in enumerate(checks)
                                            if check['id'].startswith(f'{field}[name=')
                                            and check['id'].endswith('.shape[0]')]
                                self.assertEqual(len(repeated), 2)
                                checks[repeated[0]] = copy.deepcopy(checks[repeated[1]])
                                with self.assertRaises(ValidationError):
                                    type(model).model_validate(payload)

    def test_simulator_integer_failures_preserve_timing_and_raw_input(self):
        limit = getattr(sys, 'get_int_max_str_digits', lambda: 0)()
        if not limit:
            self.skipTest('runtime has no integer string conversion limit')
        token = '9' * (limit + 1)
        for field in ('call_count', 'cycles', 'code'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                path = root / 'reports/OPPROF_001/simulator/core0_code_exe.csv'
                path.parent.mkdir(parents=True)
                path.write_text('code,call_count,cycles,running_time(us)\n'
                    f"kernel.cpp:{token if field == 'code' else '1'},{token if field == 'call_count' else '0'},"
                    f"{token if field == 'cycles' else '2'},3\n")
                raw = path.read_bytes()
                model = build_simulator_hotspot_model(root)
                row = model.source_lines[0]
                self.assertEqual(row.primary_metric.value, 3)
                self.assertTrue(any(issue.source.field == field for issue in model.inputs[0].issues))
                self.assertEqual(SimulatorModel.model_validate_json(model.model_dump_json()), model)
                summary = write_evidence_model(root).summary
                self.assertTrue(any(signal.value == 3 for dimension in summary.analysis_dimensions
                                    if dimension.id == 'source_pipeline_context' for signal in dimension.signals))
                self.assertTrue(RunEvidence.load(root).inspection_targets())
                self.assertEqual(path.read_bytes(), raw)

    def test_writers_preserve_finite_context_and_source_on_overflow(self):
        for entry in ('tilelang', 'harness'):
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                app = root / 'app.py'
                app.write_text('# caller\n')
                source = root / 'verify.json'
                source.write_text('{"compiled":true,"correctness":true,"runtime":1e309,'
                    '"metadata":{"id":"case","shape":[1],"dtype":"float32"}}')
                raw = source.read_bytes()
                run = root / 'run'
                if entry == 'tilelang':
                    path, *_ = prepare_profile_run(run, app, source)
                else:
                    path = ProfileHarnessArtifacts(run).write_profile_context(manifest_path=None, manifest=None,
                        application=app, verify_json_path=source, verify_json=load_verify_json(source))
                payload = json.loads(path.read_text())
                self.assertIsNone(payload['benchmark']['candidate']['runtime'])
                self.assertTrue(payload['benchmark']['correctness']['raw'])
                self.assertEqual(payload['benchmark']['workload']['id'], 'case')
                self.assertTrue(any('runtime' in warning and 'non-finite' in warning for warning in payload['warnings']))
                self.assertTrue(all(path.name in warning for warning in payload['warnings']))
                self.assertEqual(source.read_bytes(), raw)
                source_name = 'benchmark_json' if entry == 'tilelang' else 'verify_json'
                import hashlib
                self.assertEqual(payload['sources'][source_name]['sha256'], hashlib.sha256(raw).hexdigest())
                evidence = RunEvidence.load_assessment(run)
                self.assertEqual(evidence.candidate_context().workload['id'], 'case')

    def test_frequency_and_metadata_projection_use_normalized_facts(self):
        for text in ('Current Freq\n1650\n', 'Metric,Value\nCurrent Freq,1650\n'):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                path = root / 'reports/op/OPPROF_001/OpBasicInfo.csv'
                path.parent.mkdir(parents=True)
                path.write_text(text)
                summary = write_evidence_model(root).summary
                frequency = summary.measurement_quality.frequency
                self.assertEqual(frequency.status, 'observed')
                self.assertEqual(frequency.groups[0].observations[0].current_frequency_mhz, 1650)
                self.assertIn('field=Value' if text.startswith('Metric') else 'field=Current Freq',
                              frequency.groups[0].observations[0].current_frequency_field_ref)
                self.assertIn('1650', build_report(summary, root))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / 'reports/op/OPPROF_001/OpBasicInfo.csv'
            path.parent.mkdir(parents=True)
            path.write_text('Op Name,Block Dim,Task Duration(us)\nkernel,8,12\nkernel,16,20\n')
            summary = write_evidence_model(root).summary
            signals = [s for d in summary.analysis_dimensions for s in d.signals if s.metadata_field == 'Block Dim']
            self.assertEqual([s.signal for s in signals], ['kernel', 'kernel'])
            self.assertEqual([s.metadata_value for s in signals], [8, 16])
            self.assertIn('record=3', signals[1].field_ref)
