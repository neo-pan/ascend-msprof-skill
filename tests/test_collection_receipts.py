"""Collection admission stays sourced, strict and shared by every consumer."""
import json
import tempfile
from pathlib import Path
from unittest import mock

from tests.helpers_shared import unittest
from pydantic import ValidationError
from ascend_msprof_skill.collection_receipts import CollectionReceipts, load_collection_receipts
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.run_evidence import RunEvidence, RunEvidenceError
from ascend_msprof_skill.summary_types import Summary


class CollectionReceiptTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "logs").mkdir()
        folder = self.root / "reports/PROF_001"
        folder.mkdir(parents=True)
        for i in range(3):
            (folder / f"op_summary_{i}.csv").write_text("Op Name,Task Duration(us)\nkernel,12\n")

    def receipt(self, text, name="msprof_default"):
        path = self.root / f"logs/{name}.result.json"
        path.write_text(text)
        return path

    def test_missing_invalid_and_execution_results_are_distinct(self):
        self.assertEqual(load_collection_receipts(self.root).records, ())
        self.assertTrue(load_collection_receipts(self.root).allows("app"))
        for status in ("succeeded", "failed", "core_dump", "timeout"):
            with self.subTest(status=status):
                self.receipt(json.dumps({"status": status, "unused_metadata": {"key": "raw"}}))
                receipts = load_collection_receipts(self.root)
                self.assertEqual(receipts.allows("app"), status == "succeeded")
                self.assertEqual(receipts.records[0].status, status)
                self.assertIsNone(receipts.records[0].issue)
                self.assertEqual(CollectionReceipts.model_validate(receipts.model_dump(mode="json")), receipts)
        for text in ('{"status":"failed","status":"succeeded"}', '{', '[]', '{}',
                     '{"status":true}', '{"status":[]}', '{"status":"unknown"}'):
            with self.subTest(text=text):
                path = self.receipt(text)
                receipts = load_collection_receipts(self.root)
                self.assertFalse(receipts.allows("app"))
                self.assertIsNone(receipts.records[0].status)
                self.assertEqual(receipts.records[0].issue.source.artifact, "logs/msprof_default.result.json")
                self.assertEqual(path.read_text(), text)

    def test_invalid_receipt_excludes_only_its_segment_and_preserves_inventory(self):
        self.receipt('{"status":"failed","status":"succeeded"}')
        simulator = self.root / "reports/OPPROF_001/simulator"
        simulator.mkdir(parents=True)
        (simulator / "core0_code_exe.csv").write_text("code,cycles\nkernel.cpp:1,2\n")
        result = write_evidence_model(self.root)
        self.assertEqual(result.summary.headlines["op_summary"].artifacts, ())
        self.assertEqual(len([i for i in result.raw_artifact_index.artifacts if i.group == "op_summary"]), 3)
        self.assertTrue(result.simulator_model.inputs)
        self.assertIn("duplicate JSON key", " ".join(result.summary.warnings))
        self.assertTrue(RunEvidence.load(self.root).summary_present())

    def test_one_receipt_read_per_analysis_and_load(self):
        path = self.receipt('{"status":"succeeded"}')
        original = Path.open
        reads = []

        def track(candidate, *args, **kwargs):
            if candidate == path:
                reads.append(candidate)
            return original(candidate, *args, **kwargs)

        with mock.patch.object(Path, "open", track):
            write_evidence_model(self.root)
        self.assertEqual(len(reads), 1)
        reads.clear()
        with mock.patch.object(Path, "open", track):
            RunEvidence.load(self.root)
        self.assertEqual(len(reads), 1)

    def test_receipt_cannot_authorize_another_segment_or_contradict_retained_facts(self):
        self.receipt('{"status":"succeeded"}')
        result = write_evidence_model(self.root)
        payload = result.summary.model_dump(mode="json")
        payload["collection_receipts"]["records"][0]["status"] = "failed"
        with self.assertRaisesRegex(ValidationError, "excluded by collection receipts"):
            Summary.model_validate(payload)
        payload = result.summary.collection_receipts.model_dump(mode="json")
        payload["records"][0]["segment"] = "op"
        with self.assertRaisesRegex(ValidationError, "artifact disagrees"):
            CollectionReceipts.model_validate(payload)

    def test_changed_receipt_rejects_stale_summary_even_without_index(self):
        from ascend_msprof_skill.collect_benchmark_context import import_benchmark
        from ascend_msprof_skill.run_assessment import assess_run
        self.receipt('{"status":"succeeded"}')
        result = write_evidence_model(self.root)
        example = Path(__file__).resolve().parents[1] / "skills/ascend-msprof-skill/assets/benchmark-single-case.json"
        import_benchmark(self.root, example)
        self.receipt('{"status":"failed"}')
        for has_index in (True, False):
            with self.subTest(has_index=has_index):
                if not has_index:
                    result.raw_artifact_index_path.unlink()
                with self.assertRaisesRegex(RunEvidenceError, "excluded by collection receipts"):
                    RunEvidence.load(self.root)
                evidence = RunEvidence.load_assessment(self.root)
                self.assertFalse(evidence.summary_present())
                self.assertEqual(assess_run(evidence).model_dump(mode="json")["performance_assessment"]["eligibility"]["status"], "eligible")

    def test_simulator_and_stdout_use_the_same_admission(self):
        simulator = self.root / "reports/OPPROF_001/simulator"
        simulator.mkdir(parents=True)
        (simulator / "core0_code_exe.csv").write_text("code,cycles\nkernel.cpp:1,2\n")
        (self.root / "logs/msprof_op.stdout").write_text("[INFO] Performance Summary Report:\n1) raw statement\n")
        self.receipt('{"status":"failed"}', "msprof_op")
        self.receipt('{"status":"timeout"}', "msprof_simulator")
        result = write_evidence_model(self.root)
        self.assertIsNone(result.summary.stdout_sections.performance_summary)
        self.assertEqual(result.simulator_model.inputs, ())
        self.assertTrue(result.summary.headlines["op_summary"].artifacts)
        self.assertTrue(RunEvidence.load(self.root).summary_present())
