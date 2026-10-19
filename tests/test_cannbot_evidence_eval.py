"""The contributor evaluator cannot turn model text into host execution."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cannbot_eval', REPO / 'scripts/run_cannbot_evidence_eval.py')
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


class EvidenceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'run'
        self.run.mkdir()
        self.tools = evaluation.EvidenceTools(self.run, REPO, {'inputs': []}, self.root)

    def test_unknown_commands_never_spawn_and_are_recorded(self):
        with patch.object(evaluation.subprocess, 'run', side_effect=AssertionError('executed')):
            for command in ('npu-smi info', 'msprof op --application=bad',
                            'ascend-msprof profile-harness --run-dir run',
                            'ascend-msprof evidence --run-dir run ; touch /tmp/sentinel',
                            'ascend-msprof evidence --verify /etc/passwd',
                            'ascend-msprof evidence --run-dir /etc'):
                result = json.loads(self.tools.handle('run_shell', {'command': command}))
                self.assertEqual(result['status'], 'rejected', command)
        calls = [json.loads(line) for line in (self.root/'tool-calls.jsonl').read_text().splitlines()]
        self.assertEqual(len(calls), 6)

    def test_read_pagination_and_escape_rejection(self):
        (self.run/'raw.csv').write_text('a,b\n1,2\n3,4\n')
        result = self.tools.read('workspace', 'raw.csv', offset=1, limit=1)
        self.assertEqual(result['content'], '2: 1,2')
        self.assertEqual(result['next_offset'], 2)
        secret = self.root/'private.txt'
        secret.write_text('private')
        (self.run/'escape').symlink_to(secret)
        for path in ('../private.txt', str(secret), 'escape'):
            result = json.loads(self.tools.handle('read_file', {'root': 'workspace', 'path': path}))
            self.assertEqual(result['status'], 'rejected')

    def test_recorded_actions_require_exact_identity_and_bytes(self):
        import shlex
        request = {'action': 'memory-detail', 'input_identity': self.tools.input_identity}
        command = 'request-evidence '+shlex.quote(json.dumps(request))
        self.assertEqual(self.tools.command(command)['status'], 'unavailable')
        response = self.run/'recorded.json'
        response.write_text('{"origin":"saved","value":7}')
        self.tools.task['recorded_actions'] = [{'request': request, 'response_path': 'recorded.json',
                                              'sha256': evaluation.digest(response)}]
        result = self.tools.command(command)
        self.assertEqual(result['status'], 'recorded')
        self.assertFalse(result['executed'])
        response.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            self.tools.command(command)
        request['input_identity'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            self.tools.command('request-evidence '+shlex.quote(json.dumps(request)))

    def test_budget_rejects_without_reading(self):
        self.tools.max_calls = 0
        result = json.loads(self.tools.handle('read_file', {'root': 'workspace', 'path': 'missing'}))
        self.assertIn('budget exhausted', result['error'])

    def test_large_log_can_be_located_and_read_without_losing_failure_scope(self):
        source = self.run/'simulator.stdout'
        with source.open('w') as stream:
            stream.write(('progress ' + 'x'*100 + '\n')*50000)
            stream.write('Model stopped successfully\nSendMsg failed\n')
        self.assertGreater(source.stat().st_size, 4_000_000)
        found = self.tools.search_text('workspace', 'SendMsg', path='simulator.stdout')
        self.assertEqual(found['matches'][0]['line'], 50002)
        page = self.tools.read('workspace', 'simulator.stdout', offset=50000, limit=2)
        self.assertEqual(page['content'], '50001: Model stopped successfully\n50002: SendMsg failed')
        self.assertIsNone(page['next_offset'])
        (self.run/'unknown.bin').write_bytes(b'visible but not text')
        with self.assertRaisesRegex(ValueError, 'binary'):
            self.tools.read('workspace', 'unknown.bin')

    def test_offline_field_cli_keeps_numeric_zero_and_na(self):
        # Independent raw values, no expected result generated with the parser.
        source = self.run/'reports/op/OPPROF_test/PipeUtilization.csv'
        source.parent.mkdir(parents=True)
        source.write_text('block_id,sub_block_id,aiv_time(us),aic_mte2_active_bw(GB/s)\n'
                          '0,vector0,0,NA\n1,vector0,4,NA\n')
        for command in ('provenance', 'analyze'):
            result = evaluation.offline_cli(REPO, self.run, [command, '--run-dir', str(self.run)])
            self.assertEqual(result.returncode, 0, result.stderr)
        result = self.tools.command('ascend-msprof evidence --run-dir run --question pipe '
             '--artifact reports/op/OPPROF_test/PipeUtilization.csv --field "aiv_time(us)" --format json')
        self.assertEqual(result['returncode'], 0, result)
        raw = self.tools.read('workspace', 'reports/op/OPPROF_test/PipeUtilization.csv')['content']
        self.assertIn('vector0,0,NA', raw)
        self.assertIn('vector0,4,NA', raw)
        # Assert full CLI distribution against the manually known two-cell population.
        payload = json.loads(result['stdout'])
        fields = payload['facts'][0]['selection']['groups'][0]['fields']['aiv_time(us)']
        self.assertEqual(fields['valid'], 2)
        self.assertEqual(fields['minimum'], 0)
        self.assertEqual(fields['maximum'], 4)
        result = self.tools.command('ascend-msprof joint-row --run-dir run '
            '--artifact reports/op/OPPROF_test/PipeUtilization.csv --record 2')
        self.assertEqual(result['returncode'], 0, result)
        row = json.loads(result['stdout'])
        self.assertEqual(row['record'], 2)
        self.assertEqual(row['fields'][0]['raw_token'], '0')


if __name__ == '__main__':
    unittest.main()
