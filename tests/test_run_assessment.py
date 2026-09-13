"""Behavioral tests for the public dual assessment interface and caller adapters."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ascend_msprof_skill.benchmark_evidence import ARTIFACT, load_benchmark
from ascend_msprof_skill.collect_benchmark_context import import_benchmark
from ascend_msprof_skill.collect_tilelang_context import collect_context, write_context
from ascend_msprof_skill.compare_runs import build_comparison, render_markdown
from ascend_msprof_skill.run_assessment import assess_run
from ascend_msprof_skill.run_evidence import RunEvidence, RunEvidenceError
from ascend_msprof_skill.summarize_candidate import build_candidate_summary

EXAMPLE = ROOT / "skills/ascend-msprof-skill/assets/benchmark-single-case.json"


from ascend_msprof_skill.assessment_types import CandidateSummary, ComparisonSummary

class RunAssessmentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.a, self.b = self.root / "baseline", self.root / "candidate"
        self.record = json.loads(EXAMPLE.read_text())["assessment"]
        self.counter = 0

    def write(self, run, record=None, **kwargs):
        self.counter += 1
        source = self.root / f"input-{self.counter}.json"
        source.write_text(json.dumps({"assessment": self.record if record is None else record}))
        return import_benchmark(run, source, **kwargs)

    def pair(self, record=None):
        self.write(self.a)
        candidate = copy.deepcopy(self.record) if record is None else record
        candidate["measurement_id"] = "candidate"
        candidate["measurement"]["value_ms"] = 1.0
        self.write(self.b, candidate)
        return build_comparison(self.a, self.b).model_dump(mode="json")

    def test_benchmark_only_comparison_and_single_run(self):
        result = self.pair()
        p = result["performance_assessment"]
        self.assertEqual(p["eligibility"]["status"], "eligible")
        self.assertEqual(p["comparison"]["status"], "observed_only")
        self.assertAlmostEqual(p["comparison"]["observation"]["speedup_pct"], 20)
        self.assertEqual(p["comparison"]["observation"]["delta_ms"], -0.25)
        self.assertEqual(result["mechanism_assessment"]["coverage"], "missing")
        for run in (self.a, self.b):
            self.assertFalse((run / "reports").exists())
            self.assertFalse((run / "analysis/summary.json").exists())
        single = build_candidate_summary(self.b).model_dump(mode="json")
        self.assertEqual(single["performance_assessment"]["comparison"], {"status": "not_applicable", "observation": None})
        self.assertNotIn("verdict", result)
        self.assertNotIn("benchmark", result)

    def test_comparison_and_summary_share_assessments(self):
        result = self.pair()
        summary = build_candidate_summary(self.b, self.a).model_dump(mode="json")
        for key in ("performance_assessment", "mechanism_assessment"):
            self.assertEqual(summary[key], result[key])
        markdown = render_markdown(ComparisonSummary.model_validate(result))
        self.assertIn("Observed in these caller-provided measurements", markdown)
        self.assertIn("assessment.measurement", markdown)

    def test_invalid_optional_provenance_preserves_eligible_natural_measurement(self):
        expected = self.pair()["performance_assessment"]
        path = self.b / "analysis/provenance.json"
        for raw in ('{"schema_version": 2, "hardware": {"summary": {"value": true}}}',
                    '{"schema_version": 2, "schema_version": 2}'):
            with self.subTest(raw=raw):
                path.write_text(raw)
                evidence = RunEvidence.load_assessment(self.b)
                self.assertIsNone(evidence.provenance())
                self.assertTrue(any("invalid analysis/provenance.json" in warning for warning in evidence.warnings()))
                result = build_comparison(self.a, self.b).model_dump(mode="json")["performance_assessment"]
                self.assertEqual(result, expected)
                self.assertEqual(result["eligibility"]["status"], "eligible")
                self.assertEqual(path.read_text(), raw)

    def test_invalid_caller_context_cannot_invalidate_independent_natural_performance(self):
        expected = self.pair()["performance_assessment"]
        path = self.b / "analysis/tilelang_context.json"
        for raw in ('{"benchmark": {"workload": {"case_count": true}, "candidate": {"compiled": "false"}}}',
                    '{"benchmark": {}, "benchmark": {}}'):
            with self.subTest(raw=raw):
                path.write_text(raw)
                evidence = RunEvidence.load_assessment(self.b)
                self.assertTrue(evidence.warnings())
                result = build_comparison(self.a, self.b).model_dump(mode="json")["performance_assessment"]
                self.assertEqual(result, expected)
                self.assertEqual(result["eligibility"]["status"], "eligible")
                self.assertEqual(path.read_text(), raw)

    def test_incomplete_protocol_keeps_original_value_without_delta(self):
        record = copy.deepcopy(self.record)
        del record["protocol"]["synchronization"]
        p = self.pair(record)["performance_assessment"]
        self.assertEqual(p["eligibility"]["status"], "incomplete")
        self.assertIsNone(p["comparison"]["observation"])
        self.assertEqual(p["measurements"]["candidate"]["record"]["measurement"]["value_ms"], 1)
        self.assertTrue(any("synchronization" in r for r in p["eligibility"]["reasons"]))

    def test_condition_mismatches_block_and_implementation_changes_do_not(self):
        for field, value in (("stride", [1,128]), ("offset", 1), ("dtype", "float16")):
            with self.subTest(field=field):
                record = copy.deepcopy(self.record)
                record["inputs"][0][field] = value
                run = self.root / field
                self.write(run, record)
                self.write(self.a)
                p = assess_run(RunEvidence.load_assessment(run), RunEvidence.load_assessment(self.a)).model_dump(mode="json")["performance_assessment"]
                self.assertEqual(p["eligibility"]["status"], "blocked")
                self.assertIsNone(p["comparison"]["observation"])
        record = copy.deepcopy(self.record)
        record["subject"]["implementation"]["id"] = "optimized-code"
        record["subject"]["build"] = {"tile":64}
        record["correctness"]["subject_id"] = "optimized-code"
        record["measurement"]["sample_count"] = 23
        self.assertEqual(self.pair(record)["performance_assessment"]["eligibility"]["status"], "eligible")

    def test_invalid_inputs_and_all_reasons_survive(self):
        for name, value in (("bool", True), ("zero", 0), ("negative", -1)):
            with self.subTest(name=name):
                record = copy.deepcopy(self.record)
                record["measurement"]["value_ms"] = value
                record["correctness"]["status"] = "fail"
                del record["environment"]["driver_version"]
                self.write(self.root/name, record)
                p = assess_run(RunEvidence.load_assessment(self.root/name)).model_dump(mode="json")["performance_assessment"]
                self.assertEqual(p["eligibility"]["status"], "blocked")
                self.assertGreaterEqual(len(p["eligibility"]["reasons"]),3)
                json.dumps(p, allow_nan=False)
        record = copy.deepcopy(self.record)
        record["inputs"].append(record["inputs"][0])
        record["measurement"]["sample_count"] = True
        ev = self.write(self.b, record)
        self.assertTrue({"duplicate_tensor_name", "invalid_value"} <= {i.reason_code for i in ev.issues})

    def test_samples_are_raw_context_only_and_named_tensors_align(self):
        record = copy.deepcopy(self.record)
        record["measurement"]["samples_ms"] = [None, False, -4]
        record["inputs"].reverse()
        p = self.pair(record)["performance_assessment"]
        self.assertEqual(p["eligibility"]["status"], "eligible")
        self.assertNotIn("samples_ms", p["measurements"]["candidate"]["record"]["measurement"])

    def test_duplicates_conflicts_and_source_tampering(self):
        first = self.write(self.a)
        duplicate = self.write(self.a, entrypoint="profile-harness")
        self.assertEqual(len(duplicate.records),1)
        self.assertEqual(set(duplicate.sources[0].entrypoints), {"collect-benchmark","profile-harness"})
        record = copy.deepcopy(self.record)
        record["measurement"]["value_ms"] = 0.9
        conflict = self.write(self.a, record)
        self.assertIsNone(conflict.record)
        self.assertIn("conflicting_measurements", [i.reason_code for i in conflict.issues])
        self.assertIsNone(json.loads((self.a/ARTIFACT).read_text())["measurement"])
        self.write(self.b)
        path = self.b/first.sources[0].artifact
        path.write_text('{}')
        evidence = self.write(self.b)
        self.assertIn("source_digest_mismatch", [i.reason_code for i in evidence.issues])
        self.assertEqual(assess_run(RunEvidence.load_assessment(self.b)).model_dump(mode="json")["performance_assessment"]["eligibility"]["status"], "blocked")

    def test_legacy_context_does_not_fill_new_measurement(self):
        (self.a/"analysis").mkdir(parents=True)
        (self.a/"analysis/profile_context.json").write_text(json.dumps({"benchmark":{"candidate":{"runtime":1},"correctness":{"raw":True}}}))
        result = build_candidate_summary(self.a).model_dump(mode="json")
        self.assertEqual(result["performance_assessment"]["eligibility"]["status"], "incomplete")
        self.assertIsNone(result["performance_assessment"]["measurements"]["candidate"]["record"])

    def test_profiler_changes_do_not_affect_performance(self):
        expected = self.pair()["performance_assessment"]
        for name, content in (("summary.json", {"target_identity": [], "evidence_readiness":{"level":"insufficient"},"next_collection_actions":[{"id":"unknown", "required_artifacts": None}]}),
                              ("simulator_hotspots.json", {"hotspots":[]}), ("raw_artifact_index.json", {"artifacts":[]})):
            path = self.b/"analysis"/name
            path.write_text(json.dumps(content))
            self.assertEqual(build_comparison(self.a,self.b).model_dump(mode="json")["performance_assessment"],expected)
            path.write_text('{bad')
            self.assertEqual(build_comparison(self.a,self.b).model_dump(mode="json")["performance_assessment"],expected)
            path.unlink()

    def test_non_object_summary_does_not_interrupt_independent_natural_assessment(self):
        expected = self.pair()["performance_assessment"]
        path = self.b / "analysis/summary.json"
        for value in ([], None, 12, "invalid", True):
            with self.subTest(value=value):
                path.write_text(json.dumps(value))
                self.assertEqual(build_comparison(self.a, self.b).model_dump(mode="json")["performance_assessment"], expected)
                evidence = RunEvidence.load_assessment(self.b)
                self.assertTrue(any("invalid analysis/summary.json" in warning for warning in evidence.warnings()))

    def test_deleted_timing_group_is_invalid_without_affecting_natural_assessment(self):
        from ascend_msprof_skill.evidence_model import write_evidence_model
        expected = self.pair()["performance_assessment"]
        reports = self.b / "reports/PROF_001"
        reports.mkdir(parents=True)
        for ordinal, value in ((1, 12), (2, 99)):
            (reports / f"op_summary_{ordinal:03}.csv").write_text(f"Op Name,Task Duration(us)\nkernel,{value}\n")
        result = write_evidence_model(self.b)
        self.assertTrue(RunEvidence.load(self.b).ambiguous_timing())
        summary = json.loads(result.summary_path.read_text())
        del summary["headlines"]["op_summary"]
        result.summary_path.write_text(json.dumps(summary))
        with self.assertRaises(RunEvidenceError):
            RunEvidence.load(self.b)
        optional = RunEvidence.load_assessment(self.b)
        self.assertFalse(optional.summary_present())
        self.assertTrue(any("invalid analysis/summary.json" in warning for warning in optional.warnings()))
        self.assertEqual(build_comparison(self.a, self.b).model_dump(mode="json")["performance_assessment"], expected)

    def test_assessment_computes_without_file_or_device_access(self):
        self.pair()
        a,b = RunEvidence.load_assessment(self.a),RunEvidence.load_assessment(self.b)
        with mock.patch.object(Path,"open",side_effect=AssertionError("unexpected I/O")), mock.patch("subprocess.run", side_effect=AssertionError("unexpected command")):
            self.assertEqual(assess_run(b,a).model_dump(mode="json")["performance_assessment"]["eligibility"]["status"],"eligible")

    def test_cli_import_compare_summary_and_removed_options(self):
        env={**os.environ,"PYTHONPATH":str(ROOT/"src")}
        def cli(*args):
            return subprocess.run([sys.executable,"-m","ascend_msprof_skill",*map(str,args)],env=env,capture_output=True,text=True)
        self.assertEqual(cli("collect-benchmark","--run-dir",self.a,"--benchmark-json",EXAMPLE).returncode,0)
        self.assertEqual(cli("collect-benchmark","--run-dir",self.b,"--benchmark-json",EXAMPLE).returncode,0)
        out=self.root/"out"
        result=cli("compare","--run-dir-a",self.a,"--run-dir-b",self.b,"--out-dir",out)
        self.assertEqual(result.returncode,0,result.stderr)
        result=cli("summarize-candidate","--run-dir",self.b,"--baseline-run-dir",self.a,"--out-dir",out)
        self.assertEqual(result.returncode,0,result.stderr)
        for option in ("--min-speedup-pct","--min-practical-speedup-pct","--comparison-evidence"):
            result=cli("compare","--run-dir-a",self.a,"--run-dir-b",self.b,option,"1")
            self.assertEqual(result.returncode,2)
        conflict=copy.deepcopy(self.record);conflict["measurement_id"]="different"
        path=self.root/"conflict.json";path.write_text(json.dumps({"assessment":conflict}))
        self.assertEqual(cli("collect-benchmark","--run-dir",self.a,"--benchmark-json",path).returncode,1)

    def test_tilelang_adapter_links_only_matching_payload(self):
        self.a.mkdir()
        payload=self.root/"payload.py";payload.write_text("# measured implementation\n")
        record=copy.deepcopy(self.record)
        subject=hashlib.sha256(payload.read_bytes()).hexdigest()
        record["subject"]["implementation"]["id"]=subject
        record["correctness"]["subject_id"]=subject
        path=self.root/"caller.json";path.write_text(json.dumps({"assessment":record}))
        context=collect_context(self.a,payload,path,None)
        write_context(self.a,context)
        self.assertEqual(context["schema_version"],2)
        self.assertEqual(context["benchmark_assessment"]["artifact"],ARTIFACT)
        self.assertEqual(build_candidate_summary(self.a).model_dump(mode="json")["mechanism_assessment"]["benchmark_association"][0]["status"],"linked")
        context["sources"]["payload"]["sha256"]="other"
        write_context(self.a,context)
        result=build_candidate_summary(self.a).model_dump(mode="json")
        self.assertEqual(result["mechanism_assessment"]["benchmark_association"][0]["status"],"blocked")
        self.assertEqual(result["performance_assessment"]["eligibility"]["status"],"eligible")

    def test_protocol_environment_and_input_identity_mismatches(self):
        changes = (("protocol.sample_unit", "batch"), ("protocol.synchronization", "stream only"),
                   ("measurement.statistic", "median"), ("input_identity.seed", 8),
                   ("environment.runtimes.cann", "different-runtime"), ("environment.device.id", "other-device"),
                   ("correctness.reference.version", "different-standard"), ("workload.parameters.alpha", 2))
        self.write(self.a)
        for field, value in changes:
            with self.subTest(field=field):
                record = copy.deepcopy(self.record)
                parent = record
                parts = field.split(".")
                for part in parts[:-1]:
                    parent = parent[part]
                parent[parts[-1]] = value
                run = self.root / field
                self.write(run, record)
                p = assess_run(RunEvidence.load_assessment(run), RunEvidence.load_assessment(self.a)).model_dump(mode="json")["performance_assessment"]
                expected = "blocked"
                self.assertEqual(p["eligibility"]["status"], expected)
                self.assertIsNone(p["comparison"]["observation"])

    def test_unsupported_contract_multicase_and_correctness_binding(self):
        for field, value in (("contract_version", "2.0"), ("workload.case_count", 2), ("correctness.subject_id", "wrong-code"), ("measurement.sample_count", 1.5)):
            with self.subTest(field=field):
                record = copy.deepcopy(self.record)
                parent = record
                parts = field.split(".")
                for part in parts[:-1]:
                    parent = parent[part]
                parent[parts[-1]] = value
                run = self.root / field
                self.write(run, record)
                self.assertEqual(build_candidate_summary(run).model_dump(mode="json")["performance_assessment"]["eligibility"]["status"], "blocked")

    def test_missing_source_remains_blocked_when_another_import_is_added(self):
        evidence = self.write(self.a)
        (self.a / evidence.sources[0].artifact).unlink()
        source = self.root / "new-wrapper.json"
        source.write_text(json.dumps({"assessment": self.record, "caller_metadata": "another entrypoint"}))
        evidence = import_benchmark(self.a, source)
        self.assertEqual(len(evidence.sources), 2)
        self.assertTrue(any(i.reason_code == "source_unreadable" for i in evidence.issues))
        self.assertEqual(build_candidate_summary(self.a).model_dump(mode="json")["performance_assessment"]["eligibility"]["status"], "blocked")

    def generated_context_run(self, name):
        run = self.root / name
        fixture = ROOT / "tests/fixtures/tilelang_design_feedback/candidate_comparability/baseline"
        shutil.copytree(fixture, run)
        path = run / "analysis/tilelang_context.json"
        context = json.loads(path.read_text())
        context["benchmark"]["correctness"]["raw"] = False
        context["benchmark"]["workload"]["case_count"] = 1
        path.write_text(json.dumps(context))
        record = copy.deepcopy(self.record)
        subject = context["sources"]["payload"]["sha256"]
        record["subject"]["implementation"]["id"] = subject
        record["correctness"]["subject_id"] = subject
        record["workload"] = {**context["benchmark"]["workload"], "parameters": {}}
        return run, record

    def test_generated_context_remains_inspectable_when_benchmark_validation_fails(self):
        cases = (
            ("valid", None, None, "available"),
            ("correctness", "subject_id", "other-implementation", "available"),
            ("correctness", "subject_id", None, "available"),
            ("correctness", "method", None, "available"),
            ("correctness", "status", "fail", "available"),
            ("correctness", "status", "error", "available"),
            ("correctness", "tolerances", {"atol": -1}, "available"),
            ("protocol", "synchronization", None, "available"),
            ("measurement", "value_ms", -1, "available"),
        )
        for index, (group, field, value, expected) in enumerate(cases):
            with self.subTest(group=group, field=field, value=value):
                run, record = self.generated_context_run(str(index))
                if field is not None:
                    record[group][field] = value
                evidence = self.write(run, record)
                result = build_candidate_summary(run).model_dump(mode="json")
                mechanism = result["mechanism_assessment"]
                question = next(q for q in mechanism["questions"] if q["id"] == "generated_context")
                self.assertEqual(question["status"], expected)
                self.assertTrue(all(f["kind"] == "metric_observation" for f in mechanism["findings"]))
                if group in {"measurement", "correctness"}:
                    self.assertNotEqual(result["performance_assessment"]["eligibility"]["status"], "eligible")
                if group == "measurement":
                    self.assertEqual(result["performance_assessment"]["eligibility"]["status"], "blocked")

    def test_failure_stage_has_shared_correctness_semantics(self):
        from ascend_msprof_skill.summarize_candidate import render_markdown as render_candidate
        for stage in ("compile", "correctness", "timing"):
            with self.subTest(stage=stage):
                run, record = self.generated_context_run(stage)
                record["failure"] = {"stage": stage, "message": "caller reported failure"}
                self.write(run, record)
                passed, issues = load_benchmark(run).correctness()
                self.assertEqual(passed, stage == "timing")
                result = build_candidate_summary(run).model_dump(mode="json")
                performance = result["performance_assessment"]
                self.assertEqual(performance["eligibility"]["status"], "blocked")
                question = next(q for q in result["mechanism_assessment"]["questions"] if q["id"] == "generated_context")
                self.assertEqual(question["status"], "available")
                if not passed:
                    failure = next(i for i in issues if i.id == "failure")
                    check = next(c for c in performance["eligibility"]["checks"] if c["id"] == "candidate.failure")
                    self.assertEqual(check["reason_code"], failure.reason_code)
                    self.assertEqual(check["candidate"], failure.value)
                    for source in failure.sources:
                        self.assertIn(source.artifact, json.dumps(performance))
                        self.assertIn(source.field_ref, json.dumps(performance))
                    self.assertIn("measurement_stage_failed", render_candidate(CandidateSummary.model_validate(result)))

    def test_invalid_benchmark_source_blocks_performance_not_independent_generated_context(self):
        for reason in ("source_unreadable", "source_digest_mismatch"):
            with self.subTest(reason=reason):
                run, record = self.generated_context_run(reason)
                first = self.write(run, record)
                source = self.root / "another-wrapper.json"
                source.write_text(json.dumps({"assessment": record, "caller_metadata": "second import"}))
                import_benchmark(run, source)
                snapshot = run / first.sources[0].artifact
                if reason == "source_unreadable":
                    snapshot.unlink()
                else:
                    snapshot.write_text("{}")
                result = build_candidate_summary(run).model_dump(mode="json")
                question = next(q for q in result["mechanism_assessment"]["questions"] if q["id"] == "generated_context")
                self.assertEqual(question["status"], "available")
                self.assertEqual(result["performance_assessment"]["eligibility"]["status"], "blocked")
                self.assertIn(reason, json.dumps(result["performance_assessment"]))
                self.assertIn(first.sources[0].artifact, json.dumps(result["performance_assessment"]))

    def test_unavailable_benchmark_preserves_independent_historical_correctness(self):
        run, record = self.generated_context_run("historical-correctness")
        path = run / "analysis/tilelang_context.json"
        context = json.loads(path.read_text())
        context["benchmark"]["correctness"]["raw"] = True
        path.write_text(json.dumps(context))
        imported = self.write(run, record)
        (run / imported.sources[0].artifact).unlink()
        result = build_candidate_summary(run).model_dump(mode="json")
        self.assertEqual(result["performance_assessment"]["eligibility"]["status"], "blocked")
        question = next(q for q in result["mechanism_assessment"]["questions"] if q["id"] == "generated_context")
        self.assertEqual(question["status"], "available")

    def test_complementary_incomplete_records_are_not_merged(self):
        a, b = copy.deepcopy(self.record), copy.deepcopy(self.record)
        del a["protocol"]
        del b["environment"]
        self.write(self.a, a)
        evidence = self.write(self.a, b)
        self.assertIsNone(evidence.record)
        self.assertEqual(len(evidence.records), 2)
        self.assertEqual(build_candidate_summary(self.a).model_dump(mode="json")["performance_assessment"]["eligibility"]["status"], "blocked")

    def test_harness_adapter_retains_profiler_success_and_separate_versions(self):
        from ascend_msprof_skill.profile_harness import ProfileHarnessArtifacts
        self.a.mkdir()
        application = self.root / "application"
        application.write_text("supplied executable fixture")
        record = copy.deepcopy(self.record)
        identity = hashlib.sha256(application.read_bytes()).hexdigest()
        record["subject"]["implementation"]["id"] = identity
        record["correctness"]["subject_id"] = identity
        source = self.root / "verify.json"
        data = {"assessment": record}
        source.write_text(json.dumps(data))
        artifacts = ProfileHarnessArtifacts(self.a)
        args = dict(manifest_path=None, manifest=None, application=application, verify_json_path=source)
        path = artifacts.write_profile_context(**args, verify_json=data)
        self.assertEqual(json.loads(path.read_text())["schema_version"], 5)
        artifacts.write_workflow_metadata(**args, preset_id="triage")
        self.assertEqual(json.loads(artifacts.workflow_metadata_path.read_text())["schema_version"], 4)
        self.assertEqual(build_candidate_summary(self.a).model_dump(mode="json")["mechanism_assessment"]["benchmark_association"][0]["status"], "linked")
        data["assessment"]["measurement_id"] = "conflicting-measurement"
        source.write_text(json.dumps(data))
        path = artifacts.write_profile_context(**args, verify_json=data)
        self.assertIn("conflicting_measurements", [i["reason_code"] for i in json.loads(path.read_text())["benchmark_issues"]])
        self.assertFalse((self.a / "reports").exists())

    def test_metric_decrease_can_coexist_with_runtime_regression(self):
        self.write(self.a)
        candidate = copy.deepcopy(self.record)
        candidate["measurement_id"] = "slower"
        candidate["measurement"]["value_ms"] = 1.5
        self.write(self.b, candidate)
        for run, value in ((self.a, 0.9), (self.b, 0.7)):
            from ascend_msprof_skill.evidence_model import build_evidence_model
            path = run / "reports/op/OPPROF_001/PipeUtilization.csv"
            path.parent.mkdir(parents=True)
            path.write_text(f"block_id,sub_block_id,aic_mte2_ratio\n0,cube0,{value}\n")
            logs = run / "logs"
            logs.mkdir()
            (logs / "command_msprof_op.txt").write_text("msprof op --aic-metrics=PipeUtilization")
            (path.parent / "OpBasicInfo.csv").write_text("Op Name\nkernel\n")
            (run / "analysis/tilelang_context.json").write_text(json.dumps({"expected_kernel_names": ["kernel"]}))
            summary, index, _simulator = build_evidence_model(run)
            summary = summary.model_dump(mode="json", exclude_unset=True)
            (run / "analysis/raw_artifact_index.json").write_text(json.dumps(index.model_dump(mode="json", exclude_unset=True)))
            from ascend_msprof_skill.generate_provenance import build_manifest
            (logs / "cann_version.cfg").write_text("toolkit_running_version=[8.3.RC2]\n")
            (logs / "npu_smi_info.stdout").write_text("| 0 910B2 | OK |\n")
            provenance = build_manifest(run).model_dump(mode="json", exclude_unset=True)
            (run / "analysis/summary.json").write_text(json.dumps(summary))
            (run / "analysis/provenance.json").write_text(json.dumps(provenance))
            (run / "analysis/profile_context.json").write_text(json.dumps({"benchmark": {"workload": self.record["workload"]}}))
        result = build_comparison(self.a, self.b).model_dump(mode="json")
        self.assertEqual(result["performance_assessment"]["comparison"]["observation"]["direction"], "slower")
        row = next(item for item in result["mechanism_assessment"]["headlines"] if item["group"] == "pipe_utilization")
        self.assertTrue(row["numeric"])
        self.assertAlmostEqual(row["delta"], -0.2)
        provenance["profile_output_segments"]["simulator"] = {"output": {"value": "reports/simulator", "source": {"artifact": "logs/command_msprof_simulator.txt", "field": "--output"}}}
        (self.b / "analysis/provenance.json").write_text(json.dumps(provenance))
        changed = build_comparison(self.a, self.b).model_dump(mode="json")
        self.assertEqual(changed["performance_assessment"], result["performance_assessment"])
        self.assertEqual(next(item for item in changed["mechanism_assessment"]["headlines"] if item["group"] == "pipe_utilization"), row)

    def test_named_field_sources_survive_tensor_reordering(self):
        record = copy.deepcopy(self.record)
        record["inputs"].reverse()
        result = self.pair(record)
        checks = result["performance_assessment"]["eligibility"]["checks"]
        tensor = next(c for c in checks if c["id"] == "inputs[name=a].offset")
        self.assertTrue(all(s["field_ref"] == "assessment.inputs[name=a].offset" for s in tensor["sources"]))

    def test_report_uses_same_single_run_assessment(self):
        from ascend_msprof_skill.generate_report import build_report_from_evidence
        self.write(self.a)
        evidence = RunEvidence.load_assessment(self.a)
        report = build_report_from_evidence(evidence)
        self.assertIn("Eligibility: `eligible`; comparison: `not_applicable`", report)
        self.assertIn("context/benchmark-inputs/", report)
        self.assertLess(report.index("## Performance Assessment"), report.index("## Mechanism Assessment"))

    def test_legacy_caller_speedup_is_not_published_as_an_assessment(self):
        from ascend_msprof_skill.generate_report import build_report_from_evidence
        self.a.mkdir()
        context = {"benchmark": {"candidate": {"runtime": 1, "ref_runtime": 2, "speedup": 2}}}
        evidence = RunEvidence.from_loaded(self.a, None, profile_context=context)
        report = build_report_from_evidence(evidence)
        self.assertNotIn("| Speedup |", report)
        self.assertNotIn("benchmark.candidate.speedup", report)
        self.assertIsNone(assess_run(evidence).model_dump(mode="json")["performance_assessment"]["comparison"]["observation"])

    def test_single_run_json_is_deterministic_across_hash_seeds(self):
        fixture = ROOT / "tests/fixtures/real_cann852_workload_pair/shape-128"
        program = "import json,sys; from pathlib import Path; from ascend_msprof_skill.summarize_candidate import build_candidate_summary; print(json.dumps(build_candidate_summary(Path(sys.argv[1])).model_dump(mode='json'),sort_keys=True))"
        outputs = []
        for seed in ("1", "2"):
            env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONHASHSEED": seed}
            outputs.append(subprocess.check_output([sys.executable, "-c", program, str(fixture)], env=env, text=True))
        self.assertEqual(outputs[0], outputs[1])


if __name__ == '__main__':
    unittest.main()
