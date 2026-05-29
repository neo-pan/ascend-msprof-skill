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

    def test_generate_report_from_existing_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp) / "profile", "mock_run")
            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("# MockMatMul Ascend Profiling Report", report)
            self.assertIn("**Run directory:** `profile/mock_run`", report)
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
