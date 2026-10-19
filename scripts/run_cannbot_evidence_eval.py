#!/usr/bin/env python3
"""Contributor-only offline evidence replay, using the frozen caller's Codex transport.

No model command is passed to a shell. The MCP run_shell name is inherited from
the caller; here it accepts only the documented offline argv grammar. Credentials
remain in the caller's deployment boundary. This is not the production Executor.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_digest(root, folders):
    entries = [(str(p.relative_to(root)), digest(p)) for folder in folders
               for p in sorted((root / folder).rglob('*'))
               if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def confined(root, path):
    candidate = (root / path).resolve()
    candidate.relative_to(root.resolve())
    return candidate


def offline_cli(skill, run, argv):
    # Even an accidental probe inside a parser fails before creating a process.
    code = """
import sys, subprocess, os
sys.path.insert(0, sys.argv.pop(1))
def forbidden(*a, **k): raise RuntimeError('offline evaluation forbids child processes')
subprocess.Popen = forbidden
os.system = os.popen = forbidden
from ascend_msprof_skill.cli import main
raise SystemExit(main(sys.argv[1:]))
"""
    return subprocess.run([sys.executable, '-I', '-c', code, str(skill / 'src'), *argv],
                          cwd=run, capture_output=True, text=True, timeout=45)


class EvidenceTools:
    """A single trajectory's bounded evidence, references and recorded actions."""

    def __init__(self, run, skill, task, output, max_calls=24, replay_root=None):
        self.run, self.skill, self.task, self.output = run, skill, task, output
        # ``calls`` is the transport-attempt sequence.  It is deliberately
        # separate from ``evidence_calls``: malformed requests, rejected
        # paths, and empty discovery results are useful audit events but do
        # not consume the bounded evidence-access budget.
        self.max_calls, self.calls, self.evidence_calls = max_calls, 0, 0
        self.roots = {'workspace': run, 'repository': skill / 'skills/ascend-msprof-skill'}
        self.input_identity = hashlib.sha256(json.dumps(task['inputs'], sort_keys=True).encode()).hexdigest()
        self.replay_root = Path(replay_root).resolve() if replay_root else None
        self.released_actions = {}
        if self.replay_root:
            for root in self.roots.values():
                if self.replay_root.is_relative_to(root.resolve()) or root.resolve().is_relative_to(self.replay_root):
                    raise ValueError('replay store must be separate from visible roots')

    def action_catalog(self):
        """Public capabilities only; private paths, hashes and results stay hidden."""
        entries = []
        for action in self.task.get('action_catalog', []):
            request = {'action': action['action'], 'input_identity': self.input_identity,
                       'subject_identity': action['subject_identity']}
            entries.append({**{key: action[key] for key in
                              ('action', 'kind', 'description', 'subject_identity', 'cost')},
                            'request_command': 'request-evidence ' + shlex.quote(json.dumps(request))})
        return {'origin': 'offline_capability_catalog', 'executed': False, 'actions': entries}

    def replay(self, request):
        action = next((a for a in self.task.get('action_catalog', [])
                       if a['action'] == request['action']), None)
        if action and request['subject_identity'] != action['subject_identity']:
            raise ValueError('implementation/workload/target identity mismatch')
        record = next((x for x in self.task.get('recorded_actions', []) if x['request'] == request), None)
        if not action or not record:
            return {'status': 'unavailable', 'origin': 'offline_request', 'executed': False,
                    'coverage': 'not_recorded', 'reason': 'No matching saved result; not proof this check is impossible.'}
        if self.replay_root is None:
            raise ValueError('private replay store is required')
        if request['action'] in self.released_actions:
            result = self.released_actions[request['action']]
            if any(digest(confined(self.run, x['path'])) != x['sha256'] for x in result['artifacts']):
                raise ValueError('released artifact identity changed')
            return {**result, 'reused': True}
        source = confined(self.replay_root, record['response_path'])
        if digest(source) != record['sha256']:
            raise ValueError('recorded response identity changed')
        response = json.loads(source.read_text())
        if response['subject_identity'] != request['subject_identity']:
            raise ValueError('recorded subject identity mismatch')
        artifacts = response['artifacts']
        if not artifacts or len({x['path'] for x in artifacts}) != len(artifacts):
            raise ValueError('recorded result needs distinct raw artifacts')
        # Validate the complete release before touching this trajectory. No
        # replacement of original raw, formal timing or helper-derived files.
        with tempfile.TemporaryDirectory(prefix='replay-', dir=self.output) as tmp:
            copies = []
            for entry in artifacts:
                relative = Path(entry['path'])
                if relative.is_absolute() or '..' in relative.parts or not relative.parts or relative.parts[0] in {'analysis', 'eval-tool-output', 'eval-actions.json'}:
                    raise ValueError('invalid recorded artifact destination')
                raw = confined(self.replay_root, entry['path'])
                if digest(raw) != entry['sha256']:
                    raise ValueError('recorded artifact identity changed')
                target = confined(self.run, entry['path'])
                if target.exists() and digest(target) != entry['sha256']:
                    raise ValueError('recorded result would overwrite existing evidence')
                staged = Path(tmp) / str(len(copies))
                shutil.copyfile(raw, staged)
                copies.append((staged, target))
            for staged, target in copies:
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(staged, target)
                    target.chmod(0o444)
        # Only reports added to the initial run belong in its derived evidence.
        # A diagnostic experiment may return other implementations' raw CSVs;
        # rebuilding the initial run would pool those records and needlessly
        # reparse every independent experiment. Keep them readable by path.
        adds_reports = any(Path(entry['path']).parts[0] == 'reports' for entry in artifacts)
        refreshed = refresh(self.skill, self.run, self.output, f'replay-{self.calls}') if adds_reports else []
        result = {'status': 'recorded', 'origin': 'recorded_replay', 'executed': False,
                  'subject_identity': response['subject_identity'], 'artifacts': artifacts,
                  'source_receipts': response['source_receipts'], 'refresh': refreshed,
                  'refresh_reason': 'initial_run_reports_added' if adds_reports else 'no_initial_run_reports_added',
                  'reused': False, 'kind': action['kind'], 'declared_cost': action['cost']}
        self.released_actions[request['action']] = result
        return result

    def handle(self, name, arguments):
        started = time.monotonic()
        self.calls += 1
        billable = False
        try:
            if self.evidence_calls >= self.max_calls:
                raise ValueError('tool budget exhausted; answer from obtained evidence')
            method = {'read_file': self.read, 'list_files': self.list_files,
                      'search_text': self.search_text, 'run_shell': self.command}.get(name)
            if method is None:
                raise ValueError('unknown tool; execution is unavailable')
            result = method(**arguments)
            billable = self._counts_as_evidence_access(name, result)
            if billable:
                self.evidence_calls += 1
        except (ValueError, TypeError, KeyError, OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
            result = {'status': 'rejected', 'error': str(exc)}
            if self.evidence_calls >= self.max_calls:
                result.update(code='evidence_budget_exhausted', retryable=False,
                              next_step='Answer from obtained evidence; further tool calls cannot return evidence in this trajectory.')
        result['budget'] = {'used': self.evidence_calls, 'limit': self.max_calls,
                            'remaining': max(0, self.max_calls - self.evidence_calls)}
        with (self.output / 'tool-calls.jsonl').open('a') as stream:
            stream.write(json.dumps({'index': self.calls, 'tool': name, 'arguments': arguments,
                'result': result, 'billable': billable,
                'evidence_calls': self.evidence_calls,
                'elapsed_s': time.monotonic()-started}, ensure_ascii=False) + '\n')
        return json.dumps(result, ensure_ascii=False)

    @staticmethod
    def _counts_as_evidence_access(name, result):
        """Return whether a completed handler call consumed evidence budget.

        The v2 protocol records every handler attempt, while charging only a
        successful access that returned evidence.  Empty list/search results,
        unavailable recorded actions, and all rejected/schema-invalid calls
        remain visible in the attempt log but are not charged.  A successful
        read of a non-empty page and a successful offline CLI/replay response
        are charged, including a repeated read of an already released result.
        """
        if not isinstance(result, dict) or result.get('status') == 'rejected':
            return False
        if name == 'list_files':
            return bool(result.get('files'))
        if name == 'search_text':
            return bool(result.get('matches'))
        if name == 'read_file':
            return bool(result.get('content'))
        if name == 'run_shell':
            # A matching replay is an evidence access; an unavailable action
            # is an audited miss rather than evidence.  Offline CLI commands
            # charge only when they completed with output successfully.
            if result.get('origin') == 'recorded_replay':
                return True
            return result.get('status') == 'ok' and bool(result.get('stdout'))
        return False

    def read(self, root, path, offset=0, limit=200):
        if root not in self.roots or type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 1000:
            raise ValueError('invalid root or pagination')
        source = confined(self.roots[root], path)
        if source.suffix in {'.bin', '.o', '.so', '.elf'}:
            raise ValueError('binary files remain inventory only; read recorded tool output')
        # Large profiler logs remain readable without materializing the whole file.
        selected = []
        more = False
        total_lines = 0
        with source.open() as stream:
            for index, line in enumerate(stream):
                total_lines = index + 1
                if index < offset:
                    continue
                if len(selected) == limit:
                    more = True
                    break
                if '\x00' in line:
                    raise ValueError('binary content is inventory only')
                selected.append(line.rstrip('\n'))
        if sum(map(len, selected)) > 100_000:
            raise ValueError('page exceeds character limit; narrow pagination')
        return {'path': path, 'sha256': digest(source), 'offset': offset,
                'total_lines': None if more else total_lines, 'next_offset': offset+limit if more else None,
                'content': '\n'.join(f'{offset+i+1}: {line}' for i, line in enumerate(selected))}

    def search_text(self, root, query, path='.', pattern='**/*', limit=32):
        if root not in self.roots or not isinstance(query, str) or not query or len(query) > 200 or type(limit) is not int or not 1 <= limit <= 64:
            raise ValueError('invalid search root, query or limit')
        if '..' in Path(pattern).parts or Path(pattern).is_absolute():
            raise ValueError('pattern escapes root')
        base = confined(self.roots[root], path)
        candidates = [base] if base.is_file() else sorted(base.glob(pattern))
        matches = []
        files_scanned = skipped_non_text = 0
        def response(limit_reached):
            return {'matches': matches, 'limit_reached': limit_reached,
                    'root': root, 'path': path, 'pattern': pattern,
                    'files_scanned': files_scanned, 'skipped_non_text_files': skipped_non_text}
        for candidate in candidates:
            source = confined(self.roots[root], candidate)
            if not source.is_file():
                continue
            first_match = len(matches)
            try:
                if source.suffix in {'.bin', '.o', '.so', '.elf'}:
                    raise ValueError('binary content is inventory only')
                with source.open(encoding='utf-8') as stream:
                    for line_number, line in enumerate(stream, 1):
                        if '\x00' in line:
                            raise ValueError('binary content is inventory only')
                        if query in line:
                            matches.append({'path': str(source.relative_to(self.roots[root])),
                                            'line': line_number, 'text': line.rstrip('\n')[:1000]})
                            if len(matches) == limit:
                                files_scanned += 1
                                return response(True)
                    files_scanned += 1
            except (UnicodeError, ValueError):
                if base.is_file():
                    raise
                del matches[first_match:]
                skipped_non_text += 1
                continue
        return response(False)

    def list_files(self, root, path='.', pattern='*', limit=64):
        if root not in self.roots or type(limit) is not int or not 1 <= limit <= 256:
            raise ValueError('invalid root or limit')
        if '..' in Path(pattern).parts or Path(pattern).is_absolute():
            raise ValueError('pattern escapes root')
        base = confined(self.roots[root], path)
        files = []
        for candidate in sorted(base.glob(pattern)):
            if candidate.is_file():
                source = confined(self.roots[root], candidate)
                files.append({'path': str(source.relative_to(self.roots[root])),
                              'bytes': source.stat().st_size, 'sha256': digest(source)})
                if len(files) == limit:
                    break
        return {'files': files, 'limit': limit}

    def command(self, command):
        argv = shlex.split(command)
        if argv[:1] == ['request-evidence']:
            if len(argv) != 2:
                raise ValueError('request-evidence requires one quoted JSON object')
            request = json.loads(argv[1])
            required = {'action', 'input_identity'}
            if self.task.get('replay_version') == 2:
                required.add('subject_identity')
            if not isinstance(request, dict) or set(request) != required:
                raise ValueError('request needs ' + ', '.join(sorted(required)))
            if request['input_identity'] != self.input_identity:
                raise ValueError('input identity mismatch')
            if self.task.get('replay_version') == 2:
                return self.replay(request)
            record = next((x for x in self.task.get('recorded_actions', []) if x['request'] == request), None)
            if record is None:
                return {'status': 'unavailable', 'origin': 'offline_request', 'executed': False,
                        'reason': 'No identity-matched recorded response; no application or collection was started.'}
            source = confined(self.run, record['response_path'])
            if digest(source) != record['sha256']:
                raise ValueError('recorded response identity changed')
            return {'status': 'recorded', 'origin': 'recorded_replay', 'executed': False,
                    'response': json.loads(source.read_text())}
        if len(argv) < 2 or argv[0] != 'ascend-msprof' or argv[1] not in {'evidence', 'joint-row'}:
            raise ValueError('Only offline ascend-msprof evidence/joint-row and request-evidence are available; no shell')
        values = {'--run-dir', '--question', '--segment', '--artifact', '--field', '--offset',
                  '--limit', '--launch-scope', '--format', '--scope', '--record', '--group', '--verify'}
        flags = {'--aggregate-launches', '--list-fields', '--records', '--help'}
        filtered, i = [], 2
        while i < len(argv):
            key = argv[i]
            if key in flags:
                filtered.append(key); i += 1; continue
            if key not in values or i + 1 == len(argv):
                raise ValueError('unsupported offline option: ' + key)
            value = argv[i+1]
            if key == '--run-dir':
                if value not in {'.', 'run', str(self.run)}:
                    raise ValueError('run-dir must identify this trajectory')
            else:
                if key in {'--artifact', '--verify'}:
                    source = confined(self.run, value)
                    if key == '--verify':
                        value = str(source)
                filtered.extend([key, value])
            i += 2
        result = offline_cli(self.skill, self.run, [argv[1], '--run-dir', str(self.run), *filtered])
        # Save complete output; pagination remains available through read_file.
        relative = f'eval-tool-output/{self.calls:03d}.txt'
        target = self.run / relative
        target.parent.mkdir(exist_ok=True)
        target.write_text(result.stdout)
        return {'status': 'ok' if result.returncode == 0 else 'error', 'returncode': result.returncode,
                'stdout': result.stdout[:60000], 'stderr': result.stderr[:2000],
                'full_output': relative, 'truncated': len(result.stdout) > 60000}


def refresh(skill, run, output, prefix='prepare'):
    preparation = []
    if (run / 'reports').exists():
        for cmd in ('provenance', 'analyze'):
            result = offline_cli(skill, run, [cmd, '--run-dir', str(run)])
            (output / f'{prefix}-{cmd}.stdout').write_text(result.stdout)
            (output / f'{prefix}-{cmd}.stderr').write_text(result.stderr)
            preparation.append({'command': cmd, 'returncode': result.returncode})
    return preparation


def validate_replays(task, replay_root):
    """Check frozen private bytes before starting any model process."""
    if task.get('replay_version') != 2:
        return
    catalog = task.get('action_catalog', [])
    actions = {a['action']: a for a in catalog}
    if len(actions) != len(catalog):
        raise ValueError('duplicate action capability')
    identity = hashlib.sha256(json.dumps(task['inputs'], sort_keys=True).encode()).hexdigest()
    seen = set()
    for record in task.get('recorded_actions', []):
        request = record['request']
        action = actions.get(request['action'])
        if not action or request != {'action': action['action'], 'input_identity': identity,
                                     'subject_identity': action['subject_identity']}:
            raise ValueError('recorded request does not match public capability identity')
        if action['action'] in seen:
            raise ValueError('duplicate recorded action')
        seen.add(action['action'])
        if replay_root is None:
            raise ValueError('private replay store is required')
        source = confined(replay_root, record['response_path'])
        if digest(source) != record['sha256']:
            raise ValueError('recorded response identity changed')
        response = json.loads(source.read_text())
        if response['subject_identity'] != action['subject_identity']:
            raise ValueError('recorded subject identity mismatch')
        paths = {a['path'] for a in response['artifacts']}
        if not paths or not response['source_receipts'] or not set(response['source_receipts']) <= paths:
            raise ValueError('recorded artifacts must include their source receipts')
        for entry in response['artifacts']:
            if digest(confined(replay_root, entry['path'])) != entry['sha256']:
                raise ValueError('recorded artifact identity changed')


def prepare(task, corpus, skill, output):
    run = output / 'run'
    run.mkdir()
    for entry in task['inputs']:
        source = confined(corpus, entry['path'])
        if digest(source) != entry['sha256']:
            raise ValueError('input drift: ' + entry['path'])
        target = confined(run, entry['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    # Standard A/B preparation, performed with that arm's own code. Preserve all
    # input bytes and do not query the current environment.
    preparation = refresh(skill, run, output)
    save(output / 'preparation.json', preparation)
    return run


def public_task_context(task):
    """Expose task facts, not evaluator rubric or expected-answer hints.

    Values still require a semantic review before freezing: a permitted key
    cannot mechanically certify that its prose contains only task facts.
    """
    context = task.get('task_context', {})
    allowed = {'target', 'target_artifact', 'scope', 'workload',
               'measurement_protocol', 'authorization'}
    if not isinstance(context, dict) or set(context) - allowed:
        raise ValueError('task_context accepts only public task facts; keep answer requirements in the private rubric')
    if any(not isinstance(value, str) for value in context.values()):
        raise ValueError('public task context values must be text reviewed before freezing')
    return context


def run_one(args):
    runner_identity = digest(__file__)
    caller, skill, output = args.caller_root.resolve(), args.skill_repo.resolve(), args.output.resolve()
    if output.exists():
        raise ValueError('output must be a new trajectory directory; no silent retries')
    manifest = json.loads(args.manifest.read_text())
    if args.formal and manifest['kind'] != 'frozen_holdout':
        raise ValueError('formal run requires a frozen manifest')
    if args.formal:
        frozen = manifest['execution_freeze']
        frozen_evidence_budget = frozen.get('evidence_accesses', frozen.get('tool_calls'))
        if frozen_evidence_budget is None:
            raise ValueError('freeze is missing evidence_accesses budget')
        if (args.timeout, args.max_calls) != (frozen['wall_timeout_s'], frozen_evidence_budget):
            raise ValueError('formal budget differs from freeze')
        if digest(__file__) != frozen['runner_sha256']:
            raise ValueError('evaluation runner drift')
        if tree_digest(caller, ['src', 'scripts', 'hardware', 'docs']) != frozen['caller_tree_sha256']:
            raise ValueError('caller source drift')
        if tree_digest(skill, ['src', 'skills']) not in frozen['skill_trees'].values():
            raise ValueError('skill source is outside frozen A/B')
    task = next(t for t in manifest['tasks'] if t['id'] == args.task)
    context = public_task_context(task)
    replay_root = (args.replay_root / args.task).resolve() if args.replay_root else None
    validate_replays(task, replay_root)
    output.mkdir(parents=True)
    started = time.monotonic()
    run = prepare(task, (args.corpus / args.task).resolve(), skill, output)
    tools = EvidenceTools(run, skill, task, output, args.max_calls, replay_root)
    if task.get('replay_version') == 2:
        save(run / 'eval-actions.json', tools.action_catalog())
    sys.path.insert(0, str(caller / 'src'))
    from kernel_agent.search_composition import DeploymentInputs
    from kernel_agent.codex_transport import CodexCliAdapter
    from kernel_agent.tool_bridge import SessionToolBridge

    deployment = DeploymentInputs.load(os.environ['KERNEL_AGENT_DEPLOYMENT'], environment=os.environ, project_root=caller)
    t = deployment.codex_cli
    if deployment.runtime_kind != 'codex_cli' or t is None or t.model != 'deepseek-flash':
        raise ValueError('requires the pinned caller codex_cli / deepseek-flash deployment')
    expected = manifest.get('configuration_audit', {})
    if expected.get('cli_sha256', t.executable_sha256) != digest(t.executable):
        raise ValueError('CLI executable identity drift')
    if args.formal and (t.reasoning_effort != frozen['reasoning_effort'] or t.identity_digest != frozen['transport_identity']):
        raise ValueError('deployment differs from freeze')
    env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL', 'LD_LIBRARY_PATH') if k in os.environ}
    env['PYTHONPATH'] = str(caller / 'src')
    adapter = CodexCliAdapter(system_prompt='', user_prompt='', model=t.model, reasoning_effort=t.reasoning_effort,
        session_timeout_sec=args.timeout, mcp_tool_timeout_sec=60, executable=t.executable,
        executable_sha256=t.executable_sha256, version=t.version, auth_mode=t.auth_mode,
        api_key=t.api_key, base_url=t.base_url, local_codex_home=t.local_codex_home,
        transport_identity_digest=t.identity_digest, workspace_dir=run, stream_log_dir=output,
        log_stem='model', repository_root=caller, subprocess_environment=env, model_catalog_json=t.model_catalog_json)
    skill_text = (skill / 'skills/ascend-msprof-skill/SKILL.md').read_text()
    prompt = f'''Answer the evidence question below. You are in an offline recorded-evidence evaluation.
Use the selected Skill and retained files. No current environment query or real execution is available.
Tools: read_file/list_files/search_text root=workspace accesses the supplied run; root=repository accesses this Skill and its references.
read_file uses zero-based line offset, limit 1..1000 and returns numbered lines.
list_files limit is 1..256; search_text uses literal text, limit 1..64, for locating large logs.
The inherited run_shell tool is an argv dispatcher, NOT a shell. It accepts:
ascend-msprof evidence --run-dir run [standard evidence options]
ascend-msprof joint-row --run-dir run [standard joint-row options]
Use each CLI's --help for its options. The same offline permissions apply to both groups.
{'Read eval-actions.json for available checks, identity, cost and exact request commands. Results are released only after a matching request. Added reports/ files refresh initial-run derived evidence; independent experiment results remain separate and are readable at the returned paths.' if task.get('replay_version') == 2 else "request-evidence '<JSON with action and input_identity>' requests an identity-matched saved action, never new measurement."}
Unknown requests fail; a missing saved response means unavailable, not success. You may answer or propose a scoped
experiment without taking an action when that is sufficient. Raw files and normal CLI outputs retain their limitations.
Budget: {args.max_calls} successful evidence accesses are allowed; later handler requests are rejected.
Schema-rejected requests, rejected paths, unavailable replays, and empty resource discovery do not consume
that evidence budget, while every handler attempt is recorded separately. Model wall-time limit: {args.timeout}
seconds; no retry. Return your answer with exact file/field
references, scope, and any necessary next step. You need not produce a kernel recipe or unique root cause.
Input identity: {tools.input_identity}
Available raw inputs: {json.dumps([x['path'] for x in task['inputs']], ensure_ascii=False)}
Task-supplied context: {json.dumps(context, ensure_ascii=False)}
Question: {task['question']}
Selected Skill (references available on demand):
{skill_text}
'''
    (output / 'prompt.txt').write_text(prompt)
    preparation_s = time.monotonic()-started
    with tempfile.TemporaryDirectory(prefix='cannbot-eval-') as tmp:
        private = Path(tmp)
        if t.model_catalog_json:
            (private / 'models.json').write_text(t.model_catalog_json)
        adapter._install_local_auth_snapshot(private)
        handlers = {name: (lambda arguments, name=name: tools.handle(name, arguments))
                    for name in ('read_file', 'list_files', 'search_text', 'run_shell')}
        bridge = SessionToolBridge(private / 'mcp.sock', handlers)
        command = adapter._command(output_path=private / 'answer.txt', socket_path=private / 'mcp.sock',
            tool_names=list(handlers), web_search_enabled=False, native_coder_tools=False,
            deadline_monotonic=time.monotonic()+args.timeout)
        # Explicitly close other native execution entrances in the pinned CLI.
        command[-1:-1] = ['--disable', 'apply_patch_freeform', '--disable', 'js_repl',
                         '--disable', 'multi_agent', '-c', 'approval_policy="never"']
        save(output / 'command.json', [adapter._redact_transport_values(x) for x in command])
        process = None
        status = 'error'
        stdout = stderr = b''
        try:
            process = subprocess.Popen(command, cwd=run, env=adapter._environment(private),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            try:
                stdout, stderr = process.communicate(prompt.encode(), timeout=args.timeout)
                status = 'completed' if process.returncode == 0 else 'failed'
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                status = 'timeout' if isinstance(exc, subprocess.TimeoutExpired) else 'interrupted'
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate(timeout=5)
            if (private / 'answer.txt').exists():
                (output / 'answer.md').write_text(adapter._redact_transport_values((private / 'answer.txt').read_text()))
        finally:
            if process and process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            bridge_receipt = bridge.close()
        # Retain visible messages/tool events, counts and usage, not private reasoning.
        visible = []
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('item', {}).get('type') == 'reasoning':
                continue
            visible.append(json.loads(adapter._redact_transport_values(json.dumps(event))))
        (output / 'events.jsonl').write_text(''.join(json.dumps(x, ensure_ascii=False)+'\n' for x in visible))
        (output / 'stderr.txt').write_text(adapter._redact_transport_values(stderr.decode(errors='replace')))
        counts, items, failures, diagnostics = {}, {}, [], {}
        outcome = adapter._drain_events(stdout, event_counts=counts, item_counts=items, failure_events=failures,
            api_key=t.api_key, base_url=t.base_url, diagnostics=diagnostics,
            allow_web_search=False, allow_native_tools=False)
        if outcome.unexpected_items or failures or not counts.get('turn.completed'):
            status = status if status != 'completed' else 'failed'
        inputs_unchanged = all(digest(confined(run, x['path'])) == x['sha256'] for x in task['inputs'])
        inputs_unchanged = inputs_unchanged and all(
            digest(confined(run, x['path'])) == x['sha256']
            for release in tools.released_actions.values() for x in release['artifacts'])
        if not inputs_unchanged:
            status = 'input_mutation'
        save(output / 'result.json', {'status': status, 'formal': args.formal, 'task': args.task,
            'model': t.model, 'effort': t.reasoning_effort, 'cli_sha256': t.executable_sha256,
            'transport_identity': t.identity_digest, 'model_catalog_sha256': hashlib.sha256((t.model_catalog_json or '').encode()).hexdigest(),
            'input_identity': tools.input_identity, 'prompt_sha256': digest(output/'prompt.txt'),
            'manifest_sha256': digest(args.manifest), 'runner_sha256': runner_identity,
            'skill_tree_sha256': tree_digest(skill, ['src', 'skills']),
            'preparation_s': preparation_s, 'agent_s': time.monotonic()-started-preparation_s,
            'budget': {'wall_s': args.timeout, 'evidence_accesses': args.max_calls,
                       'external_retries': 0},
            # Keep the historical ``tool_calls`` field as the total visible
            # attempt count for old packet readers; the explicit names below
            # prevent it from being mistaken for the evidence budget.
            'elapsed_s': time.monotonic()-started, 'tool_calls': tools.calls,
            'tool_attempts': tools.calls, 'evidence_calls': tools.evidence_calls,
            'bridge': bridge_receipt,
            'event_counts': counts, 'item_counts': items, 'diagnostics': diagnostics, 'failures': failures,
            'unexpected_items': list(outcome.unexpected_items), 'returncode': process.returncode,
            'inputs_unchanged': inputs_unchanged, 'recorded_releases': tools.released_actions,
            'npu_measurements': False, 'semantic_verdict': 'pending_review', 'credential_value_recorded': False})
    return 0 if status == 'completed' else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('caller-root', 'skill-repo', 'manifest', 'corpus', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--task', required=True)
    p.add_argument('--replay-root', type=Path, help='Private, non-visible recorded result store; task subdirectories')
    p.add_argument('--timeout', type=int, default=180)
    p.add_argument('--max-calls', type=int, default=24)
    p.add_argument('--formal', action='store_true')
    return run_one(p.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
