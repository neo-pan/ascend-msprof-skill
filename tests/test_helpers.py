import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "mock_run"
REAL_FIXTURE = ROOT / "tests" / "fixtures" / "real_cann_minimal"


def run(cmd, cwd=ROOT):
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True)


def fresh_run(parent: Path, name: str = "mock_run") -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    dst = parent / name
    shutil.copytree(FIXTURE, dst)
    return dst


def fresh_real_run(parent: Path, name: str = "real_cann_minimal") -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    dst = parent / name
    shutil.copytree(REAL_FIXTURE, dst, ignore=shutil.ignore_patterns("analysis"))
    return dst


def one_line_read(report: str) -> str:
    return next(line for line in report.splitlines() if line.startswith("**One-line read:**"))


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

    def test_simulator_hotspots_and_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp))
            run(["python3", "helpers/extract_simulator_hotspots.py", "--run-dir", str(run_dir)])
            run(["python3", "helpers/plot_timeline.py", "--run-dir", str(run_dir)])
            self.assertIn(
                "mock_kernel.cpp:42",
                (run_dir / "analysis" / "simulator_hotspots.txt").read_text(),
            )
            self.assertIn("MockMatMul", (run_dir / "analysis" / "timeline.txt").read_text())

    def test_real_cann_minimal_missing_simulator_files_do_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_run(Path(tmp))
            run(["python3", "helpers/extract_simulator_hotspots.py", "--run-dir", str(run_dir)])
            run(["python3", "helpers/plot_timeline.py", "--run-dir", str(run_dir)])
            self.assertIn(
                "No core*_code_exe.csv files found.",
                (run_dir / "analysis" / "simulator_hotspots.txt").read_text(),
            )
            self.assertIn("sanitized_kernel", (run_dir / "analysis" / "timeline.txt").read_text())

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
            run_dir = fresh_run(Path(tmp))
            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("# MockMatMul Ascend Profiling Report", report)
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
