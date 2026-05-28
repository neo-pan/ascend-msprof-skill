import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "mock_run"


def run(cmd, cwd=ROOT):
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True)


def fresh_run(parent: Path, name: str = "mock_run") -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    dst = parent / name
    shutil.copytree(FIXTURE, dst)
    return dst


class HelperTests(unittest.TestCase):
    def test_analyze_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp))
            run(["python3", "helpers/analyze_msprof_outputs.py", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            self.assertEqual(summary["headlines"]["op_summary"]["name"], "MockMatMul")
            self.assertEqual(summary["headlines"]["pipe_utilization"]["value"], 86.0)
            self.assertTrue((run_dir / "analysis" / "key_metrics.txt").exists())

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


if __name__ == "__main__":
    unittest.main()
