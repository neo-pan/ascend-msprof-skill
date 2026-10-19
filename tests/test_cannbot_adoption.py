"""Question-level CANNBot adoption regressions, grounded in saved raw reports."""
import csv
import io
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from tests.helpers_shared import unittest
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.evidence_binding import verify_reference
from ascend_msprof_skill.operator_evidence import field_definition
from ascend_msprof_skill.question_evidence import read_question_from_dir, render_question, main
from ascend_msprof_skill import generate_provenance, generate_report


FIXTURE = Path(__file__).parent / 'fixtures/real_cann852_baseline'
FIELDS = ['aic_mte1_active_bw(GB/s)', 'aic_mte2_active_bw(GB/s)']


class CannbotAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def prepare(self, name):
        run = self.root / name
        shutil.copytree(FIXTURE / name, run)
        write_evidence_model(run)
        return run

    def query(self, run, artifact, fields=FIELDS):
        return read_question_from_dir(run, 'pipe', artifact=artifact, fields=fields)

    def test_existing_evidence_repeated_reads_and_report_start_no_processes(self):
        run = self.prepare('cube_memory_detail')
        artifact = str(next((run / 'reports').rglob('PipeUtilization.csv')).relative_to(run))
        with (mock.patch('subprocess.Popen', side_effect=AssertionError('offline read launched a process')),
              mock.patch('ascend_msprof_skill.generate_provenance.collect_environment',
                         side_effect=AssertionError('offline read queried current environment')),
              mock.patch('sys.stdout', new_callable=io.StringIO)):
            first = self.query(run, artifact)
            second = self.query(run, artifact)
            generate_provenance.main(['--run-dir', str(run)])
            generate_report.main(['--run-dir', str(run)])
        self.assertEqual(first, second)
        self.assertEqual(verify_reference(run, first['facts'][0]['reference'])['status'], 'verified')
        self.assertTrue(first['facts'][0]['selection']['groups'][0]['fields'][FIELDS[1]]['valid'])

    def test_na_and_instrumented_values_keep_raw_oracle_and_conditional_guidance(self):
        for name, expected in [('cube', ['NA', 'NA']),
                               ('cube_memory_detail', ['244.098267', '37.883278'])]:
            with self.subTest(name=name):
                run = self.prepare(name)
                folder = run / ('reports/followups' if name == 'cube' else 'reports/op')
                path = next(folder.rglob('PipeUtilization.csv'))
                with path.open(newline='') as stream:
                    raw_rows = list(csv.DictReader(stream))
                raw = raw_rows[0]
                self.assertEqual([raw[field] for field in FIELDS], expected)
                result = self.query(run, str(path.relative_to(run)))
                fact = result['facts'][0]
                cube = next(g for g in fact['selection']['groups'] if g['scope']['sub_block_id'] == 'cube0')
                notes = [n for n in fact['field_availability'] if n['scope']['sub_block_id'] == 'cube0']
                for field, token, note in zip(FIELDS, expected, notes):
                    counts = cube['fields'][field]
                    if token == 'NA':
                        self.assertEqual(counts['valid'], 0)
                        self.assertGreater(counts['missing'], 0)
                        self.assertIsNone(counts['maximum'])
                        self.assertIn('cause remains unresolved', note['next_step'])
                        self.assertIn('targeted MemoryDetail', note['next_step'])
                    else:
                        values = [float(row[field]) for row in raw_rows if row['sub_block_id'] == 'cube0']
                        self.assertEqual(counts['maximum'], max(values))
                        self.assertEqual(counts['valid'], len(values))
                        self.assertIn('reuse', note['reason'])
                        self.assertNotIn('targeted MemoryDetail', note['next_step'])
                self.assertEqual(fact['field_definitions'][0]['collection_prerequisite']['producer'], 'msprof op')
                self.assertIn('Active pipe time', fact['field_definitions'][0]['denominator'])
                self.assertIn(notes[0]['reason'], render_question(result))

    def test_requested_detail_with_na_does_not_blindly_request_detail_again(self):
        run = self.prepare('cube_memory_detail')
        path = next((run / 'reports').rglob('PipeUtilization.csv'))
        with path.open(newline='') as stream:
            reader = csv.DictReader(stream)
            columns, rows = reader.fieldnames, list(reader)
        for row in rows:
            row[FIELDS[0]] = 'NA'
        with path.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        write_evidence_model(run)
        result = self.query(run, str(path.relative_to(run)), [FIELDS[0]])
        note = next(n for n in result['facts'][0]['field_availability'] if n['scope']['sub_block_id'] == 'cube0')
        self.assertIn('requested', note['next_step'])
        self.assertIn('instrumentation results', note['next_step'])
        self.assertNotIn('targeted MemoryDetail collection', note['next_step'])

    def test_unknown_field_and_other_core_do_not_recommend_instrumentation(self):
        run = self.prepare('vector')
        path = next((run / 'reports').rglob('PipeUtilization.csv'))
        result = self.query(run, str(path.relative_to(run)), FIELDS + ['future_counter'])
        notes = result['facts'][0]['field_availability']
        self.assertTrue(notes)
        for note in notes:
            self.assertNotIn('targeted MemoryDetail', note['next_step'])
            if note['field'] == 'future_counter':
                self.assertIn('definition is unknown', note['reason'])
            else:
                self.assertIn('AIV row', note['reason'])

    def test_cli_and_shared_definition_match_question_guidance(self):
        run = self.prepare('cube_memory_detail')
        artifact = str(next((run / 'reports').rglob('PipeUtilization.csv')).relative_to(run))
        args = ['--run-dir', str(run), '--question', 'pipe', '--artifact', artifact,
                '--field', FIELDS[0], '--format', 'json']
        with mock.patch('sys.stdout', new_callable=io.StringIO) as stream:
            self.assertEqual(main(args), 0)
        cli = json.loads(stream.getvalue())
        fact = cli['facts'][0]
        self.assertEqual(fact['field_definitions'], [field_definition('pipe_utilization', FIELDS[0])])
        self.assertEqual(cli, self.query(run, artifact, [FIELDS[0]]))
        unknown = field_definition('pipe_utilization', 'future_active_bw(GB/s)')
        self.assertFalse(unknown['recognized'])
        self.assertNotIn('collection_prerequisite', unknown)

    def test_failed_segment_does_not_gain_field_facts_from_guidance(self):
        run = self.prepare('cube_memory_detail')
        path = next((run / 'reports').rglob('PipeUtilization.csv'))
        (run / 'logs/msprof_op.result.json').write_text('{"status":"failed"}')
        write_evidence_model(run)
        result = self.query(run, str(path.relative_to(run)))
        self.assertFalse(result['facts'])
        self.assertFalse(result['inventory'][0]['admitted'])
        self.assertEqual(verify_reference(run, result['inventory'][0]['reference'])['status'], 'verified')

    def test_zero_and_invalid_cells_survive_column_reordering(self):
        run = self.prepare('cube_memory_detail')
        path = next((run / 'reports').rglob('PipeUtilization.csv'))
        with path.open(newline='') as stream:
            reader = csv.DictReader(stream)
            columns, rows = reader.fieldnames, list(reader)
        for row in rows:
            if row['sub_block_id'] == 'cube0':
                row[FIELDS[0]], row[FIELDS[1]] = '0', 'bad'
        with path.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(reversed(columns)))
            writer.writeheader()
            writer.writerows(reversed(rows))
        write_evidence_model(run)
        result = self.query(run, str(path.relative_to(run)))
        fact = result['facts'][0]
        notes = {n['field']: n for n in fact['field_availability'] if n['scope']['sub_block_id'] == 'cube0'}
        cube = next(g for g in fact['selection']['groups'] if g['scope']['sub_block_id'] == 'cube0')
        self.assertEqual(cube['fields'][FIELDS[0]]['maximum'], 0)
        self.assertGreater(cube['fields'][FIELDS[0]]['valid'], 0)
        self.assertIn('reuse', notes[FIELDS[0]]['reason'])
        self.assertGreater(cube['fields'][FIELDS[1]]['invalid'], 0)
        self.assertIn('invalid tokens', notes[FIELDS[1]]['reason'])
        self.assertNotIn('targeted MemoryDetail', notes[FIELDS[1]]['next_step'])
