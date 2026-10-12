"""Explicit caller timing and local code remain independently auditable."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from ascend_msprof_skill.caller_evidence import (CALLER_ARTIFACT, load_caller_evidence,
                                                load_source_snapshots, caller_context_lines)
from ascend_msprof_skill.evidence_binding import digest, snapshot, verify_reference
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.question_evidence import read_question_from_dir, render_question
from tests.helpers_shared import fresh_real_run


class CallerExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = fresh_real_run(Path(self.temp.name))
        write_evidence_model(self.root)
        caller = self.root / "analysis/caller"
        caller.mkdir()
        (caller / "source.py").write_bytes(b"# original source\r\n")
        (caller / "generated.cc").write_bytes(b"// generated scheduling\n")
        self.source_sha = digest(caller / "source.py")
        self.report = {"candidate_id": "candidate", "status": "success", "correctness_ok": True,
            "tolerance_passed": True, "metrics": {"formal_measurement_mode": "msprof_op",
            "profile_source_sha256": self.source_sha, "device_program_duration_ms": 0.01584,
            "device_program_launches": 8, "device_program_steady_state_skip": 3,
            "compilation_evidence": {"generated_sources": ["/removed/external/generated.cc"],
                "artifact_sha256": {"/removed/external/generated.cc": digest(caller / "generated.cc")}},
            "device_program_profile_receipts": [
                {"attempt_index": 1, "duration_ms": 0.01584},
                {"attempt_index": 2, "duration_ms": 0.01542},
                {"attempt_index": 3, "duration_ms": 0.01590}]}}
        (caller / "source-report.json").write_text(json.dumps(self.report))
        def ref(name):
            path = caller / name
            return {"path": str(path.relative_to(self.root)), "sha256": digest(path),
                    "original_path": f"/removed/external/{name}"}
        self.payload = {"schema_version": 1, "producer": "kernel-agent",
            "measurement": {"mode": "msprof_op", "boundary": "executor_device_program_task_duration",
                "metric": "device_program_duration_ms", "unit": "ms", "value": 0.01584,
                "aggregation": {"within_process": None, "across_process": None},
                "program_launches": 8, "steady_state_skip": 3, "sample_index": 2,
                "sample_duration_ms": 0.01542, "samples": self.report["metrics"]["device_program_profile_receipts"]},
            "identity": {"candidate_id": "candidate", "source_sha256": self.source_sha,
                         "measurement_identity": None, "measurement_protocol": None},
            "correctness": {"status": "success", "correctness_ok": True, "tolerance_passed": True},
            "source_report": ref("source-report.json"), "snapshots": {
                "source": ref("source.py"), "generated": [ref("generated.cc")]},
            "origin": {"kind": "explicit_report_export", "sample_attempt_index": 2,
                       "source_sha256": self.source_sha}, "issues": []}
        self.save()

    def save(self):
        (self.root / CALLER_ARTIFACT).write_text(json.dumps(self.payload))

    def test_report_aggregate_and_current_process_are_distinct(self):
        context = load_caller_evidence(self.root)
        self.assertEqual(context["status"], "verified")
        self.assertEqual(context["measurement"]["value"], 0.01584)
        self.assertEqual(context["measurement"]["sample_duration_ms"], 0.01542)
        text = "\n".join(caller_context_lines(context))
        self.assertIn("0.01584", text)
        self.assertIn("0.01542", text)
        self.assertIn("not natural-launch", text)

    def test_relocation_requires_only_run_local_bytes(self):
        bound = snapshot(self.root, [])
        moved = Path(self.temp.name) / "moved"
        shutil.move(str(self.root), moved)
        self.assertEqual(load_caller_evidence(moved)["status"], "verified")
        self.assertEqual(verify_reference(moved, bound)["status"], "verified")
        self.assertEqual((moved / "analysis/caller/source.py").read_bytes(), b"# original source\r\n")

    def test_code_mutation_invalidates_question_snapshot_and_binding(self):
        bound = snapshot(self.root, [])
        (self.root / "analysis/caller/generated.cc").write_text("// changed\n")
        context = load_caller_evidence(self.root)
        self.assertEqual(context["status"], "partial")
        self.assertEqual(context["snapshots"]["generated"][0]["status"], "mismatch")
        self.assertEqual(verify_reference(self.root, bound)["status"], "stale")

    def test_changed_report_value_is_not_a_verified_export(self):
        self.payload["measurement"]["value"] = 0.001
        self.save()
        context = load_caller_evidence(self.root)
        self.assertEqual(context["status"], "partial")
        self.assertTrue(any(x["source"]["field"] == "measurement.value" for x in context["issues"]))

    def test_wrong_process_sample_does_not_borrow_aggregate(self):
        self.payload["measurement"]["sample_duration_ms"] = self.payload["measurement"]["value"]
        self.save()
        context = load_caller_evidence(self.root)
        self.assertEqual(context["status"], "partial")
        self.assertTrue(any(x["source"]["field"] == "measurement.sample_duration_ms" for x in context["issues"]))

    def test_another_valid_process_is_not_current_run(self):
        self.payload["measurement"].update(sample_index=3, sample_duration_ms=0.01590)
        self.save()
        context = load_caller_evidence(self.root)
        self.assertEqual(context["status"], "partial")
        self.assertTrue(any(x["source"]["field"] == "origin.sample_attempt_index" for x in context["issues"]))

    def test_aggregation_cannot_override_original_report(self):
        self.payload["measurement"]["aggregation"]["within_process"] = "sum of kernel medians"
        self.save()
        context = load_caller_evidence(self.root)
        self.assertEqual(context["status"], "partial")
        self.assertTrue(any(x["source"]["field"] == "measurement.aggregation" for x in context["issues"]))

    def test_generated_hash_must_match_original_report_even_if_local_reference_is_updated(self):
        path = self.root / "analysis/caller/generated.cc"
        path.write_text("// unrelated code\n")
        self.payload["snapshots"]["generated"][0]["sha256"] = digest(path)
        self.save()
        context = load_caller_evidence(self.root)
        self.assertEqual(context["status"], "partial")
        self.assertTrue(any(x["source"]["field"] == "snapshots.generated[0].sha256" for x in context["issues"]))

    def test_omitting_a_declared_generated_product_is_partial(self):
        self.payload["snapshots"]["generated"] = []
        self.save()
        context = load_caller_evidence(self.root)
        self.assertEqual(context["status"], "partial")
        self.assertTrue(any(x["source"]["field"] == "snapshots.generated" for x in context["issues"]))

    def test_invalid_optional_export_preserves_profile_observations(self):
        before = read_question_from_dir(self.root, "pipe", limit=1)["facts"]
        self.payload["snapshots"]["source"]["path"] = "../outside.py"
        self.save()
        context = load_caller_evidence(self.root)
        self.assertEqual(context["status"], "partial")
        self.assertEqual(read_question_from_dir(self.root, "pipe", limit=1)["facts"], before)

    def test_missing_optional_export_remains_absent(self):
        (self.root / CALLER_ARTIFACT).unlink()
        self.assertIsNone(load_caller_evidence(self.root))
        self.assertIsNone(load_source_snapshots(self.root))

    def test_question_overlays_export_without_rewriting_old_summary(self):
        summary = self.root / "analysis/summary.json"
        before = digest(summary)
        question = read_question_from_dir(self.root, "pipe", limit=1)
        self.assertEqual(question["context"]["caller_evidence"]["status"], "verified")
        self.assertIn("analysis/caller/generated.cc", question["binding"]["files"])
        self.assertIn("Caller Executor Evidence", render_question(question))
        self.assertEqual(digest(summary), before)

    def test_explicit_export_supplies_scored_range_without_backfilling_context(self):
        path = self.root / "analysis/profile_context.json"
        original = path.read_bytes() if path.exists() else None
        result = read_question_from_dir(self.root, "pipe", launch_scope="scored", aggregate_launches=True)
        sampling = result["launch_selection"]["sampling"]
        self.assertEqual(sampling["source"], {"artifact": CALLER_ARTIFACT, "field": "measurement"})
        self.assertEqual(result["launch_selection"]["expected_launch_indices"], [3, 4, 5, 6, 7])
        self.assertEqual(path.read_bytes() if path.exists() else None, original)

    def test_conflicting_sampling_blocks_scored_but_preserves_default_observations(self):
        path = self.root / "analysis/profile_context.json"
        context = json.loads(path.read_text()) if path.is_file() else {}
        context["sampling"] = {"program_launches": 9, "steady_state_skip": 3}
        path.write_text(json.dumps(context))
        self.assertTrue(read_question_from_dir(self.root, "pipe")["facts"])
        with self.assertRaisesRegex(ValueError, "disagree on program_launches"):
            read_question_from_dir(self.root, "pipe", launch_scope="scored")

    def test_diagnostic_only_snapshot_is_not_formal_timing(self):
        (self.root / "analysis/source_snapshots.json").write_text(json.dumps({
            "schema_version": 1, "snapshots": self.payload["snapshots"], "issues": []}))
        result = load_source_snapshots(self.root)
        self.assertEqual(result["status"], "verified")
        self.assertNotIn("measurement", result)

    def test_run_source_identity_conflict_is_explicit(self):
        path = self.root / "analysis/profile_context.json"
        context = json.loads(path.read_text()) if path.is_file() else {}
        context["source_sha256"] = "0" * 64
        path.write_text(json.dumps(context))
        result = load_caller_evidence(self.root)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(any("current profile context" in x["reason"] for x in result["issues"]))
