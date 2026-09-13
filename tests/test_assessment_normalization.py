"""Assessment output composition, invariants, schemas and model consumers."""
import copy
import json
import tempfile
from pathlib import Path
from unittest import mock

from tests.helpers_shared import unittest
from pydantic import ValidationError
from ascend_msprof_skill.assessment_types import CandidateSummary, ComparisonSummary, RunAssessment, HeadlineComparison, BenchmarkAssociation
from ascend_msprof_skill.benchmark_types import BenchmarkContext
from ascend_msprof_skill.collect_benchmark_context import import_benchmark
from ascend_msprof_skill.compare_runs import build_comparison, render_markdown as render_comparison
from ascend_msprof_skill.summarize_candidate import build_candidate_summary, render_markdown
from ascend_msprof_skill._headline_comparison import compare_numeric

ROOT = Path(__file__).resolve().parents[1]


class AssessmentNormalizationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.a, self.b = self.root / 'a', self.root / 'b'
        self.data = json.loads((ROOT / 'skills/ascend-msprof-skill/assets/benchmark-single-case.json').read_text())

    def write(self, run, data=None):
        source = self.root / f'{run.name}.json'
        source.write_text(json.dumps(data or self.data, allow_nan=False))
        return import_benchmark(run, source)

    def test_full_model_json_roundtrips_and_renderers_consume_without_io(self):
        self.write(self.a)
        self.write(self.b)
        comparison = build_comparison(self.a, self.b)
        candidate = build_candidate_summary(self.b, self.a)
        self.assertEqual(candidate.performance_assessment, comparison.performance_assessment)
        self.assertEqual(candidate.mechanism_assessment, comparison.mechanism_assessment)
        for model in (comparison, candidate):
            encoded = json.dumps(model.model_dump(mode='json'), allow_nan=False)
            self.assertEqual(type(model).model_validate(json.loads(encoded)), model)
        with mock.patch.object(Path, 'open', side_effect=AssertionError('rendering read a file')):
            self.assertIn('Observed in these caller-provided measurements', render_comparison(comparison))
            self.assertIn('## Evidence Questions', render_markdown(candidate))

    def test_missing_fields_cannot_be_promoted_by_forging_eligibility_checks(self):
        del self.data['assessment']['protocol']['synchronization']
        self.write(self.b)
        model = build_candidate_summary(self.b)
        self.assertEqual(model.performance_assessment.eligibility.status, 'incomplete')
        payload = model.model_dump(mode='json')
        payload['performance_assessment']['eligibility'] = {'status': 'eligible', 'checks': [], 'reasons': []}
        with self.assertRaises(ValidationError):
            CandidateSummary.model_validate(payload)

    def test_forged_observations_conditions_and_role_composition_are_rejected(self):
        self.write(self.a)
        self.write(self.b)
        model = build_comparison(self.a, self.b)
        for change in ('delta', 'condition', 'mode', 'role', 'coverage', 'finding', 'question', 'source', 'missing_sources'):
            payload = model.model_dump(mode='json')
            if change == 'delta':
                payload['performance_assessment']['comparison']['observation']['delta_ms'] = 99.0
            elif change == 'condition':
                payload['performance_assessment']['measurements']['candidate']['record']['protocol']['synchronization'] = 'other'
            elif change == 'mode':
                payload['mechanism_assessment']['mode'] = 'single_run'
            elif change == 'role':
                del payload['runs']['baseline']
            elif change == 'coverage':
                payload['mechanism_assessment']['coverage'] = 'available'
            elif change == 'finding':
                payload['mechanism_assessment']['findings'].append({'kind': 'metric_observation', 'evidence_level': 'descriptive', 'group': 'memory', 'evidence': []})
            elif change == 'source':
                payload['performance_assessment']['comparison']['observation']['sources'][0]['artifact'] = 'unrelated.json'
            elif change == 'missing_sources':
                payload['performance_assessment']['measurements']['candidate']['sources'] = []
            else:
                payload['mechanism_assessment']['questions'][0]['status'] = 'available'
            with self.subTest(change=change), self.assertRaises(ValidationError):
                ComparisonSummary.model_validate(payload)

    def test_observed_and_numeric_headlines_require_the_same_admission_as_generation(self):
        fixture = ROOT / 'tests/fixtures/tilelang_design_feedback/candidate_comparability/baseline/analysis/candidate_summary.json'
        model = CandidateSummary.model_validate(json.loads(fixture.read_text()))
        observed = next(row for row in model.mechanism_assessment.headlines if row.status == 'observed')
        for field in ('value', 'target_identity', 'field', 'field_kind', 'name', 'segment', 'metric_scope', 'block_scope'):
            payload = model.model_dump(mode='json')
            row = next(row for row in payload['mechanism_assessment']['headlines'] if row['status'] == 'observed')
            row['candidate'][field] = None
            with self.subTest(field=field), self.assertRaises(ValidationError):
                CandidateSummary.model_validate(payload)
        paired = HeadlineComparison(group=observed.group, status='same', a=observed.candidate,
            b=observed.candidate, numeric=True, delta=0.0, delta_pct=0.0,
            checks=tuple(dict(id=f'segment.{observed.candidate.segment}.{key}', title=key, status='match',
                              a={'value': 'same', 'source': None}, b={'value': 'same', 'source': None})
                         for key in ('output', 'command')))
        for field in ('target_identity', 'block_scope', 'field'):
            payload = paired.model_dump(mode='json')
            payload['b'][field] = None
            with self.subTest(paired_field=field), self.assertRaises(ValidationError):
                HeadlineComparison.model_validate(payload)

    def test_linked_association_requires_subject_and_all_recorded_workload_checks(self):
        def check(name, status='match'):
            value = 'other' if status == 'mismatch' else 'same'
            sources = [{'value': value, 'source': {'artifact': 'analysis/profile_context.json', 'field_ref': name}}]
            if status == 'conflict':
                sources.append({'value': 'other', 'source': {'artifact': 'analysis/tilelang_context.json', 'field_ref': name}})
                value = None
            return dict(id=name, status=status, benchmark='same', profiler=value,
                        sources=sources if name.startswith('benchmark_workload.') else [])
        checks = [check('benchmark_subject'), *(check(f'benchmark_workload.{field}')
                  for field in ('id', 'shape', 'dtype', 'case_count'))]
        payload = dict(role='candidate', status='linked', checks=checks, limitation=None)
        BenchmarkAssociation.model_validate(payload)
        # Matching either implementation remains enough: payload and harness differ.
        BenchmarkAssociation.model_validate({**payload, 'checks': [*checks, check('benchmark_subject', 'mismatch')]})
        for incomplete in ([], checks[1:], checks[:-1], [*checks[:-1], check('benchmark_workload.case_count', 'conflict')]):
            with self.subTest(checks=incomplete), self.assertRaises(ValidationError):
                BenchmarkAssociation.model_validate({**payload, 'checks': incomplete})
        self.write(self.b)
        candidate = build_candidate_summary(self.b).model_dump(mode='json')
        candidate['mechanism_assessment']['benchmark_association'][0].update(status='linked', checks=[])
        with self.assertRaises(ValidationError):
            CandidateSummary.model_validate(candidate)

    def test_normalized_eligible_records_reject_empty_tensor_lists(self):
        self.write(self.b)
        model = build_candidate_summary(self.b)
        self.assertEqual(model.performance_assessment.eligibility.status, 'eligible')
        for field in ('inputs', 'outputs'):
            payload = model.model_dump(mode='json')
            payload['performance_assessment']['measurements']['candidate']['record'][field] = []
            with self.subTest(field=field), self.assertRaises(ValidationError):
                CandidateSummary.model_validate(payload)

    def test_nonfinite_deltas_never_become_observations(self):
        data = copy.deepcopy(self.data)
        data['assessment']['measurement']['value_ms'] = 5e-324
        self.write(self.a, data)
        self.write(self.b)
        model = build_comparison(self.a, self.b)
        self.assertEqual(model.performance_assessment.eligibility.status, 'blocked')
        self.assertIsNone(model.performance_assessment.comparison.observation)
        self.assertIn('nonfinite_delta', {check.reason_code for check in model.performance_assessment.eligibility.checks})
        self.assertEqual(compare_numeric(-1e308, 1e308), (None, None, False))
        self.assertEqual(compare_numeric(0.0, 1.0), (1.0, None, True))
        json.dumps(model.model_dump(mode='json'), allow_nan=False)

    def test_published_schemas_come_from_authoritative_models(self):
        folder = ROOT / 'skills/ascend-msprof-skill/data'
        for name, model in (('benchmark-context', BenchmarkContext), ('run-assessment', RunAssessment),
                            ('candidate-summary', CandidateSummary), ('comparison', ComparisonSummary)):
            with self.subTest(name=name):
                self.assertEqual(json.loads((folder / f'{name}.schema.json').read_text()), model.model_json_schema())
