"""Core parser, validation, packaging, and collection-plan tests."""

from tests.helpers_shared import *  # noqa: F401,F403


class CoreHelperTests(unittest.TestCase):
    def test_to_float_accepts_only_complete_finite_numbers(self):
        from ascend_msprof_skill.ascend_profile_utils import to_float

        for value, expected in [
            (0, 0.0), (-2, -2.0), (1.25, 1.25),
            ("1.2e-3", 0.0012), ("2E3", 2000.0), (".5", 0.5),
            ("-.5", -0.5), ("1.", 1.0), (" +2.5e+1 ", 25.0),
        ]:
            with self.subTest(value=value):
                self.assertEqual(to_float(value), expected)
        for value in [
            None, "", "  ", "NA", True, False, "abc123", "1.2e", "1 2",
            "85%", "1ms", "1,234", "1_000", "NaN", "Inf", "-Infinity",
            float("nan"), float("inf"), -float("inf"), "1e309", 10 ** 400,
        ]:
            with self.subTest(value=value):
                self.assertIsNone(to_float(value))

    def test_profiler_segments_classify_artifacts_and_metric_scope(self):
        self.assertEqual(profiler_segments.segment_for_relpath("reports/app/PROF_001/op_summary_001.csv"), "app")
        self.assertEqual(profiler_segments.segment_for_relpath("reports/op/OPPROF_001/PipeUtilization.csv"), "op")
        self.assertEqual(
            profiler_segments.segment_for_relpath(
                "reports/followups/collect_default_metric_followup/OPPROF_001/Memory.csv"
            ),
            "followup:collect_default_metric_followup",
        )
        self.assertEqual(
            profiler_segments.segment_for_relpath("reports/OPPROF_001/simulator/trace.json"),
            "simulator",
        )
        self.assertEqual(
            profiler_segments.segment_for_relpath("reports/PROF_001/mindstudio_profiler_output/task_time.csv"),
            "app",
        )
        self.assertEqual(
            profiler_segments.segment_for_relpath("reports/OPPROF_001/OpBasicInfo.csv"),
            "op",
        )
        self.assertEqual(profiler_segments.segment_for_relpath("somewhere/task_time_001.csv", "task_time"), "app")
        self.assertEqual(
            profiler_segments.metric_scope_for_segment("followup:collect_default_metric_followup", None),
            "Default",
        )
        self.assertEqual(profiler_segments.segment_for_relpath("reports/other/file.csv"), "unknown")
        self.assertIsNone(profiler_segments.metric_scope_for_segment("followup:unknown_action", None))
        for malformed_segment in ["followup:", None, 123, "op"]:
            self.assertFalse(profiler_segments.is_followup_segment(malformed_segment))
            self.assertIsNone(profiler_segments.followup_action_from_segment(malformed_segment))
        self.assertTrue(profiler_segments.is_followup_segment("followup:collect_default_metric_followup"))

    def test_profiler_segments_classify_provenance_logs(self):
        self.assertEqual(profiler_segments.command_profile_output_segment(Path("command_msprof.txt")), "app")
        self.assertEqual(profiler_segments.command_profile_output_segment(Path("command_msprof_op.txt")), "op")
        self.assertIsNone(
            profiler_segments.command_profile_output_segment(
                Path("command_msprof_followup_collect_default_metric_followup.txt")
            )
        )
        self.assertEqual(
            profiler_segments.followup_action_from_command_path(
                Path("command_msprof_followup_collect_default_metric_followup.txt")
            ),
            "collect_default_metric_followup",
        )
        self.assertIsNone(
            profiler_segments.followup_action_from_command_path(Path("command_msprof_followup_unknown.txt"))
        )
        self.assertTrue(
            profiler_segments.is_followup_stdout_or_status(
                Path("msprof_followup_collect_default_metric_followup.stdout")
            )
        )
        self.assertTrue(
            profiler_segments.is_followup_stdout_or_status(
                Path("msprof_followup_collect_default_metric_followup.status")
            )
        )
        self.assertFalse(
            profiler_segments.is_followup_stdout_or_status(
                Path("msprof_followup_collect_default_metric_followup.stderr")
            )
        )
        self.assertEqual(profiler_segments.stdout_profile_output_segment(Path("msprof_default.stdout")), "app")
        self.assertEqual(profiler_segments.stdout_profile_output_segment(Path("msprof_op.stdout")), "op")
        self.assertEqual(profiler_segments.stdout_profile_output_segment(Path("msprof_occupancy.stdout")), "op")
        self.assertEqual(profiler_segments.stdout_profile_output_segment(Path("msprof_roofline.stdout")), "op")

    def test_evidence_readiness_uses_validated_followup_segments(self):
        from pydantic import ValidationError
        from ascend_msprof_skill.summary_types import RawArtifactIndex, IndexedArtifact
        from ascend_msprof_skill._evidence_readiness import build_evidence_readiness, known_scope_segments

        def record(segment, ordinal):
            return IndexedArtifact(artifact=f"reports/OPPROF_{ordinal}/ArithmeticUtilization.csv",
                parser="csv", group="arithmetic_utilization", segment=segment, metric_scope="Default",
                status="parsed", columns=("aiv_vec_ratio",), row_count=1, sample_rows=(), warnings=())

        with self.assertRaises(ValidationError):
            record(123, 0)
        index = RawArtifactIndex(raw_artifact_index_schema_version="1.1",
            artifacts=(record("followup:", 1), record("followup:collect_default_metric_followup", 2)), warnings=())
        with tempfile.TemporaryDirectory() as tmp:
            summary, _, _simulator = evidence_model.build_evidence_model(Path(tmp))
        self.assertEqual(known_scope_segments(summary, index), [("followup:collect_default_metric_followup", "Default")])
        readiness = build_evidence_readiness(summary, index, actions=(), simulator_signals=())
        segments = readiness.segments
        self.assertFalse(any(item.segment == "followup:" for item in segments))
        self.assertTrue(any(item.segment == "followup:collect_default_metric_followup" for item in segments))

    def test_parse_occupancy_summary_text_one_message(self):
        section = parse_occupancy_summary_text(
            (
                "2026-05-31 13:04:28 [INFO]  Occupancy Summary Report:\n"
                "\n"
                "\t1) core2 vector0 took more time than other vector cores.\n"
                "\n"
                "2026-05-31 13:04:29 [INFO]  Performance Summary Report:\n"
            ),
            "logs/msprof_occupancy.stdout",
        ).model_dump(mode="json", exclude_unset=True)

        self.assertEqual(section["source"], "logs/msprof_occupancy.stdout")
        self.assertEqual(section["section"], "Occupancy Summary Report")
        self.assertEqual(
            section["messages"],
            [{"ordinal": 1, "message": "core2 vector0 took more time than other vector cores."}],
        )

    def test_parse_occupancy_summary_text_multi_message_stops_before_next_report(self):
        section = parse_occupancy_summary_text(
            (
                "2026-05-31 13:04:39 [INFO]  Occupancy Summary Report:\n"
                "\n"
                "\t1) core3 vector0 took more time than other vector cores.\n"
                "\t2) core0 vector0 cache hit rate lower than other vector cores.\n"
                "\n"
                "2026-05-31 13:04:41 [INFO]  Performance Summary Report:\n"
                "\t3) this belongs to another section.\n"
            ),
            "logs/msprof_occupancy.stdout",
        ).model_dump(mode="json", exclude_unset=True)

        self.assertEqual(len(section["messages"]), 2)
        self.assertEqual(section["messages"][1]["ordinal"], 2)
        self.assertEqual(
            section["messages"][1]["message"],
            "core0 vector0 cache hit rate lower than other vector cores.",
        )
        self.assertNotIn("core_id", section["messages"][0])
        self.assertNotIn("role", section["messages"][0])
        self.assertNotIn("severity", section["messages"][0])
        self.assertNotIn("advice", section["messages"][0])

    def test_parse_occupancy_summary_stdout_returns_none_without_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            logs = run_dir / "logs"
            logs.mkdir(parents=True)
            (logs / "msprof_default.stdout").write_text(
                "2026-05-31 13:04:41 [INFO]  Performance Summary Report:\n",
                encoding="utf-8",
            )

            self.assertIsNone(parse_occupancy_summary_stdout(run_dir))

    def test_parse_roofline_summary_text_one_message(self):
        section = parse_roofline_summary_text(
            (
                "2026-05-31 15:28:43 [INFO]  RoofLine Summary Report:\n"
                "\n"
                "\tlatency bound:pipeline caused\n"
                "\n"
                "2026-05-31 15:28:45 [INFO]  Performance Summary Report:\n"
            ),
            "logs/msprof_roofline.stdout",
        ).model_dump(mode="json", exclude_unset=True)

        self.assertEqual(section["source"], "logs/msprof_roofline.stdout")
        self.assertEqual(section["section"], "RoofLine Summary Report")
        self.assertEqual(section["messages"], [{"message": "latency bound:pipeline caused"}])
        self.assertNotIn("bound_type", section["messages"][0])
        self.assertNotIn("cause", section["messages"][0])
        self.assertNotIn("severity", section["messages"][0])
        self.assertNotIn("advice", section["messages"][0])

    def test_parse_roofline_summary_text_stops_before_next_report(self):
        section = parse_roofline_summary_text(
            (
                "2026-05-31 15:28:43 [INFO]  RoofLine Summary Report:\n"
                "\n"
                "\tlatency bound:pipeline caused\n"
                "\n"
                "2026-05-31 15:28:45 [INFO]  Performance Summary Report:\n"
                "\t1) this belongs to another section.\n"
            ),
            "logs/msprof_roofline.stdout",
        ).model_dump(mode="json", exclude_unset=True)

        self.assertEqual(section["messages"], [{"message": "latency bound:pipeline caused"}])

    def test_parse_roofline_summary_stdout_returns_none_without_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            logs = run_dir / "logs"
            logs.mkdir(parents=True)
            (logs / "msprof_roofline.stdout").write_text(
                "2026-05-31 15:28:45 [INFO]  Performance Summary Report:\n",
                encoding="utf-8",
            )

            self.assertIsNone(parse_roofline_summary_stdout(run_dir))

    def test_parse_performance_summary_text_messages_stop_before_next_header(self):
        section = parse_performance_summary_text(
            (
                "2026-06-02 12:56:11 [INFO]  Performance Summary Report:\n"
                "\n"
                "\t1) aicore MTE3 bandwidth utilization lower than 80% when active.\n"
                "\t2) aivector compute usage lower than 20%.\n"
                "\n"
                "2026-06-02 12:56:11 [INFO]  Operator Basic Information:\n"
                "\t3) this belongs to another section.\n"
            ),
            "logs/msprof_op.stdout",
        ).model_dump(mode="json", exclude_unset=True)

        self.assertEqual(section["source"], "logs/msprof_op.stdout")
        self.assertEqual(section["section"], "Performance Summary Report")
        self.assertEqual(
            section["messages"],
            [
                {
                    "ordinal": 1,
                    "message": "aicore MTE3 bandwidth utilization lower than 80% when active.",
                },
                {
                    "ordinal": 2,
                    "message": "aivector compute usage lower than 20%.",
                },
            ],
        )
        self.assertNotIn("severity", section["messages"][0])
        self.assertNotIn("advice", section["messages"][0])
        self.assertNotIn("category", section["messages"][0])

    def test_parse_performance_summary_stdout_returns_none_without_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            logs = run_dir / "logs"
            logs.mkdir(parents=True)
            (logs / "msprof_op.stdout").write_text(
                "2026-06-02 12:56:11 [INFO]  Performance Summary Report:\n"
                "2026-06-02 12:56:11 [INFO]  Operator Basic Information:\n",
                encoding="utf-8",
            )

            self.assertIsNone(parse_performance_summary_stdout(run_dir))

    def test_selected_occupancy_stdout_priority_excludes_auxiliary_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            logs = run_dir / "logs"
            logs.mkdir(parents=True)
            for name in [
                "msprof_default.stdout",
                "command_msprof.stdout",
                "msprof_occupancy_help.stdout",
                "msprof_occupancy.stdout",
                "msprof_z.stdout",
            ]:
                (logs / name).write_text("", encoding="utf-8")

            selected = [path.name for path in selected_profiler_stdout_paths(run_dir)]
            self.assertEqual(
                selected,
                [
                    "msprof_occupancy.stdout",
                    "msprof_default.stdout",
                    "command_msprof.stdout",
                    "msprof_z.stdout",
                ],
            )

    def test_selected_roofline_stdout_priority_excludes_auxiliary_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            logs = run_dir / "logs"
            logs.mkdir(parents=True)
            for name in [
                "msprof_default.stdout",
                "command_msprof.stdout",
                "msprof_roofline_help.stdout",
                "msprof_roofline_export.stdout",
                "msprof_roofline_validation.stdout",
                "msprof_roofline_malformed.stdout",
                "msprof_roofline.stdout",
                "msprof_z.stdout",
            ]:
                (logs / name).write_text("", encoding="utf-8")

            selected = [path.name for path in selected_roofline_stdout_paths(run_dir)]
            self.assertEqual(
                selected,
                [
                    "msprof_roofline.stdout",
                    "msprof_default.stdout",
                    "command_msprof.stdout",
                    "msprof_z.stdout",
                ],
            )

    def test_validate_covers_readme_application_first_guidance(self):
        import scripts.validate as validate

        readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
        guidance_paths = set(validate.GUIDANCE_DOC_PATHS)
        required_reference_paths = {
            f"skills/ascend-msprof-skill/reference/{name}" for name in validate.REQUIRED_REFERENCES
        }

        self.assertTrue(required_reference_paths.issubset(guidance_paths))
        self.assertIn("AGENTS.md", guidance_paths)
        self.assertIn("ARCHITECTURE.md", guidance_paths)
        self.assertIn("skills/ascend-msprof-skill/ascend-910b-programming.md", guidance_paths)
        self.assertNotIn("scripts/validate.py", guidance_paths)
        self.assertNotIn("tests/test_helpers.py", guidance_paths)
        self.assertIn("pip install -e .", readme_text)
        self.assertIn("pip install dist/ascend_msprof_skill-0.1.0-py3-none-any.whl", readme_text)
        self.assertIn("skills/ascend-msprof-skill/", readme_text)
        self.assertIn("$APPLICATION", readme_text)
        for log_name in validate.REQUIRED_COMMAND_LOGS:
            self.assertIn(log_name, readme_text)
        for setup in validate.REQUIRED_COMMAND_SETUP:
            self.assertIn(setup, readme_text)
        canonical_text = (ROOT / validate.CANONICAL_AGENT_COMMAND_DOC).read_text(encoding="utf-8")
        for setup in validate.REQUIRED_COMMAND_SETUP:
            self.assertIn(setup, canonical_text)
        self.assertNotIn("--benchmark-repo", readme_text)
        self.assertNotIn("render-profile-harness", readme_text)

    def test_validate_skill_contract_rejects_each_scoped_task_route(self):
        import scripts.validate as validate

        skill_rel = validate.skill_rel("SKILL.md")
        collection_rel = validate.skill_rel("reference/03-collection.md")
        skill_text = (ROOT / skill_rel).read_text(encoding="utf-8")
        collection_text = (ROOT / collection_rel).read_text(encoding="utf-8")
        expected_routes = {
            "End-to-end profiling": (
                "reference/00-directory-layout.md",
                "reference/01-workflow.md",
                "reference/03-collection.md",
            ),
            "Supplied harness or direct application": (
                "reference/02-harness-guide.md",
                "reference/03-collection.md",
            ),
            "Analyze an existing run": (
                "reference/04-output-files.md",
                "reference/05-analysis-dimensions.md",
                "reference/10-summary-schema.md",
            ),
            "Diagnose a supported signal": ("reference/06-diagnosis-playbook.md",),
            "Interpret an unfamiliar field or metric scope": (
                "reference/08-ascend-metric-files.md",
            ),
            "Inspect simulator evidence": (
                "reference/03-collection.md",
                "reference/04-output-files.md",
                "reference/10-summary-schema.md",
            ),
            "Summarize or compare candidates": (
                "reference/11-candidate-comparison-schema.md",
                "reference/10-summary-schema.md",
            ),
            "Generate or review a report": ("reference/07-report-template.md",),
            "Resolve collection or parsing failures": ("reference/09-common-issues.md",),
            "Understand Ascend C terms in source or profiler evidence": ("ascend-910b-programming.md",),
        }
        self.assertEqual(validate.REQUIRED_TASK_ROUTES, expected_routes)

        for branch, routes in expected_routes.items():
            row = next(
                line for line in skill_text.splitlines() if line.startswith(f"| {branch} |")
            )
            with self.subTest(branch=branch, mutation="row"):
                errors: list[str] = []
                validate.validate_skill_contract(
                    errors,
                    {
                        skill_rel: skill_text.replace(f"{row}\n", "", 1),
                        collection_rel: collection_text,
                    },
                )
                self.assertTrue(any(branch in error for error in errors), errors)

            for route in routes:
                with self.subTest(branch=branch, route=route):
                    mutated_row = row.replace(f"]({route})", "](missing.md)", 1)
                    self.assertNotEqual(mutated_row, row)
                    errors = []
                    validate.validate_skill_contract(
                        errors,
                        {
                            skill_rel: skill_text.replace(row, mutated_row, 1),
                            collection_rel: collection_text,
                        },
                    )
                    self.assertTrue(
                        any(branch in error and route in error for error in errors),
                        errors,
                    )

    def test_validate_skill_contract_rejects_missing_capability_anchor(self):
        import scripts.validate as validate

        rel = validate.skill_rel("SKILL.md")
        skill_text = (ROOT / rel).read_text(encoding="utf-8")
        errors: list[str] = []

        validate.validate_skill_contract(
            errors,
            {rel: skill_text.replace("--follow-next-actions", "--follow-actions")},
        )

        self.assertTrue(any("--follow-next-actions" in error for error in errors))

    def test_validate_skill_contract_rejects_missing_drilldown_anchor(self):
        import scripts.validate as validate

        rel = validate.skill_rel("SKILL.md")
        skill_text = (ROOT / rel).read_text(encoding="utf-8").replace("sample_rows", "samples")
        errors: list[str] = []

        validate.validate_skill_contract(errors, {rel: skill_text})

        self.assertTrue(any("sample_rows" in error for error in errors))

    def test_validate_skill_contract_rejects_each_collection_semantic_phrase(self):
        import scripts.validate as validate

        skill_rel = validate.skill_rel("SKILL.md")
        collection_rel = validate.skill_rel("reference/03-collection.md")
        baseline_docs = {
            skill_rel: (ROOT / skill_rel).read_text(encoding="utf-8"),
            collection_rel: validate.normalize_semantic_text(
                (ROOT / collection_rel).read_text(encoding="utf-8")
            ),
        }
        requirements = validate.REQUIRED_DOCUMENT_SEMANTICS[collection_rel]
        self.assertEqual(
            {label for label, _ in requirements},
            {
                "triage preset",
                "default-depth preset",
                "full preset",
                "omitted preset defaults to triage",
                "full simulator condition",
                "summary continuation flag",
                "continuation metadata reuse",
                "continuation overwrite refusal",
                "continuation action statuses",
                "unsupported action handling",
            },
        )

        for label, phrase in requirements:
            with self.subTest(label=label):
                self.assertIn(phrase, baseline_docs[collection_rel])
                docs = dict(baseline_docs)
                docs[collection_rel] = docs[collection_rel].replace(phrase, "", 1)
                errors: list[str] = []

                validate.validate_skill_contract(errors, docs)

                self.assertTrue(any(label in error for error in errors), errors)

    def test_validate_skill_contract_rejects_each_skill_semantic_phrase(self):
        import scripts.validate as validate

        skill_rel = validate.skill_rel("SKILL.md")
        collection_rel = validate.skill_rel("reference/03-collection.md")
        baseline_docs = {
            skill_rel: validate.normalize_semantic_text(
                (ROOT / skill_rel).read_text(encoding="utf-8")
            ),
            collection_rel: (ROOT / collection_rel).read_text(encoding="utf-8"),
        }
        requirements = validate.REQUIRED_DOCUMENT_SEMANTICS[skill_rel]
        self.assertEqual(
            {label for label, _ in requirements},
            {
                "fresh-run directory creation before resolution",
                "missing-derived entry condition",
                "missing-derived disclosure",
                "missing-derived purpose bound",
                "missing-derived exact citation",
                "missing-derived claim gate",
            },
        )

        for label, phrase in requirements:
            with self.subTest(label=label):
                self.assertIn(phrase, baseline_docs[skill_rel])
                docs = dict(baseline_docs)
                docs[skill_rel] = docs[skill_rel].replace(phrase, "", 1)
                errors: list[str] = []

                validate.validate_skill_contract(errors, docs)

                self.assertTrue(any(label in error for error in errors), errors)

    def test_validate_markdown_links_rejects_broken_local_target(self):
        import scripts.validate as validate

        docs = {
            "skills/demo/SKILL.md": "Read [the reference](reference/missing.md).\n",
            "skills/demo/reference/present.md": "# Present\n",
        }
        errors: list[str] = []

        validate.validate_markdown_links(errors, docs)

        self.assertEqual(
            errors,
            ["skills/demo/SKILL.md:1: broken Markdown link reference/missing.md"],
        )

    def test_validate_markdown_links_rejects_broken_local_anchor(self):
        import scripts.validate as validate

        docs = {
            "skills/demo/SKILL.md": "Read [the section](reference/present.md#missing).\n",
            "skills/demo/reference/present.md": "# Present\n\n## Existing\n",
        }
        errors: list[str] = []

        validate.validate_markdown_links(errors, docs)

        self.assertEqual(
            errors,
            ["skills/demo/SKILL.md:1: broken Markdown anchor reference/present.md#missing"],
        )

    def test_validate_markdown_links_ignores_headings_inside_fenced_code(self):
        import scripts.validate as validate

        docs = {
            "skills/demo/SKILL.md": (
                "Read [the rendered section](reference/present.md#existing) and "
                "[the fenced example](reference/present.md#example-only).\n"
            ),
            "skills/demo/reference/present.md": (
                "# Present\n\n"
                "```markdown\n## Example Only\n```\n\n"
                "## Existing\n"
            ),
        }
        errors: list[str] = []

        validate.validate_markdown_links(errors, docs)

        self.assertEqual(
            errors,
            [
                "skills/demo/SKILL.md:1: broken Markdown anchor "
                "reference/present.md#example-only"
            ],
        )

    def test_validate_command_docs_keeps_recipe_details_out_of_routing_docs(self):
        import scripts.validate as validate

        paths = sorted(set(validate.COMMAND_DOC_PATHS + validate.GUIDANCE_DOC_PATHS))
        docs = {rel: (ROOT / rel).read_text(encoding="utf-8") for rel in paths}
        for rel in [validate.skill_rel("SKILL.md"), validate.WORKFLOW_DOC]:
            for token in [
                *validate.REQUIRED_APP_FLAGS,
                *validate.REQUIRED_COMMAND_LOGS,
                *validate.REQUIRED_COMMAND_SETUP,
            ]:
                docs[rel] = docs[rel].replace(token, "")
        errors: list[str] = []

        validate.validate_command_docs(errors, docs)

        self.assertFalse(any(validate.skill_rel("SKILL.md") in error for error in errors), errors)
        self.assertFalse(any(validate.WORKFLOW_DOC in error and "command" in error for error in errors), errors)

    def test_validate_command_docs_rejects_each_scoped_recipe_semantic(self):
        import scripts.validate as validate

        paths = sorted(set(validate.COMMAND_DOC_PATHS + validate.GUIDANCE_DOC_PATHS))
        baseline_docs = {rel: (ROOT / rel).read_text(encoding="utf-8") for rel in paths}
        canonical_text = baseline_docs[validate.CANONICAL_AGENT_COMMAND_DOC]
        blocks = validate.bash_code_blocks(canonical_text)
        expected_contract = {
            "application": (
                "MSPROF_APP_CMD=(",
                [
                    ("invocation", "MSPROF_APP_CMD=( msprof"),
                    ("output", '--output="$PROFILE_RUN_DIR/reports/app"'),
                    ("application", '--application="$APPLICATION"'),
                    ("--runtime-api=on", "--runtime-api=on"),
                    ("--task-time=on", "--task-time=on"),
                    ("--ai-core=on", "--ai-core=on"),
                    ("--aic-metrics=PipeUtilization", "--aic-metrics=PipeUtilization"),
                    ("--type=text", "--type=text"),
                    ("--summary-format=csv", "--summary-format=csv"),
                    (
                        "command log",
                        'printf "%q " "${MSPROF_APP_CMD[@]}" > '
                        '"$PROFILE_RUN_DIR/logs/command_msprof.txt"',
                    ),
                    (
                        "execution",
                        'printf "\\n" >> "$PROFILE_RUN_DIR/logs/command_msprof.txt" '
                        '"${MSPROF_APP_CMD[@]}"',
                    ),
                ],
            ),
            "operator": (
                "MSPROF_OP_CMD=(",
                [
                    ("invocation", "MSPROF_OP_CMD=( msprof op"),
                    ("output", '--output="$PROFILE_RUN_DIR/reports/op"'),
                    ("application", '--application="$APPLICATION"'),
                    ("metric", "--aic-metrics=PipeUtilization"),
                    (
                        "command log",
                        'printf "%q " "${MSPROF_OP_CMD[@]}" > '
                        '"$PROFILE_RUN_DIR/logs/command_msprof_op.txt"',
                    ),
                    (
                        "execution",
                        'printf "\\n" >> "$PROFILE_RUN_DIR/logs/command_msprof_op.txt" '
                        '"${MSPROF_OP_CMD[@]}"',
                    ),
                ],
            ),
            "follow-up": (
                "MSPROF_FOLLOWUP_CMD=(",
                [
                    ("invocation", "MSPROF_FOLLOWUP_CMD=( msprof op"),
                    (
                        "output",
                        '--output="$PROFILE_RUN_DIR/reports/followups/'
                        'collect_default_metric_followup"',
                    ),
                    ("application", '--application="$APPLICATION"'),
                    ("metric", "--aic-metrics=Default"),
                    (
                        "command log",
                        'printf "%q " "${MSPROF_FOLLOWUP_CMD[@]}" \\ '
                        '> "$PROFILE_RUN_DIR/logs/'
                        'command_msprof_followup_collect_default_metric_followup.txt"',
                    ),
                    (
                        "execution",
                        'printf "\\n" >> "$PROFILE_RUN_DIR/logs/'
                        'command_msprof_followup_collect_default_metric_followup.txt" '
                        '"${MSPROF_FOLLOWUP_CMD[@]}"',
                    ),
                ],
            ),
            "simulator": (
                "msprof op simulator",
                [
                    ("invocation", "msprof op simulator"),
                    ("output", '--output="$PROFILE_RUN_DIR/reports/sim"'),
                    ("application", '--application="$APPLICATION"'),
                    ("metric", "--aic-metrics=PipeUtilization"),
                ],
            ),
        }
        actual_contract = {
            recipe: (
                marker,
                [
                    (semantic, validate.normalize_semantic_text(phrase))
                    for semantic, phrase in requirements
                ],
            )
            for recipe, (marker, requirements) in (
                validate.REQUIRED_CANONICAL_COMMAND_BLOCKS.items()
            )
        }
        self.assertEqual(actual_contract, expected_contract)

        for recipe, (marker, requirements) in (
            validate.REQUIRED_CANONICAL_COMMAND_BLOCKS.items()
        ):
            block = next(item for item in blocks if marker in item)
            normalized_block = validate.normalize_semantic_text(block)
            for semantic, phrase in requirements:
                with self.subTest(recipe=recipe, semantic=semantic):
                    normalized_phrase = validate.normalize_semantic_text(phrase)
                    self.assertIn(normalized_phrase, normalized_block)
                    mutated_block = normalized_block.replace(normalized_phrase, "", 1)
                    docs = dict(baseline_docs)
                    docs[validate.CANONICAL_AGENT_COMMAND_DOC] = canonical_text.replace(
                        block,
                        mutated_block,
                        1,
                    )
                    errors: list[str] = []

                    validate.validate_command_docs(errors, docs)

                    expected = (
                        f"missing {recipe} command recipe"
                        if semantic == "invocation"
                        else f"{recipe} command recipe: {semantic}"
                    )
                    self.assertTrue(any(expected in error for error in errors), errors)

    def test_validate_source_boundary_rejects_benchmark_renderer_commands(self):
        import scripts.validate as validate

        forbidden = "cmd = '" + "render-profile-" + "harness --task demo'"
        errors = validate.audit_source_boundary_text("src/ascend_msprof_skill/example.py", forbidden)

        self.assertTrue(any("forbidden source-boundary token benchmark-renderer-command" in error for error in errors))

    def test_validate_rejects_legacy_committed_skill_source(self):
        import scripts.validate as validate

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(validate, "ROOT", Path(tmp)):
            legacy_skill = validate.ROOT / validate.LEGACY_COMMITTED_SKILL_ROOT_REL
            legacy_skill.mkdir(parents=True)
            errors: list[str] = []
            validate.validate_skill_layout(errors)

            self.assertTrue(any("must not be committed" in error for error in errors))

    def test_validate_fixture_audit_rejects_unmarked_stale_payload_name(self):
        import scripts.validate as validate

        with tempfile.TemporaryDirectory() as tmp:
            fixtures_root = Path(tmp) / "fixtures"
            stale = fixtures_root / "generic" / "analysis" / "context.json"
            stale.parent.mkdir(parents=True)
            stale.write_text(json.dumps({"artifact": "kernel_payload_baseline.py"}) + "\n", encoding="utf-8")

            errors: list[str] = []
            validate.validate_fixture_stale_names(errors, fixtures_root)

            self.assertTrue(any("unmarked stale fixture token baseline-payload-name" in error for error in errors))

    def test_package_cli_help_and_skill_path(self):
        help_result = run([*CLI, "--help"])
        self.assertIn("ascend-msprof", help_result.stdout)
        self.assertIn("analyze", help_result.stdout)
        self.assertIn("profile-harness", help_result.stdout)
        self.assertIn("skill", help_result.stdout)

        analyze_help = run([*CLI, "analyze", "--help"])
        self.assertIn("--run-dir", analyze_help.stdout)

        profile_help = run([*CLI, "profile-harness", "--help"])
        self.assertIn("--manifest", profile_help.stdout)
        self.assertIn("--application", profile_help.stdout)
        self.assertIn("--verify-json", profile_help.stdout)
        self.assertIn("--simulator", profile_help.stdout)
        self.assertIn("--simulator-timeout-s", profile_help.stdout)

        skill_path_result = run([*CLI, "skill", "path"])
        skill_path = Path(skill_path_result.stdout.strip())
        self.assertTrue((skill_path / "SKILL.md").exists())
        self.assertTrue((skill_path / "ascend-910b-programming.md").exists())
        self.assertTrue((skill_path / "reference" / "01-workflow.md").exists())
        self.assertTrue((skill_path / "data" / "reference-sources.yaml").exists())
        self.assertTrue((skill_path / "assets" / "harness_template.cpp").exists())

    def test_dist_content_audit_rejects_forbidden_paths(self):
        import scripts.check_dist_contents as check_dist_contents

        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / "bad.whl"
            with zipfile.ZipFile(wheel, "w") as zf:
                zf.writestr("ascend_msprof_skill/cli.py", "")
                zf.writestr("tests/fixtures/leak.csv", "")

            errors = check_dist_contents.audit(wheel)
            self.assertTrue(any("forbidden path" in error for error in errors))

    def test_dist_content_audit_requires_canonical_skill_sdist_and_packaged_wheel_skill(self):
        import scripts.check_dist_contents as check_dist_contents

        with tempfile.TemporaryDirectory() as tmp:
            root = "ascend_msprof_skill-0.1.0"
            sdist = Path(tmp) / "good.tar.gz"
            with tarfile.open(sdist, "w:gz") as tf:
                for name in check_dist_contents.REQUIRED_SDIST_PATHS:
                    info = tarfile.TarInfo(f"{root}/{name}")
                    payload = b"x\n"
                    info.size = len(payload)
                    tf.addfile(info, io.BytesIO(payload))

            self.assertEqual(check_dist_contents.audit(sdist), [])

            wheel = Path(tmp) / "bad_skill_source.whl"
            with zipfile.ZipFile(wheel, "w") as zf:
                for name in check_dist_contents.REQUIRED_WHEEL_PATHS:
                    zf.writestr(name, "")
                zf.writestr("skills/ascend-msprof-skill/SKILL.md", "")

            errors = check_dist_contents.audit(wheel)
            self.assertTrue(any("top-level skill source path" in error for error in errors))

    def test_collection_plan_catalog_is_metadata_only(self):
        expected_segments = {
            "triage": ["app", "op"],
            "default-depth": ["app", "op", "default"],
            "full": ["app", "op", "default", "simulator"],
        }
        for preset_id, segment_ids in expected_segments.items():
            plan = collection_plan.preset_plan(preset_id)
            self.assertIsNotNone(plan)
            self.assertEqual(plan["preset_id"], preset_id)
            self.assertEqual([segment["segment_id"] for segment in plan["segments"]], segment_ids)
            for segment in plan["segments"]:
                self.assertIn("output_key", segment)
                self.assertIn("command_log", segment)
                self.assertNotIn("output", segment)
                self.assertNotIn("status", segment)

        self.assertIsNone(collection_plan.preset_plan("unknown"))
