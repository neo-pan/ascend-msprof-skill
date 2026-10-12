"""Real caller sampling stays visible beside a bounded PMU observation page."""
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest

from ascend_msprof_skill.evidence_model import write_evidence_model


FIXTURE = Path(__file__).parent / "fixtures/real_kernel_agent_sampling_minimal"


class CallerSamplingContextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.run = Path(temporary.name) / "run"
        shutil.copytree(FIXTURE, self.run)
        self.origin = json.loads((self.run / "origin.json").read_text())
        self.context_path = self.run / "analysis/profile_context.json"
        self.caller = json.loads(self.context_path.read_text())

    def query(self, output_format="json"):
        result = subprocess.run([
            "ascend-msprof", "evidence", "--run-dir", str(self.run),
            "--question", "pipe", "--artifact", self.origin["selected_pipe"],
            "--limit", "1", "--format", output_format,
        ], text=True, capture_output=True, check=True)
        return json.loads(result.stdout) if output_format == "json" else result.stdout

    def test_first_launch_pmu_page_retains_caller_timing_subset_and_raw_coverage(self):
        for entry in self.origin["artifacts"]:
            self.assertEqual(hashlib.sha256((self.run / entry["artifact"]).read_bytes()).hexdigest(),
                             entry["retained_sha256"])
        write_evidence_model(self.run)
        result = self.query()
        sampling = result["context"]["analysis_context"].get("sampling")
        self.assertIsNotNone(sampling, "bounded question lost the caller's captured/scored launch distinction")
        self.assertEqual(sampling["program_launches"], 23)
        self.assertEqual(sampling["steady_state_skip"], 3)
        self.assertEqual(sampling["scope"], self.caller["sampling"]["scope"])
        self.assertEqual(sampling["source"]["artifact"], "analysis/profile_context.json")
        self.assertEqual(sampling["source"]["field"], "sampling")
        coverage = result["context"]["profile_coverage"]["segments"]["op"]
        self.assertEqual(coverage["observed_total"], 23)
        self.assertTrue(coverage["count_complete"])
        self.assertFalse(coverage["metric_coverage"]["pipe_utilization"]["complete"])
        self.assertEqual(len(result["facts"][0]["observations"]), 1)
        self.assertEqual(result["facts"][0]["artifact"], self.origin["selected_pipe"])
        for text in (self.query("markdown"), (self.run / "analysis/reading_guide.md").read_text()):
            self.assertIn("program_launches=23", text)
            self.assertIn("steady_state_skip=3", text)
            self.assertIn(self.caller["sampling"]["scope"], text)
            self.assertIn("analysis/profile_context.json", text)
            self.assertIn("Caller-declared", text)
            self.assertIn("not a validated benchmark", text)

    def test_query_reads_existing_caller_sampling_without_regenerating_old_summary(self):
        write_evidence_model(self.run)
        path = self.run / "analysis/summary.json"
        summary = json.loads(path.read_text())
        summary["analysis_context"].pop("sampling", None)
        path.write_text(json.dumps(summary))
        before = path.read_bytes()
        result = self.query()
        self.assertEqual(result["context"]["analysis_context"].get("sampling", {}).get("program_launches"), 23)
        self.assertEqual(path.read_bytes(), before)

    def test_absent_sampling_is_not_inferred_from_coverage_or_cached_context(self):
        write_evidence_model(self.run)
        self.caller.pop("sampling")
        self.context_path.write_text(json.dumps(self.caller))
        result = self.query()
        self.assertNotIn("sampling", result["context"]["analysis_context"])
        self.assertEqual(result["context"]["profile_coverage"]["segments"]["op"]["observed_total"], 23)
        regenerated = write_evidence_model(self.run)
        self.assertNotIn("sampling", regenerated.summary.analysis_context.model_dump(mode="json"))
        self.assertNotIn("Caller-declared sampling", (self.run / "analysis/reading_guide.md").read_text())

    def test_invalid_sampling_is_local_and_preserves_valid_declarations_and_pmu(self):
        write_evidence_model(self.run)
        before = self.query()
        for value, field in (({**self.caller["sampling"], "steady_state_skip": "3"}, "sampling.steady_state_skip"),
                             ([], "sampling")):
            with self.subTest(value=value):
                self.context_path.write_text(json.dumps({**self.caller, "sampling": value}))
                result = self.query()
                context = result["context"]["analysis_context"]
                self.assertEqual([issue["source"]["field"] for issue in context["issues"]], [field])
                self.assertEqual(result["facts"], before["facts"])
                self.assertEqual(result["context"]["profile_coverage"], before["context"]["profile_coverage"])
                if isinstance(value, dict):
                    self.assertEqual(context["sampling"]["program_launches"], 23)
                    self.assertNotIn("steady_state_skip", context["sampling"])
                    self.assertEqual(context["sampling"]["scope"], self.caller["sampling"]["scope"])
                else:
                    self.assertNotIn("sampling", context)
                self.assertIn(field, self.query("markdown"))
                summary = write_evidence_model(self.run).summary
                self.assertEqual([issue.source.field for issue in summary.analysis_context.issues], [field])
