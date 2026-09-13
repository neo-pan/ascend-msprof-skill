"""Strict provenance boundaries and independent evidence on malformed inputs."""
import json
import tempfile
from pathlib import Path
from unittest import mock

from tests.helpers_shared import unittest
from pydantic import ValidationError
from ascend_msprof_skill import generate_provenance as producer
from ascend_msprof_skill.generate_report import load_provenance
from ascend_msprof_skill.provenance_types import CannEnvironment, CannVersion, Provenance
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.run_evidence import RunEvidence, RunEvidenceError


class ProvenanceNormalizationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.logs = self.root / "logs"
        self.logs.mkdir()
        (self.root / "analysis").mkdir()
        (self.logs / "cann_version.cfg").write_text("toolkit_running_version=[8.5.2]\nruntime_running_version=[8.5.2]\n")
        (self.logs / "npu_smi_info.stdout").write_text("| 0 910B2 | OK |\n")

    def test_roundtrip_and_generated_schema(self):
        manifest = producer.build_manifest(self.root)
        producer.write_manifest(self.root, manifest)
        self.assertEqual(load_provenance(self.root), manifest)
        self.assertEqual(Provenance.model_validate_json(manifest.model_dump_json()), manifest)
        schema = Path(__file__).resolve().parents[1] / "skills/ascend-msprof-skill/data/provenance.schema.json"
        self.assertEqual(json.loads(schema.read_text()), Provenance.model_json_schema())
        self.assertNotIn("run_dir", manifest.model_dump())

    def test_invalid_sourced_hardware_is_rejected_at_explicit_boundary(self):
        payload = producer.build_manifest(self.root).model_dump(mode="json", exclude_unset=True)
        for value in (True, 42, ["910B2"], "2 x 910B2; health OK"):
            with self.subTest(value=value):
                payload["hardware"]["summary"]["value"] = value
                with self.assertRaises(RunEvidenceError):
                    RunEvidence.from_loaded(self.root, None, provenance=payload)

    def test_duplicate_keys_are_invalid_for_all_disk_consumers(self):
        result = write_evidence_model(self.root)
        path = self.root / "analysis/provenance.json"
        path.write_text('{"schema_version": 2, "schema_version": 2}')
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            load_provenance(self.root)
        for evidence in (RunEvidence.load(self.root), RunEvidence.load_report(self.root, result.summary),
                         RunEvidence.load_assessment(self.root)):
            self.assertIsNone(evidence.provenance())
            self.assertTrue(any("invalid analysis/provenance.json" in warning for warning in evidence.warnings()))
            self.assertIsNotNone(evidence.summary())
        self.assertEqual(path.read_bytes(), before)
        path.unlink()
        self.assertIsNone(load_provenance(self.root))
        self.assertFalse(any("invalid analysis/provenance.json" in warning for warning in RunEvidence.load(self.root).warnings()))

    def test_environment_bool_is_strict_and_healthy_facts_survive_invalid_receipt(self):
        receipt = {"msprof": "/toolkit/bin/msprof", "toolkit_root": "/toolkit", "environment_roots": {},
                   "mixed_roots": False, "snapshots": []}
        path = self.logs / "msprof_environment.json"
        for value in ("false", "true", 0, 1, None):
            with self.subTest(value=value):
                receipt["mixed_roots"] = value
                path.write_text(json.dumps(receipt))
                raw = path.read_bytes()
                with self.assertRaises(ValidationError):
                    producer.load_cann_environment(self.root)
                manifest = producer.build_manifest(self.root)
                self.assertIsNone(manifest.cann_version)
                self.assertEqual(manifest.cann_components["toolkit_running_version"].value, "8.5.2")
                self.assertEqual(manifest.hardware.summary.value, "1 x 910B2; health OK")
                self.assertTrue(any("Invalid logs/msprof_environment.json" in warning for warning in manifest.warnings))
                self.assertEqual(raw, path.read_bytes())
        receipt["mixed_roots"] = False
        path.write_text(json.dumps(receipt))
        self.assertEqual(producer.build_manifest(self.root).cann_version.status, "recorded")
        receipt["mixed_roots"] = True
        path.write_text(json.dumps(receipt))
        manifest = producer.build_manifest(self.root)
        self.assertEqual(manifest.cann_version.status, "conflict")
        self.assertIsNone(manifest.cann_version.value)

    def test_version_conflicts_cannot_select_or_cite_unrelated_source(self):
        (self.logs / "cann_version.cfg").write_text("toolkit_running_version=[8.5.2]\nruntime_running_version=[8.3]\n")
        version = producer.build_manifest(self.root).cann_version
        self.assertEqual(version.status, "conflict")
        for changes in ({"value": "8.5.2"}, {"status": "recorded"}, {"conflicts": []},
                        {"source": {"artifact": "logs/cann_version.cfg", "field": "toolkit_running_version"}}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                CannVersion.model_validate({**version.model_dump(mode="json"), **changes})

    def test_continuation_and_manifest_each_decode_environment_once(self):
        installed = self.root / "toolkit/version.cfg"
        installed.parent.mkdir()
        installed.write_bytes((self.logs / "cann_version.cfg").read_bytes())
        environment = CannEnvironment(msprof="/toolkit/bin/msprof", toolkit_root="/toolkit", environment_roots={},
            mixed_roots=False, snapshots=[{"path": str(installed), "artifact": "logs/cann_version.cfg"}])
        path = self.logs / "msprof_environment.json"
        path.write_text(environment.model_dump_json())
        with mock.patch.object(producer, "read_json", wraps=producer.read_json) as reader:
            producer.build_manifest(self.root)
            self.assertEqual([call.args[0] for call in reader.call_args_list].count(path), 1)
        with mock.patch.object(producer, "read_json", wraps=producer.read_json) as reader, mock.patch.object(
                producer, "current_cann_environment", return_value=environment):
            producer.require_matching_cann_environment(self.root)
            self.assertEqual([call.args[0] for call in reader.call_args_list].count(path), 1)

    def test_invalid_optional_plan_does_not_erase_version_or_hardware(self):
        (self.root / "analysis/profile_harness_run.json").write_text(json.dumps({
            "collection_plan": {"preset_id": "triage", "segments": [{"segment_id": True}]}}))
        result = producer.build_manifest(self.root)
        self.assertIsNone(result.collection_plan)
        self.assertIsNotNone(result.cann_version)
        self.assertIsNotNone(result.hardware)
        self.assertTrue(any("collection_plan is invalid" in warning for warning in result.warnings))
