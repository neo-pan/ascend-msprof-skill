"""Declared expectations and observed launches keep separate origins in collection reads."""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.question_evidence import main, read_question_from_dir, render_question
from ascend_msprof_skill.run_evidence import RunEvidence


class CoverageCountSemanticsTests(unittest.TestCase):
    def test_collection_explains_counts_without_changing_inputs_or_numeric_evidence(self):
        for expected, observed in ((2, 1), (3, 1), (None, 1), (2, 0)):
            with self.subTest(expected=expected, observed=observed), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                analysis = root / "analysis"
                analysis.mkdir()
                if expected is not None:
                    (analysis / "profile_context.json").write_text(json.dumps({"profile_harness": {
                        "target": {"kernel_selector": "kernel", "expected_launches": [
                            {"name": "kernel", "count": expected}]}}}))
                raw = root / "reports/op/OPPROF_001/kernel/0/OpBasicInfo.csv"
                raw.parent.mkdir(parents=True)
                raw.write_text("Op Name,Task Duration(us)\n" + ("kernel,10\n" if observed else ""))
                write_evidence_model(root)
                saved = json.loads((analysis / "summary.json").read_text())["profile_coverage"]["segments"]["op"]
                self.assertEqual((saved["expected_total"], saved["observed_total"]), (expected, observed))
                before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                with patch("subprocess.Popen", side_effect=AssertionError("offline query executed")):
                    result = RunEvidence.load(root).question_evidence("collection")
                    text = render_question(result)
                    out = io.StringIO()
                    with redirect_stdout(out):
                        self.assertEqual(main(["--run-dir", str(root), "--question", "collection",
                                               "--format", "json"]), 0)
                    self.assertEqual(json.loads(out.getvalue()), result)
                coverage = result["context"]["profile_coverage"]
                for field in ("expected_total", "observed_total", "expected_counts", "observed_counts",
                              "counting_authority", "count_complete"):
                    self.assertEqual(coverage["segments"]["op"][field], saved[field])
                definitions = coverage["count_semantics"]
                self.assertEqual(set(definitions), {"expected_total", "observed_total", "counting_authority"})
                self.assertIn("caller-declared", definitions["expected_total"])
                self.assertIn("null", definitions["expected_total"])
                self.assertIn("parsed", definitions["observed_total"])
                self.assertIn("observed_total only", definitions["counting_authority"])
                for definition in definitions.values():
                    self.assertIn(definition, text)
                self.assertEqual(before, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()})
                self.assertNotIn("count_semantics", read_question_from_dir(root)["context"]["profile_coverage"])

    def test_log_only_collection_does_not_imply_evaluated_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "logs").mkdir()
            (root / "logs/msprof.stdout").write_text("Generate hot spot function failed\n")
            result = read_question_from_dir(root, "collection")
            self.assertEqual(result["context"]["analysis_status"], "unavailable")
            self.assertNotIn("profile_coverage", result["context"])
