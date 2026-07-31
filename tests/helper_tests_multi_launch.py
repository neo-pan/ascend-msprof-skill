"""Declared multi-launch collection and coverage tests."""

from tests.helpers_shared import *  # noqa: F401,F403

from ascend_msprof_skill import _profile_target


def declared_target(*launches, selector="kernel_*"):
    return _profile_target.normalize_target_contract(
        {
            "target": {
                "kernel_selector": selector,
                "expected_launches": [
                    {"name": name, "count": count} for name, count in launches
                ],
            }
        }
    )


def write_declared_target(run_dir: Path, target: dict) -> None:
    analysis = run_dir / "analysis"
    logs = run_dir / "logs"
    analysis.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    (analysis / "profile_harness_run.json").write_text(
        json.dumps({"target_selection": target}), encoding="utf-8"
    )
    (logs / "command_msprof_op.txt").write_text(
        "msprof op --aic-metrics=PipeUtilization\n", encoding="utf-8"
    )


def write_app_launches(run_dir: Path, names: list[str], *, duplicate_summary: bool = False) -> None:
    root = run_dir / "reports" / "app" / "PROF_001" / "mindstudio_profiler_output"
    root.mkdir(parents=True, exist_ok=True)
    rows = "".join(f"{name},{10 + index},99\n" for index, name in enumerate(names))
    content = "Op Name,Task Duration(us),Calls\n" + rows
    (root / "op_summary_001.csv").write_text(content, encoding="utf-8")
    if duplicate_summary:
        (root / "op_summary_002.csv").write_text(content, encoding="utf-8")


def write_operator_launch(
    run_dir: Path,
    name: str,
    ordinal: int,
    *,
    segment: str = "op",
    families=("pipe_utilization",),
    timestamped: bool = True,
) -> Path:
    if segment == "op":
        base = run_dir / "reports" / "op"
    else:
        base = run_dir / "reports" / "followups" / segment.removeprefix("followup:")
    launch = base / "OPPROF_001" / name / f"{ordinal:03d}"
    launch.mkdir(parents=True, exist_ok=True)
    suffix = "_20260730130344937" if timestamped else ""
    (launch / f"OpBasicInfo{suffix}.csv").write_text(
        f"Op Name,Task Duration(us),Block Dim\n{name},{20 + ordinal},8\n",
        encoding="utf-8",
    )
    stems = {
        "pipe_utilization": ("PipeUtilization",),
        "arithmetic_utilization": ("ArithmeticUtilization",),
        "l2_cache": ("L2Cache",),
        "memory": ("Memory", "MemoryL0", "MemoryUB"),
        "resource_conflict": ("ResourceConflictRatio",),
    }
    for family in families:
        for stem in stems[family]:
            (launch / f"{stem}{suffix}.csv").write_text(
                "Metric,Utilization(%)\nmetric,50\n", encoding="utf-8"
            )
    return launch


