"""Operator raw inputs and their typed report/coverage consumers."""
import json
import tempfile
from pathlib import Path
from unittest import mock

from tests.helpers_shared import unittest
from pydantic import ValidationError
from ascend_msprof_skill.operator_evidence import (
    OperatorEvidence, joint_operator_row, normalize_operator, observations_are_joint,
    operator_group_for_path, select_operator_primary,
)
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

    def test_pipe_utilization_maps_fixture_times_and_active_bandwidth(self):
        fixture = Path(__file__).resolve().parents[1] / (
            "tests/fixtures/real_cann_minimal/reports/OPPROF_001/PipeUtilization.csv")
        artifact = normalize_operator(
            fixture, "reports/OPPROF_001/PipeUtilization.csv", "pipe_utilization", "op", "PipeUtilization")
        by_metric = {item.metric: item for item in artifact.observations}
        self.assertEqual((by_metric["aiv_mte2_time(us)"].value, by_metric["aiv_mte2_time(us)"].unit),
                         (0.918333, "us"))
        self.assertEqual(by_metric["aiv_mte3_time(us)"].value, 0.256667)
        self.assertEqual((by_metric["aiv_mte2_active_bw(GB/s)"].value, by_metric["aiv_mte2_active_bw(GB/s)"].statistic),
                         (4.153935, "bandwidth"))
        self.assertEqual(dict(by_metric["aiv_mte2_time(us)"].scope)["sub_block_id"], "vector0")
        self.assertIn("aiv_mte2_time(us)", {item.metric for item in artifact.core_time_distributions})
        self.assertNotIn("aic_total_cycles", by_metric)
        self.assertEqual(fixture.read_text().splitlines()[0].count("aiv_mte2_time(us)"), 1)

    def test_joint_operator_row_returns_same_record_fields_without_guessing_cycles(self):
        fixture = Path(__file__).resolve().parents[1] / (
            "tests/fixtures/real_cann_minimal/reports/OPPROF_001/PipeUtilization.csv")
        self.assertEqual(operator_group_for_path(fixture), "pipe_utilization")
        row = joint_operator_row(
            fixture, "reports/OPPROF_001/PipeUtilization.csv", "pipe_utilization",
            scope={"block_id": "0", "sub_block_id": "vector0"},
        )
        by_metric = {item.metric: item for item in row.fields}
        self.assertEqual(row.record, 3)
        self.assertEqual(by_metric["aiv_mte2_time(us)"].value, 0.918333)
        self.assertEqual(by_metric["aiv_mte2_ratio"].value, 0.183667)
        self.assertEqual(by_metric["aiv_mte2_active_bw(GB/s)"].value, 4.153935)
        self.assertIn("aic_total_cycles", row.unmatched)
        self.assertEqual(dict(row.raw_cells)["aic_total_cycles"], "NA")
        same = joint_operator_row(
            fixture, "reports/OPPROF_001/PipeUtilization.csv", "pipe_utilization", record=3)
        self.assertEqual(same.record, row.record)
        artifact = normalize_operator(
            fixture, "reports/OPPROF_001/PipeUtilization.csv", "pipe_utilization", "op", "PipeUtilization")
        mte2 = next(item for item in artifact.observations if item.metric == "aiv_mte2_time(us)")
        active = next(item for item in artifact.observations if item.metric == "aiv_mte2_active_bw(GB/s)")
        self.assertTrue(observations_are_joint(mte2, active))
        self.assertEqual(mte2.source.record, row.record)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            joint_operator_row(fixture, "x", "pipe_utilization")
        with self.assertRaisesRegex(ValueError, "no operator CSV row matched"):
            joint_operator_row(
                fixture, "x", "pipe_utilization", scope={"block_id": "99", "sub_block_id": "vector0"})

    def test_joint_row_cli_prints_json_for_fixture_scope(self):
        import io
        import json
        from contextlib import redirect_stdout
        from ascend_msprof_skill.joint_row import main as joint_row_main
        root = Path(__file__).resolve().parents[1] / "tests/fixtures/real_cann_minimal"
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = joint_row_main([
                "--run-dir", str(root),
                "--artifact", "reports/OPPROF_001/PipeUtilization.csv",
                "--scope", "block_id=0", "--scope", "sub_block_id=vector0",
            ])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["record"], 3)
        self.assertEqual(payload["group"], "pipe_utilization")
        fields = {item["metric"]: item for item in payload["fields"]}
        self.assertEqual(fields["aiv_mte2_time(us)"]["value"], 0.918333)
        self.assertIn("aic_total_cycles", payload["unmapped_columns"])

    def test_joint_row_cli_attaches_same_row_pipe_time_over_core_time(self):
        import io
        import json
        from contextlib import redirect_stdout
        from ascend_msprof_skill.joint_row import derived_pipe_quotients, main as joint_row_main
        path = self.artifact(
            "block_id,sub_block_id,aiv_time(us),aiv_mte2_time(us),aiv_mte2_ratio,aiv_scalar_time(us)\n"
            "0,vector0,10,6.5,0.2,3\n",
            "PipeUtilization.csv",
        )
        row = joint_operator_row(
            path, path.relative_to(self.root).as_posix(), "pipe_utilization", record=2)
        quotients = {f"{item['numerator']}/{item['denominator']}": item for item in derived_pipe_quotients(row.fields)}
        self.assertAlmostEqual(quotients["aiv_mte2_time(us)/aiv_time(us)"]["value"], 0.65)
        self.assertEqual(quotients["aiv_mte2_time(us)/aiv_time(us)"]["recorded_ratio"], 0.2)
        self.assertAlmostEqual(quotients["aiv_scalar_time(us)/aiv_time(us)"]["value"], 0.3)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = joint_row_main([
                "--run-dir", str(self.root),
                "--artifact", path.relative_to(self.root).as_posix(),
                "--record", "2",
            ])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(len(payload["derived_pipe_quotients"]), 2)
        self.assertIn("CalRatio", payload["note"])

    def test_joint_row_rejects_prefix_path_escape_and_infers_memory_csv(self):
        import io
        from contextlib import redirect_stdout
        from ascend_msprof_skill.joint_row import main as joint_row_main
        run = self.root / "runA"
        sibling = self.root / "runAB" / "reports" / "OPPROF_001"
        (run / "reports" / "OPPROF_001").mkdir(parents=True)
        sibling.mkdir(parents=True)
        fixture = Path(__file__).resolve().parents[1] / (
            "tests/fixtures/real_cann_minimal/reports/OPPROF_001/PipeUtilization.csv")
        memory = Path(__file__).resolve().parents[1] / (
            "tests/fixtures/real_cann_minimal/reports/OPPROF_001/Memory.csv")
        target = sibling / "PipeUtilization.csv"
        target.write_text(fixture.read_text())
        (run / "reports" / "OPPROF_001" / "Memory.csv").write_text(memory.read_text())
        self.assertEqual(operator_group_for_path(Path("Memory.csv")), "memory")
        with self.assertRaises(SystemExit) as escaped:
            joint_row_main([
                "--run-dir", str(run),
                "--artifact", f"../runAB/reports/OPPROF_001/PipeUtilization.csv",
                "--record", "2",
            ])
        self.assertIn("artifact must stay under --run-dir", str(escaped.exception))
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = joint_row_main([
                "--run-dir", str(run),
                "--artifact", "reports/OPPROF_001/Memory.csv",
                "--scope", "block_id=0", "--scope", "sub_block_id=vector0",
            ])
        self.assertEqual(code, 0)
        self.assertIn('"group": "memory"', buf.getvalue())

    def test_operator_csv_names_share_canonical_and_timestamped_identity(self):
        from ascend_msprof_skill._evidence_artifacts import operator_file_stem
        from ascend_msprof_skill._operator_csv_names import (
            operator_group_for_name, parse_operator_csv_name,
        )
        from ascend_msprof_skill.run_evidence import _canonical_operator_stem

        timestamp = "20260730130344937"
        pipe = f"PipeUtilization_{timestamp}.csv"
        memory_l0 = f"MemoryL0_{timestamp}.csv"
        self.assertEqual(parse_operator_csv_name("PipeUtilization.csv"), ("PipeUtilization", None))
        self.assertEqual(parse_operator_csv_name(pipe), ("PipeUtilization", timestamp))
        self.assertEqual(operator_group_for_path(Path("PipeUtilization.csv")), "pipe_utilization")
        self.assertEqual(operator_group_for_path(Path(pipe)), "pipe_utilization")
        self.assertEqual(operator_group_for_name(memory_l0), "memory")
        self.assertEqual(operator_group_for_path(Path(memory_l0)), "memory")
        self.assertIsNone(parse_operator_csv_name("PipeUtilization_123.csv"))
        self.assertIsNone(operator_group_for_path(Path("PipeUtilization_123.csv")))
        self.assertIsNone(operator_group_for_name("Unknown.csv"))
        self.assertIsNone(operator_file_stem(Path("PipeUtilization.csv"), "pipe_utilization"))
        self.assertEqual(
            operator_file_stem(Path(f"reports/OPPROF_001/{pipe}"), "pipe_utilization"),
            "PipeUtilization",
        )
        self.assertEqual(_canonical_operator_stem(f"reports/OPPROF_001/{pipe}"), "PipeUtilization")
        self.assertEqual(_canonical_operator_stem(f"reports/OPPROF_001/{memory_l0}"), "MemoryL0")
        self.assertIsNone(_canonical_operator_stem("reports/OPPROF_001/OpBasicInfo.csv"))

    def test_joint_row_cli_infers_group_from_timestamped_filenames(self):
        import io
        from contextlib import redirect_stdout
        from ascend_msprof_skill.joint_row import main as joint_row_main

        fixtures = Path(__file__).resolve().parents[1] / "tests/fixtures/real_cann_minimal/reports/OPPROF_001"
        timestamp = "20260730130344937"
        pipe = self.artifact(
            (fixtures / "PipeUtilization.csv").read_text(),
            f"PipeUtilization_{timestamp}.csv",
        )
        memory = self.artifact(
            (fixtures / "MemoryL0.csv").read_text(),
            f"MemoryL0_{timestamp}.csv",
        )
        unknown = self.artifact(
            (fixtures / "PipeUtilization.csv").read_text(),
            "PipeUtilization_123.csv",
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = joint_row_main([
                "--run-dir", str(self.root),
                "--artifact", pipe.relative_to(self.root).as_posix(),
                "--record", "3",
            ])
        self.assertEqual(code, 0)
        self.assertIn('"group": "pipe_utilization"', buf.getvalue())
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = joint_row_main([
                "--run-dir", str(self.root),
                "--artifact", memory.relative_to(self.root).as_posix(),
                "--record", "2",
            ])
        self.assertEqual(code, 0)
        self.assertIn('"group": "memory"', buf.getvalue())
        with self.assertRaises(SystemExit) as inferred:
            joint_row_main([
                "--run-dir", str(self.root),
                "--artifact", unknown.relative_to(self.root).as_posix(),
                "--record", "3",
            ])
        self.assertIn("could not infer operator group; pass --group", str(inferred.exception))

    def test_observations_are_joint_requires_same_artifact_and_record(self):
        fixture = Path(__file__).resolve().parents[1] / (
            "tests/fixtures/real_cann_minimal/reports/OPPROF_001/PipeUtilization.csv")
        memory = Path(__file__).resolve().parents[1] / (
            "tests/fixtures/real_cann_minimal/reports/OPPROF_001/Memory.csv")
        pipe = normalize_operator(
            fixture, "reports/OPPROF_001/PipeUtilization.csv", "pipe_utilization", "op", "PipeUtilization")
        mem = normalize_operator(
            memory, "reports/OPPROF_001/Memory.csv", "memory", "op", "Default")
        cube_time = next(item for item in pipe.observations if item.metric == "aic_time(us)")
        vec_time = next(item for item in pipe.observations if item.metric == "aiv_time(us)")
        mem_bw = next(item for item in mem.observations if item.metric == "aiv_gm_to_ub_bw(GB/s)")
        self.assertFalse(observations_are_joint(cube_time, vec_time))
        self.assertFalse(observations_are_joint(vec_time, mem_bw))
        multi = self.artifact(
            "block_id,sub_block_id,aiv_mte2_ratio\n0,vector0,.1\n1,vector0,.2\n",
            "PipeUtilization.csv")
        with self.assertRaisesRegex(ValueError, "matched 2"):
            joint_operator_row(
                multi, "reports/op/OPPROF_001/PipeUtilization.csv", "pipe_utilization",
                scope={"sub_block_id": "vector0"})

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

    def test_normalize_and_joint_row_share_metric_value_and_negative_pipe_legality(self):
        memory_text = "Metric,Value\nGM_to_UB_bw_usage_rate(%),64\n"
        memory_path = self.artifact(memory_text, "Memory.csv")
        normalized = normalize_operator(
            memory_path, memory_path.relative_to(self.root).as_posix(), "memory", "op", "Memory")
        joint = joint_operator_row(
            memory_path, memory_path.relative_to(self.root).as_posix(), "memory", record=2)
        self.assertEqual(len(normalized.observations), 1)
        self.assertEqual(len(joint.fields), 1)
        self.assertEqual(normalized.observations[0].metric, joint.fields[0].metric)
        self.assertEqual(normalized.observations[0].value, joint.fields[0].value)
        self.assertEqual(normalized.observations[0].unit, joint.fields[0].unit)
        self.assertEqual(normalized.observations[0].source.field, joint.fields[0].source.field)
        self.assertEqual(normalized.observations[0].metric_source.field, joint.fields[0].metric_source.field)

        pipe_text = (
            "Device Id,block_id,sub_block_id,aiv_time(us),aiv_mte2_time(us),aiv_mte2_ratio\n"
            "0,0,vector0,10,-1.5,0.2\n"
        )
        pipe_path = self.artifact(pipe_text, "PipeUtilization.csv")
        pipe_norm = normalize_operator(
            pipe_path, pipe_path.relative_to(self.root).as_posix(), "pipe_utilization", "op", "PipeUtilization")
        pipe_joint = joint_operator_row(
            pipe_path, pipe_path.relative_to(self.root).as_posix(), "pipe_utilization", record=2)
        self.assertNotIn("aiv_mte2_time(us)", {item.metric for item in pipe_norm.observations})
        self.assertNotIn("aiv_mte2_time(us)", {item.metric for item in pipe_joint.fields})
        self.assertIn("aiv_time(us)", {item.metric for item in pipe_norm.observations})
        self.assertIn("aiv_time(us)", {item.metric for item in pipe_joint.fields})
        self.assertIn("pipe time must be nonnegative", {issue.reason for issue in pipe_norm.issues})
        self.assertIn("pipe time must be nonnegative", {issue.reason for issue in pipe_joint.issues})
        self.assertEqual(
            {issue.code for issue in pipe_norm.issues if "nonnegative" in issue.reason},
            {issue.code for issue in pipe_joint.issues if "nonnegative" in issue.reason},
        )

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

    def test_memory_fixture_populations_split_cube_vector_and_sum_differs_from_max(self):
        fixture = Path(__file__).resolve().parents[1] / (
            "tests/fixtures/real_cann_minimal/reports/OPPROF_001/Memory.csv")
        artifact = normalize_operator(
            fixture, "reports/OPPROF_001/Memory.csv", "memory", "op", "Default")
        by_metric = {}
        for item in artifact.field_populations:
            by_metric.setdefault(item.metric, []).append(item)
        read = by_metric["read_main_memory_datas(KB)"]
        self.assertEqual({dict(item.scope)["sub_block_id"] for item in read}, {"cube0", "vector0"})
        self.assertTrue(all("block_id" not in dict(item.scope) for item in read))
        gm = next(item for item in artifact.field_populations if item.metric == "GM_to_UB_datas(KB)")
        self.assertEqual(dict(gm.scope)["sub_block_id"], "vector0")
        self.assertEqual(gm.aggregation, "sum_over_rows")
        self.assertEqual(gm.valid_count, 1)
        self.assertEqual(gm.sum, gm.maximum)

        header, cube, vector = fixture.read_text().splitlines()[:3]
        extra_vector = vector.replace(",4.000000,", ",98304.000000,", 1)
        path = self.artifact("\n".join([header, cube, vector, extra_vector]) + "\n", "Memory.csv")
        summed = normalize_operator(path, path.relative_to(self.root).as_posix(), "memory", "op", "Default")
        gm_sum = next(
            item for item in summed.field_populations
            if item.metric == "GM_to_UB_datas(KB)" and dict(item.scope).get("sub_block_id") == "vector0"
        )
        self.assertEqual(gm_sum.valid_count, 2)
        self.assertEqual(gm_sum.minimum, 4.0)
        self.assertEqual(gm_sum.maximum, 98304.0)
        self.assertEqual(gm_sum.sum, 98308.0)
        self.assertNotEqual(gm_sum.sum, gm_sum.maximum)
        cube_read = next(
            item for item in summed.field_populations
            if item.metric == "read_main_memory_datas(KB)" and dict(item.scope).get("sub_block_id") == "cube0"
        )
        vector_read = next(
            item for item in summed.field_populations
            if item.metric == "read_main_memory_datas(KB)" and dict(item.scope).get("sub_block_id") == "vector0"
        )
        self.assertNotEqual(cube_read.scope, vector_read.scope)
        rate_pop = next(item for item in summed.field_populations if item.statistic == "percentage")
        self.assertIsNone(rate_pop.sum)
        self.assertEqual(rate_pop.aggregation, "population_over_rows")

    def test_pipe_fixture_ratio_observation_keeps_same_record_quotients(self):
        fixture = Path(__file__).resolve().parents[1] / (
            "tests/fixtures/real_cann_minimal/reports/OPPROF_001/PipeUtilization.csv")
        artifact = normalize_operator(
            fixture, "reports/OPPROF_001/PipeUtilization.csv", "pipe_utilization", "op", "PipeUtilization")
        ratio = next(item for item in artifact.observations if item.metric == "aiv_scalar_ratio")
        peers = {cell.metric: cell for cell in ratio.same_record}
        self.assertEqual(peers["aiv_scalar_time(us)"].value, 1.631111)
        self.assertEqual(peers["aiv_time(us)"].value, 3.200556)
        self.assertNotIn("aiv_scalar_ratio", peers)
        quotient = next(
            item for item in ratio.derived_pipe_quotients if item.numerator == "aiv_scalar_time(us)")
        self.assertEqual(quotient.denominator, "aiv_time(us)")
        self.assertAlmostEqual(quotient.value, 1.631111 / 3.200556)
        self.assertEqual(quotient.recorded_ratio, 0.326222)
        self.assertNotIn("inconsistent", ratio.model_dump(mode="json"))
