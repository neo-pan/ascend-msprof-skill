"""Caller metadata is normalized once before report and comparison consume it."""
import json
import tempfile
from pathlib import Path
from unittest import mock

from tests.helpers_shared import unittest
from pydantic import ValidationError
from ascend_msprof_skill import caller_context
from ascend_msprof_skill.caller_context import CallerContext, normalize_caller_context
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.run_evidence import RunEvidence, RunEvidenceError

PROFILE = "analysis/profile_context.json"
TILE = "analysis/tilelang_context.json"


class CallerContextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "analysis").mkdir()

    def test_bool_case_counts_cannot_authorize_profiler_comparison(self):
        from tests.test_headline_comparison import HeadlineComparisonTests, pipe_row
        case = HeadlineComparisonTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        for run in (case.baseline, case.candidate):
            case.write_workload(run, {**case.workload, "case_count": True})
        evidence = RunEvidence.load_assessment(case.baseline)
        self.assertNotIn("case_count", evidence.candidate_context().workload)
        self.assertEqual(evidence.candidate_context().workload["shape"], [128, 256])
        self.assertTrue(any("benchmark.workload.case_count" in warning for warning in evidence.warnings()))
        row = pipe_row(case.comparison())
        self.assertFalse(row["numeric"])
        self.assertIn("workload.case_count missing", row["comparison_reasons"])

    def test_invalid_payload_and_jit_flags_agree_across_consumers(self):
        payload = {"sources": {"payload": {"artifact": True, "sha256": True, "size_bytes": False}},
                   "jit_debug": {"found": "false", "artifacts": []},
                   "benchmark": {"workload": {"id": "healthy", "shape": [128], "case_count": 1}}}
        evidence = RunEvidence.from_loaded(self.root, None, tilelang_context=payload)
        self.assertFalse(evidence.candidate_context().payload.present)
        self.assertFalse(evidence.feedback_facts().jit_debug_found())
        rows = {row.label: row.value for row in evidence.report_tilelang_context_rows()}
        self.assertEqual(rows["JIT debug artifacts"], "availability not recorded")
        self.assertEqual(rows["Workload id"], "healthy")
        fields = {issue.source.field for issue in evidence.tilelang_context().issues}
        self.assertEqual(fields, {"sources.payload.artifact", "sources.payload.sha256", "sources.payload.size_bytes", "jit_debug.found"})

    def test_bad_preferred_components_preserve_healthy_alternate_sources(self):
        tile = {"benchmark": {"workload": {"id": "case", "case_count": True},
                "candidate": {"compiled": "false", "runtime_stats": {"value_ms": False}},
                "correctness": {"raw": {"passed": "false"}}}}
        profile = {"benchmark": {"workload": {"id": "case", "case_count": 3},
                   "candidate": {"compiled": True, "runtime_stats": {"mean_ms": 1.25}},
                   "correctness": {"raw": {"passed": True}}}}
        evidence = RunEvidence.from_loaded(self.root, None, tilelang_context=tile, profile_context=profile)
        facts = evidence.candidate_context()
        self.assertEqual(facts.workload["case_count"], 3)
        self.assertIs(facts.correctness.compiled, True)
        self.assertIs(facts.correctness.passed, True)
        self.assertEqual(facts.runtime.mean_ms, 1.25)
        for key in ("workload.case_count", "correctness.compiled", "correctness.passed", "runtime.value_ms"):
            self.assertEqual(facts.context_sources[key].artifact, PROFILE)
        self.assertGreaterEqual(len(evidence.warnings()), 4)

    def test_partial_context_retains_exact_verification_and_sample_sources(self):
        payload = {"verify_context": {"raw": {"workload": {"task_name": "task", "dtype": False, "shape": [4]},
            "correctness": {"correctness_ok": True, "receipt": {"case_count": 2}},
            "official_timing": {"latency_ms": 2, "aggregation": "median", "samples_ms": [1, False, "2.0", "bad"]}}}}
        evidence = RunEvidence.from_loaded(self.root, None, profile_context=payload)
        facts = evidence.candidate_context()
        self.assertEqual(facts.workload, {"id": "task", "shape": [4], "case_count": 2})
        self.assertEqual(facts.context_sources["workload.id"].field_ref, "verify_context.raw.workload.task_name")
        self.assertEqual(facts.context_sources["workload.case_count"].field_ref, "verify_context.raw.correctness.receipt.case_count")
        self.assertEqual(facts.runtime.samples_ms, (1.0, 2.0))
        self.assertEqual(facts.runtime.statistic, "median")
        fields = {issue.source.field for issue in evidence.profile_context().issues}
        self.assertIn("verify_context.raw.official_timing.samples_ms[1]", fields)
        self.assertIn("verify_context.raw.official_timing.samples_ms[3]", fields)

    def test_model_roundtrip_and_scope_check(self):
        payload = {"benchmark": {"workload": {"id": "case", "case_count": 2},
                                  "candidate": {"compiled": True, "runtime_stats": {"mean_ms": 1.25}}},
                   "jit_debug": {"found": True, "provided": "jit", "artifacts": [{"artifact": "kernel.c", "size_bytes": 0}]}}
        model = normalize_caller_context(payload, TILE)
        self.assertEqual(CallerContext.model_validate_json(model.model_dump_json()), model)
        self.assertIs(RunEvidence.from_loaded(self.root, None, tilelang_context=model).tilelang_context(), model)
        with self.assertRaises(RunEvidenceError):
            RunEvidence.from_loaded(self.root, None, profile_context=model)
        changed = model.model_dump(mode="json")
        changed["workloads"][0]["source"]["artifact"] = PROFILE
        with self.assertRaises(ValidationError):
            CallerContext.model_validate(changed)

    def test_profile_context_projects_declared_implementation_sources(self):
        payload = {
            "sources": {
                "application": {"artifact": "harness/run.sh", "sha256": "aa", "size_bytes": 1},
                "implementation": [
                    {"artifact": "harness/a.cpp", "sha256": "bb", "size_bytes": 2},
                    {"artifact": "harness/b.cpp", "sha256": "cc", "size_bytes": 3},
                ],
            }
        }
        model = normalize_caller_context(payload, PROFILE)
        self.assertEqual(
            [item.artifact for item in model.sources.implementation],
            ["harness/a.cpp", "harness/b.cpp"],
        )
        rows = {
            row.label: row.value
            for row in RunEvidence.from_loaded(self.root, None, profile_context=payload).report_profile_context_rows()
        }
        self.assertEqual(rows["Implementation[0]"], "harness/a.cpp")
        self.assertEqual(rows["Implementation[1] sha256"], "cc")

    def test_optional_disk_loading_is_strict_and_decodes_each_context_once(self):
        result = write_evidence_model(self.root)
        paths = [self.root / name for name in (TILE, PROFILE)]
        for path in paths:
            path.write_text(json.dumps({"benchmark": {"workload": {"id": "case", "case_count": 1}}}))
        before = {path: path.read_bytes() for path in paths}
        with mock.patch.object(caller_context, "read_json", wraps=caller_context.read_json) as read:
            loaded = RunEvidence.load_assessment(self.root)
            loaded.candidate_context()
            loaded.candidate_context()
            loaded.report_tilelang_context_rows()
            self.assertEqual([call.args[0] for call in read.call_args_list], paths)
        self.assertEqual(before, {path: path.read_bytes() for path in paths})
        paths[0].write_text('{"benchmark": {}, "benchmark": {}}')
        for evidence in (RunEvidence.load(self.root), RunEvidence.load_report(self.root, result.summary),
                         RunEvidence.load_assessment(self.root)):
            self.assertIsNone(evidence.tilelang_context())
            self.assertIsNotNone(evidence.profile_context())
            self.assertTrue(any(f"invalid {TILE}" in warning for warning in evidence.warnings()))

    def test_jit_config_and_metadata_are_not_forced_into_measurement_models(self):
        config = {"tiles": [16, 32], "experimental": {"enabled": True}, "output": None}
        model = normalize_caller_context({"benchmark": {"jit_config": config},
                                          "profile_harness": {"workload": {"custom_dimension": [1, 2]}}}, TILE)
        self.assertEqual(model.benchmark.jit_config, config)
        self.assertEqual(model.harness_workload, {"custom_dimension": [1, 2]})
        self.assertIsNone(model.benchmark.runtime)
        self.assertFalse(model.workloads)
        self.assertFalse(model.issues)

    def test_collector_rejects_duplicate_json_keys_without_rewriting_input(self):
        from ascend_msprof_skill.collect_tilelang_context import collect_context
        payload = self.root / "kernel.py"
        payload.write_text("# caller source\n")
        source = self.root / "benchmark.json"
        source.write_text('{"compiled": true, "compiled": false}')
        before = source.read_bytes()
        with self.assertRaises(ValueError):
            collect_context(self.root, payload, source, None)
        self.assertEqual(source.read_bytes(), before)
