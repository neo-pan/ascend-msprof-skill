#!/usr/bin/env python3
"""Contributor-only offline evidence replay, using the frozen caller's Codex transport.

No model command is passed to a shell. The MCP run_shell name is inherited from
the caller; here it accepts only the documented offline argv grammar. Credentials
remain in the caller's deployment boundary. This is not the production Executor.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
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

    def __init__(self, run, skill, task, output, max_calls=24):
        self.run, self.skill, self.task, self.output = run, skill, task, output
        self.max_calls, self.calls = max_calls, 0
        self.roots = {'workspace': run, 'repository': skill / 'skills/ascend-msprof-skill'}
        self.input_identity = hashlib.sha256(json.dumps(task['inputs'], sort_keys=True).encode()).hexdigest()

    def handle(self, name, arguments):
        started = time.monotonic()
        self.calls += 1
        try:
            if self.calls > self.max_calls:
                raise ValueError('tool budget exhausted; answer from obtained evidence')
            method = {'read_file': self.read, 'list_files': self.list_files,
                      'search_text': self.search_text, 'run_shell': self.command}.get(name)
            if method is None:
                raise ValueError('unknown tool; execution is unavailable')
            result = method(**arguments)
        except (ValueError, TypeError, OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
            result = {'status': 'rejected', 'error': str(exc)}
        with (self.output / 'tool-calls.jsonl').open('a') as stream:
            stream.write(json.dumps({'index': self.calls, 'tool': name, 'arguments': arguments,
                'result': result, 'elapsed_s': time.monotonic()-started}, ensure_ascii=False) + '\n')
        return json.dumps(result, ensure_ascii=False)

    def read(self, root, path, offset=0, limit=200):
        if root not in self.roots or type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 1000:
            raise ValueError('invalid root or pagination')
        source = confined(self.roots[root], path)
        if source.suffix in {'.bin', '.o', '.so', '.elf'}:
            raise ValueError('binary files remain inventory only; read recorded tool output')
        # Large profiler logs remain readable without materializing the whole file.
        selected = []
        more = False
        with source.open() as stream:
            for index, line in enumerate(itertools.islice(stream, offset, offset+limit+1)):
                if index == limit:
                    more = True
                    break
                if '\x00' in line:
                    raise ValueError('binary content is inventory only')
                selected.append(line.rstrip('\n'))
        if sum(map(len, selected)) > 100_000:
            raise ValueError('page exceeds character limit; narrow pagination')
        return {'path': path, 'sha256': digest(source), 'offset': offset,
                'total_lines': None if more else offset+len(selected), 'next_offset': offset+limit if more else None,
                'content': '\n'.join(f'{offset+i+1}: {line}' for i, line in enumerate(selected))}

    def search_text(self, root, query, path='.', pattern='*', limit=32):
        if root not in self.roots or not isinstance(query, str) or not query or len(query) > 200 or type(limit) is not int or not 1 <= limit <= 64:
            raise ValueError('invalid search root, query or limit')
        if '..' in Path(pattern).parts or Path(pattern).is_absolute():
            raise ValueError('pattern escapes root')
        base = confined(self.roots[root], path)
        candidates = [base] if base.is_file() else sorted(base.glob(pattern))
        matches = []
        for candidate in candidates:
            source = confined(self.roots[root], candidate)
            if not source.is_file() or source.suffix in {'.bin', '.o', '.so', '.elf'}:
                continue
            with source.open(errors='replace') as stream:
                for line_number, line in enumerate(stream, 1):
                    if query in line:
                        matches.append({'path': str(source.relative_to(self.roots[root])),
                                        'line': line_number, 'text': line.rstrip('\n')[:1000]})
                        if len(matches) == limit:
                            return {'matches': matches, 'limit_reached': True}
        return {'matches': matches, 'limit_reached': False}

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
            if not isinstance(request, dict) or set(request) != {'action', 'input_identity'}:
                raise ValueError('request needs action and input_identity')
            if request['input_identity'] != self.input_identity:
                raise ValueError('input identity mismatch')
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
        flags = {'--aggregate-launches', '--list-fields', '--records'}
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
    preparation = []
    if (run / 'reports').exists():
        for cmd in ('provenance', 'analyze'):
            result = offline_cli(skill, run, [cmd, '--run-dir', str(run)])
            (output / f'prepare-{cmd}.stdout').write_text(result.stdout)
            (output / f'prepare-{cmd}.stderr').write_text(result.stderr)
            preparation.append({'command': cmd, 'returncode': result.returncode})
    save(output / 'preparation.json', preparation)
    return run


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
        if (args.timeout, args.max_calls) != (frozen['wall_timeout_s'], frozen['tool_calls']):
            raise ValueError('formal budget differs from freeze')
        if digest(__file__) != frozen['runner_sha256']:
            raise ValueError('evaluation runner drift')
        if tree_digest(caller, ['src', 'scripts', 'hardware', 'docs']) != frozen['caller_tree_sha256']:
            raise ValueError('caller source drift')
        if tree_digest(skill, ['src', 'skills']) not in frozen['skill_trees'].values():
            raise ValueError('skill source is outside frozen A/B')
    task = next(t for t in manifest['tasks'] if t['id'] == args.task)
    output.mkdir(parents=True)
    started = time.monotonic()
    run = prepare(task, (args.corpus / args.task).resolve(), skill, output)
    tools = EvidenceTools(run, skill, task, output, args.max_calls)
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
read_file uses zero-based line offset and returns numbered lines; search_text is literal text search for locating large logs.
The inherited run_shell tool is an argv dispatcher, NOT a shell. It accepts:
ascend-msprof evidence --run-dir run [standard evidence options]
ascend-msprof joint-row --run-dir run [standard joint-row options]
request-evidence '<JSON with action and input_identity>' requests an identity-matched saved action, never new measurement.
Unknown requests fail; a missing saved response means unavailable, not success. You may answer or propose a scoped
experiment without taking an action when that is sufficient. Raw files and normal CLI outputs retain their limitations.
Budget: {args.max_calls} total tool requests, {args.timeout} seconds; no retry. Return your answer with exact file/field
references, scope, and any necessary next step. You need not produce a kernel recipe or unique root cause.
Input identity: {tools.input_identity}
Available raw inputs: {json.dumps([x['path'] for x in task['inputs']], ensure_ascii=False)}
Task-supplied context: {json.dumps(task.get('task_context', {}), ensure_ascii=False)}
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
        if not inputs_unchanged:
            status = 'input_mutation'
        save(output / 'result.json', {'status': status, 'formal': args.formal, 'task': args.task,
            'model': t.model, 'effort': t.reasoning_effort, 'cli_sha256': t.executable_sha256,
            'transport_identity': t.identity_digest, 'model_catalog_sha256': hashlib.sha256((t.model_catalog_json or '').encode()).hexdigest(),
            'input_identity': tools.input_identity, 'prompt_sha256': digest(output/'prompt.txt'),
            'manifest_sha256': digest(args.manifest), 'runner_sha256': runner_identity,
            'skill_tree_sha256': tree_digest(skill, ['src', 'skills']),
            'preparation_s': preparation_s, 'agent_s': time.monotonic()-started-preparation_s,
            'budget': {'wall_s': args.timeout, 'tool_calls': args.max_calls, 'external_retries': 0},
            'elapsed_s': time.monotonic()-started, 'tool_calls': tools.calls, 'bridge': bridge_receipt,
            'event_counts': counts, 'item_counts': items, 'diagnostics': diagnostics, 'failures': failures,
            'unexpected_items': list(outcome.unexpected_items), 'returncode': process.returncode,
            'inputs_unchanged': inputs_unchanged,
            'npu_measurements': False, 'semantic_verdict': 'pending_review', 'credential_value_recorded': False})
    return 0 if status == 'completed' else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('caller-root', 'skill-repo', 'manifest', 'corpus', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--task', required=True)
    p.add_argument('--timeout', type=int, default=180)
    p.add_argument('--max-calls', type=int, default=24)
    p.add_argument('--formal', action='store_true')
    return run_one(p.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
