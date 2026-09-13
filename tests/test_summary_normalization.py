"""Persistent envelope integrity and independent optional-evidence loading."""
import copy
import json
import tempfile
from pathlib import Path

from tests.helpers_shared import ROOT, unittest
from pydantic import ValidationError
from ascend_msprof_skill.collect_benchmark_context import import_benchmark
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.run_assessment import assess_run
from ascend_msprof_skill.run_evidence import RunEvidence, RunEvidenceError
from ascend_msprof_skill.summary_types import (RawArtifactIndex, MeasurementQuality, SelectedMetricScope,
                                             StdoutSection, StdoutSections)
from ascend_msprof_skill.summary_types import IndexedArtifact, Summary
from ascend_msprof_skill.coverage_types import ProfileCoverage
from ascend_msprof_skill.identity_types import TargetIdentity


class SummaryNormalizationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        path = self.root / "reports/PROF_001/op_summary_001.csv"
        path.parent.mkdir(parents=True)
        path.write_text("Op Name,Task Duration(us)\nkernel,12\n")
        self.result = write_evidence_model(self.root)

    def test_nested_launch_directory_must_match_recorded_artifact(self):
        path = self.root / 'reports/op/OPPROF_001/kernel/000/OpBasicInfo.csv'
        path.parent.mkdir(parents=True)
        path.write_text('Op Name,Task Duration(us)\nkernel,12\n')
        result = write_evidence_model(self.root)
        payload = result.raw_artifact_index.model_dump(mode='json')
        row = next(item for item in payload['artifacts'] if item['artifact'].endswith('OpBasicInfo.csv'))
        row['launch_directory'] = '99'
        with self.assertRaises(ValidationError):
            RawArtifactIndex.model_validate(payload)

    def test_complete_envelope_schemas_are_generated_from_models(self):
        for name, model in (('summary', Summary), ('raw-artifact-index', RawArtifactIndex)):
            path = ROOT / f'skills/ascend-msprof-skill/data/{name}.schema.json'
            with self.subTest(name=name):
                self.assertEqual(json.loads(path.read_text()), model.model_json_schema())

    def test_stdout_preserves_statement_and_source_through_report_loading(self):
        logs = self.root / "logs"
        logs.mkdir()
        source = logs / "msprof_op.stdout"
        statement = "aivector compute usage lower than 20%."
        raw = f"2026-09-13 [INFO] Performance Summary Report:\n1) {statement}\n"
        source.write_text(raw)
        (logs / "command_msprof_op.txt").write_text("msprof op --aic-metrics=PipeUtilization\n")
        result = write_evidence_model(self.root)
        loaded = RunEvidence.load(self.root).summary()
        section = loaded.stdout_sections.performance_summary
        self.assertIsInstance(section, StdoutSection)
        self.assertEqual(section.messages[0].message, statement)
        self.assertEqual(section.source, "logs/msprof_op.stdout")
        self.assertEqual(loaded.stdout_sections, result.summary.stdout_sections)
        self.assertEqual(source.read_text(), raw)
        persisted = json.loads(result.summary_path.read_text())
        self.assertNotIn("source", persisted["stdout_sections"]["performance_summary"]["messages"][0])
        self.assertEqual(set(persisted["metric_scope"]), {"value", "artifact", "field_ref"})
        persisted["stdout_sections"]["performance_summary"]["source"] = "logs/missing.stdout"
        result.summary_path.write_text(json.dumps(persisted))
        with self.assertRaisesRegex(RunEvidenceError, "stdout section"):
            RunEvidence.load(self.root)

    def test_stdout_section_and_metric_scope_reject_contradictions(self):
        payload = {"source": "logs/msprof_op.stdout", "section": "Performance Summary Report",
                   "messages": [{"ordinal": 1, "message": "raw CANN statement"}]}
        for change in ({"messages": []}, {"messages": [{"message": "missing ordinal"}]},
                       {"messages": [{"ordinal": True, "message": "bool ordinal"}]},
                       {"section": "RoofLine Summary Report"}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                StdoutSection.model_validate({**payload, **change})
        with self.assertRaises(ValidationError):
            StdoutSections(occupancy_summary=StdoutSection.model_validate(payload))
        for value in ("pipeutilization", "", " PipeUtilization "):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                SelectedMetricScope(value=value, artifact="logs/command_msprof_op.txt")

    def test_dimension_signal_cannot_override_normalized_observation(self):
        payload = json.loads(self.result.summary_path.read_text())
        payload["analysis_dimensions"][0]["signals"][0]["value"] = 999.0
        self.result.summary_path.write_text(json.dumps(payload))
        for with_index in (True, False):
            if not with_index:
                self.result.raw_artifact_index_path.unlink()
            with self.subTest(with_index=with_index), self.assertRaisesRegex(
                    RunEvidenceError, "dimensions disagree"):
                RunEvidence.load(self.root)

    def test_readiness_cannot_claim_available_without_operator_evidence(self):
        payload = json.loads(self.result.summary_path.read_text())
        self.assertEqual(payload["evidence_readiness"]["level"], "partial")
        payload["evidence_readiness"]["level"] = "available"
        self.result.summary_path.write_text(json.dumps(payload))
        for with_index in (True, False):
            if not with_index:
                self.result.raw_artifact_index_path.unlink()
            with self.subTest(with_index=with_index), self.assertRaisesRegex(
                    RunEvidenceError, "readiness level disagrees"):
                RunEvidence.load(self.root)

    def test_collection_actions_use_artifact_facts_and_reject_forged_derivations(self):
        from ascend_msprof_skill.summary_types import Summary, load_summary
        logs = self.root / "logs"
        logs.mkdir()
        (logs / "command_msprof_op.txt").write_text("msprof op --aic-metrics=PipeUtilization\n")
        result = write_evidence_model(self.root)
        payload = json.loads(result.summary_path.read_text())
        self.assertEqual([action.id for action in result.summary.next_collection_actions],
                         ["recollect_pipeutilization", "collect_default_metric_followup"])
        # Neither deleting warning prose nor adding a misleading missing warning
        # changes collection decisions based on the admitted artifact inventory.
        payload["warnings"] = ["missing task_time: arbitrary changed wording"]
        self.assertEqual(load_summary(payload).next_collection_actions, result.summary.next_collection_actions)
        evidence = result.summary.next_collection_actions[0].evidence[1]
        self.assertEqual(evidence.field_ref, "headlines.op_basic_info.artifacts")
        for field in ("next_collection_actions", "recommended_followups"):
            changed = copy.deepcopy(payload)
            if field == "next_collection_actions":
                changed[field][0]["necessity"] = "optional"
            else:
                changed["evidence_readiness"][field] = []
            for with_index in (True, False):
                with self.subTest(field=field, with_index=with_index), self.assertRaisesRegex(
                        RunEvidenceError, "collection facts"):
                    RunEvidence.from_loaded(self.root, changed,
                                            raw_artifact_index=result.raw_artifact_index if with_index else None)
        del payload["headlines"]["op_basic_info"]
        with self.assertRaisesRegex(ValidationError, "every normalized headline group"):
            Summary.model_validate(payload)

    def test_missing_artifacts_are_distinct_from_present_invalid_artifacts(self):
        from ascend_msprof_skill._evidence_readiness import missing_artifact_groups
        path = self.root / "reports/OPPROF_001/Memory.csv"
        path.parent.mkdir(parents=True)
        path.write_text('"unterminated\n')
        result = write_evidence_model(self.root)
        self.assertNotIn("memory", missing_artifact_groups(result.summary))
        self.assertFalse(result.summary.headlines["memory"].available)
        self.assertEqual(result.summary.headlines["memory"].artifacts[0].status, "invalid")

    def test_simulator_dimension_must_occur_exactly_once(self):
        from ascend_msprof_skill.summary_types import load_summary
        payload = json.loads(self.result.summary_path.read_text())
        dimension = next(item for item in payload["analysis_dimensions"] if item["id"] == "source_pipeline_context")
        for copies in (0, 2):
            changed = copy.deepcopy(payload)
            changed["analysis_dimensions"] = [item for item in changed["analysis_dimensions"]
                                               if item["id"] != "source_pipeline_context"] + [dimension] * copies
            with self.subTest(copies=copies), self.assertRaisesRegex(ValidationError, "exactly one source"):
                load_summary(changed)

    def test_relation_metrics_follow_selected_coverage_and_preserve_each_launch(self):
        from tests.helper_tests_multi_launch import (
            declared_target, write_declared_target, write_app_launches, write_operator_launch,
        )
        for op_count, followup_count, selected in ((2, 1, "op"), (1, 2, "followup:collect_default_metric_followup")):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                write_declared_target(root, declared_target(("kernel_a", 2)))
                write_app_launches(root, ["kernel_a"] * 2)
                workflow_path = root / "analysis/profile_harness_run.json"
                workflow = json.loads(workflow_path.read_text())
                workflow["follow_up_actions"] = [{"id": "collect_default_metric_followup",
                                                   "segment_id": "collect_default_metric_followup",
                                                   "status": "succeeded", "target_scope": {"kind": "complete_program"}}]
                workflow_path.write_text(json.dumps(workflow))
                for segment, count in (("op", op_count), ("followup:collect_default_metric_followup", followup_count)):
                    for ordinal in range(count):
                        write_operator_launch(root, "kernel_a", ordinal, segment=segment)
                written = write_evidence_model(root)
                loaded = RunEvidence.load(root)
                self.assertEqual(loaded.profile_coverage().selected_segments_by_family["pipe_utilization"], selected)
                relation = next(item for item in loaded.evidence_relations() if item.kind == "timing_plus_pipe")
                metrics = [item for item in relation.evidence if "headlines.pipe_utilization." in item.field_ref]
                self.assertEqual(len(metrics), 2)
                self.assertEqual({item.segment for item in metrics}, {selected})
                self.assertEqual(len({item.artifact for item in metrics}), 2)
                payload = json.loads(written.summary_path.read_text())
                payload["evidence_relations"][0]["evidence"][1]["value"] = 999.0
                written.summary_path.write_text(json.dumps(payload))
                with self.assertRaisesRegex(RunEvidenceError, "relation evidence disagrees"):
                    RunEvidence.load(root)

    def test_index_roundtrip_keeps_typed_inventory_and_raw_sample_tokens(self):
        index = self.result.raw_artifact_index
        self.assertIsInstance(index, RawArtifactIndex)
        loaded = RunEvidence.load(self.root).raw_artifact_index()
        self.assertEqual(index, loaded)
        item = loaded.artifacts[0]
        self.assertEqual(item.sample_rows[0]["Task Duration(us)"], "12")
        self.assertEqual((item.artifact, item.row_count, item.status),
                         ("reports/PROF_001/op_summary_001.csv", 1, "parsed"))
        self.assertEqual(RawArtifactIndex.model_validate(json.loads(index.model_dump_json())), index)
        with self.assertRaises(ValidationError):
            item.row_count = 99

    def test_index_rejects_invalid_counts_status_identity_and_duplicates(self):
        payload = json.loads(self.result.raw_artifact_index_path.read_text())
        for field, value in (("row_count", True), ("row_count", -1), ("status", "empty"),
                             ("normalized_target_name", "fabricated")):
            changed = copy.deepcopy(payload)
            changed["artifacts"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                RawArtifactIndex.model_validate(changed)
        payload["artifacts"].append(copy.deepcopy(payload["artifacts"][0]))
        with self.assertRaisesRegex(ValidationError, "duplicate raw artifact"):
            RawArtifactIndex.model_validate(payload)

    def test_invalid_index_cannot_bypass_composition_or_erase_natural_measurement(self):
        source = ROOT / "skills/ascend-msprof-skill/assets/benchmark-single-case.json"
        import_benchmark(self.root, source)
        payload = json.loads(self.result.raw_artifact_index_path.read_text())
        payload["artifacts"][0]["row_count"] = True
        self.result.raw_artifact_index_path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(RunEvidenceError, "invalid analysis/raw_artifact_index.json"):
            RunEvidence.load(self.root)
        evidence = RunEvidence.load_assessment(self.root)
        self.assertFalse(evidence.summary_present())
        self.assertIsNone(evidence.raw_artifact_index())
        self.assertEqual(assess_run(evidence).model_dump(mode="json")["performance_assessment"]["eligibility"]["status"], "eligible")
        self.assertIn("invalid analysis/raw_artifact_index.json", "\n".join(evidence.warnings()))
        self.assertIs(json.loads(self.result.raw_artifact_index_path.read_text())["artifacts"][0]["row_count"], True)

    def test_index_decode_failures_follow_the_same_policy_at_all_disk_entry_points(self):
        import_benchmark(self.root, ROOT / "skills/ascend-msprof-skill/assets/benchmark-single-case.json")
        summary = json.loads(self.result.summary_path.read_text())
        for text in ('{', 'null', '[]', '{"artifacts": [], "artifacts": []}',
                     '{"artifacts": NaN}'):
            with self.subTest(payload=text):
                self.result.raw_artifact_index_path.write_text(text)
                for load in (lambda: RunEvidence.load(self.root),
                             lambda: RunEvidence.load_report(self.root, summary),
                             lambda: RunEvidence.from_report_inputs(self.root, summary)):
                    with self.assertRaisesRegex(RunEvidenceError, "invalid analysis/raw_artifact_index.json"):
                        load()
                evidence = RunEvidence.load_assessment(self.root)
                self.assertFalse(evidence.summary_present())
                self.assertIsNone(evidence.raw_artifact_index())
                self.assertIn("invalid analysis/raw_artifact_index.json", "\n".join(evidence.warnings()))
                self.assertEqual(assess_run(evidence).model_dump(mode="json")["performance_assessment"]["eligibility"]["status"], "eligible")
                self.assertEqual(self.result.raw_artifact_index_path.read_text(), text)

        self.result.raw_artifact_index_path.unlink()
        evidence = RunEvidence.load(self.root)
        self.assertTrue(evidence.summary_present())
        self.assertIsNone(evidence.raw_artifact_index())
        self.assertNotIn("invalid analysis/raw_artifact_index.json", "\n".join(evidence.warnings()))

    def test_raw_json_overflow_is_located_invalid_input_and_keeps_finite_subset(self):
        path = self.root / "reports/PROF_001/msprof_001.json"
        raw = '{"traceEvents":[{"name":"bad","dur":1e400},{"name":"valid","dur":12}]}'
        path.write_text(raw)
        result = write_evidence_model(self.root)
        item = next(item for item in result.raw_artifact_index.artifacts if item.artifact.endswith(path.name))
        self.assertEqual((item.status, item.row_count), ("invalid", 2))
        self.assertEqual(item.sample_rows, ({"name": "valid", "dur": 12},))
        self.assertIn("event[0]", "\n".join(item.warnings))
        self.assertTrue(RunEvidence.load(self.root).summary_present())
        self.assertEqual(path.read_text(), raw)

    def test_raw_csv_inventory_preserves_structure_errors_without_mapping_collisions(self):
        path = self.root / "reports/core0_code_exe.csv"
        for raw in ("code,cycles\na,3,4\nb,5\n", "code,cycles,cycles\na,3,4\n"):
            with self.subTest(raw=raw):
                path.write_text(raw)
                result = write_evidence_model(self.root)
                record = next(item for item in result.raw_artifact_index.artifacts if item.artifact.endswith(path.name))
                self.assertEqual(record.status, "invalid")
                self.assertTrue(record.warnings)
                self.assertEqual(path.read_text(), raw)

    def test_frequency_quality_is_validated_against_its_observations_and_summary(self):
        path = self.root / "reports/op/OPPROF_001/OpBasicInfo.csv"
        path.parent.mkdir(parents=True)
        path.write_text("Op Name,Current Freq,Rated Freq\nkernel,800,1800\n")
        result = write_evidence_model(self.root)
        quality = result.summary.measurement_quality
        self.assertIsInstance(quality, MeasurementQuality)
        self.assertEqual(RunEvidence.load(self.root).measurement_quality(), quality)
        payload = quality.model_dump(mode="json")
        for field, value in (("launch_count", 2), ("mixed_frequency", True),
                             ("below_rated_launch_count", 0), ("current_frequencies_mhz", [900.0])):
            changed = copy.deepcopy(payload)
            changed["frequency"]["groups"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                MeasurementQuality.model_validate(changed)
        summary = json.loads(result.summary_path.read_text())
        group = summary["measurement_quality"]["frequency"]["groups"][0]
        group["current_frequencies_mhz"] = [900.0]
        group["observations"][0]["current_frequency_mhz"] = 900.0
        result.summary_path.write_text(json.dumps(summary))
        with self.assertRaisesRegex(RunEvidenceError, "frequency quality disagrees"):
            RunEvidence.load(self.root)
        result.raw_artifact_index_path.unlink()
        with self.assertRaisesRegex(RunEvidenceError, "frequency quality disagrees"):
            RunEvidence.load(self.root)

    def test_coverage_roundtrip_rejects_contradictory_counts_durations_and_selection(self):
        from tests.helper_tests_multi_launch import declared_target, write_declared_target, write_operator_launch
        write_declared_target(self.root, declared_target(("kernel", 1), selector="kernel"))
        write_operator_launch(self.root, "kernel", 0)
        result = write_evidence_model(self.root)
        coverage = result.summary.profile_coverage
        self.assertIsInstance(coverage, ProfileCoverage)
        self.assertEqual(RunEvidence.load(self.root).profile_coverage(), coverage)
        self.assertTrue(coverage.segments["app"].count_complete)
        self.assertEqual(coverage.selected_segments_by_family["pipe_utilization"], "op")
        payload = coverage.model_dump(mode="json", exclude_unset=True)
        changes = (
            (("segments", "app", "observed_total"), 2),
            (("segments", "app", "count_complete"), False),
            (("segments", "app", "duration_total_us"), 0.0),
            (("segments", "app", "extra_counts"), {"fabricated": 1}),
            (("segments", "op", "metric_coverage", "pipe_utilization", "complete"), False),
            (("selected_segments_by_family", "pipe_utilization"), None),
        )
        for keys, value in changes:
            with self.subTest(field=keys):
                changed = copy.deepcopy(payload)
                cursor = changed
                for key in keys[:-1]:
                    cursor = cursor[key]
                cursor[keys[-1]] = value
                with self.assertRaises(ValidationError):
                    ProfileCoverage.model_validate(changed)

    def test_consistent_coverage_cannot_disagree_with_normalized_observations(self):
        payload = json.loads(self.result.summary_path.read_text())
        app = payload["profile_coverage"]["segments"]["app"]
        app["duration_total_us"] = 50.0
        app["duration_by_target_us"] = {"kernel": 50.0}
        ProfileCoverage.model_validate(payload["profile_coverage"])
        self.result.summary_path.write_text(json.dumps(payload))
        for missing_index in (False, True):
            with self.subTest(missing_index=missing_index):
                if missing_index:
                    self.result.raw_artifact_index_path.unlink()
                with self.assertRaisesRegex(RunEvidenceError, "coverage disagrees"):
                    RunEvidence.load(self.root)

    def test_indexed_operator_duration_cannot_replace_normalized_measurement(self):
        from tests.helper_tests_multi_launch import write_operator_launch
        write_operator_launch(self.root, "kernel", 0)
        result = write_evidence_model(self.root)
        index = json.loads(result.raw_artifact_index_path.read_text())
        item = next(item for item in index["artifacts"] if item["group"] == "op_basic_info")
        item["duration_us"] = 999.0
        result.raw_artifact_index_path.write_text(json.dumps(index))
        with self.assertRaisesRegex(RunEvidenceError, "indexed duration disagrees"):
            RunEvidence.load(self.root)

    def test_identity_status_and_sources_must_agree_with_normalized_observations(self):
        (self.root / "analysis/profile_context.json").write_text(json.dumps({"expected_kernel_names": ["kernel"]}))
        result = write_evidence_model(self.root)
        identity = result.summary.target_identity
        self.assertIsInstance(identity, TargetIdentity)
        self.assertEqual(RunEvidence.load(self.root).target_identity(), identity)
        self.assertEqual((identity.status, identity.confidence), ("match", "high"))
        changed = identity.model_dump(mode="json", exclude_unset=True)
        changed["confidence"] = "low"
        with self.assertRaisesRegex(ValidationError, "status/confidence disagrees"):
            TargetIdentity.model_validate(changed)
        payload = json.loads(result.summary_path.read_text())
        forged = payload["target_identity"]
        forged["expected"]["names"] = ["other"]
        forged["observed"][0]["name"] = "other"
        TargetIdentity.model_validate(forged)
        result.summary_path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(RunEvidenceError, "target identity disagrees"):
            RunEvidence.load(self.root)
