"""Profile Harness tests."""

import signal

from tests.helpers_shared import *  # noqa: F401,F403

from ascend_msprof_skill import _profile_target


class ProfileHarnessTests(unittest.TestCase):
    def test_subprocess_runner_stages_profiler_output_on_local_filesystem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            final_output = root / "durable" / "reports" / "op"
            local_stage_root = root / "local"
            cwd = root / "work"
            cwd.mkdir()
            observed_output = None

            def fake_run(command, **kwargs):
                nonlocal observed_output
                output_arg = next(item for item in command if item.startswith("--output="))
                observed_output = Path(output_arg.removeprefix("--output="))
                (observed_output / "OPPROF_TEST").mkdir(parents=True)
                (observed_output / "OPPROF_TEST" / "OpBasicInfo.csv").write_text(
                    "Op Name\nmain_kernel_mix_aic\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 0, "ok\n", "")

            command = [
                "msprof",
                "op",
                f"--output={final_output}",
                "--application=run.sh",
            ]
            with (
                mock.patch.dict(
                    os.environ,
                    {"ASCEND_MSPROF_STAGE_ROOT": str(local_stage_root)},
                ),
                mock.patch.object(
                    profile_harness_module.subprocess,
                    "run",
                    side_effect=fake_run,
                ),
            ):
                result = profile_harness_module.SubprocessCommandRunner().run(
                    command,
                    cwd=cwd,
                )

            self.assertEqual(result.returncode, 0)
            self.assertTrue(result.output_staged_locally)
            self.assertEqual(result.preserved_output, str(final_output))
            self.assertIsNotNone(observed_output)
            self.assertNotEqual(observed_output, final_output)
            self.assertTrue(str(observed_output).startswith(str(local_stage_root)))
            self.assertEqual(
                (final_output / "OPPROF_TEST" / "OpBasicInfo.csv").read_text(
                    encoding="utf-8"
                ),
                "Op Name\nmain_kernel_mix_aic\n",
            )

    def test_run_logged_timeout_preserves_staged_profiler_output_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "profile" / "timeout_staging"
            final_output = run_dir / "reports" / "op"
            local_stage_root = root / "local"
            cwd = root / "work"
            cwd.mkdir()

            def fake_run(command, **kwargs):
                output_arg = next(
                    item for item in command if item.startswith("--output=")
                )
                staged_output = Path(output_arg.removeprefix("--output="))
                (staged_output / "OPPROF_TIMEOUT").mkdir(parents=True)
                (staged_output / "OPPROF_TIMEOUT" / "partial.csv").write_text(
                    "partial\n",
                    encoding="utf-8",
                )
                raise subprocess.TimeoutExpired(
                    command,
                    kwargs["timeout_s"],
                    output="partial stdout\n",
                    stderr="slow profiler\n",
                )

            with (
                mock.patch.dict(
                    os.environ,
                    {"ASCEND_MSPROF_STAGE_ROOT": str(local_stage_root)},
                ),
                mock.patch.object(
                    profile_harness_module.SubprocessCommandRunner,
                    "_run_subprocess",
                    side_effect=fake_run,
                ),
            ):
                result = profile_harness_module.run_logged(
                    [
                        "msprof",
                        "op",
                        f"--output={final_output}",
                        "--application=run.sh",
                    ],
                    run_dir,
                    command_name="command_msprof_op.txt",
                    log_stem="msprof_op",
                    cwd=cwd,
                    timeout_s=0.01,
                    fatal=False,
                )

            self.assertEqual(result.status, "timeout")
            self.assertTrue(result.output_staged_locally)
            self.assertEqual(result.preserved_output, str(final_output))
            self.assertEqual(
                (final_output / "OPPROF_TIMEOUT" / "partial.csv").read_text(
                    encoding="utf-8"
                ),
                "partial\n",
            )
            receipt = json.loads(
                (run_dir / "logs" / "msprof_op.result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(receipt["output_staged_locally"])
            self.assertEqual(receipt["preserved_output"], str(final_output))

    def test_run_logged_timeout_with_new_core_takes_core_dump_precedence(self):
        class TimingOutCoreRunner(RecordingCommandRunner):
            def run(self, command, *, cwd, timeout_s=None):
                (cwd / "core.timeout").write_bytes(b"core")
                raise subprocess.TimeoutExpired(
                    command,
                    timeout_s,
                    output="partial stdout\n",
                    stderr="slow profiler\n",
                )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "timeout_core_dump"
            cwd = Path(tmp) / "work"
            cwd.mkdir()

            result = profile_harness_module.run_logged(
                ["msprof", "op", "--application=run.sh"],
                run_dir,
                command_name="command_msprof_op.txt",
                log_stem="msprof_op",
                cwd=cwd,
                timeout_s=0.01,
                fatal=False,
                runner=TimingOutCoreRunner(),
            )

            core_path = cwd / "core.timeout"
            self.assertEqual(result.status, "core_dump")
            self.assertIsNone(result.returncode)
            self.assertEqual(result.stdout, "partial stdout\n")
            self.assertIn("timed out", result.stderr)
            self.assertIn(str(core_path), result.stderr)
            self.assertEqual(result.core_dumps, (core_path,))
            receipt = json.loads(
                (run_dir / "logs" / "msprof_op.result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(receipt["status"], "core_dump")
            self.assertIsNone(receipt["process_returncode"])
            self.assertEqual(receipt["core_dumps"], [str(core_path)])

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
            self.assertEqual(result.stdout, "out\n")
            self.assertEqual(result.stderr, "err\n")
            self.assertEqual(result.core_dumps, ())
            self.assertFalse(result.output_staged_locally)
            self.assertIsNone(result.preserved_output)
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
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "failed\n")
            self.assertEqual(result.core_dumps, ())
            self.assertEqual((run_dir / "logs" / "msprof_simulator.stderr").read_text(encoding="utf-8"), "failed\n")
            self.assertEqual((run_dir / "logs" / "msprof_simulator.status").read_text(encoding="utf-8"), "9\n")

    def test_profile_harness_run_logged_rejects_zero_exit_with_new_core_dump(self):
        class CoreDumpingRunner(RecordingCommandRunner):
            def run(self, command, *, cwd, timeout_s=None):
                result = super().run(command, cwd=cwd, timeout_s=timeout_s)
                (cwd / "core.123").write_bytes(b"core")
                return result

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "runner_core_dump"
            cwd = Path(tmp) / "work"
            cwd.mkdir()

            result = profile_harness_module.run_logged(
                ["msprof", "op", "--application=run.sh"],
                run_dir,
                command_name="command_msprof_op.txt",
                log_stem="msprof_op",
                cwd=cwd,
                fatal=False,
                runner=CoreDumpingRunner(returncode=0),
            )

            self.assertEqual(result.status, "core_dump")
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn(str(cwd / "core.123"), result.stderr)
            self.assertEqual(result.core_dumps, (cwd / "core.123",))
            self.assertEqual((run_dir / "logs" / "msprof_op.status").read_text(encoding="utf-8"), "0\n")
            self.assertIn(str(cwd / "core.123"), (run_dir / "logs" / "msprof_op.stderr").read_text(encoding="utf-8"))
            logical_result = json.loads(
                (run_dir / "logs" / "msprof_op.result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(logical_result["status"], "core_dump")
            self.assertEqual(logical_result["process_returncode"], 0)
            self.assertTrue(logical_result["retryable_infrastructure_failure"])
            self.assertEqual(logical_result["core_dumps"], [str(cwd / "core.123")])

    def test_profile_harness_run_logged_raises_for_fatal_zero_exit_core_dump(self):
        class CoreDumpingRunner(RecordingCommandRunner):
            def run(self, command, *, cwd, timeout_s=None):
                result = super().run(command, cwd=cwd, timeout_s=timeout_s)
                (cwd / "core.456").write_bytes(b"core")
                return result

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "fatal_core_dump"
            cwd = Path(tmp) / "work"
            cwd.mkdir()

            with self.assertRaisesRegex(RuntimeError, r"core\.456"):
                profile_harness_module.run_logged(
                    ["msprof", "op", "--application=run.sh"],
                    run_dir,
                    command_name="command_msprof_op.txt",
                    log_stem="msprof_op",
                    cwd=cwd,
                    runner=CoreDumpingRunner(returncode=0),
                )

            self.assertEqual((run_dir / "logs" / "msprof_op.status").read_text(encoding="utf-8"), "0\n")

    def test_profile_harness_run_logged_ignores_preexisting_core_dump(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "preexisting_core_dump"
            cwd = Path(tmp) / "work"
            cwd.mkdir()
            (cwd / "core.789").write_bytes(b"old core")

            result = profile_harness_module.run_logged(
                ["msprof", "--version"],
                run_dir,
                command_name="command_msprof.txt",
                log_stem="msprof_default",
                cwd=cwd,
                runner=RecordingCommandRunner(returncode=0),
            )

            self.assertEqual(result.status, "succeeded")
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.core_dumps, ())

    def test_profile_harness_run_logged_gives_new_core_precedence_over_nonzero_exit(self):
        class CoreDumpingRunner(RecordingCommandRunner):
            def run(self, command, *, cwd, timeout_s=None):
                result = super().run(command, cwd=cwd, timeout_s=timeout_s)
                (cwd / "core.999").write_bytes(b"core")
                return result

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "nonzero_core_dump"
            cwd = Path(tmp) / "work"
            cwd.mkdir()

            result = profile_harness_module.run_logged(
                ["msprof", "op", "--application=run.sh"],
                run_dir,
                command_name="command_msprof_op.txt",
                log_stem="msprof_op",
                cwd=cwd,
                fatal=False,
                runner=CoreDumpingRunner(stdout="out\n", stderr="failed\n", returncode=9),
            )

            self.assertEqual(result.status, "core_dump")
            self.assertEqual(result.returncode, 9)
            self.assertEqual(result.stdout, "out\n")
            self.assertIn("failed\n", result.stderr)
            self.assertIn(str(cwd / "core.999"), result.stderr)
            self.assertEqual(result.core_dumps, (cwd / "core.999",))
            logical_result = json.loads(
                (run_dir / "logs" / "msprof_op.result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(logical_result["status"], "core_dump")
            self.assertEqual(logical_result["process_returncode"], 9)

    def test_subprocess_runner_terminates_process_group_after_timeout_grace(self):
        class FakeProcess:
            pid = 4321

            def __init__(self, grace_expires):
                self.communicate_calls = 0
                self.grace_expires = grace_expires

            def communicate(self, timeout=None):
                self.communicate_calls += 1
                if self.communicate_calls == 1 or (
                    self.communicate_calls == 2 and self.grace_expires
                ):
                    raise subprocess.TimeoutExpired(
                        ["tool"],
                        timeout,
                        output="partial\n",
                        stderr="slow\n",
                    )
                return "partial\n", "slow\n"

        for grace_expires in (False, True):
            with self.subTest(grace_expires=grace_expires):
                process = FakeProcess(grace_expires)
                with (
                    tempfile.TemporaryDirectory() as tmp,
                    mock.patch.object(
                        profile_harness_module.subprocess,
                        "run",
                        side_effect=AssertionError(
                            "timed commands must use a process group"
                        ),
                    ) as run,
                    mock.patch.object(
                        profile_harness_module.subprocess,
                        "Popen",
                        return_value=process,
                    ) as popen,
                    mock.patch.object(profile_harness_module.os, "killpg") as killpg,
                ):
                    runner = profile_harness_module.SubprocessCommandRunner()
                    with self.assertRaises(subprocess.TimeoutExpired) as raised:
                        runner.run(["tool"], cwd=Path(tmp), timeout_s=0.01)

                run.assert_not_called()
                self.assertEqual(raised.exception.output, "partial\n")
                self.assertEqual(raised.exception.stderr, "slow\n")
                self.assertEqual(
                    killpg.call_args_list,
                    [
                        mock.call(4321, signal.SIGTERM),
                        mock.call(4321, signal.SIGKILL),
                    ],
                )
                self.assertTrue(popen.call_args.kwargs["start_new_session"])

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
            self.assertEqual(result.stdout, "partial\n")
            self.assertIn("slow", result.stderr)
            self.assertEqual(result.core_dumps, ())
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

    def test_profile_harness_workflow_records_simulator_core_dump_warning(self):
        class SimulatorCoreRunner(RecordingCommandRunner):
            def run(self, command, *, cwd, timeout_s=None):
                result = super().run(command, cwd=cwd, timeout_s=timeout_s)
                if len(self.calls) == 3:
                    (cwd / "core.simulator").write_bytes(b"core")
                return result

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "workflow_runner_core_dump"
            manifest, _ = write_profile_harness_fixture(run_dir)

            with mock.patch.object(profile_harness_module, "run_profile_harness_analysis"):
                result = profile_harness_module._run_profile_harness_workflow(
                    profile_harness_module.ProfileHarnessRequest(
                        run_dir=run_dir,
                        manifest_path=manifest,
                        application_path=None,
                        verify_json_path=None,
                        simulator_enabled=True,
                        simulator_timeout_s=0.25,
                    ),
                    runner=SimulatorCoreRunner(),
                )

            warning = "optional simulator collection produced a core dump"
            self.assertEqual(result.command_results["msprof_simulator"].status, "core_dump")
            self.assertTrue(any(warning in item for item in result.simulator_warnings))
            workflow = json.loads(
                (run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8")
            )
            self.assertTrue(any(warning in item for item in workflow["warnings"]))
            context = json.loads(
                (run_dir / "analysis" / "profile_context.json").read_text(encoding="utf-8")
            )
            self.assertTrue(any(warning in item for item in context["warnings"]))

    @mock.patch.object(profile_harness_module.generate_provenance, "require_matching_cann_environment", new=lambda *_: None)
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
                        profile_harness_module.ContinueFollowupsRequest(run_dir=run_dir, selected_action_id="collect_default_metric_followup"),
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

    def test_continue_checks_toolkit_before_running_profiler(self):
        provenance = profile_harness_module.generate_provenance
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for change in ("none", "version", "executable", "missing_receipt"):
                with self.subTest(change=change):
                    toolkit = root / change / "toolkit"
                    binary = toolkit / "bin/msprof"
                    binary.parent.mkdir(parents=True)
                    binary.write_text("#!/bin/sh\nexit 0\n")
                    binary.chmod(0o755)
                    version = toolkit / "version.cfg"
                    version.write_text("toolkit_running_version=[8.5.2]\n")
                    run_dir = root / change / "run"
                    write_continue_followup_inputs(run_dir, include_pipe=False)
                    logs = run_dir / "logs"
                    logs.mkdir(exist_ok=True)
                    env = {key: "" for key in provenance.CANN_VERSION_ROOT_KEYS}
                    env["PATH"] = str(binary.parent) + os.pathsep + os.environ.get("PATH", "")
                    with mock.patch.dict(os.environ, env):
                        provenance.collect_cann_sources(logs, "msprof")
                        if change == "version":
                            version.write_text("toolkit_running_version=[8.6.0]\n")
                        elif change == "executable":
                            other = toolkit / "other/msprof"
                            other.parent.mkdir()
                            shutil.copy2(binary, other)
                            binary.unlink()
                            binary.symlink_to(other)
                        elif change == "missing_receipt":
                            (logs / "msprof_environment.json").unlink()
                        before = {p.name: p.read_bytes() for p in logs.iterdir()}
                        runner = RecordingCommandRunner()
                        with mock.patch.object(profile_harness_module, "run_profile_harness_analysis"):
                            request = profile_harness_module.ContinueFollowupsRequest(run_dir=run_dir, selected_action_id="collect_default_metric_followup")
                            if change == "none":
                                profile_harness_module._run_continue_followups_workflow(request, runner=runner)
                                self.assertEqual(len(runner.calls), 1)
                            else:
                                with self.assertRaisesRegex(RuntimeError, "CANN.*new run"):
                                    profile_harness_module._run_continue_followups_workflow(request, runner=runner)
                                self.assertEqual(runner.calls, [])
                                self.assertEqual(before, {p.name: p.read_bytes() for p in logs.iterdir()})
                                workflow = json.loads((run_dir / "analysis/profile_harness_run.json").read_text())
                                skipped, blocked = workflow["follow_up_actions"]
                                self.assertEqual(skipped["status"], "skipped")
                                self.assertEqual(blocked["status"], "blocked")
                                self.assertRegex(blocked["reason"], "CANN.*new run")

    @mock.patch.object(profile_harness_module.generate_provenance, "require_matching_cann_environment", new=lambda *_: None)
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
                        profile_harness_module.ContinueFollowupsRequest(run_dir=run_dir, selected_action_id="collect_default_metric_followup"),
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

    @mock.patch.object(profile_harness_module.generate_provenance, "require_matching_cann_environment", new=lambda *_: None)
    def test_profile_harness_continue_workflow_reruns_analysis_after_default_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "continue_runner_success"
            application = write_continue_followup_inputs(run_dir)
            runner = RecordingCommandRunner(stdout="default ok\n", returncode=0)

            with mock.patch.object(profile_harness_module, "run_profile_harness_analysis") as run_analysis:
                result = profile_harness_module._run_continue_followups_workflow(
                    profile_harness_module.ContinueFollowupsRequest(run_dir=run_dir, selected_action_id="collect_default_metric_followup"),
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
            self.assertIn("PipeUtilization-only evidence", record["reason"])
            self.assertEqual(record["returncode"], 0)
            self.assertEqual(workflow["commands"]["msprof_default_followup"], "logs/command_msprof_followup_collect_default_metric_followup.txt")
            self.assertEqual(workflow["outputs"]["default"], "reports/followups/collect_default_metric_followup")

    def test_profile_harness_continue_workflow_skipped_followup_does_not_rerun_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "continue_runner_skipped"
            write_continue_followup_inputs(run_dir, scope="Roofline")
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
            self.assertEqual(record["id"], "recollect_roofline")
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
            self.assertIn("Operator duration observations", report)

            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(timing_observation(summary, "op_summary").name, "harness_kernel")
            self.assertEqual(operator_headline(summary, "pipe_utilization").value, 66.5)
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
            from types import SimpleNamespace
            model = object()

            with (
                mock.patch.object(
                    profile_harness_module.generate_provenance,
                    "main",
                    side_effect=lambda argv: order.append(("provenance", argv)),
                ),
                mock.patch.object(
                    profile_harness_module.evidence_model,
                    "write_evidence_model",
                    side_effect=lambda path: (order.append(("evidence_model", path)), SimpleNamespace(simulator_model=model))[1],
                ),
                mock.patch.object(profile_harness_module, "write_simulator_markdown",
                                  side_effect=lambda path, payload: order.append(("simulator_markdown", path, payload))),
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
                    ("simulator_markdown", run_dir, model),
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
                {"follow_action": "collect_default_metric_followup"},
                "--follow-action and --follow-target-json require --continue-from-summary",
            ),
            (
                {
                    "follow_next_actions": True,
                    "continue_from_summary": True,
                    "manifest": None,
                    "follow_target_json": Path("focused.json"),
                },
                "--follow-target-json requires --follow-action",
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

    def test_profile_harness_question_followup_requires_explicit_selection(self):
        focused = _profile_target.normalize_target_contract(
            {
                "target": {
                    "kernel_selector": "gram_kernel",
                    "expected_launches": [{"name": "gram_kernel", "count": 1}],
                }
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            write_continue_followup_inputs(run_dir)
            summary = RunEvidence.load(run_dir).summary()
            skipped = profile_harness_module.plan_followup_actions(run_dir, summary)
            selected = profile_harness_module.plan_followup_actions(
                run_dir,
                summary,
                selected_action_id="collect_default_metric_followup",
                target_selection=focused,
            )

        self.assertFalse(skipped[0].execute_default_followup)
        self.assertEqual(skipped[0].record["status"], "skipped")
        self.assertTrue(selected[0].execute_default_followup)
        self.assertEqual(selected[0].record["target_scope"]["kind"], "focused_subset")
        self.assertEqual(selected[0].target_selection.launch_count, 1)

    @mock.patch.object(profile_harness_module.generate_provenance, "require_matching_cann_environment", new=lambda *_: None)
    def test_profile_harness_focused_followup_keeps_full_default_path_collectable(self):
        program = _profile_target.normalize_target_contract(
            {
                "target": {
                    "kernel_selector": "harness_kernel",
                    "expected_launches": [{"name": "harness_kernel", "count": 2}],
                }
            }
        )
        focused = _profile_target.normalize_target_contract(
            {
                "target": {
                    "kernel_selector": "harness_kernel",
                    "expected_launches": [{"name": "harness_kernel", "count": 1}],
                }
            }
        )

        class MaterializingDefaultRunner(RecordingCommandRunner):
            def run(self, command, *, cwd: Path, timeout_s: float | None = None):
                output = Path(next(item.split("=", 1)[1] for item in command if item.startswith("--output=")))
                kernel_name = next(
                    item.split("=", 1)[1] for item in command if item.startswith("--kernel-name=")
                )
                launch_count = int(
                    next(item.split("=", 1)[1] for item in command if item.startswith("--launch-count="))
                )
                for ordinal in range(launch_count):
                    launch = output / "OPPROF_001" / kernel_name / f"{ordinal:03d}"
                    launch.mkdir(parents=True, exist_ok=True)
                    (launch / "OpBasicInfo.csv").write_text(
                        f"Op Name,Task Duration(us),Block Dim\n{kernel_name},12.5,8\n",
                        encoding="utf-8",
                    )
                    for name in [
                        "PipeUtilization",
                        "ArithmeticUtilization",
                        "Memory",
                        "MemoryL0",
                        "MemoryUB",
                        "ResourceConflictRatio",
                    ]:
                        (launch / f"{name}.csv").write_text(
                            "Metric,Value\nvalue,1\n",
                            encoding="utf-8",
                        )
                return super().run(command, cwd=cwd, timeout_s=timeout_s)

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "focused_then_full"
            write_continue_followup_inputs(run_dir)
            workflow_path = run_dir / "analysis" / "profile_harness_run.json"
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            workflow["target_selection"] = program.model_dump(mode="json")
            workflow_path.write_text(json.dumps(workflow, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            focused_runner = MaterializingDefaultRunner(stdout="focused ok\n", returncode=0)
            full_runner = MaterializingDefaultRunner(stdout="full ok\n", returncode=0)
            with mock.patch.object(profile_harness_module, "run_profile_harness_analysis"):
                focused_result = profile_harness_module._run_continue_followups_workflow(
                    profile_harness_module.ContinueFollowupsRequest(
                        run_dir=run_dir,
                        selected_action_id="collect_default_metric_followup",
                        target_selection=focused,
                    ),
                    runner=focused_runner,
                )
                full_result = profile_harness_module._run_continue_followups_workflow(
                    profile_harness_module.ContinueFollowupsRequest(
                        run_dir=run_dir,
                        selected_action_id="collect_default_metric_followup",
                    ),
                    runner=full_runner,
                )

            focused_output = next(
                item.split("=", 1)[1]
                for item in focused_runner.calls[0]["command"]
                if item.startswith("--output=")
            )
            full_output = next(
                item.split("=", 1)[1]
                for item in full_runner.calls[0]["command"]
                if item.startswith("--output=")
            )
            self.assertNotEqual(focused_output, full_output)
            self.assertIn("collect_default_metric_followup_focused_", focused_output)
            self.assertTrue(full_output.endswith("reports/followups/collect_default_metric_followup"))
            self.assertEqual(focused_result.records[0]["status"], "succeeded")
            self.assertEqual(full_result.records[0]["status"], "succeeded")
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            records = workflow["follow_up_actions"]
            self.assertEqual(len(records), 2)
            self.assertNotEqual(records[0]["segment_id"], records[1]["segment_id"])
            self.assertEqual(records[1]["segment_id"], "collect_default_metric_followup")
            focused_record = records[0]
            focused_segment = f"followup:{focused_record['segment_id']}"
            self.assertEqual(
                workflow["commands"][focused_record["command_key"]],
                f"logs/command_msprof_followup_{focused_record['segment_id']}.txt",
            )
            self.assertEqual(
                workflow["outputs"][focused_record["output_key"]],
                f"reports/followups/{focused_record['segment_id']}",
            )
            self.assertEqual(
                workflow["outputs"]["default"],
                "reports/followups/collect_default_metric_followup",
            )

            provenance = profile_harness_module.generate_provenance.build_manifest(run_dir)
            provenance_followups = provenance.profile_output_segments.followups
            self.assertIn(focused_record["segment_id"], provenance_followups)
            self.assertIn("collect_default_metric_followup", provenance_followups)

            summary, raw_index, _simulator = evidence_model.build_evidence_model(run_dir)
            focused_artifacts = [
                item for item in raw_index.artifacts if item.segment == focused_segment
            ]
            self.assertTrue(focused_artifacts)
            self.assertTrue(all(item.metric_scope == "Default" for item in focused_artifacts))
            coverage = summary.profile_coverage.model_dump(mode="json", exclude_unset=True)
            self.assertTrue(coverage["segments"][focused_segment]["count_complete"])
            self.assertEqual(
                coverage["segments"][focused_segment]["target_scope"]["kind"],
                "focused_subset",
            )
            canonical_segment = "followup:collect_default_metric_followup"
            self.assertTrue(coverage["segments"][canonical_segment]["count_complete"])
            self.assertEqual(
                coverage["segments"][canonical_segment]["target_scope"]["kind"],
                "complete_program",
            )
            self.assertEqual(
                coverage["selected_segments_by_family"]["arithmetic_utilization"],
                canonical_segment,
            )

    def test_profile_harness_normalized_official_mean_preserves_mean_ms(self):
        verify_json = {
            "official_timing": {
                "latency_ms": 1.25,
                "aggregation": "mean",
                "samples_ms": [1.2, 1.3],
                "authority": "executor_natural_launch",
            }
        }

        benchmark = profile_harness_module.normalize_profile_benchmark(verify_json)
        context = RunEvidence.from_loaded(
            Path("profile/official_mean"),
            None,
            profile_context={"benchmark": benchmark},
        ).candidate_context()

        self.assertEqual(benchmark["candidate"]["runtime_stats"]["mean_ms"], 1.25)
        self.assertEqual(context.runtime.value_ms, 1.25)
        self.assertEqual(context.runtime.statistic, "mean")
        self.assertEqual(context.runtime.mean_ms, 1.25)
        self.assertEqual(
            context.context_sources["runtime.value_ms"].field_ref,
            "benchmark.candidate.runtime_stats.value_ms",
        )

        median_benchmark = profile_harness_module.normalize_profile_benchmark(
            {"official_timing": {"latency_ms": 1.2, "aggregation": "median"}}
        )
        self.assertNotIn("mean_ms", median_benchmark["candidate"]["runtime_stats"])

    def test_profile_harness_opt_in_candidate_summary_after_initial_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "initial_candidate_summary"
            manifest, application = write_profile_harness_fixture(run_dir)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--summarize-candidate",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=profile_harness_env_expect_cwd(fake_bin, application.parent),
            )

            candidate = json.loads((run_dir / "analysis" / "candidate_summary.json").read_text(encoding="utf-8"))
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(candidate["candidate_summary_schema_version"], "4.2")
            self.assertEqual(workflow["outputs"]["candidate_summary"], "analysis/candidate_summary.json")
            self.assertTrue((run_dir / "analysis" / "candidate_summary.md").is_file())

    def test_profile_harness_continue_can_summarize_without_recollection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "continue_candidate_summary"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)
            subprocess.run(
                [*CLI, "profile-harness", "--run-dir", str(run_dir), "--manifest", str(manifest)],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            reports_before = reports_file_snapshot(run_dir)
            report_before = (run_dir / "REPORT.md").read_bytes()

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                    "--continue-from-summary",
                    "--summarize-candidate",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertTrue((run_dir / "analysis" / "candidate_summary.json").is_file())
            self.assertEqual(reports_file_snapshot(run_dir), reports_before)
            self.assertEqual((run_dir / "REPORT.md").read_bytes(), report_before)

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
            self.assertEqual(operator_headline(summary, "arithmetic_utilization").metric_scope, "Default")

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
                    "--follow-action",
                    "collect_default_metric_followup",
                    "--summarize-candidate",
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
            self.assertEqual(
                workflow["follow_up_actions"][0]["unlocks_claims"],
                [
                    "describe recorded arithmetic time and ratios",
                    "describe recorded memory/cache fields",
                    "describe recorded resource conflict fields",
                ],
            )
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(operator_headline(summary, "arithmetic_utilization").metric_scope, "Default")
            candidate = json.loads(
                (run_dir / "analysis" / "candidate_summary.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                candidate["source_artifacts"]["candidate"]["summary"]["sha256"],
                hashlib.sha256(
                    (run_dir / "analysis" / "summary.json").read_bytes()
                ).hexdigest(),
            )
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
            (run_dir / "logs/command_msprof_op.txt").write_text("msprof op --aic-metrics=Roofline\n")
            evidence_model.write_evidence_model(run_dir)

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
            self.assertEqual(actions["recollect_roofline"]["status"], "skipped")
            self.assertNotIn("msprof_default_followup", workflow["commands"])
            self.assertNotIn("default", workflow["outputs"])

    def test_profile_harness_follow_next_actions_uses_readiness_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "readiness_fallback"
            write_continue_followup_inputs(run_dir, scope="UnknownScope")
            summary = RunEvidence.load(run_dir).summary()
            self.assertEqual(summary.next_collection_actions, ())
            self.assertEqual([action.id for action in summary.evidence_readiness.recommended_followups],
                             ["collect_app_timing"])
            runner = RecordingCommandRunner()
            with mock.patch.object(profile_harness_module, "run_profile_harness_analysis") as analyze:
                result = profile_harness_module._run_continue_followups_workflow(
                    profile_harness_module.ContinueFollowupsRequest(run_dir=run_dir), runner=runner)
            self.assertEqual(result.records[0]["id"], "collect_app_timing")
            self.assertEqual(result.records[0]["status"], "skipped")
            self.assertEqual(runner.calls, [])
            analyze.assert_not_called()

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
            # A genuinely incomplete existing segment still cannot be overwritten.
            for artifact in (run_dir / "reports").rglob("ArithmeticUtilization.csv"):
                artifact.unlink()
            evidence_model.write_evidence_model(run_dir)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                    "--continue-from-summary",
                    "--follow-action",
                    "collect_default_metric_followup",
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
                    "--follow-action",
                    "collect_default_metric_followup",
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
            (run_dir / "analysis/profile_context.json").write_text(json.dumps({"expected_kernel_names": ["definitely_wrong_kernel"]}))
            evidence_model.write_evidence_model(run_dir)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                    "--continue-from-summary",
                    "--follow-action",
                    "collect_default_metric_followup",
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
            self.assertIn("No finite application timing observation was parsed", report)
            self.assertNotIn("Operator duration observations", report)
            self.assertNotIn("Inspect Top operator duration", report)
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(RunEvidence.load(run_dir).headline_records(), [])
            self.assertTrue(all(not value["artifacts"]
                                for group, value in summary["headlines"].items()))
