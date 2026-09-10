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

    def test_compare_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_a = fresh_run(root / "a", "run_a")
            run_b = fresh_run(root / "b", "run_b")
            run([*CLI, "analyze", "--run-dir", str(run_a)])
            run([*CLI, "analyze", "--run-dir", str(run_b)])
            run([
                *CLI, "compare",
                "--run-dir-a",
                str(run_a),
                "--run-dir-b",
                str(run_b),
            ])
            json_outputs = list((run_b / "analysis").glob("compare_*.json"))
            md_outputs = list((run_b / "analysis").glob("compare_*.md"))
            self.assertTrue(json_outputs)
            self.assertTrue(md_outputs)
            comparison = json.loads(json_outputs[0].read_text(encoding="utf-8"))
            report = md_outputs[0].read_text(encoding="utf-8")

            self.assertEqual(comparison["comparison_schema_version"], "1.5")
            self.assertIn("runs", comparison)
            self.assertIn("compatibility", comparison)
            self.assertIn("benchmark", comparison)
            self.assertIn("headlines", comparison)
            self.assertIn("evidence", comparison)
            self.assertIn("design_feedback", comparison)
            self.assertIn("verdict", comparison)
            self.assertIn("warnings", comparison)
            self.assertEqual(comparison["design_feedback"]["contract_version"], "1.1")
            self.assertIn(comparison["design_feedback"]["status"], {"ready", "incomplete", "blocked"})
            self.assertTrue(comparison["design_feedback"]["questions"])
            self.assertEqual(comparison["runs"]["a"]["run_dir"], "<abs-path>/run_a")
            self.assertEqual(comparison["runs"]["b"]["run_dir"], "<abs-path>/run_b")
            self.assertIn("# Ascend Run Comparison", report)
            self.assertIn("## Verdict", report)
            self.assertIn("## Profiler Headlines", report)
            self.assertIn("## Design Feedback", report)
            timing = next(item for item in comparison["headlines"] if item["group"] == "op_summary")
            self.assertEqual(timing["status"], "not_comparable")
            summary_a = json.loads((run_a / "analysis" / "summary.json").read_text())
            self.assertEqual(timing["a"]["value"], summary_a["headlines"]["op_summary"]["value"])
            self.assertIsNone(timing["delta"])
            self.assertIsNone(timing["delta_pct"])
            self.assertIn("field missing", timing["comparison_reasons"])
            self.assertIn("metric_scope missing", timing["comparison_reasons"])
            self.assertIn("field missing", report)

    def test_summarize_candidate_writes_keep_and_preserves_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = fresh_run(root / "profile", "candidate")
            attach_tilelang_context(root, run_dir)
            set_evidence_readiness(run_dir)
            reports_before = reports_file_snapshot(run_dir)

            run([*CLI, "summarize-candidate", "--run-dir", str(run_dir)])
            candidate = json.loads((run_dir / "analysis" / "candidate_summary.json").read_text(encoding="utf-8"))
            markdown = (run_dir / "analysis" / "candidate_summary.md").read_text(encoding="utf-8")

            self.assertEqual(candidate["candidate_summary_schema_version"], "1.2")
            self.assertEqual(
                candidate["source_artifacts"]["summary"]["artifact"],
                "analysis/summary.json",
            )
            self.assertEqual(
                candidate["source_artifacts"]["summary"]["sha256"],
                hashlib.sha256(
                    (run_dir / "analysis" / "summary.json").read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(candidate["verdict"]["decision"], "keep")
            self.assertEqual(candidate["run"]["workload"]["id"], "tilelang-ascend/kernel/v1/4096x2048-f16-cases2")
            self.assertEqual(candidate["run"]["runtime"]["mean_ms"], 1.25)
            self.assertTrue(candidate["run"]["profiler_evidence"]["evidence_present"])
            self.assertEqual(candidate["run"]["profiler_evidence"]["evidence_readiness"]["level"], "directional")
            self.assertIn("design_feedback", candidate)
            self.assertEqual(candidate["design_feedback"]["contract_version"], "1.1")
            self.assertIn(candidate["design_feedback"]["status"], {"ready", "incomplete", "blocked"})
            self.assertTrue(candidate["design_feedback"]["questions"])
            self.assertTrue(any(item["source"] == "optimization_directions" for item in candidate["inspection_targets"]))
            self.assertTrue(any(item["source"] == "simulator_hotspots" for item in candidate["inspection_targets"]))
            self.assertIn("# TileLang Candidate Summary", markdown)
            self.assertIn("- Evidence readiness: `directional`", markdown)
            self.assertIn("## Design Feedback", markdown)
            self.assertEqual(reports_before, reports_file_snapshot(run_dir))

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

    def test_summarize_candidate_uses_evidence_readiness_gate(self):
        cases = [
            ("missing_readiness", None, [], "evidence readiness is missing"),
            ("insufficient", "insufficient", [], "evidence readiness level insufficient is below directional"),
            ("triage_only", "triage_only", [], "evidence readiness level triage_only is below directional"),
            (
                "readiness_followup",
                "directional",
                [{"id": "collect_default_metric_followup", "reason": "needs Default"}],
                "pending collection actions: collect_default_metric_followup",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, level, followups, reason in cases:
                with self.subTest(name=name):
                    run_dir = fresh_run(root / name, name)
                    attach_tilelang_context(root, run_dir)
                    if level is not None:
                        set_evidence_readiness(run_dir, level=level, followups=followups)
                    if name == "readiness_followup":
                        summary_path = run_dir / "analysis" / "summary.json"
                        summary = json.loads(summary_path.read_text(encoding="utf-8"))
                        summary["next_collection_actions"] = [
                            {"id": "collect_default_metric_followup", "reason": "same action from analyzer"}
                        ]
                        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

                    run([*CLI, "summarize-candidate", "--run-dir", str(run_dir)])
                    candidate = json.loads((run_dir / "analysis" / "candidate_summary.json").read_text(encoding="utf-8"))
                    markdown = (run_dir / "analysis" / "candidate_summary.md").read_text(encoding="utf-8")

                    self.assertEqual(candidate["verdict"]["decision"], "inconclusive")
                    self.assertIn(reason, " ".join(candidate["verdict"]["reasons"]))
                    if name == "readiness_followup":
                        self.assertEqual(len(candidate["run"]["profiler_evidence"]["pending_collection_actions"]), 1)
                        self.assertEqual(
                            " ".join(candidate["verdict"]["reasons"]).count("collect_default_metric_followup"),
                            1,
                        )
                        self.assertIn("- Pending collection actions: 1", markdown)
                        self.assertNotIn("Readiness follow-ups", markdown)

    def test_summarize_candidate_rejects_failed_benchmark_context(self):
        cases = [
            ("compiled_false", {"compiled": False}, "compiled=false"),
            ("correctness_false", {"passed": False}, "correctness failed"),
            ("benchmark_error", {"error": "benchmark failed"}, "benchmark error present"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, kwargs, reason in cases:
                with self.subTest(name=name):
                    run_dir = fresh_run(root / name, name)
                    attach_tilelang_context(root, run_dir, **kwargs)
                    run([*CLI, "summarize-candidate", "--run-dir", str(run_dir)])
                    candidate = json.loads((run_dir / "analysis" / "candidate_summary.json").read_text())

                    self.assertEqual(candidate["verdict"]["decision"], "reject")
                    self.assertIn(reason, " ".join(candidate["verdict"]["reasons"]))

    def test_summarize_candidate_marks_missing_inputs_inconclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = [
                "missing_context",
                "missing_runtime",
                "nonfinite_runtime",
                "missing_summary",
                "missing_profiler_evidence",
            ]
            for name in cases:
                with self.subTest(name=name):
                    run_dir = fresh_run(root / name, name)
                    if name != "missing_context":
                        attach_tilelang_context(root, run_dir)
                    if name in {"missing_runtime", "nonfinite_runtime"}:
                        context_path = run_dir / "analysis" / "tilelang_context.json"
                        context = json.loads(context_path.read_text())
                        if name == "missing_runtime":
                            context["benchmark"]["candidate"]["runtime"] = None
                            context["benchmark"]["candidate"]["runtime_stats"].pop("mean_ms", None)
                        else:
                            context["benchmark"]["candidate"]["runtime"] = float("nan")
                            context["benchmark"]["candidate"]["runtime_stats"]["mean_ms"] = float("inf")
                        context_path.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n")
                    if name == "missing_summary":
                        (run_dir / "analysis" / "summary.json").unlink()
                    if name == "missing_profiler_evidence":
                        (run_dir / "analysis" / "raw_artifact_index.json").unlink()

                    run([*CLI, "summarize-candidate", "--run-dir", str(run_dir)])
                    candidate = json.loads((run_dir / "analysis" / "candidate_summary.json").read_text())

                    self.assertEqual(candidate["verdict"]["decision"], "inconclusive")
                    output_text = (run_dir / "analysis" / "candidate_summary.json").read_text()
                    self.assertNotIn("NaN", output_text)
                    self.assertNotIn("Infinity", output_text)

    def test_candidate_feedback_rejects_negative_speedup_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = fresh_run(root / "a", "baseline")
            candidate_run = fresh_run(root / "b", "candidate")
            attach_tilelang_context(root, baseline, mean_ms=1.25)
            attach_tilelang_context(root, candidate_run, mean_ms=1.0)
            make_comparison_verdict_compatible(baseline, candidate_run)

            compare_result = subprocess.run(
                [
                    *CLI, "compare",
                    "--run-dir-a",
                    str(baseline),
                    "--run-dir-b",
                    str(candidate_run),
                    "--min-speedup-pct",
                    "-1",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                env=test_env(),
            )
            summarize_result = subprocess.run(
                [
                    *CLI, "summarize-candidate",
                    "--run-dir",
                    str(candidate_run),
                    "--baseline-run-dir",
                    str(baseline),
                    "--min-speedup-pct",
                    "-1",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                env=test_env(),
            )

            self.assertNotEqual(compare_result.returncode, 0)
            self.assertNotEqual(summarize_result.returncode, 0)
            self.assertIn("--min-speedup-pct must be a finite non-negative number", compare_result.stderr)
            self.assertIn("--min-speedup-pct must be a finite non-negative number", summarize_result.stderr)

    def test_compare_runs_verdict_promotes_and_records_lineage_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = fresh_run(root / "a", "baseline")
            candidate_run = fresh_run(root / "b", "candidate")
            attach_tilelang_context(root, baseline, mean_ms=1.25)
            attach_tilelang_context(root, candidate_run, mean_ms=1.0, payload_tile_m=128, pipeline_depth=4)
            make_comparison_verdict_compatible(baseline, candidate_run)

            run([*CLI, "compare", "--run-dir-a", str(baseline), "--run-dir-b", str(candidate_run)])
            comparison = json.loads((candidate_run / "analysis" / "compare_baseline_vs_candidate.json").read_text())
            lineage = {item["id"]: item for item in comparison["verdict"]["compatibility"]["lineage"]}

            self.assertEqual(comparison["verdict"]["decision"], "promote")
            self.assertTrue(comparison["verdict"]["can_compare"])
            self.assertEqual(lineage["payload.sha256"]["status"], "mismatch")
            self.assertEqual(lineage["jit_config"]["status"], "mismatch")

    def test_compare_runs_verdict_uses_evidence_readiness_gate(self):
        full_families = [
            "app_timing",
            "operator_metadata",
            "pipe_utilization",
            "arithmetic_utilization",
            "memory_cache",
            "resource_conflict",
            "simulator_source_pipeline",
        ]
        cases = [
            ("missing_readiness", None, full_families, "evidence_readiness.level missing"),
            ("triage_only", "triage_only", full_families, "evidence_readiness.level insufficient"),
            (
                "family_mismatch",
                "directional",
                ["app_timing", "operator_metadata", "pipe_utilization"],
                "evidence_readiness.material_families mismatch",
            ),
            (
                "readiness_followup",
                "directional",
                full_families,
                "evidence_readiness.pending_followups pending",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, candidate_level, candidate_families, reason in cases:
                with self.subTest(name=name):
                    baseline = fresh_run(root / f"{name}_a", "baseline")
                    candidate_run = fresh_run(root / f"{name}_b", "candidate")
                    attach_tilelang_context(root, baseline, mean_ms=1.25)
                    attach_tilelang_context(root, candidate_run, mean_ms=1.0)
                    make_comparison_verdict_compatible(baseline, candidate_run)
                    summary_path = candidate_run / "analysis" / "summary.json"
                    summary = json.loads(summary_path.read_text(encoding="utf-8"))
                    if candidate_level is None:
                        summary.pop("evidence_readiness", None)
                    else:
                        summary["evidence_readiness"]["level"] = candidate_level
                        summary["evidence_readiness"]["available_evidence_families"] = candidate_families
                        if name == "readiness_followup":
                            summary["next_collection_actions"] = [
                                {"id": "collect_default_metric_followup", "reason": "same action from analyzer"}
                            ]
                            summary["evidence_readiness"]["recommended_followups"] = [
                                {"id": "collect_default_metric_followup", "reason": "needs Default"}
                            ]
                    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

                    run([*CLI, "compare", "--run-dir-a", str(baseline), "--run-dir-b", str(candidate_run)])
                    comparison = json.loads((candidate_run / "analysis" / "compare_baseline_vs_candidate.json").read_text())

                    self.assertEqual(comparison["verdict"]["decision"], "inconclusive")
                    self.assertFalse(comparison["verdict"]["can_compare"])
                    self.assertIn(reason, " ".join(comparison["verdict"]["reasons"]))
                    if name == "readiness_followup":
                        followups = {
                            item["id"]: item for item in comparison["verdict"]["compatibility"]["evidence_readiness"]
                        }["evidence_readiness.pending_followups"]
                        self.assertEqual(followups["b"], ["collect_default_metric_followup"])
                        report = (candidate_run / "analysis" / "compare_baseline_vs_candidate.json").with_suffix(".md").read_text(encoding="utf-8")
                        self.assertIn("- Pending collection actions: 1", report)
                        self.assertNotIn("Readiness follow-ups", report)

    def test_compare_runs_ignores_stdout_only_readiness_family_difference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = fresh_run(root / "a", "baseline")
            candidate_run = fresh_run(root / "b", "candidate")
            attach_tilelang_context(root, baseline, mean_ms=1.25)
            attach_tilelang_context(root, candidate_run, mean_ms=1.0)
            make_comparison_verdict_compatible(baseline, candidate_run)
            summary_path = candidate_run / "analysis" / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["evidence_readiness"]["available_evidence_families"] = [
                item
                for item in summary["evidence_readiness"]["available_evidence_families"]
                if item != "stdout_performance_summary"
            ]
            summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            run([*CLI, "compare", "--run-dir-a", str(baseline), "--run-dir-b", str(candidate_run)])
            comparison = json.loads((candidate_run / "analysis" / "compare_baseline_vs_candidate.json").read_text())
            readiness = {
                item["id"]: item for item in comparison["verdict"]["compatibility"]["evidence_readiness"]
            }

            self.assertEqual(comparison["verdict"]["decision"], "promote")
            self.assertEqual(readiness["evidence_readiness.material_families"]["status"], "match")

    def test_compare_runs_verdict_promotes_with_segment_source_metadata_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = fresh_run(root / "a", "baseline")
            candidate_run = fresh_run(root / "b", "candidate")
            attach_tilelang_context(root, baseline, mean_ms=1.25)
            attach_tilelang_context(root, candidate_run, mean_ms=1.0)
            make_comparison_verdict_compatible(baseline, candidate_run)
            for run_dir, source_artifact in [
                (baseline, "logs/command_msprof_op.txt"),
                (candidate_run, "logs/msprof_op.stdout"),
            ]:
                provenance_path = run_dir / "analysis" / "provenance.json"
                provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                provenance["profile_output_segments"] = {
                    "value": {"op": {"kind": "op", "mode": "operator"}},
                    "source": {"artifact": source_artifact, "field": "profile_output_segments"},
                }
                provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")

            run([*CLI, "compare", "--run-dir-a", str(baseline), "--run-dir-b", str(candidate_run)])
            comparison = json.loads((candidate_run / "analysis" / "compare_baseline_vs_candidate.json").read_text())
            profiler = {item["id"]: item for item in comparison["verdict"]["compatibility"]["profiler"]}

            self.assertEqual(comparison["verdict"]["decision"], "promote")
            self.assertEqual(profiler["profile_output_segments"]["status"], "match")

    def test_compare_runs_verdict_promotes_when_profile_command_missing_for_both_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = fresh_run(root / "a", "baseline")
            candidate_run = fresh_run(root / "b", "candidate")
            attach_tilelang_context(root, baseline, mean_ms=1.25)
            attach_tilelang_context(root, candidate_run, mean_ms=1.0)
            make_comparison_verdict_compatible(baseline, candidate_run)
            for run_dir in [baseline, candidate_run]:
                provenance_path = run_dir / "analysis" / "provenance.json"
                provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                provenance.pop("profile_command", None)
                provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")

            run([*CLI, "compare", "--run-dir-a", str(baseline), "--run-dir-b", str(candidate_run)])
            comparison = json.loads((candidate_run / "analysis" / "compare_baseline_vs_candidate.json").read_text())
            profiler = {item["id"]: item for item in comparison["verdict"]["compatibility"]["profiler"]}

            self.assertEqual(comparison["verdict"]["decision"], "promote")
            self.assertEqual(profiler["profile_command"]["status"], "match")

    def test_compare_runs_verdict_rejects_correctness_failure_and_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = [
                ("candidate_correctness_failed", {}, {"mean_ms": 1.0, "passed": False}),
                ("baseline_correctness_failed", {"passed": False}, {"mean_ms": 1.0}),
                ("runtime_regressed", {}, {"mean_ms": 1.5}),
            ]
            for name, baseline_kwargs, candidate_kwargs in cases:
                with self.subTest(name=name):
                    baseline = fresh_run(root / f"{name}_a", "baseline")
                    candidate_run = fresh_run(root / f"{name}_b", "candidate")
                    attach_tilelang_context(root, baseline, mean_ms=1.25, **baseline_kwargs)
                    attach_tilelang_context(root, candidate_run, **candidate_kwargs)
                    make_comparison_verdict_compatible(baseline, candidate_run)

                    run([*CLI, "compare", "--run-dir-a", str(baseline), "--run-dir-b", str(candidate_run)])
                    comparison = json.loads((candidate_run / "analysis" / "compare_baseline_vs_candidate.json").read_text())

                    self.assertEqual(comparison["verdict"]["decision"], "reject")

    def test_compare_runs_verdict_inconclusive_for_incompatibility_or_missing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = [
                ("workload_mismatch", {"workload_id": "different-workload"}, False),
                ("missing_evidence", {}, True),
                ("profile_command_mismatch", {}, False),
                ("profile_command_one_sided_missing", {}, False),
                ("nonfinite_runtime", {}, False),
            ]
            for name, candidate_kwargs, remove_raw_index in cases:
                with self.subTest(name=name):
                    baseline = fresh_run(root / f"{name}_a", "baseline")
                    candidate_run = fresh_run(root / f"{name}_b", "candidate")
                    attach_tilelang_context(root, baseline, mean_ms=1.25)
                    attach_tilelang_context(root, candidate_run, mean_ms=1.0, **candidate_kwargs)
                    make_comparison_verdict_compatible(baseline, candidate_run)
                    if name == "profile_command_mismatch":
                        provenance_path = candidate_run / "analysis" / "provenance.json"
                        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                        provenance["profile_command"]["value"] = "msprof op --application=<different-abs-path>"
                        provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
                    if name == "profile_command_one_sided_missing":
                        provenance_path = candidate_run / "analysis" / "provenance.json"
                        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                        provenance.pop("profile_command", None)
                        provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
                    if name == "nonfinite_runtime":
                        context_path = candidate_run / "analysis" / "tilelang_context.json"
                        context = json.loads(context_path.read_text(encoding="utf-8"))
                        context["benchmark"]["candidate"]["runtime"] = float("nan")
                        context["benchmark"]["candidate"]["runtime_stats"]["mean_ms"] = float("inf")
                        context_path.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n")
                    if remove_raw_index:
                        (candidate_run / "analysis" / "raw_artifact_index.json").unlink()

                    run([*CLI, "compare", "--run-dir-a", str(baseline), "--run-dir-b", str(candidate_run)])
                    comparison = json.loads((candidate_run / "analysis" / "compare_baseline_vs_candidate.json").read_text())

                    self.assertEqual(comparison["verdict"]["decision"], "inconclusive")
                    output_text = (candidate_run / "analysis" / "compare_baseline_vs_candidate.json").read_text()
                    self.assertNotIn("NaN", output_text)
                    self.assertNotIn("Infinity", output_text)

    def test_compare_runs_redirects_outputs_and_requires_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_a = fresh_run(root / "a", "run_a")
            run_b = fresh_run(root / "b", "run_b")
            out_dir = root / "comparison"
            run([*CLI, "analyze", "--run-dir", str(run_a)])
            run([*CLI, "analyze", "--run-dir", str(run_b)])

            run([
                *CLI, "compare",
                "--run-dir-a",
                str(run_a),
                "--run-dir-b",
                str(run_b),
                "--out-dir",
                str(out_dir),
            ])

            self.assertTrue((out_dir / "compare_run_a_vs_run_b.json").exists())
            self.assertTrue((out_dir / "compare_run_a_vs_run_b.md").exists())

            shutil.rmtree(run_a / "analysis")
            result = subprocess.run(
                [
                    *CLI, "compare",
                    "--run-dir-a",
                    str(run_a),
                    "--run-dir-b",
                    str(run_b),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=test_env(),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("run ascend-msprof analyze first", result.stderr)

    def test_compare_runs_records_segmented_headline_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_a = fresh_real_pipe_default_followup_run(root / "a", "baseline")
            run_b = fresh_real_pipe_default_followup_run(root / "b", "candidate")
            run([*CLI, "analyze", "--run-dir", str(run_a)])
            run([*CLI, "analyze", "--run-dir", str(run_b)])
            make_comparison_verdict_compatible(run_a, run_b)
            for run_dir in (run_a, run_b):
                (run_dir / "analysis/profile_context.json").write_text(json.dumps({
                    "benchmark": {"workload": {"id": "kernel", "shape": [128], "dtype": "float32", "case_count": 1}}
                }))
                path = run_dir / "analysis" / "summary.json"
                context = json.loads(path.read_text())
                context["target_identity"] = {
                    "status": "match",
                    "expected": {"names": ["sanitized_pipe_kernel"]},
                }
                path.write_text(json.dumps(context))

            summary_path = run_b / "analysis" / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["headlines"]["pipe_utilization"]["value"] = 90.0
            summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            run([*CLI, "compare", "--run-dir-a", str(run_a), "--run-dir-b", str(run_b)])
            comparison = json.loads((run_b / "analysis" / "compare_baseline_vs_candidate.json").read_text())
            pipe = next(item for item in comparison["headlines"] if item["group"] == "pipe_utilization")

            self.assertEqual(pipe["status"], "changed")
            self.assertEqual(pipe["a"]["value"], 82.0)
            self.assertEqual(pipe["b"]["value"], 90.0)
            self.assertEqual(pipe["delta"], 8.0)
            self.assertAlmostEqual(pipe["delta_pct"], 9.75609756097561)
            self.assertEqual(pipe["a"]["segment"], "followup:collect_default_metric_followup")
            self.assertEqual(pipe["b"]["metric_scope"], "Default")

    def test_compare_runs_records_nonfatal_compatibility_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_a = fresh_run(root / "a", "baseline")
            run_b = fresh_run(root / "b", "candidate")
            for run_dir, version in [(run_a, "8.3.0.2.220:8.3.RC2"), (run_b, "9.9")]:
                summary_path = run_dir / "analysis" / "summary.json"
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                summary["metric_scope"] = {
                    "value": "PipeUtilization",
                    "artifact": "logs/command_msprof_op.txt",
                    "field_ref": "--aic-metrics",
                }
                summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                provenance = {
                    "cann_version": {
                        "value": version,
                        "source": {"artifact": "logs/cann_version.cfg", "field": "toolkit_running_version"},
                    },
                    "hardware": {
                        "summary": {
                            "value": "1 x 910B2; health OK",
                            "source": {"artifact": "logs/npu_smi_info.stdout", "field": "NPU/Name/Health"},
                        }
                    },
                    "profile_command": {
                        "value": "msprof op --output=reports/op --application=<abs-path>",
                        "source": {"artifact": "logs/command_msprof_op.txt", "field": "command"},
                    },
                    "profile_output_segments": {
                        "op": {"output": {"value": "reports/op", "source": {"artifact": "logs/command_msprof_op.txt", "field": "--output"}}}
                    },
                }
                (run_dir / "analysis" / "provenance.json").write_text(
                    json.dumps(provenance, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

            run([*CLI, "compare", "--run-dir-a", str(run_a), "--run-dir-b", str(run_b)])
            comparison = json.loads((run_b / "analysis" / "compare_baseline_vs_candidate.json").read_text())
            cann = next(check for check in comparison["compatibility"]["checks"] if check["id"] == "cann_version")

            self.assertEqual(comparison["compatibility"]["status"], "warning")
            self.assertEqual(cann["status"], "mismatch")
            self.assertEqual(cann["a"]["value"], "8.3.0.2.220:8.3.RC2")
            self.assertEqual(cann["b"]["value"], "9.9")

    def test_compare_runs_includes_tilelang_context_without_advice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_a = fresh_run(root / "a", "baseline")
            run_b = fresh_run(root / "b", "candidate")
            (root / "input_a").mkdir()
            (root / "input_b").mkdir()
            payload_a, benchmark_a = write_tilelang_inputs(root / "input_a")
            payload_b, benchmark_b = write_tilelang_inputs(root / "input_b")
            benchmark_data = json.loads(benchmark_b.read_text(encoding="utf-8"))
            benchmark_data["runtime_stats"]["mean_ms"] = 1.5
            benchmark_data["correctness"]["passed"] = False
            benchmark_b.write_text(json.dumps(benchmark_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            run([
                *CLI, "collect-tilelang",
                "--run-dir",
                str(run_a),
                "--payload-src",
                str(payload_a),
                "--benchmark-json",
                str(benchmark_a),
            ])
            run([
                *CLI, "collect-tilelang",
                "--run-dir",
                str(run_b),
                "--payload-src",
                str(payload_b),
                "--benchmark-json",
                str(benchmark_b),
            ])
            run([*CLI, "compare", "--run-dir-a", str(run_a), "--run-dir-b", str(run_b)])

            comparison = json.loads((run_b / "analysis" / "compare_baseline_vs_candidate.json").read_text())
            report = (run_b / "analysis" / "compare_baseline_vs_candidate.md").read_text(encoding="utf-8")
            mean_ms = next(item for item in comparison["benchmark"]["runtime"] if item["id"] == "candidate.runtime_stats.mean_ms")
            passed = next(item for item in comparison["benchmark"]["correctness"] if item["id"] == "correctness.passed")

            self.assertEqual(mean_ms["a"], 1.25)
            self.assertEqual(mean_ms["b"], 1.5)
            self.assertEqual(mean_ms["status"], "mismatch")
            self.assertIs(passed["a"], True)
            self.assertIs(passed["b"], False)
            for forbidden in ["bottleneck", "diagnosis", "optimization", "advice"]:
                self.assertNotIn(forbidden, report.lower())

    def test_compare_runs_handles_boolean_tilelang_correctness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_a = fresh_run(root / "a", "baseline")
            run_b = fresh_run(root / "b", "candidate")
            (root / "input_a").mkdir()
            (root / "input_b").mkdir()
            payload_a, benchmark_a = write_tilelang_inputs(root / "input_a")
            payload_b, benchmark_b = write_tilelang_inputs(root / "input_b")
            for benchmark_path, passed in [(benchmark_a, True), (benchmark_b, False)]:
                benchmark_data = json.loads(benchmark_path.read_text(encoding="utf-8"))
                benchmark_data["correctness"] = passed
                benchmark_path.write_text(json.dumps(benchmark_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            run([
                *CLI, "collect-tilelang",
                "--run-dir",
                str(run_a),
                "--payload-src",
                str(payload_a),
                "--benchmark-json",
                str(benchmark_a),
            ])
            run([
                *CLI, "collect-tilelang",
                "--run-dir",
                str(run_b),
                "--payload-src",
                str(payload_b),
                "--benchmark-json",
                str(benchmark_b),
            ])
            run([*CLI, "compare", "--run-dir-a", str(run_a), "--run-dir-b", str(run_b)])

            comparison = json.loads((run_b / "analysis" / "compare_baseline_vs_candidate.json").read_text())
            passed = next(item for item in comparison["benchmark"]["correctness"] if item["id"] == "correctness.passed")

            self.assertIs(passed["a"], True)
            self.assertIs(passed["b"], False)
            self.assertEqual(passed["status"], "mismatch")

    def test_compare_runs_status_includes_payload_and_jit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_a = fresh_run(root / "a", "baseline")
            run_b = fresh_run(root / "b", "candidate")
            (root / "input_a").mkdir()
            (root / "input_b").mkdir()
            payload_a, benchmark_a = write_tilelang_inputs(root / "input_a")
            payload_b, benchmark_b = write_tilelang_inputs(root / "input_b")
            payload_b.write_text(
                "def kernel_payload():\n"
                "    return {'op': 'generic_tilelang_kernel', 'tile_m': 128, 'tile_n': 32}\n",
                encoding="utf-8",
            )
            benchmark_data = json.loads(benchmark_b.read_text(encoding="utf-8"))
            benchmark_data["metadata"]["jit_config"]["pipeline_depth"] = 4
            benchmark_b.write_text(json.dumps(benchmark_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            run([
                *CLI, "collect-tilelang",
                "--run-dir",
                str(run_a),
                "--payload-src",
                str(payload_a),
                "--benchmark-json",
                str(benchmark_a),
            ])
            run([
                *CLI, "collect-tilelang",
                "--run-dir",
                str(run_b),
                "--payload-src",
                str(payload_b),
                "--benchmark-json",
                str(benchmark_b),
            ])
            run([*CLI, "compare", "--run-dir-a", str(run_a), "--run-dir-b", str(run_b)])

            comparison = json.loads((run_b / "analysis" / "compare_baseline_vs_candidate.json").read_text())

            self.assertEqual(comparison["benchmark"]["status"], "warning")
            self.assertEqual(comparison["benchmark"]["payload"]["status"], "mismatch")
            self.assertEqual(comparison["benchmark"]["jit_config"]["status"], "mismatch")
            mean_ms = next(item for item in comparison["benchmark"]["runtime"] if item["id"] == "candidate.runtime_stats.mean_ms")
            self.assertEqual(mean_ms["status"], "match")
