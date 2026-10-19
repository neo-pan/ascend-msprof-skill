"""The contributor evaluator cannot turn model text into host execution."""
import importlib.util
import json
import shlex
import subprocess
import sys
import threading
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cannbot_eval', REPO / 'scripts/run_cannbot_evidence_eval.py')
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


class EvidenceBoundaryTests(unittest.TestCase):
    def test_comparison_dispatch_uses_caller_reader_and_keeps_complete_receipt(self):
        pairs = [{'id': 'one', 'left': {'path': 'a.json', 'sha256': 'a'},
                  'right': {'path': 'b.json', 'sha256': 'b'}}]
        calls = []
        result = {'origin': 'executor_formal_comparison', 'comparable': False,
                  'pairs': pairs, 'statistics': None, 'issues': [{'reason': 'x' * 14000}],
                  'limits': 'No mechanism or candidate decision.'}
        def reader(root, declared):
            calls.append((root, declared))
            return result
        command = 'compare-records ' + shlex.quote(json.dumps({'pairs': pairs}))
        with self.assertRaisesRegex(ValueError, 'no formal comparison reader'):
            self.tools.command(command)
        self.tools.comparison_reader = reader
        with patch.object(evaluation.subprocess, 'Popen', side_effect=AssertionError('spawned')):
            reply = self.tools.command(command)
        self.assertEqual(calls, [(self.run, pairs)])
        self.assertFalse(reply['comparable'])
        self.assertIsNone(reply['statistics'])
        self.assertEqual(reply['issue_count'], 1)
        saved = self.run / reply['receipt']['path']
        self.assertEqual(json.loads(saved.read_text()), result)
        self.assertEqual(evaluation.digest(saved), reply['receipt']['sha256'])
        self.assertLess(len(json.dumps(reply)), evaluation.TOOL_PAGE_BYTES)
        # A negative comparison still reads evidence and consumes one access.
        self.assertTrue(self.tools._counts_as_evidence_access('run_shell', reply))

    def test_replay_pairing_is_explicit_and_bound_to_released_artifacts(self):
        response = {'artifacts': [{'path': 'a.json', 'sha256': 'a'}, {'path': 'b.json', 'sha256': 'b'}],
                    'comparison_pairs': [{'id': 'one', 'left': {'path': 'a.json', 'sha256': 'a'},
                                          'right': {'path': 'b.json', 'sha256': 'b'}}]}
        evaluation.validate_comparison_pairs(response)
        response['comparison_pairs'][0]['right']['sha256'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'matching hash'):
            evaluation.validate_comparison_pairs(response)
        response['comparison_pairs'][0]['right'] = response['comparison_pairs'][0]['left']
        with self.assertRaisesRegex(ValueError, 'distinct released artifact'):
            evaluation.validate_comparison_pairs(response)

    def test_prepare_requires_declared_operator_inputs_to_enter_standard_index(self):
        corpus = self.root / 'corpus'
        for layout in ('initial', 'op/OPPROF_saved'):
            name = f'reports/{layout}/OpBasicInfo.csv'
            source = corpus / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text('Op Name,Task Duration(us),Block Dim,Core Type\nkernel,9.48,8,vector\n')
            task = {'inputs': [{'path': name, 'sha256': evaluation.digest(source)}],
                    'required_indexed_artifacts': [name]}
            output = self.root / layout.replace('/', '-')
            output.mkdir()
            if layout == 'initial':
                with self.assertRaisesRegex(ValueError, 'required evidence was not indexed'):
                    evaluation.prepare(task, corpus, REPO, output)
            else:
                run = evaluation.prepare(task, corpus, REPO, output)
                index = json.loads((run / 'analysis/raw_artifact_index.json').read_text())
                self.assertEqual(index['artifacts'][0]['artifact'], name)
                self.assertEqual(index['artifacts'][0]['row_count'], 1)
            self.assertEqual(evaluation.digest(source), task['inputs'][0]['sha256'])

    def test_public_context_preserves_facts_without_exposing_private_rubric(self):
        task = {'question': 'Compare the recorded activity.',
                'task_context': {'target': 'kernel', 'scope': 'one retained launch'},
                'oracle': {'expected_value': 17.25},
                'material_errors': ['unsupported critical-path inference']}
        self.assertEqual(evaluation.public_task_context(task), task['task_context'])
        self.assertEqual(evaluation.public_task_context({}), {})
        # Reproduce the F06 preparation leak: answer-boundary instructions
        # must fail preflight rather than silently becoming model context.
        task['task_context']['requested_output'] = 'Reject an uncertified conversion'
        with self.assertRaisesRegex(ValueError, 'private rubric'):
            evaluation.public_task_context(task)
        for context in ({'scope': {'oracle': 17.25}}, ['scope'], None):
            with self.subTest(context=context), self.assertRaises(ValueError):
                evaluation.public_task_context({'task_context': context})

    def test_source_text_read_keeps_stage_limits_with_exact_bytes(self):
        path = self.run / 'generated.cc'
        path.write_text('pipe_barrier(PIPE_ALL);\n')
        result = self.tools.read('workspace', 'generated.cc')
        self.assertEqual(result['sha256'], evaluation.digest(path))
        self.assertEqual(result['content'], '1: pipe_barrier(PIPE_ALL);')
        self.assertIn('source text', result['interpretation'])
        self.assertIn('runtime', result['interpretation'])
        path = self.run / 'raw.csv'
        path.write_text('field,value\ncore_time,4\n')
        self.assertNotIn('interpretation', self.tools.read('workspace', 'raw.csv'))

    def test_released_record_navigation_covers_all_results_without_scoring(self):
        tools, private, request = self.private_replay()
        response = json.loads((private / 'response.json').read_text())
        for n in range(1, 4):
            for side in ('C', 'D'):
                name = f'experiments/change/round-{n:02d}/{side}/executor-record.json'
                path = private / name
                path.parent.mkdir(parents=True)
                evaluation.save(path, {'report': {'status': 'failed' if n == 3 else 'success'},
                                       'metrics': {'device_program_duration_ms': n}})
                response['artifacts'].append({'path': name, 'sha256': evaluation.digest(path)})
        evaluation.save(private / 'response.json', response)
        tools.task['recorded_actions'][0]['sha256'] = evaluation.digest(private / 'response.json')
        with patch.object(evaluation, 'refresh', return_value=[]):
            reply = tools.replay(request)
        hints = reply['record_reads']
        self.assertEqual(sum(x['records'] for x in hints), 6)
        projected = tools.command(hints[0]['command'])
        self.assertEqual(len(projected['records']), 6)
        self.assertEqual(sum(x['values']['/report']['status'] == 'failed' for x in projected['records']), 2)
        self.assertTrue(all('/metrics/device_program_duration_ms' in x['values'] for x in projected['records']))
        self.assertNotIn('winner', reply)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'run'
        self.run.mkdir()
        self.tools = evaluation.EvidenceTools(self.run, REPO, {'inputs': []}, self.root)

    def test_answer_reserve_stops_new_reads_without_changing_evidence_budget(self):
        (self.run / 'fact.txt').write_text('observed=17\n')
        with patch.object(evaluation.time, 'monotonic', return_value=100):
            self.tools.start_session(180, answer_reserve_s=45)
            first = json.loads(self.tools.handle('read_file', {'root': 'workspace', 'path': 'fact.txt'}))
        self.assertEqual(first['budget']['wall_remaining_s'], 180)
        self.assertEqual(first['budget']['read_remaining_s'], 135)
        self.assertEqual(first['budget']['used'], 1)
        with patch.object(evaluation.time, 'monotonic', return_value=235):
            with patch.object(self.tools, 'read', side_effect=AssertionError('read during answer reserve')):
                stopped = json.loads(self.tools.handle('read_file', {'root': 'workspace', 'path': 'fact.txt'}))
        self.assertEqual(stopped['code'], 'answer_reserve')
        self.assertFalse(stopped['retryable'])
        self.assertEqual(stopped['budget']['used'], 1)
        self.assertEqual(stopped['budget']['wall_remaining_s'], 45)
        self.assertEqual(self.tools.calls, 2)
        self.assertEqual((self.run / 'fact.txt').read_text(), 'observed=17\n')
        with self.assertRaises(ValueError):
            self.tools.start_session(180, answer_reserve_s=180)

    def test_default_session_keeps_reads_available_before_original_deadline(self):
        (self.run / 'fact.txt').write_text('observed=17\n')
        with patch.object(evaluation.time, 'monotonic', return_value=100):
            self.tools.start_session(180)
        with patch.object(evaluation.time, 'monotonic', return_value=279):
            result = json.loads(self.tools.handle('read_file', {'root': 'workspace', 'path': 'fact.txt'}))
        self.assertIn('observed=17', result['content'])
        self.assertNotIn('wall_remaining_s', result['budget'])

    def test_formal_run_rejects_unfrozen_answer_policy_before_execution(self):
        from types import SimpleNamespace
        manifest = self.root / 'manifest.json'
        evaluation.save(manifest, {'kind': 'frozen_holdout', 'execution_freeze': {
            'wall_timeout_s': 180, 'evidence_accesses': 24}})
        args = SimpleNamespace(caller_root=REPO, skill_repo=REPO, output=self.root/'trajectory',
            manifest=manifest, formal=True, timeout=180, max_calls=24, answer_reserve_seconds=45)
        with patch.object(evaluation.subprocess, 'Popen', side_effect=AssertionError('spawned')):
            with self.assertRaisesRegex(ValueError, 'interaction policy differs'):
                evaluation.run_one(args)
        self.assertFalse(args.output.exists())

    def test_large_release_returns_manifest_instead_of_flooding_tool_context(self):
        tools, private, request = self.private_replay()
        response = json.loads((private / 'response.json').read_text())
        for n in range(100):
            name = f'experiments/change/round-{n:03d}/raw.csv'
            path = private / name
            path.parent.mkdir(parents=True)
            path.write_text('raw,value\nmetric,0\n')
            response['artifacts'].append({'path': name, 'sha256': evaluation.digest(path)})
        evaluation.save(private / 'response.json', response)
        tools.task['recorded_actions'][0]['sha256'] = evaluation.digest(private / 'response.json')
        with patch.object(evaluation, 'refresh', return_value=[]):
            reply = tools.replay(request)
        self.assertLess(len(json.dumps(reply)), 12000)
        saved = tools.run / reply['artifact_manifest']['path']
        self.assertEqual(evaluation.digest(saved), reply['artifact_manifest']['sha256'])
        self.assertEqual(json.loads(saved.read_text())['artifacts'], response['artifacts'])
        self.assertEqual(reply['artifact_count'], 102)
        # Reuse must still check every released raw file, even when the list is external.
        again = tools.replay(request)
        self.assertTrue(again['reused'])
        (tools.run / response['artifacts'][-1]['path']).chmod(0o644)
        (tools.run / response['artifacts'][-1]['path']).write_text('changed')
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            tools.replay(request)

    def test_projection_pages_by_bytes_without_losing_failed_or_missing_records(self):
        for n in range(12):
            evaluation.save(self.run / f'{n:02d}.json', {
                'status': 'failed' if n == 7 else 'success', 'detail': '内容' * 700})
        command = 'read-json-records ' + shlex.quote(json.dumps({
            'pattern': '*.json', 'pointers': ['/status', '/detail', '/missing']}))
        seen = []
        while command:
            page = self.tools.command(command)
            self.assertLessEqual(len(json.dumps(page, ensure_ascii=False).encode()), 12000)
            self.assertEqual(page['offset'], len(seen))
            for row in page['records']:
                raw = json.loads((self.run / row['path']).read_text())
                self.assertEqual(row['values'], {'/status': raw['status'], '/detail': raw['detail']})
                self.assertEqual(row['missing_pointers'], ['/missing'])
                self.assertEqual(row['sha256'], evaluation.digest(self.run / row['path']))
            seen.extend(page['records'])
            command = page['next_command']
            if page['truncated']:
                self.assertEqual(page['next_offset'], len(seen))
                self.assertTrue(command)
        self.assertEqual([row['path'] for row in seen], [f'{n:02d}.json' for n in range(12)])
        self.assertEqual(seen[7]['values']['/status'], 'failed')
        with self.assertRaises(ValueError):
            self.tools.json_records('*.json', ['/status'], offset=-1)

    def test_compact_projection_preserves_full_checks_and_last_round_exceptions(self):
        pointers = ['/report', '/protocol', '/identity', '/correctness', '/quality', '/time']
        protocol = {'mode': 'msprof_op', 'skip': 3, 'detail': 'protocol ' * 100}
        for n in range(12):
            value = {'report': {'success': True}, 'protocol': protocol,
                     'identity': {'workload': 'same', 'runtime': 'version ' * 100},
                     'correctness': {'passed': True}, 'quality': {'status': 'ok'}, 'time': n}
            if n == 9:
                value['protocol'] = {**protocol, 'skip': 4}
            if n == 10:
                value['correctness'] = {'passed': False}
            if n == 11:
                del value['quality']
            evaluation.save(self.run / f'{n:02d}.json', value)
        command = 'read-json-records ' + shlex.quote(json.dumps({
            'pattern': '*.json', 'pointers': pointers, 'compact': True, 'limit': 8}))
        seen, pages = [], []
        while command:
            page = self.tools.command(command)
            pages.append(page)
            self.assertEqual(page['selected_pointers'], pointers)
            self.assertLessEqual(len(json.dumps(page, ensure_ascii=False).encode()), 12000)
            for row in page['records']:
                values = {**row['values'], **{p: page['shared_values'][key]
                          for p, key in row['value_refs'].items()}}
                raw = json.loads((self.run / row['path']).read_text())
                self.assertEqual(values, {'/' + k: v for k, v in raw.items()})
                self.assertEqual(row['missing_pointers'], ['/quality'] if row['path'] == '11.json' else [])
                self.assertEqual(row['sha256'], evaluation.digest(self.run / row['path']))
                seen.append(values)
            command = page['next_command']
            if command:
                options = json.loads(shlex.split(command)[1])
                self.assertTrue(options['compact'])
                self.assertEqual(options['pointers'], pointers)
        self.assertEqual(len(seen), 12)
        self.assertEqual(len(pages), 2)
        self.assertEqual(seen[9]['/protocol']['skip'], 4)
        self.assertFalse(seen[10]['/correctness']['passed'])
        self.assertNotIn('/quality', seen[11])

    def test_compact_projection_preserves_types_null_and_literal_ref_objects(self):
        evaluation.save(self.run / 'a.json', {'a': {'value_ref': 'literal', 'long': 'x' * 400},
                                             'b': None, 'c': False, 'd': 0})
        page = self.tools.json_records('*.json', ['/a', '/b', '/c', '/d', '/missing'], compact=True)
        row = page['records'][0]
        self.assertEqual(page['shared_values'][row['value_refs']['/a']],
                         {'value_ref': 'literal', 'long': 'x' * 400})
        self.assertEqual(row['values'], {'/b': None, '/c': False, '/d': 0})
        self.assertEqual(row['missing_pointers'], ['/missing'])
        with self.assertRaises(ValueError):
            self.tools.json_records('*.json', ['/a'], compact='yes')

    def test_answer_hint_is_rejected_before_preparation_or_model_start(self):
        from types import SimpleNamespace
        manifest = self.root / 'manifest.json'
        evaluation.save(manifest, {'kind': 'development', 'tasks': [{
            'id': 'F06', 'inputs': [], 'task_context': {
                'requested_output': 'Reject uncertified definitions'}}]})
        args = SimpleNamespace(caller_root=REPO, skill_repo=REPO,
                               output=self.root / 'trajectory', manifest=manifest,
                               formal=False, task='F06')
        with patch.object(evaluation.subprocess, 'run', side_effect=AssertionError('spawned')):
            with self.assertRaisesRegex(ValueError, 'private rubric'):
                evaluation.run_one(args)
        self.assertFalse(args.output.exists())

    def test_cancelled_search_preserves_attempt_without_returning_partial_success(self):
        import io
        import threading
        self.tools.cancel_event = threading.Event()
        source = self.run / 'report.txt'
        source.write_text('start\nvalue=17.25\n')
        original = Path.open
        cancel = self.tools.cancel_event
        class CancellingInput(io.StringIO):
            def __iter__(self):
                yield 'start\n'
                cancel.set()
                yield 'value=17.25\n'
        def opening(path, *args, **kwargs):
            return CancellingInput() if path == source else original(path, *args, **kwargs)
        with patch.object(Path, 'open', opening):
            result = json.loads(self.tools.handle('search_text', {
                'root': 'workspace', 'path': 'report.txt', 'query': 'value'}))
        self.assertEqual(result.get('status'), 'rejected')
        self.assertIn('cancel', result['error'])
        self.assertEqual(self.tools.calls, 1)
        self.assertEqual(self.tools.evidence_calls, 0)
        log = json.loads((self.root/'tool-calls.jsonl').read_text())
        self.assertFalse(log['billable'])

    def test_offline_cli_cancellation_reaps_owned_process_and_keeps_bystander(self):
        # A real ordinary child exercises pipe draining/reaping; no NPU or model.
        original = subprocess.Popen
        spawned = []
        entered = threading.Event()
        cancel = threading.Event()
        def spawn(*args, **kwargs):
            child = original([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
            spawned.append(child)
            entered.set()
            return child
        bystander = original([sys.executable, '-c', 'import time; time.sleep(30)'])
        errors = []
        def operation():
            try:
                evaluation.offline_cli(REPO, self.run, ['evidence'], cancel)
            except Exception as exc:
                errors.append(exc)
        worker = threading.Thread(target=operation)
        try:
            with patch.object(evaluation.subprocess, 'Popen', spawn):
                worker.start()
                self.assertTrue(entered.wait(2))
                cancel.set()
                worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], ValueError)
            self.assertIn('cancelled', str(errors[0]))
            self.assertIsNotNone(spawned[0].poll())
            self.assertIsNone(bystander.poll())
        finally:
            cancel.set()
            for child in [*spawned, bystander]:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=3)
            worker.join(3)

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
        self.assertEqual(self.tools.calls, 6)
        self.assertEqual(self.tools.evidence_calls, 0)
        self.assertTrue(all(not call['billable'] for call in calls))

    def test_attempts_are_separate_from_evidence_budget(self):
        self.tools.max_calls = 1
        # Empty discovery and schema/path rejection remain auditable attempts,
        # but do not consume the one successful evidence access.
        empty = json.loads(self.tools.handle('list_files', {'root': 'workspace'}))
        self.assertEqual(empty['files'], [])
        empty = json.loads(self.tools.handle('search_text', {
            'root': 'workspace', 'query': 'absent'}))
        self.assertEqual(empty['matches'], [])
        rejected = json.loads(self.tools.handle('run_shell', {'command': 'npu-smi info'}))
        self.assertEqual(rejected['status'], 'rejected')
        self.assertEqual(self.tools.evidence_calls, 0)

        source = self.run / 'evidence.csv'
        source.write_text('value\n17.25\n')
        # The first non-empty read is the sole billable access.
        result = json.loads(self.tools.handle('read_file', {
            'root': 'workspace', 'path': 'evidence.csv'}))
        self.assertIn('17.25', result['content'])
        self.assertEqual(self.tools.evidence_calls, 1)

        exhausted = json.loads(self.tools.handle('read_file', {
            'root': 'workspace', 'path': 'evidence.csv'}))
        self.assertEqual(exhausted['status'], 'rejected')
        self.assertIn('budget exhausted', exhausted['error'])
        self.assertEqual(self.tools.evidence_calls, 1)
        calls = [json.loads(line) for line in (self.root/'tool-calls.jsonl').read_text().splitlines()]
        self.assertEqual(len(calls), 5)
        self.assertEqual(sum(call['billable'] for call in calls), 1)
        self.assertEqual([call['index'] for call in calls], [1, 2, 3, 4, 5])

    def test_search_default_reaches_nested_text_and_reports_coverage(self):
        nested = self.run / 'reference' / 'nested'
        nested.mkdir(parents=True)
        (nested / 'metric.md').write_text('counter activity definition\n')
        (self.run / 'module.py').write_text('counter = 1\n')
        (self.run / 'object.bin').write_bytes(b'\xff\x00counter')
        result = self.tools.search_text('workspace', 'counter')
        self.assertEqual({m['path'] for m in result['matches']},
                         {'reference/nested/metric.md', 'module.py'})
        self.assertEqual(result['files_scanned'], 2)
        self.assertEqual(result['pattern'], '**/*')
        self.assertEqual(result['skipped_non_text_files'], 1)
        empty = self.tools.search_text('workspace', 'counter', pattern='**/*.csv')
        self.assertEqual(empty['files_scanned'], 0)
        miss = self.tools.search_text('workspace', 'absent', pattern='**/*.py')
        self.assertEqual(miss['files_scanned'], 1)
        self.assertEqual(miss['matches'], [])

    def test_budget_is_visible_on_last_success_and_terminal_rejection(self):
        self.tools.max_calls = 1
        (self.run / 'raw.csv').write_text('value\n17.25\n')
        result = json.loads(self.tools.handle('read_file', {
            'root': 'workspace', 'path': 'raw.csv'}))
        self.assertIn('17.25', result['content'])
        self.assertEqual(result['budget'], {'used': 1, 'limit': 1, 'remaining': 0})
        with patch.object(self.tools, 'read', side_effect=AssertionError('read after budget')):
            rejected = json.loads(self.tools.handle('read_file', {
                'root': 'workspace', 'path': 'raw.csv'}))
        self.assertEqual(rejected['code'], 'evidence_budget_exhausted')
        self.assertFalse(rejected['retryable'])
        self.assertEqual(rejected['budget'], result['budget'])
        self.assertEqual(self.tools.calls, 2)
        self.assertEqual(self.tools.evidence_calls, 1)

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

    def private_replay(self):
        private = self.root/'private'
        private.mkdir()
        subject = {'implementation_sha256': 'a'*64, 'workload': 'shape-16-fp16', 'target': 'cube0'}
        task = {'inputs': [], 'replay_version': 2, 'action_catalog': [{
            'action': 'retrieve-memory', 'kind': 'retrieve_existing',
            'description': 'Retrieve the saved matching instrumentation report.',
            'subject_identity': subject, 'cost': {'simulated_device_s': 0}}]}
        files = {
            'reports/followups/OPPROF_saved/PipeUtilization.csv':
                'block_id,sub_block_id,aic_mte2_active_bw(GB/s)\n0,cube0,17.25\n',
            'logs/saved-receipt.json': '{"status":"succeeded","metric":"MemoryDetail"}',
        }
        for name, content in files.items():
            source = private/name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(content)
        response = {'subject_identity': subject,
                    'source_receipts': ['logs/saved-receipt.json'],
                    'artifacts': [{'path': n, 'sha256': evaluation.digest(private/n)} for n in files]}
        evaluation.save(private/'response.json', response)
        tools = evaluation.EvidenceTools(self.run, REPO, task, self.root, replay_root=private)
        request = {'action': 'retrieve-memory', 'input_identity': tools.input_identity, 'subject_identity': subject}
        task['recorded_actions'] = [{'request': request, 'response_path': 'response.json',
                                    'sha256': evaluation.digest(private/'response.json')}]
        return tools, private, request

    def test_private_release_then_selected_helper_refreshes_same_trajectory(self):
        tools, private, request = self.private_replay()
        evaluation.validate_replays(tools.task, private)
        catalog = tools.action_catalog()
        self.assertNotIn('17.25', json.dumps(catalog))
        self.assertNotIn('response.json', json.dumps(catalog))
        self.assertEqual(tools.list_files('workspace', pattern='**/*')['files'], [])
        self.assertEqual(tools.search_text('workspace', '17.25', pattern='**/*')['matches'], [])
        denied = json.loads(tools.handle('read_file', {'root': 'workspace', 'path': '../private/response.json'}))
        self.assertEqual(denied['status'], 'rejected')
        reply = json.loads(tools.handle('run_shell', {'command': catalog['actions'][0]['request_command']}))
        self.assertEqual(reply['origin'], 'recorded_replay')
        self.assertFalse(reply['executed'])
        self.assertTrue(all(x['returncode'] == 0 for x in reply['refresh']))
        raw = self.run/'reports/followups/OPPROF_saved/PipeUtilization.csv'
        self.assertEqual(raw.read_text().splitlines()[1], '0,cube0,17.25')
        self.assertEqual(raw.stat().st_mode & 0o222, 0)
        self.assertTrue((self.run/'analysis/summary.json').is_file())
        evidence = tools.command('ascend-msprof evidence --run-dir run --question pipe '
            '--artifact reports/followups/OPPROF_saved/PipeUtilization.csv '
            '--field "aic_mte2_active_bw(GB/s)" --format json')
        fields = json.loads(evidence['stdout'])['facts'][0]['selection']['groups'][0]['fields']
        self.assertEqual(fields['aic_mte2_active_bw(GB/s)']['maximum'], 17.25)
        with patch.object(evaluation, 'refresh', side_effect=AssertionError('duplicate refresh')):
            self.assertTrue(tools.command(catalog['actions'][0]['request_command'])['reused'])

    def test_wrong_identity_corruption_and_budget_do_not_release_private_files(self):
        tools, private, request = self.private_replay()
        command = lambda r: 'request-evidence '+shlex.quote(json.dumps(r))
        wrong = {**request, 'subject_identity': {**request['subject_identity'], 'target': 'other'}}
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            tools.command(command(wrong))
        self.assertEqual(tools.command(command({**request, 'action': 'unrecorded'}))['status'], 'unavailable')
        tools.max_calls = 0
        self.assertEqual(json.loads(tools.handle('run_shell', {'command': command(request)}))['status'], 'rejected')
        (private/'logs/saved-receipt.json').write_text('corrupted')
        with self.assertRaisesRegex(ValueError, 'artifact identity changed'):
            evaluation.validate_replays(tools.task, private)
        with self.assertRaisesRegex(ValueError, 'artifact identity changed'):
            tools.command(command(request))
        self.assertEqual(list(self.run.iterdir()), [])

    def test_separate_experiment_release_preserves_initial_analysis(self):
        tools, private, request = self.private_replay()
        response = json.loads((private/'response.json').read_text())
        for entry in response['artifacts']:
            original = entry['path']
            entry['path'] = 'experiments/candidate/' + original
            destination = private/entry['path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((private/original).read_bytes())
        response['source_receipts'] = ['experiments/candidate/logs/saved-receipt.json']
        evaluation.save(private/'response.json', response)
        tools.task['recorded_actions'][0]['sha256'] = evaluation.digest(private/'response.json')
        (self.run/'analysis').mkdir()
        summary = self.run/'analysis/summary.json'
        summary.write_text('{"original_run":true}')
        (self.run/'reports').mkdir()
        with patch.object(evaluation, 'refresh', side_effect=AssertionError(
                'independent experiment must not be merged into initial run')):
            reply = tools.replay(request)
        self.assertEqual(reply['refresh'], [])
        self.assertEqual(reply['refresh_reason'], 'no_initial_run_reports_added')
        self.assertEqual(summary.read_text(), '{"original_run":true}')
        raw = tools.read('workspace', response['artifacts'][0]['path'])
        self.assertIn('17.25', raw['content'])
        self.assertFalse(reply['executed'])

    def test_paired_json_read_retains_failed_missing_and_reordered_records(self):
        records = {
            'round-02/C': {'status': 'failed', 'metrics': {}},
            'round-01/D': {'status': 'success', 'metrics': {'duration_ms': 5, 'samples': [4, 6]}},
            'round-01/C': {'status': 'success', 'metrics': {'duration_ms': 3, 'samples': [2, 4]}},
        }
        for folder, value in records.items():
            target = self.run / 'experiments' / folder / 'record.json'
            target.parent.mkdir(parents=True)
            evaluation.save(target, value)
        result = self.tools.command('read-json-records ' + shlex.quote(json.dumps({
            'pattern': 'experiments/*/*/record.json',
            'pointers': ['/status', '/metrics/duration_ms', '/metrics/samples']})))
        rows = result['records']
        self.assertEqual([x['path'] for x in rows], [
            'experiments/round-01/C/record.json', 'experiments/round-01/D/record.json',
            'experiments/round-02/C/record.json'])
        self.assertEqual(rows[0]['values']['/metrics/samples'], [2, 4])
        self.assertEqual(rows[1]['values']['/metrics/duration_ms'], 5)
        self.assertEqual(rows[2]['values']['/status'], 'failed')
        self.assertEqual(rows[2]['missing_pointers'], ['/metrics/duration_ms', '/metrics/samples'])
        self.assertEqual(rows[0]['sha256'], evaluation.digest(self.run/rows[0]['path']))
        self.assertFalse(result['truncated'])
        self.assertNotIn('winner', result)
        self.assertNotIn('delta', result)
        # A missing side is not synthesized and corrupt inputs are not omitted.
        (self.run / rows[0]['path']).write_text('{broken')
        again = self.tools.json_records('experiments/*/*/record.json', ['/status'])
        self.assertEqual(len(again['records']), 3)
        self.assertIn('error', again['records'][0])
        with self.assertRaises(ValueError):
            self.tools.json_records('../private/*.json', ['/status'])

    def test_directory_discovery_shows_child_paths_without_claiming_file_evidence(self):
        (self.run / 'experiments/C').mkdir(parents=True)
        reply = self.tools.list_files('workspace', path='experiments')
        self.assertEqual(reply['files'], [])
        self.assertEqual(reply['directories'], ['experiments/C'])

    def test_release_preserves_existing_raw_and_protects_hidden_root(self):
        tools, private, request = self.private_replay()
        target = self.run/'logs/saved-receipt.json'
        target.parent.mkdir()
        target.write_text('original independent record')
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            tools.command('request-evidence '+shlex.quote(json.dumps(request)))
        self.assertEqual(target.read_text(), 'original independent record')
        self.assertFalse((self.run/'reports').exists())
        with self.assertRaisesRegex(ValueError, 'separate'):
            evaluation.EvidenceTools(self.run, REPO, tools.task, self.root, replay_root=self.run/'private')

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

    def test_empty_pages_report_actual_eof_not_requested_offset(self):
        source = self.run/'failure.stdout'
        # Include a final line without a newline, as truncated failure logs can.
        source.write_text('started\nModel stopped successfully\nSendMsg failed')
        for offset in (3, 4, 5_000_000, 10_000_000):
            with self.subTest(offset=offset):
                result = json.loads(self.tools.handle('read_file', {
                    'root': 'workspace', 'path': 'failure.stdout',
                    'offset': offset, 'limit': 5}))
                self.assertEqual(result['total_lines'], 3)
                self.assertEqual(result['content'], '')
                self.assertIsNone(result['next_offset'])
        page = self.tools.read('workspace', 'failure.stdout', offset=1, limit=1)
        self.assertIsNone(page['total_lines'])
        self.assertEqual(page['next_offset'], 2)
        tail = self.tools.read('workspace', 'failure.stdout', offset=2, limit=1)
        self.assertEqual(tail['total_lines'], 3)
        self.assertEqual(tail['content'], '3: SendMsg failed')
        self.assertIsNone(tail['next_offset'])
        source.write_text('')
        for offset in (0, 5_000_000):
            self.assertEqual(self.tools.read('workspace', 'failure.stdout',
                                            offset=offset)['total_lines'], 0)

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
