"""Run Evidence tests."""

from tests.helpers_shared import *
from ascend_msprof_skill.run_assessment import assess_run  # noqa: F401,F403


class RunEvidenceTests(unittest.TestCase):
    def test_run_evidence_loads_fixture_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp) / "profile", "mock_run")
            evidence = RunEvidence.load(run_dir)
            readiness = evidence.evidence_readiness().model_dump(mode="json", exclude_unset=True)
            raw_summary = evidence.raw_artifact_summary()
            presence = evidence.artifact_presence()

            self.assertEqual(evidence.target_name(), "MockMatMul")
            self.assertIsNone(evidence.metric_scope())
            warnings = "\n".join(evidence.warnings())
            self.assertIn("missing analysis/provenance.json", warnings)
            self.assertIn("missing analysis/tilelang_context.json", warnings)
            self.assertIn("missing analysis/profile_context.json", warnings)
            self.assertEqual(presence["summary"], "analysis/summary.json")
            self.assertEqual(presence["raw_artifact_index"], "analysis/raw_artifact_index.json")
            self.assertIsNone(presence["provenance"])
            self.assertEqual(readiness["level"], "available")
            self.assertGreater(raw_summary.artifact_count, 0)
            self.assertEqual(raw_summary.parsed_count, raw_summary.artifact_count)
            self.assertGreater(raw_summary.group_counts["op_summary"], 0)

            headlines = {fact.group: fact for fact in evidence.headline_records()}
            self.assertEqual(headlines["op_summary"].signal, "MockMatMul / Task Duration(us)")
            self.assertIn("field=Task Duration(us); statistic=duration; unit=us", headlines["op_summary"].field_ref)
            self.assertIn("field=Value; statistic=bandwidth; unit=GB/s; metric=GM Read Bandwidth(GB/s)", headlines["memory"].field_ref)
            self.assertEqual(headlines["memory"].raw_value_field_ref, headlines["memory"].field_ref)
            self.assertEqual(dict(evidence.launch_metadata().fields)["BlockDim"], 8)
            diagnosis = evidence.diagnosis_headlines()
            self.assertEqual([label for label, _fact in diagnosis], [
                "Operator duration observations",
                "Task duration observations",
                "Host/runtime API statistics",
            ])
            self.assertEqual(evidence.section_headlines(["pipe_utilization"])[0].artifact, "reports/OPPROF_001/PipeUtilization.csv")
            self.assertEqual(evidence.correlation_headlines([("App top operator", "op_summary")])[0][1].group, "op_summary")
            self.assertEqual(evidence.correlation_headlines([("missing", "l2_cache")]), [])

            current_run = copy_fixture(
                ROOT / "tests" / "fixtures" / "tilelang_design_feedback" / "pipe_arithmetic" / "positive",
                Path(tmp) / "profile",
                "pipe_arithmetic_positive",
            )
            current_evidence = RunEvidence.load(current_run)
            current_readiness = current_evidence.evidence_readiness()
            self.assertEqual(current_readiness.level, "available")
            self.assertGreater(len(current_readiness.available_evidence_families), 0)
            self.assertEqual(current_evidence.pending_collection_actions(), ())
            self.assertEqual(
                current_evidence.raw_artifact_index_view().artifact_count,
                current_evidence.raw_artifact_summary().artifact_count,
            )
            self.assertGreater(current_evidence.parsed_raw_artifact_counts()[0], 0)
            self.assertTrue(current_evidence.feedback_facts().profiler_evidence_present())
            self.assertIn("pipe_utilization", current_evidence.headline_group_names())
            self.assertFalse(current_evidence.comparison_headline_record("pipe_utilization").present)
            pipe_records = current_evidence.operator_headline_records("pipe_utilization")
            self.assertEqual({fact.segment for fact in pipe_records}, {"op", "followup:collect_default_metric_followup"})
            self.assertTrue(all(fact.value is not None for fact in pipe_records))

            launch_run = fresh_real_app_op_stdout_run(Path(tmp) / "profile", "real_app_op_stdout_minimal")
            run([*CLI, "analyze", "--run-dir", str(launch_run)])
            launch_metadata = RunEvidence.load(launch_run).launch_metadata()
            self.assertIsNotNone(launch_metadata)
            self.assertEqual(launch_metadata.artifact, "reports/op/OPPROF_20260602101111_OPHASH12/OpBasicInfo.csv")
            self.assertIn(("Block Dim", 1), launch_metadata.fields)
            self.assertIn(("Mix Block Dim", 2), launch_metadata.fields)

    def test_run_evidence_missing_and_invalid_optional_artifacts_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp) / "profile", "mock_run")
            (run_dir / "analysis" / "raw_artifact_index.json").unlink()
            (run_dir / "analysis" / "provenance.json").write_text("{", encoding="utf-8")
            (run_dir / "analysis" / "tilelang_context.json").write_text("[]", encoding="utf-8")

            evidence = RunEvidence.load(run_dir)

            self.assertEqual(evidence.raw_artifacts(), [])
            self.assertFalse(evidence.raw_artifact_summary().present)
            self.assertEqual(evidence.provenance(), None)
            self.assertEqual(evidence.tilelang_context(), None)
            self.assertEqual(evidence.profile_context(), None)
            warnings = "\n".join(evidence.warnings())
            self.assertIn("missing analysis/raw_artifact_index.json", warnings)
            self.assertIn("invalid analysis/provenance.json", warnings)
            self.assertIn("invalid analysis/tilelang_context.json: expected a JSON object", warnings)
            self.assertIn("missing analysis/profile_context.json", warnings)
            self.assertEqual(evidence.target_name(), "MockMatMul")

    def test_run_evidence_requires_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp) / "profile", "mock_run")
            (run_dir / "analysis" / "summary.json").unlink()

            with self.assertRaisesRegex(RunEvidenceError, "missing .*analysis/summary.json"):
                RunEvidence.load(run_dir)

    def test_run_evidence_handles_unknown_raw_artifact_shapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "custom_run"
            (run_dir / "analysis").mkdir(parents=True)
            (run_dir / "analysis/summary.json").write_text(json.dumps({"analysis_schema_version": "5.1"}))
            (run_dir / "analysis" / "raw_artifact_index.json").write_text(
                json.dumps(
                    {
                        "raw_artifact_index_schema_version": "test",
                        "artifacts": [
                            "not-an-object",
                            {"artifact": "reports/custom.bin", "warnings": "not-a-list"},
                            {"group": "custom_group", "status": "preserved"},
                        ],
                        "warnings": ["top-level warning"],
                    }
                ),
                encoding="utf-8",
            )

            raw_before = (run_dir / "analysis/raw_artifact_index.json").read_bytes()
            with self.assertRaisesRegex(RunEvidenceError, "invalid analysis/raw_artifact_index.json"):
                RunEvidence.load(run_dir)
            evidence = RunEvidence.load_assessment(run_dir)
            self.assertFalse(evidence.summary_present())
            self.assertFalse(evidence.raw_artifact_summary().present)
            self.assertIn("invalid analysis/raw_artifact_index.json", "\n".join(evidence.warnings()))
            self.assertEqual((run_dir / "analysis/raw_artifact_index.json").read_bytes(), raw_before)

    def test_run_evidence_loads_candidate_summary_when_summary_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp) / "profile", "missing_summary")
            (run_dir / "analysis" / "summary.json").unlink()

            evidence = RunEvidence.load_assessment(run_dir)
            presence = evidence.artifact_presence()
            profiler = assess_run(evidence).mechanism_assessment.evidence["candidate"]

            self.assertFalse(evidence.summary_present())
            self.assertIsNone(presence["summary"])
            self.assertEqual(presence["raw_artifact_index"], "analysis/raw_artifact_index.json")
            self.assertIn("missing analysis/summary.json", evidence.warnings())
            self.assertFalse(evidence.summary_present())
            self.assertTrue(profiler.raw_artifact_index.present)
            self.assertFalse(profiler.evidence_present)
            self.assertGreater(profiler.parsed_artifact_count, 0)

    def test_run_evidence_candidate_context_facts_normalize_tilelang_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = fresh_run(root / "profile", "candidate_context")
            attach_tilelang_context(root, run_dir)

            facts = RunEvidence.load_assessment(run_dir).candidate_context()
            self.assertEqual(facts.workload["id"], "tilelang-ascend/kernel/v1/4096x2048-f16-cases2")
            self.assertTrue(facts.payload.present)
            self.assertEqual(facts.runtime.mean_ms, 1.25)
            self.assertIs(facts.correctness.compiled, True)
            self.assertIs(facts.correctness.passed, True)
            self.assertEqual(facts.correctness.error, None)
            self.assertEqual(facts.correctness.source, "analysis/tilelang_context.json")
            self.assertEqual(facts.runtime.source, "analysis/tilelang_context.json")

            context_path = run_dir / "analysis" / "tilelang_context.json"
            context = json.loads(context_path.read_text(encoding="utf-8"))
            context["benchmark"]["candidate"].pop("runtime_stats")
            context["benchmark"]["candidate"]["runtime"] = "2.5"
            context["benchmark"]["correctness"]["raw"] = {"passed": False}
            context_path.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            legacy_facts = RunEvidence.load_assessment(run_dir).candidate_context()
            self.assertEqual(legacy_facts.runtime.mean_ms, 2.5)
            self.assertIs(legacy_facts.correctness.passed, False)

            context["benchmark"]["candidate"]["runtime"] = float("nan")
            context["benchmark"]["candidate"]["runtime_stats"] = {"mean_ms": float("inf")}
            context_path.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            nonfinite_facts = RunEvidence.load_assessment(run_dir).candidate_context()
            self.assertIsNone(nonfinite_facts.runtime.mean_ms)

    def test_run_evidence_candidate_context_projects_profile_verify_context(self):
        summary = {
            "analysis_schema_version": "5.1",
            "evidence_readiness": {
                "level": "available",
                "available_evidence_families": ["app_timing", "pipe_utilization"],
                "recommended_followups": [],
            },
            "next_collection_actions": [],
        }
        profile_context = {
            "verify_context": {
                "raw": {
                    "workload": {
                        "task_name": "regularized_right_inverse",
                        "shape": {"batch": 17, "m": 64, "n": 256},
                        "dtype": "float32",
                    },
                    "correctness": {
                        "correctness_ok": True,
                        "receipt": {"case_count": 3},
                    },
                    "official_timing": {
                        "authority": "executor_natural_launch",
                        "aggregation": "median",
                        "latency_source": "executor_latency_ms",
                        "latency_ms": 0.701959991,
                        "samples_ms": [0.7001, 0.7032, 0.701959991, 0.6998, 0.7040],
                    },
                }
            }
        }
        raw_index = {
            "raw_artifact_index_schema_version": "1.1",
            "warnings": [],
            "artifacts": [
                {
                    "artifact": "reports/op/OPPROF_001/OpBasicInfo.csv",
                    "group": "op_basic_info",
                    "status": "parsed",
                    "segment": "op",
                    "parser": "csv",
                    "metric_scope": None,
                    "columns": ["Op Name"],
                    "row_count": 1,
                    "sample_rows": [{"Op Name": "main_kernel"}],
                    "warnings": [],
                }
            ],
        }

        evidence = RunEvidence.from_loaded(
            Path("profile/profile_context_only"),
            None,
            raw_artifact_index=raw_index,
            profile_context=profile_context,
        )
        context = evidence.candidate_context()
        performance = assess_run(evidence).model_dump(mode="json")["performance_assessment"]

        self.assertEqual(context.workload["id"], "regularized_right_inverse")
        self.assertEqual(context.workload["shape"], {"batch": 17, "m": 64, "n": 256})
        self.assertEqual(context.workload["dtype"], "float32")
        self.assertEqual(context.workload["case_count"], 3)
        self.assertIs(context.correctness.passed, True)
        self.assertEqual(context.runtime.value_ms, 0.701959991)
        self.assertEqual(context.runtime.statistic, "median")
        self.assertIsNone(context.runtime.mean_ms)
        self.assertEqual(context.runtime.authority, "executor_natural_launch")
        self.assertEqual(context.runtime.latency_source, "executor_latency_ms")
        expected_refs = {
            "runtime.value_ms": "verify_context.raw.official_timing.latency_ms",
            "runtime.statistic": "verify_context.raw.official_timing.aggregation",
            "runtime.samples_ms": "verify_context.raw.official_timing.samples_ms",
            "runtime.authority": "verify_context.raw.official_timing.authority",
            "runtime.latency_source": "verify_context.raw.official_timing.latency_source",
        }
        self.assertEqual(
            {key: context.context_sources[key].field_ref for key in expected_refs},
            expected_refs,
        )
        for key in expected_refs:
            self.assertEqual(context.context_sources[key].artifact, "analysis/profile_context.json")
            self.assertEqual(
                context.context_sources[key].evidence_role,
                "caller_owned_acceptance_context_not_profiler_evidence",
            )
        self.assertEqual(performance["eligibility"]["status"], "incomplete")

    def test_run_evidence_candidate_context_preserves_benchmark_runtime_field_sources(self):
        profile_context = {
            "benchmark": {
                "candidate": {
                    "runtime_stats": {
                        "value_ms": 1.75,
                        "aggregation": "median",
                        "samples_ms": [1.7, 1.75, 1.8],
                        "authority": "executor_natural_launch",
                        "latency_source": "executor_latency_ms",
                    }
                }
            }
        }

        context = RunEvidence.from_loaded(
            Path("profile/benchmark_runtime_sources"),
            None,
            profile_context=profile_context,
        ).candidate_context()

        self.assertEqual(context.runtime.value_ms, 1.75)
        self.assertEqual(context.runtime.statistic, "median")
        self.assertEqual(context.runtime.samples_ms, (1.7, 1.75, 1.8))
        self.assertEqual(context.runtime.authority, "executor_natural_launch")
        self.assertEqual(context.runtime.latency_source, "executor_latency_ms")
        expected_refs = {
            "runtime.value_ms": "benchmark.candidate.runtime_stats.value_ms",
            "runtime.statistic": "benchmark.candidate.runtime_stats.aggregation",
            "runtime.samples_ms": "benchmark.candidate.runtime_stats.samples_ms",
            "runtime.authority": "benchmark.candidate.runtime_stats.authority",
            "runtime.latency_source": "benchmark.candidate.runtime_stats.latency_source",
        }
        self.assertEqual(
            {key: context.context_sources[key].field_ref for key in expected_refs},
            expected_refs,
        )
        self.assertTrue(
            all(source.artifact == "analysis/profile_context.json" for source in context.context_sources.values())
        )
        self.assertTrue(
            all(source.evidence_role == "caller_context_not_profiler_evidence" for source in context.context_sources.values())
        )

    def test_run_evidence_candidate_context_preserves_mean_and_legacy_runtime_sources(self):
        mean_context = RunEvidence.from_loaded(
            Path("profile/mean_runtime_source"),
            None,
            profile_context={"benchmark": {"candidate": {"runtime_stats": {"mean_ms": 1.25}}}},
        ).candidate_context()
        self.assertEqual(mean_context.runtime.value_ms, 1.25)
        self.assertEqual(mean_context.runtime.statistic, "mean")
        self.assertEqual(mean_context.runtime.mean_ms, 1.25)
        self.assertEqual(
            mean_context.context_sources["runtime.value_ms"].field_ref,
            "benchmark.candidate.runtime_stats.mean_ms",
        )
        self.assertEqual(
            mean_context.context_sources["runtime.statistic"].field_ref,
            "benchmark.candidate.runtime_stats.mean_ms",
        )

        legacy_context = RunEvidence.from_loaded(
            Path("profile/legacy_runtime_source"),
            None,
            profile_context={"benchmark": {"candidate": {"runtime": "2.5"}}},
        ).candidate_context()
        self.assertEqual(legacy_context.runtime.value_ms, 2.5)
        self.assertEqual(legacy_context.runtime.statistic, "legacy_runtime")
        self.assertEqual(legacy_context.runtime.mean_ms, 2.5)
        self.assertEqual(
            legacy_context.context_sources["runtime.value_ms"].field_ref,
            "benchmark.candidate.runtime",
        )
        self.assertEqual(
            legacy_context.context_sources["runtime.statistic"].field_ref,
            "benchmark.candidate.runtime",
        )

        median_context = RunEvidence.from_loaded(
            Path("profile/median_runtime_source"),
            None,
            profile_context={
                "benchmark": {
                    "candidate": {
                        "runtime_stats": {"value_ms": 2.0, "statistic": "median", "mean_ms": 1.5}
                    }
                }
            },
        ).candidate_context()
        self.assertEqual(median_context.runtime.statistic, "median")
        self.assertIsNone(median_context.runtime.mean_ms)
        self.assertEqual(
            median_context.context_sources["runtime.value_ms"].field_ref,
            "benchmark.candidate.runtime_stats.value_ms",
        )

    def test_run_evidence_candidate_context_records_workload_conflicts(self):
        tilelang_context = {
            "benchmark": {
                "workload": {"shape": [32, 64], "dtype": "float16"},
                "candidate": {"runtime_stats": {"mean_ms": 1.25}},
                "correctness": {"raw": {"passed": True}},
            }
        }
        profile_context = {
            "benchmark": {
                "workload": {"id": "profile-task", "shape": [17, 64], "dtype": "float32", "case_count": 5},
                "candidate": {"runtime_stats": {"value_ms": 2.0, "statistic": "median"}},
                "correctness": {"raw": {"passed": False}},
            }
        }

        context = RunEvidence.from_loaded(
            Path("profile/precedence"),
            None,
            tilelang_context=tilelang_context,
            profile_context=profile_context,
        ).candidate_context()

        self.assertEqual(context.workload, {"id": "profile-task", "case_count": 5})
        self.assertEqual([item["value"] for item in context.workload_evidence["shape"]], [[32, 64], [17, 64]])
        self.assertEqual(context.runtime.value_ms, 1.25)
        self.assertEqual(context.runtime.statistic, "mean")
        self.assertIs(context.correctness.passed, True)
        self.assertEqual(context.context_sources["workload.shape"].artifact, "analysis/tilelang_context.json")
        self.assertEqual(context.context_sources["workload.id"].artifact, "analysis/profile_context.json")
        self.assertEqual(context.context_sources["runtime.value_ms"].artifact, "analysis/tilelang_context.json")
        self.assertEqual(context.context_sources["runtime.statistic"].artifact, "analysis/tilelang_context.json")

    def test_run_evidence_report_tilelang_rows_cite_mixed_context_sources(self):
        evidence = RunEvidence.from_loaded(
            Path("profile/mixed_context_report"),
            None,
            tilelang_context={
                "benchmark": {
                    "workload": {"shape": [32, 64], "dtype": "float16"},
                    "candidate": {"runtime_stats": {"mean_ms": 1.25}},
                    "correctness": {"raw": {"passed": True}},
                }
            },
            profile_context={
                "benchmark": {
                    "workload": {"id": "profile-task", "case_count": 5},
                    "candidate": {"compiled": True},
                    "correctness": {"maxima": [{"field": "max_abs_error", "value": 0.001}]},
                    "jit_config": {"pipeline_depth": 2},
                }
            },
        )

        rows = {row.label: row for row in evidence.report_tilelang_context_rows()}
        report = generate_report.build_report_from_evidence(evidence)

        self.assertEqual(rows["Workload id"].artifact, "analysis/profile_context.json")
        self.assertEqual(rows["Workload id"].field_ref, "benchmark.workload.id")
        self.assertEqual(rows["Shape"].artifact, "analysis/tilelang_context.json")
        self.assertEqual(rows["Compiled"].artifact, "analysis/profile_context.json")
        self.assertEqual(rows["Correctness maxima"].artifact, "analysis/profile_context.json")
        self.assertEqual(rows["JIT config"].artifact, "analysis/profile_context.json")
        self.assertIn(
            "| Workload id | profile-task | `analysis/profile_context.json`; `benchmark.workload.id` |",
            report,
        )

    def test_run_evidence_exposes_context_and_simulator_inspection_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = fresh_run(root / "profile", "inspection_targets")
            attach_tilelang_context(root, run_dir)
            (run_dir / 'reports/OPPROF_001/core0_instr_exe.csv').write_text(
                'instr,pipe,call_count,cycles,running_time(us)\nVADD,VECTOR,1,2,3\n')
            (run_dir / 'analysis/profile_context.json').write_text(json.dumps({'expected_kernel_names': ['MockMatMul', 'MockMatMulTask']}))
            evidence_model.write_evidence_model(run_dir)


            evidence = RunEvidence.load_assessment(run_dir)
            context = evidence.candidate_context()
            targets = evidence.inspection_targets()
            self.assertEqual(context.workload['id'], 'tilelang-ascend/kernel/v1/4096x2048-f16-cases2')
            self.assertEqual(context.runtime.mean_ms, 1.25)
            self.assertTrue(evidence.feedback_facts().profiler_evidence_present())
            self.assertEqual(evidence.evidence_readiness().level, 'available')
            self.assertIn('simulator_hotspots', {target.source for target in targets})
            self.assertEqual(evidence.warnings(), [])


    def test_run_evidence_feedback_facts_expose_candidate_feedback_policy_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = fresh_run(root / "profile", "feedback_policy_inputs")
            attach_tilelang_context(root, run_dir)

            evidence = RunEvidence.load_assessment(run_dir)
            facts = evidence.feedback_facts()

            self.assertTrue(facts.tilelang_context_present)
            self.assertIs(facts.compiled_value(), True)
            self.assertIs(facts.correctness_passed(), True)
            self.assertIsNone(facts.benchmark_error())
            self.assertEqual(facts.runtime_mean_ms(), 1.25)
            self.assertEqual(facts.runtime_evidence_field_ref(), "benchmark.candidate.runtime_stats.mean_ms")
            self.assertEqual(facts.workload_value("id"), "tilelang-ascend/kernel/v1/4096x2048-f16-cases2")
            payload_path = root / f"inputs_{run_dir.parent.name}_{run_dir.name}" / "tilelang_kernel_payload.py"
            self.assertEqual(facts.payload_sha256(), hashlib.sha256(payload_path.read_bytes()).hexdigest())
            self.assertEqual(facts.jit_config(), {"num_warps": 4, "pipeline_depth": 3})
            self.assertFalse(facts.jit_debug_found())

            context_path = run_dir / "analysis" / "tilelang_context.json"
            context = json.loads(context_path.read_text(encoding="utf-8"))
            context["benchmark"]["candidate"].pop("runtime_stats")
            context["benchmark"]["candidate"]["runtime"] = "2.5"
            context["benchmark"]["candidate"]["compiled"] = False
            context["benchmark"]["candidate"]["error"] = "compile failed"
            context["benchmark"]["correctness"]["raw"] = {"passed": False}
            context["jit_debug"] = {"found": False, "artifacts": []}
            context_path.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            fallback_facts = RunEvidence.load_assessment(run_dir).feedback_facts()

            self.assertEqual(fallback_facts.runtime_mean_ms(), 2.5)
            self.assertEqual(fallback_facts.runtime_evidence_field_ref(), "benchmark.candidate.runtime")
            self.assertIs(fallback_facts.compiled_value(), False)
            self.assertIs(fallback_facts.correctness_passed(), False)
            self.assertEqual(fallback_facts.benchmark_error(), "compile failed")
            self.assertFalse(fallback_facts.jit_debug_found())


    def test_legacy_evidence_escape_hatch_use_is_audited(self):
        pattern = re.compile(
            r"context_value\(|tilelang_context\(|profile_context\(|provenance\(\)|"
            r"raw_artifact_index\(|get\(\"benchmark\""
        )
        allowed = {
            ("src/ascend_msprof_skill/caller_context.py", 'benchmark = _object(data.get("benchmark"), artifact, "benchmark", issues)'),
            (
                "src/ascend_msprof_skill/_evidence_artifacts.py",
                "def build_raw_artifact_index(",
            ),
            ("src/ascend_msprof_skill/evidence_model.py", "raw_artifact_index = build_raw_artifact_index("),
            ("src/ascend_msprof_skill/profile_harness.py", "def write_profile_context("),
            ("src/ascend_msprof_skill/profile_harness.py", "return ProfileHarnessArtifacts(run_dir).write_profile_context("),
            ("src/ascend_msprof_skill/profile_harness.py", "artifacts.write_profile_context("),
        }
        matches: set[tuple[str, str]] = set()
        for path in (ROOT / "src" / "ascend_msprof_skill").rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel == "src/ascend_msprof_skill/run_evidence.py":
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if pattern.search(stripped):
                    matches.add((rel, stripped))

        self.assertSetEqual(matches, allowed)

    def test_run_evidence_report_facts_preserve_context_citations_and_caveats(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "report_facts"
            (run_dir / "analysis").mkdir(parents=True)
            for name in ["summary.json", "raw_artifact_index.json", "simulator_hotspots.json", "simulator_hotspots.txt"]:
                (run_dir / "analysis" / name).write_text("{}\n", encoding="utf-8")
            (run_dir / "logs").mkdir()
            (run_dir / "logs" / "command_msprof_op.txt").write_text(
                "msprof op --aic-metrics=PipeUtilization\n", encoding="utf-8"
            )
            summary, _, _simulator = evidence_model.build_evidence_model(run_dir)
            evidence = RunEvidence.from_loaded(
                run_dir,
                summary,
                profile_context={
                    "warnings": ["profile context warning"],
                    "sources": {
                        "profile_harness_manifest": {
                            "artifact": "harness/profile_harness.json",
                            "sha256": "manifest-sha",
                        },
                        "application": {
                            "artifact": "harness/run.sh",
                            "sha256": "application-sha",
                        },
                        "verify_json": {"artifact": "context/verify.json"},
                    },
                    "profile_harness": {
                        "workload": {"id": "generic/profile-harness/v1"},
                        "jit_config": {"pipeline_depth": 2},
                    },
                    "benchmark": {
                        "workload": {
                            "id": "verify/generic",
                            "shape": [4, 8],
                            "dtype": "float16",
                            "case_count": 3,
                        },
                        "candidate": {
                            "compiled": True,
                            "runtime": 1.5,
                            "runtime_stats": {"mean_ms": 1.5},
                            "ref_runtime": 2.0,
                            "speedup": 1.333333,
                        },
                        "correctness": {
                            "maxima": [{"field": "max_abs_error", "value": 0.000244}],
                        },
                    },
                },
                tilelang_context={
                    "warnings": ["tile context warning"],
                    "sources": {
                        "payload": {
                            "artifact": "tilelang_kernel_payload.py",
                            "sha256": "payload-sha",
                        }
                    },
                    "benchmark": {
                        "workload": {
                            "id": "tilelang/kernel",
                            "shape": [16, 32],
                            "dtype": "float16",
                            "case_count": 2,
                        },
                        "jit_config": {"pipeline_depth": 3},
                        "candidate": {
                            "compiled": True,
                            "runtime": 2.5,
                            "runtime_stats": {"mean_ms": 2.5},
                            "ref_runtime": 5.0,
                            "speedup": 2.0,
                        },
                        "correctness": {
                            "raw": {"passed": True},
                            "maxima": [{"field": "max_abs_diff", "value": 0.125}],
                        },
                    },
                },
            )

            profile_rows = {row.label: row for row in evidence.report_profile_context_rows()}
            tilelang_rows = {row.label: row for row in evidence.report_tilelang_context_rows()}
            setup = evidence.report_setup_context()
            caveats = evidence.report_caveats([], op_metric_scope_value="PipeUtilization")
            report_facts = evidence.report_facts(
                generate_report.ANALYSIS_ARTIFACTS,
                generate_report.OPTIONAL_ANALYSIS_ARTIFACTS,
                generate_report.ANALYSIS_SECTIONS,
            )

            self.assertEqual(profile_rows["Verify JSON"].artifact, "analysis/profile_context.json")
            self.assertEqual(profile_rows["Verify JSON"].field_ref, "sources.verify_json.artifact")
            self.assertEqual(profile_rows["Correctness maxima"].value, "max_abs_error=0.000244")
            self.assertEqual(tilelang_rows["Payload source"].field_ref, "sources.payload.artifact")
            self.assertEqual(tilelang_rows["Correctness maxima"].value, "max_abs_diff=0.125")
            self.assertIn("profile harness manifest `harness/profile_harness.json`", setup.application_text)
            self.assertIn("source: `analysis/profile_context.json`", setup.workload_text)
            self.assertIn("Analyzer warning: missing op_basic_info: ['OpBasicInfo.csv']", caveats)
            self.assertIn("Analyzer warning: missing pipe_utilization: ['PipeUtilization.csv']", caveats)
            self.assertIn("Profile context warning: profile context warning", caveats)
            self.assertIn("TileLang context warning: tile context warning", caveats)
            self.assertNotIn("Analyzer warning: missing l2_cache: ['L2Cache.csv']", caveats)
            self.assertNotIn("Analyzer warning: missing memory: ['Memory.csv']", caveats)
            self.assertEqual(report_facts.setup_context, setup)
            self.assertIn("`analysis/raw_artifact_index.json`", report_facts.analysis_artifacts)
            self.assertIn("`analysis/simulator_hotspots.json`", report_facts.analysis_artifacts)
            self.assertIn("`analysis/simulator_hotspots.txt`", report_facts.analysis_artifacts)
            self.assertIn("`analysis/tilelang_context.json`", report_facts.analysis_artifacts)
            self.assertIn("`analysis/profile_context.json`", report_facts.analysis_artifacts)
            self.assertTrue(report_facts.simulator_hotspots.structured_model_present)
            self.assertTrue(report_facts.simulator_hotspots.markdown_summary_present)
            self.assertEqual(
                report_facts.caveats,
                tuple(
                    evidence.report_caveats(
                        generate_report.OPTIONAL_ANALYSIS_ARTIFACTS,
                        op_metric_scope_value="PipeUtilization",
                    )
                ),
            )

    def test_run_evidence_report_setup_metadata_preserves_setup_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "setup_metadata"
            logs = run_dir / "logs"
            logs.mkdir(parents=True)
            (logs / "command_msprof.txt").write_text(
                "msprof --output=<abs-path>/reports/app --application=<abs-path>/run.sh --aic-metrics=IgnoredApp\n",
                encoding="utf-8",
            )
            (logs / "command_msprof_op.txt").write_text(
                "msprof op --aic-metrics=Default\n", encoding="utf-8"
            )
            summary, _, _simulator = evidence_model.build_evidence_model(run_dir)
            (logs / "command_msprof_op.txt").write_text(
                "msprof op --output=<abs-path>/reports/op --application=<abs-path>/op.sh --aic-metrics=PipeUtilization\n",
                encoding="utf-8",
            )
            provenance = {
                "schema_version": 2,
                "cann_version": {
                    "status": "recorded",
                    "evidence": [{"value": "8.3.0.2.220:8.3.RC2", "source": {"artifact": "logs/cann_version.cfg", "field": "toolkit_running_version"}}],
                    "value": "8.3.0.2.220:8.3.RC2",
                    "source": {"artifact": "logs/cann_version.cfg", "field": "toolkit_running_version"},
                },
                "profile_date": {
                    "value": "2026-05-30 19:11:28",
                    "source": {"artifact": "logs/msprof_op.stdout", "field": "Started profiling"},
                },
                "hardware": {
                    "summary": {
                        "value": "1 x 910B2; health OK",
                        "source": {"artifact": "logs/npu_smi_info.stdout", "field": "NPU/Name/Health"},
                    }
                },
                "profile_command": {
                    "value": "msprof op --output=<abs-path>/reports/op",
                    "source": {"artifact": "logs/command_msprof_op.txt", "field": "command"},
                },
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
                ],
                "profile_output_segments": {
                    "app": {
                        "output": {
                            "value": "reports/app",
                            "source": {"artifact": "logs/command_msprof.txt", "field": "--output"},
                        },
                        "resolved_output": {
                            "value": "reports/app/PROF_<sanitized>",
                            "source": {"artifact": "logs/msprof_default.stdout", "field": "Profiling results saved in"},
                        },
                    },
                    "op": {
                        "output": {
                            "value": "reports/op",
                            "source": {"artifact": "logs/command_msprof_op.txt", "field": "--output"},
                        },
                    },
                    "followups": {
                        "collect_default_metric_followup": {
                            "resolved_output": {
                                "value": "reports/followups/collect_default_metric_followup/OPPROF_<sanitized>",
                                "source": {
                                    "artifact": "logs/msprof_followup_collect_default_metric_followup.stdout",
                                    "field": "Profiling results saved in",
                                },
                            },
                        }
                    },
                },
                "collection_plan": {
                    "preset_id": "triage",
                    "source": "profile_harness_preset",
                    "segments": [
                        {"segment_id": "app"},
                        {"segment_id": "op"},
                    ],
                },
            }
            facts = RunEvidence.from_loaded(run_dir, summary, provenance=provenance).report_setup_metadata()

            self.assertEqual(facts.hardware_text, "1 x 910B2; health OK (source: `logs/npu_smi_info.stdout`; `NPU/Name/Health`)")
            self.assertEqual(facts.cann_text, "8.3.0.2.220:8.3.RC2 (source: `logs/cann_version.cfg`; `toolkit_running_version`)")
            self.assertEqual(facts.profile_date_text, "2026-05-30 19:11:28 (source: `logs/msprof_op.stdout`; `Started profiling`)")
            self.assertIn("app: reports/app (source: `logs/command_msprof.txt`; `--output`)", facts.profile_output_line)
            self.assertIn(
                "resolved reports/app/PROF_<sanitized> (source: `logs/msprof_default.stdout`; `Profiling results saved in`)",
                facts.profile_output_line,
            )
            self.assertIn("op: reports/op (source: `logs/command_msprof_op.txt`; `--output`)", facts.profile_output_line)
            self.assertIn(
                "followups.collect_default_metric_followup: resolved "
                "reports/followups/collect_default_metric_followup/OPPROF_<sanitized> "
                "(source: `logs/msprof_followup_collect_default_metric_followup.stdout`; `Profiling results saved in`)",
                facts.profile_output_line,
            )
            self.assertEqual(
                facts.collection_plan_line,
                "- Collection plan: triage; segments: app, op; source: profile_harness_preset",
            )
            self.assertIsNotNone(facts.metric_scope)
            self.assertEqual(facts.metric_scope.value, "PipeUtilization")
            self.assertEqual(facts.metric_scope.artifact, "logs/command_msprof_op.txt")
            self.assertEqual(facts.metric_scope.field_ref, "--aic-metrics")

            no_segments = dict(provenance)
            no_segments.pop("profile_output_segments")
            facts = RunEvidence.from_loaded(run_dir, summary, provenance=no_segments).report_setup_metadata()
            self.assertIn("reports/app/PROF_<sanitized>", facts.profile_output_line)
            self.assertIn("reports/op/OPPROF_<sanitized>", facts.profile_output_line)

            legacy_only = dict(no_segments)
            legacy_only.pop("profile_outputs")
            facts = RunEvidence.from_loaded(run_dir, summary, provenance=legacy_only).report_setup_metadata()
            self.assertEqual(
                facts.profile_output_line,
                "- Profile output: reports/legacy (source: `logs/legacy.stdout`; `Profiling results saved in`)",
            )

            (logs / "command_msprof_op.txt").unlink()
            facts = RunEvidence.from_loaded(run_dir, summary, provenance=provenance).report_setup_metadata()
            self.assertEqual(facts.metric_scope.value, "Default")
            self.assertEqual(facts.metric_scope.artifact, "logs/command_msprof_op.txt")
            self.assertEqual(facts.metric_scope.field_ref, "--aic-metrics")

            missing = RunEvidence.from_loaded(run_dir, None, provenance=None).report_setup_metadata()
            self.assertEqual(missing.hardware_text, "Ascend 910B")
            self.assertEqual(missing.profile_command_text, "see reproduction section")
            self.assertEqual(missing.profile_output_line, "- Profile output: not recorded")
            self.assertIsNone(missing.collection_plan_line)
            self.assertIsNone(missing.metric_scope)

    def test_run_evidence_feedback_facts_preserve_raw_inventory_when_summary_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp) / "profile", "missing_summary_feedback")
            (run_dir / "analysis" / "summary.json").unlink()

            facts = RunEvidence.load_assessment(run_dir).feedback_facts()

            self.assertFalse(facts.summary_present)
            self.assertTrue(facts.raw_artifact_index_present)
            self.assertTrue(facts.raw_inventory_present())
            self.assertFalse(facts.profiler_evidence_present())
            self.assertEqual(facts.parsed_artifact_count(), len(raw_artifact_index(run_dir)["artifacts"]))

    def test_run_evidence_feedback_facts_expose_design_evidence_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = copy_fixture(
                ROOT / "tests" / "fixtures" / "tilelang_design_feedback" / "memory_cache" / "positive",
                Path(tmp) / "profile",
                "memory_cache_positive",
            )
            evidence = RunEvidence.load_assessment(run_dir)
            facts = evidence.feedback_facts()

            present, missing, allowed_keys = facts.parsed_required_artifacts(
                {"memory", "l2_cache"},
                ["Memory.csv", "MemoryL0.csv", "MemoryUB.csv", "L2Cache.csv"],
            )
            signals = facts.summary_signal_records({"memory", "l2_cache"}, allowed_artifact_keys=allowed_keys)

            self.assertEqual([], missing)
            self.assertEqual(
                {"L2Cache.csv", "Memory.csv", "MemoryL0.csv", "MemoryUB.csv"},
                {Path(str(item.artifact)).name for item in present},
            )
            self.assertTrue(any(item.columns for item in present))
            self.assertTrue(signals)
            self.assertTrue(all(isinstance(signal, object) and signal.field_ref for signal in signals))
            self.assertEqual("available", facts.readiness_level())
            self.assertEqual((), facts.combined_pending_collection_actions())


    def test_run_evidence_design_feedback_uses_timestamped_selected_followup_artifacts(self):
        from tests.helper_tests_multi_launch import declared_target, write_declared_target, write_app_launches, write_operator_launch
        segment = "followup:collect_default_metric_followup"
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            write_declared_target(run_dir, declared_target(("main_kernel", 1), selector="main_kernel*"))
            write_app_launches(run_dir, ["main_kernel"])
            write_operator_launch(run_dir, "main_kernel_mix_aic", 0, segment=segment,
                                  families=("memory", "l2_cache", "pipe_utilization", "arithmetic_utilization"))
            evidence_model.write_evidence_model(run_dir)
            evidence = RunEvidence.load_assessment(run_dir)
            feedback = assess_run(evidence).model_dump(mode="json")["mechanism_assessment"]
            memory = next(item for item in feedback["questions"] if item["id"] == "memory_cache")
            pipe = next(item for item in feedback["questions"] if item["id"] == "pipe_arithmetic")
            self.assertEqual(memory["missing_evidence"], [])
            self.assertEqual(pipe["missing_evidence"], [])
            for question in [memory, pipe]:
                self.assertTrue(question["available_evidence"])
                self.assertTrue(all(item["segment"] == segment for item in question["available_evidence"]))
                self.assertTrue(all(item["metric_scope"] == "Default" for item in question["available_evidence"]))
                self.assertTrue(all(item["target_scope"]["kind"] == "complete_program" for item in question["available_evidence"]))
                self.assertTrue(any(str(item["field_ref"]).startswith("artifacts[") for item in question["available_evidence"]))


    def test_generate_report_includes_app_op_correlation_without_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_app_op_stdout_run(Path(tmp) / "profile")
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            diagnosis = report.split("## 3. Observations", 1)[1].split("## 4. Assessment Limits", 1)[0]
            performance = summary["stdout_sections"]["performance_summary"]

            self.assertIn("### App/Op Correlation", report)
            self.assertEqual(timing_artifact(summary, "op_summary").segment, "app")
            self.assertIsNone(timing_artifact(summary, "op_summary").metric_scope)
            self.assertEqual(timing_artifact(summary, "task_time").segment, "app")
            self.assertIsNone(timing_artifact(summary, "task_time").metric_scope)
            self.assertEqual(operator_headline(summary, "op_basic_info").segment, "op")
            self.assertEqual(operator_headline(summary, "op_basic_info").metric_scope, "PipeUtilization")
            self.assertEqual(operator_headline(summary, "pipe_utilization", field="aiv_scalar_ratio").segment, "op")
            self.assertEqual(operator_headline(summary, "pipe_utilization", field="aiv_scalar_ratio").metric_scope, "PipeUtilization")
            self.assertEqual(performance["source"], "logs/msprof_op.stdout")
            self.assertEqual(performance["section"], "Performance Summary Report")
            self.assertEqual(
                performance["messages"][0],
                {
                    "ordinal": 1,
                    "message": "aicore MTE3 bandwidth utilization lower than 80% when active.",
                },
            )
            self.assertNotIn("severity", performance["messages"][0])
            self.assertNotIn("advice", performance["messages"][0])
            self.assertIn("### CANN Performance Summary", report)
            self.assertIn("### Evidence Readiness", report)
            self.assertIn("- Level: `available`.", report)
            readiness_section = report.split("### Evidence Readiness", 1)[1].split("### App/Op Correlation", 1)[0]
            for token in ["app_timing", "operator_metadata", "pipe_utilization", "stdout_performance_summary"]:
                self.assertIn(token, readiness_section)
            self.assertIn("- Conditional collection option: `collect_default_metric_followup`", report)
            self.assertIn(
                "| 1 | aicore MTE3 bandwidth utilization lower than 80% when active. | `logs/msprof_op.stdout` |",
                report,
            )
            self.assertIn(
                "## CANN Performance Summary",
                (run_dir / "analysis" / "key_metrics.txt").read_text(encoding="utf-8"),
            )
            self.assertIn("- Op metric scope: PipeUtilization (source: `logs/command_msprof_op.txt`; `--aic-metrics`).", report)
            self.assertTrue(any(warning.startswith("missing arithmetic_utilization:") for warning in summary["warnings"]))
            self.assertTrue(any(warning.startswith("missing memory:") for warning in summary["warnings"]))
            self.assertNotIn("Analyzer warning: missing arithmetic_utilization:", report)
            self.assertNotIn("Analyzer warning: missing l2_cache:", report)
            self.assertNotIn("Analyzer warning: missing memory:", report)
            self.assertNotIn("Analyzer warning: missing resource_conflict:", report)
            self.assertIn(
                "- Operator launch metadata: Op Type=mix, Block Dim=1, Mix Block Dim=2, Current Freq=1800, Rated Freq=1800 "
                "(source: `reports/op/OPPROF_20260602101111_OPHASH12/OpBasicInfo.csv`; "
                "fields `Op Type`, `Block Dim`, `Mix Block Dim`, `Current Freq`, `Rated Freq`).",
                report,
            )
            self.assertIn(
                "| App top operator | sanitized_app_kernel / Task Duration(us) | 42.5 | "
                "`reports/app/PROF_000001_20260602101101_APPHASH1/mindstudio_profiler_output/op_summary_001.csv`; "
                f"`{observation_field_ref('op_summary', timing_observation(summary))}` |",
                report,
            )
            self.assertIn(
                "| App top task | sanitized_app_task / task_time(us) | 43 | "
                "`reports/app/PROF_000001_20260602101101_APPHASH1/mindstudio_profiler_output/task_time_001.csv`; "
                f"`{observation_field_ref('task_time', timing_observation(summary, 'task_time'))}` |",
                report,
            )
            self.assertIn(
                "| Op metadata | sanitized_op_kernel / Task Duration(us) | 5.75 | "
                "`reports/op/OPPROF_20260602101111_OPHASH12/OpBasicInfo.csv`; "
                f"`{observation_field_ref('op_basic_info', operator_observation(summary, 'op_basic_info'))}` |",
                report,
            )
            self.assertIn(
                "| Op pipe signal | vector0 / aiv_scalar_ratio | 0.5 | "
                "`reports/op/OPPROF_20260602101111_OPHASH12/PipeUtilization.csv`; "
                f"`{observation_field_ref('pipe_utilization', operator_observation(summary, 'pipe_utilization', field='aiv_scalar_ratio'))}` |",
                report,
            )
            self.assertNotIn("App/Op Correlation", diagnosis)
            self.assertNotIn("Op metadata", diagnosis)
            self.assertNotIn("sanitized_op_kernel", diagnosis)
            self.assertNotIn("aiv_scalar_ratio", diagnosis)
            actions = {item["id"]: item for item in summary["next_collection_actions"]}
            self.assertIn("collect_default_metric_followup", actions)
            self.assertEqual(actions["collect_default_metric_followup"]["recommended_aic_metrics"], ["Default"])
            self.assertIn("ArithmeticUtilization.csv", actions["collect_default_metric_followup"]["required_artifacts"])
            self.assertIn("### Next Collection Actions", report)
            self.assertIn("collect_default_metric_followup", report)
            self.assertNotIn("Optimization Directions", report)

    def test_analyze_default_performance_stdout_keeps_app_identity_with_op_scope(self):
        def write_run(root: Path, with_scope: bool) -> Path:
            run_dir = root / ("default_perf_scope" if with_scope else "default_perf_no_scope")
            logs = run_dir / "logs"
            op_dir = run_dir / "reports" / "OPPROF_001"
            logs.mkdir(parents=True)
            op_dir.mkdir(parents=True)
            if with_scope:
                (logs / "command_msprof_op.txt").write_text(
                    "msprof op --output=<abs-path>/reports --application=<abs-path>/run.sh --aic-metrics=PipeUtilization\n",
                    encoding="utf-8",
                )
            (logs / "msprof_default.stdout").write_text(
                (
                    "2026-06-03 12:00:00 [INFO] Performance Summary Report:\n"
                    "1) application performance message.\n"
                ),
                encoding="utf-8",
            )
            (op_dir / "OpBasicInfo.csv").write_text(
                "Op Name,Task Duration(us),Block Dim\nfallback_kernel,9,1\n",
                encoding="utf-8",
            )
            (op_dir / "PipeUtilization.csv").write_text(
                "Pipe,Utilization(%)\nVector,83\n",
                encoding="utf-8",
            )
            return run_dir

        with tempfile.TemporaryDirectory() as tmp:
            scoped_run = write_run(Path(tmp), True)
            unscoped_run = write_run(Path(tmp), False)

            for run_dir in [scoped_run, unscoped_run]:
                run([*CLI, "analyze", "--run-dir", str(run_dir)])

            scoped_summary = json.loads((scoped_run / "analysis" / "summary.json").read_text(encoding="utf-8"))
            unscoped_summary = json.loads((unscoped_run / "analysis" / "summary.json").read_text(encoding="utf-8"))


            self.assertEqual(scoped_summary["stdout_sections"]["performance_summary"]["source"], "logs/msprof_default.stdout")
