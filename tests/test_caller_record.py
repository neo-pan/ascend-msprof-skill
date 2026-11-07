"""Formal identity survives delivery while retaining measurement provenance."""
import copy
import unittest

from ascend_msprof_skill.caller_record import record_reference, validate_record_reference


class CallerRecordTests(unittest.TestCase):
    def setUp(self):
        self.report = {"status": "success", "latency_ms": 0.01584, "correctness_ok": True,
            "metrics": {"profile_source_sha256": "a" * 64,
                "measurement_protocol": {"launches_per_process": 8},
                "profile_collection": {"collection_id": "first"},
                "device_program_profile_receipts": [{"attempt_index": 1,
                    "artifact_dir": "/sample/one", "duration_ms": 0.01584}]}}

    def test_delivery_and_serialization_do_not_change_record(self):
        reference = record_reference(self.report)
        self.report["metrics"].update(formal_measurement_record=reference,
            executor_attempt_ref={"attempt": 1}, profile_evidence={"status": "accepted"},
            future_host_metadata={"arbitrary": True})
        self.report["stdout"] = "delivery log"
        self.report["metrics"]["device_program_profile_receipts"][0]["profile_analysis"] = {"summary": "/derived"}
        self.assertEqual(validate_record_reference(self.report, reference), reference)

    def test_changed_formal_facts_invalidate_carried_reference(self):
        reference = record_reference(self.report)
        changes = [([], "status", "failed"), ([], "correctness_ok", False), ([], "latency_ms", 0.02),
            (["metrics"], "profile_source_sha256", "b" * 64),
            (["metrics"], "correctness_receipt", {"case_count": 2}),
            (["metrics"], "compilation_evidence", {"artifact_sha256": {"code": "c" * 64}}),
            (["metrics", "measurement_protocol"], "launches_per_process", 9),
            (["metrics", "profile_collection"], "collection_id", "second"),
            (["metrics", "device_program_profile_receipts", 0], "attempt_index", 2),
            (["metrics", "device_program_profile_receipts", 0], "artifact_dir", "/sample/two"),
            (["metrics", "device_program_profile_receipts", 0], "duration_ms", 0.02),
            (["metrics", "device_program_profile_receipts", 0], "launch_durations_us", [20, 15])]
        for path, key, value in changes:
            with self.subTest(path=path, key=key):
                changed = copy.deepcopy(self.report)
                target = changed
                for part in path:
                    target = target[part]
                target[key] = value
                with self.assertRaisesRegex(ValueError, "does not match"):
                    validate_record_reference(changed, reference)

    def test_v2_excludes_episode_state_without_redefining_v1(self):
        self.report["metrics"]["profile_collection"].update(
            episode_id="first-open", previous_attempt_count=0, remaining_budget_seconds=90)
        legacy = {"schema_version": 1, "sha256": "f94da705b0db2e7dd76336f38fc3968cca5832fc2f31fdd547ec4432c782ff55"}
        self.assertEqual(record_reference(self.report, schema_version=1), legacy)
        self.assertEqual(validate_record_reference(self.report, legacy), legacy)
        current = record_reference(self.report)
        self.assertEqual(current["schema_version"], 2)
        self.report["metrics"]["profile_collection"].update(
            episode_id="reopened", previous_attempt_count=1, remaining_budget_seconds=80,
            future_episode_metadata={"diagnostic": True})
        self.assertEqual(record_reference(self.report), current)
        with self.assertRaisesRegex(ValueError, "does not match"):
            validate_record_reference(self.report, legacy)
        self.report["metrics"]["profile_collection"]["identity"] = {"source": "different"}
        self.assertNotEqual(record_reference(self.report), current)

    def test_unknown_schema_is_not_reinterpreted(self):
        for version in (0, 3, True, "2"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                validate_record_reference(self.report, {"schema_version": version, "sha256": "a" * 64})
