"""Raw-input boundaries and validated persistence, not model-shape snapshots."""
import json
import copy
import tempfile
from pathlib import Path
from unittest import mock

from tests.helpers_shared import unittest, write_minimal_pipe_op
from pydantic import ValidationError
from ascend_msprof_skill.application_timing import TimingEvidence, normalize_timing, select_primary
from ascend_msprof_skill.artifact_reader import read_json
from ascend_msprof_skill.evidence_model import write_evidence_model
from ascend_msprof_skill.generate_report import build_report
from ascend_msprof_skill.run_evidence import RunEvidence, RunEvidenceError


class TimingNormalizationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def artifact(self, text, group="op_summary", suffix="001"):
        path = self.root / "reports" / "PROF_001" / f"{group}_{suffix}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def normalize(self, text, group="op_summary"):
        path = self.artifact(text, group)
        return normalize_timing(path, path.relative_to(self.root).as_posix(), group, "app", None)

    def test_duplicate_headers_never_overwrite_a_timing_cell(self):
        record = self.normalize("Op Name,Task Duration(us),Task Duration(us)\nkernel,12,99\n")
        self.assertEqual(record.status, "invalid")
        self.assertEqual(record.observations, ())
        issue = record.issues[0]
        self.assertEqual((issue.code, issue.source.record, issue.source.column), ("duplicate_header", 1, 2))

    def test_bad_record_preserves_valid_subset_but_blocks_count_authority(self):
        self.artifact("Op Name,Task Duration(us)\nkernel,12\nbad,3,4\nother,NaN\n")
        result = write_evidence_model(self.root)
        timing = result.summary.headlines["op_summary"]
        self.assertEqual(timing.observation.value, 12)
        self.assertEqual(timing.artifacts[0].row_count, 3)
        self.assertFalse(result.summary.profile_coverage.model_dump(mode="json", exclude_unset=True)["segments"]["app"]["authority_complete"])
        self.assertEqual({issue.code for issue in timing.artifacts[0].issues}, {"row_width", "invalid_number"})

    def test_alias_conflict_and_equivalent_aliases(self):
        for token, expected in (("99", None), ("1.2e1", 12)):
            with self.subTest(token=token):
                record = self.normalize(f"Op Name,Task Duration(us),Duration(us)\nkernel,12,{token}\n")
                if expected is None:
                    self.assertEqual(record.observations, ())
                    self.assertEqual(record.issues[0].code, "alias_conflict")
                else:
                    observation = record.observations[0]
                    self.assertEqual(observation.value, expected)
                    self.assertEqual(observation.aliases[0].column, 3)

    def test_statistics_are_distinct_and_unknown_spelling_is_not_guessed(self):
        record = self.normalize("OP Type,Total Time(us),Avg Time(us),Min Time(us),Max Time(us)\nVector,12,4,1,8\n", "op_statistic")
        self.assertEqual({item.statistic: item.value for item in record.observations},
                         {"total": 12, "average": 4, "minimum": 1, "maximum": 8})
        self.assertIsNone(select_primary((record,)).selected)
        self.assertEqual(len(select_primary((record,)).candidates), 4)
        unknown = self.normalize("Op Name,Very Long Task Duration(us)\nkernel,12\n")
        self.assertEqual(unknown.observations, ())
        self.assertEqual(unknown.issues[0].code, "unsupported_fields")

    def test_multiple_statistics_do_not_make_one_timing_scope_unready(self):
        self.artifact("OP Type,Total Time(us),Avg Time(us),Min Time(us),Max Time(us)\n"
                      "Vector,12,4,1,8\n", "op_statistic")
        write_minimal_pipe_op(self.root)
        result = write_evidence_model(self.root)
        timing = result.summary.headlines['op_statistic']
        self.assertIsNone(timing.primary.selected)
        self.assertEqual(timing.primary.reason, 'multiple_observations')
        self.assertEqual(len(timing.artifacts[0].observations), 4)
        app = next(segment for segment in result.summary.evidence_readiness.segments if segment.segment == 'app')
        self.assertEqual(app.status, 'ready')
        self.assertFalse(RunEvidence.load(self.root).ambiguous_timing())
        relations = result.summary.evidence_relations
        self.assertEqual([relation.kind for relation in relations], ['timing_plus_pipe'])
        timing_refs = [item for item in relations[0].evidence if 'op_statistic' in item.artifact]
        self.assertEqual({item.field: item.value for item in timing_refs},
                         {'Total Time(us)': 12, 'Avg Time(us)': 4, 'Min Time(us)': 1, 'Max Time(us)': 8})
        self.assertTrue(all('record=2' in item.field_ref and 'statistic=' in item.field_ref
                            for item in timing_refs))
        self.assertIn('`timing_plus_pipe`', build_report(result.summary, self.root))

    def test_timing_relations_still_require_a_unique_artifact_and_scope(self):
        write_minimal_pipe_op(self.root)
        for multiple_files in (False, True):
            with self.subTest(multiple_files=multiple_files):
                header = "Device_id,OP Type,Total Time(us),Avg Time(us)\n"
                self.artifact(header + "0,Vector,12,4\n" + (
                    "" if multiple_files else "1,Vector,24,8\n"), "op_statistic")
                if multiple_files:
                    self.artifact(header + "0,Vector,24,8\n", "op_statistic", suffix="002")
                result = write_evidence_model(self.root)
                self.assertTrue(result.summary.headlines['op_statistic'].available)
                self.assertTrue(RunEvidence.load(self.root).ambiguous_timing())
                self.assertEqual(result.summary.evidence_relations, ())

    def test_mixed_statistics_keep_all_device_scopes_in_report_and_comparison(self):
        self.artifact("Device_id,OP Type,Total Time(us),Avg Time(us)\n0,Vector,10,\n1,Vector,,20\n", "op_statistic")
        result = write_evidence_model(self.root)
        evidence = RunEvidence.load(self.root)
        timing = result.summary.headlines["op_statistic"]
        self.assertEqual(timing.primary.reason, "multiple_scopes")
        self.assertEqual(len(timing.primary.candidates), 2)
        self.assertIsNone(evidence.primary_headline())
        self.assertFalse(evidence.comparison_headline_record("op_statistic").present)
        self.assertTrue(evidence.ambiguous_timing())
        self.assertEqual([fact.value for fact in evidence.timing_headline_records("op_statistic")], [10, 20])
        report = build_report(result.summary, self.root)
        self.assertIn("Valid application timing observations span multiple sources or scopes", report)
        self.assertIn("statistic=total", report)
        self.assertIn("statistic=average", report)

    def test_conflicting_case_equivalent_names_preserve_timing_without_count_authority(self):
        for first, second in (("expected", "other"), ("other", "expected"), ("expected", "expected")):
            with self.subTest(first=first, second=second):
                self.artifact(f"Op Name,op name,Task Duration(us)\n{first},{second},12\n")
                result = write_evidence_model(self.root)
                evidence = RunEvidence.load(self.root)
                timing = result.summary.headlines["op_summary"]
                self.assertEqual(timing.observation.value, 12)
                app = result.summary.profile_coverage.model_dump(mode="json", exclude_unset=True)["segments"]["app"]
                self.assertEqual(app["authority_complete"], first == second)
                if first != second:
                    self.assertIsNone(timing.observation.name)
                    self.assertEqual(timing.artifacts[0].launch_counts[0].name, "")
                    conflict = next(issue for issue in timing.artifacts[0].issues if issue.impact == "scope")
                    self.assertEqual((conflict.code, conflict.source.record, conflict.source.column), ("alias_conflict", 2, 1))
                    self.assertIn("equivalent name columns disagree", build_report(evidence.summary(), self.root))

    def test_later_file_is_used_without_claiming_complete_coverage(self):
        self.artifact("Op Name,Task Duration(us)\n")
        self.artifact("Op Name,Task Duration(us)\nkernel,99\n", suffix="002")
        result = write_evidence_model(self.root)
        self.assertEqual(result.summary.headlines["op_summary"].observation.value, 99)
        self.assertFalse(result.summary.profile_coverage.model_dump(mode="json", exclude_unset=True)["segments"]["app"]["authority_complete"])
        self.assertIn("`99`", build_report(result.summary, self.root))

    def test_multiple_files_or_devices_keep_evidence_without_unique_headline(self):
        for devices in (False, True):
            with self.subTest(devices=devices):
                self.artifact("Device_id,Op Name,Task Duration(us)\n0,kernel,12\n" + ("1,kernel,99\n" if devices else ""))
                if not devices:
                    self.artifact("Device_id,Op Name,Task Duration(us)\n0,kernel,99\n", suffix="002")
                result = write_evidence_model(self.root)
                timing = result.summary.headlines["op_summary"]
                self.assertTrue(timing.available)
                self.assertIsNone(timing.observation)
                self.assertEqual(timing.primary.reason, "multiple_scopes")
                report = build_report(result.summary, self.root)
                self.assertIn("calling agent selects", report.lower())
                self.assertNotIn("No finite application timing observation was parsed", report)
                for path in (self.root / "reports").rglob("*.csv"):
                    path.unlink()

    def test_roundtrip_rejects_contradictions_and_strict_numeric_types(self):
        record = self.normalize("Device_id,Op Name,Task Duration(us)\n0,kernel,12\n")
        original = TimingEvidence(group="op_summary", artifacts=(record,), primary=select_primary((record,)))
        payload = original.model_dump(mode="json")
        self.assertEqual(TimingEvidence.model_validate(json.loads(json.dumps(payload))), original)
        for value in ("12", True, float("nan"), 99):
            altered = json.loads(json.dumps(payload))
            altered["artifacts"][0]["observations"][0]["value"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                TimingEvidence.model_validate(altered)
        payload["primary"]["selected"] = None
        with self.assertRaises(ValidationError):
            TimingEvidence.model_validate(payload)
        payload = original.model_dump(mode="json")
        payload["artifacts"][0]["observations"][0]["source"]["record"] = None
        with self.assertRaises(ValidationError):
            TimingEvidence.model_validate(payload)
        payload = original.model_dump(mode="json")
        payload["artifacts"][0]["status"] = "invalid"
        with self.assertRaises(ValidationError):
            TimingEvidence.model_validate(payload)

    def test_separate_units_do_not_override_the_known_header_unit(self):
        record = self.normalize("Op Name,Task Duration(us),Unit\nkernel,12,ms\n")
        self.assertEqual(record.observations, ())
        self.assertEqual(record.issues[0].code, "unsupported_unit_layout")
        self.assertEqual(record.launch_counts[0].count, 1)

    def test_invalid_normalized_summary_is_required_for_report_and_optional_for_assessment(self):
        self.artifact("Op Name,Task Duration(us)\nkernel,12\n")
        result = write_evidence_model(self.root)
        payload = json.loads(result.summary_path.read_text())
        payload["headlines"]["op_summary"]["primary"]["selected"] = None
        result.summary_path.write_text(json.dumps(payload))
        with self.assertRaises(RunEvidenceError):
            RunEvidence.load(self.root)
        optional = RunEvidence.load_assessment(self.root)
        self.assertFalse(optional.summary_present())
        self.assertTrue(any("invalid analysis/summary.json" in warning for warning in optional.warnings()))

    def test_summary_index_composition_rejects_missing_mismatched_and_other_run_sources(self):
        self.artifact("Op Name,Task Duration(us)\nkernel,12\n")
        result = write_evidence_model(self.root)
        index = json.loads(result.raw_artifact_index_path.read_text())
        changes = [{"artifacts": []}]
        for field, value in (("group", "task_time"), ("segment", "op"),
                             ("artifact", "reports/PROF_other/op_summary_001.csv"), ("row_count", 2)):
            changed = copy.deepcopy(index)
            changed["artifacts"][0][field] = value
            changes.append(changed)
        for changed in changes:
            result.raw_artifact_index_path.write_text(json.dumps(changed))
            with self.subTest(index=changed), self.assertRaises(RunEvidenceError):
                RunEvidence.load(self.root)
            self.assertFalse(RunEvidence.load_assessment(self.root).summary_present())
        result.raw_artifact_index_path.unlink()
        evidence = RunEvidence.load(self.root)
        self.assertEqual(evidence.timing_headline_records("op_summary")[0].value, 12)
        self.assertTrue(any("inventory consistency cannot be checked" in warning for warning in evidence.warnings()))

    def test_aggregate_overflow_preserves_observations_and_counts(self):
        for other_name in ("kernel", "other"):
            with self.subTest(other_name=other_name):
                self.artifact(f"Op Name,Task Duration(us)\nkernel,1e308\n{other_name},1e308\n")
                result = write_evidence_model(self.root)
                timing = result.summary.headlines["op_summary"]
                self.assertEqual(timing.observation.value, 1e308)
                self.assertTrue(any(issue.code == "aggregate_overflow" for issue in timing.artifacts[0].issues))
                coverage = result.summary.profile_coverage.model_dump(mode="json", exclude_unset=True)["segments"]["app"]
                self.assertEqual(coverage["observed_total"], 2)
                self.assertTrue(coverage["authority_complete"])
                self.assertIsNone(coverage["duration_total_us"])
                self.assertEqual(RunEvidence.load(self.root).timing_headline_records("op_summary")[0].value, 1e308)

    def test_partial_durations_never_become_complete_totals(self):
        for other_name in ("kernel", "other"):
            for invalid in ("NaN", "", "12,NaN"):
                for reverse in (False, True):
                    with self.subTest(other_name=other_name, invalid=invalid, reverse=reverse):
                        alias = "," in invalid
                        header = "Op Name,Task Duration(us)" + (",Duration(us)" if alias else "")
                        rows = ["kernel,12" + (",12" if alias else ""), f"{other_name},{invalid}"]
                        if reverse:
                            rows.reverse()
                        self.artifact(header + "\n" + "\n".join(rows) + "\n")
                        result = write_evidence_model(self.root)
                        timing = result.summary.headlines["op_summary"]
                        self.assertEqual(timing.observation.value, 12)
                        counts = timing.artifacts[0].launch_counts
                        self.assertEqual(sum(item.count for item in counts), 2)
                        self.assertIsNone(next(item.duration_us for item in counts if item.name == other_name))
                        coverage = result.summary.profile_coverage.model_dump(mode="json", exclude_unset=True)["segments"]["app"]
                        self.assertTrue(coverage["authority_complete"])
                        self.assertEqual(coverage["observed_total"], 2)
                        self.assertIsNone(coverage["duration_total_us"])
                        loaded = RunEvidence.load(self.root)
                        self.assertEqual(loaded.timing_headline_records("op_summary")[0].value, 12)
                        self.assertIn("`12`", build_report(result.summary, self.root))

    def test_source_paths_are_confined_to_the_recorded_run(self):
        record = self.normalize("Op Name,Task Duration(us)\nkernel,12\n")
        payload = record.model_dump(mode="json")
        payload["observations"][0]["source"]["artifact"] = "../another-run/reports/op_summary_001.csv"
        with self.assertRaises(ValidationError):
            type(record).model_validate(payload)

    def test_launch_identity_is_independent_of_column_order_and_operator_type(self):
        for header, row in (
            ("OP Type,Op Name,Task Duration(us)", "Add,my_kernel,12"),
            ("Op Name,OP Type,Task Duration(us)", "my_kernel,Add,12"),
            ("Name,Op Name,Task Duration(us)", "generic,my_kernel,12"),
        ):
            with self.subTest(header=header):
                self.artifact(header + "\n" + row + "\n")
                result = write_evidence_model(self.root)
                timing = result.summary.headlines["op_summary"]
                self.assertEqual(timing.observation.name, "my_kernel")
                self.assertEqual(timing.artifacts[0].launch_counts[0].name, "my_kernel")
                coverage = result.summary.profile_coverage.model_dump(mode="json", exclude_unset=True)["segments"]["app"]
                self.assertEqual(coverage["observed_counts"], {"mykernel": 1})
                self.assertTrue(coverage["authority_complete"])
                self.assertEqual(RunEvidence.load(self.root).timing_headline_records("op_summary")[0].name, "my_kernel")
        self.artifact("OP Type,Task Duration(us)\nAdd,12\n")
        result = write_evidence_model(self.root)
        self.assertIsNone(result.summary.headlines["op_summary"].observation.name)
        self.assertFalse(result.summary.profile_coverage.model_dump(mode="json", exclude_unset=True)["segments"]["app"]["authority_complete"])
        statistic = self.normalize("OP Type,Total Time(us)\nAdd,12\n", "op_statistic")
        self.assertEqual(statistic.observations[0].name, "Add")

    def test_schema_is_generated_from_the_fact_model(self):
        path = Path(__file__).resolve().parents[1] / "skills/ascend-msprof-skill/data/application-timing.schema.json"
        self.assertEqual(json.loads(path.read_text()), TimingEvidence.model_json_schema())

    def test_json_rejects_duplicate_keys_and_nonstandard_constants(self):
        path = self.root / "input.json"
        for value in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
            path.write_text(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                read_json(path)

    def test_profiler_csv_is_decoded_once_and_reports_do_not_reopen_it(self):
        path = self.artifact("Op Name,Task Duration(us)\nkernel,12\n")
        opened = []
        original = Path.open
        def track(file, *args, **kwargs):
            if file == path:
                opened.append(file)
            return original(file, *args, **kwargs)
        with mock.patch.object(Path, "open", track):
            result = write_evidence_model(self.root)
            build_report(result.summary, self.root)
            RunEvidence.load(self.root).headline_records()
        self.assertEqual(opened, [path])
