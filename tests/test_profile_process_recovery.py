"""Real ordinary subprocesses exercise ownership and failure receipts; no NPU."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


@unittest.skipUnless(sys.platform == 'linux', 'process-group checks require Linux')
class ProfileProcessRecoveryTests(unittest.TestCase):
    def running(self, pid):
        try:
            return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
        except FileNotFoundError:
            return False

    def exercise(self, *, interrupt=False, timeout=0.4, damaged=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # This named profiler stub exercises output staging, never a toolkit.
            stub = root / 'msprof'
            stub.write_text(f'#!{sys.executable}\n' + '''
import json, os, pathlib, signal, subprocess, sys, time
root = pathlib.Path.cwd()
out = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
out.mkdir(parents=True)
(out / 'partial.csv').write_text('raw retained\\n')
if '--damaged' in sys.argv:
    os.write(1, b'valid prefix\\n\\xff\\n')
    sys.exit(0)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, '-c',
    'import pathlib,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
    "pathlib.Path('grandchild-ready').touch(); time.sleep(30)"])
while not (root / 'grandchild-ready').exists():
    time.sleep(0.01)
(root / 'owned.json').write_text(json.dumps({'parent': os.getpid(),
    'child': child.pid, 'group': os.getpgrp()}))
print('partial stdout', flush=True)
time.sleep(30)
''')
            stub.chmod(0o755)
            driver = root / 'driver.py'
            driver.write_text('''
import pathlib, sys
from ascend_msprof_skill.profile_harness import run_logged
root = pathlib.Path.cwd()
run_logged([str(root / 'msprof'), '--output', str(root / 'run/reports/op')]
    + (['--damaged'] if sys.argv[2] == 'yes' else []), root / 'run',
    command_name='command_msprof_op.txt', log_stem='msprof_op', cwd=root,
    timeout_s=None if sys.argv[1] == 'none' else float(sys.argv[1]))
(root / 'next-expensive-stage').touch()
''')
            env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
                   'ASCEND_MSPROF_STAGE_ROOT': str(root / 'stage')}
            sibling = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                       start_new_session=True)
            worker = subprocess.Popen([sys.executable, str(driver),
                                       'none' if timeout is None else str(timeout),
                                       'yes' if damaged else 'no'], cwd=root, env=env,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      start_new_session=True)
            owned = None
            try:
                if not damaged:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        try:
                            owned = json.loads((root / 'owned.json').read_text())
                            break
                        except (FileNotFoundError, json.JSONDecodeError):
                            time.sleep(0.01)
                    self.assertIsNotNone(owned, 'stub did not become ready')
                    if interrupt:
                        worker.send_signal(signal.SIGINT)
                started = time.monotonic()
                worker.communicate(timeout=8)
                self.assertLess(time.monotonic() - started, 7)
                self.assertIsNone(sibling.poll(), 'cleanup affected an unrelated process')
                if owned:
                    deadline = time.monotonic() + 1
                    while time.monotonic() < deadline and any(self.running(owned[k]) for k in ('parent', 'child')):
                        time.sleep(0.01)
                    self.assertFalse(self.running(owned['parent']), 'owned child survived')
                    self.assertFalse(self.running(owned['child']), 'owned grandchild survived')
                self.assertNotEqual(worker.returncode, 0)
                self.assertFalse((root / 'next-expensive-stage').exists())
                receipt = json.loads((root / 'run/logs/msprof_op.result.json').read_text())
                self.assertEqual(receipt['status'], 'timeout' if not interrupt and not damaged else 'failed')
                self.assertEqual((root / 'run/reports/op/partial.csv').read_text(), 'raw retained\n')
                self.assertTrue(receipt['output_staged_locally'])
                if damaged:
                    self.assertEqual(receipt['failure_reason'], 'output_decode_error')
                    self.assertEqual(receipt['process_returncode'], 0)
                    self.assertEqual((root / 'run/logs/msprof_op.stdout.bin').read_bytes(), b'valid prefix\n\xff\n')
                elif interrupt:
                    self.assertEqual(receipt['failure_reason'], 'interrupted')
                    self.assertIn('partial stdout', (root / 'run/logs/msprof_op.stdout').read_text())
            finally:
                # Clean only processes started by this test, including baseline leaks.
                for group in {worker.pid, sibling.pid, *([owned['group']] if owned else [])}:
                    if group == os.getpgrp():
                        raise AssertionError('refusing to clean the test runner group')
                    try:
                        os.killpg(group, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                worker.communicate(timeout=3)
                sibling.wait(timeout=3)

    def test_timeout_preserves_output_and_spares_sibling(self):
        self.exercise()

    def test_sigint_preserves_output_and_stops_owned_group(self):
        self.exercise(interrupt=True, timeout=10)

    def test_sigint_without_timeout_still_owns_and_stops_group(self):
        self.exercise(interrupt=True, timeout=None)

    def test_damaged_stdout_preserves_bytes_and_stops_workflow(self):
        self.exercise(damaged=True)
