"""Context normalization and target authority across analysis boundaries."""
import json
import tempfile
from pathlib import Path
from unittest import mock

from tests.helpers_shared import unittest
from pydantic import ValidationError
from ascend_msprof_skill._profile_target import TargetSelection
from ascend_msprof_skill.collection_context import load_analysis_context
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.run_evidence import RunEvidence, RunEvidenceError


class CollectionContextTests(unittest.TestCase):
    def test_target_schema_is_generated_from_model(self):
        path = Path(__file__).resolve().parents[1] / "skills/ascend-msprof-skill/data/profile-target.schema.json"
        self.assertEqual(json.loads(path.read_text()), TargetSelection.model_json_schema())

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "analysis").mkdir()

    def context(self, payload, name="profile_context.json"):
        path = self.root / "analysis" / name
        path.write_text(json.dumps(payload))
        return path

    def test_unrelated_metadata_does_not_claim_workload(self):
        self.context({"note": "only a caller note"})
        result = write_evidence_model(self.root)
        self.assertFalse(result.summary.analysis_context.has_workload)
        self.assertFalse(any("Workload or shape" in reason for reason in result.summary.evidence_readiness.reasons))
        self.context({"benchmark": {"workload": {"shape": [128]}}})
        result = write_evidence_model(self.root)
        self.assertTrue(result.summary.analysis_context.has_workload)
        self.assertTrue(any("Workload or shape" in reason for reason in result.summary.evidence_readiness.reasons))

    def test_invalid_names_are_not_stringified_or_replaced_by_an_inferred_target(self):
        self.context({"expected_kernel_names": [True, 42, {"name": "kernel"}], "framework": "TileLang"})
        context = load_analysis_context(self.root)
        self.assertIsNone(context.expected_target)
        self.assertEqual(context.issues[0].source.field, "expected_kernel_names")
        self.context({"expected_kernel_names": ["valid", False]})
        self.assertIsNone(load_analysis_context(self.root).expected_target)
        self.context({"expected_kernel_names": ["kernel_a", "kernel_b"]})
        self.assertEqual(load_analysis_context(self.root).expected_target.names, ("kernel_a", "kernel_b"))

    def test_inference_cites_actual_framework_field(self):
        self.context({"benchmark": {"metadata": {"task_framework": "TileLang-Ascend"}}})
        expected = load_analysis_context(self.root).expected_target
        self.assertTrue(expected.inferred)
        self.assertEqual(expected.field_ref, "benchmark.metadata.task_framework")
        self.assertIsNone(expected.counts)

    def test_partial_workload_retains_valid_independent_fields_and_raw_sources(self):
        path = self.context({"verify_context": {"raw": {"workload": {
            "task_name": "case", "shape": [128], "dtype": False, "case_count": True}}}})
        raw = path.read_bytes()
        context = load_analysis_context(self.root)
        workload = context.workloads[0]
        self.assertEqual((workload.id, workload.id_field, workload.shape), ("case", "task_name", [128]))
        self.assertIsNone(workload.dtype)
        self.assertIsNone(workload.case_count)
        self.assertEqual({issue.source.field for issue in context.issues},
                         {"verify_context.raw.workload.dtype", "verify_context.raw.workload.case_count"})
        self.assertEqual(raw, path.read_bytes())

    def test_context_documents_are_read_once_by_analysis(self):
        paths = {self.context({"benchmark": {"workload": {"shape": [128]}}}),
                 self.context({"framework": "TileLang"}, "tilelang_context.json"),
                 self.context({}, "profile_harness_run.json")}
        reads = []
        original = Path.open

        def track(path, *args, **kwargs):
            if path in paths:
                reads.append(path)
            return original(path, *args, **kwargs)

        with mock.patch.object(Path, "open", track):
            write_evidence_model(self.root)
        self.assertEqual({path: reads.count(path) for path in paths}, dict.fromkeys(paths, 1))

    def test_target_model_has_one_count_authority(self):
        payload = {"kernel_selector": "kernel_*", "expected_launches": [{"name": "kernel_a", "count": 2}]}
        target = TargetSelection.model_validate(payload)
        self.assertEqual(target.launch_count, 2)
        self.assertEqual(target.expected_launches[0].normalized_name, "kernela")
        self.assertEqual(target.model_dump(mode="json"), payload)
        for count in (True, 1.5, "2", 0):
            with self.subTest(count=count), self.assertRaises(ValidationError):
                TargetSelection.model_validate({**payload, "expected_launches": [{"name": "kernel_a", "count": count}]})
        for extra in ({"launch_count": 99}, {"expected_launches": [{"name": "kernel_a", "count": 2, "normalized_name": "forged"}]}):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                TargetSelection.model_validate({**payload, **extra})

    def test_context_and_readiness_contradictions_fail_without_optional_index(self):
        self.context({"expected_kernel_name": "kernel", "benchmark": {"workload": {"shape": [128]}}})
        result = write_evidence_model(self.root)
        result.raw_artifact_index_path.unlink()
        original = result.summary.model_dump(mode="json")
        for field in ("reason", "target"):
            payload = json.loads(json.dumps(original))
            if field == "reason":
                payload["evidence_readiness"]["reasons"] = []
            else:
                payload["analysis_context"]["metadata_target"]["names"] = ["another"]
            result.summary_path.write_text(json.dumps(payload))
            with self.subTest(field=field), self.assertRaises(RunEvidenceError):
                RunEvidence.load(self.root)

    def test_malformed_workflow_does_not_fall_back_to_other_target_authority(self):
        target = {"kernel_selector": "kernel", "expected_launches": [{"name": "kernel", "count": 1}]}
        self.context({"profile_harness": {"target": target}})
        path = self.root / "analysis/profile_harness_run.json"
        path.write_text('{"target_selection":null,"target_selection":null}')
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            write_evidence_model(self.root)

    def test_nonfinite_shape_does_not_discard_independent_workload_identity(self):
        path = self.root / "analysis/profile_context.json"
        path.write_text('{"benchmark":{"workload":{"id":"case","shape":[1e309]}}}')
        context = load_analysis_context(self.root)
        self.assertEqual(context.workloads[0].id, "case")
        self.assertIsNone(context.workloads[0].shape)
        self.assertEqual(context.issues[0].source.field, "benchmark.workload.shape")
        json.dumps(context.model_dump(mode="json"), allow_nan=False)

    def test_workflow_target_retains_precedence_over_unused_invalid_fallback(self):
        target = {"kernel_selector": "kernel", "expected_launches": [{"name": "kernel", "count": 1}]}
        self.context({"target_selection": target}, "profile_harness_run.json")
        self.context({"profile_harness": {"target": False, "workload": {"id": "case"}}})
        context = load_analysis_context(self.root)
        self.assertEqual(context.expected_target.names, ("kernel",))
        self.assertTrue(context.has_workload)
        self.assertEqual(context.issues[0].source.field, "profile_harness.target")
