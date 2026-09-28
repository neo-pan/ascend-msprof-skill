"""End-to-end evidence output without generated optimization prescriptions."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tests.helpers_shared import (
    fresh_real_run, fresh_op_basic_block_dim_with_timing_sim_run,
    fresh_real_app_op_stdout_run, write_minimal_app_timing,
)
from tests.test_tilelang_design_feedback_fixtures import copy_case
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.summarize_candidate import build_candidate_summary, render_markdown
from ascend_msprof_skill.compare_runs import build_comparison
from ascend_msprof_skill.generate_report import build_report


from ascend_msprof_skill.assessment_types import CandidateSummary

class EvidenceAssistanceTests(unittest.TestCase):
    def assert_descriptive_output(self, value):
        removed = {
            "optimization_directions", "experiment_hint", "next_experiment",
            "expected_profiler_change", "inspect_code_area", "related_design_variables",
            "optimization_direction_count",
        }
        if isinstance(value, dict):
            self.assertFalse(removed & value.keys())
            self.assertNotEqual(value.get("kind"), "inspection_hypothesis")
            for child in value.values():
                self.assert_descriptive_output(child)
        elif isinstance(value, list):
            for child in value:
                self.assert_descriptive_output(child)

    def test_complete_partial_and_simulator_evidence_reaches_all_outputs_without_advice(self):
        for fixture in (fresh_real_run, fresh_op_basic_block_dim_with_timing_sim_run,
                        fresh_real_app_op_stdout_run, write_minimal_app_timing):
            with self.subTest(fixture=fixture.__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                run_dir = fixture(root) or root
                raw = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (run_dir / "reports").rglob("*") if p.is_file()}
                artifacts = write_evidence_model(run_dir)
                summary = json.loads(artifacts.summary_path.read_text())
                candidate = build_candidate_summary(run_dir).model_dump(mode="json")
                comparison = build_comparison(run_dir, run_dir).model_dump(mode="json")
                report = build_report(summary, run_dir)
                for result in (summary, candidate, comparison):
                    self.assert_descriptive_output(result)
                self.assertEqual(summary["analysis_schema_version"], "5.2")
                self.assertEqual(candidate["candidate_summary_schema_version"], "4.2")
                self.assertEqual(comparison["comparison_schema_version"], "4.2")
                self.assertEqual(candidate["mechanism_assessment"]["contract_version"], "3.2")
                self.assertTrue(summary["analysis_dimensions"])
                self.assertTrue(artifacts.raw_artifact_index.artifacts)
                self.assertTrue(candidate["mechanism_assessment"]["questions"])
                for rendered in (report, render_markdown(CandidateSummary.model_validate(candidate)), artifacts.key_metrics_path.read_text()):
                    for phrase in ("Optimization Directions", "Next experiment:", "Inspect code area:",
                                   "Expected profiler change:", "before changing kernel code"):
                        self.assertNotIn(phrase, rendered)
                self.assertIn("## 3. Observations", report)
                self.assertIn("## Evidence Questions", report)
                self.assertTrue(all(t["source"] == "simulator_hotspots"
                                    for t in candidate["inspection_targets"]))
                self.assertEqual(raw, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in raw})
                if fixture is fresh_op_basic_block_dim_with_timing_sim_run:
                    self.assertTrue(candidate["inspection_targets"])
                    self.assertTrue(all(t["artifact"] for t in candidate["inspection_targets"]))
                if fixture is fresh_real_app_op_stdout_run:
                    self.assertTrue(summary["stdout_sections"]["performance_summary"]["messages"])

    def test_short_overview_keeps_authority_and_sourced_observations(self):
        from ascend_msprof_skill._evidence_text_summary import write_text_summary
        from ascend_msprof_skill.operator_evidence import OperatorEvidence
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = fresh_real_run(root)
            artifacts = write_evidence_model(run_dir)
            original_summary = artifacts.summary_path.read_bytes()
            original_index = artifacts.raw_artifact_index_path.read_bytes()
            write_text_summary(artifacts.key_metrics_path, artifacts.summary)
            text = artifacts.key_metrics_path.read_text()
            self.assertLess(text.index("target_identity:"), text.index("## Recorded Observations"))
            self.assertLess(text.index("evidence_readiness.level:"), text.index("## Recorded Observations"))
            self.assertIn(artifacts.summary.target_identity.status, text)
            self.assertIn(artifacts.summary.evidence_readiness.level, text)
            for claim in artifacts.summary.evidence_readiness.blocked_claims:
                self.assertIn(claim, text)
            for warning in artifacts.summary.warnings:
                self.assertIn(warning, text)
            self.assertNotIn("    same-record:", text)
            for group, evidence in artifacts.summary.headlines.items():
                for artifact in evidence.artifacts:
                    self.assertIn(artifact.artifact, text)
                    if isinstance(evidence, OperatorEvidence):
                        for obs in artifact.observations:
                            self.assertIn(f"{obs.name}: {obs.value:g} {obs.unit} ({obs.statistic})", text)
                            self.assertIn(f"record={obs.source.record}; column={obs.source.column}; field={obs.source.field}", text)
            self.assertEqual(original_summary, artifacts.summary_path.read_bytes())
            self.assertEqual(original_index, artifacts.raw_artifact_index_path.read_bytes())

    def test_reading_guide_routes_every_headline_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_run(Path(tmp))
            artifacts = write_evidence_model(run_dir)
            guide = artifacts.reading_guide_path.read_text()
            self.assertIn("summary.json", guide)
            self.assertIn("raw_artifact_index.json", guide)
            self.assertIn("target_identity", guide)
            self.assertIn("joint-row", guide)
            for group, evidence in artifacts.summary.headlines.items():
                for artifact_index, artifact in enumerate(evidence.artifacts):
                    self.assertIn(artifact.artifact, guide)
                    self.assertIn(f"summary.json#/headlines/{group}/artifacts/{artifact_index}", guide)
            self.assertTrue(artifacts.summary_path.read_text())
            self.assertTrue(artifacts.raw_artifact_index_path.read_text())

    def test_complete_metrics_need_no_generated_hypothesis_or_optional_source_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = copy_case("memory_cache/positive", Path(tmp), "complete")
            summary = write_evidence_model(run_dir).summary
            result = build_candidate_summary(run_dir).model_dump(mode="json")
            self.assertEqual(summary.evidence_readiness.level, "available")
            self.assertNotIn("source_or_workload_context", summary.evidence_readiness.missing_evidence_families)
            self.assertNotIn("collect_source_or_context", {
                a.id for a in summary.evidence_readiness.recommended_followups})
            questions = {q["id"]: q for q in result["mechanism_assessment"]["questions"]}
            for family in ("memory_cache", "pipe_arithmetic"):
                self.assertEqual(questions[family]["status"], "available")
                self.assertTrue(questions[family]["available_evidence"])
                self.assertFalse(questions[family]["missing_evidence"])
            self.assertTrue(all(f["kind"] == "metric_observation"
                                for f in result["mechanism_assessment"]["findings"]))

    def test_missing_metric_is_named_without_discarding_available_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = copy_case("memory_cache/positive", Path(tmp), "complete")
            for artifact in (run_dir / "reports").rglob("ArithmeticUtilization.csv"):
                artifact.unlink()
            write_evidence_model(run_dir)
            result = build_candidate_summary(run_dir).model_dump(mode="json")
            questions = {q["id"]: q for q in result["mechanism_assessment"]["questions"]}
            pipe = questions["pipe_arithmetic"]
            self.assertEqual({Path(e["artifact"]).name for e in pipe["missing_evidence"]},
                             {"ArithmeticUtilization.csv"})
            self.assertTrue(any(Path(e["artifact"]).name == "PipeUtilization.csv"
                                for e in pipe["available_evidence"]))
            self.assertEqual(questions["memory_cache"]["status"], "available")
            self.assert_descriptive_output(result)
