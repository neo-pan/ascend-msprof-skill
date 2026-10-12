"""Saved real profiler launches keep scoring scope and PMU populations distinct."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
from statistics import median
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from ascend_msprof_skill.evidence_binding import verify_reference
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.question_evidence import read_question_from_dir, render_question
from ascend_msprof_skill.scoped_operator_evidence import aggregate_launches, select_launches


FIXTURES = Path(__file__).parent / "fixtures"


class ScoredOperatorEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def real_run(self, case="dft23", *, sampling=True):
        run = self.root / case
        shutil.copytree(FIXTURES / "real_kernel_agent_scored_minimal" / case, run)
        origin = json.loads((run / "origin.json").read_text())
        names = set()
        for path in run.rglob("OpBasicInfo*.csv"):
            with path.open(newline="") as stream:
                names.add(next(csv.DictReader(stream))["Op Name"])
        # Test-only caller declaration; the historical raw cells stay byte-exact.
        # Inverse deliberately retains the old caller's count=1 mismatch.
        count = 1 if case == "inverse8" else origin["program_launches"]
        context = {"profile_harness": {"target": {"kernel_selector": "|".join(sorted(names)), "expected_launches": [
            {"name": name, "count": count} for name in sorted(names)]}}}
        if sampling:
            context["sampling"] = {key: origin[key] for key in ("program_launches", "steady_state_skip")}
        (run / "analysis").mkdir()
        (run / "analysis/profile_context.json").write_text(json.dumps(context))
        write_evidence_model(run)
        return run

    def query(self, run, **kwargs):
        return read_question_from_dir(run, "pipe", launch_scope="scored", aggregate_launches=True,
                                      include_next_steps=False, **kwargs)

    def test_real_dft_20_scored_launches_match_independent_fixed_core_median(self):
        run = self.real_run()
        result = self.query(run, fields=["aiv_time(us)", "aiv_vec_time(us)"], limit=None)
        self.assertEqual(result["launch_selection"]["expected_launch_indices"], list(range(3, 23)))
        self.assertEqual(len(result["launch_selection"]["excluded_artifacts"]), 3)
        coverage = result["launch_selection"]["coverage"][0]
        self.assertTrue(coverage["basic_info_complete"])
        self.assertTrue(coverage["metric_artifact_coverage"][0]["artifact_presence_complete"])
        populations = result["launch_aggregation"]["groups"]
        vector0 = [group for group in populations if dict(group["scope"]) == {"block_id": "0", "sub_block_id": "vector0"}]
        self.assertEqual(len(vector0), 2)
        for group in vector0:
            expected = []
            for path in run.rglob("PipeUtilization*.csv"):
                if int(path.parent.name) < 3:
                    continue
                with path.open(newline="") as stream:
                    for row in csv.DictReader(stream):
                        if row["block_id"] == "0" and row["sub_block_id"] == "vector0":
                            expected.append(float(row[group["metric"]]))
            self.assertEqual(group["median"], median(expected))
            self.assertEqual((group["minimum"], group["maximum"], group["count"]), (min(expected), max(expected), 20))
            self.assertTrue(group["complete"])
            self.assertEqual(group["launch_indices"], list(range(3, 23)))
            self.assertEqual(group["unit"], "us")
            self.assertNotIn("sum", group)
            self.assertEqual(verify_reference(run, group["cells"][0]["reference"])["status"], "verified")
        self.assertEqual(next(group["median"] for group in vector0 if group["metric"] == "aiv_time(us)"), 12.0825)
        self.assertEqual(next(group["median"] for group in vector0 if group["metric"] == "aiv_vec_time(us)"), 3.531667)
        self.assertEqual(verify_reference(run, result["binding"])["status"], "verified")
        rendered = render_question(result)
        self.assertIn("scope=`scored`", rendered)
        self.assertIn("Across-Launch Operator Groups", rendered)
        self.assertIn("Complete / missing launches", rendered)
        self.assertIn("not independent process samples", rendered)

    def test_real_inverse_5_steady_launches_do_not_repair_historical_caller_count(self):
        run = self.real_run("inverse8")
        result = self.query(run, fields=["aiv_time(us)"], limit=None)
        self.assertFalse(result["context"]["profile_coverage"]["segments"]["op"]["count_complete"])
        self.assertEqual(result["launch_selection"]["expected_launch_indices"], [3, 4, 5, 6, 7])
        populated = [group for group in result["launch_aggregation"]["groups"] if group["count"]]
        self.assertTrue(populated)
        self.assertTrue(all(group["count"] == 5 and group["complete"] for group in populated))
        self.assertTrue(all(group["launch_indices"] == [3, 4, 5, 6, 7] for group in populated))
        self.assertTrue(all(group["count"] == len(group["cells"]) for group in populated))

    def test_real_multikernel_populations_remain_separate_and_do_not_form_program_score(self):
        run = self.real_run("multi23")
        result = self.query(run, fields=["aiv_time(us)"], limit=None)
        cohorts = result["launch_selection"]["coverage"]
        self.assertEqual(len(cohorts), 2)
        self.assertTrue(all(cohort["basic_info_complete"] for cohort in cohorts))
        groups = [group for group in result["launch_aggregation"]["groups"] if group["count"]]
        self.assertEqual(len({group["kernel_directory"] for group in groups}), 2)
        self.assertTrue(all(group["count"] == 20 and group["complete"] for group in groups))
        self.assertTrue(all("sum" not in group for group in groups))
        self.assertNotIn("program_duration", result["launch_aggregation"])

    def test_partial_scored_pmu_has_missing_launches_and_binds_basic_info(self):
        run = self.real_run()
        path = next(path for path in run.rglob("PipeUtilization*.csv") if path.parent.name == "10")
        path.unlink()
        write_evidence_model(run)
        result = self.query(run, fields=["aiv_time(us)"], limit=None)
        coverage = result["launch_selection"]["coverage"][0]
        self.assertTrue(coverage["basic_info_complete"])
        self.assertEqual(coverage["metric_artifact_coverage"][0]["missing_launch_indices"], [10])
        groups = [group for group in result["launch_aggregation"]["groups"] if group["count"]]
        self.assertTrue(all(group["count"] == 19 and not group["complete"] for group in groups))
        self.assertTrue(all(group["missing_launch_indices"] == [10] for group in groups))
        basic = next(run.rglob("OpBasicInfo*.csv"))
        basic.write_bytes(basic.read_bytes() + b"\n")
        self.assertEqual(verify_reference(run, result["binding"])["status"], "stale")

    def test_existing_launch0_only_fixture_reports_empty_scored_pmu_and_complete_basic(self):
        run = self.root / "partial"
        shutil.copytree(FIXTURES / "real_kernel_agent_sampling_minimal", run)
        write_evidence_model(run)
        before = read_question_from_dir(run, "pipe", limit=1)
        result = self.query(run)
        self.assertEqual(result["facts"], [])
        self.assertEqual(result["launch_aggregation"]["groups"], [])
        coverage = result["launch_selection"]["coverage"][0]
        self.assertTrue(coverage["basic_info_complete"])
        self.assertEqual(coverage["metric_artifact_coverage"][0]["missing_launch_indices"], list(range(3, 23)))
        self.assertEqual(result["context"]["profile_coverage"], before["context"]["profile_coverage"])
        default = read_question_from_dir(run, "pipe", limit=1)
        self.assertEqual(default, before)
        self.assertNotIn("launch_selection", default)

    def test_group_pages_cover_same_full_launch_population(self):
        run = self.real_run()
        full = self.query(run, fields=["aiv_time(us)"], limit=None)["launch_aggregation"]
        page = self.query(run, fields=["aiv_time(us)"], limit=2)["launch_aggregation"]
        self.assertEqual(page["group_count"], full["group_count"])
        self.assertEqual(page["groups"], full["groups"][:2])
        following = self.query(run, fields=["aiv_time(us)"], offset=page["next_offset"], limit=2)["launch_aggregation"]
        self.assertEqual(following["groups"], full["groups"][2:4])
        self.assertEqual(full["group_count"], len(full["groups"]))

    def test_exact_artifact_does_not_turn_multi_root_total_into_per_root_mapping_conflict(self):
        run = self.real_run()
        root = next((run / "reports/op").glob("OPPROF_*"))
        shutil.copytree(root, root.with_name("OPPROF_second"))
        path = run / "analysis/profile_context.json"
        context = json.loads(path.read_text())
        context["profile_harness"]["target"]["expected_launches"][0]["count"] = 46
        path.write_text(json.dumps(context))
        write_evidence_model(run)
        full = self.query(run, fields=["aiv_time(us)"], limit=None)
        self.assertEqual(len(full["launch_selection"]["coverage"]), 2)
        self.assertTrue(all(item["ordinal_mapping_conflict"] is None for item in full["launch_selection"]["coverage"]))
        artifact = str(next(path for path in root.rglob("PipeUtilization*.csv") if path.parent.name == "10").relative_to(run))
        selected = self.query(run, artifact=artifact, fields=["aiv_time(us)"], limit=None)
        self.assertEqual(len(selected["launch_selection"]["coverage"]), 1)
        self.assertIsNone(selected["launch_selection"]["coverage"][0]["ordinal_mapping_conflict"])
        groups = [item for item in selected["launch_aggregation"]["groups"] if item["count"]]
        self.assertTrue(groups)
        self.assertTrue(all(item["count"] == 1 and item["launch_indices"] == [10] for item in groups))
        self.assertTrue(all(not item["complete"] for item in groups))

    def test_missing_invalid_or_inconsistent_sampling_refuses_scored_scope(self):
        run = self.real_run(sampling=False)
        path = run / "analysis/profile_context.json"
        original = json.loads(path.read_text())
        for sampling in (None, {"program_launches": 23}, {"program_launches": 23, "steady_state_skip": 23},
                         {"program_launches": "23", "steady_state_skip": 3}):
            with self.subTest(sampling=sampling):
                path.write_text(json.dumps({**original, **({"sampling": sampling} if sampling is not None else {})}))
                with self.assertRaisesRegex(ValueError, "scored launch scope requires"):
                    self.query(run)
        self.assertTrue(read_question_from_dir(run, "pipe")["facts"])

    def test_original_fixture_bytes_are_retained(self):
        for case in (FIXTURES / "real_kernel_agent_scored_minimal").iterdir():
            if not case.is_dir():
                continue
            origin = json.loads((case / "origin.json").read_text())
            for entry in origin["artifacts"]:
                self.assertEqual(hashlib.sha256((case / entry["artifact"]).read_bytes()).hexdigest(), entry["sha256"])

    def test_cli_exposes_opt_in_scored_range_and_group_pagination(self):
        run = self.real_run()
        result = subprocess.run(["ascend-msprof", "evidence", "--run-dir", str(run), "--question", "pipe",
                                 "--launch-scope", "scored", "--aggregate-launches", "--field", "aiv_time(us)",
                                 "--limit", "2", "--format", "json"], text=True, capture_output=True, check=True)
        data = json.loads(result.stdout)
        self.assertEqual(data["selection"]["launch_scope"], "scored")
        self.assertEqual(len(data["launch_aggregation"]["groups"]), 2)
        self.assertEqual(data["launch_aggregation"]["next_offset"], 2)

    def scoped_entries(self, rows, *, group="pipe_utilization", stem="PipeUtilization"):
        entries = []
        for index, content in rows.items():
            artifact = f"reports/op/OPPROF_001/kernel/{index}/{stem}.csv"
            path = self.root / artifact
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            entries.append(SimpleNamespace(artifact=artifact, segment="op", target_name="kernel",
                                           metric_scope="Default", group=group, canonical_stem=stem))
        return entries

    def aggregate(self, entries, **kwargs):
        return aggregate_launches(self.root, entries, SimpleNamespace(allows=lambda segment: True),
                                  {"expected_launch_indices": [3, 4]}, limit=None, **kwargs)

    def test_present_device_process_stream_core_and_block_scopes_are_not_pooled(self):
        header = "Device Id,Pid,stream_id,block_id,sub_block_id,aiv_time(us),aiv_vec_ratio\n"
        entries = self.scoped_entries({
            3: header + "0,12,0,0,vector0,10,0.2\n0,12,1,0,vector0,30,0.4\n1,13,0,0,vector0,50,0.6\n",
            4: header + "0,12,0,0,vector0,12,0.3\n0,12,1,0,vector0,32,0.5\n1,13,0,0,vector0,52,0.7\n"})
        result = self.aggregate(entries)
        duration = [group for group in result["groups"] if group["metric"] == "aiv_time(us)"]
        self.assertEqual(len(duration), 3)
        self.assertEqual(sorted(group["median"] for group in duration), [11, 31, 51])
        self.assertTrue(all(group["count"] == 2 and group["complete"] for group in result["groups"]))
        self.assertTrue(all("sum" not in group for group in result["groups"]))
        self.assertTrue(all({"Device Id", "Pid", "stream_id", "block_id", "sub_block_id"} == set(dict(group["scope"]))
                            for group in result["groups"]))

    def test_duplicate_and_missing_cells_are_excluded_with_locations_and_incomplete_coverage(self):
        header = "block_id,sub_block_id,aiv_time(us),aiv_vec_ratio\n"
        entries = self.scoped_entries({3: header + "0,vector0,10,0.2\n0,vector0,11,0.3\n",
                                       4: header + "0,vector0,12,NA\n"})
        result = self.aggregate(entries)
        duration = next(group for group in result["groups"] if group["metric"] == "aiv_time(us)")
        self.assertEqual((duration["count"], duration["median"], duration["missing_launch_indices"]), (1, 12, [3]))
        self.assertEqual(len(duration["excluded_cells"]), 2)
        self.assertEqual(duration["valid_count"], 1)
        self.assertEqual(duration["duplicate_launch_count"], 1)
        self.assertEqual(duration["duplicate_cell_count"], 2)
        self.assertEqual(duration["missing_launch_count"], 1)
        self.assertTrue(all(cell["launch_index"] == 3 and "Multiple cells" in cell["reason"] for cell in duration["excluded_cells"]))
        ratio = next(group for group in result["groups"] if group["metric"] == "aiv_vec_ratio")
        self.assertEqual(ratio["count"], 0)
        self.assertIsNone(ratio["median"])
        self.assertEqual(ratio["missing_launch_indices"], [3, 4])
        self.assertEqual(len(ratio["excluded_cells"]), 3)
        self.assertEqual(ratio["missing_cell_count"], 1)
        self.assertEqual(ratio["invalid_cell_count"], 0)
        missing = next(cell for cell in ratio["excluded_cells"] if cell["cell_status"] == "missing")
        self.assertEqual(missing["raw_cells"][0]["raw_token"], "NA")
        self.assertEqual(missing["raw_cells"][0]["source"]["column"], 4)
        self.assertTrue(all(not group["complete"] for group in result["groups"]))

    def test_absent_requested_field_and_bad_token_have_distinct_counts_and_references(self):
        entries = self.scoped_entries({3: "block_id,sub_block_id,aiv_vec_ratio\n0,vector0,bad\n",
                                       4: "block_id,sub_block_id,aiv_time(us)\n0,vector0,-1\n"})
        groups = self.aggregate(entries, fields=["aiv_time(us)", "aiv_vec_ratio"])["groups"]
        self.assertEqual(len(groups), 2)
        for group in groups:
            self.assertEqual(group["valid_count"], 0)
            self.assertEqual(group["invalid_cell_count"], 1)
            self.assertEqual(group["absent_field_cell_count"], 1)
            self.assertEqual(group["missing_cell_count"], 0)
            self.assertEqual(group["missing_launch_count"], 2)
            self.assertFalse(group["complete"])
            for cell in group["excluded_cells"]:
                self.assertEqual(verify_reference(self.root, cell["record_reference"])["status"], "verified")

    def test_memory_artifact_families_and_percent_units_remain_separate_without_sums(self):
        header = "block_id,sub_block_id,GM_to_UB_datas(KB),Usage Rate(%)\n"
        entries = self.scoped_entries({3: header + "0,vector0,10,20\n", 4: header + "0,vector0,30,40\n"},
                                      group="memory", stem="Memory")
        entries += self.scoped_entries({3: header + "0,vector0,100,60\n", 4: header + "0,vector0,300,80\n"},
                                       group="memory", stem="MemoryUB")
        groups = self.aggregate(entries)["groups"]
        self.assertEqual(len(groups), 4)
        volumes = [group for group in groups if group["unit"] == "KB"]
        self.assertEqual(sorted(group["median"] for group in volumes), [20, 200])
        percents = [group for group in groups if group["unit"] == "%"]
        self.assertEqual(sorted(group["median"] for group in percents), [30, 70])
        self.assertTrue(all(group["statistic"] == "percentage" for group in percents))
        self.assertTrue(all("sum" not in group and group["complete"] for group in groups))

    def invocation_entries(self, count, kernel="kernel"):
        entries, basic = [], []
        for number in range(count):
            folder = self.root / f"reports/op/OPPROF_001/{kernel}/{number}"
            folder.mkdir(parents=True, exist_ok=True)
            pipe = folder / "PipeUtilization.csv"
            pipe.write_text(f"block_id,sub_block_id,aiv_time(us)\n0,vector0,{number + 1}\n")
            info = folder / "OpBasicInfo.csv"
            info.write_text(f"Op Name,Task Duration(us)\n{kernel},1\n")
            common = dict(segment="op", target_name=kernel, metric_scope="PipeUtilization", status="parsed", row_count=1)
            entries.append(SimpleNamespace(artifact=str(pipe.relative_to(self.root)), group="pipe_utilization",
                                           canonical_stem="PipeUtilization", **common))
            basic.append(SimpleNamespace(artifact=str(info.relative_to(self.root)), group="op_basic_info",
                                         canonical_stem="OpBasicInfo", **common))
        return entries, basic

    def test_two_invocations_per_program_refuses_false_scored_subset_but_preserves_other_kernel(self):
        repeated, repeated_basic = self.invocation_entries(46)
        ordinary, ordinary_basic = self.invocation_entries(23, "other")
        receipts = SimpleNamespace(allows=lambda segment: True)
        index = tuple(repeated + ordinary + repeated_basic + ordinary_basic)
        sampling = {"program_launches": 23, "steady_state_skip": 3}
        selected, selection = select_launches(repeated + ordinary, index, sampling, "scored", run_dir=self.root,
                                             groups=("pipe_utilization",), receipts=receipts)
        self.assertEqual(len(selected), 20)
        self.assertTrue(all(entry.target_name == "other" for entry in selected))
        conflict = next(cohort for cohort in selection["coverage"] if cohort["target_name"] == "kernel")
        self.assertEqual(conflict["out_of_declared_range_basic_indices"], list(range(23, 46)))
        self.assertFalse(conflict["basic_info_complete"])
        self.assertIn("invocation-to-program mapping", conflict["ordinal_mapping_conflict"]["reason"])
        groups = aggregate_launches(self.root, selected, receipts, selection, limit=None)["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["target_name"], "other")
        self.assertTrue(groups[0]["complete"])
        all_entries, all_selection = select_launches(repeated + ordinary, index, sampling, "all", run_dir=self.root,
                                                    groups=("pipe_utilization",), receipts=receipts)
        all_groups = aggregate_launches(self.root, all_entries, receipts, all_selection, limit=None)["groups"]
        repeated_group = next(group for group in all_groups if group["target_name"] == "kernel")
        self.assertEqual(repeated_group["count"], 46)
        self.assertFalse(repeated_group["complete"])
        self.assertTrue(repeated_group["ordinal_mapping_conflict"])

    def test_partial_invocation_capture_checks_declared_target_count_before_scored_mapping(self):
        entries, basic = self.invocation_entries(23)
        receipts = SimpleNamespace(allows=lambda segment: True)
        declared = SimpleNamespace(segments={"op": SimpleNamespace(expected_display_names={"kernel": "kernel"},
                                                                   expected_counts={"kernel": 46})})
        selected, selection = select_launches(entries, tuple(entries + basic),
            {"program_launches": 23, "steady_state_skip": 3}, "scored", run_dir=self.root,
            groups=("pipe_utilization",), receipts=receipts, declared_coverage=declared)
        self.assertEqual(selected, [])
        conflict = selection["coverage"][0]["ordinal_mapping_conflict"]
        self.assertEqual(conflict["declared_target_launch_count"], 46)
        self.assertEqual(conflict["out_of_declared_range_basic_indices"], [])


if __name__ == "__main__":
    unittest.main()
