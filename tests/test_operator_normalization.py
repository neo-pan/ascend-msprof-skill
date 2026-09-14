"""Operator raw inputs and their typed report/coverage consumers."""
import json
import tempfile
from pathlib import Path
from unittest import mock

from tests.helpers_shared import unittest
from pydantic import ValidationError
from ascend_msprof_skill.operator_evidence import OperatorEvidence, normalize_operator, select_operator_primary
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.run_evidence import RunEvidence, RunEvidenceError
from ascend_msprof_skill.generate_report import build_report


class OperatorNormalizationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def artifact(self, text, filename="OpBasicInfo.csv", root="OPPROF_001"):
        path = self.root / "reports" / "op" / root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def normalize(self, text, group="op_basic_info", filename="OpBasicInfo.csv"):
        path = self.artifact(text, filename)
        return normalize_operator(path, path.relative_to(self.root).as_posix(), group, "op", "Default")

    def test_core_time_distribution_preserves_subblocks_devices_and_locations(self):
        raw = ("Device Id,block_id,sub_block_id,aiv_time(us),aiv_scalar_time(us),aiv_scalar_ratio\n"
               "0,0,vector0,750,749,.5\n"
               "0,234,vector0,824.903748,824.717529,.6\n"
               "0,255,vector0,68146.804688,68114.367188,2.110634\n"
               "0,0,vector1,1,0,0\n"
               "0,1,vector1,1,0,0\n"
               "1,0,vector0,12,11,.3\n"
               "0,2,vector0,N/A,N/A,N/A\n")
        path = self.artifact(raw, "PipeUtilization.csv")
        self.artifact("Op Name,Task Duration(us),Current Freq,Rated Freq\nkernel,32272,800,1800\n")
        result = write_evidence_model(self.root)
        artifact = result.summary.headlines['pipe_utilization'].artifacts[0]
        distributions = {(d.metric, tuple(d.scope)): d for d in artifact.core_time_distributions}
        item = distributions['aiv_time(us)', (('Device Id', '0'), ('sub_block_id', 'vector0'))]
        self.assertEqual(item.valid_count, 3)
        self.assertEqual(item.median_us, 824.903748)
        self.assertEqual(item.maximum.value, 68146.804688)
        self.assertEqual(dict(item.maximum.scope)['block_id'], '255')
        self.assertEqual((item.maximum.source.record, item.maximum.source.column), (4, 4))
        self.assertEqual(dict(item.second_largest.scope)['block_id'], '234')
        tied = distributions['aiv_time(us)', (('Device Id', '0'), ('sub_block_id', 'vector1'))]
        self.assertEqual((tied.valid_count, tied.maximum.value, tied.second_largest.value), (2, 1, 1))
        single = distributions['aiv_time(us)', (('Device Id', '1'), ('sub_block_id', 'vector0'))]
        self.assertIsNone(single.second_largest)
        loaded = RunEvidence.load(self.root).summary()
        self.assertEqual(loaded.headlines['pipe_utilization'], result.summary.headlines['pipe_utilization'])
        self.assertIn('Per-block Time Distributions', build_report(loaded, self.root))
        self.assertIn('block_id=255', build_report(loaded, self.root))
        self.assertEqual(path.read_text(), raw)
        self.assertEqual(result.summary.measurement_quality.frequency.groups[0].below_rated_launch_count, 1)

    def test_metadata_and_frequency_are_not_task_duration(self):
        artifact = self.normalize("Op Name,Op Type,Block Dim,Mix Block Dim,Current Freq,Rated Freq\nkernel,Add,8,N/A,1650,1800\n")
        self.assertEqual(artifact.launch_name, "kernel")
        self.assertEqual({item.metric: item.value for item in artifact.metadata}, {"name": "kernel", "op_type": "Add", "block_dim": 8})
        self.assertTrue(all(item.statistic == "frequency" and item.unit == "MHz" for item in artifact.observations))
        self.assertIsNone(select_operator_primary((artifact,)).selected)
        result = write_evidence_model(self.root)
        frequency = result.summary.measurement_quality.frequency
        self.assertEqual(frequency.groups[0].below_rated_launch_count, 1)
        self.assertIsNone(RunEvidence.load(self.root).primary_headline())
        self.assertIn("Block Dim", build_report(result.summary, self.root))

    def test_block_count_requires_integer_and_does_not_destroy_timing(self):
        for token in ("1.5", "True", "NaN"):
            with self.subTest(token=token):
                artifact = self.normalize(f"Op Name,Task Duration(us),Block Dim\nkernel,12,{token}\n")
                self.assertEqual(artifact.observations[0].value, 12)
                self.assertFalse(any(item.metric == "block_dim" for item in artifact.metadata))
                self.assertIn("invalid_metadata", {item.code for item in artifact.issues})

    def test_oversized_integer_preserves_timing_through_report(self):
        import sys
        if not hasattr(sys, 'get_int_max_str_digits') or not sys.get_int_max_str_digits():
            self.skipTest('runtime has no integer string conversion limit')
        token = '9' * (sys.get_int_max_str_digits() + 1)
        path = self.artifact(f'Op Name,Task Duration(us),Block Dim\nkernel,12,{token}\n')
        raw = path.read_bytes()
        result = write_evidence_model(self.root)
        artifact = result.summary.headlines["op_basic_info"].artifacts[0]
        self.assertEqual(artifact.observations[0].value, 12)
        issue = next(issue for issue in artifact.issues if issue.code == 'invalid_metadata')
        self.assertEqual((issue.source.field, issue.source.record, issue.source.column), ('Block Dim', 2, 3))
        self.assertTrue(RunEvidence.load(self.root).summary_present())
        self.assertIn('12', build_report(result.summary, self.root))
        self.assertEqual(path.read_bytes(), raw)

    def test_equal_metadata_aliases_keep_locations(self):
        artifact = self.normalize('Op Name,Task Duration(us),Block Dim,blockdim\nkernel,12,8,08\n')
        item = next(item for item in artifact.metadata if item.metric == 'block_dim')
        self.assertEqual(item.value, 8)
        self.assertEqual(item.source.column, 3)
        self.assertEqual([(ref.field, ref.column) for ref in item.aliases], [('blockdim', 4)])
        self.assertEqual(type(artifact).model_validate_json(artifact.model_dump_json()), artifact)
        data = artifact.model_dump(mode='json')
        next(row for row in data['metadata'] if row['metric'] == 'block_dim')['aliases'][0]['record'] = 3
        with self.assertRaises(ValidationError):
            type(artifact).model_validate(data)

    def test_alias_conflicts_cannot_establish_identity(self):
        artifact = self.normalize("Op Name,op_name,Task Duration(us)\nkernel,other,12\n")
        self.assertIsNone(artifact.launch_name)
        self.assertIsNone(artifact.observations[0].name)
        self.assertEqual(artifact.launch_counts[0].name, "")
        self.assertIn("alias_conflict", {item.code for item in artifact.issues})

    def test_units_and_statistics_stay_distinct(self):
        ratio = self.normalize("sub_block_id,aic_cube_ratio\ncube0,.25\n", "arithmetic_utilization", "ArithmeticUtilization.csv")
        percentage = self.normalize("sub_block_id,aic_total_hit_rate(%)\ncube0,25\n", "l2_cache", "L2Cache.csv")
        memory = self.normalize("sub_block_id,GM_to_UB_datas(KB),L1_to_GM_datas(KB)(estimate),aiv_gm_to_ub_bw(GB/s)\nvector0,2,3,4\n", "memory", "Memory.csv")
        self.assertEqual((ratio.observations[0].value, ratio.observations[0].unit), (.25, "ratio"))
        self.assertEqual((percentage.observations[0].value, percentage.observations[0].unit), (25, "%"))
        self.assertEqual({(item.unit, item.statistic) for item in memory.observations}, {("KB", "volume"), ("KB", "estimated_volume"), ("GB/s", "bandwidth")})

    def test_long_form_uses_actual_value_cell_and_metric_label(self):
        artifact = self.normalize("Metric,Value\nGM_to_UB_bw_usage_rate(%),64\n", "memory", "Memory.csv")
        item = artifact.observations[0]
        self.assertEqual((item.metric, item.source.field, item.metric_source.field), ("GM_to_UB_bw_usage_rate(%)", "Value", "Metric"))
        self.assertEqual((item.source.column, item.metric_source.column), (2, 1))
        original = OperatorEvidence(group="memory", artifacts=(artifact,), primary=select_operator_primary((artifact,)))
        self.assertEqual(OperatorEvidence.model_validate(json.loads(original.model_dump_json())), original)
        payload = original.model_dump(mode="json")
        payload["artifacts"][0]["observations"][0]["unit"] = "ratio"
        with self.assertRaises(ValidationError):
            OperatorEvidence.model_validate(payload)

    def test_unknown_fields_remain_raw(self):
        artifact = self.normalize("sub_block_id,Unknown Bandwidth usage rate\nvector0,99\n", "memory", "Memory.csv")
        self.assertFalse(artifact.observations)
        self.assertEqual(artifact.sample_rows[0]["Unknown Bandwidth usage rate"], "99")
        self.assertIn("unsupported_fields", {item.code for item in artifact.issues})

    def test_partial_operator_rows_preserve_valid_metrics(self):
        artifact = self.normalize("sub_block_id,aic_cube_ratio,aiv_vec_ratio\ncube0,.5,NaN\nbad,1,2,3\n", "pipe_utilization", "PipeUtilization.csv")
        self.assertEqual(artifact.observations[0].value, .5)
        self.assertEqual(artifact.status, "invalid")
        self.assertEqual({item.code for item in artifact.issues}, {"row_width", "invalid_number"})

    def test_multiple_launch_files_do_not_select_first_file(self):
        for root, value in (("OPPROF_001", 12), ("OPPROF_002", 99)):
            self.artifact(f"Op Name,Task Duration(us)\nkernel,{value}\n", root=root)
        result = write_evidence_model(self.root)
        evidence = RunEvidence.load(self.root)
        self.assertIsNone(evidence.headline_record("op_basic_info"))
        self.assertEqual([item.value for item in evidence.operator_headline_records("op_basic_info")], [12, 99])
        self.assertEqual(result.summary.headlines["op_basic_info"].primary.reason, "multiple_scopes")
        self.assertIsNone(evidence.primary_headline())
        report = build_report(result.summary, self.root)
        self.assertIn("The calling agent selects", report)
        self.assertNotIn("No finite sourced headline is available", report)

    def test_operator_csv_is_read_once_including_frequency_and_coverage(self):
        path = self.artifact("Op Name,Task Duration(us),Current Freq,Rated Freq\nkernel,12,1650,1800\n")
        pipe = self.artifact("sub_block_id,aic_cube_ratio\ncube0,.5\n", "PipeUtilization.csv")
        memory = self.artifact("sub_block_id,GM_to_UB_datas(KB)\nvector0,2\n", "Memory.csv")
        paths = {path, pipe, memory}
        opened = []
        original = Path.open
        def track(file, *args, **kwargs):
            if file in paths:
                opened.append(file)
            return original(file, *args, **kwargs)
        with mock.patch.object(Path, "open", track):
            result = write_evidence_model(self.root)
            build_report(result.summary, self.root)
            RunEvidence.load(self.root).headline_records()
        self.assertCountEqual(opened, paths)

    def test_summary_index_composition_includes_operator_groups(self):
        self.artifact("Op Name,Task Duration(us)\nkernel,12\n")
        result = write_evidence_model(self.root)
        payload = json.loads(result.summary_path.read_text())
        del payload["headlines"]["op_basic_info"]
        result.summary_path.write_text(json.dumps(payload))
        with self.assertRaises(RunEvidenceError):
            RunEvidence.load(self.root)
        self.assertFalse(RunEvidence.load_assessment(self.root).summary_present())

    def test_many_core_rows_retain_bounded_facts_with_exact_sources(self):
        rows = ["block_id,sub_block_id,aic_cube_ratio,aiv_vec_ratio"]
        rows.extend(f"{i},cube{i},{i / 10000},{(10000 - i) / 10000}" for i in range(10000))
        artifact = self.normalize("\n".join(rows) + "\n", "pipe_utilization", "PipeUtilization.csv")
        self.assertEqual(artifact.row_count, 10000)
        self.assertEqual(len(artifact.observations), 2)
        self.assertLessEqual(len(artifact.sample_rows), 5)
        cube, vector = artifact.observations
        self.assertEqual((cube.value, cube.source.record, dict(cube.scope)["block_id"]), (.9999, 10001, "9999"))
        self.assertEqual((vector.value, vector.source.record, dict(vector.scope)["block_id"]), (1.0, 2, "0"))

    def test_operator_schema_is_generated_from_model(self):
        path = Path(__file__).resolve().parents[1] / "skills/ascend-msprof-skill/data/operator-evidence.schema.json"
        self.assertEqual(json.loads(path.read_text()), OperatorEvidence.model_json_schema())

    def test_distinct_devices_in_one_file_preserve_scope_ambiguity(self):
        self.artifact("Op Name,Device Id,Task Duration(us)\nkernel,0,12\nkernel,1,99\n")
        write_evidence_model(self.root)
        evidence = RunEvidence.load(self.root)
        self.assertFalse(evidence.comparison_headline_record("op_basic_info").present)
        records = evidence.operator_headline_records("op_basic_info")
        self.assertEqual([fact.value for fact in records], [12, 99])
        self.assertEqual([fact.source.record for fact in records], [2, 3])

    def test_mixed_statistic_files_cannot_hide_candidate_scope(self):
        self.artifact("sub_block_id,GM_to_UB_bw_usage_rate(%)\nvector0,50\n", "Memory.csv", "OPPROF_001")
        self.artifact("sub_block_id,aiv_gm_to_ub_bw(GB/s)\nvector0,100\n", "Memory.csv", "OPPROF_002")
        result = write_evidence_model(self.root)
        evidence = RunEvidence.load(self.root)
        self.assertEqual(len(result.summary.headlines["memory"].primary.candidates), 2)
        self.assertFalse(evidence.comparison_headline_record("memory").present)
        self.assertIsNone(evidence.primary_headline())
        self.assertEqual([item.value for item in evidence.operator_headline_records("memory")], [50, 100])
        self.assertIn("The calling agent selects", build_report(result.summary, self.root))

    def test_mixed_statistic_devices_cannot_hide_candidate_scope(self):
        artifact = self.normalize("Device Id,GM_to_UB_bw_usage_rate(%),aiv_gm_to_ub_bw(GB/s)\n0,50,\n1,,100\n", "memory", "Memory.csv")
        selection = select_operator_primary((artifact,))
        self.assertEqual(selection.reason, "multiple_scopes")
        self.assertEqual([source.record for source in selection.candidates], [2, 3])
        write_evidence_model(self.root)
        evidence = RunEvidence.load(self.root)
        self.assertFalse(evidence.comparison_headline_record("memory").present)
        self.assertEqual([item.value for item in evidence.operator_headline_records("memory")], [50, 100])
