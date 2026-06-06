import csv
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ascend_msprof_skill.compare_runs import build_comparison  # noqa: E402


FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "tilelang_design_feedback"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def case_path(case_id: str) -> Path:
    return FIXTURE_ROOT / case_id


def csv_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


class TileLangDesignFeedbackFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_json(FIXTURE_ROOT / "manifest.json")
        cls.cases = cls.manifest["cases"]

    def test_manifest_covers_evidence_families_and_artifact_contract(self):
        expected_families = {
            "candidate_comparability",
            "missing_evidence",
            "memory_cache",
            "pipe_arithmetic",
            "opbasic_workload",
            "pipeline_expression",
            "generated_context",
        }
        self.assertEqual(expected_families, {case["evidence_family"] for case in self.cases})
        self.assertEqual({"positive", "negative", "boundary"}, {case["role"] for case in self.cases})
        self.assertEqual("blocked", self.manifest["formal_behavior_status"])

        for case in self.cases:
            base = case_path(case["case_id"])
            self.assertTrue(base.exists(), case["case_id"])
            self.assertIn("evidence carriers only", case["workload_role_note"])
            for rel in case["required_artifacts"]:
                self.assertTrue((base / rel).exists(), f"{case['case_id']} requires {rel}")
            for rel in case["missing_artifacts"]:
                self.assertFalse((base / rel).exists(), f"{case['case_id']} must omit {rel}")

    def test_candidate_comparability_positive_and_boundary_cases(self):
        family = FIXTURE_ROOT / "candidate_comparability"
        baseline = family / "baseline"

        comparable = build_comparison(baseline, family / "comparable_candidate")
        self.assertTrue(comparable["verdict"]["can_compare"])
        self.assertEqual("promote", comparable["verdict"]["decision"])
        self.assertEqual(15, comparable["evidence"]["a"]["raw_artifact_index"]["artifact_count"])
        self.assertEqual(15, comparable["evidence"]["b"]["raw_artifact_index"]["artifact_count"])

        mismatch = build_comparison(baseline, family / "workload_mismatch_candidate")
        self.assertFalse(mismatch["verdict"]["can_compare"])
        self.assertEqual("inconclusive", mismatch["verdict"]["decision"])
        self.assertTrue(
            any(reason.startswith("incompatible runs: workload.id mismatch") for reason in mismatch["verdict"]["reasons"])
        )

        missing_raw = build_comparison(baseline, family / "missing_raw_index_candidate")
        self.assertTrue(missing_raw["verdict"]["can_compare"])
        self.assertEqual("inconclusive", missing_raw["verdict"]["decision"])
        self.assertIn("profiler evidence is missing", missing_raw["verdict"]["reasons"])

    def test_compile_blocked_and_correctness_failed_negative_evidence_have_no_profiler_artifacts(self):
        compile_blocked = case_path("missing_evidence/compile_blocked_candidate")
        result = load_json(compile_blocked / "benchmark_result.json")
        self.assertIs(result["compiled"], False)
        self.assertEqual("compile", result["error"]["stage"])
        self.assertFalse((compile_blocked / "analysis").exists())
        self.assertFalse((compile_blocked / "reports").exists())
        self.assertEqual([], list(compile_blocked.rglob("*.csv")))

        correctness_failed = case_path("missing_evidence/correctness_failed_candidate")
        failed_result = load_json(correctness_failed / "benchmark_result.json")
        self.assertIs(failed_result["compiled"], True)
        self.assertIs(failed_result["correctness"], False)
        self.assertFalse((correctness_failed / "reports").exists())
        self.assertTrue((correctness_failed / "tilelang-jit-debug" / "tilelang_jit_program_build_svd_kernel.py").exists())

    def test_memory_cache_positive_and_missing_family(self):
        positive = case_path("memory_cache/positive")
        memory_files = {
            "Memory.csv",
            "MemoryL0.csv",
            "MemoryUB.csv",
            "L2Cache.csv",
        }
        present = {path.name for path in positive.rglob("*.csv")}
        self.assertTrue(memory_files <= present)
        self.assertIn("GM_to_UB_bw_usage_rate(%)", csv_header(next(positive.rglob("Memory.csv"))))

        missing = case_path("memory_cache/missing_memory_family")
        absent = {path.name for path in missing.rglob("*.csv")}
        self.assertTrue(memory_files.isdisjoint(absent))
        groups = {item["group"] for item in load_json(missing / "analysis" / "raw_artifact_index.json")["artifacts"]}
        self.assertFalse({"memory", "l2_cache"} & groups)

    def test_pipe_arithmetic_positive_and_missing_arithmetic(self):
        positive = case_path("pipe_arithmetic/positive")
        self.assertTrue(any(path.name == "PipeUtilization.csv" for path in positive.rglob("*.csv")))
        self.assertTrue(any(path.name == "ArithmeticUtilization.csv" for path in positive.rglob("*.csv")))
        self.assertIn("aiv_scalar_ratio", csv_header(next(positive.rglob("PipeUtilization.csv"))))
        self.assertIn("aiv_vec_ratio", csv_header(next(positive.rglob("ArithmeticUtilization.csv"))))

        missing = case_path("pipe_arithmetic/missing_arithmetic")
        self.assertTrue(any(path.name == "PipeUtilization.csv" for path in missing.rglob("*.csv")))
        self.assertFalse(any(path.name == "ArithmeticUtilization.csv" for path in missing.rglob("*.csv")))
        groups = {item["group"] for item in load_json(missing / "analysis" / "raw_artifact_index.json")["artifacts"]}
        self.assertNotIn("arithmetic_utilization", groups)

    def test_opbasic_workload_preserves_fields_context_and_missing_context_branch(self):
        positive = case_path("opbasic_workload/positive")
        opbasic = next(path for path in positive.rglob("OpBasicInfo.csv") if "followups" in path.parts)
        header = csv_header(opbasic)
        self.assertIn("Block Dim", header)
        self.assertIn("Mix Block Dim", header)

        context = load_json(positive / "analysis" / "tilelang_context.json")
        self.assertEqual([256, 32, 32], context["benchmark"]["workload"]["shape"])
        self.assertEqual("float32", context["benchmark"]["workload"]["dtype"])
        provenance = load_json(positive / "analysis" / "provenance.json")
        self.assertEqual("8.3.0.2.220:8.3.RC2", provenance["cann_version"]["value"])
        self.assertEqual("4 x 910B2; health OK", provenance["hardware"]["summary"]["value"])

        missing = case_path("opbasic_workload/missing_workload_context")
        self.assertTrue(any(path.name == "OpBasicInfo.csv" for path in missing.rglob("*.csv")))
        self.assertFalse((missing / "analysis" / "tilelang_context.json").exists())

    def test_pipeline_positive_pair_is_separate_from_compile_blocked_negative(self):
        serial = case_path("pipeline_expression/serial")
        pipelined = case_path("pipeline_expression/pipelined")
        comparison = build_comparison(serial, pipelined)
        self.assertTrue(comparison["verdict"]["can_compare"])
        self.assertEqual("promote", comparison["verdict"]["decision"])
        self.assertEqual(
            "tilelang-ascend/matmul_add/v1/controlled-1024x1024x1024-float16",
            comparison["benchmark"]["workload"][0]["a"],
        )
        self.assertTrue((pipelined / "analysis" / "compare_tilelang-controlled-matmul-add-serial-20260606_vs_tilelang-controlled-matmul-add-pipelined-20260606.json").exists())

        blocked = case_path("pipeline_expression/compile_blocked_negative")
        self.assertFalse((blocked / "analysis").exists())
        self.assertFalse((blocked / "reports").exists())
        blocked_result = load_json(blocked / "benchmark_result.json")
        self.assertIs(blocked_result["compiled"], False)
        self.assertEqual("compile", blocked_result["error"]["stage"])

    def test_generated_context_is_source_inspection_context_not_standalone_evidence(self):
        positive = case_path("generated_context/positive")
        context = load_json(positive / "analysis" / "tilelang_context.json")
        self.assertTrue(context["jit_debug"]["found"])
        self.assertGreaterEqual(context["jit_debug"]["artifact_count"], 5)
        self.assertTrue((positive / "analysis" / "summary.json").exists())
        self.assertTrue((positive / "analysis" / "raw_artifact_index.json").exists())
        self.assertTrue((positive / "tilelang-jit-debug" / "tilelang_jit_kernel_build_svd_kernel.c").exists())

        missing = case_path("generated_context/missing_on_device_evidence")
        missing_context = load_json(missing / "analysis" / "tilelang_context.json")
        self.assertTrue(missing_context["jit_debug"]["found"])
        self.assertFalse((missing / "analysis" / "summary.json").exists())
        self.assertFalse((missing / "analysis" / "raw_artifact_index.json").exists())
        self.assertFalse((missing / "reports").exists())

    def test_fixture_json_and_markdown_outputs_avoid_forbidden_design_feedback_wording(self):
        forbidden = [
            "root " + "cause",
            "thres" + "hold",
            "re" + "write",
            "automatic " + "tuning",
            "task-specific " + "SVD diagnosis",
            "failed-SVD-" + "profiler",
        ]
        for path in FIXTURE_ROOT.rglob("*"):
            if path.suffix not in {".json", ".md"}:
                continue
            text = path.read_text(encoding="utf-8").lower()
            for term in forbidden:
                self.assertNotIn(term.lower(), text, path)

    def test_fixture_text_is_sanitized_and_contains_no_large_binary_artifacts(self):
        for path in FIXTURE_ROOT.rglob("*"):
            if path.is_file() and path.suffix in {".json", ".md", ".txt", ".csv", ".py", ".c", ".cpp"}:
                text = path.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn("/data/", text, path)
                self.assertNotIn("/tmp/", text, path)
                self.assertNotIn("/home/", text, path)
            self.assertNotIn(path.suffix, {".db", ".so", ".bin", ".o"})


if __name__ == "__main__":
    unittest.main()
