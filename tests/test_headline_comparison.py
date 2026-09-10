"""Headline comparison behavior through analyzed run inputs."""

import copy
import json
import sys
import tempfile
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
            "cann_version": {"value": "8.3.RC2"},
            "hardware": {"summary": {"value": "Ascend 910B2"}},
            "profile_command": {"value": "msprof op --aic-metrics=PipeUtilization"},
            "profile_output_segments": {"op": {"kind": "op"}},
        }
        for run_dir in (self.baseline, self.candidate):
            (run_dir / "analysis").mkdir(parents=True)
            self.write_summary(run_dir, self.summary)
            (run_dir / "analysis" / "provenance.json").write_text(json.dumps(self.provenance))

    def write_summary(self, run_dir, summary):
        (run_dir / "analysis" / "summary.json").write_text(json.dumps(summary))

    def comparison(self):
        return build_comparison(self.baseline, self.candidate)

    def test_different_metrics_keep_values_without_delta(self):
        candidate = copy.deepcopy(self.summary)
        candidate["headlines"]["pipe_utilization"].update(field="aiv_vec_ratio", value=0.8)
        self.write_summary(self.candidate, candidate)
        comparison = self.comparison()
        row = comparison["headlines"][0]
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
                row = self.comparison()["headlines"][0]
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
                    row = self.comparison()["headlines"][0]
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
                row = self.comparison()["headlines"][0]
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
        row = comparison["headlines"][0]
        self.assertEqual(comparison["compatibility"]["status"], "warning")
        self.assertEqual(comparison["benchmark"], original["benchmark"])
        self.assertEqual(row["status"], "not_comparable")
        self.assertIn("profiler.cann_version mismatch", row["comparison_reasons"])
        self.assertIsNone(row["delta"])

    def test_matching_metric_compares_values_and_handles_zero_baseline(self):
        candidate = copy.deepcopy(self.summary)
        candidate["headlines"]["pipe_utilization"]["value"] = 0.8
        self.write_summary(self.candidate, candidate)
        row = self.comparison()["headlines"][0]
        self.assertEqual(row["status"], "changed")
        self.assertTrue(row["numeric"])
        self.assertEqual(row["comparison_reasons"], [])
        self.assertAlmostEqual(row["delta"], -0.1)
        self.assertAlmostEqual(row["delta_pct"], -11.1111111111)
        self.summary["headlines"]["pipe_utilization"]["value"] = 0.0
        self.write_summary(self.baseline, self.summary)
        row = self.comparison()["headlines"][0]
        self.assertEqual(row["delta"], 0.8)
        self.assertIsNone(row["delta_pct"])
        self.write_summary(self.candidate, self.summary)
        self.assertEqual(self.comparison()["headlines"][0]["status"], "same")

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
                row = self.comparison()["headlines"][0]
                self.assertEqual(row["status"], "not_comparable")
                self.assertIn(reason, row["comparison_reasons"])
                self.assertIsNone(row["delta"])
                self.assertIsNone(row["delta_pct"])

    def test_missing_headline_remains_missing(self):
        candidate = copy.deepcopy(self.summary)
        candidate["headlines"] = {}
        self.write_summary(self.candidate, candidate)
        row = self.comparison()["headlines"][0]
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
        self.assertTrue(self.comparison()["headlines"][0]["numeric"])
        summary["target_identity"]["segments"]["op"]["expected"]["names"] = ["other_kernel"]
        self.write_summary(self.candidate, summary)
        self.assertIn("target mismatch", self.comparison()["headlines"][0]["comparison_reasons"])
        summary["target_identity"]["segments"] = {"app": selected_identity}
        self.write_summary(self.candidate, summary)
        self.assertIn("target unverified", self.comparison()["headlines"][0]["comparison_reasons"])

    def test_missing_profiler_context_withholds_delta(self):
        (self.candidate / "analysis" / "provenance.json").unlink()
        row = self.comparison()["headlines"][0]
        self.assertEqual(row["status"], "not_comparable")
        self.assertIn("profiler.cann_version missing", row["comparison_reasons"])
        self.assertIsNone(row["delta"])
