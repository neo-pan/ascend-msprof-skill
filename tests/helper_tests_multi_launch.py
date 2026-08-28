"""Declared multi-launch collection and coverage tests."""

from tests.helpers_shared import *  # noqa: F401,F403

from ascend_msprof_skill import _profile_target
from ascend_msprof_skill.candidate_feedback import build_comparison_design_feedback
from ascend_msprof_skill.summarize_candidate import build_candidate_summary


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


def write_candidate_context(run_dir: Path) -> None:
    (run_dir / "analysis" / "profile_context.json").write_text(
        json.dumps(
            {
                "verify_context": {
                    "raw": {
                        "workload": {
                            "task_name": "focused-scope-test",
                            "shape": [1],
                            "dtype": "float32",
                        },
                        "correctness": {
                            "correctness_ok": True,
                            "receipt": {"case_count": 1},
                        },
                        "official_timing": {
                            "authority": "executor_natural_launch",
                            "aggregation": "median",
                            "latency_source": "executor_latency_ms",
                            "latency_ms": 1.0,
                            "samples_ms": [1.0],
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )


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

    def test_focused_target_must_be_a_count_bounded_program_subset(self):
        program = declared_target(("kernel_a", 2), ("kernel_b", 1), selector="kernel_*")
        focused = declared_target(("kernel_a", 1), selector="kernel_a")

        self.assertEqual(_profile_target.validate_target_subset(program, focused), focused)
        focused_pair = declared_target(("kernel_a", 1), ("kernel_b", 1), selector="kernel_[ab]")
        self.assertEqual(_profile_target.validate_target_subset(program, focused_pair), focused_pair)
        with self.assertRaisesRegex(ValueError, "not a program-target subset"):
            _profile_target.validate_target_subset(
                program,
                declared_target(("kernel_c", 1), selector="kernel_c"),
            )
        with self.assertRaisesRegex(ValueError, "launch count exceeds"):
            _profile_target.validate_target_subset(
                program,
                declared_target(("kernel_a", 3), selector="kernel_a"),
            )
        with self.assertRaisesRegex(ValueError, "kernel_selector must match"):
            _profile_target.validate_target_subset(
                program,
                declared_target(("kernel_a", 1), selector="kernel_b"),
            )
        with self.assertRaisesRegex(ValueError, "must not match unselected"):
            _profile_target.validate_target_subset(
                program,
                declared_target(("kernel_a", 1), selector="kernel_*"),
            )
        with self.assertRaisesRegex(ValueError, "proper subset"):
            _profile_target.validate_target_subset(program, program)

        single = declared_target(("kernel_a", 1), selector="kernel_a")
        self.assertEqual(_profile_target.validate_target_subset(single, single), single)

    def test_invalid_persisted_focused_target_does_not_fall_back_to_program_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            program = declared_target(("kernel_a", 1))
            write_declared_target(run_dir, program)
            workflow_path = run_dir / "analysis" / "profile_harness_run.json"
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            workflow["follow_up_actions"] = [
                {
                    "id": "collect_default_metric_followup",
                    "status": "succeeded",
                    "target_selection": {"kernel_selector": "kernel_a", "expected_launches": []},
                }
            ]
            workflow_path.write_text(json.dumps(workflow), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "follow_up_actions target_selection is invalid"):
                evidence_model.build_evidence_model(run_dir)

    def test_persisted_focused_target_must_remain_a_program_subset(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            program = declared_target(("kernel_a", 1), selector="kernel_a")
            unrelated = declared_target(("kernel_b", 1), selector="kernel_b")
            write_declared_target(run_dir, program)
            workflow_path = run_dir / "analysis" / "profile_harness_run.json"
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            workflow["follow_up_actions"] = [
                {
                    "id": "collect_default_metric_followup",
                    "segment_id": profile_harness_module.default_followup_layout(
                        unrelated
                    ).segment_id,
                    "status": "succeeded",
                    "target_selection": unrelated,
                }
            ]
            workflow_path.write_text(json.dumps(workflow), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "not a program-target subset"):
                evidence_model.build_evidence_model(run_dir)

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

    def test_focused_default_followup_has_local_coverage_without_program_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            program = declared_target(("kernel_a", 2), ("kernel_b", 1), selector="kernel_*")
            focused = declared_target(("kernel_b", 1), selector="kernel_b")
            write_declared_target(run_dir, program)
            write_app_launches(run_dir, ["kernel_a", "kernel_a", "kernel_b"])
            write_operator_launch(run_dir, "kernel_a", 0)
            write_operator_launch(run_dir, "kernel_a", 1)
            write_operator_launch(run_dir, "kernel_b", 0)

            initial, _ = evidence_model.build_evidence_model(run_dir)
            action = next(
                item
                for item in initial["next_collection_actions"]
                if item["id"] == "collect_default_metric_followup"
            )
            self.assertEqual(action["necessity"], "hypothesis_required")
            self.assertEqual(action["target_scope"]["kind"], "complete_program")
            self.assertEqual(action["estimated_cost"]["estimated_launches"], 3)
            self.assertTrue(action["unlocks_claims"])

            focused_segment_id = profile_harness_module.default_followup_layout(
                focused
            ).segment_id
            workflow_path = run_dir / "analysis" / "profile_harness_run.json"
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            workflow["follow_up_actions"] = [
                {
                    "id": "collect_default_metric_followup",
                    "segment_id": focused_segment_id,
                    "status": "succeeded",
                    "target_selection": focused,
                    "target_scope": {"kind": "focused_subset"},
                }
            ]
            workflow_path.write_text(json.dumps(workflow, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            write_operator_launch(
                run_dir,
                "kernel_b",
                0,
                segment=f"followup:{focused_segment_id}",
                families=(
                    "pipe_utilization",
                    "arithmetic_utilization",
                    "l2_cache",
                    "memory",
                    "resource_conflict",
                ),
            )

            summary, _ = evidence_model.build_evidence_model(run_dir)
            coverage = summary["profile_coverage"]
            focused_segment = coverage["segments"][f"followup:{focused_segment_id}"]
            self.assertEqual(coverage["schema_version"], "1.1")
            self.assertEqual(focused_segment["target_scope"]["kind"], "focused_subset")
            self.assertEqual(focused_segment["target_scope"]["expected_total"], 1)
            self.assertTrue(focused_segment["count_complete"])
            self.assertEqual(focused_segment["target_identity"]["status"], "match")
            self.assertTrue(focused_segment["metric_coverage"]["arithmetic_utilization"]["complete"])
            self.assertIsNone(coverage["selected_segments_by_family"]["arithmetic_utilization"])
            action = next(
                item
                for item in summary["next_collection_actions"]
                if item["id"] == "collect_default_metric_followup"
            )
            self.assertEqual(action["target_scope"]["kind"], "complete_program")
            self.assertEqual(
                set(action["required_artifacts"]),
                {
                    "ArithmeticUtilization.csv",
                    "Memory.csv/MemoryL0.csv/MemoryUB.csv",
                    "ResourceConflictRatio.csv",
                },
            )
            self.assertTrue(
                any(
                    item["field_ref"]
                    == "profile_coverage.selected_segments_by_family.arithmetic_utilization"
                    for item in action["evidence"]
                )
            )
            command = profile_harness_module.msprof_default_followup_command(
                run_dir,
                Path("/tmp/run.sh"),
                focused,
                focused_target_selection=focused,
            )
            self.assertIn("--kernel-name=kernel_b", command)
            self.assertIn("--launch-count=1", command)

    def test_duplicate_blocked_followup_preserves_succeeded_target_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            program = declared_target(("kernel_a", 1), ("kernel_b", 1), selector="kernel_*")
            focused = declared_target(("kernel_b", 1), selector="kernel_b")
            write_declared_target(run_dir, program)
            write_app_launches(run_dir, ["kernel_a", "kernel_b"])
            write_operator_launch(run_dir, "kernel_a", 0)
            write_operator_launch(run_dir, "kernel_b", 0)

            initial, _ = evidence_model.build_evidence_model(run_dir)
            decision = next(
                item
                for item in profile_harness_module.plan_followup_actions(
                    run_dir,
                    initial,
                    selected_action_id=profile_harness_module.DEFAULT_FOLLOWUP_ACTION_ID,
                    target_selection=focused,
                )
                if item.execute_default_followup
            )
            succeeded = dict(decision.record)
            succeeded.update({"status": "succeeded", "returncode": 0})
            workflow_path = run_dir / "analysis" / "profile_harness_run.json"
            profile_harness_module.append_followup_action_records(
                workflow_path,
                [succeeded],
                recorded_commands={},
                recorded_outputs={},
            )
            segment = f"followup:{succeeded['segment_id']}"
            write_operator_launch(
                run_dir,
                "kernel_b",
                0,
                segment=segment,
                families=(
                    "pipe_utilization",
                    "arithmetic_utilization",
                    "l2_cache",
                    "memory",
                    "resource_conflict",
                ),
            )

            successful, _ = evidence_model.build_evidence_model(run_dir)
            blocked = next(
                item
                for item in profile_harness_module.plan_followup_actions(
                    run_dir,
                    successful,
                    selected_action_id=profile_harness_module.DEFAULT_FOLLOWUP_ACTION_ID,
                    target_selection=focused,
                )
                if item.record.get("segment_id") == succeeded["segment_id"]
            )
            self.assertEqual(blocked.record["status"], "blocked")
            profile_harness_module.append_followup_action_records(
                workflow_path,
                [blocked.record],
                recorded_commands={},
                recorded_outputs={},
            )

            summary, _ = evidence_model.build_evidence_model(run_dir)
            coverage = summary["profile_coverage"]
            focused_coverage = coverage["segments"][segment]
            self.assertEqual(focused_coverage["target_scope"]["kind"], "focused_subset")
            self.assertEqual(focused_coverage["target_identity"]["status"], "match")
            self.assertTrue(focused_coverage["count_complete"])
            self.assertIsNone(
                coverage["selected_segments_by_family"]["arithmetic_utilization"]
            )

    def test_flat_focused_default_real_shape_normalizes_one_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            program = declared_target(
                ("rr17_paco_complete_gram_kernel", 1),
                ("rr17_paco_complete_trsm_update_kernel", 14),
                selector="rr17_paco_complete_*",
            )
            focused = declared_target(
                ("rr17_paco_complete_gram_kernel", 1),
                selector="rr17_paco_complete_gram_kernel",
            )
            write_declared_target(run_dir, program)
            write_candidate_context(run_dir)
            write_app_launches(
                run_dir,
                ["rr17_paco_complete_gram_kernel"]
                + ["rr17_paco_complete_trsm_update_kernel"] * 14,
            )
            write_operator_launch(run_dir, "rr17_paco_complete_gram_kernel", 0)
            for ordinal in range(14):
                write_operator_launch(
                    run_dir,
                    "rr17_paco_complete_trsm_update_kernel",
                    ordinal,
                )
            workflow_path = run_dir / "analysis" / "profile_harness_run.json"
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            segment_id = "collect_default_metric_followup_focused_54c738d03ece"
            workflow["follow_up_actions"] = [
                {
                    "id": "collect_default_metric_followup",
                    "segment_id": segment_id,
                    "status": "succeeded",
                    "target_selection": focused,
                    "target_scope": {"kind": "focused_subset"},
                }
            ]
            workflow_path.write_text(
                json.dumps(workflow, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            flat_root = (
                run_dir
                / "reports"
                / "followups"
                / segment_id
                / "OPPROF_20260731234035_UIFNUDWBCPGKNZAZ"
            )
            shutil.copytree(
                REAL_DEFAULT_VECTOR_FIXTURE / "reports" / "OPPROF_001",
                flat_root,
            )
            (flat_root / "L2Cache.csv").write_text(
                "Metric,Hit Rate(%)\nl2,50\n",
                encoding="utf-8",
            )
            (flat_root / "OpBasicInfo.csv").write_text(
                "Op Name,Op Type,Task Duration(us),Block Dim,Mix Block Dim,Device Id,Pid,Current Freq,Rated Freq,\n"
                "rr17_paco_complete_gram_kernel_mix_aic,mix,21.160000,17,34,1,NA,1800,1800,\n",
                encoding="utf-8",
            )

            model = evidence_model.write_evidence_model(run_dir)
            summary = model.summary
            raw_index = model.raw_artifact_index

            coverage = summary["profile_coverage"]
            focused_segment = coverage["segments"][f"followup:{segment_id}"]
            self.assertEqual(focused_segment["observed_total"], 1)
            self.assertTrue(focused_segment["count_complete"])
            self.assertEqual(focused_segment["target_identity"]["status"], "match")
            self.assertTrue(focused_segment["metric_coverage"]["arithmetic_utilization"]["complete"])
            self.assertTrue(focused_segment["metric_coverage"]["memory"]["complete"])
            self.assertTrue(focused_segment["metric_coverage"]["resource_conflict"]["complete"])
            self.assertIsNone(coverage["selected_segments_by_family"]["arithmetic_utilization"])
            focused_records = [
                item
                for item in raw_index["artifacts"]
                if item.get("segment") == f"followup:{segment_id}"
                and item.get("group") in {
                    "op_basic_info",
                    "pipe_utilization",
                    "arithmetic_utilization",
                    "l2_cache",
                    "memory",
                    "resource_conflict",
                }
            ]
            self.assertTrue(focused_records)
            self.assertEqual(
                {item.get("launch_key") for item in focused_records},
                {
                    f"followup:{segment_id}|"
                    "reports/followups/collect_default_metric_followup_focused_54c738d03ece/"
                    "OPPROF_20260731234035_UIFNUDWBCPGKNZAZ"
                },
            )
            self.assertEqual(
                {item.get("normalized_target_name") for item in focused_records},
                {"rr17pacocompletegramkernelmixaic"},
            )
            readiness_scopes = {
                item["segment"]: item["metric_scope"]
                for item in summary["evidence_readiness"]["segments"]
            }
            self.assertEqual(readiness_scopes["app"], None)
            self.assertEqual(readiness_scopes["op"], "PipeUtilization")
            self.assertEqual(readiness_scopes[f"followup:{segment_id}"], "Default")
            focused_expected = summary["target_identity"]["segments"][f"followup:{segment_id}"]["expected"]
            self.assertEqual(focused_expected["names"], ["rr17_paco_complete_gram_kernel"])
            self.assertEqual(focused_expected["counts"], {"rr17pacocompletegramkernel": 1})
            self.assertEqual(
                summary["target_identity"]["expected"]["counts"],
                _profile_target.expected_counts(program),
            )

            candidate = build_candidate_summary(run_dir)
            questions = {item["id"]: item for item in candidate["design_feedback"]["questions"]}
            memory = questions["memory_cache"]
            arithmetic = questions["pipe_arithmetic"]
            focused_artifacts = {
                Path(str(item["artifact"])).name
                for item in [*memory["available_evidence"], *arithmetic["available_evidence"]]
                if item.get("target_scope", {}).get("kind") == "focused_subset"
            }
            self.assertEqual(
                focused_artifacts,
                {
                    "ArithmeticUtilization.csv",
                    "L2Cache.csv",
                    "Memory.csv",
                    "MemoryL0.csv",
                    "MemoryUB.csv",
                },
            )
            for question in (memory, arithmetic):
                self.assertTrue(question["missing_evidence"])
                self.assertTrue(
                    all(
                        item["target_scope"]["kind"] == "complete_program"
                        and item["role"].startswith("complete-program ")
                        and item["role"].endswith(" coverage is missing")
                        for item in question["missing_evidence"]
                    )
                )
            action = next(
                item
                for item in summary["next_collection_actions"]
                if item["id"] == "collect_default_metric_followup"
            )
            self.assertEqual(action["necessity"], "hypothesis_required")
            self.assertEqual(action["target_scope"]["expected_total"], 15)
            self.assertIsNone(coverage["selected_segments_by_family"]["memory"])
            self.assertEqual(candidate["candidate_summary_schema_version"], "1.2")

            profile_context = json.loads(
                (run_dir / "analysis" / "profile_context.json").read_text(encoding="utf-8")
            )
            comparison = build_comparison_design_feedback(
                summary,
                summary,
                profile_context,
                profile_context,
                raw_index,
                raw_index,
                None,
                None,
                None,
            )
            comparison_memory = next(
                item
                for item in comparison["questions"]
                if item["id"] == "memory_cache"
            )
            comparison_scoped = [
                item
                for item in comparison_memory["available_evidence"]
                if item.get("target_scope", {}).get("kind") == "focused_subset"
            ]
            self.assertEqual({item["source"] for item in comparison_scoped}, {"a", "b"})
            self.assertTrue(
                all(
                    item["target_scope"] == focused_segment["target_scope"]
                    for item in comparison_scoped
                )
            )

    def test_flat_initial_operator_single_launch_normalizes_one_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            target = declared_target(("minimal_kernel", 1), selector="minimal_kernel")
            write_declared_target(run_dir, target)
            write_candidate_context(run_dir)
            write_app_launches(run_dir, ["minimal_kernel"])
            write_minimal_pipe_op(run_dir)

            model = evidence_model.write_evidence_model(run_dir)
            coverage = model.summary["profile_coverage"]
            op_segment = coverage["segments"]["op"]

            self.assertEqual(op_segment["observed_total"], 1)
            self.assertTrue(op_segment["count_complete"])
            self.assertIn("verified flat single-launch", op_segment["counting_authority"])
            self.assertEqual(op_segment["target_identity"]["status"], "match")
            self.assertTrue(op_segment["metric_coverage"]["pipe_utilization"]["complete"])
            self.assertEqual(coverage["selected_segments_by_family"]["pipe_utilization"], "op")
            op_records = [
                item
                for item in model.raw_artifact_index["artifacts"]
                if item.get("segment") == "op"
                and item.get("group") in {"op_basic_info", "pipe_utilization"}
            ]
            self.assertEqual(
                {item.get("launch_key") for item in op_records},
                {"op|reports/op/OPPROF_001"},
            )
            self.assertEqual(model.summary["target_identity"]["status"], "match")

    def test_flat_complete_program_single_launch_normalizes_one_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            target = declared_target(
                ("rr17_paco_complete_gram_kernel", 1),
                selector="rr17_paco_complete_gram_kernel",
            )
            write_declared_target(run_dir, target)
            write_candidate_context(run_dir)
            write_app_launches(run_dir, ["rr17_paco_complete_gram_kernel"])
            write_operator_launch(run_dir, "rr17_paco_complete_gram_kernel", 0)
            initial, _ = evidence_model.build_evidence_model(run_dir)
            decision = next(
                item
                for item in profile_harness_module.plan_followup_actions(
                    run_dir,
                    initial,
                    selected_action_id=profile_harness_module.DEFAULT_FOLLOWUP_ACTION_ID,
                )
                if item.execute_default_followup
            )
            workflow_path = run_dir / "analysis" / "profile_harness_run.json"
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            record = dict(decision.record)
            record.update({"status": "succeeded", "returncode": 0})
            workflow["follow_up_actions"] = [record]
            workflow_path.write_text(
                json.dumps(workflow, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            segment_id = record["segment_id"]
            flat_root = (
                run_dir
                / "reports"
                / "followups"
                / segment_id
                / "OPPROF_20260731234035_UIFNUDWBCPGKNZAZ"
            )
            shutil.copytree(
                REAL_DEFAULT_VECTOR_FIXTURE / "reports" / "OPPROF_001",
                flat_root,
            )
            (flat_root / "L2Cache.csv").write_text(
                "Metric,Hit Rate(%)\nl2,50\n",
                encoding="utf-8",
            )
            (flat_root / "OpBasicInfo.csv").write_text(
                "Op Name,Op Type,Task Duration(us),Block Dim,Mix Block Dim,Device Id,Pid,Current Freq,Rated Freq,\n"
                "rr17_paco_complete_gram_kernel_mix_aic,mix,21.160000,17,34,1,NA,1800,1800,\n",
                encoding="utf-8",
            )

            model = evidence_model.write_evidence_model(run_dir)
            summary = model.summary
            raw_index = model.raw_artifact_index

            self.assertEqual(
                workflow["follow_up_actions"][0]["target_scope"]["kind"],
                "complete_program",
            )
            self.assertNotIn("target_selection", workflow["follow_up_actions"][0])
            coverage = summary["profile_coverage"]
            followup_segment = coverage["segments"][f"followup:{segment_id}"]
            self.assertEqual(followup_segment["observed_total"], 1)
            self.assertTrue(followup_segment["count_complete"])
            self.assertEqual(followup_segment["target_identity"]["status"], "match")
            self.assertEqual(followup_segment["target_scope"]["kind"], "complete_program")
            self.assertTrue(followup_segment["metric_coverage"]["arithmetic_utilization"]["complete"])
            self.assertTrue(followup_segment["metric_coverage"]["memory"]["complete"])
            self.assertTrue(followup_segment["metric_coverage"]["resource_conflict"]["complete"])
            self.assertEqual(
                coverage["selected_segments_by_family"]["arithmetic_utilization"],
                f"followup:{segment_id}",
            )
            self.assertEqual(
                coverage["selected_segments_by_family"]["memory"],
                f"followup:{segment_id}",
            )
            self.assertEqual(
                coverage["selected_segments_by_family"]["resource_conflict"],
                f"followup:{segment_id}",
            )
            followup_records = [
                item
                for item in raw_index["artifacts"]
                if item.get("segment") == f"followup:{segment_id}"
                and item.get("group") in {
                    "op_basic_info",
                    "pipe_utilization",
                    "arithmetic_utilization",
                    "l2_cache",
                    "memory",
                    "resource_conflict",
                }
            ]
            self.assertTrue(followup_records)
            self.assertEqual(
                {item.get("launch_key") for item in followup_records},
                {
                    f"followup:{segment_id}|"
                    f"reports/followups/{segment_id}/"
                    "OPPROF_20260731234035_UIFNUDWBCPGKNZAZ"
                },
            )

    def test_unadmitted_followup_segments_cannot_gain_program_authority(self):
        target = declared_target(("kernel_a", 1), selector="kernel_a")
        focused_segment_id = profile_harness_module.default_followup_layout(target).segment_id
        mismatched_segment_id = focused_segment_id[:-1] + (
            "0" if focused_segment_id[-1] != "0" else "1"
        )
        cases = (
            (
                "unsupported_segment",
                {
                    "id": "unsupported_action",
                    "segment_id": "unsupported_segment",
                    "status": "succeeded",
                },
                True,
            ),
            (
                "collect_default_metric_followup_focused_deadbeefcafe",
                {
                    "id": "collect_default_metric_followup",
                    "segment_id": "collect_default_metric_followup_focused_deadbeefcafe",
                    "status": "succeeded",
                },
                False,
            ),
            (
                mismatched_segment_id,
                {
                    "id": "collect_default_metric_followup",
                    "segment_id": mismatched_segment_id,
                    "status": "succeeded",
                },
                True,
            ),
            (
                "collect_default_metric_followup",
                {
                    "id": "collect_default_metric_followup",
                    "segment_id": "collect_default_metric_followup",
                    "status": "failed",
                    "returncode": 9,
                },
                False,
            ),
        )
        for segment_id, action, include_target in cases:
            with self.subTest(segment_id=segment_id), tempfile.TemporaryDirectory() as tmp:
                run_dir = Path(tmp) / "run"
                write_declared_target(run_dir, target)
                write_candidate_context(run_dir)
                write_app_launches(run_dir, ["kernel_a"])
                write_operator_launch(run_dir, "kernel_a", 0)
                workflow_path = run_dir / "analysis" / "profile_harness_run.json"
                workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
                record = dict(action)
                if include_target:
                    record["target_selection"] = target
                workflow["follow_up_actions"] = [record]
                workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
                segment = f"followup:{segment_id}"
                write_operator_launch(
                    run_dir,
                    "kernel_a",
                    0,
                    segment=segment,
                    families=(
                        "pipe_utilization",
                        "arithmetic_utilization",
                        "l2_cache",
                        "memory",
                        "resource_conflict",
                    ),
                )

                summary, _ = evidence_model.build_evidence_model(run_dir)
                coverage = summary["profile_coverage"]
                segment_coverage = coverage["segments"][segment]

                self.assertEqual(segment_coverage["target_scope"]["kind"], "observed_run")
                self.assertEqual(segment_coverage["target_identity"]["status"], "not_applicable")
                self.assertIsNone(segment_coverage["count_complete"])
                self.assertIsNone(
                    coverage["selected_segments_by_family"]["arithmetic_utilization"]
                )

    def test_canonical_core_dump_receipt_cannot_gain_program_authority(self):
        for action_recorded in (False, True):
            with (
                self.subTest(action_recorded=action_recorded),
                tempfile.TemporaryDirectory() as tmp,
            ):
                run_dir = Path(tmp) / "run"
                target = declared_target(("kernel_a", 1), selector="kernel_a")
                write_declared_target(run_dir, target)
                if action_recorded:
                    workflow_path = run_dir / "analysis" / "profile_harness_run.json"
                    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
                    workflow["follow_up_actions"] = [
                        {
                            "id": "collect_default_metric_followup",
                            "segment_id": "collect_default_metric_followup",
                            "status": "succeeded",
                        }
                    ]
                    workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
                write_app_launches(run_dir, ["kernel_a"])
                write_operator_launch(run_dir, "kernel_a", 0)
                segment = "followup:collect_default_metric_followup"
                write_operator_launch(
                    run_dir,
                    "kernel_a",
                    0,
                    segment=segment,
                    families=(
                        "pipe_utilization",
                        "arithmetic_utilization",
                        "l2_cache",
                        "memory",
                        "resource_conflict",
                    ),
                )
                profile_harness_module.write_command_result(
                    run_dir,
                    "msprof_followup_collect_default_metric_followup",
                    status="core_dump",
                    process_returncode=0,
                )

                summary, _ = evidence_model.build_evidence_model(run_dir)
                coverage = summary["profile_coverage"]
                segment_coverage = coverage["segments"][segment]

                self.assertEqual(segment_coverage["target_scope"]["kind"], "observed_run")
                self.assertIsNone(segment_coverage["count_complete"])
                self.assertIsNone(
                    coverage["selected_segments_by_family"]["arithmetic_utilization"]
                )

    def test_app_core_dump_receipt_excludes_derived_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            target = declared_target(("kernel_a", 1), selector="kernel_a")
            write_declared_target(run_dir, target)
            write_app_launches(run_dir, ["kernel_a"])
            write_operator_launch(run_dir, "kernel_a", 0)
            profile_harness_module.write_command_result(
                run_dir,
                "msprof_default",
                status="core_dump",
                process_returncode=0,
            )

            summary, raw_index = evidence_model.build_evidence_model(run_dir)

            app_coverage = summary["profile_coverage"]["segments"]["app"]
            self.assertEqual(app_coverage["observed_total"], 0)
            self.assertFalse(app_coverage["count_complete"])
            self.assertNotIn(
                "app_timing",
                summary["evidence_readiness"]["available_evidence_families"],
            )
            self.assertTrue(
                any(
                    item.get("segment") == "app" and item.get("group") == "op_summary"
                    for item in raw_index["artifacts"]
                )
            )
            self.assertFalse(
                any(
                    str(item.get("artifact") or "").endswith(".result.json")
                    for item in raw_index["artifacts"]
                )
            )

    def test_op_core_dump_receipt_excludes_derived_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            target = declared_target(("kernel_a", 1), selector="kernel_a")
            write_declared_target(run_dir, target)
            write_app_launches(run_dir, ["kernel_a"])
            write_operator_launch(run_dir, "kernel_a", 0)
            (run_dir / "logs" / "msprof_op.stdout").write_text(
                "2026-08-27 00:00:00 [INFO] Performance Summary Report:\n"
                "1) failed profile summary\n",
                encoding="utf-8",
            )
            profile_harness_module.write_command_result(
                run_dir,
                "msprof_op",
                status="core_dump",
                process_returncode=0,
            )

            summary, raw_index = evidence_model.build_evidence_model(run_dir)

            coverage = summary["profile_coverage"]
            self.assertEqual(coverage["segments"]["op"]["target_scope"]["kind"], "observed_run")
            self.assertIsNone(coverage["selected_segments_by_family"]["pipe_utilization"])
            self.assertEqual(summary["target_identity"]["status"], "missing_observed")
            self.assertEqual(summary["target_identity"]["expected"]["names"], ["kernel_a"])
            self.assertEqual(summary["target_identity"]["expected"]["counts"], {"kernela": 1})
            self.assertIsNone(summary["stdout_sections"]["performance_summary"])
            self.assertNotIn(
                "pipe_utilization",
                summary["evidence_readiness"]["available_evidence_families"],
            )
            self.assertTrue(
                any(
                    item.get("segment") == "op" and item.get("group") == "pipe_utilization"
                    for item in raw_index["artifacts"]
                )
            )
            self.assertTrue(
                any(
                    item.get("segment") == "op"
                    and item.get("group") == "stdout_performance_summary"
                    for item in raw_index["artifacts"]
                )
            )

    def test_simulator_core_dump_receipt_excludes_derived_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            write_minimal_simulator_trace(run_dir)
            profile_harness_module.write_command_result(
                run_dir,
                "msprof_simulator",
                status="core_dump",
                process_returncode=0,
            )

            artifacts = evidence_model.write_evidence_model(run_dir)
            summary = artifacts.summary
            raw_index = artifacts.raw_artifact_index

            self.assertNotIn(
                "simulator_source_pipeline",
                summary["evidence_readiness"]["available_evidence_families"],
            )
            source_dimension = next(
                item
                for item in summary["analysis_dimensions"]
                if item["id"] == "source_pipeline_context"
            )
            self.assertEqual(source_dimension["status"], "insufficient")
            self.assertEqual(summary["_simulator_hotspot_model"]["inputs"], [])
            self.assertTrue(
                any(
                    item.get("segment") == "simulator"
                    and item.get("group") == "simulator_trace"
                    for item in raw_index["artifacts"]
                )
            )
            candidate = build_candidate_summary(run_dir)
            self.assertNotIn(
                "generated_context",
                {item["id"] for item in candidate["design_feedback"]["questions"]},
            )

    def test_core_dump_raw_artifacts_are_audit_only_in_candidate_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            target = declared_target(("kernel_a", 1), selector="kernel_a")
            write_declared_target(run_dir, target)
            write_candidate_context(run_dir)
            write_app_launches(run_dir, ["kernel_a"])
            write_operator_launch(run_dir, "kernel_a", 0)
            for log_stem in ("msprof_default", "msprof_op"):
                profile_harness_module.write_command_result(
                    run_dir,
                    log_stem,
                    status="core_dump",
                    process_returncode=0,
                )
            evidence_model.write_evidence_model(run_dir)

            candidate = build_candidate_summary(run_dir)
            profiler = candidate["run"]["profiler_evidence"]
            questions = {
                item["id"]: item for item in candidate["design_feedback"]["questions"]
            }
            raw_index = json.loads(
                (run_dir / "analysis" / "raw_artifact_index.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertGreater(
                sum(item.get("status") == "parsed" for item in raw_index["artifacts"]),
                0,
            )
            self.assertEqual(profiler["parsed_artifact_count"], 0)
            self.assertFalse(profiler["evidence_present"])
            self.assertIn(
                "missing opbasic_workload profiler evidence",
                questions["opbasic_workload"]["blocked_by"],
            )
            self.assertFalse(
                any(
                    item.get("role") == "work distribution raw artifact"
                    for item in questions["opbasic_workload"]["available_evidence"]
                )
            )

    def test_flat_operator_output_remains_rejected_outside_strict_focused_contract(self):
        cases = (
            "multiple_roots",
            "multiple_basic",
            "empty_basic",
            "invalid_basic",
            "multirow_basic",
            "name_mismatch",
            "expected_two",
            "nonflat_unkeyed_path",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                run_dir = Path(tmp) / "run"
                gram_count = 2 if case == "expected_two" else 1
                program = declared_target(
                    ("rr17_paco_complete_gram_kernel", gram_count),
                    ("rr17_paco_complete_trsm_update_kernel", 1),
                    selector="rr17_paco_complete_*",
                )
                focused = declared_target(
                    ("rr17_paco_complete_gram_kernel", gram_count),
                    selector="rr17_paco_complete_gram_kernel",
                )
                write_declared_target(run_dir, program)
                write_candidate_context(run_dir)
                launch_names = ["rr17_paco_complete_gram_kernel"] * gram_count
                launch_names.append("rr17_paco_complete_trsm_update_kernel")
                write_app_launches(run_dir, launch_names)
                for ordinal, name in enumerate(launch_names):
                    write_operator_launch(run_dir, name, ordinal)
                workflow_path = run_dir / "analysis" / "profile_harness_run.json"
                workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
                segment_id = profile_harness_module.default_followup_layout(
                    focused
                ).segment_id
                workflow["follow_up_actions"] = [
                    {
                        "id": "collect_default_metric_followup",
                        "segment_id": segment_id,
                        "status": "succeeded",
                        "target_selection": focused,
                        "target_scope": {"kind": "focused_subset"},
                    }
                ]
                workflow_path.write_text(
                    json.dumps(workflow, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                flat_root = (
                    run_dir
                    / "reports"
                    / "followups"
                    / segment_id
                    / "OPPROF_20260731234035_UIFNUDWBCPGKNZAZ"
                )
                shutil.copytree(
                    REAL_DEFAULT_VECTOR_FIXTURE / "reports" / "OPPROF_001",
                    flat_root,
                )
                basic = flat_root / "OpBasicInfo.csv"
                basic.write_text(
                    "Op Name,Op Type,Task Duration(us),Block Dim\n"
                    "rr17_paco_complete_gram_kernel_mix_aic,mix,21.16,17\n",
                    encoding="utf-8",
                )
                if case == "multiple_roots":
                    shutil.copytree(flat_root, flat_root.parent / "OPPROF_SECOND")
                elif case == "multiple_basic":
                    shutil.copy2(basic, flat_root / "OpBasicInfo_20260731234035000.csv")
                elif case == "empty_basic":
                    basic.write_text("Op Name,Task Duration(us)\n", encoding="utf-8")
                elif case == "invalid_basic":
                    basic.write_bytes(b"\xff")
                elif case == "multirow_basic":
                    basic.write_text(
                        "Op Name,Task Duration(us)\n"
                        "rr17_paco_complete_gram_kernel_mix_aic,21.16\n"
                        "rr17_paco_complete_gram_kernel_mix_aic,21.17\n",
                        encoding="utf-8",
                    )
                elif case == "name_mismatch":
                    basic.write_text(
                        "Op Name,Task Duration(us)\n"
                        "rr17_paco_complete_other_kernel_mix_aic,21.16\n",
                        encoding="utf-8",
                    )
                elif case == "nonflat_unkeyed_path":
                    unexpected = flat_root / "unexpected"
                    unexpected.mkdir()
                    for path in flat_root.glob("*.csv"):
                        path.rename(unexpected / path.name)

                model = evidence_model.write_evidence_model(run_dir)
                summary = model.summary
                raw_index = model.raw_artifact_index

                segment = f"followup:{segment_id}"
                focused_segment = summary["profile_coverage"]["segments"][segment]
                self.assertEqual(focused_segment["observed_total"], 0)
                self.assertFalse(focused_segment["count_complete"])
                self.assertEqual(focused_segment["target_identity"]["status"], "missing_observed")
                self.assertFalse(
                    any(
                        item.get("launch_key")
                        for item in raw_index["artifacts"]
                        if item.get("segment") == segment
                    )
                )
                candidate = build_candidate_summary(run_dir)
                family_questions = {
                    item["id"]: item
                    for item in candidate["design_feedback"]["questions"]
                    if item["id"] in {"memory_cache", "pipe_arithmetic"}
                }
                self.assertFalse(
                    any(
                        item.get("segment") == segment
                        for question in family_questions.values()
                        for item in question["available_evidence"]
                    )
                )

    def test_complete_program_default_feedback_has_no_scope_coverage_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            target = declared_target(("kernel_a", 1), selector="kernel_a")
            write_declared_target(run_dir, target)
            write_candidate_context(run_dir)
            write_app_launches(run_dir, ["kernel_a"])
            write_operator_launch(run_dir, "kernel_a", 0)
            workflow_path = run_dir / "analysis" / "profile_harness_run.json"
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            workflow["follow_up_actions"] = [
                {
                    "id": "collect_default_metric_followup",
                    "segment_id": "collect_default_metric_followup",
                    "status": "succeeded",
                    "target_selection": target,
                    "target_scope": {"kind": "complete_program"},
                }
            ]
            workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
            write_operator_launch(
                run_dir,
                "kernel_a",
                0,
                segment="followup:collect_default_metric_followup",
                families=(
                    "pipe_utilization",
                    "arithmetic_utilization",
                    "l2_cache",
                    "memory",
                    "resource_conflict",
                ),
            )

            model = evidence_model.write_evidence_model(run_dir)
            candidate = build_candidate_summary(run_dir)
            questions = {item["id"]: item for item in candidate["design_feedback"]["questions"]}

            self.assertEqual(
                model.summary["profile_coverage"]["selected_segments_by_family"]["memory"],
                "followup:collect_default_metric_followup",
            )
            self.assertEqual([], model.summary["next_collection_actions"])
            self.assertEqual([], questions["memory_cache"]["missing_evidence"])
            self.assertEqual([], questions["pipe_arithmetic"]["missing_evidence"])
            self.assertFalse(
                any(
                    "complete-program" in str(item.get("role"))
                    for question in (questions["memory_cache"], questions["pipe_arithmetic"])
                    for item in question["missing_evidence"]
                )
            )

            stale_summary_path = run_dir / "analysis" / "summary.json"
            stale_summary = json.loads(stale_summary_path.read_text(encoding="utf-8"))
            for family in ("arithmetic_utilization", "memory", "l2_cache", "resource_conflict"):
                stale_summary["profile_coverage"]["selected_segments_by_family"][family] = None
            stale_summary_path.write_text(json.dumps(stale_summary), encoding="utf-8")
            stale_candidate = build_candidate_summary(run_dir)
            stale_questions = {
                item["id"]: item
                for item in stale_candidate["design_feedback"]["questions"]
            }
            self.assertFalse(
                any(
                    item.get("segment") == "followup:collect_default_metric_followup"
                    and "scope-local" in str(item.get("role"))
                    for question in (stale_questions["memory_cache"], stale_questions["pipe_arithmetic"])
                    for item in question["available_evidence"]
                )
            )

    def test_partial_focused_family_distinguishes_parsed_artifacts_from_missing_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            program = declared_target(("kernel_a", 1), ("kernel_b", 1), selector="kernel_*")
            focused = declared_target(("kernel_b", 1), selector="kernel_b")
            write_declared_target(run_dir, program)
            write_candidate_context(run_dir)
            write_app_launches(run_dir, ["kernel_a", "kernel_b"])
            write_operator_launch(run_dir, "kernel_a", 0)
            write_operator_launch(run_dir, "kernel_b", 0)

            focused_segment_id = profile_harness_module.default_followup_layout(
                focused
            ).segment_id
            workflow_path = run_dir / "analysis" / "profile_harness_run.json"
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            workflow["follow_up_actions"] = [
                {
                    "id": "collect_default_metric_followup",
                    "segment_id": focused_segment_id,
                    "status": "succeeded",
                    "target_selection": focused,
                    "target_scope": {"kind": "focused_subset"},
                }
            ]
            workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
            launch = write_operator_launch(
                run_dir,
                "kernel_b",
                0,
                segment=f"followup:{focused_segment_id}",
                families=("memory",),
            )

            complete_model = evidence_model.write_evidence_model(run_dir)
            complete_candidate = build_candidate_summary(run_dir)
            complete_memory = next(
                item
                for item in complete_candidate["design_feedback"]["questions"]
                if item["id"] == "memory_cache"
            )
            segment = f"followup:{focused_segment_id}"
            complete_scoped = [
                item
                for item in complete_memory["available_evidence"]
                if item.get("segment") == segment
            ]
            self.assertEqual(
                {Path(item["artifact"]).name.split("_", 1)[0] for item in complete_scoped},
                {"Memory", "MemoryL0", "MemoryUB"},
            )
            self.assertEqual(
                next(
                    item["metric_scope"]
                    for item in complete_model.summary["evidence_readiness"]["segments"]
                    if item["segment"] == segment
                ),
                "Default",
            )
            self.assertEqual(
                complete_model.summary["target_identity"]["segments"][segment]["expected"]["names"],
                ["kernel_b"],
            )

            next(launch.glob("MemoryUB*.csv")).unlink()

            model = evidence_model.write_evidence_model(run_dir)
            candidate = build_candidate_summary(run_dir)
            memory = next(
                item
                for item in candidate["design_feedback"]["questions"]
                if item["id"] == "memory_cache"
            )
            self.assertTrue(model.summary["profile_coverage"]["segments"][segment]["count_complete"])
            self.assertFalse(
                model.summary["profile_coverage"]["segments"][segment]["metric_coverage"]["memory"]["complete"]
            )
            self.assertIsNone(
                model.summary["profile_coverage"]["selected_segments_by_family"]["memory"]
            )
            self.assertFalse(
                any(item.get("segment") == segment for item in memory["available_evidence"])
            )
            self.assertIn(
                "missing complete-program memory_cache profiler coverage",
                memory["blocked_by"],
            )
            parsed_incomplete = [
                item
                for item in memory["missing_evidence"]
                if item.get("segment") == segment
            ]
            self.assertEqual(
                {Path(item["artifact"]).name.split("_", 1)[0] for item in parsed_incomplete},
                {"Memory", "MemoryL0"},
            )
            self.assertTrue(
                all(
                    item["target_scope"]["kind"] == "focused_subset"
                    and item["role"] == "scope-local artifact is parsed but its metric-family coverage is incomplete"
                    for item in parsed_incomplete
                )
            )
            absent = {
                item["artifact"]: item["role"]
                for item in memory["missing_evidence"]
                if item.get("segment") is None
            }
            self.assertEqual(absent["MemoryUB.csv"], "memory_cache artifact is missing")
            self.assertEqual(absent["L2Cache.csv"], "memory_cache artifact is missing")

    def test_frequency_quality_is_cited_context_without_readiness_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            target = declared_target(("kernel_a", 2))
            write_declared_target(run_dir, target)
            write_app_launches(run_dir, ["kernel_a", "kernel_a"])
            launches = [
                write_operator_launch(run_dir, "kernel_a", ordinal)
                for ordinal in range(2)
            ]
            for launch in launches:
                (launch / "OpBasicInfo_20260730130344937.csv").write_text(
                    "Op Name,Task Duration(us),Block Dim,Current Freq,Rated Freq\n"
                    "kernel_a,20,8,1800,1800\n",
                    encoding="utf-8",
                )

            stable_summary, stable_index = evidence_model.build_evidence_model(run_dir)
            stable_verdict = RunEvidence.from_loaded(
                run_dir,
                stable_summary,
                raw_artifact_index=stable_index,
            ).single_run_feedback_verdict().as_payload()
            (launches[1] / "OpBasicInfo_20260730130344937.csv").write_text(
                "Op Name,Task Duration(us),Block Dim,Current Freq,Rated Freq\n"
                "kernel_a,20,8,800,1800\n",
                encoding="utf-8",
            )

            mixed_summary, mixed_index = evidence_model.build_evidence_model(run_dir)
            mixed_verdict = RunEvidence.from_loaded(
                run_dir,
                mixed_summary,
                raw_artifact_index=mixed_index,
            ).single_run_feedback_verdict().as_payload()
            frequency = mixed_summary["measurement_quality"]["frequency"]
            group = frequency["groups"][0]

            self.assertEqual(mixed_summary["analysis_schema_version"], "1.5")
            self.assertEqual(group["current_frequencies_mhz"], [800.0, 1800.0])
            self.assertEqual(group["rated_frequencies_mhz"], [1800.0])
            self.assertEqual(group["below_rated_launch_count"], 1)
            self.assertTrue(group["mixed_frequency"])
            self.assertTrue(group["observations"][0]["artifact"])
            self.assertTrue(group["observations"][0]["current_frequency_field_ref"].startswith("artifacts["))
            self.assertTrue(any("measurement quality: frequency variation" in item for item in mixed_summary["warnings"]))
            self.assertEqual(mixed_summary["evidence_readiness"], stable_summary["evidence_readiness"])
            self.assertEqual(mixed_summary["optimization_directions"], stable_summary["optimization_directions"])
            self.assertEqual(mixed_verdict, stable_verdict)

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
