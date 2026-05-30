import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "mock_run"
REAL_FIXTURE = ROOT / "tests" / "fixtures" / "real_cann_minimal"
REAL_SIMULATOR_FIXTURE = ROOT / "tests" / "fixtures" / "real_simulator_minimal"
REAL_L2CACHE_FIXTURE = ROOT / "tests" / "fixtures" / "real_l2cache_minimal"
REAL_DEFAULT_VECTOR_FIXTURE = ROOT / "tests" / "fixtures" / "real_default_vector_minimal"


def run(cmd, cwd=ROOT):
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True)


def fresh_run(parent: Path, name: str = "mock_run") -> Path:
    return copy_fixture(FIXTURE, parent, name)


def fresh_real_run(parent: Path, name: str = "real_cann_minimal") -> Path:
    return copy_fixture(REAL_FIXTURE, parent, name, ignore_analysis=True)


def fresh_real_simulator_run(parent: Path, name: str = "real_simulator_minimal") -> Path:
    return copy_fixture(REAL_SIMULATOR_FIXTURE, parent, name, ignore_analysis=True)


def fresh_real_l2cache_run(parent: Path, name: str = "real_l2cache_minimal") -> Path:
    return copy_fixture(REAL_L2CACHE_FIXTURE, parent, name, ignore_analysis=True)


def fresh_real_default_vector_run(parent: Path, name: str = "real_default_vector_minimal") -> Path:
    return copy_fixture(REAL_DEFAULT_VECTOR_FIXTURE, parent, name, ignore_analysis=True)


def copy_fixture(source: Path, parent: Path, name: str, ignore_analysis: bool = False) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    dst = parent / name
    ignore = shutil.ignore_patterns("analysis") if ignore_analysis else None
    shutil.copytree(source, dst, ignore=ignore)
    return dst


def fresh_op_summary_variant_run(parent: Path, name: str = "source_shape_run") -> Path:
    dst = parent / name
    op_summary_dir = dst / "reports" / "PROF_001" / "mindstudio_profiler_output"
    op_summary_dir.mkdir(parents=True, exist_ok=True)
    (op_summary_dir / "op_summary_001.csv").write_text(
        (
            "Device_id,Model ID,Task ID,Stream ID,Op Name,OP Type,OP State,Task Type,"
            "Task Start Time(us),Task Duration(us),Task Wait Time(us),Block Dim,"
            "Mix Block Dim,HF32 Eligible,Input Shapes,Input Data Types,Input Formats,"
            "Output Shapes,Output Data Types,Output Formats,Context ID,aicore_time(us),"
            "total_cycles,ai*_vec_time(us),ai*_mac_time(us),ai*_scalar_time(us),"
            "ai*_scalar_ratio,ai*_mte2_time(us)\n"
            "0,100,1,2,official_kernel_a,MatMul,static,AI_CORE,0.0,12.5,0.1,1,1,YES,"
            "\"[1,2]\",\"F16\",\"ND\",\"[1,2]\",\"F16\",\"ND\",7,11.0,1000,4.0,5.0,3.0,0.25,6.0\n"
            "0,100,2,2,official_kernel_b,MatMul,static,AI_CORE,0.0,88.125,0.1,1,1,YES,"
            "\"[1,2]\",\"F16\",\"ND\",\"[1,2]\",\"F16\",\"ND\",7,77.0,2000,8.0,9.0,10.0,0.75,11.0\n"
        ),
        encoding="utf-8",
    )
    return dst


def one_line_read(report: str) -> str:
    return next(line for line in report.splitlines() if line.startswith("**One-line read:**"))


def timeline_text(run_dir: Path) -> str:
    return (run_dir / "analysis" / "timeline.txt").read_text()


def assert_l2cache_report_evidence(test: unittest.TestCase, report: str) -> None:
    test.assertIn("| L2 cache hit-rate signal | cube0 / aic_total_hit_rate(%) | 72 |", report)
    test.assertIn("reports/OPPROF_001/L2Cache.csv", report)
    test.assertIn("headlines.l2_cache.field=aic_total_hit_rate(%)", report)
    test.assertIn("### L2 Cache", report)
    test.assertIn("`l2_cache`: `cube0` field `aic_total_hit_rate(%)` = `72`", report)


