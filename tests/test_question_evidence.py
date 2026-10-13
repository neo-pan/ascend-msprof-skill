"""Question reads preserve partial evidence, identity limits and stable references."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ascend_msprof_skill.application_events import read_application_events
from ascend_msprof_skill.evidence_binding import raw_reference, snapshot, verify_reference
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.joint_row import select_records
from ascend_msprof_skill.operator_evidence import normalize_operator, field_definition
from ascend_msprof_skill.question_evidence import read_question, read_question_from_dir, render_question
from ascend_msprof_skill.run_evidence import RunEvidence
from tests.helpers_shared import fresh_real_run


class QuestionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = fresh_real_run(Path(self.temp.name))
        write_evidence_model(self.run)

    def query(self, question=None, **kwargs):
        return RunEvidence.load(self.run).question_evidence(question, **kwargs)

    def test_app_only_target_with_extras_has_question_local_scope(self):
        from tests.helper_tests_multi_launch import declared_target, write_declared_target, write_app_launches
        run = Path(self.temp.name) / "app_only"
        write_declared_target(run, declared_target(("kernel_a", 2)))
        write_app_launches(run, ["kernel_a", "kernel_a", "helper_kernel"])
        write_evidence_model(run)
        result = read_question_from_dir(run, "application-timing", segment="app")
        context = result["context"]
        self.assertEqual(context["target_identity"]["status"], "missing_observed")
        self.assertEqual(context["readiness"]["allowed_claims"], [])
        scope = context["question_scope"][0]
        self.assertEqual(scope["target_identity"]["status"], "match")
        self.assertTrue(scope["declared_launches_present"])
        self.assertFalse(scope["count_complete"])
        self.assertEqual(scope["extra_counts"], {"helperkernel": 1})
        self.assertEqual(scope["artifacts"][0]["target_names"], ["kernel_a"])
        self.assertIn("describe recorded target task values", scope["artifacts"][0]["allowed_claims"])
        self.assertIn("rank complete-program hot paths", scope["blocked_claims"])
        self.assertEqual(result["facts"][0]["events"]["event_count"], 3)
        self.assertIn("describe recorded target task values", render_question(result))
        self.assertFalse(next(x for x in result["related_evidence"] if x["artifact"].endswith("benchmark_context.json"))["present"])

    def test_app_scope_preserves_partial_counts_and_selected_raw_gates(self):
        from tests.helper_tests_multi_launch import declared_target, write_declared_target, write_app_launches
        from ascend_msprof_skill._profiler_segments import segment_receipt_artifact
        for names, complete in [(["kernel_a"], False), (["kernel_a"] * 3, False),
                                (["helper_kernel"], False), (["kernel_a"] * 2, True)]:
            with self.subTest(names=names):
                run = Path(self.temp.name) / ("app_" + str(len(names)) + names[0])
                write_declared_target(run, declared_target(("kernel_a", 2)))
                write_app_launches(run, names)
                write_evidence_model(run)
                result = read_question_from_dir(run, "application-timing")
                scope = result["context"]["question_scope"][0]
                self.assertEqual(scope["declared_launches_present"], complete)
                self.assertEqual(bool(scope["artifacts"][0]["target_names"]), "kernel_a" in names)
                self.assertEqual(result["context"]["readiness"]["allowed_claims"], [])
                artifact = scope["artifacts"][0]["artifact"]
                raw = run / artifact
                original = raw.read_text()
                raw.write_text("Op Name,Task Duration(us)\nkernel_a,bad\n")
                self.assertEqual(read_question_from_dir(run, "application-timing")["context"]["question_scope"][0]["artifacts"][0]["allowed_claims"], [])
                raw.unlink()
                self.assertEqual(read_question_from_dir(run, "application-timing")["context"]["question_scope"][0]["artifacts"][0]["allowed_claims"], [])
                raw.write_text(original)
                receipt = run / segment_receipt_artifact("app")
                receipt.parent.mkdir(parents=True, exist_ok=True)
                receipt.write_text(json.dumps({"status": "failed"}))
                write_evidence_model(run)
                self.assertEqual(read_question_from_dir(run, "application-timing")["context"]["question_scope"][0]["artifacts"][0]["allowed_claims"], [])

    def test_app_scope_api_statistics_never_inherit_target_attribution(self):
        from tests.helper_tests_multi_launch import declared_target, write_declared_target, write_app_launches
        run = Path(self.temp.name) / "api_only_selection"
        write_declared_target(run, declared_target(("kernel_a", 2)))
        write_app_launches(run, ["kernel_a", "kernel_a"])
        path = next((run / "reports").rglob("op_summary_001.csv")).with_name("api_statistic_001.csv")
        path.write_text("API Name,Time(us)\naclrtLaunchKernel,300\n")
        write_evidence_model(run)
        result = read_question_from_dir(run, "application-timing", artifact=str(path.relative_to(run)))
        scope = result["context"]["question_scope"][0]
        self.assertTrue(scope["count_complete"])
        self.assertEqual(len(scope["artifacts"]), 1)
        self.assertEqual(scope["artifacts"][0]["allowed_claims"], ["describe recorded artifact statistics"])
        self.assertEqual(scope["artifacts"][0]["target_names"], [])
        self.assertNotIn("question_scope", read_question_from_dir(self.run, "pipe")["context"])

    def test_app_scope_does_not_borrow_target_values_from_another_artifact(self):
        from tests.helper_tests_multi_launch import declared_target, write_declared_target, write_app_launches, write_operator_launch
        run = Path(self.temp.name) / "separate_artifacts"
        write_declared_target(run, declared_target(("kernel_a", 2)))
        write_app_launches(run, ["kernel_a", "kernel_a"])
        write_operator_launch(run, "wrong_kernel", 0)
        raw = next((run / "reports" / "app").rglob("op_summary_001.csv"))
        helper = raw.with_name("task_time_001.csv")
        helper.write_text("kernel_name,task_time(us)\nhelper_kernel,40\n")
        write_evidence_model(run)
        result = read_question_from_dir(run, "application-timing")
        self.assertEqual(result["context"]["target_identity"]["status"], "mismatch")
        scope = result["context"]["question_scope"][0]
        target = next(x for x in scope["artifacts"] if x["group"] == "op_summary")
        self.assertEqual(target["target_names"], ["kernel_a"])
        selected = read_question_from_dir(run, "application-timing", artifact=str(helper.relative_to(run)))
        self.assertEqual(selected["context"]["question_scope"][0]["artifacts"][0]["target_names"], [])
        raw.write_text("Op Name,Op Name,Task Duration(us)\nkernel_a,helper_kernel,10\n")
        selected = read_question_from_dir(run, "application-timing", artifact=str(raw.relative_to(run)))
        self.assertEqual(selected["context"]["question_scope"][0]["artifacts"][0]["target_names"], [])

    def test_directory_entry_loads_once_and_can_skip_unused_navigation_actions(self):
        expected = self.query()
        with patch.object(RunEvidence, 'load', wraps=RunEvidence.load) as load:
            self.assertEqual(read_question_from_dir(self.run), expected)
            self.assertEqual(load.call_count, 1)
        with patch('ascend_msprof_skill.question_evidence._question_next_steps') as next_steps:
            result = read_question_from_dir(self.run, include_next_steps=False)
            next_steps.assert_not_called()
        self.assertEqual(result['binding'], expected['binding'])
        for actual, full in zip(result['questions'], expected['questions']):
            self.assertEqual(actual, {key: value for key, value in full.items()
                                     if key not in {'gaps', 'conditional_collection_actions', 'action_note'}})

    def test_unbounded_observations_are_complete_for_caller_delivery_pagination(self):
        result = read_question_from_dir(self.run, 'pipe', limit=None)
        for fact in result['facts']:
            self.assertEqual(len(fact['observations']), fact['observation_count'])
            self.assertIsNone(fact['next_offset'])
            for observation in fact['observations']:
                self.assertEqual(verify_reference(self.run, observation['reference'])['status'], 'verified')

    def test_unbounded_application_timing_matches_paginated_observations(self):
        result = read_question_from_dir(self.run, 'application-timing', limit=None)
        self.assertEqual({fact['group'] for fact in result['facts']},
                         {'op_summary', 'task_time', 'api_statistic', 'op_statistic'})
        self.assertEqual(verify_reference(self.run, result['binding'])['status'], 'verified')
        for fact in result['facts']:
            with self.subTest(artifact=fact['artifact']):
                observations = fact['timing']['observations']
                self.assertGreater(len(observations), 0)
                self.assertEqual(len(observations), fact['observation_count'])
                self.assertIsNone(fact['next_offset'])
                self.assertIsNone(fact['events'])
                paginated, offset = [], 0
                while offset is not None:
                    page = read_question_from_dir(
                        self.run, 'application-timing', artifact=fact['artifact'],
                        offset=offset, limit=2)['facts'][0]
                    paginated.extend(page['timing']['observations'])
                    offset = page['next_offset']
                self.assertEqual(paginated, observations)
                for observation in observations:
                    self.assertEqual(verify_reference(self.run, observation['reference'])['status'], 'verified')

    def test_application_event_pages_remain_available_after_unbounded_export(self):
        result = read_question_from_dir(self.run, 'application-timing', limit=None)
        fact = next(fact for fact in result['facts'] if fact['group'] == 'op_summary')
        first = read_question_from_dir(
            self.run, 'application-timing', artifact=fact['artifact'], limit=1)['facts'][0]['events']
        self.assertEqual(first['event_count'], 2)
        self.assertEqual(first['next_offset'], 1)
        second = read_question_from_dir(
            self.run, 'application-timing', artifact=fact['artifact'],
            offset=first['next_offset'], limit=1)['facts'][0]['events']
        self.assertIsNone(second['next_offset'])
        self.assertEqual([event['record'] for event in first['events'] + second['events']], [2, 3])
        self.assertEqual(first['events'][0]['times']['Task Duration(us)']['raw'], '42399.120')
        self.assertEqual(second['events'][0]['times']['Task Duration(us)']['raw'], '42058.480')
        self.assertFalse(first['relations'])
        self.assertEqual(second['relations'][0]['signed_end_to_start_us'], '0.880')
        for event in first['events'] + second['events']:
            self.assertEqual(verify_reference(self.run, event['reference'])['status'], 'verified')
        for reference in second['relations'][0]['references']:
            self.assertEqual(verify_reference(self.run, reference)['status'], 'verified')

    def test_pipe_remains_readable_independent_of_arithmetic(self):
        result = self.query('pipe', limit=1)
        self.assertEqual(result['questions'][0]['available_families'], ['pipe_utilization'])
        self.assertTrue(result['facts'])
        fact = result['facts'][0]
        self.assertEqual(len(fact['observations']), 1)
        ref = fact['observations'][0]['reference']
        raw = verify_reference(self.run, ref)
        self.assertEqual(raw['status'], 'verified')
        self.assertEqual(raw['records'][0]['record'], ref['record'])
        legacy = {key: ref[key] for key in ('artifact', 'record', 'field', 'column')}
        self.assertEqual(verify_reference(self.run, legacy)['status'], 'unbound')
        self.assertIn('minimum', result['context']['readiness']['meaning'].lower())
        self.assertIn("caller's formal report and measurement protocol", result['context']['readiness']['meaning'])
        rendered = render_question(result)
        self.assertIn(ref['sha256'], rendered)
        self.assertIn(result['context']['target_identity']['status'], rendered)
        self.assertIn('analysis/benchmark_context.json', rendered)
        self.assertNotIn('same_record', rendered)
        next_result = self.query('pipe', artifact=fact['artifact'], offset=fact['next_offset'], limit=1)
        self.assertNotEqual(next_result['facts'][0]['observations'][0]['metric'], fact['observations'][0]['metric'])

    def test_support_gap_visible_and_field_selection_reuses_parser(self):
        path = next((self.run / 'reports').rglob('PipeUtilization.csv'))
        lines = path.read_text().splitlines()
        path.write_text('\n'.join(line + (',future_metric' if i == 0 else ',4') for i, line in enumerate(lines))+'\n')
        write_evidence_model(self.run)
        result = self.query('pipe')
        item = next(x for x in result['inventory'] if x['artifact'] == str(path.relative_to(self.run)))
        self.assertIn('future_metric', item['unsupported_columns'])
        selected = self.query('pipe', artifact=item['artifact'], fields=['future_metric'])
        populations = selected['facts'][0]['selection']['groups']
        self.assertGreater(sum(x['fields']['future_metric']['unrecognized'] for x in populations), 0)
        self.assertFalse(selected['facts'][0]['field_definitions'][0]['recognized'])

    def test_snapshot_changes_but_unchanged_raw_reference_survives_followup(self):
        result = self.query('pipe')
        ref = result['facts'][0]['reference']
        self.assertEqual(verify_reference(self.run, result['binding'])['status'], 'verified')
        self.assertEqual(result['binding']['selection']['question'], 'pipe')
        other_page = self.query('pipe', limit=1)
        self.assertNotEqual(result['binding']['sha256'], other_page['binding']['sha256'])
        (self.run / 'reports' / 'new.csv').write_text('new\n1\n')
        self.assertEqual(verify_reference(self.run, result['binding'])['status'], 'stale')
        self.assertEqual(verify_reference(self.run, ref)['status'], 'verified')
        (self.run / ref['artifact']).write_text('changed\n1\n')
        self.assertEqual(verify_reference(self.run, ref)['status'], 'mismatch')

    def test_regenerated_summary_invalidates_derived_binding_only(self):
        result = self.query('pipe')
        ref = result['facts'][0]['reference']
        path = self.run / 'analysis/summary.json'
        path.write_text(path.read_text()+'\n')
        self.assertEqual(verify_reference(self.run, result['binding'])['status'], 'stale')
        self.assertEqual(verify_reference(self.run, ref)['status'], 'verified')

    def test_missing_raw_retains_other_admitted_artifacts(self):
        before = self.query()
        victim = next(x for x in before['inventory'] if x['group'] == 'pipe_utilization')
        (self.run / victim['artifact']).unlink()
        after = self.query()
        item = next(x for x in after['inventory'] if x['artifact'] == victim['artifact'])
        self.assertIsNone(item['reference'])
        self.assertIn('unavailable', item['reason'])
        self.assertTrue(any(x.get('numeric_observations', 0) for x in after['inventory']))

    def test_failed_collection_keeps_raw_audit_but_excludes_facts(self):
        retained = RunEvidence.load(self.run)
        result = self.query('pipe')
        segment = result['inventory'][0]['segment']
        from ascend_msprof_skill._profiler_segments import segment_receipt_artifact
        receipt = self.run / segment_receipt_artifact(segment)
        receipt.parent.mkdir(exist_ok=True)
        receipt.write_text(json.dumps({'status': 'failed'}))
        write_evidence_model(self.run)
        result = retained.question_evidence('pipe')
        self.assertFalse(result['facts'])
        self.assertTrue(all(not x['admitted'] for x in result['inventory']))
        self.assertEqual(result, self.query('pipe'))
        self.assertEqual(verify_reference(self.run, result['binding'])['status'], 'verified')
        self.assertEqual(verify_reference(self.run, result['inventory'][0]['reference'])['status'], 'verified')

    def test_context_change_during_query_load_is_rejected(self):
        retained = RunEvidence.load(self.run)
        original_load = RunEvidence.load

        def changing_load(root):
            loaded = original_load(root)
            path = self.run / 'analysis/summary.json'
            path.write_text(path.read_text() + '\n')
            return loaded

        with patch.object(RunEvidence, 'load', side_effect=changing_load):
            with self.assertRaisesRegex(ValueError, 'inputs changed'):
                retained.question_evidence('pipe')

    def test_reference_position_validation_precedes_pagination(self):
        path = self.run / 'reports/reference.csv'
        path.write_text('Metric,Value\nknown,4\n')
        reference = raw_reference(self.run, 'reports/reference.csv', record=2, field='Value', column=2)
        for offset in (0, 1):
            for invalid in ({'column': 3}, {'field': 'wrong'}, {'field': 'Metric'}):
                with self.subTest(offset=offset, invalid=invalid):
                    with self.assertRaises(ValueError):
                        verify_reference(self.run, {**reference, **invalid}, offset=offset)
        page = verify_reference(self.run, reference, offset=1)
        self.assertEqual(page['status'], 'verified')
        self.assertEqual(page['matched_records'], 1)
        self.assertEqual(page['records'], [])

    def test_long_form_support_gaps_identify_metric_names(self):
        path = self.run / 'reports/OPPROF_long/Memory.csv'
        path.parent.mkdir()
        for extra in ('', 'future_metric,4\n'):
            with self.subTest(extra=extra):
                path.write_text('Metric,Value\nGM_to_UB_bw_usage_rate(%),64\n' + extra)
                write_evidence_model(self.run)
                result = self.query('memory', artifact=str(path.relative_to(self.run)))
                item = result['inventory'][0]
                self.assertEqual(item['unsupported_columns'], [])
                self.assertEqual(item['unsupported_metrics'], ['future_metric'] if extra else [])
                self.assertEqual(result['facts'][0]['observations'][0]['value'], 64)
                rendered = render_question(result)
                self.assertIn('| GM_to_UB_bw_usage_rate(%) | 64', rendered)
                if extra:
                    self.assertIn('Unregistered metric names (audit only): `future_metric`', rendered)

    def test_timing_markdown_names_the_observed_api_and_task(self):
        folder = self.run / 'reports/PROF_names'
        folder.mkdir()
        for filename, content, name in (
            ('api_statistic_001.csv', 'Name,Time(us)\naclrtSynchronizeStream,1.5\n', 'aclrtSynchronizeStream'),
            ('task_time_001.csv', 'kernel_name,task_time(us)\nnamed_kernel,12.5\n', 'named_kernel'),
        ):
            path = folder / filename
            path.write_text(content)
            write_evidence_model(self.run)
            rendered = render_question(self.query('application-timing', artifact=str(path.relative_to(self.run))))
            self.assertIn('| Name | Field |', rendered)
            self.assertIn('| ' + name + ' |', rendered)

    def test_scope_selection_does_not_guess(self):
        with self.assertRaises(ValueError):
            self.query('pipe', segment='not-a-segment')
        with self.assertRaises(ValueError):
            self.query('memory', artifact='not-an-artifact')
        with self.assertRaises(ValueError):
            self.query('pipe', fields=['aiv_time(us)'])

    def test_question_gaps_prefer_analysis_and_existing_evidence_before_collection(self):
        for pattern in ('Memory*.csv', 'L2Cache.csv', 'ArithmeticUtilization.csv', 'ResourceConflictRatio.csv'):
            for path in (self.run / 'reports').rglob(pattern):
                path.unlink()
        logs = self.run / 'logs'
        logs.mkdir(exist_ok=True)
        (logs / 'command_msprof_op.txt').write_text('msprof op --aic-metrics=PipeUtilization\n')
        write_evidence_model(self.run)
        retained = RunEvidence.load(self.run)
        before = retained.question_evidence('memory')
        question = before['questions'][0]
        self.assertEqual([a['id'] for a in question['conditional_collection_actions']], ['collect_default_metric_followup'])
        self.assertEqual(question['conditional_collection_actions'][0]['necessity'], 'question_required')
        self.assertFalse(retained.question_evidence('pipe')['questions'][0]['conditional_collection_actions'])
        old_ref = retained.question_evidence('pipe')['facts'][0]['reference']
        folder = self.run / 'reports/followups/collect_default_metric_followup/OPPROF_002'
        folder.mkdir(parents=True)
        (folder / 'Memory.csv').write_text('Metric,Value\nGM_to_UB_bw_usage_rate(%),64\n')
        (folder / 'L2Cache.csv').write_text('sub_block_id,aiv_read_hit_rate(%)\nvector0,5\n')
        pending = retained.question_evidence('memory')['questions'][0]
        self.assertFalse(pending['conditional_collection_actions'])
        self.assertTrue(all('analyze' in gap['command'] for gap in pending['gaps']))
        write_evidence_model(self.run)
        after = retained.question_evidence('memory')
        self.assertEqual(set(after['questions'][0]['available_families']), {'memory', 'l2_cache'})
        self.assertFalse(after['questions'][0]['gaps'])
        self.assertEqual(verify_reference(self.run, before['binding'])['status'], 'stale')
        self.assertEqual(verify_reference(self.run, old_ref)['status'], 'verified')
        narrowed = retained.question_evidence('memory', segment='op')['questions'][0]
        self.assertFalse(narrowed['conditional_collection_actions'])
        self.assertTrue(all('outside' in gap['reason'] for gap in narrowed['gaps']))

    def test_generation_provenance_limit_travels_with_query_and_verification(self):
        from ascend_msprof_skill.evidence_binding import GENERATION_LIMIT
        result = self.query('pipe')
        self.assertIn(GENERATION_LIMIT, result['context']['limitations'])
        self.assertIn(GENERATION_LIMIT, render_question(result))
        self.assertIn(GENERATION_LIMIT, verify_reference(self.run, result['binding'])['meaning'])


class L2AndEventTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        (self.run / 'reports').mkdir()

    def test_real_l2_fixture_preserves_exact_percentages_and_sources(self):
        import shutil
        fixture = Path(__file__).parent / 'fixtures/real_l2cache_minimal/reports/OPPROF_001/L2Cache.csv'
        path = self.run / 'reports/L2Cache.csv'
        shutil.copyfile(fixture, path)
        evidence = normalize_operator(path, 'reports/L2Cache.csv', 'l2_cache', 'op', 'Default')
        values = {x.metric: x for x in evidence.observations}
        self.assertEqual(values['aic_read_hit_rate(%)'].value, 69.565216)
        self.assertEqual(values['aic_write_hit_rate(%)'].value, 100)
        self.assertEqual(values['aic_read_hit_rate(%)'].source.record, 2)
        self.assertEqual(len(values), 6)
        path.write_text(path.read_text() + 'bad row\n')
        self.assertTrue(normalize_operator(path, 'reports/L2Cache.csv', 'l2_cache', 'op', 'Default').issues)

    def test_independent_maxima_keep_distinct_bound_records(self):
        path = self.run / 'reports/OPPROF_001/PipeUtilization.csv'
        path.parent.mkdir()
        path.write_text('block_id,sub_block_id,aiv_time(us),aiv_vec_ratio\n0,vector0,10,0.1\n1,vector0,1,0.9\n')
        write_evidence_model(self.run)
        result = RunEvidence.load(self.run).question_evidence('pipe')
        values = {x['metric']: x for x in result['facts'][0]['observations']}
        self.assertEqual(values['aiv_time(us)']['source']['record'], 2)
        self.assertEqual(values['aiv_vec_ratio']['source']['record'], 3)
        for item in values.values():
            verified = verify_reference(self.run, item['reference'])
            row = verified['records'][0]
            self.assertEqual(float(row['cells'][item['source']['column']-1]['raw']), item['value'])
        selected = RunEvidence.load(self.run).question_evidence('pipe', artifact=str(path.relative_to(self.run)), fields=['aiv_time(us)'])
        self.assertEqual(selected['facts'][0]['core_time_distributions'][0]['maximum']['source']['record'], 2)

    def test_all_l2_directions_preserve_semantics_and_cell_states(self):
        path = self.run / 'reports/L2Cache.csv'
        columns = ['block_id','sub_block_id'] + [f'{core}_{direction}_hit_rate(%)'
            for core in ('aic','aiv') for direction in ('read','write','total')]
        path.write_text(','.join(columns)+'\n0,cube0,0,25,10,NA,NA,NA\n0,vector0,NA,NA,NA,0.259572,0.065062,0.220751\n')
        evidence = normalize_operator(path, 'reports/L2Cache.csv', 'l2_cache', 'op', 'Default')
        self.assertEqual(len(evidence.observations), 6)
        self.assertTrue(all(x.sum is None for x in evidence.field_populations))
        result = select_records(self.run, 'reports/L2Cache.csv', 'l2_cache', columns[2:]+['unknown'], summary_only=True)
        self.assertTrue(all(x['unit'] == '%' for x in result['fields'][:-1]))
        self.assertIn('denominator', field_definition('l2_cache', columns[2]))
        vector = next(x for x in result['groups'] if dict(x['scope']).get('sub_block_id') == 'vector0')
        self.assertEqual(vector['fields']['aiv_read_hit_rate(%)']['minimum'], 0.259572)
        self.assertEqual(vector['fields']['aic_read_hit_rate(%)']['missing'], 1)
        self.assertEqual(vector['fields']['unknown']['missing_column'], 1)

    def test_default_l2_page_carries_shared_limits_in_json_and_markdown(self):
        path = self.run / 'reports/OPPROF_001/L2Cache.csv'
        path.parent.mkdir()
        path.write_text('block_id,sub_block_id,aiv_read_hit_rate(%),aiv_write_hit_rate(%)\n'
                        '0,vector0,25,50\n')
        write_evidence_model(self.run)
        result = RunEvidence.load(self.run).question_evidence('memory', artifact='reports/OPPROF_001/L2Cache.csv')
        limits = result['facts'][0]['field_limits']
        self.assertEqual(len(limits), 1)
        self.assertEqual(limits[0]['fields'], ['aiv_read_hit_rate(%)', 'aiv_write_hit_rate(%)'])
        self.assertIn('miss-not-allocate', limits[0]['constraints']['denominator'])
        rendered = render_question(result)
        self.assertEqual(rendered.count('no overall hit rate without matching request denominators'), 1)
        page = RunEvidence.load(self.run).question_evidence('memory', artifact='reports/OPPROF_001/L2Cache.csv', offset=1, limit=1)
        self.assertEqual(page['facts'][0]['field_limits'][0]['fields'], ['aiv_write_hit_rate(%)'])
        empty = RunEvidence.load(self.run).question_evidence('memory', artifact='reports/OPPROF_001/L2Cache.csv', offset=2)
        self.assertEqual(empty['facts'][0]['field_limits'], [])

    def events(self, rows, **kwargs):
        path = self.run / 'reports/op_summary.csv'
        path.write_text('Device_id,Stream ID,Op Name,Task Start Time(us),Task Duration(us),Task Wait Time(us)\n'+rows)
        return read_application_events(path, 'reports/op_summary.csv', **kwargs)

    def test_exact_interval_preserves_repeated_launches_and_sources(self):
        result = self.events('0,47,cast,1790602788560636.620,36.480,0\n0,47,compute,1790602788561296.900,41.280,623.800\n0,47,compute,1790602788561396.900,41.280,58.720\n', offset=1, limit=1)
        self.assertEqual(result['event_count'], 3)
        relation = result['relations'][0]
        self.assertEqual(relation['signed_end_to_start_us'], '623.800')
        self.assertEqual(relation['left_record'], 2)
        self.assertEqual(result['next_offset'], 2)
        self.assertEqual(relation['sources'][0]['column'], 4)

    def test_overlap_and_cross_stream_are_not_idle(self):
        result = self.events('0,1,a,10,5,0\n0,2,b,11,2,0\n0,1,c,12,2,0\n')
        self.assertEqual(len(result['relations']), 1)
        self.assertEqual(result['relations'][0]['kind'], 'overlap')
        self.assertEqual(result['relations'][0]['signed_end_to_start_us'], '-3')
        result = self.events('0,,a,10,5,0\n0,,b,20,2,0\n')
        self.assertFalse(result['relations'])

    def test_invalid_event_prevents_false_adjacency_but_raw_survives(self):
        result = self.events('0,1,a,10,2,0\n0,1,b,NA,2,0\n0,1,c,20,2,0\n')
        self.assertFalse(result['relations'])
        self.assertEqual(len(result['events']), 3)
        self.assertTrue(result['issues'])
