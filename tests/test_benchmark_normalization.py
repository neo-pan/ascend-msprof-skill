"""Natural measurement boundaries, partial evidence, and source replay."""
import copy
import json
import tempfile
from pathlib import Path
from unittest import mock

from tests.helpers_shared import unittest
from pydantic import ValidationError
from ascend_msprof_skill.artifact_reader import decode_json
from ascend_msprof_skill.benchmark_evidence import ARTIFACT, BenchmarkEvidence, load_benchmark, validate_measurement
from ascend_msprof_skill.benchmark_types import BenchmarkContext, BenchmarkRecord, BenchmarkSource
from ascend_msprof_skill.collect_benchmark_context import import_benchmark
from ascend_msprof_skill.run_assessment import _performance

EXAMPLE = Path(__file__).resolve().parents[1] / 'skills/ascend-msprof-skill/assets/benchmark-single-case.json'


class BenchmarkNormalizationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.run = self.root / 'run'
        self.input = self.root / 'input.json'
        self.data = json.loads(EXAMPLE.read_text())
        self.source = BenchmarkSource(artifact='context/input.json', sha256='0' * 64, entrypoints=('test',))

    def write(self):
        self.input.write_text(json.dumps(self.data, allow_nan=False))
        return import_benchmark(self.run, self.input)

    def test_empty_tensor_lists_have_the_same_raw_and_normalized_constraint(self):
        valid, issues = validate_measurement(self.data['assessment'], self.source)
        self.assertFalse(issues)
        for field in ('inputs', 'outputs'):
            raw = copy.deepcopy(self.data['assessment'])
            raw[field] = []
            record, issues = validate_measurement(raw, self.source)
            self.assertIsNone(getattr(record, field))
            self.assertTrue(any(issue.id == field and issue.status == 'invalid' for issue in issues))
            normalized = valid.model_dump(mode='json')
            normalized[field] = []
            with self.subTest(field=field), self.assertRaises(ValidationError):
                BenchmarkRecord.model_validate(normalized)

    def test_overflowing_raw_component_retains_independent_correctness_and_exact_citation(self):
        raw = json.dumps(self.data).replace('"value_ms": 1.25', '"value_ms": 1e309').encode()
        self.assertIn(b'1e309', raw)
        self.input.write_bytes(raw)
        evidence = import_benchmark(self.run, self.input)
        self.assertIsNotNone(evidence.record)
        self.assertIsNone(evidence.record.measurement.value_ms)
        self.assertEqual(evidence.record.measurement.statistic, 'mean')
        self.assertEqual(evidence.record.measurement.sample_count, self.data['assessment']['measurement']['sample_count'])
        self.assertTrue(evidence.correctness()[0])
        self.assertEqual([issue.id for issue in evidence.issues], ['measurement.value_ms'])
        self.assertEqual(evidence.issues[0].sources[0].field_ref, 'assessment.measurement.value_ms')
        snapshot = self.run / evidence.sources[0].artifact
        self.assertEqual(snapshot.read_bytes(), raw)
        self.assertEqual(load_benchmark(self.run), evidence)
        self.assertEqual(_performance(evidence, None).eligibility.status, 'blocked')
        json.dumps(evidence.model_dump(mode='json'), allow_nan=False)

    def test_invalid_build_json_does_not_discard_subject_identity(self):
        raw = copy.deepcopy(self.data['assessment'])
        raw['subject']['build']['extra'] = float('inf')
        record, issues = validate_measurement(raw, self.source)
        self.assertEqual(record.subject_id, raw['subject']['implementation']['id'])
        self.assertIsNone(record.subject.build)
        self.assertTrue(any(issue.id.startswith('subject.build') for issue in issues))
        self.assertFalse(any(issue.id in ('', 'subject', 'subject.implementation') for issue in issues))

    def test_partial_measurement_and_subject_keep_independent_facts(self):
        record = self.data['assessment']
        record['measurement']['sample_count'] = True
        record['subject']['build'] = 'invalid'
        evidence = self.write()
        self.assertEqual(evidence.record.measurement.value_ms, 1.25)
        self.assertIsNone(evidence.record.measurement.sample_count)
        self.assertIsNone(evidence.record.subject.build)
        self.assertEqual(evidence.record.subject_id, record['subject']['implementation']['id'])
        self.assertTrue(evidence.correctness()[0])
        self.assertEqual(_performance(evidence, None).eligibility.status, 'blocked')
        self.assertEqual(BenchmarkEvidence.model_validate(evidence.model_dump(mode='json')), evidence)
        self.assertEqual(load_benchmark(self.run), evidence)

    def test_bad_timing_or_protocol_does_not_undo_correctness(self):
        for field in ('measurement', 'protocol'):
            data = copy.deepcopy(self.data['assessment'])
            data[field] = {'bad': True}
            record, issues = validate_measurement(data, self.source)
            evidence = BenchmarkEvidence(record=record, records=(record,), sources=(self.source,), issues=tuple(issues))
            self.assertTrue(evidence.correctness()[0])
            self.assertNotEqual(_performance(evidence, None).eligibility.status, 'eligible')

    def test_correctness_failure_retains_point_estimate(self):
        self.data['assessment']['correctness']['status'] = 'fail'
        evidence = self.write()
        self.assertFalse(evidence.correctness()[0])
        self.assertEqual(evidence.record.measurement.value_ms, 1.25)
        self.assertEqual(_performance(evidence, None).eligibility.status, 'blocked')

    def test_failure_message_errors_preserve_the_independent_stage(self):
        for stage in ('compile', 'correctness', 'timing'):
            for message in (None, True, ''):
                with self.subTest(stage=stage, message=message):
                    data = copy.deepcopy(self.data['assessment'])
                    data['failure'] = {'stage': stage, 'message': message}
                    record, issues = validate_measurement(data, self.source)
                    evidence = BenchmarkEvidence(record=record, records=(record,), sources=(self.source,), issues=tuple(issues))
                    self.assertEqual(record.failure.stage, stage)
                    self.assertIsNone(record.failure.message)
                    self.assertEqual(evidence.correctness()[0], stage == 'timing')
                    self.assertEqual(_performance(evidence, None).eligibility.status, 'blocked')
                    self.assertIn('failure.message', {item.id for item in issues})
                    self.assertEqual(BenchmarkEvidence.model_validate(evidence.model_dump(mode='json')), evidence)

    def test_import_confines_outputs_before_writing_any_snapshot(self):
        outside = self.root / 'outside'
        outside.mkdir()
        for folder in ('context/benchmark-inputs', 'analysis'):
            with self.subTest(folder=folder):
                run = self.root / folder.replace('/', '-')
                link = run / folder
                link.parent.mkdir(parents=True)
                link.symlink_to(outside, target_is_directory=True)
                with self.assertRaises(ValueError):
                    import_benchmark(run, EXAMPLE)
                self.assertEqual(list(outside.iterdir()), [])
                self.assertFalse((run / ARTIFACT).exists())

    def test_boolean_case_counts_are_rejected_before_single_case_policy(self):
        for field in ('workload', 'correctness'):
            data = copy.deepcopy(self.data['assessment'])
            data[field]['case_count'] = True
            record, issues = validate_measurement(data, self.source)
            self.assertTrue(any(item.id == f'{field}.case_count' and item.status == 'invalid' for item in issues))
            self.assertIsNone(getattr(record, field))

    def test_duplicate_keys_and_nonstandard_constants_reject_import_without_snapshot(self):
        raw = json.dumps(self.data)
        cases = [raw.replace('"value_ms": 1.25', '"value_ms": 99, "value_ms": 1.25')]
        cases.extend(raw.replace('"value_ms": 1.25', f'"value_ms": {token}') for token in ('NaN', 'Infinity', '-Infinity'))
        cases.append(raw.replace('"value_ms": 1.25', '"value_ms": 1.25, "samples_ms": [NaN]'))
        for text in cases:
            with self.subTest(text=text):
                self.input.write_text(text)
                with self.assertRaises(ValueError):
                    import_benchmark(self.run, self.input)
                self.assertFalse(self.run.exists())
                self.assertEqual(self.input.read_text(), text)

    def test_legal_samples_stay_raw_and_do_not_change_semantic_identity(self):
        first = self.write()
        original = self.input.read_bytes()
        self.data['assessment']['measurement']['samples_ms'] = [None, False, -4, {'opaque': True}]
        second = self.write()
        self.assertEqual(len(second.records), 1)
        self.assertEqual(first.record, second.record)
        self.assertNotIn('samples_ms', second.record.model_dump(mode='json')['measurement'])
        self.assertEqual((self.run / first.sources[0].artifact).read_bytes(), original)
        self.assertEqual((self.run / second.sources[-1].artifact).read_bytes(), self.input.read_bytes())

    def test_raw_extensions_remain_in_snapshot_without_disabling_known_facts(self):
        baseline = self.write()
        record = self.data['assessment']
        record['producer']['description'] = 'caller extension'
        record['correctness']['reference']['description'] = {'document': 'caller reference notes'}
        record['protocol']['timer']['clock_domain'] = 'caller extension'
        record['inputs'][0]['annotation'] = 'caller extension'
        evidence = self.write()
        self.assertEqual(evidence.record, baseline.record)
        self.assertTrue(evidence.correctness()[0])
        self.assertEqual(evidence.issues, ())
        self.assertEqual(_performance(evidence, None).eligibility.status, 'eligible')
        snapshot = self.run / evidence.sources[-1].artifact
        self.assertEqual(snapshot.read_bytes(), self.input.read_bytes())
        self.assertIn('description', json.loads(snapshot.read_text())['assessment']['correctness']['reference'])

    def test_import_decodes_new_snapshot_once_and_replay_reads_each_once(self):
        self.input.write_text(json.dumps(self.data))
        with mock.patch('ascend_msprof_skill.collect_benchmark_context.decode_json', wraps=decode_json) as incoming, \
             mock.patch('ascend_msprof_skill.benchmark_evidence.decode_json', wraps=decode_json) as replay:
            evidence = import_benchmark(self.run, self.input)
        self.assertEqual(incoming.call_count, 1)
        self.assertEqual(replay.call_count, 0)
        reads = []
        original = Path.read_bytes
        def record_read(path):
            reads.append(path)
            return original(path)
        with mock.patch.object(Path, 'read_bytes', record_read), \
             mock.patch('ascend_msprof_skill.benchmark_evidence.decode_json', wraps=decode_json) as replay:
            self.assertEqual(load_benchmark(self.run), evidence)
        self.assertEqual(reads, [self.run / evidence.sources[0].artifact])
        self.assertEqual(replay.call_count, 1)

    def test_cached_measurement_is_not_replay_authority(self):
        expected = self.write()
        path = self.run / ARTIFACT
        payload = json.loads(path.read_text())
        self.assertEqual(BenchmarkContext.model_validate(payload), expected.as_context())
        payload.update(measurement={'wrong': True}, issues='stale display')
        path.write_text(json.dumps(payload))
        self.assertEqual(load_benchmark(self.run), expected)

    def test_registration_and_snapshot_errors_block_all_uses(self):
        evidence = self.write()
        path = self.run / ARTIFACT
        original = json.loads(path.read_text())
        for change in ('digest', 'path', 'version', 'duplicate'):
            payload = copy.deepcopy(original)
            if change == 'digest':
                payload['imports'][0]['sha256'] = True
            elif change == 'path':
                payload['imports'][0]['artifact'] = '../outside.json'
            elif change == 'version':
                payload['schema_version'] = '1.0'
            raw = json.dumps(payload)
            if change == 'duplicate':
                raw = raw.replace('"imports":', '"imports": [], "imports":', 1)
            path.write_text(raw)
            loaded = load_benchmark(self.run)
            self.assertFalse(loaded.correctness()[0])
            self.assertEqual(_performance(loaded, None).eligibility.status, 'blocked')
        path.write_text(json.dumps(original))
        snapshot = self.run / evidence.sources[0].artifact
        outside = self.root / 'outside.json'
        outside.write_bytes(snapshot.read_bytes())
        snapshot.unlink()
        snapshot.symlink_to(outside)
        loaded = load_benchmark(self.run)
        self.assertFalse(loaded.correctness()[0])
        self.assertEqual(loaded.issues[0].reason_code, 'source_unreadable')

    def test_input_union_errors_cite_raw_field_without_schema_tag(self):
        data = self.data['assessment']
        data['input_identity'] = {'kind': 'digest', 'sha256': True}
        record, issues = validate_measurement(data, self.source)
        self.assertIsNone(record.input_identity)
        self.assertEqual([item.id for item in issues], ['input_identity.sha256'])
        self.assertEqual(issues[0].sources[0].field_ref, 'assessment.input_identity.sha256')

    def test_normalized_record_rejects_scalar_coercion_and_extra_fields(self):
        evidence = self.write()
        for field, value in (('value_ms', True), ('sample_count', '100')):
            payload = evidence.record.model_dump(mode='json')
            payload['measurement'][field] = value
            with self.assertRaises(ValidationError):
                BenchmarkRecord.model_validate(payload)
        payload = evidence.record.model_dump(mode='json')
        payload['measurement']['samples_ms'] = [1]
        with self.assertRaises(ValidationError):
            BenchmarkRecord.model_validate(payload)
