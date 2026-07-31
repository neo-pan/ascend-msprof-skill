"""Analysis tests."""

from tests.helpers_shared import *  # noqa: F401,F403


class AnalysisTests(HelperAssertionsMixin, unittest.TestCase):
    def test_analyze_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            self.assertEqual(summary["analysis_schema_version"], "1.4")
            self.assertEqual(summary["headlines"]["op_summary"]["name"], "MockMatMul")
            self.assertEqual(summary["headlines"]["op_summary"]["segment"], "app")
            self.assertIsNone(summary["headlines"]["op_summary"]["metric_scope"])
            self.assertEqual(summary["headlines"]["pipe_utilization"]["value"], 86.0)
            self.assertEqual(summary["headlines"]["pipe_utilization"]["segment"], "op")
            self.assertIsNone(summary["headlines"]["pipe_utilization"]["metric_scope"])
            self.assertEqual(summary["headlines"]["memory"]["name"], "metric")
            self.assertEqual(summary["headlines"]["memory"]["field"], "GM Read Bandwidth(GB/s)")
            self.assertEqual(summary["headlines"]["memory"]["value"], 700.0)
            self.assertEqual(summary["headlines"]["memory"]["field_kind"], "memory_bandwidth")
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            memory_signal = next(signal for signal in dimensions["memory_cache_movement"]["signals"] if signal["group"] == "memory")
            self.assertEqual(memory_signal["segment"], "op")
            self.assertIsNone(memory_signal["metric_scope"])
            self.assertEqual(memory_signal["field"], "Value")
            self.assertIn("headlines.memory.raw_row.Value", memory_signal["field_ref"])
            self.assertIn("headlines.memory.field=GM Read Bandwidth(GB/s)", memory_signal["field_ref"])
            self.assertNotIn("headlines.memory.raw_row.GM Read Bandwidth(GB/s)", memory_signal["field_ref"])
            self.assertIsNone(summary["stdout_sections"]["occupancy_summary"])
            self.assertFalse(any("occupancy" in warning.lower() for warning in summary["warnings"]))
            self.assertTrue((run_dir / "analysis" / "key_metrics.txt").exists())
            self.assertTrue((run_dir / "analysis" / "simulator_hotspots.json").exists())
            index = raw_artifact_index(run_dir)
            records = raw_artifacts_by_key(run_dir)
            self.assertEqual(index["raw_artifact_index_schema_version"], "1.1")
            self.assertTrue((run_dir / "analysis" / "raw_artifact_index.json").exists())
            self.assertNotIn("raw_artifact_index_schema_version", summary)
            self.assertEqual(
                records[("op_summary", "reports/PROF_001/mindstudio_profiler_output/op_summary_001.csv")]["segment"],
                "app",
            )
            self.assertEqual(
                records[("pipe_utilization", "reports/OPPROF_001/PipeUtilization.csv")]["parser"],
                "csv",
            )
            self.assertEqual(
                records[("app_timeline", "reports/PROF_001/mindstudio_profiler_output/msprof_001.json")]["row_count"],
                2,
            )
            self.assertEqual(
                records[("simulator_trace", "reports/OPPROF_001/trace.json")]["segment"],
                "simulator",
            )
            for artifact in [item["artifact"] for item in index["artifacts"]]:
                self.assertFalse(Path(artifact).is_absolute())
                self.assertNotIn(str(Path(tmp)), artifact)

    def test_evidence_model_writes_contract_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp))

            artifacts = evidence_model.write_evidence_model(run_dir)
            summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
            raw_index = json.loads(artifacts.raw_artifact_index_path.read_text(encoding="utf-8"))
            key_metrics = artifacts.key_metrics_path.read_text(encoding="utf-8")

            self.assertEqual(artifacts.summary_path, run_dir / "analysis" / "summary.json")
            self.assertEqual(artifacts.raw_artifact_index_path, run_dir / "analysis" / "raw_artifact_index.json")
            self.assertEqual(artifacts.key_metrics_path, run_dir / "analysis" / "key_metrics.txt")
            self.assertEqual(summary["analysis_schema_version"], "1.4")
            self.assertIsInstance(summary["headlines"], dict)
            self.assertIsInstance(summary["target_identity"], dict)
            self.assertIsInstance(summary["analysis_dimensions"], list)
            self.assertIsInstance(summary["next_collection_actions"], list)
            self.assertIsInstance(summary["evidence_relations"], list)
            self.assertIsInstance(summary["optimization_directions"], list)
            self.assertIsInstance(summary["evidence_readiness"], dict)
            self.assertNotIn("run_dir_path", summary)
            self.assertNotIn("_simulator_hotspot_model", summary)
            self.assertEqual(raw_index["raw_artifact_index_schema_version"], "1.1")
            self.assertIsInstance(raw_index["artifacts"], list)
            self.assertIn("# Ascend msprof Key Metrics", key_metrics)
            self.assertEqual(artifacts.summary["headlines"]["op_summary"]["name"], "MockMatMul")
            self.assertIn("run_dir_path", artifacts.summary)
            self.assertIn("_simulator_hotspot_model", artifacts.summary)
            self.assertGreater(len(artifacts.raw_artifact_index["artifacts"]), 0)

    def test_analyze_real_cann_minimal_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_run(Path(tmp))
            opprof_dir = run_dir / "reports" / "OPPROF_001"
            (opprof_dir / "visualize_data.bin").write_bytes(b"viz")
            dump_dir = opprof_dir / "dump"
            dump_dir.mkdir()
            (dump_dir / "DeviceProf1.bin").write_bytes(b"device")
            (dump_dir / "duration.bin").write_bytes(b"duration")
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            self.assertEqual(summary["headlines"]["op_summary"]["name"], "sanitized_kernel")
            self.assertEqual(summary["headlines"]["op_summary"]["segment"], "app")
            self.assertIsNone(summary["headlines"]["op_summary"]["metric_scope"])
            self.assertEqual(summary["headlines"]["op_summary"]["value"], 42399.12)
            self.assertEqual(summary["headlines"]["task_time"]["name"], "sanitized_kernel")
            self.assertEqual(summary["headlines"]["op_basic_info"]["name"], "sanitized_operator_kernel")
            self.assertEqual(summary["files"]["memory"][0]["row_count"], 2)
            self.assertEqual(summary["files"]["memory"][0]["segment"], "op")
            self.assertIsNone(summary["files"]["memory"][0]["metric_scope"])
            self.assertEqual(summary["headlines"]["memory"]["name"], "vector0")
            self.assertEqual(summary["headlines"]["memory"]["file"], "reports/OPPROF_001/Memory.csv")
            self.assertEqual(summary["headlines"]["memory"]["segment"], "op")
            self.assertIsNone(summary["headlines"]["memory"]["metric_scope"])
            self.assertEqual(summary["headlines"]["memory"]["field"], "UB_to_GM_bw_usage_rate(%)")
            self.assertEqual(summary["headlines"]["memory"]["value"], 0.357273)
            self.assertEqual(summary["headlines"]["memory"]["field_kind"], "memory_usage_rate")
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            self.assertEqual(dimensions["hot_path_dispatch"]["status"], "available")
            self.assertEqual(dimensions["pipe_arithmetic_mix"]["status"], "available")
            self.assertEqual(dimensions["memory_cache_movement"]["status"], "available")
            self.assertIn("headlines.op_summary.raw_row.Task Duration(us)", dimensions["hot_path_dispatch"]["evidence_refs"][0])
            self.assertTrue(summary["optimization_directions"])
            first_direction = summary["optimization_directions"][0]
            self.assertEqual(first_direction["rank"], 1)
            self.assertIn("evidence", first_direction)
            self.assertTrue(first_direction["requires_artifacts"])
            self.assertEqual(first_direction["missing_artifacts"], [])
            self.assertIn("evidence_id", first_direction["evidence"][0])
            self.assertIn("confidence", first_direction)
            self.assertIn("effort", first_direction)
            self.assertEqual(summary["next_collection_actions"], [])
            records = raw_artifacts_by_key(run_dir)
            app_timeline = records[("app_timeline", "reports/PROF_001/mindstudio_profiler_output/msprof_001.json")]
            self.assertEqual(app_timeline["parser"], "json")
            self.assertEqual(app_timeline["segment"], "app")
            self.assertEqual(app_timeline["status"], "parsed")
            self.assertNotIn("app_timeline", summary["headlines"])
            readiness = summary["evidence_readiness"]
            self.assertEqual(readiness["level"], "directional")
            self.assertIn("app_timing", readiness["available_evidence_families"])
            self.assertIn("memory_cache", readiness["available_evidence_families"])
            self.assertTrue(readiness["unparsed_binary_artifacts"])
            binary = records[("unparsed_profiler_binary", "reports/OPPROF_001/visualize_data.bin")]
            self.assertEqual(binary["parser"], "none")
            self.assertEqual(binary["status"], "unparsed")
            self.assertEqual(binary["segment"], "op")
            self.assertEqual(binary["size_bytes"], 3)
            self.assertEqual(binary["known_role"], "MindStudio visualization artifact")
            self.assertEqual(binary["diagnosis_role"], "not_used")
            device = records[("unparsed_profiler_binary", "reports/OPPROF_001/dump/DeviceProf1.bin")]
            self.assertEqual(device["parser"], "none")
            self.assertEqual(device["status"], "unparsed")
            self.assertEqual(device["known_role"], "internal device profiling dump")
            duration = records[("unparsed_profiler_binary", "reports/OPPROF_001/dump/duration.bin")]
            self.assertEqual(duration["known_role"], "internal raw duration dump")
            self.assertNotIn("unparsed_profiler_binary", json.dumps(summary["headlines"]))

    def test_evidence_readiness_levels_for_minimal_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            empty = root / "empty"
            empty.mkdir()
            run([*CLI, "analyze", "--run-dir", str(empty)])
            self.assertEqual(summary_json(empty)["evidence_readiness"]["level"], "insufficient")

            timing_only = root / "timing_only"
            write_minimal_app_timing(timing_only)
            run([*CLI, "analyze", "--run-dir", str(timing_only)])
            timing_readiness = summary_json(timing_only)["evidence_readiness"]
            self.assertEqual(timing_readiness["level"], "triage_only")
            self.assertIn("app_timing", timing_readiness["available_evidence_families"])
            self.assertIn("operator_metric", timing_readiness["missing_evidence_families"])
            self.assertIn(
                "propose focused kernel code experiment without stronger context",
                timing_readiness["blocked_claims"],
            )

            pipe_only = root / "pipe_only"
            write_minimal_pipe_op(pipe_only)
            run([*CLI, "analyze", "--run-dir", str(pipe_only)])
            pipe_readiness = summary_json(pipe_only)["evidence_readiness"]
            self.assertEqual(pipe_readiness["level"], "triage_only")
            self.assertIn("pipe_utilization", pipe_readiness["available_evidence_families"])
            self.assertIn("app_timing", pipe_readiness["missing_evidence_families"])

            app_pipe = root / "app_pipe"
            write_minimal_app_timing(app_pipe)
            write_minimal_pipe_op(app_pipe)
            run([*CLI, "analyze", "--run-dir", str(app_pipe)])
            app_pipe_readiness = summary_json(app_pipe)["evidence_readiness"]
            self.assertEqual(app_pipe_readiness["level"], "directional")
            self.assertIn("rank first AI Core pipe inspection direction", app_pipe_readiness["allowed_claims"])
            self.assertIn("source-line or instruction attribution without simulator/source artifacts", app_pipe_readiness["blocked_claims"])

    def test_evidence_readiness_does_not_promote_simulator_or_binary_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            simulator_only = root / "simulator_only"
            sim_dir = simulator_only / "reports" / "OPPROF_001" / "simulator"
            sim_dir.mkdir(parents=True)
            (sim_dir / "trace.json").write_text(json.dumps({"traceEvents": [{"name": "VECTOR", "dur": 5}]}), encoding="utf-8")
            (sim_dir / "visualize_data.bin").write_bytes(b"simviz")
            run([*CLI, "analyze", "--run-dir", str(simulator_only)])
            sim_summary = summary_json(simulator_only)
            sim_readiness = sim_summary["evidence_readiness"]
            self.assertEqual(sim_readiness["level"], "insufficient")
            self.assertIn("simulator_source_pipeline", sim_readiness["available_evidence_families"])
            self.assertIn("app_timing", sim_readiness["missing_evidence_families"])
            self.assertIn("operator_metric", sim_readiness["missing_evidence_families"])
            self.assertEqual(sim_summary["evidence_relations"], [])
            sim_records = raw_artifacts_by_key(simulator_only)
            sim_binary = sim_records[("unparsed_profiler_binary", "reports/OPPROF_001/simulator/visualize_data.bin")]
            self.assertEqual(sim_binary["known_role"], "simulator visualization artifact")
            self.assertEqual(sim_binary["diagnosis_role"], "not_used")

            binary_only = root / "binary_only"
            op_dir = binary_only / "reports" / "OPPROF_001" / "dump"
            op_dir.mkdir(parents=True)
            (op_dir / "DeviceProf0.bin").write_bytes(b"device")
            (op_dir / "duration.bin").write_bytes(b"duration")
            run([*CLI, "analyze", "--run-dir", str(binary_only)])
            binary_summary = summary_json(binary_only)
            binary_readiness = binary_summary["evidence_readiness"]
            self.assertEqual(binary_readiness["level"], "insufficient")
            self.assertEqual(binary_readiness["available_evidence_families"], [])
            self.assertTrue(binary_readiness["unparsed_binary_artifacts"])
            self.assertEqual(binary_summary["evidence_relations"], [])

    def test_evidence_relations_require_corroborated_cross_family_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            timing_only = root / "timing_only"
            write_minimal_app_timing(timing_only)
            run([*CLI, "analyze", "--run-dir", str(timing_only)])
            self.assertEqual(summary_json(timing_only)["evidence_relations"], [])

            app_pipe = root / "app_pipe"
            write_minimal_app_timing(app_pipe)
            write_minimal_pipe_op(app_pipe)
            run([*CLI, "analyze", "--run-dir", str(app_pipe)])
            relations = summary_json(app_pipe)["evidence_relations"]
            self.assertEqual([item["kind"] for item in relations], ["timing_plus_pipe"])
            self.assertEqual(relations[0]["confidence"], "low")
            self.assertEqual(
                [item["artifact"] for item in relations[0]["evidence"]],
                [
                    "reports/app/PROF_001/mindstudio_profiler_output/op_summary_001.csv",
                    "reports/op/OPPROF_001/PipeUtilization.csv",
                ],
            )
            self.assertIn("does not establish a performance cause", relations[0]["blocked_interpretation"])

            app_arithmetic = root / "app_arithmetic"
            write_minimal_app_timing(app_arithmetic)
            write_minimal_arithmetic_op(app_arithmetic)
            run([*CLI, "analyze", "--run-dir", str(app_arithmetic)])
            arithmetic_relations = summary_json(app_arithmetic)["evidence_relations"]
            self.assertEqual([item["kind"] for item in arithmetic_relations], ["timing_plus_arithmetic"])
            self.assertTrue(
                any(item["artifact"].endswith("ArithmeticUtilization.csv") for item in arithmetic_relations[0]["evidence"])
            )

            app_memory = root / "app_memory"
            write_minimal_app_timing(app_memory)
            write_minimal_memory_op(app_memory)
            run([*CLI, "analyze", "--run-dir", str(app_memory)])
            memory_relations = summary_json(app_memory)["evidence_relations"]
            self.assertEqual([item["kind"] for item in memory_relations], ["timing_plus_memory_cache"])
            self.assertTrue(any(item["artifact"].endswith("Memory.csv") for item in memory_relations[0]["evidence"]))

            app_l2 = root / "app_l2"
            write_minimal_app_timing(app_l2)
            write_minimal_l2_op(app_l2)
            run([*CLI, "analyze", "--run-dir", str(app_l2)])
            l2_relations = summary_json(app_l2)["evidence_relations"]
            self.assertEqual([item["kind"] for item in l2_relations], ["timing_plus_memory_cache"])
            self.assertTrue(any(item["artifact"].endswith("L2Cache.csv") for item in l2_relations[0]["evidence"]))

            app_conflict = root / "app_conflict"
            write_minimal_app_timing(app_conflict)
            write_minimal_resource_conflict_op(app_conflict)
            run([*CLI, "analyze", "--run-dir", str(app_conflict)])
            conflict_relations = summary_json(app_conflict)["evidence_relations"]
            self.assertEqual([item["kind"] for item in conflict_relations], ["timing_plus_resource_conflict"])
            self.assertTrue(
                any(item["artifact"].endswith("ResourceConflictRatio.csv") for item in conflict_relations[0]["evidence"])
            )

            app_pipe_sim = root / "app_pipe_sim"
            write_minimal_app_timing(app_pipe_sim)
            write_minimal_pipe_op(app_pipe_sim)
            write_minimal_simulator_trace(app_pipe_sim)
            run([*CLI, "analyze", "--run-dir", str(app_pipe_sim)])
            sim_relations = {
                item["kind"]: item for item in summary_json(app_pipe_sim)["evidence_relations"]
            }
            self.assertIn("timing_plus_pipe", sim_relations)
            self.assertIn("timing_metric_plus_simulator_trace", sim_relations)
            trace_relation = sim_relations["timing_metric_plus_simulator_trace"]
            self.assertTrue(trace_relation["source_context_refs"])
            self.assertEqual(trace_relation["source_context_refs"][0]["artifact"], "analysis/simulator_hotspots.json")
            self.assertTrue(
                any(item["artifact"].endswith("trace.json") for item in trace_relation["evidence"])
            )

            app_pipe_source = fresh_line_only_simulator_code_run(root, "app_pipe_source")
            write_minimal_app_timing(app_pipe_source)
            write_minimal_pipe_op(app_pipe_source)
            run([*CLI, "analyze", "--run-dir", str(app_pipe_source)])
            source_relations = {
                item["kind"]: item for item in summary_json(app_pipe_source)["evidence_relations"]
            }
            self.assertIn("timing_metric_plus_simulator_source", source_relations)
            source_relation = source_relations["timing_metric_plus_simulator_source"]
            self.assertTrue(source_relation["source_context_refs"])
            self.assertEqual(source_relation["source_context_refs"][0]["field_ref"], "source_lines[0]")
            self.assertTrue(
                any(item["artifact"].endswith("core0_code_exe.csv") for item in source_relation["evidence"])
            )

            app_pipe_instruction = fresh_multi_row_simulator_csv_run(root, "app_pipe_instruction")
            write_minimal_app_timing(app_pipe_instruction)
            write_minimal_pipe_op(app_pipe_instruction)
            run([*CLI, "analyze", "--run-dir", str(app_pipe_instruction)])
            instruction_relations = {
                item["kind"]: item for item in summary_json(app_pipe_instruction)["evidence_relations"]
            }
            self.assertIn("timing_metric_plus_simulator_instruction", instruction_relations)
            instruction_relation = instruction_relations["timing_metric_plus_simulator_instruction"]
            self.assertTrue(instruction_relation["source_context_refs"])
            self.assertEqual(instruction_relation["source_context_refs"][0]["field_ref"], "instructions[0]")
            self.assertTrue(
                any(item["artifact"].endswith("core0_instr_exe.csv") for item in instruction_relation["evidence"])
            )

            stdout_only = fresh_real_occupancy_stdout_run(root / "stdout_only")
            run([*CLI, "analyze", "--run-dir", str(stdout_only)])
            self.assertEqual(summary_json(stdout_only)["evidence_relations"], [])

    def test_evidence_relations_respect_blocked_target_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_target_identity_run(
                Path(tmp),
                expected="main_kernel",
                observed="Cast_15ccf3aee15572ed7572778d4afbef60_high_performance_210010000",
                app_observed="main_kernel",
            )
            write_minimal_pipe_op(run_dir)
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = summary_json(run_dir)

            self.assertEqual(summary["target_identity"]["status"], "partial_mismatch")
            self.assertEqual(summary["target_identity"]["confidence"], "blocked")
            self.assertEqual(summary["optimization_directions"], [])
            self.assertEqual(summary["evidence_relations"], [])

    def test_generate_report_renders_evidence_relations_only_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            app_pipe = root / "app_pipe"
            write_minimal_app_timing(app_pipe)
            write_minimal_pipe_op(app_pipe)
            run([*CLI, "report", "--run-dir", str(app_pipe)])
            summary = summary_json(app_pipe)
            report = (app_pipe / "REPORT.md").read_text(encoding="utf-8")

            self.assertEqual([item["kind"] for item in summary["evidence_relations"]], ["timing_plus_pipe"])
            self.assertIn("### Evidence Relations", report)
            self.assertIn("`timing_plus_pipe`", report)
            self.assertIn("minimal_kernel", report)
            self.assertIn("confidence", report.lower())
            self.assertIn("reports/op/OPPROF_001/PipeUtilization.csv", report)
            self.assertIn("Allowed:", report)
            self.assertIn("Blocked:", report)
            self.assertNotIn("root cause is", report.lower())
            self.assertNotIn("rewrite", report.lower())
            self.assertNotIn("guaranteed", report.lower())

            timing_only = root / "timing_only"
            write_minimal_app_timing(timing_only)
            run([*CLI, "report", "--run-dir", str(timing_only)])
            timing_report = (timing_only / "REPORT.md").read_text(encoding="utf-8")
            self.assertEqual(summary_json(timing_only)["evidence_relations"], [])
            self.assertNotIn("### Evidence Relations", timing_report)

    def test_analyze_real_l2cache_minimal_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_l2cache_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            l2_file = summary["files"]["l2_cache"][0]
            l2_headline = summary["headlines"]["l2_cache"]
            self.assertIn("aic_total_hit_rate(%)", l2_file["columns"])
            self.assertIn("aiv_total_hit_rate(%)", l2_file["columns"])
            self.assertEqual(l2_file["row_count"], 3)
            self.assertEqual(l2_headline["file"], "reports/OPPROF_001/L2Cache.csv")
            self.assertEqual(l2_headline["name"], "cube0")
            self.assertEqual(l2_headline["field"], "aic_total_hit_rate(%)")
            self.assertEqual(l2_headline["value"], 72.0)
            self.assertEqual(l2_headline["field_kind"], "l2_cache_hit_rate")
            key_metrics = (run_dir / "analysis" / "key_metrics.txt").read_text()
            self.assertIn("- l2_cache: cube0 aic_total_hit_rate(%) = 72", key_metrics)
            self.assertNotIn("bottleneck", key_metrics.lower())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            self.assertEqual(dimensions["memory_cache_movement"]["status"], "available")
            self.assertEqual(summary["optimization_directions"], [])

    def test_analyze_real_default_vector_minimal_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            pipe = summary["headlines"]["pipe_utilization"]
            arithmetic = summary["headlines"]["arithmetic_utilization"]
            conflict = summary["headlines"]["resource_conflict"]
            self.assertEqual(summary["headlines"]["op_basic_info"]["name"], "sanitized_add_custom_vector")
            self.assertEqual(pipe["file"], "reports/OPPROF_001/PipeUtilization.csv")
            self.assertEqual(pipe["name"], "vector0")
            self.assertEqual(pipe["field"], "aiv_scalar_ratio")
            self.assertEqual(pipe["value"], 0.992752)
            self.assertEqual(arithmetic["field"], "aiv_vec_ratio")
            self.assertEqual(arithmetic["value"], 0.06446)
            self.assertEqual(conflict["field"], "aiv_vec_wait_ratio")
            self.assertEqual(conflict["value"], 0.3824)
            key_metrics = (run_dir / "analysis" / "key_metrics.txt").read_text()
            self.assertIn("- pipe_utilization: vector0 aiv_scalar_ratio = 0.992752", key_metrics)
            self.assertIn("- arithmetic_utilization: vector0 aiv_vec_ratio = 0.06446", key_metrics)
            self.assertIn("- resource_conflict: vector0 aiv_vec_wait_ratio = 0.3824", key_metrics)
            self.assertEqual(summary["metric_scope"]["value"], "Default")
            self.assertTrue(summary["metric_scope"]["known"])
            self.assertEqual(summary["next_collection_actions"], [])

    def test_analyze_pipe_default_followup_fixture_clears_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_pipe_default_followup_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            self.assertEqual(summary["metric_scope"]["value"], "PipeUtilization")
            self.assertEqual(summary["next_collection_actions"], [])
            pipe_files = {
                Path(item["path"]).relative_to(run_dir).as_posix(): item
                for item in summary["files"]["pipe_utilization"]
            }
            self.assertEqual(pipe_files["reports/op/OPPROF_001/PipeUtilization.csv"]["segment"], "op")
            self.assertEqual(pipe_files["reports/op/OPPROF_001/PipeUtilization.csv"]["metric_scope"], "PipeUtilization")
            self.assertEqual(
                pipe_files["reports/followups/collect_default_metric_followup/OPPROF_001/PipeUtilization.csv"]["segment"],
                "followup:collect_default_metric_followup",
            )
            self.assertEqual(
                pipe_files["reports/followups/collect_default_metric_followup/OPPROF_001/PipeUtilization.csv"]["metric_scope"],
                "Default",
            )
            arithmetic = summary["headlines"]["arithmetic_utilization"]
            self.assertEqual(arithmetic["segment"], "followup:collect_default_metric_followup")
            self.assertEqual(arithmetic["metric_scope"], "Default")
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            arithmetic_signal = next(
                signal
                for signal in dimensions["pipe_arithmetic_mix"]["signals"]
                if signal["group"] == "arithmetic_utilization"
            )
            self.assertEqual(arithmetic_signal["segment"], "followup:collect_default_metric_followup")
            self.assertEqual(arithmetic_signal["metric_scope"], "Default")
            evidence = [
                item
                for direction in summary["optimization_directions"]
                for item in direction["evidence"]
                if item["artifact"] == "reports/followups/collect_default_metric_followup/OPPROF_001/ArithmeticUtilization.csv"
            ]
            self.assertTrue(evidence)
            self.assertTrue(all(item["segment"] == "followup:collect_default_metric_followup" for item in evidence))
            self.assertTrue(all(item["metric_scope"] == "Default" for item in evidence))
            self.assertEqual(
                summary["headlines"]["arithmetic_utilization"]["file"],
                "reports/followups/collect_default_metric_followup/OPPROF_001/ArithmeticUtilization.csv",
            )
            self.assertEqual(
                summary["headlines"]["resource_conflict"]["file"],
                "reports/followups/collect_default_metric_followup/OPPROF_001/ResourceConflictRatio.csv",
            )
            records = raw_artifacts_by_key(run_dir)
            self.assertEqual(
                records[("pipe_utilization", "reports/op/OPPROF_001/PipeUtilization.csv")]["segment"],
                "op",
            )
            self.assertEqual(
                records[("pipe_utilization", "reports/op/OPPROF_001/PipeUtilization.csv")]["metric_scope"],
                "PipeUtilization",
            )
            self.assertEqual(
                records[
                    (
                        "arithmetic_utilization",
                        "reports/followups/collect_default_metric_followup/OPPROF_001/ArithmeticUtilization.csv",
                    )
                ]["segment"],
                "followup:collect_default_metric_followup",
            )
            self.assertEqual(
                records[
                    (
                        "arithmetic_utilization",
                        "reports/followups/collect_default_metric_followup/OPPROF_001/ArithmeticUtilization.csv",
                    )
                ]["metric_scope"],
                "Default",
            )

    def test_analyze_real_occupancy_stdout_summary_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_occupancy_stdout_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            occupancy = summary["stdout_sections"]["occupancy_summary"]
            key_metrics = (run_dir / "analysis" / "key_metrics.txt").read_text()
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            op_basic_signal = next(
                signal
                for signal in dimensions["tiling_core_balance"]["signals"]
                if signal["group"] == "op_basic_info"
            )

            self.assertEqual(occupancy["source"], "logs/msprof_occupancy.stdout")
            self.assertEqual(occupancy["section"], "Occupancy Summary Report")
            self.assertEqual(
                occupancy["messages"],
                [
                    {"ordinal": 1, "message": "core3 vector0 took more time than other vector cores."},
                    {"ordinal": 2, "message": "core0 vector0 cache hit rate lower than other vector cores."},
                ],
            )
            self.assertNotIn("core_id", occupancy["messages"][0])
            self.assertNotIn("role", occupancy["messages"][0])
            self.assertNotIn("severity", occupancy["messages"][0])
            self.assertNotIn("advice", occupancy["messages"][0])
            self.assertEqual(op_basic_signal["field"], "task_duration")
            self.assertIn("headlines.op_basic_info.first_row.task_duration", op_basic_signal["field_ref"])
            self.assertIn("## Occupancy Summary", key_metrics)
            self.assertIn("| 1 | core3 vector0 took more time than other vector cores. | logs/msprof_occupancy.stdout |", key_metrics)
            stdout_records = [
                item
                for item in raw_artifact_index(run_dir)["artifacts"]
                if item["group"] == "stdout_occupancy_summary"
            ]
            self.assertEqual(len(stdout_records), 1)
            self.assertEqual(stdout_records[0]["artifact"], "logs/msprof_occupancy.stdout")
            self.assertEqual(stdout_records[0]["parser"], "stdout")
            self.assertEqual(stdout_records[0]["segment"], "unknown")
            self.assertEqual(stdout_records[0]["row_count"], 2)

    def test_analyze_real_roofline_stdout_summary_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_roofline_stdout_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            roofline = summary["stdout_sections"]["roofline_summary"]
            key_metrics = (run_dir / "analysis" / "key_metrics.txt").read_text()

            self.assertEqual(roofline["source"], "logs/msprof_roofline.stdout")
            self.assertEqual(roofline["section"], "RoofLine Summary Report")
            self.assertEqual(roofline["messages"], [{"message": "latency bound:pipeline caused"}])
            self.assertNotIn("bound_type", roofline["messages"][0])
            self.assertNotIn("cause", roofline["messages"][0])
            self.assertNotIn("severity", roofline["messages"][0])
            self.assertNotIn("advice", roofline["messages"][0])
            self.assertNotIn("optimization", roofline["messages"][0])
            self.assertIn("## RoofLine Summary", key_metrics)
            self.assertIn("| latency bound:pipeline caused | logs/msprof_roofline.stdout |", key_metrics)
            stdout_records = [
                item
                for item in raw_artifact_index(run_dir)["artifacts"]
                if item["group"] == "stdout_roofline_summary"
            ]
            self.assertEqual(len(stdout_records), 1)
            self.assertEqual(stdout_records[0]["artifact"], "logs/msprof_roofline.stdout")
            self.assertEqual(stdout_records[0]["row_count"], 1)

    def test_analyze_source_shape_op_summary_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_summary_variant_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            op_summary_columns = summary["files"]["op_summary"][0]["columns"]
            op_summary = summary["headlines"]["op_summary"]
            raw_row = op_summary["raw_row"]
            self.assertEqual(op_summary_columns[0], "Device_id")
            self.assertIn("aicore_time(us)", op_summary_columns)
            self.assertIn("total_cycles", op_summary_columns)
            self.assertIn("ai*_scalar_time(us)", op_summary_columns)
            self.assertIn("ai*_scalar_ratio", op_summary_columns)
            self.assertIn("ai*_mte2_time(us)", op_summary_columns)
            self.assertEqual(op_summary["name"], "official_kernel_b")
            self.assertEqual(op_summary["value"], 88.125)
            self.assertEqual(raw_row["aicore_time(us)"], "77.0")
            self.assertEqual(raw_row["total_cycles"], "2000")
            self.assertEqual(raw_row["ai*_vec_time(us)"], "8.0")
            self.assertEqual(raw_row["ai*_mac_time(us)"], "9.0")
            self.assertEqual(raw_row["ai*_scalar_time(us)"], "10.0")
            self.assertEqual(raw_row["ai*_scalar_ratio"], "0.75")
            self.assertEqual(raw_row["ai*_mte2_time(us)"], "11.0")
            self.assertEqual(op_summary["field_kind"], "duration_or_time")
            directions = summary["optimization_directions"]
            self.assertEqual(len(directions), 1)
            self.assertEqual(directions[0]["id"], "focus_hot_path")
            self.assertIn("without enough corroborating metric families", directions[0]["impact_basis"])
            self.assertNotIn("rewrite", json.dumps(directions).lower())

    def test_analyze_target_identity_match_allows_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_target_identity_run(Path(tmp), expected="main_kernel", observed="main_kernel_mix_aic")
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            identity = summary["target_identity"]
            self.assertEqual(identity["status"], "match")
            self.assertEqual(identity["expected"]["names"], ["main_kernel"])
            self.assertEqual(identity["observed"][0]["name"], "main_kernel_mix_aic")
            self.assertEqual(identity["observed"][0]["match_rule"], "known_suffix")
            self.assertEqual(identity["confidence"], "medium")
            self.assertFalse(any("target identity mismatch" in warning for warning in summary["warnings"]))
            self.assertTrue(summary["optimization_directions"])

    def test_analyze_target_identity_exact_match_confidence_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_target_identity_run(Path(tmp), expected="main_kernel", observed="main_kernel")
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            identity = json.loads((run_dir / "analysis" / "summary.json").read_text())["target_identity"]

            self.assertEqual(identity["status"], "match")
            self.assertEqual(identity["observed"][0]["match_rule"], "exact")
            self.assertEqual(identity["confidence"], "high")

    def test_analyze_target_identity_exact_multiple_targets_not_high_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_multi_expected_target_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            identity = json.loads((run_dir / "analysis" / "summary.json").read_text())["target_identity"]

            self.assertEqual(identity["status"], "match")
            self.assertEqual({item["match_rule"] for item in identity["observed"]}, {"exact"})
            self.assertEqual({item["name"] for item in identity["observed"]}, {"kernel_a", "kernel_b"})
            self.assertEqual(identity["confidence"], "medium")

    def test_analyze_target_identity_mismatch_blocks_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_target_identity_run(
                Path(tmp),
                expected="main_kernel",
                observed="Cast_15ccf3aee15572ed7572778d4afbef60_high_performance_210010000",
            )
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            identity = summary["target_identity"]
            self.assertEqual(identity["status"], "mismatch")
            self.assertEqual(identity["expected"]["names"], ["main_kernel"])
            self.assertEqual(identity["observed"][0]["name"], "Cast_15ccf3aee15572ed7572778d4afbef60_high_performance_210010000")
            self.assertEqual(identity["observed"][0]["match_rule"], "unmatched")
            self.assertEqual(identity["confidence"], "blocked")
            self.assertTrue(any("target identity mismatch" in warning for warning in summary["warnings"]))
            self.assertEqual(summary["optimization_directions"], [])

    def test_analyze_target_identity_does_not_match_inner_substring(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_target_identity_run(
                Path(tmp),
                expected="Mul",
                observed="MatMul",
            )
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            identity = summary["target_identity"]
            self.assertEqual(identity["status"], "mismatch")
            self.assertEqual(identity["observed"][0]["status"], "mismatch")
            self.assertEqual(identity["observed"][0]["match_rule"], "unmatched")
            self.assertEqual(identity["confidence"], "blocked")
            self.assertEqual(summary["optimization_directions"], [])

    def test_analyze_target_identity_partial_mismatch_blocks_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_target_identity_run(
                Path(tmp),
                expected="main_kernel",
                observed="main_kernel_mix_aic",
                app_observed="framework_helper_kernel",
            )
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            identity = summary["target_identity"]
            self.assertEqual(identity["status"], "partial_mismatch")
            statuses = {item["group"]: item["status"] for item in identity["observed"]}
            self.assertEqual(statuses["op_basic_info"], "match")
            self.assertEqual(statuses["op_summary"], "mismatch")
            self.assertEqual(identity["confidence"], "blocked")
            self.assertTrue(any("target identity partial_mismatch" in warning for warning in summary["warnings"]))
            self.assertEqual(summary["optimization_directions"], [])

    def test_analyze_target_identity_missing_observed_blocks_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_missing_observed_target_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            identity = summary["target_identity"]
            self.assertEqual(identity["status"], "missing_observed")
            self.assertEqual(identity["expected"]["names"], ["main_kernel"])
            self.assertEqual(identity["observed"], [])
            self.assertEqual(identity["confidence"], "blocked")
            self.assertTrue(any("target identity missing observed" in warning for warning in summary["warnings"]))
            self.assertEqual(summary["optimization_directions"], [])

    def test_analyze_target_identity_unverified_without_expected_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_target_identity_run(
                Path(tmp),
                observed="Cast_15ccf3aee15572ed7572778d4afbef60_high_performance_210010000",
                include_expected=False,
            )
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            self.assertEqual(summary["target_identity"]["status"], "unverified")
            self.assertEqual(summary["target_identity"]["confidence"], "low")
            self.assertNotIn("match_rule", summary["target_identity"]["observed"][0])
            self.assertFalse(any("target identity" in warning for warning in summary["warnings"]))
            self.assertTrue(summary["optimization_directions"])

    def test_analyze_tilelang_context_infers_main_kernel_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_target_identity_run(
                Path(tmp),
                observed="main_kernel_mix_aic",
                include_expected=False,
                tilelang_context=True,
            )
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            identity = summary["target_identity"]
            self.assertEqual(identity["status"], "match")
            self.assertEqual(identity["expected"]["names"], ["main_kernel"])
            self.assertTrue(identity["expected"]["inferred"])
            self.assertEqual(identity["expected"]["field_ref"], "inferred:tilelang_default_kernel")
            self.assertTrue(summary["optimization_directions"])

    def test_analyze_tilelang_context_inferred_target_catches_framework_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_target_identity_run(
                Path(tmp),
                observed="Cast_15ccf3aee15572ed7572778d4afbef60_high_performance_210010000",
                include_expected=False,
                tilelang_context=True,
            )
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            identity = summary["target_identity"]
            self.assertEqual(identity["status"], "mismatch")
            self.assertEqual(identity["expected"]["names"], ["main_kernel"])
            self.assertTrue(identity["expected"]["inferred"])
            self.assertTrue(any("target identity mismatch" in warning for warning in summary["warnings"]))
            self.assertEqual(summary["optimization_directions"], [])

    def test_analyze_explicit_target_overrides_tilelang_default_from_earlier_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_explicit_target_precedence_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            identity = summary["target_identity"]
            self.assertEqual(identity["status"], "match")
            self.assertEqual(identity["expected"]["names"], ["custom_kernel"])
            self.assertEqual(identity["expected"]["artifact"], "analysis/tilelang_context.json")
            self.assertNotIn("inferred", identity["expected"])
            self.assertTrue(summary["optimization_directions"])

    def test_analyze_simulator_context_records_raw_field_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_simulator_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            signals = dimensions["source_pipeline_context"]["signals"]
            model = json.loads((run_dir / "analysis" / "simulator_hotspots.json").read_text())

            self.assertEqual(model["simulator_hotspot_model_schema_version"], "1.1")
            self.assertEqual(dimensions["source_pipeline_context"]["model_artifact"], "analysis/simulator_hotspots.json")
            self.assertTrue(model["instructions"])
            self.assertTrue(model["pipeline_events"])
            self.assertEqual(model["inputs"][0]["parser_status"], "empty")
            self.assertTrue(any(signal["field"] == "running_time(us)" for signal in signals))
            self.assertTrue(any(signal["field"] == "traceEvents[].dur" for signal in signals))
            self.assertTrue(any("source_pipeline_context.signals.field=running_time(us)" in signal["field_ref"] for signal in signals))
            self.assertTrue(any("source_pipeline_context.signals.value" in signal["field_ref"] for signal in signals))
            self.assertTrue(any(signal.get("evidence_id") for signal in signals))
            self.assertTrue(any(signal["value"] is not None for signal in signals))
            self.assertTrue(signals)
            self.assertTrue(all(signal["segment"] == "simulator" for signal in signals))
            self.assertTrue(all(signal["metric_scope"] is None for signal in signals))
            self.assertEqual(summary["optimization_directions"], [])
            records = raw_artifacts_by_key(run_dir)
            self.assertIn(
                ("simulator_csv", "reports/OPPROF_001/simulator/core3.veccore0/core3.veccore0_code_exe.csv"),
                records,
            )
            self.assertIn(
                ("simulator_csv", "reports/OPPROF_001/simulator/core3.veccore0/core3.veccore0_instr_exe.csv"),
                records,
            )
            self.assertEqual(records[("simulator_trace", "reports/OPPROF_001/simulator/trace.json")]["segment"], "simulator")

    def test_analyze_simulator_trace_uses_largest_duration_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_multi_duration_trace_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            trace_signals = [
                signal
                for signal in dimensions["source_pipeline_context"]["signals"]
                if signal["artifact"].endswith("trace.json")
            ]

            self.assertEqual(len(trace_signals), 1)
            self.assertEqual(trace_signals[0]["field"], "traceEvents[].dur")
            self.assertEqual(trace_signals[0]["signal"], "dominant_pipeline")
            self.assertEqual(trace_signals[0]["value"], 640.0)

    def test_analyze_simulator_top_level_trace_uses_largest_duration_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_top_level_trace_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            trace_signals = [
                signal
                for signal in dimensions["source_pipeline_context"]["signals"]
                if signal["artifact"].endswith("trace.json")
            ]

            self.assertEqual(len(trace_signals), 1)
            self.assertEqual(trace_signals[0]["field"], "traceEvents[].dur")
            self.assertEqual(trace_signals[0]["signal"], "dominant_top_level")
            self.assertEqual(trace_signals[0]["value"], 900.0)

    def test_simulator_model_keeps_per_core_trace_pipeline_artifacts_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_per_core_trace_only_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            model = json.loads((run_dir / "analysis" / "simulator_hotspots.json").read_text())

            rows = sorted(model["pipeline_events"], key=lambda row: row["artifact"])
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                [(row["artifact"], row["duration"]) for row in rows],
                [
                    ("reports/OPPROF_001/simulator/core0.veccore0/trace.json", 10.0),
                    ("reports/OPPROF_001/simulator/core1.veccore0/trace.json", 20.0),
                ],
            )
            for row in rows:
                self.assertIn(row["artifact"], row["field_ref"])

    def test_simulator_model_uses_per_core_trace_when_aggregate_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_invalid_aggregate_with_valid_per_core_trace_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            model = json.loads((run_dir / "analysis" / "simulator_hotspots.json").read_text())
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            inputs = {row["artifact"]: row["parser_status"] for row in model["inputs"]}
            self.assertEqual(inputs["reports/OPPROF_001/simulator/trace.json"], "invalid")
            self.assertEqual(inputs["reports/OPPROF_001/simulator/core0.veccore0/trace.json"], "parsed")
            self.assertEqual(len(model["pipeline_events"]), 1)
            self.assertEqual(
                model["pipeline_events"][0]["artifact"],
                "reports/OPPROF_001/simulator/core0.veccore0/trace.json",
            )
            self.assertEqual(model["pipeline_events"][0]["value"], 123.0)

            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            trace_signals = [
                signal
                for signal in dimensions["source_pipeline_context"]["signals"]
                if signal["artifact"].endswith("core0.veccore0/trace.json")
            ]
            self.assertEqual(len(trace_signals), 1)
            self.assertEqual(trace_signals[0]["signal"], "per_core_valid")
            self.assertEqual(trace_signals[0]["value"], 123.0)

    def test_analyze_simulator_csv_uses_largest_running_time_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_multi_row_simulator_csv_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            csv_signals = [
                signal
                for signal in dimensions["source_pipeline_context"]["signals"]
                if signal["artifact"].endswith("core0_instr_exe.csv")
            ]

            self.assertEqual(len(csv_signals), 1)
            self.assertEqual(csv_signals[0]["field"], "running_time(us)")
            self.assertEqual(csv_signals[0]["signal"], "dominant_instr")
            self.assertEqual(csv_signals[0]["value"], 75.0)

    def test_analyze_unreadable_optional_simulator_csv_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_unreadable_simulator_csv_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            signals = dimensions["source_pipeline_context"]["signals"]

            self.assertTrue((run_dir / "analysis" / "key_metrics.txt").exists())
            self.assertTrue(any(warning.startswith("invalid simulator csv") for warning in summary["warnings"]))
            self.assertEqual(signals[0]["field"], "file")
            self.assertEqual(signals[0]["kind"], "simulator_artifact")
            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])

    def test_analyze_op_basic_plus_simulator_only_does_not_emit_tiling_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_simulator_only_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            op_basic_signal = dimensions["tiling_core_balance"]["signals"][0]

            self.assertEqual(op_basic_signal["field"], "task_duration")
            self.assertIn("headlines.op_basic_info.first_row.task_duration", op_basic_signal["field_ref"])
            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])
            self.assertNotIn("inspect_tiling_core_balance", json.dumps(summary["optimization_directions"]))

    def test_analyze_op_basic_block_dim_can_emit_tiling_direction_with_field_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_block_dim_with_timing_sim_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            op_basic_signal = dimensions["tiling_core_balance"]["signals"][0]
            directions = {item["id"]: item for item in summary["optimization_directions"]}

            self.assertIsNone(op_basic_signal["field"])
            self.assertIsNone(op_basic_signal["value"])
            self.assertEqual(op_basic_signal["tiling_field"], "Block Dim")
            self.assertEqual(op_basic_signal["tiling_value"], 8.0)
            self.assertNotIn("headlines.op_basic_info.first_row.Block Dim", op_basic_signal["field_ref"])
            self.assertIn("inspect_tiling_core_balance", directions)
            evidence = json.dumps(directions["inspect_tiling_core_balance"]["evidence"])
            self.assertIn("headlines.op_basic_info.tiling_value", evidence)
            self.assertIn("headlines.op_basic_info.first_row.Block Dim", evidence)
            self.assertIn("headlines.op_basic_info.tiling_field=Block Dim", evidence)

    def test_analyze_op_basic_block_dim_without_timing_does_not_emit_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_block_dim_sim_only_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            op_basic_signal = dimensions["tiling_core_balance"]["signals"][0]

            self.assertIsNone(op_basic_signal["field"])
            self.assertIsNone(op_basic_signal["value"])
            self.assertEqual(op_basic_signal["tiling_field"], "Block Dim")
            self.assertEqual(op_basic_signal["tiling_value"], 8.0)
            self.assertEqual(summary["optimization_directions"], [])

    def test_analyze_op_basic_blank_block_dim_does_not_emit_tiling_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_invalid_block_dim_with_timing_sim_run(Path(tmp), "")
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            op_basic_signal = dimensions["tiling_core_balance"]["signals"][0]

            self.assertEqual(op_basic_signal["tiling_field"], "Block Dim")
            self.assertIsNone(op_basic_signal["tiling_value"])
            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])
            self.assertNotIn("inspect_tiling_core_balance", json.dumps(summary["optimization_directions"]))

    def test_analyze_op_basic_non_numeric_block_dim_does_not_emit_tiling_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_invalid_block_dim_with_timing_sim_run(Path(tmp), "not_recorded")
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            op_basic_signal = dimensions["tiling_core_balance"]["signals"][0]

            self.assertEqual(op_basic_signal["tiling_field"], "Block Dim")
            self.assertIsNone(op_basic_signal["tiling_value"])
            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])
            self.assertNotIn("inspect_tiling_core_balance", json.dumps(summary["optimization_directions"]))

    def test_analyze_op_basic_duration_only_does_not_emit_tiling_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_duration_only_with_timing_sim_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            op_basic_signal = dimensions["tiling_core_balance"]["signals"][0]

            self.assertEqual(op_basic_signal["field"], "Task Duration(us)")
            self.assertIn("headlines.op_basic_info.first_row.Task Duration(us)", op_basic_signal["field_ref"])
            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])
            self.assertNotIn("inspect_tiling_core_balance", json.dumps(summary["optimization_directions"]))

    def test_analyze_op_basic_duration_plus_block_dim_uses_tiling_evidence_for_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_duration_block_dim_with_timing_sim_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            op_basic_signal = dimensions["tiling_core_balance"]["signals"][0]
            directions = {item["id"]: item for item in summary["optimization_directions"]}

            self.assertEqual(op_basic_signal["field"], "Task Duration(us)")
            self.assertEqual(op_basic_signal["tiling_field"], "Block Dim")
            self.assertIn("inspect_tiling_core_balance", directions)
            evidence = json.dumps(directions["inspect_tiling_core_balance"]["evidence"])
            self.assertIn("headlines.op_basic_info.tiling_value", evidence)
            self.assertIn("headlines.op_basic_info.first_row.Block Dim", evidence)
            self.assertIn("headlines.op_basic_info.tiling_field=Block Dim", evidence)
            self.assertNotIn("headlines.op_basic_info.field=Task Duration(us)", evidence)

    def test_analyze_name_only_op_basic_does_not_emit_tiling_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_name_only_op_basic_with_timing_sim_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            op_basic_signal = dimensions["tiling_core_balance"]["signals"][0]

            self.assertIsNone(op_basic_signal["field"])
            self.assertNotIn("headlines.op_basic_info.first_row.Task Duration(us)", op_basic_signal["field_ref"])
            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])
            self.assertNotIn("inspect_tiling_core_balance", json.dumps(summary["optimization_directions"]))

    def test_analyze_malformed_optional_trace_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_malformed_trace_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}

            self.assertTrue((run_dir / "analysis" / "key_metrics.txt").exists())
            self.assertTrue(any(warning.startswith("invalid simulator trace") for warning in summary["warnings"]))
            self.assertEqual(dimensions["source_pipeline_context"]["signals"][0]["field"], "file")
            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])
            self.assertNotIn("inspect_tiling_core_balance", json.dumps(summary["optimization_directions"]))
            trace_record = raw_artifacts_by_key(run_dir)[("simulator_trace", "reports/OPPROF_001/simulator/trace.json")]
            self.assertEqual(trace_record["status"], "invalid")
            self.assertEqual(trace_record["row_count"], 0)
            self.assertTrue(trace_record["warnings"][0].startswith("invalid json reports/OPPROF_001/simulator/trace.json"))
            self.assertIn(trace_record["warnings"][0], raw_artifact_index(run_dir)["warnings"])

    def test_generate_report_empty_direction_model_does_not_use_legacy_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_header_only_op_summary_run(Path(tmp) / "profile")
            run([*CLI, "report", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            optimization = report.split("## 4. Optimization Directions", 1)[1].split(
                "## 5. Confidence And Caveats",
                1,
            )[0]

            self.assertEqual(summary["optimization_directions"], [])
            self.assertIn("No ranked optimization direction generated from the available evidence.", optimization)
            self.assertNotIn("Inspect Highest application-level operator duration", optimization)
            self.assertNotIn("= n/a", optimization)
            op_summary_record = raw_artifacts_by_key(run_dir)[
                ("op_summary", "reports/PROF_001/mindstudio_profiler_output/op_summary_001.csv")
            ]
            self.assertEqual(op_summary_record["status"], "empty")
            self.assertEqual(op_summary_record["columns"], ["Op Name", "Task Duration(us)"])
            self.assertEqual(op_summary_record["row_count"], 0)

    def test_optimization_direction_experiment_hint_for_timing_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "timing_only"
            write_minimal_app_timing(run_dir)
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])
            direction = summary["optimization_directions"][0]
            self.assert_experiment_hint_shape(direction, ["op_summary_*.csv", "task_time_*.csv"])
            hint = direction["experiment_hint"]
            self.assertIn("timing", " ".join(hint["caveats"]).lower())
            self.assertIn("Collect the missing operator-level metric family", hint["next_experiment"])
            self.assertNotIn("source_context", hint)

    def test_focus_hot_path_hint_includes_fresh_next_collection_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "default_scope_timing_only"
            write_minimal_app_timing(run_dir)
            logs = run_dir / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            (logs / "command_msprof_op.txt").write_text(
                "msprof op --output=<abs-path>/reports/op --application=<abs-path>/run.sh --aic-metrics=Default\n",
                encoding="utf-8",
            )

            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            direction = summary["optimization_directions"][0]
            action_artifacts = summary["next_collection_actions"][0]["required_artifacts"]
            hint_artifacts = direction["experiment_hint"]["recollect_artifacts"]

            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])
            self.assertEqual(summary["next_collection_actions"][0]["id"], "recollect_default")
            for artifact in action_artifacts:
                self.assertIn(artifact, hint_artifacts)

    def test_optimization_direction_experiment_hints_preserve_rank_and_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            directions = summary["optimization_directions"]

            self.assertEqual(
                [(item["rank"], item["id"]) for item in directions],
                [
                    (1, "inspect_pipe_arithmetic_mix"),
                    (2, "inspect_memory_movement"),
                    (3, "inspect_resource_conflict"),
                ],
            )
            required_fields = {
                "id",
                "rank",
                "title",
                "action",
                "impact_basis",
                "confidence",
                "effort",
                "requires_artifacts",
                "missing_artifacts",
                "evidence",
                "experiment_hint",
            }
            for item in directions:
                self.assertTrue(required_fields.issubset(item.keys()))
                self.assertNotIn("score", item)

            by_id = {item["id"]: item for item in directions}
            self.assert_experiment_hint_shape(
                by_id["inspect_pipe_arithmetic_mix"],
                ["PipeUtilization.csv", "ArithmeticUtilization.csv"],
            )
            self.assert_experiment_hint_shape(
                by_id["inspect_memory_movement"],
                ["Memory.csv", "MemoryL0.csv", "MemoryUB.csv", "L2Cache.csv"],
            )
            self.assert_experiment_hint_shape(
                by_id["inspect_resource_conflict"],
                ["ResourceConflictRatio.csv", "PipeUtilization.csv"],
            )

    def test_optimization_direction_experiment_hints_for_specialized_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            advisory_run = fresh_real_app_op_stdout_run(root / "advisory")
            run([*CLI, "analyze", "--run-dir", str(advisory_run)])
            advisory_summary = json.loads((advisory_run / "analysis" / "summary.json").read_text())
            advisory = {
                item["id"]: item for item in advisory_summary["optimization_directions"]
            }["inspect_pipe_utilization_advisory"]
            self.assert_experiment_hint_shape(advisory, ["PipeUtilization.csv", "profiler stdout log"])
            self.assertIn("stdout wording alone is not enough", advisory["experiment_hint"]["expected_profiler_change"])
            self.assertIn(
                "corroborating context",
                " ".join(advisory["experiment_hint"]["caveats"]),
            )

            tiling_run = fresh_op_basic_block_dim_with_timing_sim_run(root / "tiling")
            run([*CLI, "analyze", "--run-dir", str(tiling_run)])
            tiling_summary = json.loads((tiling_run / "analysis" / "summary.json").read_text())
            tiling = {
                item["id"]: item for item in tiling_summary["optimization_directions"]
            }["inspect_tiling_core_balance"]
            self.assert_experiment_hint_shape(tiling, ["OpBasicInfo.csv", "trace.json", "core*_instr_exe.csv"])
            self.assertIn("work-distribution", tiling["experiment_hint"]["next_experiment"])

    def test_optimization_direction_experiment_hint_source_context_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_block_dim_with_timing_sim_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            directions = {
                item["id"]: item for item in summary["optimization_directions"]
            }

            tiling = directions["inspect_tiling_core_balance"]
            source_context = tiling["experiment_hint"].get("source_context")
            self.assert_source_context_shape(source_context)
            self.assertTrue(
                any(item["field_ref"].startswith("pipeline_events[") for item in source_context)
            )

            focus = directions["focus_hot_path"]
            self.assertNotIn("source_context", focus["experiment_hint"])

    def test_optimization_direction_experiment_hints_do_not_create_directions_without_timing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "pipe_only"
            op_dir = run_dir / "reports" / "op" / "OPPROF_001"
            op_dir.mkdir(parents=True, exist_ok=True)
            (op_dir / "PipeUtilization.csv").write_text(
                "Pipe,Utilization(%)\nVector,73\n",
                encoding="utf-8",
            )
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            self.assertEqual(summary["optimization_directions"], [])

    def test_optimization_direction_source_context_requires_on_device_timing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_block_dim_sim_only_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            self.assertEqual(summary["optimization_directions"], [])
            self.assertNotIn("source_context", json.dumps(summary))

    def test_generate_report_renders_experiment_hints(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_block_dim_with_timing_sim_run(Path(tmp))
            run([*CLI, "report", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            optimization = report.split("## 4. Optimization Directions", 1)[1].split(
                "## 5. Confidence And Caveats", 1
            )[0]

            self.assertIn("experiment_hint", json.dumps(summary["optimization_directions"]))
            self.assertIn("   - Inspect code area:", optimization)
            self.assertIn("   - Next experiment:", optimization)
            self.assertIn("   - Expected profiler change:", optimization)
            self.assertIn("   - Recollect artifacts:", optimization)
            self.assertIn("   - Source context:", optimization)
            self.assertIn("   - Caveats:", optimization)
            self.assertIn("analysis/simulator_hotspots.json", optimization)
            self.assertNotIn("## Experiment Hints", report)
            self.assertNotIn("rewrite", optimization.lower())
            self.assertNotIn("guaranteed", optimization.lower())

    def test_generate_report_skips_missing_experiment_hint_source_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "timing_only_report"
            write_minimal_app_timing(run_dir)
            run([*CLI, "report", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            optimization = report.split("## 4. Optimization Directions", 1)[1].split(
                "## 5. Confidence And Caveats", 1
            )[0]

            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])
            self.assertIn("   - Inspect code area:", optimization)
            self.assertIn("   - Next experiment:", optimization)
            self.assertIn("   - Expected profiler change:", optimization)
            self.assertIn("   - Recollect artifacts:", optimization)
            self.assertIn("   - Caveats:", optimization)
            self.assertNotIn("   - Source context:", optimization)

    def test_analyze_header_only_op_basic_does_not_emit_tiling_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_header_only_op_basic_with_timing_sim_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])
            self.assertNotIn("inspect_tiling_core_balance", json.dumps(summary["optimization_directions"]))

    def test_analyze_prefers_op_statistic_timing_before_op_basic_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_statistic_op_basic_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            first_evidence = summary["optimization_directions"][0]["evidence"][0]

            self.assertEqual(summary["optimization_directions"][0]["id"], "focus_hot_path")
            self.assertEqual(first_evidence["artifact"], "reports/PROF_001/mindstudio_profiler_output/op_statistic_001.csv")
            self.assertIn("headlines.op_statistic.value", first_evidence["field_ref"])
            self.assertNotIn("OpBasicInfo.csv", first_evidence["artifact"])

    def test_analyze_pipe_l2_emits_memory_direction_without_memory_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_pipe_l2_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            directions = {item["id"]: item for item in summary["optimization_directions"]}

            self.assertIn("inspect_memory_movement", directions)
            evidence = json.dumps(directions["inspect_memory_movement"]["evidence"])
            self.assertIn("reports/OPPROF_001/L2Cache.csv", evidence)
            self.assertIn("headlines.l2_cache.value", evidence)

    def test_analyze_conflict_simulator_emits_conflict_direction_without_pipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_conflict_simulator_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            directions = {item["id"]: item for item in summary["optimization_directions"]}

            self.assertIn("inspect_resource_conflict", directions)
            self.assertIn(
                "simulator source/pipeline context",
                directions["inspect_resource_conflict"]["impact_basis"],
            )
            self.assertNotIn("another operator-level metric family", directions["inspect_resource_conflict"]["impact_basis"])
            evidence = json.dumps(directions["inspect_resource_conflict"]["evidence"])
            self.assertIn("reports/OPPROF_001/ResourceConflictRatio.csv", evidence)
            self.assertIn("reports/OPPROF_001/simulator/trace.json", evidence)

    def test_experiment_hint_docs_describe_limits(self):
        schema = (ROOT / "skills" / "ascend-msprof-skill" / "reference" / "10-summary-schema.md").read_text(
            encoding="utf-8"
        )
        playbook = (ROOT / "skills" / "ascend-msprof-skill" / "reference" / "06-diagnosis-playbook.md").read_text(
            encoding="utf-8"
        )
        template = (ROOT / "skills" / "ascend-msprof-skill" / "reference" / "07-report-template.md").read_text(
            encoding="utf-8"
        )
        docs = "\n".join([schema, playbook, template])

        self.assertIn("experiment_hint", schema)
        self.assertIn("source_context", schema)
        self.assertIn("support or refute", docs)
        self.assertIn("not a code-change instruction", docs)
        self.assertNotIn("guaranteed outcome", docs.lower())
