"""Headline comparison behavior through analyzed run inputs."""

import copy
import csv
import json
import sys
import tempfile
import shutil
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ascend_msprof_skill.provenance_types import Provenance
from ascend_msprof_skill.compare_runs import build_comparison, render_markdown  # noqa: E402


def pipe_row(comparison):
    return next(row for row in comparison["mechanism_assessment"]["headlines"] if row["group"] == "pipe_utilization")


from pydantic import ValidationError
from ascend_msprof_skill.assessment_types import ComparisonSummary

class HeadlineComparisonTests(unittest.TestCase):
    def test_metric_order_changes_do_not_change_comparison_selection(self):
        from ascend_msprof_skill.evidence_model import write_evidence_model
        from ascend_msprof_skill.summarize_candidate import build_candidate_summary, render_markdown as render_candidate
        from ascend_msprof_skill.run_evidence import RunEvidence
        for run, values in ((self.baseline, (0.9, 0.2)), (self.candidate, (0.1, 0.8))):
            path = run / "reports/op/OPPROF_001/PipeUtilization.csv"
            path.write_text("block_id,sub_block_id,aic_mte2_ratio,aic_scalar_ratio\n"
                            f"255,cube0,{values[0]},{values[1]}\n")
            summary = write_evidence_model(run).summary
            selection = summary.headlines['pipe_utilization'].primary
            self.assertIsNone(selection.selected)
            self.assertEqual({source.field for source in selection.candidates}, {'aic_mte2_ratio', 'aic_scalar_ratio'})
        result = self.comparison()
        rows = [row for row in result['mechanism_assessment']['headlines'] if row['group'] == 'pipe_utilization']
        self.assertEqual({row['a']['field'] for row in rows}, {'aic_mte2_ratio', 'aic_scalar_ratio'})
        self.assertTrue(all(row['numeric'] and row['a']['field'] == row['b']['field'] for row in rows))
        deltas = {row['a']['field']: row['delta'] for row in rows}
        self.assertAlmostEqual(deltas['aic_mte2_ratio'], -0.8)
        self.assertAlmostEqual(deltas['aic_scalar_ratio'], 0.6)
        candidate = build_candidate_summary(self.candidate)
        metrics = [row.candidate for row in candidate.mechanism_assessment.headlines if row.group == 'pipe_utilization']
        self.assertEqual(len(metrics), 2)
        self.assertTrue(all(item.scope == {'block_id': '255', 'sub_block_id': 'cube0'} for item in metrics))
        report = render_candidate(candidate)
        self.assertIn('block_id=255', report)
        self.assertIn('aggregation=maximum_observed_cell', report)
        self.assertIsNone(RunEvidence.load(self.candidate).primary_headline())

    def test_multiple_launches_are_preserved_without_arbitrary_pairing(self):
        from ascend_msprof_skill.evidence_model import write_evidence_model
        path = self.candidate / 'reports/op/OPPROF_002/PipeUtilization.csv'
        path.parent.mkdir(parents=True)
        path.write_text('block_id,sub_block_id,aic_mte2_ratio\n0,cube0,0.2\n')
        write_evidence_model(self.candidate)
        rows = [row for row in self.comparison()['mechanism_assessment']['headlines'] if row['group'] == 'pipe_utilization']
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(not row['numeric'] and 'metric scope ambiguous' in row['comparison_reasons'] for row in rows))

    def test_unverified_single_run_keeps_values_without_admitted_findings(self):
        from ascend_msprof_skill.evidence_model import write_evidence_model
        from ascend_msprof_skill.summarize_candidate import build_candidate_summary
        context_path = self.candidate / 'analysis/profile_context.json'
        context = json.loads(context_path.read_text())
        context.pop('expected_kernel_names')
        context_path.write_text(json.dumps(context))
        write_evidence_model(self.candidate)
        mechanism = build_candidate_summary(self.candidate).mechanism_assessment
        row = next(row for row in mechanism.headlines if row.group == 'pipe_utilization')
        self.assertEqual(row.status, 'unassessed')
        self.assertEqual(row.candidate.value, 0.9)
        self.assertIn('record=2', row.candidate.field_ref)
        self.assertIn('target unverified', row.comparison_reasons)
        self.assertFalse(row.numeric)
        self.assertFalse(any(finding.group == 'pipe_utilization' for finding in mechanism.findings))
        forged = row.model_dump(mode='json')
        forged['status'] = 'observed'
        forged['comparison_reasons'] = []
        from ascend_msprof_skill.assessment_types import HeadlineComparison
        with self.assertRaises(ValidationError):
            HeadlineComparison.model_validate(forged)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.baseline = Path(temporary.name) / "baseline"
        self.candidate = Path(temporary.name) / "candidate"
        self.case = {
            "analysis_schema_version": "5.1",
            "target_identity": {"status": "match", "expected": {"names": ["kernel"]}},
            "metric_scope": {"value": "PipeUtilization", "artifact": "logs/command.txt"},
            "metrics": {
                "pipe_utilization": {
                    "name": "cube0", "value": 0.9, "field": "aic_mte2_ratio",
                    "field_kind": "utilization_or_ratio", "segment": "op",
                    "metric_scope": "PipeUtilization",
                    "file": "reports/op/OPPROF_001/PipeUtilization.csv",
                    "row": {"block_id": "0", "sub_block_id": "cube0", "aic_mte2_ratio": "0.9"},
                },
            },
        }
        from ascend_msprof_skill.generate_provenance import build_manifest
        logs = self.baseline / "logs"
        logs.mkdir(parents=True)
        (logs / "cann_version.cfg").write_text("toolkit_running_version=[8.3.RC2]\n")
        (logs / "npu_smi_info.stdout").write_text("| 0 910B2 | OK |\n")
        (logs / "command_msprof.txt").write_text("msprof op --aic-metrics=PipeUtilization --output=reports/op\n")
        self.workload = {"id": "add", "shape": [128, 256], "dtype": "float32", "case_count": 1}
        for run_dir in (self.baseline, self.candidate):
            (run_dir / "analysis").mkdir(parents=True)
            self.write_case(run_dir, self.case)
            if run_dir == self.baseline:
                self.provenance = build_manifest(run_dir).model_dump(mode="json", exclude_unset=True)
            (run_dir / "analysis" / "provenance.json").write_text(json.dumps(self.provenance))
            self.write_workload(run_dir, self.workload)

    def write_workload(self, run_dir, workload, artifact="profile_context.json"):
        path = run_dir / "analysis" / artifact
        context = json.loads(path.read_text()) if path.exists() else {}
        context["benchmark"] = {"workload": workload}
        path.write_text(json.dumps(context))

    def test_workload_mismatch_missing_and_conflict_block_deltas(self):
        for field, changed in {"id": "other", "shape": [256, 256], "dtype": "float16", "case_count": 2}.items():
            for status in ("mismatch", "missing", "conflict"):
                with self.subTest(field=field, status=status):
                    workload = dict(self.workload)
                    workload[field] = changed
                    if status == "missing":
                        del workload[field]
                    self.write_workload(self.candidate, workload)
                    tile = self.candidate / "analysis" / "tilelang_context.json"
                    if status == "conflict":
                        self.write_workload(self.candidate, self.workload, tile.name)
                    row = pipe_row(self.comparison())
                    self.assertIn(f"workload.{field} {status}", row["comparison_reasons"])
                    self.assertFalse(row["numeric"])
                    self.assertIsNone(row["delta"])
                    tile.unlink(missing_ok=True)
        for run_dir in (self.baseline, self.candidate):
            self.write_workload(run_dir, {})
        self.assertIn("workload.shape missing", pipe_row(self.comparison())["comparison_reasons"])

    def test_loaded_comparison_rejects_numeric_findings_with_common_blockers(self):
        original = self.comparison()
        self.assertTrue(pipe_row(original)['numeric'])
        for kind in ('workload', 'cann_version', 'hardware_summary'):
            payload = copy.deepcopy(original)
            mechanism = payload['mechanism_assessment']
            if kind == 'workload':
                mechanism['workload_checks'][0].update(status='mismatch', b='different-workload')
                for observation in mechanism['workload_checks'][0]['sources']['b']:
                    observation['value'] = 'different-workload'
            else:
                check = next(item for item in mechanism['compatibility']['checks'] if item['id'] == kind)
                check['status'] = 'mismatch'
                check['b']['value'] = 'different-environment'
                mechanism['compatibility']['status'] = 'warning'
            with self.subTest(kind=kind), self.assertRaisesRegex(ValidationError, 'numeric mechanism comparison'):
                ComparisonSummary.model_validate(payload)

    def test_loaded_compatibility_status_must_agree_with_its_checks(self):
        self.write_workload(self.candidate, self.workload)
        original = self.comparison()
        payload = copy.deepcopy(original)
        compatibility = payload['mechanism_assessment']['compatibility']
        compatibility['status'] = 'warning' if compatibility['status'] != 'warning' else 'compatible'
        with self.assertRaisesRegex(ValidationError, 'compatibility status disagrees'):
            ComparisonSummary.model_validate(payload)

    def test_workload_sources_are_shared_with_candidate_mechanism(self):
        from ascend_msprof_skill.summarize_candidate import build_candidate_summary
        self.write_workload(self.candidate, self.workload, "tilelang_context.json")
        comparison = self.comparison()
        checks = comparison["mechanism_assessment"]["workload_checks"]
        self.assertTrue(pipe_row(comparison)["numeric"])
        self.assertEqual(len(checks[0]["sources"]["b"]), 2)
        self.assertEqual(checks[0]["sources"]["b"][0]["source"]["field_ref"], "benchmark.workload.id")
        candidate = build_candidate_summary(self.candidate, self.baseline).model_dump(mode="json")
        self.assertEqual(checks, candidate["mechanism_assessment"]["workload_checks"])

    def test_version_comparison_requires_matching_components(self):
        for field, artifact, expected in (
            ("runtime_running_version", "logs/cann_version.cfg", "component_mismatch"),
            ("version", "logs/toolkit_install.info", "match"),
            (None, None, "missing"),
        ):
            with self.subTest(field=field):
                provenance = copy.deepcopy(self.provenance)
                if artifact is None:
                    provenance.pop("cann_version")
                else:
                    source = {"artifact": artifact, "field": field}
                    provenance["cann_version"]["source"] = source
                    provenance["cann_version"]["evidence"][0]["source"] = source
                (self.candidate / "analysis/provenance.json").write_text(json.dumps(provenance))
                comparison = self.comparison()
                self.assertEqual(comparison["mechanism_assessment"]["compatibility"]["checks"][0]["status"], expected)
                self.assertEqual(comparison["mechanism_assessment"]["compatibility"]["checks"][0]["status"], expected)
                self.assertEqual(pipe_row(comparison)["numeric"], expected == "match")

    def test_version_comparison_uses_shared_toolkit_evidence(self):
        from ascend_msprof_skill.generate_provenance import build_manifest, write_manifest

        for run_dir in (self.baseline, self.candidate):
            logs = run_dir / "logs"
            logs.mkdir(exist_ok=True)
            (logs / "toolkit_install.info").write_text("package_name=Ascend-cann-toolkit\nversion=8.5.2\n")
        for runtime_run in (self.baseline, self.candidate):
            with self.subTest(runtime_run=runtime_run.name):
                for run_dir in (self.baseline, self.candidate):
                    (run_dir / "logs/cann_version.cfg").unlink(missing_ok=True)
                cfg = runtime_run / "logs/cann_version.cfg"
                cfg.write_text("runtime_running_version=[8.5.2]\n")
                for run_dir in (self.baseline, self.candidate):
                    write_manifest(run_dir, Provenance.model_validate({**self.provenance, "cann_version": build_manifest(run_dir).cann_version}))
                comparison = self.comparison()
                check = comparison["mechanism_assessment"]["compatibility"]["checks"][0]
                self.assertEqual(check["status"], "match")
                for role in ("a", "b"):
                    self.assertEqual(check[role]["source"], {"artifact": "logs/toolkit_install.info", "field": "version", "record": None, "column": None})
                self.assertEqual(comparison["mechanism_assessment"]["compatibility"]["checks"][0]["status"], "match")
                self.assertTrue(pipe_row(comparison)["numeric"])

                cfg.write_text("runtime_running_version=[8.6.0]\n")
                write_manifest(runtime_run, Provenance.model_validate({**self.provenance, "cann_version": build_manifest(runtime_run).cann_version}))
                conflict = self.comparison()
                self.assertEqual(conflict["mechanism_assessment"]["compatibility"]["checks"][0]["status"], "conflict")
                self.assertFalse(pipe_row(conflict)["numeric"])
                cfg.unlink()

    def test_extra_toolkit_evidence_preserves_shared_component_comparison(self):
        from ascend_msprof_skill.generate_provenance import build_manifest, write_manifest

        for component in ("runtime", "compiler", "opp"):
            for extra_roles in ((), ("a",), ("b",), ("a", "b")):
                for candidate_version, expected in (("8.5.2", "match"), ("8.6.0", "mismatch")):
                    with self.subTest(component=component, extra_roles=extra_roles, candidate_version=candidate_version):
                        for role, run_dir, version in (("a", self.baseline, "8.5.2"), ("b", self.candidate, candidate_version)):
                            logs = run_dir / "logs"
                            logs.mkdir(exist_ok=True)
                            (logs / "cann_version.cfg").write_text(f"{component}_running_version=[{version}]\n")
                            info = logs / "toolkit_install.info"
                            if role in extra_roles:
                                info.write_text(f"package_name=Ascend-cann-toolkit\nversion={version}\n")
                            else:
                                info.unlink(missing_ok=True)
                            write_manifest(run_dir, Provenance.model_validate({**self.provenance, "cann_version": build_manifest(run_dir).cann_version}))
                        comparison = self.comparison()
                        check = comparison["mechanism_assessment"]["compatibility"]["checks"][0]
                        self.assertEqual(check["status"], expected)
                        source = {"artifact": "logs/toolkit_install.info", "field": "version"} if len(extra_roles) == 2 else {
                            "artifact": "logs/cann_version.cfg", "field": f"{component}_running_version",
                        }
                        for role in ("a", "b"):
                            self.assertEqual(check[role]["source"], {**source, "record": None, "column": None})
                        self.assertEqual(comparison["mechanism_assessment"]["compatibility"]["checks"][0]["status"], expected)
                        self.assertEqual(pipe_row(comparison)["numeric"], expected == "match")

    def test_real_pair_offline_replay_and_synthetic_schema_boundaries(self):
        from ascend_msprof_skill.generate_provenance import build_manifest, write_manifest
        from ascend_msprof_skill.evidence_model import write_evidence_model
        fixture = Path(__file__).parent / "fixtures/real_cann852_workload_pair"
        for name, run_dir in (("shape-128", self.baseline), ("shape-256", self.candidate)):
            shutil.copytree(fixture / name, run_dir, dirs_exist_ok=True)
            write_manifest(run_dir, build_manifest(run_dir))
            # Validate stored evidence before reanalysis can replace it.
            stored = json.loads((run_dir / "analysis/summary.json").read_text())
            for item in stored["headlines"].values():
                for artifact in item["artifacts"]:
                    with (run_dir / artifact["artifact"]).open() as stream:
                        rows = list(csv.reader(stream))
                    for observation in artifact["observations"]:
                        source = observation["source"]
                        self.assertEqual(rows[source["record"] - 1][source["column"] - 1], observation["raw_token"])
            # Stored 5.0 projections retain their raw references; regenerate
            # the derived selection contract before assessing with 5.1.
            write_evidence_model(run_dir)
            self.assertTrue(any(row["numeric"] for row in build_comparison(run_dir, run_dir).model_dump(mode="json")["mechanism_assessment"]["headlines"]))
        comparison = self.comparison()
        expected = {"arithmetic_utilization", "l2_cache", "memory", "resource_conflict"}
        for row in comparison["mechanism_assessment"]["headlines"]:
            if row["group"] in expected:
                self.assertIn("workload.shape mismatch", row["comparison_reasons"])
                self.assertNotIn("profiler.cann_version missing", row["comparison_reasons"])
                self.assertFalse(row["numeric"])
        control = build_comparison(self.baseline, self.baseline).model_dump(mode="json")
        # OpBasicInfo belongs to separate op and follow-up collections: no single duration delta.
        self.assertEqual(next(row for row in control["mechanism_assessment"]["headlines"] if row["group"] == "op_basic_info")["comparison_reasons"], ["metric scope ambiguous"])
        self.assertTrue(expected <= {r["group"] for r in control["mechanism_assessment"]["headlines"] if r["numeric"]})
        self.assertIn("workload.shape mismatch", render_markdown(ComparisonSummary.model_validate(comparison)))
        (self.baseline / "logs/toolkit_install.info").unlink()
        write_manifest(self.baseline, build_manifest(self.baseline))
        missing_version = next(r for r in self.comparison()["mechanism_assessment"]["headlines"] if r["group"] == "memory")
        self.assertIn("profiler.cann_version missing", missing_version["comparison_reasons"])

        # Synthetic mutations of a real CSV, always restore the valid version gate.
        shutil.copyfile(fixture / "shape-128/logs/toolkit_install.info", self.baseline / "logs/toolkit_install.info")
        write_manifest(self.baseline, build_manifest(self.baseline))
        path = next((self.baseline / "reports").rglob("Memory.csv"))
        original = path.read_text()
        for field, reason in (("Unit", "unsupported unit layout"), ("Units", "unsupported unit layout"), ("Unknown Bandwidth", "unsupported metric field")):
            with self.subTest(synthetic=field):
                lines = original.splitlines()
                if field in ("Unit", "Units"):
                    changed = "\n".join(line + ("," + field if i == 0 else ",GB/s") for i, line in enumerate(lines)) + "\n"
                else:
                    # Make the unfamiliar field the selected maximum without changing its value.
                    changed = original.replace("GM_to_UB_bw_usage_rate(%)", "Unknown Bandwidth usage rate")
                path.write_text(changed)
                write_evidence_model(self.baseline)
                row = next(r for r in build_comparison(self.baseline, self.baseline).model_dump(mode="json")["mechanism_assessment"]["headlines"] if r["group"] == "memory")
                from ascend_msprof_skill.run_evidence import RunEvidence
                artifacts = RunEvidence.load(self.baseline).summary().headlines["memory"].artifacts
                changed_artifact = next(item for item in artifacts if item.artifact.endswith("Memory.csv"))
                if field in ("Unit", "Units"):
                    self.assertFalse(changed_artifact.observations)
                    self.assertIn("unsupported_unit_layout", {issue.code for issue in changed_artifact.issues})
                else:
                    self.assertNotIn("Unknown Bandwidth usage rate", {item.metric for item in changed_artifact.observations})
                    self.assertIn("Unknown Bandwidth usage rate", changed_artifact.columns)
        path.write_text(original)

    def write_case(self, run_dir, case):
        """Produce a complete normalized summary from this test's raw inputs."""
        from ascend_msprof_skill.evidence_model import write_evidence_model
        shutil.rmtree(run_dir / "reports", ignore_errors=True)
        for group, item in case.get("metrics", {}).items():
            if item is None:
                continue
            artifact = item["file"]
            segment = item.get("segment", "op")
            if segment.startswith("followup:"):
                artifact = artifact.replace("reports/op/", "reports/followups/" + segment.removeprefix("followup:") + "/")
            path = run_dir / artifact
            path.parent.mkdir(parents=True, exist_ok=True)
            row = dict(item.get("row") or {})
            field = item.get("field") or "unknown"
            row.pop("aic_mte2_ratio", None)
            row[field] = item.get("value")
            with path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
        identity_spec = case.get("target_identity", {})
        names = identity_spec.get("expected", {}).get("names", ["kernel"])
        basic_path = run_dir / "reports/op/OPPROF_001/OpBasicInfo.csv"
        basic_path.parent.mkdir(parents=True, exist_ok=True)
        basic_path.write_text(f"Op Name\n{names[0]}\n")
        context_path = run_dir / "analysis/profile_context.json"
        context = json.loads(context_path.read_text()) if context_path.exists() else {}
        context.pop("expected_kernel_names", None)
        if identity_spec.get("status") != "unverified":
            context["expected_kernel_names"] = names
        context_path.write_text(json.dumps(context))
        logs = run_dir / "logs"
        logs.mkdir(exist_ok=True)
        metric = next((item for item in case.get("metrics", {}).values() if item is not None), {})
        scope = metric.get("metric_scope", case.get("metric_scope", {}).get("value"))
        command = logs / "command_msprof_op.txt"
        if scope is None:
            command.unlink(missing_ok=True)
        else:
            command.write_text(f"msprof op --aic-metrics={scope}\n")
        write_evidence_model(run_dir)

    def test_persisted_compatibility_checks_reject_changed_values_and_components(self):
        for field, value in (('value', '99.0'), ('source', {'artifact': 'logs/version.cfg', 'field': 'runtime_running_version'})):
            with self.subTest(field=field):
                data = self.comparison()
                check = next(check for check in data['mechanism_assessment']['compatibility']['checks'] if check['id'] == 'cann_version')
                check['b'][field] = value
                with self.assertRaises(ValidationError):
                    ComparisonSummary.model_validate(data)

    def test_persisted_headline_status_requires_corresponding_observations(self):
        from ascend_msprof_skill.assessment_types import HeadlineComparison
        for status in ('same', 'changed', 'missing', 'not_comparable', 'observed'):
            with self.subTest(status=status), self.assertRaises(ValidationError):
                HeadlineComparison(group='pipe_utilization', status=status)
        row = pipe_row(self.comparison())
        for changes in ({'numeric': False, 'delta': None, 'delta_pct': None}, {'status': 'missing'}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                HeadlineComparison.model_validate({**row, **changes})

    def comparison(self):
        return build_comparison(self.baseline, self.candidate).model_dump(mode="json")

    def test_different_metrics_keep_values_without_delta(self):
        candidate = copy.deepcopy(self.case)
        candidate["metrics"]["pipe_utilization"].update(field="aiv_vec_ratio", value=0.8)
        self.write_case(self.candidate, candidate)
        comparison = self.comparison()
        rows = [row for row in comparison["mechanism_assessment"]["headlines"] if row["group"] == "pipe_utilization"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["status"] == "missing" and not row["numeric"] for row in rows))
        self.assertEqual({side["value"] for row in rows for side in (row["a"], row["b"]) if side["present"]}, {0.9, 0.8})
        report = render_markdown(ComparisonSummary.model_validate(comparison))
        self.assertIn("aic_mte2_ratio", report)
        self.assertIn("aiv_vec_ratio", report)
        self.assertIn("matching metric missing", report)
        self.assertNotIn("-11.1111", report)

    def test_target_and_block_context_must_match(self):
        cases = [
            ("target unverified", "identity", {"status": "unverified", "expected": {"names": ["kernel"]}}),
            ("target mismatch", "identity", {"status": "match", "expected": {"names": ["other_kernel"]}}),
            ("target ambiguous", "identity", {"status": "match", "expected": {"names": ["kernel", "other_kernel"]}}),
            ("block_scope mismatch", "row", {"block_id": "1", "sub_block_id": "cube0"}),
            ("block_scope mismatch", "row", {"block_id": "0", "sub_block_id": "vector0"}),
            ("block_scope mismatch", "row", {"sub_block_id": "cube0"}),
        ]
        for reason, kind, value in cases:
            with self.subTest(reason=reason, value=value):
                candidate = copy.deepcopy(self.case)
                if kind == "identity":
                    candidate["target_identity"] = value
                else:
                    candidate["metrics"]["pipe_utilization"]["row"] = value
                self.write_case(self.candidate, candidate)
                row = pipe_row(self.comparison())
                self.assertEqual(row["status"], "missing" if reason == "matching metric missing" else "not_comparable")
                self.assertIn(reason, row["comparison_reasons"])
                self.assertIsNone(row["delta"])

    def test_empty_block_identifiers_withhold_delta(self):
        for field in ("block_id", "sub_block_id"):
            for value in ("", None):
                with self.subTest(field=field, value=value):
                    baseline = copy.deepcopy(self.case)
                    baseline["metrics"]["pipe_utilization"]["row"][field] = value
                    candidate = copy.deepcopy(baseline)
                    candidate["metrics"]["pipe_utilization"]["value"] = 0.8
                    self.write_case(self.baseline, baseline)
                    self.write_case(self.candidate, candidate)
                    row = pipe_row(self.comparison())
                    self.assertEqual(row["status"], "not_comparable")
                    self.assertFalse(row["numeric"])
                    self.assertIsNone(row["delta"])
                    self.assertIsNone(row["delta_pct"])
                    self.assertIn("block_scope missing", row["comparison_reasons"])
                    self.assertEqual(row["a"]["value"], 0.9)
                    self.assertEqual(row["b"]["value"], 0.8)

    def test_zero_identifiers_and_absent_block_columns_allow_delta(self):
        for raw_row in ({"block_id": 0, "sub_block_id": 0}, {"aic_mte2_ratio": "0.9"}):
            with self.subTest(raw_row=raw_row):
                baseline = copy.deepcopy(self.case)
                baseline["metrics"]["pipe_utilization"]["row"] = raw_row
                candidate = copy.deepcopy(baseline)
                candidate["metrics"]["pipe_utilization"]["value"] = 0.8
                self.write_case(self.baseline, baseline)
                self.write_case(self.candidate, candidate)
                row = pipe_row(self.comparison())
                if "sub_block_id" not in raw_row:
                    self.assertFalse(row["numeric"])
                    self.assertIn("name missing", row["comparison_reasons"])
                    continue
                self.assertEqual(row["status"], "changed")
                self.assertTrue(row["numeric"])
                self.assertEqual(row["comparison_reasons"], [])
                self.assertAlmostEqual(row["delta"], -0.1)

    def test_profiler_compatibility_is_required_only_for_headline_deltas(self):
        original = self.comparison()
        provenance = copy.deepcopy(self.provenance)
        provenance["cann_version"]["value"] = "9.0"
        provenance["cann_version"]["evidence"][0]["value"] = "9.0"
        (self.candidate / "analysis" / "provenance.json").write_text(json.dumps(provenance))
        comparison = self.comparison()
        row = pipe_row(comparison)
        self.assertEqual(comparison["mechanism_assessment"]["compatibility"]["status"], "warning")
        self.assertEqual(comparison["performance_assessment"], original["performance_assessment"])
        self.assertEqual(row["status"], "not_comparable")
        self.assertIn("profiler.cann_version mismatch", row["comparison_reasons"])
        self.assertIsNone(row["delta"])

    def test_matching_metric_compares_values_and_handles_zero_baseline(self):
        candidate = copy.deepcopy(self.case)
        candidate["metrics"]["pipe_utilization"]["value"] = 0.8
        self.write_case(self.candidate, candidate)
        row = pipe_row(self.comparison())
        self.assertEqual(row["status"], "changed")
        self.assertTrue(row["numeric"])
        self.assertEqual(row["comparison_reasons"], [])
        self.assertAlmostEqual(row["delta"], -0.1)
        self.assertAlmostEqual(row["delta_pct"], -11.1111111111)
        self.case["metrics"]["pipe_utilization"]["value"] = 0.0
        self.write_case(self.baseline, self.case)
        row = pipe_row(self.comparison())
        self.assertEqual(row["delta"], 0.8)
        self.assertIsNone(row["delta_pct"])
        self.write_case(self.candidate, self.case)
        self.assertEqual(pipe_row(self.comparison())["status"], "same")

    def test_changed_or_missing_metric_context_blocks_delta(self):
        for field, value, reason in [
            ("field", "aiv_vec_ratio", "matching metric missing"),
            ("field", None, "matching metric missing"),
            ("row", {"block_id": "0", "sub_block_id": "vector0"}, "name mismatch"),
            ("segment", "followup:collect_default_metric_followup", "segment mismatch"),
            ("metric_scope", "Default", "metric_scope mismatch"),
            ("metric_scope", None, "metric_scope missing"),
            ("row", None, "block_scope missing"),
            ("value", None, "matching metric missing"),
        ]:
            with self.subTest(field=field, value=value):
                candidate = copy.deepcopy(self.case)
                candidate["metrics"]["pipe_utilization"][field] = value
                self.write_case(self.candidate, candidate)
                row = pipe_row(self.comparison())
                self.assertEqual(row["status"], "missing" if reason == "matching metric missing" else "not_comparable")
                self.assertIn(reason, row["comparison_reasons"])
                self.assertIsNone(row["delta"])
                self.assertIsNone(row["delta_pct"])

    def test_missing_headline_remains_missing(self):
        candidate = copy.deepcopy(self.case)
        candidate["metrics"] = {}
        self.write_case(self.candidate, candidate)
        row = pipe_row(self.comparison())
        self.assertEqual(row["status"], "missing")
        self.assertEqual(row["a"]["value"], 0.9)
        self.assertFalse(row["numeric"])
        self.assertIsNone(row["delta"])

    def test_inconsistent_segment_identity_is_rejected(self):
        from ascend_msprof_skill.run_evidence import RunEvidence, RunEvidenceError
        path = self.candidate / "analysis/summary.json"
        summary = json.loads(path.read_text())
        identity = copy.deepcopy(summary["target_identity"])
        summary["target_identity"]["segments"] = {"op": identity}
        path.write_text(json.dumps(summary))
        with self.assertRaisesRegex(RunEvidenceError, "segment identity requires a declared target"):
            RunEvidence.load(self.candidate)

    def test_missing_profiler_context_withholds_delta(self):
        (self.candidate / "analysis" / "provenance.json").unlink()
        row = pipe_row(self.comparison())
        self.assertEqual(row["status"], "not_comparable")
        self.assertIn("profiler.cann_version missing", row["comparison_reasons"])
        self.assertIsNone(row["delta"])
