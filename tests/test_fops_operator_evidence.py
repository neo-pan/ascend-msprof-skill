"""Real A2 Arithmetic FOPS retain computation-count and launch/core boundaries."""
import csv
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from ascend_msprof_skill.evidence_binding import verify_reference
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.joint_row import select_records
from ascend_msprof_skill.operator_evidence import OP_FIELDS, field_definition, normalize_operator
from ascend_msprof_skill.question_evidence import read_question_from_dir
from ascend_msprof_skill.scoped_operator_evidence import aggregate_launches


FIXTURES = Path(__file__).parent / "fixtures/real_kernel_agent_scored_minimal"
FOPS = ["aic_cube_fops", "aiv_vec_fops"]


class FopsOperatorEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def real_run(self, case="dft23"):
        run = self.root / case
        shutil.copytree(FIXTURES / case, run)
        names = set()
        for path in run.rglob("OpBasicInfo*.csv"):
            with path.open(newline="") as stream:
                names.add(next(csv.DictReader(stream))["Op Name"])
        names = sorted(names)
        context = {"sampling": {"program_launches": 23, "steady_state_skip": 3},
            "profile_harness": {"target": {"kernel_selector": "|".join(names),
                "expected_launches": [{"name": name, "count": 23} for name in names]}}}
        (run / "analysis").mkdir()
        (run / "analysis/profile_context.json").write_text(json.dumps(context))
        write_evidence_model(run)
        return run

    def query(self, run, **kwargs):
        return read_question_from_dir(run, "arithmetic", launch_scope="scored",
            aggregate_launches=True, fields=FOPS, include_next_steps=False, limit=None, **kwargs)

    def group(self, result, metric, lane, *, block="0", kernel_part=None):
        return next(group for group in result["launch_aggregation"]["groups"]
                    if group["metric"] == metric and dict(group["scope"]) == {
                        "block_id": block, "sub_block_id": lane}
                    and (kernel_part is None or kernel_part in group["kernel_directory"]))

    def test_only_two_fops_spellings_are_registered_as_counts(self):
        self.assertEqual({field for fields in OP_FIELDS.values() for field in fields if "fops" in field}, set(FOPS))
        for field in FOPS:
            definition = field_definition("arithmetic_utilization", field)
            self.assertEqual((definition["unit"], definition["statistic"]), ("FLOP", "operation_count"))
            self.assertIn("not operations per second", definition["denominator"])
            self.assertIn("no automatic sum", definition["aggregation"])
            self.assertFalse(field_definition("pipe_utilization", field)["recognized"])
        self.assertFalse(field_definition("arithmetic_utilization", "aic_cube_total_instr_number")["recognized"])
        self.assertFalse(field_definition("arithmetic_utilization", "aic_total_cycles")["recognized"])

    def test_real_typed_query_keeps_fops_ratio_and_missing_other_core_distinct(self):
        path = next((FIXTURES / "dft23").rglob("ArithmeticUtilization*.csv"))
        run = FIXTURES / "dft23"
        artifact = str(path.relative_to(run))
        result = select_records(run, artifact, "arithmetic_utilization", FOPS,
                                scope={"block_id": "0"}, limit=3)
        cube, vector0, vector1 = result["records"]
        self.assertEqual(cube["fields"]["aic_cube_fops"]["value"], 163840)
        self.assertEqual(vector0["fields"]["aiv_vec_fops"]["value"], 179648)
        self.assertEqual(vector1["fields"]["aiv_vec_fops"]["value"], 184384)
        self.assertEqual((cube["fields"]["aiv_vec_fops"]["state"], cube["fields"]["aiv_vec_fops"]["raw"]), ("missing", "NA"))
        normalized = normalize_operator(path, artifact, "arithmetic_utilization", "op", "ArithmeticUtilization")
        counts = [cell for cell in normalized.observations if cell.metric in FOPS]
        self.assertEqual(len(counts), 2)
        self.assertTrue(all(cell.unit == "FLOP" and cell.statistic == "operation_count" for cell in counts))
        self.assertTrue(all(cell.statistic == "ratio" for cell in normalized.observations if cell.metric.endswith("_ratio")))
        self.assertEqual(counts[0].source.column, 8)
        self.assertEqual(counts[1].source.column, 20)
        self.assertTrue(any(peer.statistic == "operation_count" for cell in normalized.observations
                            for peer in cell.same_record))

    def test_real_scored_counts_keep_all_blocks_and_core_lanes_with_bound_cells(self):
        run = self.real_run()
        result = self.query(run)
        groups = result["launch_aggregation"]["groups"]
        self.assertEqual(result["launch_selection"]["expected_launch_indices"], list(range(3, 23)))
        self.assertEqual(len(groups), 144)  # 24 blocks × 3 lanes × 2 fields.
        valid = [group for group in groups if group["valid_count"]]
        self.assertEqual(len(valid), 72)
        self.assertEqual({dict(group["scope"])["block_id"] for group in valid}, {str(i) for i in range(24)})
        for metric, lane, expected in (("aic_cube_fops", "cube0", 163840),
                                       ("aiv_vec_fops", "vector0", 179648),
                                       ("aiv_vec_fops", "vector1", 184384)):
            group = self.group(result, metric, lane)
            self.assertEqual((group["minimum"], group["median"], group["maximum"]), (expected,) * 3)
            self.assertEqual((group["count"], group["unit"], group["statistic"]), (20, "FLOP", "operation_count"))
            self.assertTrue(group["complete"])
            self.assertEqual(group["launch_indices"], list(range(3, 23)))
            self.assertNotIn("sum", group)
            cell = group["cells"][0]
            self.assertEqual(verify_reference(run, cell["reference"])["status"], "verified")
            with (run / cell["source"]["artifact"]).open(newline="") as stream:
                raw_rows = list(csv.reader(stream))
            self.assertEqual(raw_rows[cell["source"]["record"] - 1][cell["source"]["column"] - 1], cell["raw_token"])
        other_core = self.group(result, "aiv_vec_fops", "cube0")
        self.assertEqual((other_core["valid_count"], other_core["missing_cell_count"]), (0, 20))
        self.assertIsNone(other_core["median"])
        self.assertEqual(other_core["missing_launch_indices"], list(range(3, 23)))
        missing = other_core["excluded_cells"][0]
        self.assertEqual(missing["raw_cells"][0]["raw_token"], "NA")
        self.assertEqual(verify_reference(run, missing["raw_cells"][0]["reference"])["status"], "verified")
        self.assertEqual(result["launch_aggregation"]["unrecognized_requested_fields"], [])
        self.assertEqual(result["launch_aggregation"]["unavailable_requested_fields"], [])

    def test_real_multikernel_zero_is_retained_and_program_score_is_absent(self):
        run = self.real_run("multi23")
        basic_before = {str(path): path.read_bytes() for path in run.rglob("OpBasicInfo*.csv")}
        result = self.query(run)
        self.assertEqual(len(result["launch_selection"]["coverage"]), 2)
        groups = result["launch_aggregation"]["groups"]
        self.assertEqual(len(groups), 252)  # (18 + 24) blocks × 3 lanes × 2 fields.
        dft = self.group(result, "aiv_vec_fops", "vector0", kernel_part="_dft_kernel_")
        padding = self.group(result, "aiv_vec_fops", "vector0", kernel_part="_pad_twiddle_")
        zero = self.group(result, "aic_cube_fops", "cube0", kernel_part="_pad_twiddle_")
        self.assertEqual((dft["median"], padding["median"], zero["median"]), (128, 177984, 0))
        self.assertEqual((zero["valid_count"], zero["missing_cell_count"]), (20, 0))
        self.assertTrue(all(group["count"] == 20 and group["complete"] for group in groups if group["count"]))
        self.assertNotIn("program_duration", result["launch_aggregation"])
        self.assertTrue(all("sum" not in group for group in groups))
        self.assertEqual(basic_before, {str(path): path.read_bytes() for path in run.rglob("OpBasicInfo*.csv")})

    def test_real_partial_artifact_keeps_basic_coverage_and_detects_stale_binding(self):
        run = self.real_run()
        result = self.query(run)
        self.assertEqual(verify_reference(run, result["binding"])["status"], "verified")
        path = next(path for path in run.rglob("ArithmeticUtilization*.csv") if path.parent.name == "10")
        path.unlink()
        self.assertEqual(verify_reference(run, result["binding"])["status"], "stale")
        write_evidence_model(run)
        partial = self.query(run)
        self.assertTrue(partial["launch_selection"]["coverage"][0]["basic_info_complete"])
        group = self.group(partial, "aiv_vec_fops", "vector0")
        self.assertEqual((group["valid_count"], group["missing_launch_indices"]), (19, [10]))
        self.assertEqual(group["absent_launch_indices"], [10])
        self.assertFalse(group["complete"])

    def test_missing_bad_negative_and_absent_cells_preserve_independent_counts_and_positions(self):
        entries = []
        for number, content in {
            3: "block_id,sub_block_id,aiv_vec_fops\n0,vector0,0\n",
            4: "block_id,sub_block_id,aiv_vec_fops\n0,vector0,NA\n",
            5: "block_id,sub_block_id,aiv_vec_fops\n0,vector0,bad\n",
            6: "block_id,sub_block_id,aiv_vec_fops\n0,vector0,-1\n",
            7: "block_id,sub_block_id,aiv_vec_fops\n0,vector0,inf\n",
            8: "block_id,sub_block_id,aiv_vec_ratio\n0,vector0,0.5\n",
        }.items():
            artifact = f"reports/op/OPPROF_001/kernel/{number}/ArithmeticUtilization.csv"
            path = self.root / artifact
            path.parent.mkdir(parents=True)
            path.write_text(content)
            entries.append(SimpleNamespace(artifact=artifact, segment="op", target_name="kernel",
                metric_scope="ArithmeticUtilization", group="arithmetic_utilization", canonical_stem="ArithmeticUtilization"))
        result = aggregate_launches(self.root, entries, SimpleNamespace(allows=lambda _: True),
            {"expected_launch_indices": list(range(3, 9))}, fields=["aiv_vec_fops"], limit=None)
        group, = result["groups"]
        self.assertEqual((group["valid_count"], group["missing_cell_count"], group["invalid_cell_count"],
                          group["absent_field_cell_count"]), (1, 1, 3, 1))
        self.assertEqual((group["minimum"], group["median"], group["maximum"]), (0, 0, 0))
        self.assertEqual(group["missing_launch_indices"], [4, 5, 6, 7, 8])
        self.assertFalse(group["complete"])
        for cell in group["excluded_cells"]:
            self.assertEqual(verify_reference(self.root, cell["record_reference"])["status"], "verified")
            if cell["raw_cells"]:
                raw, = cell["raw_cells"]
                self.assertEqual((raw["source"]["record"], raw["source"]["column"]), (2, 3))
        self.assertTrue(any("nonnegative" in issue["reason"] for issue in result["issues"]))

    def test_metric_scope_and_artifact_family_populations_do_not_pool(self):
        entries = []
        for suffix, stem, metric_scope, amount in (("a", "ArithmeticUtilization", "Default", 10),
                                                  ("b", "ArithmeticUtilization", "ArithmeticUtilization", 100),
                                                  ("c", "ArithmeticExtra", "Default", 1000)):
            for launch in (3, 4):
                artifact = f"reports/op/OPPROF_001/kernel/{launch}/{stem}_{suffix}.csv"
                path = self.root / artifact
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"block_id,sub_block_id,aiv_vec_fops\n0,vector0,{amount}\n")
                entries.append(SimpleNamespace(artifact=artifact, segment="op", target_name="kernel",
                    metric_scope=metric_scope, group="arithmetic_utilization", canonical_stem=stem))
        result = aggregate_launches(self.root, entries, SimpleNamespace(allows=lambda _: True),
            {"expected_launch_indices": [3, 4]}, fields=["aiv_vec_fops"], limit=None)
        self.assertEqual(len(result["groups"]), 3)
        self.assertEqual(sorted(group["median"] for group in result["groups"]), [10, 100, 1000])
        self.assertTrue(all(group["valid_count"] == 2 for group in result["groups"]))

    def test_cli_exposes_scored_fops_type_and_group_pagination(self):
        run = self.real_run()
        completed = subprocess.run(["ascend-msprof", "evidence", "--run-dir", str(run),
            "--question", "arithmetic", "--launch-scope", "scored", "--aggregate-launches",
            "--field", "aiv_vec_fops", "--limit", "2", "--format", "json"],
            text=True, capture_output=True, check=True)
        result = json.loads(completed.stdout)
        self.assertEqual(result["launch_aggregation"]["group_count"], 72)
        self.assertEqual(result["launch_aggregation"]["next_offset"], 2)
        self.assertEqual(len(result["launch_aggregation"]["groups"]), 2)
        self.assertTrue(all(group["unit"] == "FLOP" and group["statistic"] == "operation_count"
                            for group in result["launch_aggregation"]["groups"]))


if __name__ == "__main__":
    unittest.main()
