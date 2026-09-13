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
from ascend_msprof_skill.run_assessment import assess_run
from ascend_msprof_skill.run_evidence import RunEvidence
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


from ascend_msprof_skill.assessment_types import ComparisonSummary

class TileLangDesignFeedbackFixtureTests(unittest.TestCase):
    def test_fixture_manifest_and_raw_artifacts_remain_intact(self):
        manifest = load_json(FIXTURE_ROOT / "manifest.json")
        for case in manifest["cases"]:
            base = case_path(case["case_id"])
            for rel in case["required_artifacts"]:
                self.assertTrue((base / rel).exists(), f"{case['case_id']}: {rel}")
            for rel in case["missing_artifacts"]:
                self.assertFalse((base / rel).exists(), f"{case['case_id']}: {rel}")

    def test_legacy_profiler_records_have_no_natural_performance_conclusion(self):
        result = build_comparison(case_path("candidate_comparability/baseline"), case_path("candidate_comparability/comparable_candidate")).model_dump(mode="json")
        self.assertEqual(result["performance_assessment"]["eligibility"]["status"], "incomplete")
        self.assertIsNone(result["performance_assessment"]["comparison"]["observation"])
        for q in result["mechanism_assessment"]["questions"]:
            self.assertTrue({"baseline", "candidate"} <= evidence_sources(q))
            self.assertFalse(any("runtime" in str(e.get("field_ref")) for e in q["available_evidence"]))

    def test_workload_mismatch_blocks_paired_questions(self):
        result = build_comparison(case_path("candidate_comparability/baseline"), case_path("candidate_comparability/workload_mismatch_candidate")).model_dump(mode="json")
        mechanism = result["mechanism_assessment"]
        self.assertTrue(any(c["status"] == "mismatch" for c in mechanism["workload_checks"]))
        self.assertTrue(all(q["blocked_by"] for q in mechanism["questions"]))

    def test_family_questions_preserve_present_and_missing_artifact_sources(self):
        for family, negative in (("memory_cache", "missing_memory_family"), ("pipe_arithmetic", "missing_arithmetic")):
            with self.subTest(family=family):
                positive = build_candidate_summary(case_path(f"{family}/positive")).model_dump(mode="json")["mechanism_assessment"]
                question = question_by_id(positive, family)
                self.assertTrue(question["available_evidence"])
                self.assertFalse(question["missing_evidence"])
                missing = build_candidate_summary(case_path(f"{family}/{negative}")).model_dump(mode="json")["mechanism_assessment"]
                question = question_by_id(missing, family)
                self.assertTrue(question["missing_evidence"])
                self.assertTrue(all(e["artifact"] and e["source"] for e in question["missing_evidence"]))

    def test_one_missing_artifact_does_not_hide_other_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = copy_case("memory_cache/positive", Path(tmp), "partial")
            before = build_candidate_summary(run_dir).model_dump(mode="json")["mechanism_assessment"]
            remove_raw_index_artifacts(run_dir, {"MemoryUB.csv"})
            after = build_candidate_summary(run_dir).model_dump(mode="json")["mechanism_assessment"]
            memory = question_by_id(after, "memory_cache")
            self.assertEqual(evidence_basenames(memory["missing_evidence"]), {"MemoryUB.csv"})
            left, right = (question_by_id(m, "pipe_arithmetic") for m in (before, after))
            self.assertEqual(left["status"], right["status"])
            self.assertEqual(left["blocked_by"], right["blocked_by"])
            self.assertEqual(evidence_basenames(left["available_evidence"]), evidence_basenames(right["available_evidence"]))

    def test_pair_missing_artifact_names_only_affected_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = copy_case("memory_cache/positive", Path(tmp), "baseline")
            candidate = copy_case("memory_cache/positive", Path(tmp), "candidate")
            remove_raw_index_artifacts(candidate, {"MemoryUB.csv"})
            q = question_by_id(build_comparison(baseline, candidate).model_dump(mode="json")["mechanism_assessment"], "memory_cache")
            self.assertEqual(missing_sources(q), {"candidate"})
            self.assertEqual(evidence_basenames(q["missing_evidence"]), {"MemoryUB.csv"})

    def test_missing_natural_runtime_does_not_block_profiler_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = copy_case("memory_cache/positive", Path(tmp), "candidate")
            before = build_candidate_summary(run_dir).model_dump(mode="json")["mechanism_assessment"]
            path = run_dir / "analysis/tilelang_context.json"
            context = load_json(path)
            context["benchmark"]["candidate"] = {"compiled": True}
            write_json(path, context)
            after = build_candidate_summary(run_dir).model_dump(mode="json")["mechanism_assessment"]
            self.assertEqual(before, after)

    def test_correctness_failure_preserves_generated_context_and_raw_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = copy_case("pipeline_expression/serial", Path(tmp), "candidate")
            path = run_dir / "analysis/tilelang_context.json"
            context = load_json(path)
            context["benchmark"]["correctness"]["raw"] = False
            write_json(path, context)
            mechanism = build_candidate_summary(run_dir).model_dump(mode="json")["mechanism_assessment"]
            generated = question_by_id(mechanism, "generated_context")
            self.assertFalse(any("correctness" in b for b in generated["blocked_by"]))
            self.assertTrue(generated["available_evidence"])
            self.assertTrue(question_by_id(mechanism, "memory_cache")["available_evidence"])

    def test_missing_summary_keeps_raw_inventory_inspectable(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = copy_case("memory_cache/positive", Path(tmp), "candidate")
            (run_dir / "analysis/summary.json").unlink()
            mechanism = build_candidate_summary(run_dir).model_dump(mode="json")["mechanism_assessment"]
            self.assertTrue(question_by_id(mechanism, "memory_cache")["available_evidence"])
            self.assertNotEqual(mechanism["coverage"], "missing")

    def test_markdown_cites_both_roles_and_separates_assessments(self):
        result = build_comparison(case_path("pipeline_expression/serial"), case_path("pipeline_expression/pipelined")).model_dump(mode="json")
        text = render_compare_markdown(ComparisonSummary.model_validate(result))
        self.assertIn("## Performance Assessment", text)
        self.assertIn("## Mechanism Assessment", text)
        self.assertIn("baseline", text)
        self.assertIn("candidate", text)
        self.assertIn("## Evidence Questions", text)

    def test_fixture_text_is_sanitized_and_has_no_large_binary_artifacts(self):
        for path in FIXTURE_ROOT.rglob("*"):
            if path.is_file() and path.suffix in {".json", ".md", ".txt", ".csv", ".py", ".c", ".cpp"}:
                text = path.read_text(encoding="utf-8", errors="replace")
                for prefix in ("/data/", "/tmp/", "/home/"):
                    self.assertNotIn(prefix, text, path)
            self.assertNotIn(path.suffix, {".db", ".so", ".bin", ".o"})


if __name__ == "__main__":
    unittest.main()
