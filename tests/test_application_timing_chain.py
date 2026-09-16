"""Application timing contracts from raw CSV through persisted evidence and reports."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tests.helpers_shared import CLI, fresh_real_run, one_line_read, run
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.application_timing import TimingEvidence, observation_field_ref
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
        self.assertEqual(evidence.evidence_readiness().model_dump(mode="json", exclude_unset=True), summary["evidence_readiness"])
        available = "app_timing" in summary["evidence_readiness"]["available_evidence_families"]
        self.assertEqual(available, bool(expected_groups))
        facts = {}
        for _, fact in evidence.diagnosis_headlines():
            facts.setdefault(fact.group, []).append(fact)
        self.assertEqual(set(facts), set(expected_groups))
        report = build_report(summary, root)
        self.assertNotIn("No application timing observation available", report)
        self.assertNotIn("**One-line read:**", report)
        self.assertIn("The calling agent selects", report)
        for group_facts in facts.values():
            for fact in group_facts:
                self.assertIn(fact.artifact, report)
                self.assertIn(fact.raw_value_field_ref, report)
        observations = report.split("## 3. Observations", 1)[1].split("## 4.", 1)[0]
        for group in expected_groups:
            timing = TimingEvidence.model_validate(summary["headlines"][group])
            items = [item for artifact in timing.artifacts for item in artifact.observations]
            self.assertEqual({fact.value for fact in facts[group]}, {item.value for item in items})
            for item in items:
                self.assertIn(item.source.artifact, observations)
                self.assertIn(observation_field_ref(group, item), observations)
        return summary, report

    def test_each_supported_timing_source_reaches_report_with_its_exact_field(self):
        for group, name, field in TIMING_INPUTS:
            with self.subTest(group=group), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                raw = self.write_csv(root, group, name, field, "smaller,12.5\nlarger,99\n")
                before = raw.read_bytes()
                summary, report = self.assert_chain(root, {group})
                timing = TimingEvidence.model_validate(summary["headlines"][group])
                by_name = {item.name: item for artifact in timing.artifacts for item in artifact.observations}
                if group in {"op_summary", "task_time"}:
                    self.assertEqual({name: item.value for name, item in by_name.items()}, {"smaller": 12.5, "larger": 99})
                    self.assertEqual(by_name["larger"].raw_token, "99")
                    self.assertIsNone(timing.observation)
                else:
                    self.assertEqual(timing.observation.value, 99)
                    self.assertEqual(timing.observation.raw_token, "99")
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
                    self.assertTrue(summary["headlines"][group]["artifacts"])
                    self.assertIsNone(TimingEvidence.model_validate(summary["headlines"][group]).observation)
                    stage = next(s for s in summary["evidence_readiness"]["segments"] if s["segment"] == "app")
                    self.assertEqual(stage["status"], "no_usable_timing")
                    self.assertEqual(stage["missing_required_artifacts"], [])
                    self.assertIn("No finite application timing observation was parsed", report)
                    self.assertTrue(path.exists())

    def test_zero_and_scientific_notation_are_valid_timing(self):
        for value, expected in (("0", 0), ("9.9e1", 99)):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.write_csv(root, "api_statistic", "API Name", "Time(us)", f"api,{value}\n")
                summary, _ = self.assert_chain(root, {"api_statistic"})
                self.assertEqual(TimingEvidence.model_validate(summary["headlines"]["api_statistic"]).observation.value, expected)

    def test_unusable_source_does_not_hide_valid_timing_from_another_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_csv(root, "op_summary", "Op Name", "Task Duration(us)", "kernel,NaN\n")
            self.write_csv(root, "op_statistic", "OP Type", "Total Time(us)", "")
            self.write_csv(root, "api_statistic", "API Name", "Time(us)", "api,99\n")
            summary, _ = self.assert_chain(root, {"api_statistic"})
            stage = next(s for s in summary["evidence_readiness"]["segments"] if s["segment"] == "app")
            self.assertEqual(stage["status"], "ready")
            self.assertTrue(summary["headlines"]["op_summary"]["artifacts"])
            self.assertTrue(summary["headlines"]["op_statistic"]["artifacts"])

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

    def test_observations_keep_valid_operator_metric_when_app_timing_is_unusable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.write_csv(root, "op_summary", "Op Name", "Task Duration(us)", "kernel,NaN\n")
            op = root / "reports" / "OPPROF_001"
            op.mkdir()
            (op / "PipeUtilization.csv").write_text("Pipe,Utilization(%)\nVector,73\n")
            summary = write_evidence_model(root).summary
            report = build_report(summary, root)
            self.assertNotIn("**One-line read:**", report)
            read = report
            self.assertIn("Pipe observations", read)
            self.assertIn("`73`", read)
            self.assertIn("field=Utilization(%)", read)
            self.assertNotIn("= `n/a`", read)
            self.assertIn(app.relative_to(root).as_posix(), report)

    def test_report_does_not_promote_metadata_to_a_conclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "reports" / "OPPROF_001"
            reports.mkdir(parents=True)
            (reports / "OpBasicInfo.csv").write_text("Op Name,Op Type\nkernel,Vector\n")
            summary = write_evidence_model(root).summary
            report = build_report(summary, root)
            self.assertNotIn("**One-line read:**", report)
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
                timing = TimingEvidence.model_validate(summary["headlines"][group])
                for artifact in timing.artifacts:
                    self.assertIn(artifact.artifact, observations)
                self.assertIn(f"field={field}", observations)
            candidate = build_candidate_summary(root, root).model_dump(mode="json")
            comparison = build_comparison(root, root).model_dump(mode="json")
            for key in ("performance_assessment", "mechanism_assessment"):
                self.assertEqual(candidate[key], comparison[key])
            self.assertEqual(raw, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in raw})
