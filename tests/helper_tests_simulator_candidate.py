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
            # Historical synthetic File/Line/Time(us) and Instruction/Cycles
            # layouts remain raw evidence; no unconfirmed aliases are interpreted.
            self.assertEqual(model["source_lines"], [])
            self.assertEqual(model["instructions"], [])
            self.assertTrue(any(issue["code"] == "unsupported_identity"
                                for item in model["inputs"] for issue in item["issues"]))
            timeline = timeline_text(run_dir)
            self.assertIn("MockMatMul", timeline)
            self.assertIn("aclrtSynchronizeStream", timeline)
            self.assertIn("msprof_001.json", timeline)

    def test_timeline_trace_events_object_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp))
            run([*CLI, "timeline", "--run-dir", str(run_dir)])
            timeline = timeline_text(run_dir)
            self.assertIn("# Event Duration Summary", timeline)
            self.assertIn("## Application", timeline)
            self.assertIn("| 120.5 | dur | unspecified | reports/PROF_001/mindstudio_profiler_output/msprof_001.json |", timeline)
            self.assertIn("| MockMatMul |", timeline)
            self.assertIn("| 8 | dur | unspecified | reports/PROF_001/mindstudio_profiler_output/msprof_001.json |", timeline)
            self.assertIn("| aclrtSynchronizeStream |", timeline)
            self.assertIn("## Simulator", timeline)
            self.assertIn("| 70 | dur | unspecified | reports/OPPROF_001/trace.json |", timeline)

    def test_timeline_real_cann_top_level_array(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_run(Path(tmp))
            run([*CLI, "timeline", "--run-dir", str(run_dir)])
            timeline = timeline_text(run_dir)
            self.assertIn("# Event Duration Summary", timeline)
            self.assertIn("## Application", timeline)
            self.assertIn("| 42399.1 | dur | unspecified | reports/PROF_001/mindstudio_profiler_output/msprof_001.json |", timeline)
            self.assertIn("| sanitized_kernel | 1000000.000 | 1000 | 1716 | X |", timeline)
            self.assertIn("| 42001.4 | dur | unspecified | reports/PROF_001/mindstudio_profiler_output/msprof_001.json |", timeline)
            self.assertIn("| Runtime@DeviceSynchronize | 1000100.000 | 1001 | 2000 | X |", timeline)
            self.assertIn("| Computing | 1000000.000 | 1002 | 2 | X |", timeline)

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

    def test_simulator_hotspots_preserves_code_without_source_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_line_only_simulator_code_run(Path(tmp))
            run([*CLI, "sim-hotspots", "--run-dir", str(run_dir)])
            text = (run_dir / "analysis" / "simulator_hotspots.txt").read_text()
            model = json.loads((run_dir / "analysis" / "simulator_hotspots.json").read_text())

            self.assertIn("running_time(us): 7.5 us (total)", text)
            self.assertIsNone(model["source_lines"][0]["line"])
            self.assertEqual(model["source_lines"][0]["code"], "42")
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            signals = dimensions["source_pipeline_context"]["signals"]
            self.assertEqual(
                signals[0]["signal"],
                "42",
            )
            self.assertIn(
                "42",
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

        from ascend_msprof_skill.simulator_types import SourceSnippetLine
        tags, basis = classify_source_context(tuple(SourceSnippetLine(**row, hotspot=False) for row in snippet))

        self.assertIn("vector_compute", tags)
        self.assertEqual(basis["vector_compute"], ("AscendC::Sub",))
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
            self.assertIn("No source-line rows with confirmed simulator fields found.", text)
            self.assertEqual(model["simulator_hotspot_model_schema_version"], "2.0")
            self.assertEqual(model["source_lines"], [])
            self.assertTrue(model["instructions"])
            self.assertTrue(model["pipeline_events"])
            self.assertTrue(model["flow_categories"])
            self.assertIn("display_time_unit", model["inputs"][2])
            self.assertIn("- MOV_OUT_TO_UB;", text)
            self.assertIn("running_time(us): 2.99 us (total)", text)
            self.assertIn("- MOV_UB_TO_OUT;", text)
            self.assertIn("running_time(us): 2.9 us (total)", text)
            self.assertIn("## Trace Pipeline Context", text)
            self.assertIn("- displayTimeUnit: ns", text)
            self.assertIn("| 0.209 | total | 1/1 | pid=core3.veccore0; tid=MTE3 |", text)
            self.assertIn("| 0.154 | total | 1/1 | pid=core3.veccore0; tid=MTE2 |", text)
            self.assertIn("| 0.013 | total | 1/1 | pid=core3.veccore0; tid=VECTOR |", text)
            self.assertIn("## Trace Flow Categories", text)
            self.assertIn("MTE2ToVECTOR: 2 events", text)
            self.assertIn("VECTORToMTE3: 2 events", text)
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
            self.assertIn('SET_FLAG: 2 trace events', text)
            self.assertIn('WAIT_FLAG: 2 trace events', text)
            self.assertEqual([(row['instruction'], row['trace_events']) for row in model['sync_events']],
                             [('SET_FLAG', 2), ('WAIT_FLAG', 2)])
            self.assertTrue(all(row['artifact'] == trace_source for row in model['sync_events']))
            for instruction, cycles, duration in [('SET_FLAG', 831, 0.45), ('WAIT_FLAG', 837, 0.48)]:
                rows = [row for row in model['instructions'] if row['instr'] == instruction]
                self.assertEqual({row['artifact'] for row in rows}, {core0_source, core1_source})
                values = lambda field: [metric['total'] for row in rows for metric in row['metrics'] if metric['field'] == field]
                self.assertEqual(sum(values('call_count')), 3)
                self.assertEqual(sum(values('cycles')), cycles)
                self.assertAlmostEqual(sum(values('running_time(us)')), duration)
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
                "No SET_FLAG/WAIT_FLAG B/E synchronization events found in selected simulator traces.",
                text,
            )
            self.assertIn("throughput(MB/s)", text)
            self.assertIn(source, text)
            self.assertIn(f"| GM_TO_L1 | 0 | 0 | 2 | `{source}`;", text)
            self.assertIn(f"| GM_TO_TOTAL | 11718.8 | 7812.5 | 2 | `{source}`;", text)
            self.assertIn(f"| GM_TO_UB | 244.141 | 122.07 | 2 | `{source}`;", text)
            self.assertIn(f"| L1_TO_GM | 0 | 0 | 2 | `{source}`;", text)
            self.assertIn(f"| TOTAL_TO_GM | 7812.5 | 5859.38 | 2 | `{source}`;", text)
            self.assertIn(f"| UB_TO_GM | 7812.5 | 5859.38 | 2 | `{source}`;", text)
            self.assertNotIn("NOT_A_MTE_CHANNEL", text)
            self.assertEqual(
                sorted(row["channel"] for row in model["mte_throughput"]),
                ["GM_TO_L1", "GM_TO_TOTAL", "GM_TO_UB", "L1_TO_GM", "TOTAL_TO_GM", "UB_TO_GM"],
            )
            self.assertNotIn("NOT_A_MTE_CHANNEL", json.dumps(model["mte_throughput"]))
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
