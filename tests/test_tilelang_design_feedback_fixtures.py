import csv
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ascend_msprof_skill.compare_runs import build_comparison, render_markdown as render_compare_markdown  # noqa: E402
from ascend_msprof_skill.candidate_feedback import build_comparison_design_feedback, build_single_run_design_feedback  # noqa: E402
from ascend_msprof_skill.summarize_candidate import build_candidate_summary, render_markdown  # noqa: E402


FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "tilelang_design_feedback"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def case_path(case_id: str) -> Path:
    return FIXTURE_ROOT / case_id


def csv_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def copy_case(case_id: str, root: Path, name: str) -> Path:
    dst = root / name
    shutil.copytree(case_path(case_id), dst)
    return dst


def question_by_id(feedback: dict, question_id: str) -> dict:
    for question in feedback["questions"]:
        if question["id"] == question_id:
            return question
    raise AssertionError(f"missing design feedback question {question_id}")


def evidence_sources(question: dict) -> set[str]:
    return {item["source"] for item in question["available_evidence"] if isinstance(item, dict) and item.get("source")}


def missing_sources(question: dict) -> set[str]:
    return {item["source"] for item in question["missing_evidence"] if isinstance(item, dict) and item.get("source")}


def evidence_basenames(items: list[dict]) -> set[str]:
    return {Path(str(item.get("artifact"))).name for item in items if isinstance(item, dict) and item.get("artifact")}


def has_artifact(items: list[dict], artifact: str, *, source: str | None = None) -> bool:
    return any(
        isinstance(item, dict)
        and item.get("artifact") == artifact
        and (source is None or item.get("source") == source)
        for item in items
    )


def has_field_ref(items: list[dict], field_ref: str) -> bool:
    return any(isinstance(item, dict) and item.get("field_ref") == field_ref for item in items)


