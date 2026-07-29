"""Profile Harness tests."""

from tests.helpers_shared import *  # noqa: F401,F403


class ProfileHarnessTests(unittest.TestCase):
    def test_profile_harness_run_logged_uses_command_runner_and_writes_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "runner_success"
            cwd = Path(tmp) / "work"
            cwd.mkdir()
            runner = RecordingCommandRunner(stdout="out\n", stderr="err\n", returncode=0)

            result = profile_harness_module.run_logged(
                ["msprof", "--version"],
                run_dir,
                command_name="command_msprof.txt",
                log_stem="msprof_default",
                cwd=cwd,
                runner=runner,
            )

            self.assertEqual(result.status, "succeeded")
            self.assertEqual(result.returncode, 0)
            self.assertEqual(runner.calls, [{"command": ["msprof", "--version"], "cwd": cwd, "timeout_s": None}])
            self.assertEqual((run_dir / "logs" / "command_msprof.txt").read_text(encoding="utf-8"), "msprof --version\n")
            self.assertEqual((run_dir / "logs" / "msprof_default.stdout").read_text(encoding="utf-8"), "out\n")
            self.assertEqual((run_dir / "logs" / "msprof_default.stderr").read_text(encoding="utf-8"), "err\n")
            self.assertEqual((run_dir / "logs" / "msprof_default.status").read_text(encoding="utf-8"), "0\n")

    def test_profile_harness_run_logged_records_nonfatal_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "runner_failure"
            cwd = Path(tmp) / "work"
            cwd.mkdir()
            runner = RecordingCommandRunner(stderr="failed\n", returncode=9)

            result = profile_harness_module.run_logged(
                ["msprof", "op", "simulator"],
                run_dir,
                command_name="command_msprof_simulator.txt",
                log_stem="msprof_simulator",
                cwd=cwd,
                fatal=False,
                runner=runner,
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.returncode, 9)
            self.assertEqual((run_dir / "logs" / "msprof_simulator.stderr").read_text(encoding="utf-8"), "failed\n")
            self.assertEqual((run_dir / "logs" / "msprof_simulator.status").read_text(encoding="utf-8"), "9\n")

    def test_profile_harness_run_logged_records_nonfatal_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "runner_timeout"
            cwd = Path(tmp) / "work"
            cwd.mkdir()
            runner = RecordingCommandRunner(stdout="partial\n", stderr="slow", timeout=True)

            result = profile_harness_module.run_logged(
                ["msprof", "op", "simulator"],
                run_dir,
                command_name="command_msprof_simulator.txt",
                log_stem="msprof_simulator",
                cwd=cwd,
                timeout_s=0.01,
                fatal=False,
                runner=runner,
            )

            self.assertEqual(result.status, "timeout")
            self.assertIsNone(result.returncode)
            self.assertEqual(runner.calls[0]["timeout_s"], 0.01)
            self.assertEqual((run_dir / "logs" / "msprof_simulator.stdout").read_text(encoding="utf-8"), "partial\n")
            self.assertEqual(
                (run_dir / "logs" / "msprof_simulator.stderr").read_text(encoding="utf-8"),
                "slow\nmsprof_simulator timed out after 0.01 seconds\n",
            )
            self.assertEqual((run_dir / "logs" / "msprof_simulator.status").read_text(encoding="utf-8"), "timeout\n")

    def test_profile_harness_workflow_routes_commands_through_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "workflow_runner"
            manifest, application = write_profile_harness_fixture(run_dir)
            runner = RecordingCommandRunner(
                responses=[
                    {"stdout": "app\n", "returncode": 0},
                    {"stdout": "op\n", "returncode": 0},
                    {"stdout": "default\n", "returncode": 0},
                    {"stderr": "sim failed\n", "returncode": 9},
                ]
            )

            with mock.patch.object(profile_harness_module, "run_profile_harness_analysis") as run_analysis:
                result = profile_harness_module._run_profile_harness_workflow(
                    profile_harness_module.ProfileHarnessRequest(
                        run_dir=run_dir,
                        manifest_path=manifest,
                        application_path=None,
                        verify_json_path=None,
                        preset_id="full",
                        simulator_enabled=True,
                        simulator_timeout_s=1.5,
                    ),
                    runner=runner,
                )

            self.assertEqual(result.workflow_path, run_dir.resolve() / "analysis" / "profile_harness_run.json")
            self.assertEqual(
                list(result.command_results),
                ["msprof", "msprof_op", "msprof_default_followup", "msprof_simulator"],
            )
            self.assertEqual(result.command_results["msprof_simulator"].status, "failed")
            self.assertTrue(any("optional simulator collection failed" in item for item in result.simulator_warnings))
            self.assertTrue(result.analysis_reran)
            run_analysis.assert_called_once_with(run_dir.resolve())
            self.assertEqual(len(runner.calls), 4)
            self.assertTrue(all(call["cwd"] == application.parent for call in runner.calls))
            self.assertEqual(runner.calls[3]["timeout_s"], 1.5)
            self.assertEqual(runner.calls[0]["command"][0], "msprof")
            self.assertEqual(runner.calls[1]["command"][:2], ["msprof", "op"])
            self.assertEqual(runner.calls[2]["command"][:2], ["msprof", "op"])
            self.assertIn("--aic-metrics=Default", runner.calls[2]["command"])
            self.assertEqual(runner.calls[3]["command"][:3], ["msprof", "op", "simulator"])
            self.assertEqual((run_dir / "logs" / "msprof_simulator.status").read_text(encoding="utf-8"), "9\n")
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["simulator"]["status"], "failed")
            self.assertTrue(any("optional simulator collection failed" in item for item in workflow["warnings"]))
            context = json.loads((run_dir / "analysis" / "profile_context.json").read_text(encoding="utf-8"))
            self.assertTrue(any("optional simulator collection failed" in item for item in context["warnings"]))

    def test_profile_harness_workflow_records_simulator_timeout_through_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "workflow_runner_timeout"
            manifest, application = write_profile_harness_fixture(run_dir)
            runner = RecordingCommandRunner(
                responses=[
                    {"stdout": "app\n", "returncode": 0},
                    {"stdout": "op\n", "returncode": 0},
                    {"stderr": "slow simulator", "timeout": True},
                ]
            )

            with mock.patch.object(profile_harness_module, "run_profile_harness_analysis") as run_analysis:
                result = profile_harness_module._run_profile_harness_workflow(
                    profile_harness_module.ProfileHarnessRequest(
                        run_dir=run_dir,
                        manifest_path=manifest,
                        application_path=None,
                        verify_json_path=None,
                        simulator_enabled=True,
                        simulator_timeout_s=0.25,
                    ),
                    runner=runner,
                )

            self.assertEqual(result.command_results["msprof_simulator"].status, "timeout")
            self.assertIsNone(result.command_results["msprof_simulator"].returncode)
            self.assertTrue(any("optional simulator collection timed out" in item for item in result.simulator_warnings))
            self.assertEqual(len(runner.calls), 3)
            self.assertTrue(all(call["cwd"] == application.parent for call in runner.calls))
            self.assertEqual(runner.calls[2]["timeout_s"], 0.25)
            run_analysis.assert_called_once_with(run_dir.resolve())
            self.assertEqual((run_dir / "logs" / "msprof_simulator.status").read_text(encoding="utf-8"), "timeout\n")
            self.assertEqual(
                (run_dir / "logs" / "msprof_simulator.stderr").read_text(encoding="utf-8"),
                "slow simulator\nmsprof_simulator timed out after 0.25 seconds\n",
            )
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["simulator"]["status"], "timeout")
            self.assertTrue(any("optional simulator collection timed out" in item for item in workflow["warnings"]))
            context = json.loads((run_dir / "analysis" / "profile_context.json").read_text(encoding="utf-8"))
            self.assertTrue(any("optional simulator collection timed out" in item for item in context["warnings"]))

    def test_profile_harness_continue_workflow_records_default_failure_through_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "continue_runner_failure"
            application = write_continue_followup_inputs(run_dir)
            runner = RecordingCommandRunner(stderr="default failed\n", returncode=8)

            with mock.patch.object(
                profile_harness_module,
                "run_profile_harness_analysis",
                side_effect=AssertionError("analysis should not rerun after failed follow-up"),
            ):
                with self.assertRaisesRegex(RuntimeError, "Default follow-up failed"):
                    profile_harness_module._run_continue_followups_workflow(
                        profile_harness_module.ContinueFollowupsRequest(run_dir=run_dir),
                        runner=runner,
                    )

            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(runner.calls[0]["cwd"], application.parent)
            self.assertIn("--aic-metrics=Default", runner.calls[0]["command"])
            self.assertEqual(
                (run_dir / "logs" / "command_msprof_followup_collect_default_metric_followup.txt").read_text(
                    encoding="utf-8"
                ),
                (
                    "msprof op "
                    f"--output={run_dir / 'reports' / 'followups' / 'collect_default_metric_followup'} "
                    f"--application={application} --aic-metrics=Default\n"
                ),
            )
            self.assertEqual(
                (run_dir / "logs" / "msprof_followup_collect_default_metric_followup.status").read_text(
                    encoding="utf-8"
                ),
                "8\n",
            )
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            record = workflow["follow_up_actions"][0]
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["returncode"], 8)
            self.assertEqual(workflow["commands"]["msprof_default_followup"], "logs/command_msprof_followup_collect_default_metric_followup.txt")
            self.assertNotIn("default", workflow["outputs"])

    def test_profile_harness_continue_workflow_records_default_timeout_through_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "continue_runner_timeout"
            application = write_continue_followup_inputs(run_dir)
            runner = RecordingCommandRunner(stderr="slow default", timeout=True)

            with mock.patch.object(
                profile_harness_module,
                "run_profile_harness_analysis",
                side_effect=AssertionError("analysis should not rerun after timed-out follow-up"),
            ):
                with self.assertRaisesRegex(RuntimeError, "Default follow-up timeout"):
                    profile_harness_module._run_continue_followups_workflow(
                        profile_harness_module.ContinueFollowupsRequest(run_dir=run_dir),
                        runner=runner,
                    )

            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(runner.calls[0]["cwd"], application.parent)
            self.assertIn("--aic-metrics=Default", runner.calls[0]["command"])
            self.assertEqual(
                (run_dir / "logs" / "msprof_followup_collect_default_metric_followup.status").read_text(
                    encoding="utf-8"
                ),
                "timeout\n",
            )
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            record = workflow["follow_up_actions"][0]
            self.assertEqual(record["status"], "timeout")
            self.assertIsNone(record["returncode"])
            self.assertEqual(record["reason"], "Default follow-up timeout")
            self.assertEqual(workflow["commands"]["msprof_default_followup"], "logs/command_msprof_followup_collect_default_metric_followup.txt")
            self.assertNotIn("default", workflow["outputs"])

    def test_profile_harness_continue_workflow_reruns_analysis_after_default_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "continue_runner_success"
            application = write_continue_followup_inputs(run_dir)
            runner = RecordingCommandRunner(stdout="default ok\n", returncode=0)

            with mock.patch.object(profile_harness_module, "run_profile_harness_analysis") as run_analysis:
                result = profile_harness_module._run_continue_followups_workflow(
                    profile_harness_module.ContinueFollowupsRequest(run_dir=run_dir),
                    runner=runner,
                )

            self.assertTrue(result.analysis_reran)
            self.assertEqual(result.command_results["msprof_default_followup"].status, "succeeded")
            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(runner.calls[0]["cwd"], application.parent)
            run_analysis.assert_called_once_with(run_dir.resolve())
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            record = workflow["follow_up_actions"][0]
            self.assertEqual(record["status"], "succeeded")
            self.assertEqual(record["reason"], "needs Default metric scope")
            self.assertEqual(record["returncode"], 0)
            self.assertEqual(workflow["commands"]["msprof_default_followup"], "logs/command_msprof_followup_collect_default_metric_followup.txt")
            self.assertEqual(workflow["outputs"]["default"], "reports/followups/collect_default_metric_followup")

    def test_profile_harness_continue_workflow_skipped_followup_does_not_rerun_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "continue_runner_skipped"
            write_continue_followup_inputs(
                run_dir,
                summary={
                    "target_identity": {"status": "match"},
                    "next_collection_actions": [{"id": "collect_roofline_followup"}],
                },
            )
            runner = RecordingCommandRunner()

            with mock.patch.object(
                profile_harness_module,
                "run_profile_harness_analysis",
                side_effect=AssertionError("analysis should not rerun after skipped follow-up"),
            ):
                result = profile_harness_module._run_continue_followups_workflow(
                    profile_harness_module.ContinueFollowupsRequest(run_dir=run_dir),
                    runner=runner,
                )

            self.assertFalse(result.analysis_reran)
            self.assertEqual(runner.calls, [])
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            record = workflow["follow_up_actions"][0]
            self.assertEqual(record["id"], "collect_roofline_followup")
            self.assertEqual(record["status"], "skipped")
            self.assertNotIn("msprof_default_followup", workflow["commands"])
            self.assertNotIn("default", workflow["outputs"])

    def test_profile_harness_manifest_orchestrates_fake_msprof_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "candidate"
            manifest, application = write_profile_harness_fixture(run_dir)
            verify_json = write_verify_json(run_dir / "context" / "verify.json")
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--verify-json",
                    str(verify_json),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertIn("wrote", result.stdout)
            self.assertTrue((run_dir / "logs" / "command_msprof.txt").exists())
            self.assertTrue((run_dir / "logs" / "command_msprof_op.txt").exists())
            self.assertFalse((run_dir / "logs" / "command_msprof_simulator.txt").exists())
            self.assertIn(str(application.resolve()), (run_dir / "logs" / "command_msprof.txt").read_text())
            self.assertTrue((run_dir / "reports" / "app" / "PROF_001" / "mindstudio_profiler_output" / "op_summary_001.csv").exists())
            self.assertTrue((run_dir / "reports" / "op" / "OPPROF_001" / "PipeUtilization.csv").exists())
            self.assertTrue((run_dir / "analysis" / "provenance.json").exists())
            self.assertTrue((run_dir / "analysis" / "summary.json").exists())
            self.assertTrue((run_dir / "analysis" / "raw_artifact_index.json").exists())
            self.assertTrue((run_dir / "analysis" / "key_metrics.txt").exists())
            self.assertTrue((run_dir / "analysis" / "profile_context.json").exists())
            self.assertTrue((run_dir / "REPORT.md").exists())

            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["workflow"], "generic profile harness profiling workflow")
            self.assertEqual(workflow["inputs"]["manifest"], "harness/profile_harness.json")
            self.assertEqual(workflow["inputs"]["application"], "harness/run.sh")
            self.assertEqual(workflow["inputs"]["application_resolved_path"], str(application.resolve()))
            self.assertEqual(workflow["inputs"]["verify_json"], "context/verify.json")
            self.assertEqual(workflow["boundary"]["benchmark_renderer_owned_by"], "caller_or_benchmark_skill")
            self.assertEqual(workflow["profile_harness"]["workload"]["id"], "generic/profile-harness/v1")
            self.assertEqual(workflow["collection_plan"]["preset_id"], "triage")
            self.assertEqual(workflow["collection_plan"]["source"], "profile_harness_preset")
            self.assertEqual(
                [segment["segment_id"] for segment in workflow["collection_plan"]["segments"]],
                ["app", "op"],
            )
            self.assertEqual(workflow["collection_plan"]["segments"][1]["metric_scope"], "PipeUtilization")

            context = json.loads((run_dir / "analysis" / "profile_context.json").read_text(encoding="utf-8"))
            self.assertEqual(context["sources"]["profile_harness_manifest"]["artifact"], "harness/profile_harness.json")
            self.assertEqual(context["sources"]["application"]["artifact"], "harness/run.sh")
            self.assertEqual(context["sources"]["application"]["resolved_path"], str(application.resolve()))
            self.assertEqual(context["sources"]["verify_json"]["artifact"], "context/verify.json")
            self.assertEqual(context["profile_harness"]["workload"]["id"], "generic/profile-harness/v1")
            self.assertEqual(context["benchmark"]["workload"]["id"], "verify/generic")
            self.assertEqual(context["verify_context"]["evidence_role"], "correctness_and_timing_context_only")

            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("### Profile Harness Context", report)
            self.assertIn("- Collection plan: triage; segments: app, op; source: profile_harness_preset", report)
            self.assertIn("`analysis/profile_context.json`; `sources.verify_json.artifact`", report)
            self.assertIn("context only; source: `analysis/profile_context.json`; `benchmark.workload`", report)
            self.assertIn("Highest application-level operator duration", report)

            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["headlines"]["op_summary"]["name"], "harness_kernel")
            self.assertEqual(summary["headlines"]["pipe_utilization"]["value"], 66.5)
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["collection_plan"]["preset_id"], "triage")
            self.assertIn("analysis/profile_harness_run.json", provenance["sources"])

    def test_profile_harness_analysis_pipeline_uses_evidence_model_not_analyzer_cli(self):
        from ascend_msprof_skill import analyze_msprof_outputs

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp), "pipeline_evidence_model")
            with mock.patch.object(analyze_msprof_outputs, "main", side_effect=AssertionError("wrong analyzer path")):
                profile_harness_module.run_analysis_pipeline(run_dir)

            self.assertTrue((run_dir / "analysis" / "provenance.json").exists())
            self.assertTrue((run_dir / "analysis" / "summary.json").exists())
            self.assertTrue((run_dir / "analysis" / "raw_artifact_index.json").exists())
            self.assertTrue((run_dir / "analysis" / "key_metrics.txt").exists())
            self.assertTrue((run_dir / "REPORT.md").exists())

    def test_profile_harness_analysis_pipeline_runs_steps_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "analysis_order"
            order = []

            with (
                mock.patch.object(
                    profile_harness_module.generate_provenance,
                    "main",
                    side_effect=lambda argv: order.append(("provenance", argv)),
                ),
                mock.patch.object(
                    profile_harness_module.evidence_model,
                    "write_evidence_model",
                    side_effect=lambda path: order.append(("evidence_model", path)),
                ),
                mock.patch.object(
                    profile_harness_module.extract_simulator_hotspots,
                    "main",
                    side_effect=lambda argv: order.append(("simulator_hotspots", argv)),
                ),
                mock.patch.object(
                    profile_harness_module.plot_timeline,
                    "main",
                    side_effect=lambda argv: order.append(("timeline", argv)),
                ),
                mock.patch.object(
                    profile_harness_module.generate_report,
                    "main",
                    side_effect=lambda argv: order.append(("report", argv)),
                ),
            ):
                profile_harness_module.run_profile_harness_analysis(run_dir)

            self.assertEqual(
                order,
                [
                    ("provenance", ["--run-dir", str(run_dir)]),
                    ("evidence_model", run_dir),
                    ("simulator_hotspots", ["--run-dir", str(run_dir)]),
                    ("timeline", ["--run-dir", str(run_dir)]),
                    ("report", ["--run-dir", str(run_dir)]),
                ],
            )

    def test_profile_harness_cli_validator_preserves_error_messages(self):
        base = {
            "simulator_timeout_s": None,
            "simulator": False,
            "follow_next_actions": False,
            "continue_from_summary": False,
            "manifest": Path("manifest.json"),
            "application": None,
            "verify_json": None,
            "preset": "triage",
        }
        cases = [
            (
                {"simulator_timeout_s": 0, "simulator": True},
                "--simulator-timeout-s must be greater than 0",
            ),
            (
                {"simulator_timeout_s": 1},
                "--simulator-timeout-s requires --simulator",
            ),
            (
                {"follow_next_actions": True},
                "--follow-next-actions and --continue-from-summary must be used together",
            ),
            (
                {
                    "follow_next_actions": True,
                    "continue_from_summary": True,
                    "manifest": Path("manifest.json"),
                },
                "--continue-from-summary reuses existing workflow inputs; omit --manifest, --application, and --verify-json",
            ),
            (
                {
                    "follow_next_actions": True,
                    "continue_from_summary": True,
                    "manifest": None,
                    "simulator": True,
                },
                "--continue-from-summary does not run simulator collection",
            ),
            (
                {
                    "follow_next_actions": True,
                    "continue_from_summary": True,
                    "manifest": None,
                    "preset": "full",
                },
                "--continue-from-summary cannot be combined with --preset orchestration",
            ),
            (
                {"manifest": None, "application": None},
                "either --manifest or --application is required",
            ),
        ]

        for overrides, expected in cases:
            with self.subTest(expected=expected):
                args = argparse.Namespace(**{**base, **overrides})
                self.assertEqual(profile_harness_module.validate_profile_harness_cli_args(args), expected)

        self.assertIsNone(profile_harness_module.validate_profile_harness_cli_args(argparse.Namespace(**base)))
        continue_args = argparse.Namespace(
            **{
                **base,
                "manifest": None,
                "follow_next_actions": True,
                "continue_from_summary": True,
            }
        )
        self.assertIsNone(profile_harness_module.validate_profile_harness_cli_args(continue_args))

    def test_profile_harness_explicit_triage_preset_matches_default_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "triage_preset"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--preset",
                    "triage",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertTrue((run_dir / "logs" / "command_msprof.txt").exists())
            self.assertTrue((run_dir / "logs" / "command_msprof_op.txt").exists())
            self.assertFalse(
                (run_dir / "logs" / "command_msprof_followup_collect_default_metric_followup.txt").exists()
            )
            self.assertFalse((run_dir / "logs" / "command_msprof_simulator.txt").exists())
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["collection_plan"]["preset_id"], "triage")
            self.assertEqual(
                [segment["segment_id"] for segment in workflow["collection_plan"]["segments"]],
                ["app", "op"],
            )

    def test_profile_harness_default_depth_preset_collects_default_followup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "default_depth"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--preset",
                    "default-depth",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            followup_command = run_dir / "logs" / "command_msprof_followup_collect_default_metric_followup.txt"
            self.assertTrue(followup_command.exists())
            self.assertIn("--aic-metrics=Default", followup_command.read_text(encoding="utf-8"))
            self.assertTrue(
                (
                    run_dir
                    / "reports"
                    / "followups"
                    / "collect_default_metric_followup"
                    / "OPPROF_001"
                    / "ArithmeticUtilization.csv"
                ).exists()
            )
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["collection_plan"]["preset_id"], "default-depth")
            self.assertEqual(
                [segment["segment_id"] for segment in workflow["collection_plan"]["segments"]],
                ["app", "op", "default"],
            )
            self.assertEqual(
                workflow["outputs"]["default"],
                "reports/followups/collect_default_metric_followup",
            )
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            self.assertIn("collect_default_metric_followup", provenance["profile_output_segments"]["followups"])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["headlines"]["arithmetic_utilization"]["metric_scope"], "Default")

    def test_profile_harness_follow_next_actions_collects_default_followup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "follow_next_default"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            initial_summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            self.assertIn(
                "collect_default_metric_followup",
                {action["id"] for action in initial_summary["next_collection_actions"]},
            )

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                    "--continue-from-summary",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            followup_command = run_dir / "logs" / "command_msprof_followup_collect_default_metric_followup.txt"
            self.assertTrue(followup_command.exists())
            self.assertIn("--aic-metrics=Default", followup_command.read_text(encoding="utf-8"))
            self.assertTrue(
                (
                    run_dir
                    / "reports"
                    / "followups"
                    / "collect_default_metric_followup"
                    / "OPPROF_001"
                    / "ArithmeticUtilization.csv"
                ).exists()
            )
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["commands"]["msprof_default_followup"], "logs/command_msprof_followup_collect_default_metric_followup.txt")
            self.assertEqual(workflow["outputs"]["default"], "reports/followups/collect_default_metric_followup")
            self.assertEqual(workflow["follow_up_actions"][0]["id"], "collect_default_metric_followup")
            self.assertEqual(workflow["follow_up_actions"][0]["status"], "succeeded")
            self.assertEqual(workflow["follow_up_actions"][0]["command_key"], "msprof_default_followup")
            self.assertEqual(workflow["follow_up_actions"][0]["output_key"], "default")
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["headlines"]["arithmetic_utilization"]["metric_scope"], "Default")
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            self.assertIn("collect_default_metric_followup", provenance["profile_output_segments"]["followups"])

    def test_profile_harness_follow_next_actions_skips_unsupported_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "follow_next_unsupported"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            summary_path = run_dir / "analysis" / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["next_collection_actions"] = [
                {"id": "collect_source_or_context", "reason": "needs simulator context"},
                {"id": "unknown_action", "reason": "not supported"},
            ]
            summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                    "--continue-from-summary",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertFalse(
                (run_dir / "logs" / "command_msprof_followup_collect_default_metric_followup.txt").exists()
            )
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            actions = {item["id"]: item for item in workflow["follow_up_actions"]}
            self.assertEqual(actions["collect_source_or_context"]["status"], "skipped")
            self.assertEqual(actions["unknown_action"]["status"], "skipped")
            self.assertNotIn("msprof_default_followup", workflow["commands"])
            self.assertNotIn("default", workflow["outputs"])

    def test_profile_harness_follow_next_actions_uses_readiness_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "follow_next_readiness_fallback"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            summary_path = run_dir / "analysis" / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["next_collection_actions"] = []
            summary["evidence_readiness"]["recommended_followups"] = [
                {"id": "collect_default_metric_followup", "reason": "fallback Default action"}
            ]
            summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                    "--continue-from-summary",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            record = workflow["follow_up_actions"][0]
            self.assertEqual(record["id"], "collect_default_metric_followup")
            self.assertEqual(record["status"], "succeeded")
            self.assertIn("fallback Default action", record["reason"])
            self.assertTrue(
                (
                    run_dir
                    / "reports"
                    / "followups"
                    / "collect_default_metric_followup"
                    / "OPPROF_001"
                    / "ArithmeticUtilization.csv"
                ).exists()
            )

    def test_profile_harness_follow_next_actions_blocks_existing_default_followup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "follow_next_existing_default"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--preset",
                    "default-depth",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            summary_path = run_dir / "analysis" / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["next_collection_actions"] = [{"id": "collect_default_metric_followup", "reason": "recollect"}]
            summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                    "--continue-from-summary",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            record = workflow["follow_up_actions"][0]
            self.assertEqual(record["id"], "collect_default_metric_followup")
            self.assertEqual(record["status"], "blocked")
            self.assertIn("would be overwritten", record["reason"])

    def test_profile_harness_follow_next_actions_failed_default_does_not_record_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "follow_next_default_failure"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            env["FAKE_MSPROF_DEFAULT_FAIL"] = "1"
            env["FAKE_MSPROF_DEFAULT_FAIL_STATUS"] = "8"

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                    "--continue-from-summary",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Default follow-up failed", result.stderr)
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            record = workflow["follow_up_actions"][0]
            self.assertEqual(record["id"], "collect_default_metric_followup")
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["returncode"], 8)
            self.assertEqual(workflow["commands"]["msprof_default_followup"], "logs/command_msprof_followup_collect_default_metric_followup.txt")
            self.assertNotIn("default", workflow["outputs"])

    def test_profile_harness_full_preset_does_not_collect_simulator_without_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "full_without_simulator"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--preset",
                    "full",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertTrue((run_dir / "logs" / "command_msprof_followup_collect_default_metric_followup.txt").exists())
            self.assertFalse((run_dir / "logs" / "command_msprof_simulator.txt").exists())
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["collection_plan"]["preset_id"], "full")
            self.assertEqual(
                [segment["segment_id"] for segment in workflow["collection_plan"]["segments"]],
                ["app", "op", "default"],
            )

    def test_profile_harness_full_preset_with_simulator_records_optional_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "full_with_simulator"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--preset",
                    "full",
                    "--simulator",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["collection_plan"]["preset_id"], "full")
            self.assertEqual(
                [segment["segment_id"] for segment in workflow["collection_plan"]["segments"]],
                ["app", "op", "default", "simulator"],
            )
            simulator_segment = workflow["collection_plan"]["segments"][3]
            self.assertFalse(simulator_segment["required"])
            self.assertEqual(simulator_segment["status"], "succeeded")

    def test_profile_harness_manifest_optional_simulator_collects_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "candidate_simulator"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--simulator",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertTrue((run_dir / "logs" / "command_msprof_simulator.txt").exists())
            self.assertTrue((run_dir / "logs" / "msprof_simulator.stdout").exists())
            self.assertEqual((run_dir / "logs" / "msprof_simulator.status").read_text(encoding="utf-8"), "0\n")
            self.assertTrue((run_dir / "reports" / "sim" / "OPPROF_001" / "simulator" / "trace.json").exists())
            self.assertTrue(
                (
                    run_dir
                    / "reports"
                    / "sim"
                    / "OPPROF_001"
                    / "simulator"
                    / "core0.veccore0"
                    / "core0.veccore0_code_exe.csv"
                ).exists()
            )
            self.assertTrue((run_dir / "analysis" / "simulator_hotspots.json").exists())
            self.assertTrue((run_dir / "REPORT.md").exists())

            command = (run_dir / "logs" / "command_msprof_simulator.txt").read_text(encoding="utf-8")
            self.assertIn("op simulator", command)
            self.assertIn("--aic-metrics=PipeUtilization", command)
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["commands"]["msprof_simulator"], "logs/command_msprof_simulator.txt")
            self.assertEqual(workflow["outputs"]["simulator"], "reports/sim")
            self.assertEqual(
                workflow["simulator"],
                {
                    "aic_metrics": "PipeUtilization",
                    "enabled": True,
                    "required": False,
                    "status": "succeeded",
                },
            )
            self.assertEqual(
                [segment["segment_id"] for segment in workflow["collection_plan"]["segments"]],
                ["app", "op", "simulator"],
            )
            simulator_segment = workflow["collection_plan"]["segments"][2]
            self.assertFalse(simulator_segment["required"])
            self.assertEqual(simulator_segment["status"], "succeeded")
            self.assertEqual(simulator_segment["command_log"], "logs/command_msprof_simulator.txt")
            context = json.loads((run_dir / "analysis" / "profile_context.json").read_text(encoding="utf-8"))
            self.assertEqual(context["warnings"], [])

    def test_profile_harness_application_optional_simulator_collects_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            application = root / "external_run.sh"
            application.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            application.chmod(0o755)
            run_dir = root / "profile" / "direct_application_simulator"
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--application",
                    str(application),
                    "--simulator",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["simulator"]["status"], "succeeded")
            self.assertTrue((run_dir / "reports" / "sim" / "OPPROF_001" / "simulator" / "trace.json").exists())
            self.assertTrue((run_dir / "analysis" / "summary.json").exists())
            self.assertTrue((run_dir / "REPORT.md").exists())

    def test_profile_harness_optional_simulator_failure_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "simulator_failure"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)
            env["FAKE_MSPROF_SIMULATOR_FAIL"] = "1"
            env["FAKE_MSPROF_SIMULATOR_FAIL_STATUS"] = "9"

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--simulator",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertEqual((run_dir / "logs" / "msprof_simulator.status").read_text(encoding="utf-8"), "9\n")
            self.assertTrue((run_dir / "reports" / "app" / "PROF_001" / "mindstudio_profiler_output" / "op_summary_001.csv").exists())
            self.assertTrue((run_dir / "reports" / "op" / "OPPROF_001" / "PipeUtilization.csv").exists())
            self.assertTrue((run_dir / "analysis" / "summary.json").exists())
            self.assertTrue((run_dir / "REPORT.md").exists())

            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["simulator"]["status"], "failed")
            self.assertTrue(any("optional simulator collection failed" in warning for warning in workflow["warnings"]))
            context = json.loads((run_dir / "analysis" / "profile_context.json").read_text(encoding="utf-8"))
            self.assertTrue(any("optional simulator collection failed" in warning for warning in context["warnings"]))

    def test_profile_harness_optional_simulator_timeout_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "simulator_timeout"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)
            env["FAKE_MSPROF_SIMULATOR_SLEEP"] = "1"

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--simulator",
                    "--simulator-timeout-s",
                    "0.01",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertEqual((run_dir / "logs" / "msprof_simulator.status").read_text(encoding="utf-8"), "timeout\n")
            self.assertTrue((run_dir / "analysis" / "summary.json").exists())
            self.assertTrue((run_dir / "REPORT.md").exists())
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["simulator"]["status"], "timeout")
            self.assertTrue(any("optional simulator collection timed out" in warning for warning in workflow["warnings"]))
            context = json.loads((run_dir / "analysis" / "profile_context.json").read_text(encoding="utf-8"))
            self.assertTrue(any("optional simulator collection timed out" in warning for warning in context["warnings"]))

    def test_profile_harness_rejects_simulator_timeout_without_simulator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            application = root / "external_run.sh"
            application.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            application.chmod(0o755)
            run_dir = root / "profile" / "timeout_without_simulator"

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--application",
                    str(application),
                    "--simulator-timeout-s",
                    "1",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--simulator-timeout-s requires --simulator", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())

    def test_profile_harness_rejects_follow_next_without_continue_from_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "follow_without_continue"

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--follow-next-actions and --continue-from-summary must be used together", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())

    def test_profile_harness_continue_from_summary_rejects_fresh_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            application = root / "external_run.sh"
            application.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            application.chmod(0o755)
            run_dir = root / "profile" / "continue_with_application"

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--application",
                    str(application),
                    "--follow-next-actions",
                    "--continue-from-summary",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--continue-from-summary reuses existing workflow inputs", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())

    def test_profile_harness_continue_from_summary_rejects_manual_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = fresh_pipe_l2_run(root / "manual_run")
            run([*CLI, "analyze", "--run-dir", str(run_dir)])

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                    "--continue-from-summary",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("analysis/profile_harness_run.json not found", result.stderr)

    def test_profile_harness_follow_next_actions_blocks_target_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "follow_next_target_mismatch"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            summary_path = run_dir / "analysis" / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["target_identity"] = {"status": "mismatch"}
            summary["next_collection_actions"] = [{"id": "collect_default_metric_followup", "reason": "needs Default"}]
            summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                    "--continue-from-summary",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertFalse(
                (run_dir / "logs" / "command_msprof_followup_collect_default_metric_followup.txt").exists()
            )
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            record = workflow["follow_up_actions"][0]
            self.assertEqual(record["status"], "blocked")
            self.assertEqual(record["consistency"], "blocked")
            self.assertIn("target identity status is mismatch", record["reason"])

    def test_profile_harness_rejects_unknown_preset_before_msprof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            application = root / "external_run.sh"
            application.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            application.chmod(0o755)
            run_dir = root / "profile" / "unknown_preset"

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--application",
                    str(application),
                    "--preset",
                    "memory-depth",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid choice", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())

    def test_profile_harness_application_orchestrates_fake_msprof_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            application = root / "external_run.sh"
            application.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            application.chmod(0o755)
            run_dir = root / "profile" / "direct_application"
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--application",
                    str(application),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertIsNone(workflow["inputs"]["manifest"])
            self.assertEqual(workflow["inputs"]["application"], application.name)
            self.assertEqual(workflow["inputs"]["application_resolved_path"], str(application.resolve()))
            context = json.loads((run_dir / "analysis" / "profile_context.json").read_text(encoding="utf-8"))
            self.assertEqual(context["sources"]["application"]["artifact"], application.name)
            self.assertEqual(context["sources"]["application"]["resolved_path"], str(application.resolve()))
            self.assertTrue((run_dir / "analysis" / "summary.json").exists())
            self.assertTrue((run_dir / "REPORT.md").exists())

    def test_profile_harness_manifest_records_external_application_resolved_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            application = root / "external" / "run.sh"
            application.parent.mkdir()
            application.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            application.chmod(0o755)
            run_dir = root / "profile" / "external_manifest_application"
            manifest = run_dir / "harness" / "profile_harness.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "task": "generic",
                        "application": str(application),
                        "workload": {"id": "generic/external-manifest", "shape": [4, 4], "dtype": "float16"},
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["inputs"]["manifest"], "harness/profile_harness.json")
            self.assertEqual(workflow["inputs"]["application"], application.name)
            self.assertEqual(workflow["inputs"]["application_resolved_path"], str(application.resolve()))
            context = json.loads((run_dir / "analysis" / "profile_context.json").read_text(encoding="utf-8"))
            self.assertEqual(context["sources"]["application"]["artifact"], application.name)
            self.assertEqual(context["sources"]["application"]["resolved_path"], str(application.resolve()))
            self.assertIn(str(application.resolve()), (run_dir / "logs" / "command_msprof.txt").read_text())

    def test_profile_harness_rejects_missing_manifest_before_msprof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "missing_manifest"

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(run_dir / "harness" / "profile_harness.json"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("profile harness manifest not found", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())
            self.assertFalse((run_dir / "reports").exists())

    def test_profile_harness_rejects_invalid_manifest_before_msprof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "bad_manifest"
            manifest = run_dir / "harness" / "profile_harness.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"schema_version": 1}) + "\n", encoding="utf-8")

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing non-empty application", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())
            self.assertFalse((run_dir / "reports").exists())

    def test_profile_harness_rejects_manifest_missing_application_file_before_msprof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "missing_manifest_application"
            manifest = run_dir / "harness" / "profile_harness.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"schema_version": 1, "application": "missing_run.sh"}) + "\n", encoding="utf-8")

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("profile harness application not found", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())
            self.assertFalse((run_dir / "reports").exists())

    def test_profile_harness_rejects_manifest_application_directory_before_msprof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "directory_manifest_application"
            application_dir = run_dir / "harness" / "app_dir"
            application_dir.mkdir(parents=True)
            manifest = run_dir / "harness" / "profile_harness.json"
            manifest.write_text(json.dumps({"schema_version": 1, "application": "app_dir"}) + "\n", encoding="utf-8")

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("profile harness application is not a file", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())
            self.assertFalse((run_dir / "reports").exists())

    def test_profile_harness_rejects_missing_direct_application_before_msprof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "missing_direct_application"

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--application",
                    str(root / "missing_run.sh"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("application not found", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())
            self.assertFalse((run_dir / "reports").exists())

    def test_profile_harness_rejects_stale_collection_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "stale"
            manifest, _application = write_profile_harness_fixture(run_dir)
            stale_report = run_dir / "reports" / "old.csv"
            stale_report.parent.mkdir(parents=True)
            stale_report.write_text("stale\n", encoding="utf-8")

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already contains collection artifacts", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())

    def test_profile_harness_rejects_stale_direct_application_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            application = root / "external_run.sh"
            application.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            application.chmod(0o755)
            run_dir = root / "profile" / "stale_direct"
            stale_report = run_dir / "reports" / "old.csv"
            stale_report.parent.mkdir(parents=True)
            stale_report.write_text("stale\n", encoding="utf-8")

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--application",
                    str(application),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already contains collection artifacts", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())

    def test_verify_json_context_without_profiler_artifacts_does_not_create_profiler_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "profile" / "context_only"
            application = run_dir / "harness" / "run.sh"
            application.parent.mkdir(parents=True)
            application.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            application.chmod(0o755)
            verify_json = write_verify_json(run_dir / "context" / "verify.json")
            verify_data = json.loads(verify_json.read_text(encoding="utf-8"))
            profile_harness_module.write_profile_context(
                run_dir,
                manifest_path=None,
                manifest=None,
                application=application,
                verify_json_path=verify_json,
                verify_json=verify_data,
            )

            generate_report.main(["--run-dir", str(run_dir)])

            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("### Profile Harness Context", report)
            self.assertIn("No headline diagnosis generated", report)
            self.assertNotIn("Highest application-level operator duration", report)
            self.assertNotIn("Inspect Highest application-level operator duration", report)
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            self.assertTrue(all(value is None for value in summary.get("headlines", {}).values()))
