"""Positive CANN 8.5.2 simulator evidence from a real standalone AIV kernel."""
import hashlib
import io
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from tests.helpers_shared import unittest
from ascend_msprof_skill import extract_simulator_hotspots, plot_timeline
from ascend_msprof_skill.simulator_hotspot_model import build_simulator_hotspot_model


FIXTURE = Path(__file__).parent / 'fixtures/real_cann852_simulator_minimal'


class Cann852SimulatorTests(unittest.TestCase):
    def test_sourced_trace_instruction_and_kernel_mapping_agree(self):
        origin = json.loads((FIXTURE / 'origin.json').read_text())
        for record in origin['files']:
            data = (FIXTURE / record['artifact']).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(),
                             record['fixture_sha256'])
            self.assertNotRegex(data.decode(), r'/(?:root|afs-data)/')
        source = FIXTURE / 'kernel/kernel.cpp'
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), origin['source_sha256'])
        lines = source.read_text().splitlines()
        self.assertIn('AscendC::Add', lines[36])
        self.assertIn('iteration < 32', lines[35])
        self.assertIn('KERNEL_TYPE_AIV_ONLY', source.read_text())
        stdout = (FIXTURE / 'logs/msprof_simulator.stdout').read_text()
        self.assertIn('<ProfInit> Start profiling on kernel: biu_native_vector_kernel', stdout)
        result = json.loads(next(line.split('=', 1)[1] for line in stdout.splitlines()
                                 if line.startswith('RESULT_JSON=')))
        self.assertEqual(result['correctness'], 'exact_pass')
        self.assertEqual(result['launches'], 1)

        trace = json.loads(next((FIXTURE / 'reports').rglob('trace.json')).read_text())
        events = trace['traceEvents']
        self.assertEqual(trace['displayTimeUnit'], 'ns')
        self.assertEqual(len(events), 802)
        self.assertTrue(all(item['ph'] == 'X' for item in events))
        self.assertEqual(sum(item['dur'] > 0 for item in events), 689)
        adds = [item for item in events if item['name'] == 'VADD']
        self.assertEqual(len(adds), 32)
        self.assertTrue(all(item['pid'] == 'core0.veccore0' and item['tid'] == 'VECTOR'
                            and 'kernel/kernel.cpp:37' in item['args']['code'] for item in adds))
        # Chrome trace timestamps/durations are us even with displayTimeUnit=ns.
        self.assertAlmostEqual(sum(item['dur'] for item in adds), 0.96, places=6)

        model = build_simulator_hotspot_model(FIXTURE.resolve())
        self.assertEqual((len(model.source_lines), len(model.instructions), len(model.pipeline_events)), (76, 176, 7))
        self.assertEqual(sum(row.event_count for row in model.pipeline_events), 802)
        row = next(row for row in model.source_lines if row.code == 'kernel/kernel.cpp:37')
        self.assertEqual(row.source_context.status, 'available')
        self.assertEqual(row.source_context.artifact, 'kernel/kernel.cpp')
        self.assertIn('vector_compute', row.source_context.tags)
        metrics = {metric.field: metric.value for metric in row.metrics}
        self.assertEqual(metrics, {'call_count': 384, 'cycles': 6272, 'running_time(us)': 1.07})
        instruction = next(row for row in model.instructions if row.instr == 'VADD')
        metrics = {metric.field: metric.value for metric in instruction.metrics}
        self.assertEqual(metrics, {'call_count': 32, 'cycles': 1728, 'running_time(us)': 0.96})

    def test_timeline_and_hotspot_commands_render_real_intervals_and_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / 'simulator'
            shutil.copytree(FIXTURE, run)
            with mock.patch('sys.stdout', new_callable=io.StringIO):
                extract_simulator_hotspots.main(['--run-dir', str(run)])
                plot_timeline.main(['--run-dir', str(run), '--svg'])
            index = json.loads((run / 'analysis/timeline_svg_index.json').read_text())
            self.assertEqual(len(index), 1)
            self.assertEqual(index[0]['measurement_source'], 'simulator')
            self.assertEqual(index[0]['source_sha256'], hashlib.sha256((run / index[0]['artifact']).read_bytes()).hexdigest())
            svg = (run / index[0]['svg']).read_text()
            self.assertEqual(svg.count('<title>'), 689)
            self.assertIn('core0.veccore0 / VECTOR', svg)
            self.assertIn('core0.veccore0 / MTE2', svg)
            self.assertIn('Simulator time (us)', svg)
            hotspots = (run / 'analysis/simulator_hotspots.txt').read_text()
            self.assertIn('source_context: kernel/kernel.cpp:37', hotspots)
            self.assertIn('AscendC::Add', hotspots)
            self.assertIn('VADD; pipe=VECTOR', hotspots)
