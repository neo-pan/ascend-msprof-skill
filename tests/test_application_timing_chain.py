"""Application timing contracts from raw CSV through persisted evidence and reports."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tests.helpers_shared import CLI, fresh_real_run, one_line_read, run
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.generate_report import build_report
from ascend_msprof_skill.run_evidence import RunEvidence
from ascend_msprof_skill.summarize_candidate import build_candidate_summary
from ascend_msprof_skill.compare_runs import build_comparison


TIMING_INPUTS = (
    ("op_summary", "Op Name", "Task Duration(us)"),
    ("op_statistic", "OP Type", "Total Time(us)"),
    ("task_time", "kernel_name", "task_time(us)"),
    ("api_statistic", "API Name", "Time(us)"),
)


class ApplicationTimingChainTests(unittest.TestCase):
    def write_csv(self, root, group, name_field, value_field, rows):
        path = root / "reports" / f"{group}_001.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{name_field},{value_field}\n{rows}", encoding="utf-8")
        return path

    def assert_chain(self, root, expected_groups):
        artifacts = write_evidence_model(root)
        summary = json.loads(artifacts.summary_path.read_text())
        evidence = RunEvidence.load(root)
        self.assertEqual(evidence.evidence_readiness(), summary["evidence_readiness"])
        available = "app_timing" in summary["evidence_readiness"]["available_evidence_families"]
        self.assertEqual(available, bool(expected_groups))
        facts = {f.group: f for _, f in evidence.diagnosis_headlines()}
        self.assertEqual(set(facts), set(expected_groups))
        report = build_report(summary, root)
        self.assertNotIn("No application timing observation available", report)
        read = one_line_read(report)
        self.assertNotIn("= `n/a`", read)
        if expected_groups:
            first = next(iter(facts.values()))
            self.assertIn(first.artifact, read)
            self.assertIn(first.raw_value_field_ref, read)
        else:
            self.assertIn("No finite sourced headline is available", read)
        observations = report.split("## 3. Observations", 1)[1].split("## 4.", 1)[0]
        for group in expected_groups:
            item = summary["headlines"][group]
            self.assertEqual(facts[group].value, item["value"])
            self.assertIn(item["file"], observations)
            self.assertIn(f"headlines.{group}.raw_row.{item['field']}", observations)
        return summary, report

    def test_each_supported_timing_source_reaches_report_with_its_exact_field(self):
        for group, name, field in TIMING_INPUTS:
            with self.subTest(group=group), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                raw = self.write_csv(root, group, name, field, "smaller,12.5\nlarger,99\n")
                before = raw.read_bytes()
                summary, report = self.assert_chain(root, {group})
                self.assertEqual(summary["headlines"][group]["value"], 99)
                self.assertEqual(summary["headlines"][group]["raw_row"][field], "99")
                self.assertEqual(raw.read_bytes(), before)
                if group == "api_statistic":
                    self.assertIn("Host/runtime API timing context; not standalone device kernel duration", report)
                if group == "op_statistic":
                    self.assertIn("Aggregate operator-type timing; not an individual kernel invocation", report)

    def test_empty_or_invalid_cells_do_not_become_available_timing(self):
        for group, name, field in TIMING_INPUTS:
            for rows in ("", "kernel,\n", "kernel,NaN\n", "kernel,1e9999\n", "kernel,99 us\n"):
                with self.subTest(group=group, rows=rows), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    path = self.write_csv(root, group, name, field, rows)
                    summary, report = self.assert_chain(root, set())
                    self.assertTrue(summary["files"][group])
                    self.assertIsNone(summary["headlines"][group]["value"])
                    stage = next(s for s in summary["evidence_readiness"]["segments"] if s["segment"] == "app")
                    self.assertEqual(stage["status"], "no_usable_timing")
                    self.assertEqual(stage["missing_required_artifacts"], [])
                    self.assertIn("No finite application timing headline was parsed", report)
                    self.assertTrue(path.exists())

    def test_zero_and_scientific_notation_are_valid_timing(self):
        for value, expected in (("0", 0), ("9.9e1", 99)):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.write_csv(root, "api_statistic", "API Name", "Time(us)", f"api,{value}\n")
                summary, _ = self.assert_chain(root, {"api_statistic"})
                self.assertEqual(summary["headlines"]["api_statistic"]["value"], expected)

    def test_unusable_source_does_not_hide_valid_timing_from_another_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_csv(root, "op_summary", "Op Name", "Task Duration(us)", "kernel,NaN\n")
            self.write_csv(root, "op_statistic", "OP Type", "Total Time(us)", "")
            self.write_csv(root, "api_statistic", "API Name", "Time(us)", "api,99\n")
            summary, _ = self.assert_chain(root, {"api_statistic"})
            stage = next(s for s in summary["evidence_readiness"]["segments"] if s["segment"] == "app")
            self.assertEqual(stage["status"], "ready")
            self.assertTrue(summary["files"]["op_summary"])
            self.assertTrue(summary["files"]["op_statistic"])

    def test_missing_and_unreadable_inputs_remain_distinct_in_raw_index(self):
        for unreadable in (False, True):
            with self.subTest(unreadable=unreadable), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                if unreadable:
                    path = self.write_csv(root, "op_summary", "Op Name", "Task Duration(us)", "")
                    path.write_bytes(b"\xff\xfe\xfa")
                summary, _ = self.assert_chain(root, set())
                records = RunEvidence.load(root).raw_artifacts()
                app_records = [r for r in records if r.group == "op_summary"]
                self.assertEqual(bool(app_records), unreadable)
                if unreadable:
                    self.assertEqual(app_records[0].status, "invalid")

    def test_one_line_keeps_valid_operator_metric_when_app_timing_is_unusable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.write_csv(root, "op_summary", "Op Name", "Task Duration(us)", "kernel,NaN\n")
            op = root / "reports" / "OPPROF_001"
            op.mkdir()
            (op / "PipeUtilization.csv").write_text("Pipe,Utilization(%)\nVector,73\n")
            summary = write_evidence_model(root).summary
            report = build_report(summary, root)
            read = one_line_read(report)
            self.assertIn("Dominant pipe signal", read)
            self.assertIn("`73`", read)
            self.assertIn("headlines.pipe_utilization.raw_row.Utilization(%)", read)
            self.assertNotIn("= `n/a`", read)
            self.assertIn(app.relative_to(root).as_posix(), report)

    def test_one_line_does_not_promote_metadata_without_a_numeric_headline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "reports" / "OPPROF_001"
            reports.mkdir(parents=True)
            (reports / "OpBasicInfo.csv").write_text("Op Name,Op Type\nkernel,Vector\n")
            summary = write_evidence_model(root).summary
            report = build_report(summary, root)
            self.assertIn("No finite sourced headline is available", one_line_read(report))
            self.assertIn("Operator metadata", report)
            self.assertIn("reports/OPPROF_001/OpBasicInfo.csv", report)

    def test_cli_replay_real_fixture_preserves_raw_and_agrees_with_in_memory_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fresh_real_run(Path(tmp))
            raw = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (root / "reports").rglob("*") if p.is_file()}
            run([*CLI, "analyze", "--run-dir", str(root)])
            run([*CLI, "report", "--run-dir", str(root)])
            summary = json.loads((root / "analysis" / "summary.json").read_text())
            rendered = (root / "REPORT.md").read_text()
            self.assertEqual(rendered, build_report(summary, root))
            observations = rendered.split("## 3. Observations", 1)[1].split("## 4.", 1)[0]
            for group, _, field in TIMING_INPUTS:
                self.assertIn(summary["headlines"][group]["file"], observations)
                self.assertIn(f"headlines.{group}.raw_row.{field}", observations)
            candidate = build_candidate_summary(root, root)
            comparison = build_comparison(root, root)
            for key in ("performance_assessment", "mechanism_assessment"):
                self.assertEqual(candidate[key], comparison[key])
            self.assertEqual(raw, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in raw})
