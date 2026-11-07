"""Explicit caller timing and local code remain independently auditable."""
import copy
import hashlib
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

    def test_sampling_projection_prefers_protocol_and_preserves_missing_values(self):
        cases = (
            ({"launches_per_process": 8, "steady_state_skip": 3}, {}, 8, 3),
            ({"launches_per_process": 8, "steady_state_skip": 3},
             {"device_program_launches": 99, "device_program_steady_state_skip": 7}, 8, 3),
            ({}, {"device_program_launches": 8, "device_program_steady_state_skip": 3}, 8, 3),
            ({"launches_per_process": None, "steady_state_skip": None},
             {"device_program_launches": 8, "device_program_steady_state_skip": 3}, None, None),
        )
        for protocol, fallback, launches, skip in cases:
            with self.subTest(protocol=protocol, fallback=fallback):
                metrics = self.report["metrics"]
                metrics.pop("device_program_launches", None)
                metrics.pop("device_program_steady_state_skip", None)
                metrics.update(fallback, measurement_protocol=protocol)
                self.payload["identity"]["measurement_protocol"] = protocol
                self.payload["measurement"].update(program_launches=launches, steady_state_skip=skip)
                source = self.root / self.payload["source_report"]["path"]
                source.write_text(json.dumps(self.report))
                self.payload["source_report"]["sha256"] = digest(source)
                self.save()
                context = load_caller_evidence(self.root)
                self.assertEqual(context["status"], "verified", context["issues"])
                self.assertEqual(context["measurement"]["program_launches"], launches)
                self.assertEqual(context["measurement"]["steady_state_skip"], skip)

    def test_default_read_rejects_damaged_or_disagreeing_carried_records(self):
        from ascend_msprof_skill.caller_record import record_reference
        report, payload = copy.deepcopy(self.report), copy.deepcopy(self.payload)
        current = record_reference(report)
        legacy = record_reference(report, schema_version=1)
        broken = {"schema_version": 2, "sha256": "0" * 64}
        cases = ((broken, None), (None, broken),
                 ({"schema_version": 99, "sha256": current["sha256"]}, None),
                 (current, legacy))
        for manifest_record, report_record in cases:
            with self.subTest(manifest_record=manifest_record, report_record=report_record):
                self.report, self.payload = copy.deepcopy(report), copy.deepcopy(payload)
                if manifest_record is not None:
                    self.payload["measurement_record"] = manifest_record
                if report_record is not None:
                    self.report["metrics"]["formal_measurement_record"] = report_record
                source = self.root / self.payload["source_report"]["path"]
                source.write_text(json.dumps(self.report))
                self.payload["source_report"]["sha256"] = digest(source)
                self.save()
                context = load_caller_evidence(self.root)
                self.assertEqual(context["status"], "unavailable")
                self.assertIsNone(context["measurement"])
                self.assertTrue(any(issue["source"]["field"] == "measurement_record"
                                    for issue in context["issues"]))

    def publish_version(self):
        report = copy.deepcopy(self.report)
        report["metrics"]["device_program_duration_ms"] = 0.012
        version = hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        prefix = f"analysis/caller_reports/{version}"
        destination = self.root / prefix
        shutil.copytree(self.root / "analysis/caller", destination)
        (destination / "source-report.json").write_text(json.dumps(report))
        payload = copy.deepcopy(self.payload)
        payload["measurement"]["value"] = 0.012
        refs = [payload["source_report"], payload["snapshots"]["source"], *payload["snapshots"]["generated"]]
        for ref in refs:
            ref["path"] = prefix + "/" + Path(ref["path"]).name
            ref["sha256"] = digest(self.root / ref["path"])
        (destination / "caller_evidence.json").write_text(json.dumps(payload))
        return version, destination

    def publish_record_locator(self, report, artifact=CALLER_ARTIFACT, *, schema_version=2):
        from ascend_msprof_skill.caller_record import record_reference
        from ascend_msprof_skill.evidence_binding import record_locator
        record_id = record_reference(report, schema_version=schema_version)["sha256"]
        path = self.root / record_locator(record_id)
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"schema_version": 1, "record_sha256": record_id,
            "artifact": artifact, "sha256": digest(self.root / artifact)}))
        return record_id, path

    def test_legacy_and_explicit_v1_references_keep_their_schema(self):
        from ascend_msprof_skill.caller_record import record_reference
        legacy = record_reference(self.report, schema_version=1)
        self.assertEqual(load_caller_evidence(self.root, measurement_record_id=legacy["sha256"])["status"], "verified")
        self.report["metrics"]["formal_measurement_record"] = legacy
        self.payload["measurement_record"] = legacy
        source = self.root / self.payload["source_report"]["path"]
        source.write_text(json.dumps(self.report))
        self.payload["source_report"]["sha256"] = digest(source)
        self.save()
        record_id, _ = self.publish_record_locator(self.report, schema_version=1)
        self.assertEqual(record_id, legacy["sha256"])
        selected = read_question_from_dir(self.root, "pipe", measurement_record_id=record_id)
        self.assertEqual(selected["context"]["caller_evidence"]["status"], "verified")
        self.assertEqual(verify_reference(self.root, selected["binding"])["status"], "verified")
        # A valid v2 digest is not a license to reinterpret an explicitly v1 attachment.
        current = record_reference(self.report)
        self.assertEqual(load_caller_evidence(self.root, measurement_record_id=current["sha256"])["status"], "unavailable")

    def test_record_selection_preserves_history_and_binds_locator(self):
        from ascend_msprof_skill.caller_record import record_reference
        original = snapshot(self.root, [])
        first_id = record_reference(self.report)["sha256"]
        # Legacy bytes are readable by exact record identity, without a locator.
        self.assertEqual(load_caller_evidence(self.root, measurement_record_id=first_id)["status"], "verified")
        version, destination = self.publish_version()
        report = json.loads((destination / "source-report.json").read_bytes())
        record_id, locator = self.publish_record_locator(report,
            str((destination / "caller_evidence.json").relative_to(self.root)))
        self.assertNotEqual(record_id, first_id)
        selected = load_caller_evidence(self.root, measurement_record_id=record_id)
        self.assertEqual(selected["measurement"]["value"], 0.012)
        question = read_question_from_dir(self.root, "pipe", measurement_record_id=record_id)
        self.assertEqual(question["context"]["caller_evidence"], selected)
        self.assertIn(str(locator.relative_to(self.root)), question["binding"]["files"])
        self.assertIn("--measurement-record " + record_id, question["questions"][0]["command"])
        self.assertEqual(verify_reference(self.root, question["binding"])["status"], "verified")
        (destination / "source-report.json").write_text("{}")
        self.assertEqual(verify_reference(self.root, question["binding"])["status"], "stale")
        self.assertIsNone(load_caller_evidence(self.root, measurement_record_id=record_id)["measurement"])
        self.assertEqual(verify_reference(self.root, original)["status"], "verified")

    def test_record_locator_rejects_damage_and_wrong_measurement(self):
        record_id, locator = self.publish_record_locator(self.report)
        payload = json.loads(locator.read_bytes())
        payload["sha256"] = "0" * 64
        locator.write_text(json.dumps(payload))
        from ascend_msprof_skill.evidence_binding import record_caller_artifact
        with self.assertRaisesRegex(ValueError, "manifest hash mismatch"):
            record_caller_artifact(self.root, record_id)
        self.assertEqual(load_caller_evidence(self.root, measurement_record_id=record_id)["status"], "unavailable")
        version, destination = self.publish_version()
        payload["artifact"] = str((destination / "caller_evidence.json").relative_to(self.root))
        payload["sha256"] = digest(destination / "caller_evidence.json")
        locator.write_text(json.dumps(payload))
        self.assertIsNone(load_caller_evidence(self.root, measurement_record_id=record_id)["measurement"])
        self.assertEqual(load_caller_evidence(self.root, report_version=version)["status"], "verified")
        with self.assertRaisesRegex(ValueError, "select either"):
            load_caller_evidence(self.root, report_version=version, measurement_record_id=record_id)

    def test_optional_locator_failures_preserve_raw_facts_and_stale_binding(self):
        record_id, locator = self.publish_record_locator(self.report)
        manifest = self.root / CALLER_ARTIFACT
        saved_manifest, saved_locator = manifest.read_bytes(), locator.read_bytes()
        healthy = read_question_from_dir(self.root, "pipe", measurement_record_id=record_id)
        self.assertGreater(sum(f.get("observation_count", 0) for f in healthy["facts"]), 0)
        raw_hashes = {p: digest(p) for p in (self.root / "reports").rglob("*") if p.is_file()}
        for mode in ("missing_manifest", "invalid_locator", "manifest_hash", "unsafe_target"):
            with self.subTest(mode=mode):
                manifest.write_bytes(saved_manifest)
                locator.write_bytes(saved_locator)
                if mode == "missing_manifest":
                    manifest.unlink()
                elif mode == "invalid_locator":
                    locator.write_text("{}")
                elif mode == "manifest_hash":
                    manifest.write_text("{}")
                else:
                    value = json.loads(saved_locator)
                    value["artifact"] = "../outside.json"
                    locator.write_text(json.dumps(value))
                selected = read_question_from_dir(self.root, "pipe", measurement_record_id=record_id)
                self.assertEqual(selected["facts"], healthy["facts"])
                caller = selected["context"]["caller_evidence"]
                self.assertEqual(caller["status"], "unavailable")
                self.assertIsNone(caller["measurement"])
                self.assertTrue(caller["issues"])
                self.assertEqual(verify_reference(self.root, healthy["binding"])["status"], "stale")
                self.assertEqual(verify_reference(self.root, selected["binding"])["status"], "verified")
                for options in ({"launch_scope": "scored"}, {"aggregate_launches": True}):
                    with self.assertRaisesRegex(ValueError, "caller"):
                        read_question_from_dir(self.root, "pipe", measurement_record_id=record_id, **options)
        self.assertEqual({p: digest(p) for p in raw_hashes}, raw_hashes)

    def test_record_cli_keeps_explicit_selection(self):
        import contextlib
        import io
        from ascend_msprof_skill.question_evidence import main
        record_id, _ = self.publish_record_locator(self.report)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(["--run-dir", str(self.root), "--question", "pipe",
                           "--measurement-record", record_id, "--format", "json"])
        self.assertEqual(status, 0, output.getvalue())
        result = json.loads(output.getvalue())
        self.assertEqual(result["binding"]["selection"]["measurement_record_id"], record_id)
        self.assertEqual(result["context"]["caller_evidence"]["status"], "verified")

    def test_version_selection_and_snapshot_keep_historical_context(self):
        original = snapshot(self.root, [])
        version, destination = self.publish_version()
        selected = load_caller_evidence(self.root, report_version=version)
        self.assertEqual(selected["status"], "verified")
        self.assertEqual(selected["measurement"]["value"], 0.012)
        self.assertEqual(load_caller_evidence(self.root)["measurement"]["value"], 0.01584)
        self.assertEqual(verify_reference(self.root, original)["status"], "verified")
        question = read_question_from_dir(self.root, "pipe", report_version=version)
        self.assertEqual(question["context"]["caller_evidence"], selected)
        self.assertIn(str((destination / "source-report.json").relative_to(self.root)), question["binding"]["files"])
        self.assertEqual(verify_reference(self.root, question["binding"])["status"], "verified")
        (destination / "source-report.json").write_text("{}")
        self.assertEqual(verify_reference(self.root, question["binding"])["status"], "stale")
        self.assertIsNone(load_caller_evidence(self.root, report_version=version)["measurement"])
        self.assertEqual(verify_reference(self.root, original)["status"], "verified")

    def test_missing_version_never_substitutes_other_report_measurement(self):
        version = hashlib.sha256(json.dumps(self.report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(load_caller_evidence(self.root, report_version=version)["status"], "verified")
        missing = load_caller_evidence(self.root, report_version="f" * 64)
        self.assertEqual(missing["status"], "unavailable")
        self.assertIsNone(missing["measurement"])
        with self.assertRaises(ValueError):
            load_caller_evidence(self.root, report_version="../caller")

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