def remove_raw_index_artifacts(run_dir: Path, artifact_names: set[str]) -> None:
    raw_index_path = run_dir / "analysis" / "raw_artifact_index.json"
    raw_index = load_json(raw_index_path)
    raw_index["artifacts"] = [
        item
        for item in raw_index["artifacts"]
        if Path(str(item.get("artifact"))).name not in artifact_names
    ]
    write_json(raw_index_path, raw_index)


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
        self.assertEqual("ready", comparable["design_feedback"]["status"])
        comparable_question = question_by_id(comparable["design_feedback"], "candidate_comparability")
        self.assertGreater(len(comparable_question["available_evidence"]), 0)
        self.assertTrue({"a", "b"} <= evidence_sources(comparable_question))
        self.assertEqual([], comparable_question["missing_evidence"])
        self.assertEqual(15, comparable["evidence"]["a"]["raw_artifact_index"]["artifact_count"])
        self.assertEqual(15, comparable["evidence"]["b"]["raw_artifact_index"]["artifact_count"])

        mismatch = build_comparison(baseline, family / "workload_mismatch_candidate")
        self.assertFalse(mismatch["verdict"]["can_compare"])
        self.assertEqual("inconclusive", mismatch["verdict"]["decision"])
        self.assertEqual("blocked", mismatch["design_feedback"]["status"])
        self.assertTrue(question_by_id(mismatch["design_feedback"], "candidate_comparability")["blocked_by"])
        self.assertTrue(
            any(reason.startswith("incompatible runs: workload.id mismatch") for reason in mismatch["verdict"]["reasons"])
        )

        missing_raw = build_comparison(baseline, family / "missing_raw_index_candidate")
        self.assertTrue(missing_raw["verdict"]["can_compare"])
        self.assertEqual("inconclusive", missing_raw["verdict"]["decision"])
        self.assertEqual("blocked", missing_raw["design_feedback"]["status"])
        missing_raw_question = question_by_id(missing_raw["design_feedback"], "candidate_comparability")
        self.assertTrue(missing_raw_question["missing_evidence"])
        self.assertIn("b", missing_sources(missing_raw_question))
        self.assertIn("profiler evidence is missing", missing_raw["verdict"]["reasons"])

    def test_compare_candidate_comparability_cites_baseline_missing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = copy_case("candidate_comparability/baseline", root, "baseline")
            candidate = copy_case("candidate_comparability/comparable_candidate", root, "candidate")
            (baseline / "analysis" / "raw_artifact_index.json").unlink()

            comparison = build_comparison(baseline, candidate)
            question = question_by_id(comparison["design_feedback"], "candidate_comparability")

            self.assertEqual("blocked", comparison["design_feedback"]["status"])
            self.assertIn("a", missing_sources(question))
            self.assertTrue(
                any(
                    item.get("source") == "a" and item.get("artifact") == "analysis/raw_artifact_index.json"
                    for item in question["missing_evidence"]
                )
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = copy_case("candidate_comparability/baseline", root, "baseline")
            candidate = copy_case("candidate_comparability/comparable_candidate", root, "candidate")
            (baseline / "analysis" / "provenance.json").unlink()

            comparison = build_comparison(baseline, candidate)
            question = question_by_id(comparison["design_feedback"], "candidate_comparability")

            self.assertEqual("blocked", comparison["design_feedback"]["status"])
            self.assertTrue(
                any(item.get("source") == "a" and item.get("artifact") == "analysis/provenance.json" for item in question["missing_evidence"])
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = copy_case("candidate_comparability/baseline", root, "baseline")
            candidate = copy_case("candidate_comparability/comparable_candidate", root, "candidate")
            (baseline / "analysis" / "tilelang_context.json").unlink()

            comparison = build_comparison(baseline, candidate)
            question = question_by_id(comparison["design_feedback"], "candidate_comparability")

            self.assertEqual("blocked", comparison["design_feedback"]["status"])
            self.assertTrue(
                any(item.get("source") == "a" and item.get("artifact") == "analysis/tilelang_context.json" for item in question["missing_evidence"])
            )

    def test_candidate_comparability_distinguishes_missing_summary_from_raw_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = copy_case("candidate_comparability/comparable_candidate", Path(tmp), "missing_summary")
            (run_dir / "analysis" / "summary.json").unlink()

            summary = build_candidate_summary(run_dir)
            question = question_by_id(summary["design_feedback"], "candidate_comparability")

            self.assertEqual("blocked", summary["design_feedback"]["status"])
            self.assertTrue(has_artifact(question["missing_evidence"], "analysis/summary.json", source="run"))
            self.assertTrue(has_artifact(question["available_evidence"], "analysis/raw_artifact_index.json", source="run"))
            self.assertFalse(has_artifact(question["missing_evidence"], "analysis/raw_artifact_index.json", source="run"))

    def test_compare_candidate_comparability_distinguishes_branch_missing_summary_from_raw_inventory(self):
        baseline = case_path("candidate_comparability/baseline")
        candidate = case_path("candidate_comparability/comparable_candidate")

        feedback = build_comparison_design_feedback(
            load_json(baseline / "analysis" / "summary.json"),
            None,
            load_json(baseline / "analysis" / "tilelang_context.json"),
            load_json(candidate / "analysis" / "tilelang_context.json"),
            load_json(baseline / "analysis" / "raw_artifact_index.json"),
            load_json(candidate / "analysis" / "raw_artifact_index.json"),
            load_json(baseline / "analysis" / "provenance.json"),
            load_json(candidate / "analysis" / "provenance.json"),
            None,
        )
        question = question_by_id(feedback, "candidate_comparability")

        self.assertEqual("blocked", feedback["status"])
        self.assertTrue(has_artifact(question["missing_evidence"], "analysis/summary.json", source="b"))
        self.assertTrue(has_artifact(question["available_evidence"], "analysis/raw_artifact_index.json", source="b"))
        self.assertFalse(has_artifact(question["missing_evidence"], "analysis/raw_artifact_index.json", source="b"))
        self.assertFalse(has_artifact(question["missing_evidence"], "analysis/summary.json", source="a"))

    def test_compare_ready_questions_cite_both_branches(self):
        comparison = build_comparison(
            case_path("candidate_comparability/baseline"),
            case_path("candidate_comparability/comparable_candidate"),
        )
        self.assertEqual("ready", comparison["design_feedback"]["status"])
        for question_id in [
            "candidate_comparability",
            "memory_cache",
            "pipe_arithmetic",
            "opbasic_workload",
            "pipeline_expression",
            "generated_context",
        ]:
            with self.subTest(question_id=question_id):
                question = question_by_id(comparison["design_feedback"], question_id)
                self.assertTrue({"a", "b"} <= evidence_sources(question))
                self.assertEqual([], question["missing_evidence"])
                self.assertEqual([], question["blocked_by"])

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

        blocked_context = {
            "benchmark": {
                "candidate": {"compiled": False},
                "correctness": {"raw": False},
            }
        }
        feedback = build_single_run_design_feedback(None, blocked_context, None)
        blocked_question = question_by_id(feedback, "missing_evidence")
        self.assertEqual("blocked", feedback["status"])
        self.assertEqual(["missing_evidence"], [question["id"] for question in feedback["questions"]])
        self.assertTrue(has_field_ref(blocked_question["available_evidence"], "benchmark.candidate.compiled"))
        self.assertEqual([], [question for question in feedback["questions"] if question["id"] in {"memory_cache", "pipe_arithmetic"}])

        partial_failed_context = {
            "benchmark": {
                "candidate": {},
                "correctness": {"raw": False},
            }
        }
        partial_feedback = build_single_run_design_feedback(None, partial_failed_context, None)
        partial_question = question_by_id(partial_feedback, "missing_evidence")
        self.assertEqual("blocked", partial_feedback["status"])
        self.assertTrue(has_field_ref(partial_question["missing_evidence"], "benchmark.candidate.compiled"))
        self.assertFalse(has_field_ref(partial_question["available_evidence"], "benchmark.candidate.compiled"))

    def test_memory_cache_positive_and_missing_family(self):
        positive = case_path("memory_cache/positive")
        positive_summary = build_candidate_summary(positive)
        memory_question = question_by_id(positive_summary["design_feedback"], "memory_cache")
        self.assertEqual("ready", positive_summary["design_feedback"]["status"])
        self.assertGreater(len(memory_question["available_evidence"]), 0)
        self.assertEqual([], memory_question["missing_evidence"])
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
        missing_summary = build_candidate_summary(missing)
        missing_question = question_by_id(missing_summary["design_feedback"], "memory_cache")
        self.assertEqual("incomplete", missing_summary["design_feedback"]["status"])
        self.assertTrue(missing_question["missing_evidence"])
        self.assertTrue(missing_question["blocked_by"])
        self.assertTrue(memory_files.isdisjoint(evidence_basenames(missing_question["available_evidence"])))
        self.assertEqual(memory_files, evidence_basenames(missing_question["missing_evidence"]))
        absent = {path.name for path in missing.rglob("*.csv")}
        self.assertTrue(memory_files.isdisjoint(absent))
        groups = {item["group"] for item in load_json(missing / "analysis" / "raw_artifact_index.json")["artifacts"]}
        self.assertFalse({"memory", "l2_cache"} & groups)

    def test_memory_cache_reports_only_missing_required_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = copy_case("memory_cache/positive", Path(tmp), "partial_memory")
            remove_raw_index_artifacts(run_dir, {"MemoryUB.csv"})

            summary = build_candidate_summary(run_dir)
            question = question_by_id(summary["design_feedback"], "memory_cache")

            self.assertEqual("incomplete", summary["design_feedback"]["status"])
            self.assertIn("Memory.csv", evidence_basenames(question["available_evidence"]))
            self.assertIn("MemoryL0.csv", evidence_basenames(question["available_evidence"]))
            self.assertIn("L2Cache.csv", evidence_basenames(question["available_evidence"]))
            self.assertNotIn("MemoryUB.csv", evidence_basenames(question["available_evidence"]))
            self.assertEqual({"MemoryUB.csv"}, evidence_basenames(question["missing_evidence"]))

    def test_pipe_arithmetic_positive_and_missing_arithmetic(self):
        positive = case_path("pipe_arithmetic/positive")
        positive_summary = build_candidate_summary(positive)
        pipe_question = question_by_id(positive_summary["design_feedback"], "pipe_arithmetic")
        self.assertEqual("ready", positive_summary["design_feedback"]["status"])
        self.assertGreater(len(pipe_question["available_evidence"]), 0)
        self.assertEqual([], pipe_question["missing_evidence"])
        self.assertTrue(any(path.name == "PipeUtilization.csv" for path in positive.rglob("*.csv")))
        self.assertTrue(any(path.name == "ArithmeticUtilization.csv" for path in positive.rglob("*.csv")))
        self.assertIn("aiv_scalar_ratio", csv_header(next(positive.rglob("PipeUtilization.csv"))))
        self.assertIn("aiv_vec_ratio", csv_header(next(positive.rglob("ArithmeticUtilization.csv"))))

        missing = case_path("pipe_arithmetic/missing_arithmetic")
        missing_summary = build_candidate_summary(missing)
        missing_question = question_by_id(missing_summary["design_feedback"], "pipe_arithmetic")
        self.assertEqual("incomplete", missing_summary["design_feedback"]["status"])
        self.assertTrue(missing_question["missing_evidence"])
        self.assertTrue(missing_question["blocked_by"])
        self.assertIn("PipeUtilization.csv", evidence_basenames(missing_question["available_evidence"]))
        self.assertNotIn("ArithmeticUtilization.csv", evidence_basenames(missing_question["available_evidence"]))
        self.assertEqual({"ArithmeticUtilization.csv"}, evidence_basenames(missing_question["missing_evidence"]))
        self.assertTrue(any(path.name == "PipeUtilization.csv" for path in missing.rglob("*.csv")))
        self.assertFalse(any(path.name == "ArithmeticUtilization.csv" for path in missing.rglob("*.csv")))
        groups = {item["group"] for item in load_json(missing / "analysis" / "raw_artifact_index.json")["artifacts"]}
        self.assertNotIn("arithmetic_utilization", groups)

    def test_compare_family_questions_report_missing_artifact_on_named_branch_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = copy_case("candidate_comparability/baseline", root, "baseline")
            candidate = copy_case("candidate_comparability/comparable_candidate", root, "candidate")
            remove_raw_index_artifacts(candidate, {"MemoryUB.csv"})

            comparison = build_comparison(baseline, candidate)
            question = question_by_id(comparison["design_feedback"], "memory_cache")

            self.assertEqual("incomplete", comparison["design_feedback"]["status"])
            self.assertIn("Memory.csv", evidence_basenames(question["available_evidence"]))
            self.assertEqual({"b"}, missing_sources(question))
            self.assertTrue(
                any(
                    item.get("source") == "b" and Path(str(item.get("artifact"))).name == "MemoryUB.csv"
                    for item in question["missing_evidence"]
                )
            )
            self.assertFalse(
                any(
                    item.get("source") == "a" and Path(str(item.get("artifact"))).name == "MemoryUB.csv"
                    for item in question["missing_evidence"]
                )
            )

    def test_opbasic_workload_preserves_fields_context_and_missing_context_branch(self):
        positive = case_path("opbasic_workload/positive")
        positive_summary = build_candidate_summary(positive)
        opbasic_question = question_by_id(positive_summary["design_feedback"], "opbasic_workload")
        self.assertEqual("ready", positive_summary["design_feedback"]["status"])
        self.assertGreater(len(opbasic_question["available_evidence"]), 0)
        self.assertEqual([], opbasic_question["missing_evidence"])
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
        missing_summary = build_candidate_summary(missing)
        missing_question = question_by_id(missing_summary["design_feedback"], "opbasic_workload")
        self.assertEqual("blocked", missing_summary["design_feedback"]["status"])
        self.assertTrue(missing_question["missing_evidence"])
        self.assertIn("missing workload context", missing_question["blocked_by"])
        self.assertTrue(any(path.name == "OpBasicInfo.csv" for path in missing.rglob("*.csv")))
        self.assertFalse((missing / "analysis" / "tilelang_context.json").exists())

    def test_opbasic_workload_reports_partial_workload_fields_as_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = copy_case("opbasic_workload/positive", Path(tmp), "partial_workload")
            context_path = run_dir / "analysis" / "tilelang_context.json"
            context = load_json(context_path)
            context["benchmark"]["workload"].pop("dtype")
            write_json(context_path, context)

            summary = build_candidate_summary(run_dir)
            question = question_by_id(summary["design_feedback"], "opbasic_workload")

            self.assertEqual("incomplete", summary["design_feedback"]["status"])
            self.assertTrue(
                any(item.get("field_ref") == "benchmark.workload.dtype" for item in question["missing_evidence"])
            )
            self.assertFalse(
                any(item.get("field_ref") == "benchmark.workload.dtype" for item in question["available_evidence"])
            )

    def test_pipeline_positive_pair_is_separate_from_compile_blocked_negative(self):
        serial = case_path("pipeline_expression/serial")
        pipelined = case_path("pipeline_expression/pipelined")
        comparison = build_comparison(serial, pipelined)
        self.assertTrue(comparison["verdict"]["can_compare"])
        self.assertEqual("promote", comparison["verdict"]["decision"])
        pipeline_question = question_by_id(comparison["design_feedback"], "pipeline_expression")
        self.assertEqual("ready", comparison["design_feedback"]["status"])
        self.assertGreater(len(pipeline_question["available_evidence"]), 0)
        self.assertEqual([], pipeline_question["missing_evidence"])
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

    def test_pipeline_expression_does_not_cite_absent_generated_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            serial = copy_case("pipeline_expression/serial", root, "serial")
            pipelined = copy_case("pipeline_expression/pipelined", root, "pipelined")
            context_path = serial / "analysis" / "tilelang_context.json"
            context = load_json(context_path)
            context.pop("jit_debug")
            write_json(context_path, context)

            comparison = build_comparison(serial, pipelined)
            pipeline_question = question_by_id(comparison["design_feedback"], "pipeline_expression")
            generated_question = question_by_id(comparison["design_feedback"], "generated_context")

            self.assertEqual("incomplete", comparison["design_feedback"]["status"])
            for question in [pipeline_question, generated_question]:
                self.assertTrue(
                    any(item.get("source") == "a" and item.get("field_ref") == "jit_debug" for item in question["missing_evidence"])
                )
                self.assertFalse(
                    any(item.get("source") == "a" and item.get("field_ref") == "jit_debug" for item in question["available_evidence"])
                )

    def test_generated_context_is_source_inspection_context_not_standalone_evidence(self):
        positive = case_path("generated_context/positive")
        positive_summary = build_candidate_summary(positive)
        generated_question = question_by_id(positive_summary["design_feedback"], "generated_context")
        self.assertEqual("ready", positive_summary["design_feedback"]["status"])
        self.assertGreater(len(generated_question["available_evidence"]), 0)
        self.assertEqual([], generated_question["missing_evidence"])
        context = load_json(positive / "analysis" / "tilelang_context.json")
        self.assertTrue(context["jit_debug"]["found"])
        self.assertGreaterEqual(context["jit_debug"]["artifact_count"], 5)
        self.assertTrue((positive / "analysis" / "summary.json").exists())
        self.assertTrue((positive / "analysis" / "raw_artifact_index.json").exists())
        self.assertTrue((positive / "tilelang-jit-debug" / "tilelang_jit_kernel_build_svd_kernel.c").exists())

        missing = case_path("generated_context/missing_on_device_evidence")
        missing_context = load_json(missing / "analysis" / "tilelang_context.json")
        missing_feedback = build_single_run_design_feedback(None, missing_context, None)
        missing_generated_question = question_by_id(missing_feedback, "generated_context")
        self.assertEqual("blocked", missing_feedback["status"])
        self.assertIn("missing on-device profiler evidence", missing_generated_question["blocked_by"])
        self.assertTrue(missing_context["jit_debug"]["found"])
        self.assertFalse((missing / "analysis" / "summary.json").exists())
        self.assertFalse((missing / "analysis" / "raw_artifact_index.json").exists())
        self.assertFalse((missing / "reports").exists())

    def test_generated_candidate_summary_markdown_contains_design_feedback_section(self):
        summary = build_candidate_summary(case_path("memory_cache/positive"))
        markdown = render_markdown(summary)
        self.assertIn("## Design Feedback", markdown)
        self.assertIn("| Question ID | Family | Question | Available Evidence | Missing Evidence | Blockers |", markdown)
        self.assertIn("Should the next inspection compare memory movement or cache context", markdown)
        self.assertIn("`memory_cache`", markdown)
        self.assertIn("`run: memory_cache raw artifact:", markdown)
        self.assertIn("- Next experiment:", markdown)

    def test_compare_markdown_contains_design_feedback_source_and_role_labels(self):
        comparison = build_comparison(
            case_path("candidate_comparability/baseline"),
            case_path("candidate_comparability/comparable_candidate"),
        )
        markdown = render_compare_markdown(comparison)
        self.assertIn("Should the next inspection compare memory movement or cache context between the two runs", markdown)
        self.assertIn("`a: memory_cache raw artifact:", markdown)
        self.assertIn("`b: memory_cache raw artifact:", markdown)

    def test_fixture_json_and_markdown_outputs_avoid_forbidden_design_feedback_wording(self):
        forbidden = [
            "root " + "cause",
            "thres" + "hold",
            "re" + "write",
            "automatic " + "tuning",
            "task-specific " + "SVD diagnosis",
            "failed-SVD-" + "profiler",
        ]
        generated_texts = [
            json.dumps(build_candidate_summary(case_path("memory_cache/positive"))["design_feedback"], sort_keys=True),
            json.dumps(build_candidate_summary(case_path("pipe_arithmetic/positive"))["design_feedback"], sort_keys=True),
            json.dumps(build_comparison(case_path("pipeline_expression/serial"), case_path("pipeline_expression/pipelined"))["design_feedback"], sort_keys=True),
            "\n".join(render_markdown(build_candidate_summary(case_path("memory_cache/positive"))).split("## Design Feedback", 1)[1:]),
        ]
        for text in generated_texts:
            text = text.lower()
            for term in forbidden:
                self.assertNotIn(term.lower(), text)

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
