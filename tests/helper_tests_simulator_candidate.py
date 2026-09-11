"""Simulator Candidate tests."""

from tests.helpers_shared import *  # noqa: F401,F403


class SimulatorCandidateTests(unittest.TestCase):
    def test_simulator_hotspots_and_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp))
            run([*CLI, "sim-hotspots", "--run-dir", str(run_dir)])
            run([*CLI, "timeline", "--run-dir", str(run_dir)])
            hotspots = (run_dir / "analysis" / "simulator_hotspots.txt").read_text()
            model = json.loads((run_dir / "analysis" / "simulator_hotspots.json").read_text())
            self.assertIn("- 155: mock_kernel.cpp:42", hotspots)
            self.assertEqual(model["source_lines"][0]["value"], 155.0)
            self.assertEqual(model["source_lines"][0]["source_file"], "mock_kernel.cpp")
            self.assertEqual(model["source_lines"][0]["line"], "42")
            self.assertNotIn("<unknown>", hotspots)
            timeline = timeline_text(run_dir)
            self.assertIn("MockMatMul", timeline)
            self.assertIn("aclrtSynchronizeStream", timeline)
            self.assertIn("msprof_001.json", timeline)

    def test_timeline_trace_events_object_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp))
            run([*CLI, "timeline", "--run-dir", str(run_dir)])
            timeline = timeline_text(run_dir)
            self.assertIn("| 120.5 | msprof_001.json | MockMatMul |", timeline)
            self.assertIn("| 8 | msprof_001.json | aclrtSynchronizeStream |", timeline)

    def test_timeline_real_cann_top_level_array(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_run(Path(tmp))
            run([*CLI, "timeline", "--run-dir", str(run_dir)])
            timeline = timeline_text(run_dir)
            self.assertIn("| 42399.1 | msprof_001.json | sanitized_kernel |", timeline)
            self.assertIn("| 42001.4 | msprof_001.json | Runtime@DeviceSynchronize |", timeline)
            self.assertIn("| 42399.1 | msprof_001.json | Computing |", timeline)

    def test_real_cann_minimal_missing_simulator_files_do_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_run(Path(tmp))
            run([*CLI, "sim-hotspots", "--run-dir", str(run_dir)])
            run([*CLI, "timeline", "--run-dir", str(run_dir)])
            model = json.loads((run_dir / "analysis" / "simulator_hotspots.json").read_text())
            self.assertEqual(model["inputs"], [])
            self.assertIn("No trace.json files found.", model["warnings"])
            self.assertIn(
                "No core*_code_exe.csv files found.",
                (run_dir / "analysis" / "simulator_hotspots.txt").read_text(),
            )
            timeline = timeline_text(run_dir)
            self.assertIn("sanitized_kernel", timeline)
            self.assertIn("Runtime@DeviceSynchronize", timeline)

    def test_simulator_hotspots_preserves_line_without_source_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_line_only_simulator_code_run(Path(tmp))
            run([*CLI, "sim-hotspots", "--run-dir", str(run_dir)])
            text = (run_dir / "analysis" / "simulator_hotspots.txt").read_text()
            model = json.loads((run_dir / "analysis" / "simulator_hotspots.json").read_text())

            self.assertIn("- 7.5: reports/OPPROF_001/simulator/core0_code_exe.csv:42", text)
            self.assertEqual(model["source_lines"][0]["line"], "42")
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            signals = dimensions["source_pipeline_context"]["signals"]
            self.assertEqual(
                signals[0]["signal"],
                "reports/OPPROF_001/simulator/core0_code_exe.csv:42",
            )
            self.assertIn(
                "reports/OPPROF_001/simulator/core0_code_exe.csv:42",
                (run_dir / "analysis" / "key_metrics.txt").read_text(),
            )

    def test_simulator_hotspots_adds_run_local_source_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run_local_source_simulator_code_run(Path(tmp))
            run([*CLI, "sim-hotspots", "--run-dir", str(run_dir)])
            text = (run_dir / "analysis" / "simulator_hotspots.txt").read_text()
            model = json.loads((run_dir / "analysis" / "simulator_hotspots.json").read_text())

            context = model["source_lines"][0]["source_context"]
            self.assertEqual(context["status"], "available")
            self.assertEqual(context["artifact"], "tilelang_tmp/tmp_kernel.cpp")
            self.assertEqual(context["line"], 5)
            self.assertIn("memory_movement", context["tags"])
            self.assertIn("pipeline_buffer", context["tags"])
            self.assertIn("scalar_control", context["tags"])
            self.assertNotIn("vector_compute", context["tags"])
            self.assertIn("source_context: tilelang_tmp/tmp_kernel.cpp:5", text)
            self.assertIn("source_context_tags:", text)
            self.assertIn("> 5:   AscendC::DataCopy(dst_ub, src_gm, 128);", text)
            for forbidden in ["bottleneck", "diagnosis", "optimization", "advice"]:
                self.assertNotIn(forbidden, text.lower())

    def test_simulator_source_context_tags_do_not_match_inside_identifiers(self):
        snippet = [
            {"line": 1, "text": "int subgroup = 0;"},
            {"line": 2, "text": "int segment = 0;"},
            {"line": 3, "text": "bool async_done = false;"},
            {"line": 4, "text": "int foobar = 0;"},
            {"line": 5, "text": "AscendC::Sub(dst, a, b);"},
        ]

        tags, basis = classify_source_context(snippet)

        self.assertIn("vector_compute", tags)
        self.assertEqual(basis["vector_compute"], ["AscendC::Sub"])
        self.assertNotIn("memory_movement", tags)
        self.assertNotIn("sync_context", tags)

    def test_simulator_hotspots_does_not_read_source_outside_run_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_external_source_simulator_code_run(Path(tmp))
            run([*CLI, "sim-hotspots", "--run-dir", str(run_dir)])
            text = (run_dir / "analysis" / "simulator_hotspots.txt").read_text()
            model = json.loads((run_dir / "analysis" / "simulator_hotspots.json").read_text())

            context = model["source_lines"][0]["source_context"]
            self.assertEqual(context["status"], "outside_run_dir")
            self.assertNotIn("external_kernel", text)
            self.assertIn("source_context: outside_run_dir", text)

    def test_simulator_hotspots_marks_missing_run_local_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_missing_source_simulator_code_run(Path(tmp))
            run([*CLI, "sim-hotspots", "--run-dir", str(run_dir)])
            text = (run_dir / "analysis" / "simulator_hotspots.txt").read_text()
            model = json.loads((run_dir / "analysis" / "simulator_hotspots.json").read_text())

            context = model["source_lines"][0]["source_context"]
            self.assertEqual(context["status"], "missing")
            self.assertEqual(context["artifact"], "tilelang_tmp/missing.cpp")
            self.assertIn("source_context: missing", text)

    def test_simulator_hotspots_marks_invalid_run_local_source_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_invalid_line_simulator_code_run(Path(tmp))
            run([*CLI, "sim-hotspots", "--run-dir", str(run_dir)])
            text = (run_dir / "analysis" / "simulator_hotspots.txt").read_text()
            model = json.loads((run_dir / "analysis" / "simulator_hotspots.json").read_text())

            context = model["source_lines"][0]["source_context"]
            self.assertEqual(context["status"], "invalid_line")
            self.assertEqual(context["artifact"], "tilelang_tmp/short.cpp")
            self.assertEqual(context["line_count"], 1)
            self.assertIn("source_context: invalid_line", text)

    def test_extract_real_simulator_minimal_trace_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_simulator_run(Path(tmp))
            run([*CLI, "sim-hotspots", "--run-dir", str(run_dir)])
            text = (run_dir / "analysis" / "simulator_hotspots.txt").read_text()
            model = json.loads((run_dir / "analysis" / "simulator_hotspots.json").read_text())
            self.assertIn("No source-line rows with numeric timing fields found.", text)
            self.assertEqual(model["simulator_hotspot_model_schema_version"], "1.1")
            self.assertEqual(model["source_lines"], [])
            self.assertTrue(model["instructions"])
            self.assertTrue(model["pipeline_events"])
            self.assertTrue(model["flow_categories"])
            self.assertIn("display_time_unit", model["inputs"][2])
            self.assertIn("- 2.99: MOV_OUT_TO_UB", text)
            self.assertIn("- 2.9: MOV_UB_TO_OUT", text)
            self.assertIn("## Trace Pipeline Context", text)
            self.assertIn("- displayTimeUnit: ns", text)
            self.assertIn("| 0.209 | 1 | MTE3 |", text)
            self.assertIn("| 0.154 | 1 | MTE2 |", text)
            self.assertIn("| 0.013 | 1 | VECTOR |", text)
            self.assertIn("## Trace Flow Categories", text)
            self.assertIn("| 2 | MTE2ToVECTOR |", text)
            self.assertIn("| 2 | VECTORToMTE3 |", text)
            self.assertIn("## MTE Throughput Context", text)
            self.assertIn(
                "No MTE Throughput counter events with numeric throughput(MB/s) values found in selected trace.json files.",
                text,
            )
            self.assertIn("## Synchronization Event Context", text)
            self.assertNotIn("bottleneck", text.lower())
            self.assertNotIn("overlap %", text.lower())

    def test_extract_resourceconflict_sync_event_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_resourceconflict_simulator_run(Path(tmp))
            run([*CLI, "sim-hotspots", "--run-dir", str(run_dir)])
            text = (run_dir / "analysis" / "simulator_hotspots.txt").read_text()
            model = json.loads((run_dir / "analysis" / "simulator_hotspots.json").read_text())
            trace_source = "reports/OPPROF_001/simulator/trace.json"
            core0_source = (
                "reports/OPPROF_001/simulator/core0.veccore0/core0.veccore0_instr_exe.csv"
            )
            core1_source = (
                "reports/OPPROF_001/simulator/core1.veccore0/core1.veccore0_instr_exe.csv"
            )

            self.assertIn("## Synchronization Event Context", text)
            self.assertIn(
                f"| SET_FLAG | 2 | 2 | 3 | 831 | 0.45 | {core0_source}; {core1_source}; {trace_source} |",
                text,
            )
            self.assertIn(
                f"| WAIT_FLAG | 2 | 2 | 3 | 837 | 0.48 | {core0_source}; {core1_source}; {trace_source} |",
                text,
            )
            self.assertEqual(
                [(row["instruction"], row["trace_events"], row["csv_rows"]) for row in model["sync_events"]],
                [("SET_FLAG", 2, 2), ("WAIT_FLAG", 2, 2)],
            )
            self.assertTrue(all(row["evidence_id"].startswith("sim.sync.") for row in model["sync_events"]))
            for forbidden in ["bottleneck", "diagnosis", "optimization", "advice"]:
                self.assertNotIn(forbidden, text.lower())

    def test_extract_pmsampling_mte_throughput_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_pmsampling_simulator_run(Path(tmp))
            run([*CLI, "sim-hotspots", "--run-dir", str(run_dir)])
            text = (run_dir / "analysis" / "simulator_hotspots.txt").read_text()
            model = json.loads((run_dir / "analysis" / "simulator_hotspots.json").read_text())
            source = "reports/OPPROF_001/simulator/trace.json"

            self.assertIn("## MTE Throughput Context", text)
            self.assertIn("## Synchronization Event Context", text)
            self.assertIn(
                "No SET_FLAG/WAIT_FLAG synchronization events found in selected simulator trace.json or core*_instr_exe.csv files.",
                text,
            )
            self.assertIn("throughput(MB/s)", text)
            self.assertIn(source, text)
            self.assertIn(f"| GM_TO_L1 | 0 | 0 | 2 | {source} |", text)
            self.assertIn(f"| GM_TO_TOTAL | 11718.8 | 7812.5 | 2 | {source} |", text)
            self.assertIn(f"| GM_TO_UB | 244.141 | 122.07 | 2 | {source} |", text)
            self.assertIn(f"| L1_TO_GM | 0 | 0 | 2 | {source} |", text)
            self.assertIn(f"| TOTAL_TO_GM | 7812.5 | 5859.38 | 2 | {source} |", text)
            self.assertIn(f"| UB_TO_GM | 7812.5 | 5859.38 | 2 | {source} |", text)
            self.assertNotIn("NOT_A_MTE_CHANNEL", text)
            self.assertEqual(
                sorted(row["channel"] for row in model["mte_throughput"]),
                ["GM_TO_L1", "GM_TO_TOTAL", "GM_TO_UB", "L1_TO_GM", "TOTAL_TO_GM", "UB_TO_GM"],
            )
            self.assertNotIn("NOT_A_MTE_CHANNEL", json.dumps(model))
            for forbidden in ["bottleneck", "diagnosis", "optimization", "advice"]:
                self.assertNotIn(forbidden, text.lower())

    def test_pmsampling_mte_throughput_top_sorts_by_throughput(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_pmsampling_simulator_run(Path(tmp))
            run([*CLI, "sim-hotspots", "--run-dir", str(run_dir), "--top", "3"])
            text = (run_dir / "analysis" / "simulator_hotspots.txt").read_text()
            section = text.split("## MTE Throughput Context", 1)[1]

            self.assertIn("| GM_TO_TOTAL | 11718.8 | 7812.5 | 2 |", section)
            self.assertIn("| TOTAL_TO_GM | 7812.5 | 5859.38 | 2 |", section)
            self.assertIn("| UB_TO_GM | 7812.5 | 5859.38 | 2 |", section)
            self.assertNotIn("| GM_TO_L1 |", section)
            self.assertNotIn("| L1_TO_GM |", section)


    def test_summarize_candidate_preserves_experiment_hint_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = fresh_run(root / "profile", "candidate_with_hints")
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            attach_tilelang_context(root, run_dir)
            set_evidence_readiness(run_dir)

            run([*CLI, "summarize-candidate", "--run-dir", str(run_dir)])
            candidate = json.loads((run_dir / "analysis" / "candidate_summary.json").read_text(encoding="utf-8"))
            direction_targets = [
                item
                for item in candidate["inspection_targets"]
                if item.get("source") == "optimization_directions"
            ]

            self.assertTrue(direction_targets)
            for target in direction_targets:
                self.assertIn("id", target)
                self.assertIn("rank", target)
                self.assertIn("evidence", target)
                self.assertIsInstance(target.get("experiment_hint"), dict)
                self.assertIn("next_experiment", target["experiment_hint"])
