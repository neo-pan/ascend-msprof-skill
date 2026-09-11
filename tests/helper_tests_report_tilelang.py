"""Report Tilelang tests."""

from tests.helpers_shared import *  # noqa: F401,F403


class ReportTileLangTests(unittest.TestCase):
    def test_generate_report_empty_run_collects_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "empty_run"
            run_dir.mkdir(parents=True)
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("**Run directory:** `profile/empty_run`", report)
            self.assertIn("No headline diagnosis generated", report)
            self.assertIn("Collect the missing profiler artifacts before changing kernel code.", report)
            self.assertNotIn("Inspect No headline diagnosis generated", report)

    def test_generate_report_surfaces_l2cache_without_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_l2cache_run(Path(tmp) / "profile", "real_l2cache_minimal")
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            assert_l2cache_report_evidence(self, report)
            self.assertIn("No headline diagnosis generated", report)
            self.assertNotIn("bottleneck", report.lower())
            self.assertNotIn("Inspect L2 cache", report)
            self.assertIn("### Analysis Dimensions", report)
            self.assertNotIn("Inspect Memory And Data Movement", report)
            self.assertNotIn(str(ROOT), report)

    def test_generate_report_surfaces_default_vector_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("# sanitized_add_custom_vector Ascend Profiling Report", report)
            self.assertIn("| Dominant pipe signal | vector0 / aiv_scalar_ratio | 0.992752 |", report)
            self.assertIn("reports/OPPROF_001/PipeUtilization.csv", report)
            self.assertIn("headlines.pipe_utilization.field=aiv_scalar_ratio", report)
            self.assertIn("| Arithmetic utilization signal | vector0 / aiv_vec_ratio | 0.06446 |", report)
            self.assertIn("headlines.arithmetic_utilization.field=aiv_vec_ratio", report)
            self.assertIn("| Top conflict signal | vector0 / aiv_vec_wait_ratio | 0.3824 |", report)
            self.assertIn("headlines.resource_conflict.field=aiv_vec_wait_ratio", report)
            self.assertIn("No headline diagnosis generated", report)
            self.assertIn("### Analysis Dimensions", report)
            self.assertIn("## 4. Optimization Directions", report)
            self.assertIn("1. Inspect Pipe And Arithmetic Mix", report)
            self.assertIn("(`inspect_pipe_arithmetic_mix`)", report)
            self.assertIn("Impact basis: Timing evidence is corroborated by PipeUtilization and ArithmeticUtilization signals.", report)
            self.assertIn("Confidence: medium; effort: medium", report)
            self.assertIn("`reports/OPPROF_001/PipeUtilization.csv` `headlines.pipe_utilization.value", report)
            self.assertNotIn("Highest pipe utilization signal", report)
            self.assertNotIn("Highest memory signal", report)
            self.assertNotIn("Highest resource conflict signal", report)
            self.assertNotIn("Inspect Highest", report)
            self.assertNotIn("TimelineDetail", report)
            self.assertNotIn("bottleneck", report.lower())
            self.assertNotIn(str(ROOT), report)

    def test_generate_report_surfaces_tiling_metadata_in_analysis_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_block_dim_with_timing_sim_run(Path(tmp) / "profile")
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            dimensions = report.split("### Analysis Dimensions", 1)[1].split("### Duration And Calls", 1)[0]

            self.assertIn("block_dim_kernel / Block Dim = 8", dimensions)
            self.assertIn("reports/OPPROF_001/OpBasicInfo.csv", dimensions)
            self.assertIn("headlines.op_basic_info.tiling_value", dimensions)
            self.assertIn("headlines.op_basic_info.first_row.Block Dim", dimensions)
            self.assertIn("headlines.op_basic_info.tiling_field=Block Dim", dimensions)
            self.assertNotIn("block_dim_kernel | `reports/OPPROF_001/OpBasicInfo.csv`; `headlines.op_basic_info.value", dimensions)

    def test_generate_report_mentions_simulator_model_only_in_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_simulator_run(Path(tmp) / "profile")
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            analysis = report.split("## 2. Analysis", 1)[1].split("## 3. Diagnosis", 1)[0]
            diagnosis = report.split("## 3. Diagnosis", 1)[1].split("## 4. Optimization Directions", 1)[0]

            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            self.assertIn("Structured simulator hotspot model is available at `analysis/simulator_hotspots.json`.", analysis)
            self.assertEqual(dimensions["source_pipeline_context"]["model_artifact"], "analysis/simulator_hotspots.json")
            self.assertNotIn("simulator_hotspots.json", diagnosis)
            self.assertNotIn("bottleneck", report.lower())

    def test_generate_report_surfaces_tiling_metadata_when_duration_present_without_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_duration_block_dim_no_sim_run(Path(tmp) / "profile")
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            dimensions = report.split("### Analysis Dimensions", 1)[1].split("### Duration And Calls", 1)[0]
            optimization = report.split("## 4. Optimization Directions", 1)[1].split(
                "## 5. Confidence And Caveats",
                1,
            )[0]

            self.assertIn("duration_block_dim_no_sim_kernel / Task Duration(us) = 3.5", dimensions)
            self.assertIn("duration_block_dim_no_sim_kernel / Block Dim = 8", dimensions)
            self.assertIn("headlines.op_basic_info.first_row.Task Duration(us)", dimensions)
            self.assertIn("headlines.op_basic_info.tiling_value", dimensions)
            self.assertIn("headlines.op_basic_info.first_row.Block Dim", dimensions)
            self.assertIn("headlines.op_basic_info.tiling_field=Block Dim", dimensions)
            self.assertNotIn("Inspect Tiling And Core Balance", optimization)

    def test_generate_report_surfaces_occupancy_summary_without_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_occupancy_stdout_run(Path(tmp) / "profile", "real_occupancy_stdout_minimal")
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            diagnosis = report.split("## 3. Diagnosis", 1)[1].split("## 4. Optimization Directions", 1)[0]
            optimization = report.split("## 4. Optimization Directions", 1)[1].split("## 5. Confidence And Caveats", 1)[0]

            self.assertIn("### Occupancy Summary", report)
            self.assertIn(
                "| 1 | core3 vector0 took more time than other vector cores. | `logs/msprof_occupancy.stdout` |",
                report,
            )
            self.assertIn(
                "| 2 | core0 vector0 cache hit rate lower than other vector cores. | `logs/msprof_occupancy.stdout` |",
                report,
            )
            self.assertNotIn("Occupancy", diagnosis)
            self.assertNotIn("core3 vector0", diagnosis)
            self.assertNotIn("cache hit rate lower", diagnosis)
            self.assertNotIn("Occupancy", optimization)
            self.assertNotIn("core3 vector0", optimization)
            self.assertNotIn("cache hit rate lower", optimization)
            self.assertNotIn("bottleneck", report.lower())
            self.assertNotIn(str(ROOT), report)

    def test_generate_report_surfaces_roofline_summary_without_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_roofline_stdout_run(Path(tmp) / "profile", "real_roofline_stdout_minimal")
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            diagnosis = report.split("## 3. Diagnosis", 1)[1].split("## 4. Optimization Directions", 1)[0]
            optimization = report.split("## 4. Optimization Directions", 1)[1].split("## 5. Confidence And Caveats", 1)[0]

            self.assertIn("### RoofLine Summary", report)
            self.assertIn(
                "| latency bound:pipeline caused | `logs/msprof_roofline.stdout` |",
                report,
            )
            self.assertNotIn("RoofLine", diagnosis)
            self.assertNotIn("Roofline", diagnosis)
            self.assertNotIn("latency bound", diagnosis)
            self.assertNotIn("pipeline caused", diagnosis)
            self.assertNotIn("RoofLine", optimization)
            self.assertNotIn("Roofline", optimization)
            self.assertNotIn("latency bound", optimization)
            self.assertNotIn("pipeline caused", optimization)
            self.assertNotIn("bottleneck", report.lower())
            self.assertNotIn(str(ROOT), report)

    def test_generate_report_keeps_performance_summary_stdout_only_out_of_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "performance_stdout_only"
            logs = run_dir / "logs"
            logs.mkdir(parents=True)
            (logs / "msprof_op.stdout").write_text(
                (
                    "2026-06-02 12:56:11 [INFO]  Performance Summary Report:\n"
                    "\n"
                    "\t1) aicore compute usage lower than 20%.\n"
                    "\n"
                    "2026-06-02 12:56:11 [INFO]  Operator Basic Information:\n"
                ),
                encoding="utf-8",
            )

            run([*CLI, "report", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            diagnosis = report.split("## 3. Diagnosis", 1)[1].split("## 4. Optimization Directions", 1)[0]
            optimization = report.split("## 4. Optimization Directions", 1)[1].split("## 5. Confidence And Caveats", 1)[0]

            self.assertEqual(summary["optimization_directions"], [])
            self.assertEqual(summary["next_collection_actions"], [])
            self.assertIn("### CANN Performance Summary", report)
            self.assertIn("| 1 | aicore compute usage lower than 20%. | `logs/msprof_op.stdout` |", report)
            stdout_records = [
                item
                for item in raw_artifact_index(run_dir)["artifacts"]
                if item["group"] == "stdout_performance_summary"
            ]
            self.assertEqual(len(stdout_records), 1)
            self.assertEqual(stdout_records[0]["artifact"], "logs/msprof_op.stdout")
            self.assertEqual(stdout_records[0]["segment"], "op")
            self.assertEqual(stdout_records[0]["row_count"], 1)
            self.assertNotIn("CANN Performance Summary", diagnosis)
            self.assertNotIn("aicore compute", diagnosis)
            self.assertNotIn("Pipe Utilization Advisory", optimization)
            self.assertNotIn("aicore compute", optimization)
            self.assertNotIn("bottleneck", report.lower())
            self.assertNotIn("rewrite", report.lower())

    def test_generate_report_pipe_scope_keeps_required_op_artifact_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "pipe_scope_missing_required"
            logs = run_dir / "logs"
            logs.mkdir(parents=True)
            (logs / "command_msprof_op.txt").write_text(
                "msprof op --output=<abs-path>/reports/op --application=<abs-path>/harness/op.sh --aic-metrics=PipeUtilization\n",
                encoding="utf-8",
            )

            run([*CLI, "report", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")

            self.assertTrue(any(warning.startswith("missing op_basic_info:") for warning in summary["warnings"]))
            self.assertTrue(any(warning.startswith("missing pipe_utilization:") for warning in summary["warnings"]))
            self.assertEqual(summary["metric_scope"]["value"], "PipeUtilization")
            actions = {item["id"]: item for item in summary["next_collection_actions"]}
            self.assertIn("recollect_pipeutilization", actions)
            self.assertIn("collect_default_metric_followup", actions)
            self.assertIn("- Op metric scope: PipeUtilization (source: `logs/command_msprof_op.txt`; `--aic-metrics`).", report)
            self.assertIn("Analyzer warning: missing op_basic_info:", report)
            self.assertIn("Analyzer warning: missing pipe_utilization:", report)
            self.assertNotIn("Analyzer warning: missing arithmetic_utilization:", report)
            self.assertNotIn("Analyzer warning: missing l2_cache:", report)
            self.assertNotIn("Analyzer warning: missing memory:", report)
            self.assertNotIn("Analyzer warning: missing resource_conflict:", report)

    def test_generate_report_unknown_metric_scope_preserves_missing_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "unknown_scope"
            logs = run_dir / "logs"
            logs.mkdir(parents=True)
            (logs / "command_msprof_op.txt").write_text(
                "msprof op --output=<abs-path>/reports/op --application=<abs-path>/harness/op.sh --aic-metrics=UnknownScope\n",
                encoding="utf-8",
            )

            run([*CLI, "report", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")

            self.assertEqual(summary["metric_scope"]["value"], "UnknownScope")
            self.assertFalse(summary["metric_scope"]["known"])
            self.assertEqual(summary["next_collection_actions"], [])
            self.assertIn("Analyzer warning: missing pipe_utilization:", report)
            self.assertIn("Analyzer warning: missing arithmetic_utilization:", report)
            self.assertIn("Analyzer warning: missing memory:", report)
            self.assertIn("Analyzer warning: missing resource_conflict:", report)

    def test_generate_report_uses_provenance_without_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            diagnosis = report.split("## 3. Diagnosis", 1)[1].split("## 4. Optimization Directions", 1)[0]
            optimization = report.split("## 4. Optimization Directions", 1)[1].split("## 5. Confidence And Caveats", 1)[0]

            self.assertNotIn("**CANN / driver / firmware:** not recorded by this helper", report)
            self.assertIn("**CANN / driver / firmware:** 8.3.0.2.220:8.3.RC2", report)
            self.assertIn("source: `logs/cann_version.cfg`; `toolkit_running_version`", report)
            self.assertIn("**Target:** 1 x 910B2; health OK", report)
            self.assertIn("**Profile date:** 2026-05-30 19:11:28", report)
            self.assertIn("- Profile command: msprof op --output=<abs-path>", report)
            self.assertIn("analysis/provenance.json", report)
            self.assertIn("ascend-msprof provenance --run-dir <run-dir>", report)
            self.assertIn("Provenance warning: Omitted path-like environment values", report)
            self.assertIn("No headline diagnosis generated", diagnosis)
            self.assertNotIn("CANN", diagnosis)
            self.assertNotIn("910B2", diagnosis)
            self.assertNotIn("provenance", diagnosis.lower())
            self.assertNotIn("CANN", optimization)
            self.assertNotIn("910B2", optimization)
            self.assertNotIn("provenance", optimization.lower())
            self.assertNotIn("/data/", report)
            self.assertNotIn("/home/", report)
            self.assertNotIn("/root/", report)
            self.assertNotIn("UARAJTADRTYKPBZQ", report)

    def test_generate_report_prefers_profile_outputs_and_falls_back_to_profile_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp) / "profile", "mock_run")
            provenance_path = run_dir / "analysis" / "provenance.json"
            provenance_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_dir": "profile/mock_run",
                        "sources": ["logs/msprof_default.stdout", "logs/msprof_op.stdout"],
                        "warnings": [],
                        "profile_output": {
                            "value": "reports/legacy",
                            "source": {"artifact": "logs/legacy.stdout", "field": "Profiling results saved in"},
                        },
                        "profile_outputs": [
                            {
                                "value": "reports/app/PROF_<sanitized>",
                                "source": {"artifact": "logs/msprof_default.stdout", "field": "Profiling results saved in"},
                            },
                            {
                                "value": "reports/op/OPPROF_<sanitized>",
                                "source": {"artifact": "logs/msprof_op.stdout", "field": "Profiling results saved in"},
                            },
                            {
                                "value": "reports/app",
                                "source": {"artifact": "logs/command_msprof.txt", "field": "--output"},
                            },
                            {
                                "value": "reports/op",
                                "source": {"artifact": "logs/command_msprof_op.txt", "field": "--output"},
                            },
                        ],
                        "profile_output_segments": {
                            "app": {
                                "output": {
                                    "value": "reports/app",
                                    "source": {"artifact": "logs/command_msprof.txt", "field": "--output"},
                                },
                                "resolved_output": {
                                    "value": "reports/app/PROF_<sanitized>",
                                    "source": {
                                        "artifact": "logs/msprof_default.stdout",
                                        "field": "Profiling results saved in",
                                    },
                                },
                            },
                            "op": {
                                "output": {
                                    "value": "reports/op",
                                    "source": {"artifact": "logs/command_msprof_op.txt", "field": "--output"},
                                },
                                "resolved_output": {
                                    "value": "reports/op/OPPROF_<sanitized>",
                                    "source": {"artifact": "logs/msprof_op.stdout", "field": "Profiling results saved in"},
                                },
                            },
                            "followups": {
                                "collect_default_metric_followup": {
                                    "output": {
                                        "value": "reports/followups/collect_default_metric_followup",
                                        "source": {
                                            "artifact": "logs/command_msprof_followup_collect_default_metric_followup.txt",
                                            "field": "--output",
                                        },
                                    },
                                    "resolved_output": {
                                        "value": "reports/followups/collect_default_metric_followup/OPPROF_<sanitized>",
                                        "source": {
                                            "artifact": "logs/msprof_followup_collect_default_metric_followup.stdout",
                                            "field": "Profiling results saved in",
                                        },
                                    },
                                    "status": {
                                        "value": "0",
                                        "source": {
                                            "artifact": "logs/msprof_followup_collect_default_metric_followup.status",
                                            "field": "exit_status",
                                        },
                                    },
                                },
                            },
                        },
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")

            self.assertIn("- Profile outputs: app: reports/app (source: `logs/command_msprof.txt`; `--output`)", report)
            self.assertIn(
                "resolved reports/app/PROF_<sanitized> (source: `logs/msprof_default.stdout`; "
                "`Profiling results saved in`)",
                report,
            )
            self.assertIn("op: reports/op (source: `logs/command_msprof_op.txt`; `--output`)", report)
            self.assertIn(
                "resolved reports/op/OPPROF_<sanitized> (source: `logs/msprof_op.stdout`; "
                "`Profiling results saved in`)",
                report,
            )
            self.assertIn(
                "followups.collect_default_metric_followup: "
                "reports/followups/collect_default_metric_followup "
                "(source: `logs/command_msprof_followup_collect_default_metric_followup.txt`; `--output`)",
                report,
            )
            self.assertIn(
                "resolved reports/followups/collect_default_metric_followup/OPPROF_<sanitized> "
                "(source: `logs/msprof_followup_collect_default_metric_followup.stdout`; "
                "`Profiling results saved in`)",
                report,
            )
            self.assertNotIn(
                "- Profile output: reports/app/PROF_<sanitized> (source: `logs/msprof_default.stdout`",
                report,
            )
            self.assertNotIn("reports/legacy", report)
            self.assertNotIn("- Profile output: not recorded", report)

            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance.pop("profile_output_segments")
            provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn(
                "- Profile output: reports/app/PROF_<sanitized> "
                "(source: `logs/msprof_default.stdout`; `Profiling results saved in`)",
                report,
            )
            self.assertIn("reports/op/OPPROF_<sanitized>", report)

            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance.pop("profile_outputs")
            provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("reports/legacy (source: `logs/legacy.stdout`; `Profiling results saved in`)", report)

    def test_collect_tilelang_context_writes_analysis_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = fresh_run(root / "profile", "tilelang_run")
            reports_before = reports_file_snapshot(run_dir)
            payload, benchmark = write_tilelang_inputs(root)
            jit_root = root / "tilelang-jit-debug"
            (jit_root / "module").mkdir(parents=True)
            (jit_root / "config.json").write_text('{"debug": true}\n', encoding="utf-8")
            (jit_root / "module" / "kernel.cce").write_text("// lowered kernel\n", encoding="utf-8")

            run([
                *CLI, "collect-tilelang",
                "--run-dir",
                str(run_dir),
                "--payload-src",
                str(payload),
                "--benchmark-json",
                str(benchmark),
                "--jit-debug-root",
                str(jit_root),
            ])
            context = json.loads((run_dir / "analysis" / "tilelang_context.json").read_text(encoding="utf-8"))

            self.assertEqual(context["schema_version"], 2)
            self.assertEqual(context["sources"]["payload"]["artifact"], "tilelang_kernel_payload.py")
            self.assertIn("def kernel_payload", context["sources"]["payload"]["content"])
            self.assertEqual(
                context["benchmark"]["workload"]["id"],
                "tilelang-ascend/kernel/v1/4096x2048-f16-cases2",
            )
            self.assertEqual(context["benchmark"]["workload"]["shape"], [4096, 2048])
            self.assertEqual(context["benchmark"]["workload"]["dtype"], "float16")
            self.assertEqual(context["benchmark"]["workload"]["case_count"], 2)
            self.assertEqual(context["benchmark"]["candidate"]["runtime_stats"]["mean_ms"], 1.25)
            self.assertEqual(context["benchmark"]["correctness"]["maxima"][0]["field"], "max_abs_error")
            self.assertEqual(context["jit_debug"]["artifact_count"], 2)
            self.assertEqual(context["warnings"], [])
            self.assertTrue((run_dir / "reports").exists())
            self.assertEqual(reports_before, reports_file_snapshot(run_dir))

    def test_collect_tilelang_context_missing_jit_debug_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = fresh_run(root / "profile", "tilelang_run")
            payload, benchmark = write_tilelang_inputs(root)
            missing_debug = root / "missing-jit-debug"

            result = subprocess.run(
                [
                    *CLI, "collect-tilelang",
                    "--run-dir",
                    str(run_dir),
                    "--payload-src",
                    str(payload),
                    "--benchmark-json",
                    str(benchmark),
                    "--jit-debug-root",
                    str(missing_debug),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=test_env(),
            )
            context = json.loads((run_dir / "analysis" / "tilelang_context.json").read_text(encoding="utf-8"))

            self.assertIn("warning: Optional JIT debug root missing: missing-jit-debug", result.stderr)
            self.assertEqual(context["jit_debug"]["provided"], "missing-jit-debug")
            self.assertFalse(context["jit_debug"]["found"])
            self.assertIn("Optional JIT debug root missing: missing-jit-debug", context["warnings"])

    def test_prepare_tilelang_profile_run_creates_layout_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "profile" / "tilelang_kernel"
            payload, benchmark = write_tilelang_inputs(root)

            result = subprocess.run(
                [
                    *CLI, "prepare-tilelang",
                    "--run-dir",
                    str(run_dir),
                    "--payload-src",
                    str(payload),
                    "--benchmark-json",
                    str(benchmark),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=test_env(),
            )
            workflow = json.loads((run_dir / "analysis" / "tilelang_profile_run.json").read_text(encoding="utf-8"))
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")

            self.assertTrue((run_dir / "reports").is_dir())
            self.assertTrue((run_dir / "analysis" / "tilelang_context.json").exists())
            self.assertIn("wrote", result.stdout)
            self.assertIn("warning: Created empty reports/ directory", result.stderr)
            self.assertEqual(workflow["workflow"], "TileLang kernel profiling workflow")
            self.assertTrue(workflow["artifacts"]["reports"]["created_by_prepare"])
            self.assertFalse(workflow["artifacts"]["reports"]["modified_by_prepare"])
            self.assertIn("### TileLang Benchmark Context", report)
            self.assertIn("tilelang-ascend/kernel/v1/4096x2048-f16-cases2", report)

    def test_prepare_tilelang_profile_run_preserves_existing_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = fresh_run(root / "profile", "tilelang_kernel")
            reports_before = reports_file_snapshot(run_dir)
            payload, benchmark = write_tilelang_inputs(root)

            run([
                *CLI, "prepare-tilelang",
                "--run-dir",
                str(run_dir),
                "--payload-src",
                str(payload),
                "--benchmark-json",
                str(benchmark),
            ])
            workflow = json.loads((run_dir / "analysis" / "tilelang_profile_run.json").read_text(encoding="utf-8"))

            self.assertEqual(reports_before, reports_file_snapshot(run_dir))
            self.assertFalse(workflow["artifacts"]["reports"]["created_by_prepare"])
            self.assertTrue(workflow["artifacts"]["reports"]["existed_before_prepare"])
            self.assertTrue((run_dir / "REPORT.md").exists())

    def test_prepare_tilelang_profile_run_missing_jit_debug_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = fresh_run(root / "profile", "tilelang_kernel")
            payload, benchmark = write_tilelang_inputs(root)
            missing_debug = root / "missing-jit-debug"

            result = subprocess.run(
                [
                    *CLI, "prepare-tilelang",
                    "--run-dir",
                    str(run_dir),
                    "--payload-src",
                    str(payload),
                    "--benchmark-json",
                    str(benchmark),
                    "--jit-debug-root",
                    str(missing_debug),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=test_env(),
            )
            workflow = json.loads((run_dir / "analysis" / "tilelang_profile_run.json").read_text(encoding="utf-8"))

            self.assertIn("warning: Optional JIT debug root missing: missing-jit-debug", result.stderr)
            self.assertIn("Optional JIT debug root missing: missing-jit-debug", workflow["warnings"])

    def test_generate_report_includes_tilelang_context_without_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "profile" / "tilelang_empty"
            run_dir.mkdir(parents=True)
            payload, benchmark = write_tilelang_inputs(root)
            run([
                *CLI, "collect-tilelang",
                "--run-dir",
                str(run_dir),
                "--payload-src",
                str(payload),
                "--benchmark-json",
                str(benchmark),
            ])
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            diagnosis = report.split("## 3. Diagnosis", 1)[1].split("## 4. Optimization Directions", 1)[0]
            optimization = report.split("## 4. Optimization Directions", 1)[1].split("## 5. Confidence And Caveats", 1)[0]

            self.assertIn("### TileLang Benchmark Context", report)
            self.assertIn(
                "| Workload id | tilelang-ascend/kernel/v1/4096x2048-f16-cases2 | `analysis/tilelang_context.json`; `benchmark.workload.id` |",
                report,
            )
            self.assertIn("mean_ms", report)
            self.assertIn("max_abs_error=0.000244", report)
            self.assertIn(
                "| Payload source | tilelang_kernel_payload.py | `analysis/tilelang_context.json`; `sources.payload.artifact` |",
                report,
            )
            self.assertIn("analysis/tilelang_context.json", report)
            self.assertIn("No headline diagnosis generated", diagnosis)
            self.assertNotIn("TileLang", diagnosis)
            self.assertNotIn("tilelang-ascend/kernel/v1/4096x2048-f16-cases2", diagnosis)
            self.assertNotIn("TileLang", optimization)
            self.assertNotIn("tilelang-ascend/kernel/v1/4096x2048-f16-cases2", optimization)
            self.assertNotIn(str(ROOT), report)

    def test_generate_report_runs_analyzer_when_summary_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_run(Path(tmp))
            self.assertFalse((run_dir / "analysis" / "summary.json").exists())
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertTrue((run_dir / "analysis" / "summary.json").exists())
            self.assertTrue((run_dir / "analysis" / "raw_artifact_index.json").exists())
            self.assertIn("# sanitized_operator_kernel Ascend Profiling Report", report)
            self.assertIn("analysis/raw_artifact_index.json", report)
            self.assertIn("reports/OPPROF_001/Memory.csv", report)
            self.assertIn("headlines.memory.field=UB_to_GM_bw_usage_rate(%)", report)
            self.assertIn("Optional analysis artifact missing: analysis/simulator_hotspots.txt", report)
            read = one_line_read(report)
            self.assertIn("reports/PROF_001/mindstudio_profiler_output/op_summary_001.csv", read)
            self.assertIn("headlines.op_summary.value", read)
            self.assertNotIn("highest available sourced headline", read)
            self.assertNotIn(str(ROOT), report)
