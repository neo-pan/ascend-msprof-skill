"""Provenance tests."""

from tests.helpers_shared import *  # noqa: F401,F403


class ProvenanceTests(unittest.TestCase):
    def test_install_info_fallback_is_offline_and_preserves_logs(self):
        from ascend_msprof_skill import generate_provenance as provenance
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logs = root / "logs"
            logs.mkdir()
            info = logs / "toolkit_install.info"
            for cfg in (None, "", "# not found\n", "unrelated=value\n"):
                for version, expected in (("8.5.2", "8.5.2"), ("", None)):
                    with self.subTest(cfg=cfg, version=version):
                        path = logs / "cann_version.cfg"
                        path.unlink(missing_ok=True)
                        if cfg is not None:
                            path.write_text(cfg)
                        info.write_text(f"package_name=Ascend-cann-toolkit\nversion={version}\n")
                        before = {p.name: p.read_bytes() for p in logs.iterdir()}
                        with mock.patch.object(provenance, "collect_environment", side_effect=AssertionError("offline replay collected environment")):
                            provenance.main(["--run-dir", str(root)])
                        manifest = json.loads((root / "analysis/provenance.json").read_text())
                        self.assertEqual(manifest.get("cann_version", {}).get("value"), expected)
                        if expected:
                            self.assertEqual(manifest["cann_version"]["source"], {"artifact": "logs/toolkit_install.info", "field": "version"})
                        self.assertEqual(before, {p.name: p.read_bytes() for p in logs.iterdir()})

    def test_version_conflicts_block_comparison_even_in_self_comparison(self):
        from ascend_msprof_skill.generate_provenance import build_manifest
        from ascend_msprof_skill.compare_runs import build_compatibility
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logs = root / "logs"
            logs.mkdir()
            (logs / "cann_version.cfg").write_text("toolkit_running_version=[8.3]\nruntime_running_version=[8.2]\n")
            manifest = build_manifest(root)
            evidence = RunEvidence.from_loaded(root, {}, provenance=manifest)
            facts = RunEvidence.comparison_facts(evidence, evidence)
            check = build_compatibility(facts.baseline, facts.candidate)["checks"][0]
            self.assertEqual(check["status"], "conflict")
            self.assertEqual(len(manifest["cann_version"]["evidence"]), 2)

    def test_collect_environment_accepts_only_toolkit_and_standard_parent_root(self):
        from ascend_msprof_skill import generate_provenance as provenance
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Ascend"
            toolkit = root / "ascend-toolkit" / "latest"
            msprof = toolkit / "bin" / "msprof"
            msprof.parent.mkdir(parents=True)
            msprof.write_text("#!/bin/sh\nexit 0\n")
            msprof.chmod(0o755)
            (toolkit / "version.cfg").write_text("toolkit_running_version=[8.5.2]\n")
            env = {key: str(root) for key in provenance.CANN_VERSION_ROOT_KEYS}
            env["ASCEND_TOOLKIT_HOME"] = str(toolkit)
            for candidate, mixed in (
                (root, False), (toolkit, False),
                (root.parent, True), (Path("/"), True),
                (toolkit.parent, True), (root / "other", True),
            ):
                with self.subTest(candidate=candidate):
                    env["ASCEND_HOME_PATH"] = str(candidate)
                    with mock.patch.dict(os.environ, env, clear=False):
                        current = provenance.current_cann_environment(str(msprof))
                    self.assertEqual(current["mixed_roots"], mixed)

    def test_generate_provenance_from_complete_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            reports_before = sorted(path.relative_to(run_dir).as_posix() for path in (run_dir / "reports").rglob("*"))
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            reports_after = sorted(path.relative_to(run_dir).as_posix() for path in (run_dir / "reports").rglob("*"))

            self.assertEqual(reports_before, reports_after)
            self.assertEqual(provenance["cann_version"]["value"], "8.3.0.2.220:8.3.RC2")
            self.assertEqual(provenance["cann_version"]["source"]["artifact"], "logs/cann_version.cfg")
            self.assertEqual(provenance["cann_version"]["source"]["field"], "toolkit_running_version")
            self.assertEqual(provenance["hardware"]["summary"]["value"], "1 x 910B2; health OK")
            self.assertEqual(provenance["hardware"]["summary"]["source"]["field"], "NPU/Name/Health")
            self.assertIn("msprof op --output=<abs-path>", provenance["profile_command"]["value"])
            self.assertEqual(provenance["profile_date"]["value"], "2026-05-30 19:11:28")
            self.assertEqual(provenance["profiler_status"][0]["value"], "0")
            self.assertIn("PATH", provenance["environment"]["omitted_keys"]["value"])

            text = json.dumps(provenance, sort_keys=True)
            self.assertNotIn("/data/", text)
            self.assertNotIn("/home/", text)
            self.assertNotIn("/root/", text)
            self.assertNotIn("UARAJTADRTYKPBZQ", text)

    def test_generate_provenance_cites_fallback_cann_version_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            (run_dir / "logs" / "cann_version.cfg").write_text(
                "# version: 1.0\nruntime_running_version=[9.9]\n",
                encoding="utf-8",
            )
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual(provenance["cann_version"]["value"], "9.9")
            self.assertEqual(provenance["cann_version"]["source"]["artifact"], "logs/cann_version.cfg")
            self.assertEqual(provenance["cann_version"]["source"]["field"], "runtime_running_version")

    def test_collect_environment_prefers_invoked_msprof_version_cfg(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            invoked_toolkit = root / "invoked-toolkit"
            env_toolkit = root / "env-toolkit"
            logs = root / "logs"
            msprof = invoked_toolkit / "bin" / "msprof"
            msprof.parent.mkdir(parents=True)
            env_toolkit.mkdir()
            logs.mkdir()
            msprof.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
            msprof.chmod(0o755)
            (invoked_toolkit / "version.cfg").write_text(
                "toolkit_running_version=[invoked-msprof-version]\n",
                encoding="utf-8",
            )
            (env_toolkit / "version.cfg").write_text(
                "toolkit_running_version=[env-root-version]\n",
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"ASCEND_TOOLKIT_HOME": str(env_toolkit)}, clear=False):
                collect_environment(logs, str(msprof))

            self.assertIn(
                "toolkit_running_version=[invoked-msprof-version]",
                (logs / "cann_version.cfg").read_text(encoding="utf-8"),
            )
            self.assertNotIn(
                "env-root-version",
                (logs / "cann_version.cfg").read_text(encoding="utf-8"),
            )
            from ascend_msprof_skill.generate_provenance import build_manifest
            manifest = build_manifest(root)
            self.assertEqual(manifest["cann_version"]["status"], "conflict")
            self.assertEqual(manifest["cann_version"]["conflicts"][0]["source"]["field"], "mixed_roots")

    def test_generate_provenance_cli_collects_missing_environment_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "profile" / "cli_env_capture"
            fake_toolkit = root / "fake-toolkit"
            fake_bin = fake_toolkit / "bin"
            fake_bin.mkdir(parents=True)
            msprof = fake_bin / "msprof"
            npu_smi = fake_bin / "npu-smi"
            msprof.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
            npu_smi.write_text(
                "#!/usr/bin/env sh\n"
                "if [ \"$1\" = \"info\" ]; then\n"
                "  printf '| 0 910B2 | OK |\\n'\n"
                "fi\n",
                encoding="utf-8",
            )
            msprof.chmod(0o755)
            npu_smi.chmod(0o755)
            (fake_toolkit / "version.cfg").write_text(
                "toolkit_running_version=[cli-captured-version]\n",
                encoding="utf-8",
            )
            env = test_env()
            for key in ("ASCEND_HOME_PATH", "ASCEND_TOOLKIT_HOME", "CANN_PATH", "DDK_PATH"):
                env.pop(key, None)
            env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
            env["ASCEND_HOME_PATH"] = str(fake_toolkit)

            subprocess.run(
                [*CLI, "provenance", "--collect-env", "--run-dir", str(run_dir)],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual(provenance["cann_version"]["value"], "cli-captured-version")
            self.assertEqual(provenance["hardware"]["summary"]["value"], "1 x 910B2; health OK")
            self.assertEqual(
                provenance["environment"]["selected"]["ASCEND_HOME_PATH"]["source"]["artifact"],
                "logs/relevant_env.txt",
            )
            for source in ["logs/cann_version.cfg", "logs/npu_smi_info.stdout", "logs/relevant_env.txt"]:
                self.assertIn(source, provenance["sources"])
                self.assertTrue((run_dir / source).exists())

    def test_generate_provenance_cli_uses_msprof_from_command_log_for_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "profile" / "cli_command_msprof"
            logs = run_dir / "logs"
            reports = run_dir / "reports"
            logs.mkdir(parents=True)
            reports.mkdir(parents=True)

            profiled_toolkit = root / "profiled-toolkit"
            path_toolkit = root / "path-toolkit"
            profiled_msprof = profiled_toolkit / "bin" / "msprof"
            path_msprof = path_toolkit / "bin" / "msprof"
            profiled_msprof.parent.mkdir(parents=True)
            path_msprof.parent.mkdir(parents=True)
            profiled_msprof.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
            path_msprof.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
            profiled_msprof.chmod(0o755)
            path_msprof.chmod(0o755)
            (profiled_toolkit / "version.cfg").write_text(
                "toolkit_running_version=[profiled-msprof-version]\n",
                encoding="utf-8",
            )
            (path_toolkit / "version.cfg").write_text(
                "toolkit_running_version=[path-msprof-version]\n",
                encoding="utf-8",
            )
            (logs / "command_msprof.txt").write_text(
                f"{profiled_msprof} --output={reports / 'app'} --application={run_dir / 'harness' / 'run.sh'}\n",
                encoding="utf-8",
            )
            env = test_env()
            for key in ("ASCEND_HOME_PATH", "ASCEND_TOOLKIT_HOME", "CANN_PATH", "DDK_PATH"):
                env.pop(key, None)
            env["PATH"] = f"{path_msprof.parent}{os.pathsep}{env.get('PATH', '')}"

            subprocess.run(
                [*CLI, "provenance", "--collect-env", "--run-dir", str(run_dir)],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual(provenance["cann_version"]["value"], "profiled-msprof-version")
            self.assertNotIn(
                "path-msprof-version",
                (logs / "cann_version.cfg").read_text(encoding="utf-8"),
            )

    def test_generate_provenance_preserves_profile_output_artifact_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            (run_dir / "logs" / "msprof_default.stdout").write_text(
                (
                    "2026-05-30 19:11:37 [INFO]  Profiling results saved in "
                    "/opt/profiler-runs/ascend-msprof-skill/profile/default/reports/"
                    "OPPROF_20260530191128_UARAJTADRTYKPBZQ\n"
                ),
                encoding="utf-8",
            )
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            output = provenance["profile_output"]["value"]

            self.assertEqual(output, "reports/OPPROF_<sanitized>")
            self.assertNotIn("/data/", output)
            self.assertNotIn("UARAJTADRTYKPBZQ", output)

    def test_generate_provenance_sanitizes_placeholder_profile_output_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            (run_dir / "logs" / "msprof_default.stdout").write_text(
                (
                    "2026-05-30 19:11:37 [INFO]  Profiling results saved in "
                    "<abs-path>/reports/OPPROF_20260530191128_UARAJTADRTYKPBZQ\n"
                ),
                encoding="utf-8",
            )
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            output = provenance["profile_output"]["value"]

            self.assertEqual(output, "reports/OPPROF_<sanitized>")
            self.assertNotIn("UARAJTADRTYKPBZQ", output)

    def test_generate_provenance_redacts_common_absolute_path_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            (run_dir / "logs" / "command_msprof.txt").write_text(
                (
                    "msprof op --output=/workspace/project/profile/run/reports "
                    "--application=/mnt/build/run.sh --aic-metrics=Default\n"
                ),
                encoding="utf-8",
            )
            (run_dir / "logs" / "msprof_default.stdout").write_text(
                (
                    "2026-05-30 19:11:37 [INFO]  Profiling results saved in "
                    "/mnt/profiles/default/reports/OPPROF_20260530191128_UARAJTADRTYKPBZQ\n"
                ),
                encoding="utf-8",
            )
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            text = json.dumps(provenance, sort_keys=True)

            self.assertIn("--output=<abs-path>", provenance["profile_command"]["value"])
            self.assertIn("--application=<abs-path>", provenance["profile_command"]["value"])
            self.assertEqual(provenance["profile_output"]["value"], "reports/OPPROF_<sanitized>")
            self.assertNotIn("/workspace/", text)
            self.assertNotIn("/mnt/", text)
            self.assertNotIn("UARAJTADRTYKPBZQ", text)

    def test_generate_provenance_ignores_auxiliary_msprof_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            (run_dir / "logs" / "msprof_op_help.stdout").write_text(
                (
                    "2026-01-01 00:00:00 [INFO]  msprof op help\n"
                    "2026-01-01 00:00:01 [INFO]  Profiling results saved in "
                    "/workspace/help/reports/OPPROF_20260101000000_HELPHELP\n"
                ),
                encoding="utf-8",
            )
            (run_dir / "logs" / "msprof_op_help.status").write_text("9\n", encoding="utf-8")
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual(provenance["profile_date"]["value"], "2026-05-30 19:11:28")
            self.assertEqual(provenance["profile_date"]["source"]["artifact"], "logs/msprof_default.stdout")
            self.assertEqual(provenance["profile_output"]["value"], "reports/OPPROF_<sanitized>")
            self.assertEqual([item["value"] for item in provenance["profiler_status"]], ["0"])
            self.assertNotIn("logs/msprof_op_help.stdout", provenance["sources"])
            self.assertNotIn("logs/msprof_op_help.status", provenance["sources"])

    def test_generate_provenance_uses_command_msprof_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            (run_dir / "logs" / "msprof_default.stdout").unlink()
            (run_dir / "logs" / "msprof_default.status").unlink()
            (run_dir / "logs" / "command_msprof.stdout").write_text(
                (
                    "2026-05-31 08:00:01 [INFO]  Op profiling analysis start.\n"
                    "2026-05-31 08:00:09 [INFO]  Profiling results saved in "
                    "/workspace/run/reports/OPPROF_20260531080001_CMDSTDOUT\n"
                ),
                encoding="utf-8",
            )
            (run_dir / "logs" / "command_msprof.status").write_text("0\n", encoding="utf-8")
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual(provenance["profile_date"]["value"], "2026-05-31 08:00:01")
            self.assertEqual(provenance["profile_date"]["source"]["artifact"], "logs/command_msprof.stdout")
            self.assertEqual(provenance["profile_output"]["value"], "reports/OPPROF_<sanitized>")
            self.assertEqual([item["value"] for item in provenance["profiler_status"]], ["0"])
            self.assertIn("logs/command_msprof.stdout", provenance["sources"])
            self.assertIn("logs/command_msprof.status", provenance["sources"])

    def test_generate_provenance_status_only_primary_does_not_hide_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            (run_dir / "logs" / "msprof_default.stdout").unlink()
            (run_dir / "logs" / "msprof_default.status").unlink()
            (run_dir / "logs" / "command_msprof.status").write_text("0\n", encoding="utf-8")
            (run_dir / "logs" / "msprof_simulator_910b2.stdout").write_text(
                (
                    "2026-06-01 10:00:01 [INFO]  Simulator profiling start.\n"
                    "2026-06-01 10:00:09 [INFO]  Profiling results saved in "
                    "/workspace/sim/reports/OPPROF_20260601100001_SIMRUNXX\n"
                ),
                encoding="utf-8",
            )
            (run_dir / "logs" / "msprof_simulator_910b2.status").write_text("0\n", encoding="utf-8")
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual(provenance["profile_date"]["value"], "2026-06-01 10:00:01")
            self.assertEqual(provenance["profile_date"]["source"]["artifact"], "logs/msprof_simulator_910b2.stdout")
            self.assertEqual(provenance["profile_output"]["value"], "reports/OPPROF_<sanitized>")
            self.assertEqual([item["value"] for item in provenance["profiler_status"]], ["0"])
            self.assertIn("logs/msprof_simulator_910b2.stdout", provenance["sources"])
            self.assertIn("logs/msprof_simulator_910b2.status", provenance["sources"])
            self.assertNotIn("logs/command_msprof.status", provenance["sources"])

    def test_generate_provenance_prefers_legacy_msprof_before_msprof_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "legacy_msprof_with_op"
            logs = run_dir / "logs"
            reports = run_dir / "reports"
            logs.mkdir(parents=True)
            (reports / "app").mkdir(parents=True)
            (reports / "op").mkdir(parents=True)
            (logs / "msprof.stdout").write_text(
                (
                    "2026-06-02 10:00:01 [INFO]  Legacy app profiling start.\n"
                    f"2026-06-02 10:00:09 [INFO]  Profiling results saved in {reports / 'app'}\n"
                ),
                encoding="utf-8",
            )
            (logs / "msprof.status").write_text("0\n", encoding="utf-8")
            (logs / "msprof_op.stdout").write_text(
                (
                    "2026-06-02 10:01:01 [INFO]  Op profiling start.\n"
                    f"2026-06-02 10:01:09 [INFO]  Profiling results saved in {reports / 'op'}\n"
                ),
                encoding="utf-8",
            )
            (logs / "msprof_op.status").write_text("0\n", encoding="utf-8")

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual(provenance["profile_date"]["value"], "2026-06-02 10:00:01")
            self.assertEqual(provenance["profile_date"]["source"]["artifact"], "logs/msprof.stdout")
            self.assertEqual(provenance["profile_output"]["value"], "reports/app")
            self.assertEqual(provenance["profile_output"]["source"]["artifact"], "logs/msprof.stdout")
            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/app", "reports/op"])
            self.assertEqual(
                [item["source"]["artifact"] for item in provenance["profiler_status"]],
                ["logs/msprof.status", "logs/msprof_op.status"],
            )

    def test_generate_provenance_prefers_command_msprof_before_msprof_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "legacy_command_msprof_with_op"
            logs = run_dir / "logs"
            reports = run_dir / "reports"
            logs.mkdir(parents=True)
            (reports / "app").mkdir(parents=True)
            (reports / "op").mkdir(parents=True)
            (logs / "command_msprof.stdout").write_text(
                (
                    "2026-06-02 10:20:01 [INFO]  Legacy command app profiling start.\n"
                    f"2026-06-02 10:20:09 [INFO]  Profiling results saved in {reports / 'app'}\n"
                ),
                encoding="utf-8",
            )
            (logs / "command_msprof.status").write_text("0\n", encoding="utf-8")
            (logs / "msprof_op.stdout").write_text(
                (
                    "2026-06-02 10:21:01 [INFO]  Op profiling start.\n"
                    f"2026-06-02 10:21:09 [INFO]  Profiling results saved in {reports / 'op'}\n"
                ),
                encoding="utf-8",
            )
            (logs / "msprof_op.status").write_text("0\n", encoding="utf-8")

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual(provenance["profile_date"]["value"], "2026-06-02 10:20:01")
            self.assertEqual(provenance["profile_date"]["source"]["artifact"], "logs/command_msprof.stdout")
            self.assertEqual(provenance["profile_output"]["value"], "reports/app")
            self.assertEqual(provenance["profile_output"]["source"]["artifact"], "logs/command_msprof.stdout")
            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/app", "reports/op"])
            self.assertEqual(
                [item["source"]["artifact"] for item in provenance["profiler_status"]],
                ["logs/command_msprof.status", "logs/msprof_op.status"],
            )

    def test_generate_provenance_infers_outputs_without_profiler_stdout_or_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "missing_profiler_logs"
            logs = run_dir / "logs"
            reports = run_dir / "reports"
            logs.mkdir(parents=True)
            (reports / "app").mkdir(parents=True)
            (reports / "op").mkdir(parents=True)
            (logs / "command_msprof.txt").write_text(
                f"msprof --output={reports / 'app'} --application={run_dir / 'harness' / 'app.sh'}\n",
                encoding="utf-8",
            )
            (logs / "command_msprof_op.txt").write_text(
                f"msprof op --output={reports / 'op'} --application={run_dir / 'harness' / 'op.sh'}\n",
                encoding="utf-8",
            )

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/app", "reports/op"])
            self.assertEqual(provenance["profile_output"]["value"], "reports/app")
            self.assertIn("Missing profiler stdout/status logs", "\n".join(provenance["warnings"]))

            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("- Profile outputs: app: reports/app (source: `logs/command_msprof.txt`; `--output`)", report)
            self.assertIn("reports/op (source: `logs/command_msprof_op.txt`; `--output`)", report)
            self.assertNotIn("- Profile output: not recorded", report)

    def test_generate_provenance_infers_outputs_from_multiline_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "multiline_command_logs"
            logs = run_dir / "logs"
            reports = run_dir / "reports"
            logs.mkdir(parents=True)
            (reports / "app").mkdir(parents=True)
            (reports / "op").mkdir(parents=True)
            (logs / "command_msprof.txt").write_text(
                (
                    "msprof \\\n"
                    f"  --output={reports / 'app'} \\\n"
                    f"  --application={run_dir / 'harness' / 'app.sh'}\n"
                ),
                encoding="utf-8",
            )
            (logs / "command_msprof_op.txt").write_text(
                (
                    "msprof op \\\n"
                    f"  --output={reports / 'op'} \\\n"
                    f"  --application={run_dir / 'harness' / 'op.sh'}\n"
                ),
                encoding="utf-8",
            )

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/app", "reports/op"])
            self.assertEqual(provenance["profile_output"]["value"], "reports/app")
            self.assertEqual(provenance["profile_command"]["value"], "msprof --output=reports/app --application=<abs-path>")
            self.assertNotIn("\\", provenance["profile_command"]["value"])

            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("- Profile outputs: app: reports/app (source: `logs/command_msprof.txt`; `--output`)", report)
            self.assertIn("reports/op (source: `logs/command_msprof_op.txt`; `--output`)", report)
            self.assertNotIn("- Profile output: not recorded", report)

    def test_generate_provenance_does_not_infer_empty_report_dirs_as_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "empty_report_dirs"
            (run_dir / "logs").mkdir(parents=True)
            (run_dir / "reports" / "app").mkdir(parents=True)
            (run_dir / "reports" / "op").mkdir(parents=True)

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertNotIn("profile_output", provenance)
            self.assertNotIn("profile_outputs", provenance)
            self.assertIn("Missing profiler stdout/status logs", "\n".join(provenance["warnings"]))

            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("- Profile output: not recorded", report)

    def test_generate_provenance_infers_nonempty_report_dirs_without_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "nonempty_report_dirs"
            app_prof = run_dir / "reports" / "app" / "PROF_001" / "mindstudio_profiler_output"
            op_prof = run_dir / "reports" / "op" / "OPPROF_001"
            (run_dir / "logs").mkdir(parents=True)
            app_prof.mkdir(parents=True)
            op_prof.mkdir(parents=True)
            (app_prof / "op_summary_001.csv").write_text("Op Name,Task Duration(us)\napp_kernel,1\n", encoding="utf-8")
            (op_prof / "OpBasicInfo.csv").write_text("Op Name,Task Duration(us)\nop_kernel,1\n", encoding="utf-8")

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/app", "reports/op"])
            self.assertEqual(provenance["profile_outputs"][0]["source"]["field"], "existing_report_dir")
            self.assertEqual(provenance["profile_outputs"][1]["source"]["field"], "existing_report_dir")
            self.assertEqual(provenance["profile_output_segments"]["app"]["output"]["value"], "reports/app")
            self.assertEqual(
                provenance["profile_output_segments"]["app"]["output"]["source"]["field"],
                "existing_report_dir",
            )
            self.assertEqual(provenance["profile_output_segments"]["op"]["output"]["value"], "reports/op")
            self.assertEqual(
                provenance["profile_output_segments"]["op"]["output"]["source"]["field"],
                "existing_report_dir",
            )

    def test_generate_provenance_infers_followup_segment_from_existing_report_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_pipe_default_followup_run(Path(tmp) / "profile")

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            segments = provenance["profile_output_segments"]
            followup = segments["followups"]["collect_default_metric_followup"]

            self.assertEqual(followup["output"]["value"], "reports/followups/collect_default_metric_followup")
            self.assertEqual(followup["output"]["source"]["field"], "existing_report_dir")
            self.assertEqual(
                followup["resolved_output"]["value"],
                "reports/followups/collect_default_metric_followup/OPPROF_001",
            )
            self.assertEqual(followup["resolved_output"]["source"]["field"], "existing_report_dir")
            self.assertEqual(segments["op"]["output"]["value"], "reports/op")
            self.assertNotIn("status", followup)
            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/op"])
            self.assertNotIn(
                "reports/followups/collect_default_metric_followup",
                [item["value"] for item in provenance["profile_outputs"]],
            )

    def test_generate_provenance_does_not_treat_followup_logs_as_primary_profiler_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "followup_only"
            logs = run_dir / "logs"
            output = run_dir / "reports" / "followups" / "collect_default_metric_followup"
            resolved = output / "OPPROF_001"
            logs.mkdir(parents=True)
            resolved.mkdir(parents=True)
            (resolved / "OpBasicInfo.csv").write_text("Op Name,Task Duration(us)\nop_kernel,1\n", encoding="utf-8")
            (logs / "command_msprof_followup_collect_default_metric_followup.txt").write_text(
                f"msprof op --output={output} --application={run_dir / 'harness' / 'op.sh'} --aic-metrics=Default\n",
                encoding="utf-8",
            )
            (logs / "msprof_followup_collect_default_metric_followup.stdout").write_text(
                f"2026-06-02 09:00:19 [INFO]  Profiling results saved in {resolved}\n",
                encoding="utf-8",
            )
            (logs / "msprof_followup_collect_default_metric_followup.status").write_text("0\n", encoding="utf-8")
            (logs / "msprof_followup_collect_default_metric_followup.stderr").write_text("", encoding="utf-8")

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            followup = provenance["profile_output_segments"]["followups"]["collect_default_metric_followup"]

            self.assertNotIn("profile_output", provenance)
            self.assertNotIn("profile_outputs", provenance)
            self.assertNotIn("profiler_status", provenance)
            self.assertNotIn("profile_date", provenance)
            self.assertEqual(followup["output"]["value"], "reports/followups/collect_default_metric_followup")
            self.assertEqual(followup["output"]["source"]["artifact"], "logs/command_msprof_followup_collect_default_metric_followup.txt")
            self.assertEqual(followup["resolved_output"]["value"], "reports/followups/collect_default_metric_followup/OPPROF_001")
            self.assertEqual(followup["resolved_output"]["source"]["artifact"], "logs/msprof_followup_collect_default_metric_followup.stdout")
            self.assertEqual(followup["status"]["value"], "0")
            self.assertEqual(followup["status"]["source"]["artifact"], "logs/msprof_followup_collect_default_metric_followup.status")
            self.assertIn("logs/msprof_followup_collect_default_metric_followup.stderr", provenance["sources"])

    def test_generate_provenance_records_app_op_statuses_and_inferred_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "tilelang_app_op"
            logs = run_dir / "logs"
            reports = run_dir / "reports"
            (reports / "app").mkdir(parents=True)
            (reports / "op").mkdir(parents=True)
            logs.mkdir(parents=True)
            (logs / "command_msprof.txt").write_text(
                f"msprof --output={reports / 'app'} --application={run_dir / 'harness' / 'app.sh'}\n",
                encoding="utf-8",
            )
            (logs / "command_msprof_op.txt").write_text(
                f"msprof op --output={reports / 'op'} --application={run_dir / 'harness' / 'op.sh'}\n",
                encoding="utf-8",
            )
            (logs / "msprof_default.stdout").write_text(
                "2026-06-02 09:00:01 [INFO]  App profiling start.\n",
                encoding="utf-8",
            )
            (logs / "msprof_default.status").write_text("0\n", encoding="utf-8")
            (logs / "msprof_op.stdout").write_text(
                "2026-06-02 09:00:11 [INFO]  Op profiling start.\n",
                encoding="utf-8",
            )
            (logs / "msprof_op.status").write_text("1\n", encoding="utf-8")
            (logs / "msprof_op_help.stdout").write_text(
                "2026-01-01 00:00:00 [INFO]  Profiling results saved in /tmp/help/reports/OPPROF_HELP\n",
                encoding="utf-8",
            )
            (logs / "msprof_op_help.status").write_text("9\n", encoding="utf-8")

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual(provenance["profile_date"]["value"], "2026-06-02 09:00:01")
            self.assertEqual([item["value"] for item in provenance["profiler_status"]], ["0", "1"])
            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/app", "reports/op"])
            self.assertEqual(provenance["profile_output"]["value"], "reports/app")
            for source in [
                "logs/msprof_default.stdout",
                "logs/msprof_default.status",
                "logs/msprof_op.stdout",
                "logs/msprof_op.status",
                "logs/command_msprof_op.txt",
            ]:
                self.assertIn(source, provenance["sources"])
            self.assertNotIn("logs/msprof_op_help.stdout", provenance["sources"])
            self.assertNotIn("logs/msprof_op_help.status", provenance["sources"])
            self.assertNotIn("collection_plan", provenance)

    def test_generate_provenance_records_app_op_output_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "tilelang_app_op_segments"
            logs = run_dir / "logs"
            reports = run_dir / "reports"
            (reports / "app").mkdir(parents=True)
            (reports / "op").mkdir(parents=True)
            logs.mkdir(parents=True)
            (logs / "command_msprof.txt").write_text(
                f"msprof --output={reports / 'app'} --application={run_dir / 'harness' / 'app.sh'}\n",
                encoding="utf-8",
            )
            (logs / "command_msprof_op.txt").write_text(
                f"msprof op --output={reports / 'op'} --application={run_dir / 'harness' / 'op.sh'}\n",
                encoding="utf-8",
            )
            (logs / "msprof_default.stdout").write_text(
                (
                    "2026-06-02 09:00:01 [INFO]  App profiling start.\n"
                    "2026-06-02 09:00:09 [INFO]  Process profiling data complete. Data is saved in "
                    f"{reports / 'app' / 'PROF_000001_20260602090001_APPAPPAPP'}\n"
                ),
                encoding="utf-8",
            )
            (logs / "msprof_default.status").write_text("0\n", encoding="utf-8")
            (logs / "msprof_op.stdout").write_text(
                (
                    "2026-06-02 09:00:11 [INFO]  Op profiling start.\n"
                    "2026-06-02 09:00:19 [INFO]  Profiling results saved in "
                    f"{reports / 'op' / 'OPPROF_20260602090011_OPOPOPOP'}\n"
                ),
                encoding="utf-8",
            )
            (logs / "msprof_op.status").write_text("0\n", encoding="utf-8")

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            segments = provenance["profile_output_segments"]

            self.assertEqual(segments["app"]["output"]["value"], "reports/app")
            self.assertEqual(segments["app"]["output"]["source"]["artifact"], "logs/command_msprof.txt")
            self.assertEqual(segments["app"]["output"]["source"]["field"], "--output")
            self.assertEqual(segments["app"]["resolved_output"]["value"], "reports/app/PROF_<sanitized>")
            self.assertEqual(
                segments["app"]["resolved_output"]["source"]["artifact"],
                "logs/msprof_default.stdout",
            )
            self.assertEqual(
                segments["app"]["resolved_output"]["source"]["field"],
                "Data is saved in",
            )
            self.assertEqual(segments["op"]["output"]["value"], "reports/op")
            self.assertEqual(segments["op"]["output"]["source"]["artifact"], "logs/command_msprof_op.txt")
            self.assertEqual(segments["op"]["output"]["source"]["field"], "--output")
            self.assertEqual(segments["op"]["resolved_output"]["value"], "reports/op/OPPROF_<sanitized>")
            self.assertEqual(segments["op"]["resolved_output"]["source"]["artifact"], "logs/msprof_op.stdout")
            self.assertEqual(
                segments["op"]["resolved_output"]["source"]["field"],
                "Profiling results saved in",
            )
            self.assertEqual(provenance["profile_output"]["value"], "reports/app/PROF_<sanitized>")

            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("- Profile outputs: app: reports/app", report)
            self.assertIn("resolved reports/app/PROF_<sanitized>", report)
            self.assertIn("op: reports/op", report)
            self.assertIn("resolved reports/op/OPPROF_<sanitized>", report)
            self.assertNotIn("- Profile output: reports/app/PROF_<sanitized>, reports/op/OPPROF_<sanitized>", report)

    def test_real_app_op_stdout_fixture_records_segmented_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_app_op_stdout_run(Path(tmp) / "profile")
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            segments = provenance["profile_output_segments"]

            self.assertEqual(segments["app"]["output"]["value"], "reports/app")
            self.assertEqual(segments["app"]["output"]["source"]["artifact"], "logs/command_msprof.txt")
            self.assertEqual(segments["app"]["resolved_output"]["value"], "reports/app/PROF_<sanitized>")
            self.assertEqual(segments["app"]["resolved_output"]["source"]["field"], "Data is saved in")
            self.assertEqual(segments["op"]["output"]["value"], "reports/op")
            self.assertEqual(segments["op"]["output"]["source"]["artifact"], "logs/command_msprof_op.txt")
            self.assertEqual(segments["op"]["resolved_output"]["value"], "reports/op/OPPROF_<sanitized>")
            self.assertEqual(segments["op"]["resolved_output"]["source"]["field"], "Profiling results saved in")
            self.assertEqual(provenance["profile_output"]["value"], "reports/app/PROF_<sanitized>")
            self.assertEqual(
                [item["value"] for item in provenance["profile_outputs"]],
                ["reports/app/PROF_<sanitized>", "reports/op/OPPROF_<sanitized>", "reports/app", "reports/op"],
            )
            self.assertNotIn("APPHASH1", json.dumps(provenance, sort_keys=True))
            self.assertNotIn("OPHASH12", json.dumps(provenance, sort_keys=True))

            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("- Profile outputs: app: reports/app", report)
            self.assertIn("resolved reports/app/PROF_<sanitized>", report)
            self.assertIn("op: reports/op", report)
            self.assertIn("resolved reports/op/OPPROF_<sanitized>", report)
            self.assertNotIn("- Profile output: reports/app/PROF_<sanitized>", report)

    def test_generate_provenance_merges_mixed_stdout_and_command_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "tilelang_mixed_outputs"
            logs = run_dir / "logs"
            reports = run_dir / "reports"
            (reports / "app").mkdir(parents=True)
            (reports / "op").mkdir(parents=True)
            logs.mkdir(parents=True)
            (logs / "command_msprof.txt").write_text(
                f"msprof --output={reports / 'app'} --application={run_dir / 'harness' / 'app.sh'}\n",
                encoding="utf-8",
            )
            (logs / "command_msprof_op.txt").write_text(
                f"msprof op --output={reports / 'op'} --application={run_dir / 'harness' / 'op.sh'}\n",
                encoding="utf-8",
            )
            (logs / "msprof_default.stdout").write_text(
                (
                    "2026-06-02 09:10:01 [INFO]  App profiling start.\n"
                    f"2026-06-02 09:10:09 [INFO]  Profiling results saved in {reports / 'app'}\n"
                ),
                encoding="utf-8",
            )
            (logs / "msprof_default.status").write_text("0\n", encoding="utf-8")
            (logs / "msprof_op.stdout").write_text(
                "2026-06-02 09:10:11 [INFO]  Op profiling start.\n",
                encoding="utf-8",
            )
            (logs / "msprof_op.status").write_text("0\n", encoding="utf-8")

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/app", "reports/op"])
            self.assertEqual(provenance["profile_output"]["value"], "reports/app")
            self.assertEqual(provenance["profile_output"]["source"]["artifact"], "logs/msprof_default.stdout")
            self.assertEqual(provenance["profile_outputs"][1]["source"]["artifact"], "logs/command_msprof_op.txt")

            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("- Profile outputs: app: reports/app (source: `logs/command_msprof.txt`; `--output`)", report)
            self.assertIn("resolved reports/app (source: `logs/msprof_default.stdout`", report)
            self.assertIn("reports/op (source: `logs/command_msprof_op.txt`; `--output`)", report)
            self.assertNotIn("- Profile output: not recorded", report)

    def test_generate_provenance_missing_logs_stays_offline_without_touching_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            shutil.rmtree(run_dir / "logs")
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            warnings = "\n".join(provenance["warnings"])

            self.assertIn("Missing logs/ directory", warnings)
            self.assertNotIn("cann_version", provenance)
            self.assertFalse((run_dir / "logs").exists())
            self.assertTrue((run_dir / "reports").exists())

    def test_generate_report_from_existing_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp) / "profile", "mock_run")
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("# MockMatMul Ascend Profiling Report", report)
            self.assertIn("**Run directory:** `profile/mock_run`", report)
            self.assertIn("**CANN / driver / firmware:** not recorded by this helper", report)
            self.assertIn("- Raw artifacts: `reports/`", report)
            self.assertNotIn("mock_run/reports/", report)
            self.assertIn("## 1. Headline Numbers", report)
            self.assertIn("## 3. Diagnosis", report)
            self.assertIn("## 6. Reproduction", report)
            self.assertIn("reports/PROF_001/mindstudio_profiler_output/op_summary_001.csv", report)
            self.assertIn("reports/OPPROF_001/PipeUtilization.csv", report)
            self.assertIn("headlines.memory.field=GM Read Bandwidth(GB/s)", report)
            read = one_line_read(report)
            self.assertIn("reports/PROF_001/mindstudio_profiler_output/op_summary_001.csv", read)
            self.assertIn("headlines.op_summary.value", read)
            self.assertNotIn("highest available sourced headline", read)
            self.assertNotIn(str(ROOT), report)

    def test_generate_report_missing_summary_uses_evidence_model_not_analyzer_cli(self):
        from ascend_msprof_skill import analyze_msprof_outputs

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_run(Path(tmp), "missing_summary_report")
            with mock.patch.object(analyze_msprof_outputs, "main", side_effect=AssertionError("wrong analyzer path")):
                summary = generate_report.load_or_create_summary(run_dir)

            self.assertEqual(summary["analysis_schema_version"], "1.5")
            self.assertTrue((run_dir / "analysis" / "summary.json").exists())
            self.assertTrue((run_dir / "analysis" / "raw_artifact_index.json").exists())
            self.assertTrue((run_dir / "analysis" / "key_metrics.txt").exists())