class HelperTests(unittest.TestCase):
    def test_analyze_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp))
            run(["python3", "helpers/analyze_msprof_outputs.py", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            self.assertEqual(summary["headlines"]["op_summary"]["name"], "MockMatMul")
            self.assertEqual(summary["headlines"]["pipe_utilization"]["value"], 86.0)
            self.assertEqual(summary["headlines"]["memory"]["name"], "metric")
            self.assertEqual(summary["headlines"]["memory"]["field"], "GM Read Bandwidth(GB/s)")
            self.assertEqual(summary["headlines"]["memory"]["value"], 700.0)
            self.assertEqual(summary["headlines"]["memory"]["field_kind"], "memory_bandwidth")
            self.assertTrue((run_dir / "analysis" / "key_metrics.txt").exists())

    def test_analyze_real_cann_minimal_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_run(Path(tmp))
            run(["python3", "helpers/analyze_msprof_outputs.py", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            self.assertEqual(summary["headlines"]["op_summary"]["name"], "sanitized_kernel")
            self.assertEqual(summary["headlines"]["op_summary"]["value"], 42399.12)
            self.assertEqual(summary["headlines"]["task_time"]["name"], "sanitized_kernel")
            self.assertEqual(summary["headlines"]["op_basic_info"]["name"], "sanitized_operator_kernel")
            self.assertEqual(summary["files"]["memory"][0]["row_count"], 2)
            self.assertEqual(summary["headlines"]["memory"]["name"], "vector0")
            self.assertEqual(summary["headlines"]["memory"]["file"], "reports/OPPROF_001/Memory.csv")
            self.assertEqual(summary["headlines"]["memory"]["field"], "UB_to_GM_bw_usage_rate(%)")
            self.assertEqual(summary["headlines"]["memory"]["value"], 0.357273)
            self.assertEqual(summary["headlines"]["memory"]["field_kind"], "memory_usage_rate")

    def test_analyze_real_l2cache_minimal_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_l2cache_run(Path(tmp))
            run(["python3", "helpers/analyze_msprof_outputs.py", "--run-dir", str(run_dir)])
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

    def test_analyze_real_default_vector_minimal_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp))
            run(["python3", "helpers/analyze_msprof_outputs.py", "--run-dir", str(run_dir)])
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

    def test_analyze_source_shape_op_summary_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_summary_variant_run(Path(tmp))
            run(["python3", "helpers/analyze_msprof_outputs.py", "--run-dir", str(run_dir)])
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

    def test_simulator_hotspots_and_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp))
            run(["python3", "helpers/extract_simulator_hotspots.py", "--run-dir", str(run_dir)])
            run(["python3", "helpers/plot_timeline.py", "--run-dir", str(run_dir)])
            hotspots = (run_dir / "analysis" / "simulator_hotspots.txt").read_text()
            self.assertIn("mock_kernel.cpp:42", hotspots)
            self.assertNotIn("<unknown>", hotspots)
            timeline = timeline_text(run_dir)
            self.assertIn("MockMatMul", timeline)
            self.assertIn("aclrtSynchronizeStream", timeline)
            self.assertIn("msprof_001.json", timeline)

    def test_timeline_trace_events_object_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp))
            run(["python3", "helpers/plot_timeline.py", "--run-dir", str(run_dir)])
            timeline = timeline_text(run_dir)
            self.assertIn("| 120.5 | msprof_001.json | MockMatMul |", timeline)
            self.assertIn("| 8 | msprof_001.json | aclrtSynchronizeStream |", timeline)

    def test_timeline_real_cann_top_level_array(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_run(Path(tmp))
            run(["python3", "helpers/plot_timeline.py", "--run-dir", str(run_dir)])
            timeline = timeline_text(run_dir)
            self.assertIn("| 42399.1 | msprof_001.json | sanitized_kernel |", timeline)
            self.assertIn("| 42001.4 | msprof_001.json | Runtime@DeviceSynchronize |", timeline)
            self.assertIn("| 42399.1 | msprof_001.json | Computing |", timeline)

    def test_real_cann_minimal_missing_simulator_files_do_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_run(Path(tmp))
            run(["python3", "helpers/extract_simulator_hotspots.py", "--run-dir", str(run_dir)])
            run(["python3", "helpers/plot_timeline.py", "--run-dir", str(run_dir)])
            self.assertIn(
                "No core*_code_exe.csv files found.",
                (run_dir / "analysis" / "simulator_hotspots.txt").read_text(),
            )
            timeline = timeline_text(run_dir)
            self.assertIn("sanitized_kernel", timeline)
            self.assertIn("Runtime@DeviceSynchronize", timeline)

    def test_extract_real_simulator_minimal_trace_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_simulator_run(Path(tmp))
            run(["python3", "helpers/extract_simulator_hotspots.py", "--run-dir", str(run_dir)])
            text = (run_dir / "analysis" / "simulator_hotspots.txt").read_text()
            self.assertIn("No source-line rows with numeric timing fields found.", text)
            self.assertIn("- 5376: MOV_OUT_TO_UB", text)
            self.assertIn("- 5391: MOV_UB_TO_OUT", text)
            self.assertIn("## Trace Pipeline Context", text)
            self.assertIn("- displayTimeUnit: ns", text)
            self.assertIn("| 0.209 | 1 | MTE3 |", text)
            self.assertIn("| 0.154 | 1 | MTE2 |", text)
            self.assertIn("| 0.013 | 1 | VECTOR |", text)
            self.assertIn("## Trace Flow Categories", text)
            self.assertIn("| 2 | MTE2ToVECTOR |", text)
            self.assertIn("| 2 | VECTORToMTE3 |", text)
            self.assertNotIn("bottleneck", text.lower())
            self.assertNotIn("overlap %", text.lower())

    def test_compare_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_a = fresh_run(root / "a", "run_a")
            run_b = fresh_run(root / "b", "run_b")
            run(["python3", "helpers/analyze_msprof_outputs.py", "--run-dir", str(run_a)])
            run(["python3", "helpers/analyze_msprof_outputs.py", "--run-dir", str(run_b)])
            run([
                "python3",
                "helpers/compare_runs.py",
                "--run-dir-a",
                str(run_a),
                "--run-dir-b",
                str(run_b),
            ])
            outputs = list((run_b / "analysis").glob("compare_*.txt"))
            self.assertTrue(outputs)

    def test_generate_provenance_from_complete_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            reports_before = sorted(path.relative_to(run_dir).as_posix() for path in (run_dir / "reports").rglob("*"))
            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
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
            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual(provenance["cann_version"]["value"], "9.9")
            self.assertEqual(provenance["cann_version"]["source"]["artifact"], "logs/cann_version.cfg")
            self.assertEqual(provenance["cann_version"]["source"]["field"], "runtime_running_version")

    def test_generate_provenance_preserves_profile_output_artifact_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            (run_dir / "logs" / "msprof_default.stdout").write_text(
                (
                    "2026-05-30 19:11:37 [INFO]  Profiling results saved in "
                    "/data/code/ref/ascend-msprof-skill/profile/default/reports/"
                    "OPPROF_20260530191128_UARAJTADRTYKPBZQ\n"
                ),
                encoding="utf-8",
            )
            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
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
            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
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
            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
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
            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
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
            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
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
            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual(provenance["profile_date"]["value"], "2026-06-01 10:00:01")
            self.assertEqual(provenance["profile_date"]["source"]["artifact"], "logs/msprof_simulator_910b2.stdout")
            self.assertEqual(provenance["profile_output"]["value"], "reports/OPPROF_<sanitized>")
            self.assertEqual([item["value"] for item in provenance["profiler_status"]], ["0"])
            self.assertIn("logs/msprof_simulator_910b2.stdout", provenance["sources"])
            self.assertIn("logs/msprof_simulator_910b2.status", provenance["sources"])
            self.assertNotIn("logs/command_msprof.status", provenance["sources"])

    def test_generate_provenance_missing_logs_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            shutil.rmtree(run_dir / "logs")
            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            warnings = "\n".join(provenance["warnings"])

            self.assertIn("Missing logs/ directory", warnings)
            self.assertIn("Missing logs/cann_version.cfg", warnings)
            self.assertIn("Missing logs/npu_smi_info.stdout", warnings)
            self.assertNotIn("cann_version", provenance)
            self.assertTrue((run_dir / "reports").exists())

    def test_generate_report_from_existing_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp) / "profile", "mock_run")
            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
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

    def test_generate_report_empty_run_collects_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "empty_run"
            run_dir.mkdir(parents=True)
            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("**Run directory:** `profile/empty_run`", report)
            self.assertIn("No headline diagnosis generated", report)
            self.assertIn("Collect the missing profiler artifacts before changing kernel code.", report)
            self.assertNotIn("Inspect No headline diagnosis generated", report)

    def test_generate_report_surfaces_l2cache_without_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_l2cache_run(Path(tmp) / "profile", "real_l2cache_minimal")
            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            assert_l2cache_report_evidence(self, report)
            self.assertIn("No headline diagnosis generated", report)
            self.assertNotIn("bottleneck", report.lower())
            self.assertNotIn("Inspect L2 cache", report)
            self.assertNotIn(str(ROOT), report)

    def test_generate_report_surfaces_default_vector_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
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
            self.assertNotIn("Highest pipe utilization signal", report)
            self.assertNotIn("Highest memory signal", report)
            self.assertNotIn("Highest resource conflict signal", report)
            self.assertNotIn("Inspect Highest", report)
            self.assertNotIn("TimelineDetail", report)
            self.assertNotIn("bottleneck", report.lower())
            self.assertNotIn(str(ROOT), report)

    def test_generate_report_uses_provenance_without_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
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
            self.assertIn("python3 helpers/generate_provenance.py --run-dir <run-dir>", report)
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

    def test_generate_report_runs_analyzer_when_summary_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_run(Path(tmp))
            self.assertFalse((run_dir / "analysis" / "summary.json").exists())
            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertTrue((run_dir / "analysis" / "summary.json").exists())
            self.assertIn("# sanitized_operator_kernel Ascend Profiling Report", report)
            self.assertIn("reports/OPPROF_001/Memory.csv", report)
            self.assertIn("headlines.memory.field=UB_to_GM_bw_usage_rate(%)", report)
            self.assertIn("Optional analysis artifact missing: analysis/simulator_hotspots.txt", report)
            read = one_line_read(report)
            self.assertIn("reports/PROF_001/mindstudio_profiler_output/op_summary_001.csv", read)
            self.assertIn("headlines.op_summary.value", read)
            self.assertNotIn("highest available sourced headline", read)
            self.assertNotIn(str(ROOT), report)


if __name__ == "__main__":
    unittest.main()
