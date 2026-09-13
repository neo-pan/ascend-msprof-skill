"""Simulator normalization, units, partial validity and shared consumption."""
import json
import tempfile
from pathlib import Path
from unittest import mock

from tests.helpers_shared import unittest
from pydantic import ValidationError
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.run_evidence import RunEvidence, RunEvidenceError
from ascend_msprof_skill.simulator_hotspot_model import build_simulator_hotspot_model
from ascend_msprof_skill.simulator_types import SimulatorModel


class SimulatorNormalizationTests(unittest.TestCase):
    def test_published_schema_is_generated_from_the_model(self):
        path = Path(__file__).resolve().parents[1] / 'skills/ascend-msprof-skill/data/simulator.schema.json'
        self.assertEqual(json.loads(path.read_text()), SimulatorModel.model_json_schema())

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.folder = self.root / 'reports/OPPROF_001/simulator'
        self.folder.mkdir(parents=True)

    def csv(self, text, name='core0_code_exe.csv'):
        path = self.folder / name
        path.write_text(text)
        return path

    def trace(self, events, *, folder=None):
        path = (folder or self.folder) / 'trace.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'displayTimeUnit': 'ns', 'traceEvents': events}))
        return path

    def test_invalid_process_identity_cites_pid_and_preserves_sibling(self):
        self.trace([{'ph': 'X', 'tid': 0, 'pid': {}, 'dur': 99}, {'ph': 'X', 'tid': 0, 'pid': 1, 'dur': 12}])
        model = build_simulator_hotspot_model(self.root)
        issues = [issue for item in model.inputs for issue in item.issues if issue.code == 'invalid_identity']
        self.assertEqual([issue.source.field for issue in issues], ['traceEvents[0].pid'])
        self.assertEqual(len(model.pipeline_events), 1)

    def test_counts_are_integers_and_partial_metrics_do_not_become_zero(self):
        self.csv('code,call_count,cycles,running_time(us)\nkernel.cpp:1,1.5,2,3\nkernel.cpp:1,4,,\n')
        model = build_simulator_hotspot_model(self.root)
        row = model.source_lines[0]
        metrics = {m.field: m for m in row.metrics}
        self.assertIsNone(metrics['call_count'].total)
        self.assertEqual(metrics['call_count'].maximum, 4)
        self.assertIs(type(metrics['call_count'].maximum), int)
        self.assertEqual(metrics['call_count'].records, (3,))
        self.assertIsNone(metrics['cycles'].total)
        self.assertEqual(metrics['cycles'].maximum, 2)
        self.assertEqual(metrics['running_time(us)'].maximum, 3)
        self.assertEqual(metrics['running_time(us)'].statistic, 'maximum')
        self.assertEqual({i.code for i in model.inputs[0].issues}, {'invalid_number', 'missing_value'})
        self.assertEqual(SimulatorModel.model_validate(model.model_dump(mode='json')), model)

    def test_exact_fields_duplicate_columns_and_bad_rows_preserve_independent_metrics(self):
        self.csv('code,call_count,cycles,running_time(us),running_time(us)\nkernel.cpp:1,1,2,3,99\nbroken,1,2\n')
        model = build_simulator_hotspot_model(self.root)
        self.assertEqual(model.inputs[0].parser_status, 'invalid')
        self.assertEqual({m.field for m in model.source_lines[0].metrics}, {'call_count', 'cycles'})
        self.assertEqual({i.code for i in model.inputs[0].issues}, {'duplicate_header', 'row_width'})
        self.csv('code,time\nkernel.cpp:1,12\n')
        model = build_simulator_hotspot_model(self.root)
        self.assertEqual(model.source_lines[0].metrics, ())
        self.assertIn('unsupported_fields', {i.code for i in model.inputs[0].issues})

    def test_overflow_preserves_maximum_and_microsecond_units(self):
        self.csv('code,call_count,cycles,running_time(us)\nkernel.cpp:1,1,2,1e308\nkernel.cpp:1,1,2,1e308\n')
        self.trace([{'ph': 'X', 'name': 'copy', 'pid': 1, 'tid': 0, 'dur': 1e308}] * 2)
        result = write_evidence_model(self.root)
        model = RunEvidence.load(self.root).simulator_hotspots()
        self.assertIsNone(model.source_lines[0].primary_metric.total)
        self.assertEqual(model.source_lines[0].primary_metric.maximum, 1e308)
        self.assertIsNone(model.pipeline_events[0].duration_us)
        self.assertEqual(model.pipeline_events[0].max_duration_us, 1e308)
        signal = next(s for s in result.summary.analysis_dimensions[-1].signals if s.kind == 'simulator_trace')
        self.assertEqual((signal.value, signal.unit, signal.statistic), (1e308, 'us', 'maximum'))
        self.assertEqual(model.inputs[-1].display_time_unit, 'ns')
        json.dumps(model.model_dump(mode='json'), allow_nan=False)

    def test_trace_selection_is_per_collection_and_thread_zero_is_preserved(self):
        self.trace([{'ph': 'X', 'tid': 0, 'dur': 12.5}])
        self.trace([{'ph': 'X', 'tid': 0, 'dur': 100}], folder=self.folder / 'core0')
        other = self.root / 'reports/OPPROF_002/simulator/core0'
        self.trace([{'ph': 'X', 'tid': 0, 'dur': 7}], folder=other)
        model = build_simulator_hotspot_model(self.root)
        self.assertEqual([r.duration_us for r in model.pipeline_events], [12.5, 7])
        self.assertEqual(len(model.inputs), 3)
        self.assertEqual(len(model.selected_trace_artifacts), 2)
        self.assertTrue(all(r.tid == 0 for r in model.pipeline_events))

    def test_source_statistics_do_not_combine_distinct_core_files(self):
        self.csv('code,call_count,cycles,running_time(us)\nkernel.cpp:1,1,2,3\n')
        self.csv('code,call_count,cycles,running_time(us)\nkernel.cpp:1,1,2,7\n', 'core1_code_exe.csv')
        model = build_simulator_hotspot_model(self.root)
        self.assertEqual([r.primary_metric.total for r in model.source_lines], [7, 3])
        self.assertEqual(len({r.artifact for r in model.source_lines}), 2)

    def test_simulator_files_are_read_once_and_rendering_uses_the_model(self):
        csv = self.csv('instr,addr,pipe,call_count,cycles,running_time(us)\nWAIT_FLAG,0,MTE2,2,3,4\n', 'core0_instr_exe.csv')
        trace = self.trace([{'ph': 'B', 'name': 'WAIT_FLAG'}, {'ph': 'E', 'name': 'WAIT_FLAG'}])
        original = Path.open
        reads = []
        def track(path, *args, **kwargs):
            if path in {csv, trace}:
                reads.append(path)
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, 'open', track):
            result = write_evidence_model(self.root)
        self.assertEqual(reads.count(csv), 1)
        self.assertEqual(reads.count(trace), 1)
        evidence = RunEvidence.load(self.root)
        model = evidence.simulator_hotspots()
        self.assertEqual(model.sync_events[0].trace_events, 2)
        self.assertEqual(next(m for m in model.instructions[0].metrics if m.field == 'call_count').total, 2)
        self.assertNotIn('csv_call_count', model.sync_events[0].model_dump())
        payload = json.loads(result.summary_path.read_text())
        signal = next(s for s in payload['analysis_dimensions'][-1]['signals'] if s['kind'] == 'simulator_instruction')
        signal['value'] = 99
        result.summary_path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(RunEvidenceError, 'simulator dimension'):
            RunEvidence.load(self.root)

    def test_persisted_counts_reject_bool_and_fractional_values(self):
        self.csv('code,call_count,cycles,running_time(us)\nkernel.cpp:1,1,2,3\n')
        model = build_simulator_hotspot_model(self.root)
        for value in (True, 1.5, '1'):
            payload = model.model_dump(mode='json')
            metric = next(m for m in payload['source_lines'][0]['metrics'] if m['field'] == 'call_count')
            metric['maximum'] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                SimulatorModel.model_validate(payload)

    def test_bad_trace_values_preserve_valid_siblings_and_standard_json_output(self):
        path = self.folder / 'trace.json'
        path.write_text('{"traceEvents":[{"ph":"X","tid":0,"dur":1e309},'
                        '{"ph":"X","tid":0,"dur":2},{"name":"SET_FLAG","ph":{}}]}')
        result = write_evidence_model(self.root)
        model = RunEvidence.load(self.root).simulator_hotspots()
        self.assertEqual((model.pipeline_events[0].event_count, model.pipeline_events[0].record_count), (1, 2))
        self.assertIsNone(model.pipeline_events[0].duration_us)
        self.assertEqual(model.pipeline_events[0].max_duration_us, 2)
        self.assertEqual(model.pipeline_events[0].maximum_source.field, 'traceEvents[1].dur')
        self.assertIn('1e309', path.read_text())
        self.assertIn('simulator_source_pipeline', result.summary.evidence_readiness.available_evidence_families)
        json.dumps(model.model_dump(mode='json'), allow_nan=False)
        self.assertTrue(result.raw_artifact_index.artifacts)

    def test_simulator_source_references_are_checked_against_normalized_inventory(self):
        self.csv('code,call_count,cycles,running_time(us)\nkernel.cpp:1,1,2,3\n')
        self.trace([{'ph': 'X', 'tid': 0, 'dur': 4}])
        model = build_simulator_hotspot_model(self.root)
        for change in ('code', 'column', 'trace_index', 'duplicate', 'csv_identity_record'):
            payload = model.model_dump(mode='json')
            if change == 'code':
                payload['source_lines'][0]['line'] = 2
            elif change == 'column':
                payload['source_lines'][0]['metrics'][0]['maximum_source']['column'] = 99
            elif change == 'trace_index':
                payload['pipeline_events'][0]['maximum_source']['field'] = 'traceEvents[99].dur'
            elif change == 'csv_identity_record':
                payload['source_lines'][0]['identity_source']['record'] = 1
            else:
                payload['source_lines'].append(payload['source_lines'][0])
            with self.subTest(change=change), self.assertRaises(ValidationError):
                SimulatorModel.model_validate(payload)

    def test_csv_blank_records_preserve_exact_source_ordinals(self):
        self.csv('code,call_count,cycles,running_time(us)\n\n\nkernel.cpp:1,1,2,3\n')
        model = build_simulator_hotspot_model(self.root)
        self.assertEqual(model.inputs[0].row_count, 1)
        self.assertEqual(model.source_lines[0].identity_source.record, 4)
        self.assertTrue(all(metric.records == (4,) for metric in model.source_lines[0].metrics))
        self.assertEqual(SimulatorModel.model_validate(model.model_dump(mode='json')), model)

    def test_trace_aggregate_counts_are_bounded_by_input_records(self):
        self.trace([
            {'ph': 'X', 'tid': 0, 'dur': 4, 'name': 'flow', 'cat': 'data'},
            {'ph': 'X', 'tid': 1, 'dur': 2},
            {'name': 'SET_FLAG', 'ph': 'B'},
            {'name': 'GM_TO_UB', 'pid': 'MTE Throughput', 'ph': 'C', 'args': {'throughput(MB/s)': 12}},
        ])
        result = write_evidence_model(self.root)
        model = RunEvidence.load(self.root).simulator_hotspots()
        # One event can contribute to different families; their counts are not summed together.
        self.assertEqual(model.inputs[0].row_count, 4)
        path = self.root / 'analysis/simulator_hotspots.json'
        original = path.read_bytes()
        for group, field in (('pipeline_events', 'record_count'), ('flow_categories', 'count'),
                             ('sync_events', 'trace_events'), ('mte_throughput', 'samples')):
            payload = model.model_dump(mode='json')
            payload[group][0][field] = 5
            if group == 'pipeline_events':
                payload[group][0]['event_count'] = 5
            with self.subTest(group=group):
                with self.assertRaisesRegex(ValidationError, 'counts exceed input inventory'):
                    SimulatorModel.model_validate(payload)
                with self.assertRaisesRegex(RunEvidenceError, 'counts exceed input inventory'):
                    RunEvidence.from_loaded(self.root, result.summary, raw_artifact_index=result.raw_artifact_index,
                                            simulator_hotspots=payload)
                path.write_text(json.dumps(payload))
                with self.assertRaisesRegex(RunEvidenceError, 'counts exceed input inventory'):
                    RunEvidence.load(self.root)
                path.write_bytes(original)
        # Individually bounded buckets may still exceed the same input collectively.
        payload = model.model_dump(mode='json')
        for row in payload['pipeline_events']:
            row['event_count'] = row['record_count'] = 3
        with self.assertRaisesRegex(ValidationError, 'counts exceed input inventory'):
            SimulatorModel.model_validate(payload)

    def test_trace_array_layout_survives_summary_report_and_inspection_citations(self):
        from ascend_msprof_skill.generate_report import build_report_from_evidence
        events = [{'ph': 'X', 'tid': 0, 'dur': 2}, {'name': 'flow', 'cat': 'data'},
                  {'name': 'SET_FLAG', 'ph': 'B'}]
        path = self.folder / 'trace.json'
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                path.write_text(json.dumps({'traceEvents': events} if wrapped else events))
                raw = path.read_bytes()
                result = write_evidence_model(self.root)
                loaded = RunEvidence.load(self.root)
                prefix = 'traceEvents' if wrapped else ''
                signals = next(d.signals for d in result.summary.analysis_dimensions if d.id == 'source_pipeline_context')
                by_kind = {item.kind: item for item in signals}
                self.assertEqual(by_kind['simulator_trace'].field, f'{prefix}[].dur')
                self.assertIn(f'{prefix}[].dur;', by_kind['simulator_trace'].field_ref)
                self.assertEqual(by_kind['simulator_flow'].field, f'{prefix}[].cat')
                self.assertEqual(by_kind['simulator_sync_event'].field, f'{prefix}[].name')
                report = build_report_from_evidence(loaded)
                self.assertIn(f'{prefix}[].dur', report)
                targets = loaded.inspection_targets()
                self.assertTrue(any(f'{prefix}[].dur' in (item.field_ref or '') for item in targets))
                if not wrapped:
                    self.assertNotIn('traceEvents', json.dumps([item.model_dump(mode='json') for item in signals]))
                self.assertEqual(path.read_bytes(), raw)

    def test_invalid_normalized_simulator_is_distinct_from_missing_and_keeps_natural_measurement(self):
        from tests.helpers_shared import ROOT
        from ascend_msprof_skill.collect_benchmark_context import import_benchmark
        from ascend_msprof_skill.run_assessment import assess_run
        result = write_evidence_model(self.root)
        import_benchmark(self.root, ROOT / 'skills/ascend-msprof-skill/assets/benchmark-single-case.json')
        path = self.root / 'analysis/simulator_hotspots.json'
        for raw in ('{', 'null', '[]', '{"inputs":[],"inputs":[]}',
                    '{"simulator_hotspot_model_schema_version":"1.1"}'):
            with self.subTest(raw=raw):
                path.write_text(raw)
                for load in (lambda: RunEvidence.load(self.root),
                             lambda: RunEvidence.load_report(self.root, result.summary),
                             lambda: RunEvidence.from_report_inputs(self.root, result.summary)):
                    with self.assertRaisesRegex(RunEvidenceError, 'invalid analysis/simulator_hotspots.json'):
                        load()
                evidence = RunEvidence.load_assessment(self.root)
                self.assertFalse(evidence.summary_present())
                self.assertIsNone(evidence.simulator_hotspots())
                self.assertEqual(assess_run(evidence).model_dump(mode="json")['performance_assessment']['eligibility']['status'], 'eligible')
                self.assertIn('invalid analysis/simulator_hotspots.json', '\n'.join(evidence.warnings()))
                self.assertEqual(path.read_text(), raw)
        path.unlink()
        self.assertTrue(RunEvidence.load(self.root).summary_present())