class MultiLaunchHelperTests(unittest.TestCase):
    def test_target_contract_drives_op_and_default_commands(self):
        target = declared_target(("kernel_a", 1), ("kernel_b", 4), selector="kernel_*")
        run_dir = Path("/tmp/profile/multi")
        application = Path("/tmp/run_application.sh")

        for command in [
            profile_harness_module.msprof_op_command(run_dir, application, target),
            profile_harness_module.msprof_default_followup_command(run_dir, application, target),
        ]:
            self.assertIn("--kernel-name=kernel_*", command)
            self.assertIn("--launch-count=5", command)
            self.assertIn("--warm-up=0", command)
            self.assertIn("--replay-mode=application", command)
        legacy = profile_harness_module.msprof_op_command(run_dir, application)
        self.assertFalse(any(item.startswith("--kernel-name=") for item in legacy))
        self.assertFalse(any(item.startswith("--launch-count=") for item in legacy))

        single = profile_harness_module.msprof_op_command(
            run_dir,
            application,
            declared_target(("kernel_a", 1), selector="kernel_a"),
        )
        self.assertIn("--kernel-name=kernel_a", single)
        self.assertIn("--launch-count=1", single)

    def test_invalid_target_contracts_fail_with_actionable_errors(self):
        invalid_targets = [
            ({}, "kernel_selector"),
            ({"kernel_selector": "x", "expected_launches": []}, "non-empty list"),
            ({"kernel_selector": "x", "expected_launches": [{"name": "", "count": 1}]}, ".name"),
            ({"kernel_selector": "x", "expected_launches": [{"name": "x", "count": 0}]}, "positive integer"),
            ({"kernel_selector": "x", "expected_launches": [{"name": "x", "count": True}]}, "positive integer"),
            (
                {"kernel_selector": "x", "expected_launches": [{"name": "a-b", "count": 1}, {"name": "ab", "count": 1}]},
                "unique after normalization",
            ),
            (
                {"kernel_selector": "x", "expected_launches": [{"name": "---", "count": 1}]},
                "must contain letters or digits",
            ),
            (
                {"kernel_selector": "x", "expected_launches": [{"name": "x", "count": 1}], "launch_count": 1},
                "accepts only",
            ),
            (
                {"kernel_selector": "x", "expected_launches": [{"name": "x", "count": 1, "role": "main"}]},
                "accepts only",
            ),
        ]
        for target, message in invalid_targets:
            with self.subTest(target=target):
                with self.assertRaisesRegex(ValueError, message):
                    _profile_target.normalize_target_contract({"target": target})

    def test_overlapping_target_names_choose_the_most_specific_suffix_match(self):
        for launches in [
            (("foo", 1), ("foo_mix", 1)),
            (("foo_mix", 1), ("foo", 1)),
        ]:
            with self.subTest(launches=launches):
                target = declared_target(*launches, selector="foo*")
                self.assertEqual(
                    _profile_target.match_expected_name(target, "foo_mix_aic"),
                    ("foomix", "known_suffix"),
                )

    def test_continue_mode_reuses_persisted_target_without_new_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            application = Path(tmp) / "run_application.sh"
            application.write_text("#!/bin/sh\n", encoding="utf-8")
            target = declared_target(("kernel_a", 2), selector="kernel_*")
            analysis = run_dir / "analysis"
            analysis.mkdir(parents=True)
            (analysis / "profile_harness_run.json").write_text(
                json.dumps(
                    {
                        "inputs": {"application_resolved_path": str(application)},
                        "target_selection": target,
                    }
                ),
                encoding="utf-8",
            )
            (analysis / "summary.json").write_text(
                json.dumps(
                    {
                        "target_identity": {"status": "match"},
                        "next_collection_actions": [
                            {"id": "collect_default_metric_followup", "reason": "complete target metrics"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            runner = RecordingCommandRunner(returncode=0)
            with mock.patch.object(profile_harness_module, "run_profile_harness_analysis") as rerun:
                result = profile_harness_module._run_continue_followups_workflow(
                    profile_harness_module.ContinueFollowupsRequest(run_dir=run_dir),
                    runner=runner,
                )

            self.assertTrue(result.analysis_reran)
            rerun.assert_called_once_with(run_dir.resolve())
            command = runner.calls[0]["command"]
            self.assertIn("--kernel-name=kernel_*", command)
            self.assertIn("--launch-count=2", command)
            persisted = json.loads((analysis / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["target_selection"], target)

    def test_timestamped_15_launch_artifacts_are_all_indexed_and_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "multi"
            target = declared_target(("kernel_a", 15))
            write_declared_target(run_dir, target)
            write_app_launches(run_dir, ["kernel_a"] * 15)
            for ordinal in range(15):
                write_operator_launch(
                    run_dir,
                    "kernel_a",
                    ordinal,
                    families=("pipe_utilization", "arithmetic_utilization"),
                )

            summary, raw_index = evidence_model.build_evidence_model(run_dir)

            operator_records = [
                item
                for item in raw_index["artifacts"]
                if item.get("group") in {"op_basic_info", "pipe_utilization", "arithmetic_utilization"}
            ]
            self.assertEqual(len(operator_records), 45)
            self.assertTrue(all(item.get("launch_key") for item in operator_records))
            self.assertTrue(all(item.get("normalized_target_name") == "kernela" for item in operator_records))
            coverage = summary["profile_coverage"]
            self.assertTrue(coverage["segments"]["app"]["count_complete"])
            self.assertTrue(coverage["segments"]["op"]["count_complete"])
            self.assertTrue(coverage["segments"]["op"]["metric_coverage"]["pipe_utilization"]["complete"])
            self.assertTrue(coverage["segments"]["op"]["metric_coverage"]["arithmetic_utilization"]["complete"])
            self.assertEqual(coverage["segments"]["app"]["duration_total_us"], sum(10 + i for i in range(15)))
            self.assertEqual(summary["target_identity"]["status"], "match")
            self.assertEqual(summary["evidence_readiness"]["level"], "actionable_experiment")
            self.assertNotIn(
                "source_or_workload_context",
                summary["evidence_readiness"]["missing_evidence_families"],
            )
            self.assertFalse(
                any(
                    item["id"] == "collect_source_or_context"
                    for item in summary["evidence_readiness"]["recommended_followups"]
                )
            )
            self.assertEqual(
                {item["kind"] for item in summary["evidence_relations"]},
                {"timing_plus_pipe", "timing_plus_arithmetic"},
            )

    def test_counts_and_identity_remain_separate_and_app_extras_do_not_block_followup(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            target = declared_target(("kernel_a", 2))
            write_declared_target(run_dir, target)
            write_app_launches(run_dir, ["kernel_a", "kernel_a", "helper_kernel"])
            write_operator_launch(run_dir, "kernel_a", 0)

            summary, _ = evidence_model.build_evidence_model(run_dir)

            self.assertEqual(summary["target_identity"]["status"], "match")
            self.assertEqual(summary["profile_coverage"]["segments"]["op"]["missing_counts"], {"kernela": 1})
            self.assertEqual(summary["profile_coverage"]["segments"]["app"]["extra_counts"], {"helperkernel": 1})
            self.assertEqual(summary["evidence_readiness"]["level"], "directional")
            self.assertFalse(summary["evidence_relations"])
            self.assertEqual(profile_harness_module.target_consistency(summary)[0], "ok")
            self.assertTrue(
                any(item["id"] == "collect_default_metric_followup" for item in summary["next_collection_actions"])
            )

    def test_missing_over_extra_and_duplicate_authorities_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            target = declared_target(("kernel_a", 2), ("kernel_b", 1))
            write_declared_target(run_dir, target)
            write_app_launches(run_dir, ["kernel_a"] * 3 + ["helper"])
            for ordinal in range(3):
                write_operator_launch(run_dir, "kernel_a", ordinal)
            write_operator_launch(run_dir, "helper", 3)

            summary, _ = evidence_model.build_evidence_model(run_dir)
            op = summary["profile_coverage"]["segments"]["op"]
            self.assertEqual(op["missing_counts"], {"kernelb": 1})
            self.assertEqual(op["over_counts"], {"kernela": 1})
            self.assertEqual(op["extra_counts"], {"helper": 1})
            self.assertFalse(op["count_complete"])

            duplicate = run_dir / "reports" / "op" / "OPPROF_001" / "kernel_a" / "000" / "OpBasicInfo.csv"
            duplicate.write_text("Op Name,Task Duration(us)\nkernel_a,20\n", encoding="utf-8")
            duplicate_summary, _ = evidence_model.build_evidence_model(run_dir)
            duplicate_op = duplicate_summary["profile_coverage"]["segments"]["op"]
            self.assertFalse(duplicate_op["authority_complete"])
            self.assertTrue(any("OpBasicInfo" in item for item in duplicate_op["ambiguities"]))

    def test_app_count_authority_rejects_missing_empty_duplicate_and_multiple_trees(self):
        cases = ("missing", "empty", "duplicate_summary", "multiple_trees")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                run_dir = Path(tmp) / "run"
                target = declared_target(("kernel_a", 1))
                write_declared_target(run_dir, target)
                if case == "empty":
                    write_app_launches(run_dir, [])
                elif case == "duplicate_summary":
                    write_app_launches(run_dir, ["kernel_a"], duplicate_summary=True)
                elif case == "multiple_trees":
                    write_app_launches(run_dir, ["kernel_a"])
                    second = run_dir / "reports" / "app" / "PROF_002" / "mindstudio_profiler_output"
                    second.mkdir(parents=True)
                    (second / "op_summary_001.csv").write_text(
                        "Op Name,Task Duration(us),Calls\nkernel_a,10,99\n",
                        encoding="utf-8",
                    )

                summary, _ = evidence_model.build_evidence_model(run_dir)
                app = summary["profile_coverage"]["segments"]["app"]
                self.assertFalse(app["authority_complete"])
                self.assertFalse(app["count_complete"])
                if case == "empty":
                    self.assertEqual(summary["evidence_readiness"]["level"], "insufficient")
                    self.assertNotIn(
                        "rank application-level hot path",
                        summary["evidence_readiness"]["allowed_claims"],
                    )

    def test_op_count_authority_rejects_missing_empty_and_multirow_basic_info(self):
        cases = ("missing", "empty", "multirow")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                run_dir = Path(tmp) / "run"
                target = declared_target(("kernel_a", 1))
                write_declared_target(run_dir, target)
                write_app_launches(run_dir, ["kernel_a"])
                launch = write_operator_launch(run_dir, "kernel_a", 0)
                basic = launch / "OpBasicInfo_20260730130344937.csv"
                if case == "missing":
                    basic.unlink()
                elif case == "empty":
                    basic.write_text("Op Name,Task Duration(us)\n", encoding="utf-8")
                else:
                    basic.write_text(
                        "Op Name,Task Duration(us)\nkernel_a,20\nkernel_a,21\n",
                        encoding="utf-8",
                    )

                summary, _ = evidence_model.build_evidence_model(run_dir)
                op = summary["profile_coverage"]["segments"]["op"]
                self.assertFalse(op["authority_complete"])
                self.assertFalse(op["count_complete"])
                self.assertFalse(summary["evidence_relations"])

    def test_name_only_basic_info_is_not_usable_readiness_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            target = declared_target(("kernel_a", 1))
            write_declared_target(run_dir, target)
            launch = write_operator_launch(run_dir, "kernel_a", 0, families=())
            (launch / "OpBasicInfo_20260730130344937.csv").write_text(
                "Op Name\nkernel_a\n",
                encoding="utf-8",
            )

            summary, _ = evidence_model.build_evidence_model(run_dir)

            self.assertEqual(summary["target_identity"]["status"], "match")
            self.assertEqual(summary["evidence_readiness"]["level"], "insufficient")
            self.assertFalse(summary["evidence_readiness"]["allowed_claims"])

    def test_actionable_requires_value_backed_selected_metric(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            target = declared_target(("kernel_a", 1))
            write_declared_target(run_dir, target)
            write_app_launches(run_dir, ["kernel_a"])
            launch = write_operator_launch(run_dir, "kernel_a", 0)
            (launch / "PipeUtilization_20260730130344937.csv").write_text(
                "Metric,Label\nfoo,bar\n",
                encoding="utf-8",
            )

            summary, _ = evidence_model.build_evidence_model(run_dir)

            self.assertEqual(summary["profile_coverage"]["selected_segments_by_family"]["pipe_utilization"], "op")
            readiness = summary["evidence_readiness"]
            self.assertEqual(readiness["level"], "directional")
            self.assertNotIn("pipe_utilization", readiness["available_evidence_families"])
            self.assertNotIn("rank first AI Core pipe inspection direction", readiness["allowed_claims"])
            self.assertEqual(
                {item["id"] for item in summary["optimization_directions"]},
                {"focus_hot_path"},
            )

    def test_persisted_target_is_authoritative_and_provenance_is_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            invalid_run = Path(tmp) / "invalid"
            target = declared_target(("kernel_a", 1))
            write_declared_target(invalid_run, target)
            (invalid_run / "analysis" / "profile_harness_run.json").write_text(
                json.dumps({"target_selection": {"kernel_selector": "x", "expected_launches": []}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "profile_harness_run.json target_selection"):
                evidence_model.build_evidence_model(invalid_run)

            context_run = Path(tmp) / "context"
            analysis = context_run / "analysis"
            analysis.mkdir(parents=True)
            (analysis / "profile_context.json").write_text(
                json.dumps({"profile_harness": {"target": target}}),
                encoding="utf-8",
            )
            write_app_launches(context_run, ["kernel_a"])
            write_operator_launch(context_run, "kernel_a", 0)

            summary, _ = evidence_model.build_evidence_model(context_run)

            self.assertTrue(summary["profile_coverage"]["explicit_target"])
            self.assertEqual(
                summary["target_identity"]["expected"]["artifact"],
                "analysis/profile_context.json",
            )
            self.assertEqual(
                summary["target_identity"]["expected"]["field_ref"],
                "profile_harness.target.expected_launches",
            )

    def test_metric_failures_do_not_change_launch_count_authority(self):
        cases = (
            ("missing", "Memory"),
            ("missing", "MemoryL0"),
            ("missing", "MemoryUB"),
            ("duplicate", "Memory"),
            ("invalid", "MemoryL0"),
            ("empty", "MemoryUB"),
        )
        for case, stem in cases:
            with self.subTest(case=case, stem=stem), tempfile.TemporaryDirectory() as tmp:
                run_dir = Path(tmp) / "run"
                target = declared_target(("kernel_a", 1))
                write_declared_target(run_dir, target)
                write_app_launches(run_dir, ["kernel_a"])
                launch = write_operator_launch(
                    run_dir,
                    "kernel_a",
                    0,
                    families=("pipe_utilization", "memory"),
                )
                metric = launch / f"{stem}_20260730130344937.csv"
                if case == "missing":
                    metric.unlink()
                elif case == "duplicate":
                    (launch / f"{stem}.csv").write_text(
                        "Metric,Utilization(%)\nmetric,49\n",
                        encoding="utf-8",
                    )
                elif case == "invalid":
                    metric.write_bytes(b"\xff")
                else:
                    metric.write_text("Metric,Utilization(%)\n", encoding="utf-8")

                summary, raw_index = evidence_model.build_evidence_model(run_dir)
                op = summary["profile_coverage"]["segments"]["op"]
                self.assertTrue(op["authority_complete"])
                self.assertTrue(op["count_complete"])
                self.assertFalse(op["metric_coverage"]["memory"]["complete"])
                for record in raw_index["artifacts"]:
                    if record.get("segment") == "op" and record.get("group") in {
                        "op_basic_info",
                        "pipe_utilization",
                        "memory",
                    }:
                        self.assertTrue(record.get("launch_key"))
                        self.assertEqual(record.get("normalized_target_name"), "kernela")

    def test_noncanonical_timestamp_suffix_is_not_discovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            target = declared_target(("kernel_a", 1))
            write_declared_target(run_dir, target)
            write_app_launches(run_dir, ["kernel_a"])
            launch = write_operator_launch(run_dir, "kernel_a", 0, families=())
            unsupported = launch / "PipeUtilization_123.csv"
            unsupported.write_text("Metric,Utilization(%)\nmetric,50\n", encoding="utf-8")

            summary, raw_index = evidence_model.build_evidence_model(run_dir)

            self.assertFalse(
                summary["profile_coverage"]["segments"]["op"]["metric_coverage"]["pipe_utilization"]["complete"]
            )
            self.assertFalse(any(item.get("artifact", "").endswith(unsupported.name) for item in raw_index["artifacts"]))

    def test_default_followup_reports_one_per_target_metric_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            target = declared_target(("kernel_a", 2))
            write_declared_target(run_dir, target)
            write_app_launches(run_dir, ["kernel_a", "kernel_a"])
            write_operator_launch(run_dir, "kernel_a", 0)
            write_operator_launch(
                run_dir,
                "kernel_a",
                0,
                segment="followup:collect_default_metric_followup",
                families=("arithmetic_utilization",),
            )
            write_operator_launch(
                run_dir,
                "kernel_a",
                1,
                segment="followup:collect_default_metric_followup",
                families=(),
            )

            summary, _ = evidence_model.build_evidence_model(run_dir)
            arithmetic = summary["profile_coverage"]["segments"][
                "followup:collect_default_metric_followup"
            ]["metric_coverage"]["arithmetic_utilization"]
            self.assertEqual(arithmetic["by_target"]["kernela"]["missing"], 1)
            self.assertFalse(arithmetic["complete"])
            self.assertIsNone(summary["profile_coverage"]["selected_segments_by_family"]["arithmetic_utilization"])
            self.assertNotIn(
                "inspect_pipe_arithmetic_mix",
                {item["id"] for item in summary["optimization_directions"]},
            )
            self.assertNotIn(
                "inspect arithmetic utilization direction",
                summary["evidence_readiness"]["allowed_claims"],
            )

    def test_memory_family_requires_all_three_stems_and_default_is_deterministic_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            target = declared_target(("kernel_a", 1))
            write_declared_target(run_dir, target)
            write_app_launches(run_dir, ["kernel_a"])
            op_launch = write_operator_launch(
                run_dir,
                "kernel_a",
                0,
                families=("pipe_utilization", "arithmetic_utilization", "memory"),
            )
            (op_launch / "MemoryUB_20260730130344937.csv").unlink()
            (op_launch / "ArithmeticUtilization.csv").write_text(
                "Metric,Utilization(%)\nmetric,49\n", encoding="utf-8"
            )
            write_operator_launch(
                run_dir,
                "kernel_a",
                0,
                segment="followup:collect_default_metric_followup",
                families=("arithmetic_utilization",),
            )

            summary, _ = evidence_model.build_evidence_model(run_dir)
            coverage = summary["profile_coverage"]
            self.assertFalse(coverage["segments"]["op"]["metric_coverage"]["memory"]["complete"])
            self.assertEqual(coverage["selected_segments_by_family"]["pipe_utilization"], "op")
            self.assertEqual(
                coverage["selected_segments_by_family"]["arithmetic_utilization"],
                "followup:collect_default_metric_followup",
            )
            self.assertEqual(
                summary["headlines"]["arithmetic_utilization"]["segment"],
                "followup:collect_default_metric_followup",
            )
            self.assertIsNone(coverage["selected_segments_by_family"]["memory"])
            self.assertEqual(summary["evidence_readiness"]["level"], "actionable_experiment")

    def test_report_renders_coverage_before_diagnosis_with_measurement_boundary(self):
        coverage = {
            "explicit_target": True,
            "segments": {
                "app": {
                    "expected_total": 1,
                    "observed_total": 1,
                    "completeness": "complete",
                    "duration_total_us": 10,
                    "duration_by_target_us": {"kernela": 10},
                }
            },
            "measurement_boundary": "Application and operator totals are separate measurements.",
        }
        lines = generate_report.profile_coverage_lines(coverage)
        rendered = "\n".join(lines)
        self.assertIn("Declared Target Coverage", rendered)
        self.assertIn("per-target duration", rendered)
        self.assertIn("separate measurements", rendered)
