"""Headline comparison behavior through analyzed run inputs."""

import copy
import csv
import json
import sys
import tempfile
import shutil
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ascend_msprof_skill.compare_runs import build_comparison, render_markdown  # noqa: E402


class HeadlineComparisonTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.baseline = Path(temporary.name) / "baseline"
        self.candidate = Path(temporary.name) / "candidate"
        self.summary = {
            "target_identity": {"status": "match", "expected": {"names": ["kernel"]}},
            "metric_scope": {"value": "PipeUtilization", "artifact": "logs/command.txt"},
            "headlines": {
                "pipe_utilization": {
                    "name": "cube0", "value": 0.9, "field": "aic_mte2_ratio",
                    "field_kind": "utilization_or_ratio", "segment": "op",
                    "metric_scope": "PipeUtilization",
                    "file": "reports/op/OPPROF_001/PipeUtilization.csv",
                    "raw_row": {"block_id": "0", "sub_block_id": "cube0", "aic_mte2_ratio": "0.9"},
                },
            },
        }
        self.provenance = {
            "cann_version": {"value": "8.3.RC2", "source": {"artifact": "logs/cann_version.cfg", "field": "toolkit_running_version"}},
            "hardware": {"summary": {"value": "Ascend 910B2"}},
            "profile_command": {"value": "msprof op --aic-metrics=PipeUtilization"},
            "profile_output_segments": {"op": {"kind": "op"}},
        }
        self.workload = {"id": "add", "shape": [128, 256], "dtype": "float32", "case_count": 1}
        for run_dir in (self.baseline, self.candidate):
            (run_dir / "analysis").mkdir(parents=True)
            self.write_summary(run_dir, self.summary)
            (run_dir / "analysis" / "provenance.json").write_text(json.dumps(self.provenance))
            self.write_workload(run_dir, self.workload)

    def write_workload(self, run_dir, workload, artifact="profile_context.json"):
        (run_dir / "analysis" / artifact).write_text(json.dumps({"benchmark": {"workload": workload}}))

    def test_workload_mismatch_missing_and_conflict_block_deltas(self):
        for field, changed in {"id": "other", "shape": [256, 256], "dtype": "float16", "case_count": 2}.items():
            for status in ("mismatch", "missing", "conflict"):
                with self.subTest(field=field, status=status):
                    workload = dict(self.workload)
                    workload[field] = changed
                    if status == "missing":
                        del workload[field]
                    self.write_workload(self.candidate, workload)
                    tile = self.candidate / "analysis" / "tilelang_context.json"
                    if status == "conflict":
                        self.write_workload(self.candidate, self.workload, tile.name)
                    row = self.comparison()["mechanism_assessment"]["headlines"][0]
                    self.assertIn(f"workload.{field} {status}", row["comparison_reasons"])
                    self.assertFalse(row["numeric"])
                    self.assertIsNone(row["delta"])
                    tile.unlink(missing_ok=True)
        for run_dir in (self.baseline, self.candidate):
            self.write_workload(run_dir, {})
        self.assertIn("workload.shape missing", self.comparison()["mechanism_assessment"]["headlines"][0]["comparison_reasons"])

    def test_workload_sources_are_shared_with_candidate_mechanism(self):
        from ascend_msprof_skill.summarize_candidate import build_candidate_summary
        self.write_workload(self.candidate, self.workload, "tilelang_context.json")
        comparison = self.comparison()
        checks = comparison["mechanism_assessment"]["workload_checks"]
        self.assertTrue(comparison["mechanism_assessment"]["headlines"][0]["numeric"])
        self.assertEqual(len(checks[0]["sources"]["b"]), 2)
        self.assertEqual(checks[0]["sources"]["b"][0]["source"]["field_ref"], "benchmark.workload.id")
        candidate = build_candidate_summary(self.candidate, self.baseline)
        self.assertEqual(checks, candidate["mechanism_assessment"]["workload_checks"])

    def test_version_comparison_requires_matching_components(self):
        for field, artifact, expected in (
            ("runtime_running_version", "logs/cann_version.cfg", "component_mismatch"),
            ("version", "logs/toolkit_install.info", "match"),
            (None, None, "missing"),
        ):
            with self.subTest(field=field):
                provenance = copy.deepcopy(self.provenance)
                provenance["cann_version"]["source"] = {"artifact": artifact, "field": field}
                (self.candidate / "analysis/provenance.json").write_text(json.dumps(provenance))
                comparison = self.comparison()
                self.assertEqual(comparison["mechanism_assessment"]["compatibility"]["checks"][0]["status"], expected)
                self.assertEqual(comparison["mechanism_assessment"]["compatibility"]["checks"][0]["status"], expected)
                self.assertEqual(comparison["mechanism_assessment"]["headlines"][0]["numeric"], expected == "match")

    def test_version_comparison_uses_shared_toolkit_evidence(self):
        from ascend_msprof_skill.generate_provenance import build_manifest, write_manifest

        for run_dir in (self.baseline, self.candidate):
            logs = run_dir / "logs"
            logs.mkdir()
            (logs / "toolkit_install.info").write_text("package_name=Ascend-cann-toolkit\nversion=8.5.2\n")
        for runtime_run in (self.baseline, self.candidate):
            with self.subTest(runtime_run=runtime_run.name):
                for run_dir in (self.baseline, self.candidate):
                    (run_dir / "logs/cann_version.cfg").unlink(missing_ok=True)
                cfg = runtime_run / "logs/cann_version.cfg"
                cfg.write_text("runtime_running_version=[8.5.2]\n")
                for run_dir in (self.baseline, self.candidate):
                    write_manifest(run_dir, {**self.provenance, "cann_version": build_manifest(run_dir)["cann_version"]})
                comparison = self.comparison()
                check = comparison["mechanism_assessment"]["compatibility"]["checks"][0]
                self.assertEqual(check["status"], "match")
                for role in ("a", "b"):
                    self.assertEqual(check[role]["source"], {"artifact": "logs/toolkit_install.info", "field": "version"})
                self.assertEqual(comparison["mechanism_assessment"]["compatibility"]["checks"][0]["status"], "match")
                self.assertTrue(comparison["mechanism_assessment"]["headlines"][0]["numeric"])

                cfg.write_text("runtime_running_version=[8.6.0]\n")
                write_manifest(runtime_run, {**self.provenance, "cann_version": build_manifest(runtime_run)["cann_version"]})
                conflict = self.comparison()
                self.assertEqual(conflict["mechanism_assessment"]["compatibility"]["checks"][0]["status"], "conflict")
                self.assertFalse(conflict["mechanism_assessment"]["headlines"][0]["numeric"])
                cfg.unlink()

    def test_extra_toolkit_evidence_preserves_shared_component_comparison(self):
        from ascend_msprof_skill.generate_provenance import build_manifest, write_manifest

        for component in ("runtime", "compiler", "opp"):
            for extra_roles in ((), ("a",), ("b",), ("a", "b")):
                for candidate_version, expected in (("8.5.2", "match"), ("8.6.0", "mismatch")):
                    with self.subTest(component=component, extra_roles=extra_roles, candidate_version=candidate_version):
                        for role, run_dir, version in (("a", self.baseline, "8.5.2"), ("b", self.candidate, candidate_version)):
                            logs = run_dir / "logs"
                            logs.mkdir(exist_ok=True)
                            (logs / "cann_version.cfg").write_text(f"{component}_running_version=[{version}]\n")
                            info = logs / "toolkit_install.info"
                            if role in extra_roles:
                                info.write_text(f"package_name=Ascend-cann-toolkit\nversion={version}\n")
                            else:
                                info.unlink(missing_ok=True)
                            write_manifest(run_dir, {**self.provenance, "cann_version": build_manifest(run_dir)["cann_version"]})
                        comparison = self.comparison()
                        check = comparison["mechanism_assessment"]["compatibility"]["checks"][0]
                        self.assertEqual(check["status"], expected)
                        source = {"artifact": "logs/toolkit_install.info", "field": "version"} if len(extra_roles) == 2 else {
                            "artifact": "logs/cann_version.cfg", "field": f"{component}_running_version",
                        }
                        for role in ("a", "b"):
                            self.assertEqual(check[role]["source"], source)
                        self.assertEqual(comparison["mechanism_assessment"]["compatibility"]["checks"][0]["status"], expected)
                        self.assertEqual(comparison["mechanism_assessment"]["headlines"][0]["numeric"], expected == "match")

    def test_real_pair_offline_replay_and_synthetic_schema_boundaries(self):
        from ascend_msprof_skill.generate_provenance import build_manifest, write_manifest
        from ascend_msprof_skill.evidence_model import write_evidence_model
        fixture = Path(__file__).parent / "fixtures/real_cann852_workload_pair"
        for name, run_dir in (("shape-128", self.baseline), ("shape-256", self.candidate)):
            shutil.copytree(fixture / name, run_dir, dirs_exist_ok=True)
            write_manifest(run_dir, build_manifest(run_dir))
            # Validate stored evidence before reanalysis can replace it.
            stored = json.loads((run_dir / "analysis/summary.json").read_text())
            for item in stored["headlines"].values():
                with (run_dir / item["file"]).open() as stream:
                    rows = list(csv.DictReader(stream))
                self.assertIn(item.get("raw_row", item.get("first_row")), rows)
            self.assertTrue(any(row["numeric"] for row in build_comparison(run_dir, run_dir)["mechanism_assessment"]["headlines"]))
            write_evidence_model(run_dir)
        comparison = self.comparison()
        expected = {"op_basic_info", "arithmetic_utilization", "l2_cache", "memory", "resource_conflict"}
        for row in comparison["mechanism_assessment"]["headlines"]:
            if row["group"] in expected:
                self.assertIn("workload.shape mismatch", row["comparison_reasons"])
                self.assertNotIn("profiler.cann_version missing", row["comparison_reasons"])
                self.assertFalse(row["numeric"])
        control = build_comparison(self.baseline, self.baseline)
        self.assertTrue(expected <= {r["group"] for r in control["mechanism_assessment"]["headlines"] if r["numeric"]})
        self.assertIn("workload.shape mismatch", render_markdown(comparison))
        (self.baseline / "logs/toolkit_install.info").unlink()
        write_manifest(self.baseline, build_manifest(self.baseline))
        missing_version = next(r for r in self.comparison()["mechanism_assessment"]["headlines"] if r["group"] == "memory")
        self.assertIn("profiler.cann_version missing", missing_version["comparison_reasons"])

        # Synthetic mutations of a real CSV, always restore the valid version gate.
        shutil.copyfile(fixture / "shape-128/logs/toolkit_install.info", self.baseline / "logs/toolkit_install.info")
        write_manifest(self.baseline, build_manifest(self.baseline))
        path = next((self.baseline / "reports").rglob("Memory.csv"))
        original = path.read_text()
        for field, reason in (("Unit", "unsupported unit layout"), ("Units", "unsupported unit layout"), ("Unknown Bandwidth", "unsupported metric field")):
            with self.subTest(synthetic=field):
                lines = original.splitlines()
                if field in ("Unit", "Units"):
                    changed = "\n".join(line + ("," + field if i == 0 else ",GB/s") for i, line in enumerate(lines)) + "\n"
                else:
                    # Make the unfamiliar field the selected maximum without changing its value.
                    changed = original.replace("GM_to_UB_bw_usage_rate(%)", "Unknown Bandwidth usage rate")
                path.write_text(changed)
                write_evidence_model(self.baseline)
                row = next(r for r in build_comparison(self.baseline, self.baseline)["mechanism_assessment"]["headlines"] if r["group"] == "memory")
                self.assertIn(reason, row["comparison_reasons"])
                self.assertFalse(row["numeric"])
                self.assertTrue(row["a"]["schema_issues"][0]["source"]["artifact"].endswith("Memory.csv"))
        path.write_text(original)

    def write_summary(self, run_dir, summary):
        (run_dir / "analysis" / "summary.json").write_text(json.dumps(summary))

    def comparison(self):
        return build_comparison(self.baseline, self.candidate)

    def test_different_metrics_keep_values_without_delta(self):
        candidate = copy.deepcopy(self.summary)
        candidate["headlines"]["pipe_utilization"].update(field="aiv_vec_ratio", value=0.8)
        self.write_summary(self.candidate, candidate)
        comparison = self.comparison()
        row = comparison["mechanism_assessment"]["headlines"][0]
        self.assertEqual(row["status"], "not_comparable")
        self.assertEqual(row["a"]["value"], 0.9)
        self.assertEqual(row["b"]["value"], 0.8)
        self.assertIsNone(row["delta"])
        self.assertIsNone(row["delta_pct"])
        self.assertFalse(row["numeric"])
        self.assertIn("field mismatch", row["comparison_reasons"])
        report = render_markdown(comparison)
        self.assertIn("Field A | Field B", report)
        self.assertIn("aic_mte2_ratio", report)
        self.assertIn("aiv_vec_ratio", report)
        self.assertIn("field mismatch", report)
        self.assertNotIn("-11.1111", report)

    def test_target_and_block_context_must_match(self):
        cases = [
            ("target unverified", "identity", {"status": "unverified", "expected": {"names": ["kernel"]}}),
            ("target mismatch", "identity", {"status": "match", "expected": {"names": ["other_kernel"]}}),
            ("target ambiguous", "identity", {"status": "match", "expected": {"names": ["kernel", "other_kernel"]}}),
            ("block_scope mismatch", "row", {"block_id": "1", "sub_block_id": "cube0"}),
            ("block_scope mismatch", "row", {"block_id": "0", "sub_block_id": "vector0"}),
            ("block_scope mismatch", "row", {"sub_block_id": "cube0"}),
        ]
        for reason, kind, value in cases:
            with self.subTest(reason=reason, value=value):
                candidate = copy.deepcopy(self.summary)
                if kind == "identity":
                    candidate["target_identity"] = value
                else:
                    candidate["headlines"]["pipe_utilization"]["raw_row"] = value
                self.write_summary(self.candidate, candidate)
                row = self.comparison()["mechanism_assessment"]["headlines"][0]
                self.assertEqual(row["status"], "not_comparable")
                self.assertIn(reason, row["comparison_reasons"])
                self.assertIsNone(row["delta"])

    def test_empty_block_identifiers_withhold_delta(self):
        for field in ("block_id", "sub_block_id"):
            for value in ("", None):
                with self.subTest(field=field, value=value):
                    baseline = copy.deepcopy(self.summary)
                    baseline["headlines"]["pipe_utilization"]["raw_row"][field] = value
                    candidate = copy.deepcopy(baseline)
                    candidate["headlines"]["pipe_utilization"]["value"] = 0.8
                    self.write_summary(self.baseline, baseline)
                    self.write_summary(self.candidate, candidate)
                    row = self.comparison()["mechanism_assessment"]["headlines"][0]
                    self.assertEqual(row["status"], "not_comparable")
                    self.assertFalse(row["numeric"])
                    self.assertIsNone(row["delta"])
                    self.assertIsNone(row["delta_pct"])
                    self.assertIn("block_scope missing", row["comparison_reasons"])
                    self.assertEqual(row["a"]["value"], 0.9)
                    self.assertEqual(row["b"]["value"], 0.8)

    def test_zero_identifiers_and_absent_block_columns_allow_delta(self):
        for raw_row in ({"block_id": 0, "sub_block_id": 0}, {"aic_mte2_ratio": "0.9"}):
            with self.subTest(raw_row=raw_row):
                baseline = copy.deepcopy(self.summary)
                baseline["headlines"]["pipe_utilization"]["raw_row"] = raw_row
                candidate = copy.deepcopy(baseline)
                candidate["headlines"]["pipe_utilization"]["value"] = 0.8
                self.write_summary(self.baseline, baseline)
                self.write_summary(self.candidate, candidate)
                row = self.comparison()["mechanism_assessment"]["headlines"][0]
                self.assertEqual(row["status"], "changed")
                self.assertTrue(row["numeric"])
                self.assertEqual(row["comparison_reasons"], [])
                self.assertAlmostEqual(row["delta"], -0.1)

    def test_profiler_compatibility_is_required_only_for_headline_deltas(self):
        original = self.comparison()
        provenance = copy.deepcopy(self.provenance)
        provenance["cann_version"]["value"] = "9.0"
        (self.candidate / "analysis" / "provenance.json").write_text(json.dumps(provenance))
        comparison = self.comparison()
        row = comparison["mechanism_assessment"]["headlines"][0]
        self.assertEqual(comparison["mechanism_assessment"]["compatibility"]["status"], "warning")
        self.assertEqual(comparison["performance_assessment"], original["performance_assessment"])
        self.assertEqual(row["status"], "not_comparable")
        self.assertIn("profiler.cann_version mismatch", row["comparison_reasons"])
        self.assertIsNone(row["delta"])

    def test_matching_metric_compares_values_and_handles_zero_baseline(self):
        candidate = copy.deepcopy(self.summary)
        candidate["headlines"]["pipe_utilization"]["value"] = 0.8
        self.write_summary(self.candidate, candidate)
        row = self.comparison()["mechanism_assessment"]["headlines"][0]
        self.assertEqual(row["status"], "changed")
        self.assertTrue(row["numeric"])
        self.assertEqual(row["comparison_reasons"], [])
        self.assertAlmostEqual(row["delta"], -0.1)
        self.assertAlmostEqual(row["delta_pct"], -11.1111111111)
        self.summary["headlines"]["pipe_utilization"]["value"] = 0.0
        self.write_summary(self.baseline, self.summary)
        row = self.comparison()["mechanism_assessment"]["headlines"][0]
        self.assertEqual(row["delta"], 0.8)
        self.assertIsNone(row["delta_pct"])
        self.write_summary(self.candidate, self.summary)
        self.assertEqual(self.comparison()["mechanism_assessment"]["headlines"][0]["status"], "same")

    def test_changed_or_missing_metric_context_blocks_delta(self):
        for field, value, reason in [
            ("field", "aic_mte2_ratio(%)", "field mismatch"),
            ("field", None, "field missing"),
            ("field_kind", "other", "field_kind mismatch"),
            ("name", "vector0", "name mismatch"),
            ("segment", "app", "segment mismatch"),
            ("metric_scope", "Default", "metric_scope mismatch"),
            ("metric_scope", None, "metric_scope missing"),
            ("raw_row", None, "block_scope missing"),
            ("value", None, "finite numeric value missing"),
        ]:
            with self.subTest(field=field, value=value):
                candidate = copy.deepcopy(self.summary)
                candidate["headlines"]["pipe_utilization"][field] = value
                self.write_summary(self.candidate, candidate)
                row = self.comparison()["mechanism_assessment"]["headlines"][0]
                self.assertEqual(row["status"], "not_comparable")
                self.assertIn(reason, row["comparison_reasons"])
                self.assertIsNone(row["delta"])
                self.assertIsNone(row["delta_pct"])

    def test_missing_headline_remains_missing(self):
        candidate = copy.deepcopy(self.summary)
        candidate["headlines"] = {}
        self.write_summary(self.candidate, candidate)
        row = self.comparison()["mechanism_assessment"]["headlines"][0]
        self.assertEqual(row["status"], "missing")
        self.assertEqual(row["a"]["value"], 0.9)
        self.assertFalse(row["numeric"])
        self.assertIsNone(row["delta"])

    def test_target_identity_uses_the_headline_segment(self):
        summary = copy.deepcopy(self.summary)
        selected_identity = copy.deepcopy(summary["target_identity"])
        summary["target_identity"]["expected"]["names"] = ["kernel", "other_kernel"]
        summary["target_identity"]["segments"] = {"op": selected_identity}
        for run_dir in (self.baseline, self.candidate):
            self.write_summary(run_dir, summary)
        self.assertTrue(self.comparison()["mechanism_assessment"]["headlines"][0]["numeric"])
        summary["target_identity"]["segments"]["op"]["expected"]["names"] = ["other_kernel"]
        self.write_summary(self.candidate, summary)
        self.assertIn("target mismatch", self.comparison()["mechanism_assessment"]["headlines"][0]["comparison_reasons"])
        summary["target_identity"]["segments"] = {"app": selected_identity}
        self.write_summary(self.candidate, summary)
        self.assertIn("target unverified", self.comparison()["mechanism_assessment"]["headlines"][0]["comparison_reasons"])

    def test_missing_profiler_context_withholds_delta(self):
        (self.candidate / "analysis" / "provenance.json").unlink()
        row = self.comparison()["mechanism_assessment"]["headlines"][0]
        self.assertEqual(row["status"], "not_comparable")
        self.assertIn("profiler.cann_version missing", row["comparison_reasons"])
        self.assertIsNone(row["delta"])
