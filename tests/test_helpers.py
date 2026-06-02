import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

from analyze_msprof_outputs import (  # noqa: E402
    parse_occupancy_summary_stdout,
    parse_occupancy_summary_text,
    parse_roofline_summary_stdout,
    parse_roofline_summary_text,
    selected_profiler_stdout_paths,
    selected_roofline_stdout_paths,
)
from profile_tilelang_benchmark_run import collect_environment  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "mock_run"
REAL_FIXTURE = ROOT / "tests" / "fixtures" / "real_cann_minimal"
REAL_SIMULATOR_FIXTURE = ROOT / "tests" / "fixtures" / "real_simulator_minimal"
REAL_PMSAMPLING_SIMULATOR_FIXTURE = ROOT / "tests" / "fixtures" / "real_pmsampling_simulator_minimal"
REAL_RESOURCECONFLICT_SIMULATOR_FIXTURE = ROOT / "tests" / "fixtures" / "real_resourceconflict_simulator_minimal"
REAL_L2CACHE_FIXTURE = ROOT / "tests" / "fixtures" / "real_l2cache_minimal"
REAL_DEFAULT_VECTOR_FIXTURE = ROOT / "tests" / "fixtures" / "real_default_vector_minimal"
REAL_APP_OP_STDOUT_FIXTURE = ROOT / "tests" / "fixtures" / "real_app_op_stdout_minimal"
REAL_OCCUPANCY_STDOUT_FIXTURE = ROOT / "tests" / "fixtures" / "real_occupancy_stdout_minimal"
REAL_ROOFLINE_STDOUT_FIXTURE = ROOT / "tests" / "fixtures" / "real_roofline_stdout_minimal"


def run(cmd, cwd=ROOT):
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True)


def fresh_run(parent: Path, name: str = "mock_run") -> Path:
    return copy_fixture(FIXTURE, parent, name)


def fresh_real_run(parent: Path, name: str = "real_cann_minimal") -> Path:
    return copy_fixture(REAL_FIXTURE, parent, name, ignore_analysis=True)


def fresh_real_simulator_run(parent: Path, name: str = "real_simulator_minimal") -> Path:
    return copy_fixture(REAL_SIMULATOR_FIXTURE, parent, name, ignore_analysis=True)


def fresh_real_pmsampling_simulator_run(parent: Path, name: str = "real_pmsampling_simulator_minimal") -> Path:
    return copy_fixture(REAL_PMSAMPLING_SIMULATOR_FIXTURE, parent, name, ignore_analysis=True)


def fresh_real_resourceconflict_simulator_run(
    parent: Path, name: str = "real_resourceconflict_simulator_minimal"
) -> Path:
    return copy_fixture(REAL_RESOURCECONFLICT_SIMULATOR_FIXTURE, parent, name, ignore_analysis=True)


def fresh_real_l2cache_run(parent: Path, name: str = "real_l2cache_minimal") -> Path:
    return copy_fixture(REAL_L2CACHE_FIXTURE, parent, name, ignore_analysis=True)


def fresh_real_default_vector_run(parent: Path, name: str = "real_default_vector_minimal") -> Path:
    return copy_fixture(REAL_DEFAULT_VECTOR_FIXTURE, parent, name, ignore_analysis=True)


def fresh_real_app_op_stdout_run(parent: Path, name: str = "real_app_op_stdout_minimal") -> Path:
    return copy_fixture(REAL_APP_OP_STDOUT_FIXTURE, parent, name, ignore_analysis=True)


def fresh_real_occupancy_stdout_run(parent: Path, name: str = "real_occupancy_stdout_minimal") -> Path:
    return copy_fixture(REAL_OCCUPANCY_STDOUT_FIXTURE, parent, name, ignore_analysis=True)


def fresh_real_roofline_stdout_run(parent: Path, name: str = "real_roofline_stdout_minimal") -> Path:
    return copy_fixture(REAL_ROOFLINE_STDOUT_FIXTURE, parent, name, ignore_analysis=True)


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


def write_tilelang_inputs(parent: Path) -> tuple[Path, Path]:
    payload = parent / "tilelang_kernel_payload.py"
    payload.write_text(
        (
            "def kernel_payload():\n"
            "    return {'op': 'generic_tilelang_kernel', 'tile_m': 64, 'tile_n': 32}\n"
        ),
        encoding="utf-8",
    )
    benchmark = parent / "tilelang_benchmark_result.json"
    benchmark.write_text(
        json.dumps(
            {
                "compiled": True,
                "correctness": {
                    "passed": True,
                    "max_abs_error": 0.000244,
                    "max_rel_error": 0.001953,
                },
                "runtime": 1.23,
                "runtime_stats": {
                    "min_ms": 1.2,
                    "mean_ms": 1.25,
                    "p50_ms": 1.24,
                },
                "ref_runtime": 4.92,
                "speedup": 4.0,
                "metadata": {
                    "workload_id": "tilelang-ascend/kernel/v1/4096x2048-f16-cases2",
                    "workload_shape": [4096, 2048],
                    "workload_dtype": "float16",
                    "workload_cases": 2,
                    "jit_config": {"num_warps": 4, "pipeline_depth": 3},
                },
                "error": None,
            }
        ),
        encoding="utf-8",
    )
    return payload, benchmark


def reports_file_snapshot(run_dir: Path) -> dict[str, bytes]:
    reports_dir = run_dir / "reports"
    if not reports_dir.exists():
        return {}
    return {
        path.relative_to(reports_dir).as_posix(): path.read_bytes()
        for path in sorted(candidate for candidate in reports_dir.rglob("*") if candidate.is_file())
    }


def write_fake_tilelang_benchmark_repo(parent: Path) -> tuple[Path, Path]:
    repo = parent / "tilelang-ascend-benchmark"
    package = repo / "ascend_svd_benchmark"
    examples = repo / "examples"
    package.mkdir(parents=True)
    examples.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    payload = examples / "kernel_payload_baseline.py"
    payload.write_text("def fake_payload():\n    return 'payload'\n", encoding="utf-8")
    (package / "runner.py").write_text(
        (
            "import argparse\n"
            "import json\n"
            "import os\n"
            "import sys\n"
            "\n"
            "def build_result(args):\n"
            "    phase = os.environ.get('TILELANG_PROFILE_PHASE', 'canonical')\n"
            "    if phase == 'op_profile':\n"
            "        if os.environ.get('FAKE_OP_CORRECTNESS_DICT_FAILURE') == '1':\n"
            "            return {\n"
            "                'compiled': True,\n"
            "                'correctness': {'passed': False, 'max_abs_error': 9.0},\n"
            "                'runtime': 9.99,\n"
            "                'runtime_stats': {'mean_ms': 9.99, 'min_ms': 9.99},\n"
            "                'ref_runtime': args.baseline_ms,\n"
            "                'speedup': None,\n"
            "                'metadata': {\n"
            "                    'task': args.task,\n"
            "                    'workload_id': 'tilelang-ascend/fake/op-profile',\n"
            "                    'workload_shape': [64, 64],\n"
            "                    'workload_dtype': 'float16',\n"
            "                    'workload_cases': 1,\n"
            "                    'kernel_payload_src': os.path.abspath(args.kernel_payload_src),\n"
            "                    'warmups': args.warmups,\n"
            "                    'repeats': args.repeats,\n"
            "                },\n"
            "                'error': {'stage': 'correctness', 'message': 'op-profile correctness failed'},\n"
            "            }\n"
            "        if os.environ.get('FAKE_OP_WORKER_FAILURE') == '1':\n"
            "            return {\n"
            "                'compiled': False,\n"
            "                'correctness': False,\n"
            "                'runtime': None,\n"
            "                'runtime_stats': None,\n"
            "                'ref_runtime': args.baseline_ms,\n"
            "                'speedup': None,\n"
            "                'metadata': {\n"
            "                    'task': args.task,\n"
            "                    'workload_id': 'tilelang-ascend/fake/op-profile',\n"
            "                    'workload_shape': [64, 64],\n"
            "                    'workload_dtype': 'float16',\n"
            "                    'workload_cases': 1,\n"
            "                    'kernel_payload_src': os.path.abspath(args.kernel_payload_src),\n"
            "                    'warmups': args.warmups,\n"
            "                    'repeats': args.repeats,\n"
            "                },\n"
            "                'error': {'stage': 'worker', 'message': 'worker returned invalid JSON'},\n"
            "            }\n"
            "        return {\n"
            "            'compiled': True,\n"
            "            'correctness': {'passed': True, 'max_abs_error': 0.001},\n"
            "            'runtime': 3.44,\n"
            "            'runtime_stats': {'mean_ms': 3.44, 'min_ms': 3.44},\n"
            "            'ref_runtime': args.baseline_ms,\n"
            "            'speedup': None if not args.baseline_ms else args.baseline_ms / 3.44,\n"
            "            'metadata': {\n"
            "                'task': args.task,\n"
            "                'workload_id': 'tilelang-ascend/fake/op-profile',\n"
            "                'workload_shape': [64, 64],\n"
            "                'workload_dtype': 'float16',\n"
            "                'workload_cases': 1,\n"
            "                'kernel_payload_src': os.path.abspath(args.kernel_payload_src),\n"
            "                'warmups': args.warmups,\n"
            "                'repeats': args.repeats,\n"
            "            },\n"
            "            'error': None,\n"
            "        }\n"
            "    if phase == 'app_profile' and os.environ.get('FAKE_APP_PROFILE_CORRECTNESS_FAILURE') == '1':\n"
            "        return {\n"
            "            'compiled': True,\n"
            "            'correctness': {'passed': False, 'max_abs_error': 7.0},\n"
            "            'runtime': 8.88,\n"
            "            'runtime_stats': {'mean_ms': 8.88, 'min_ms': 8.88},\n"
            "            'ref_runtime': args.baseline_ms,\n"
            "            'speedup': None,\n"
            "            'metadata': {\n"
            "                'task': args.task,\n"
            "                'workload_id': 'tilelang-ascend/fake/app-profile',\n"
            "                'workload_shape': [64, 64],\n"
            "                'workload_dtype': 'float16',\n"
            "                'workload_cases': 1,\n"
            "                'kernel_payload_src': os.path.abspath(args.kernel_payload_src),\n"
            "                'warmups': args.warmups,\n"
            "                'repeats': args.repeats,\n"
            "            },\n"
            "            'error': {'stage': 'correctness', 'message': 'app-profile correctness failed'},\n"
            "        }\n"
            "    runtime = 3.33 if phase == 'app_profile' else 0.77\n"
            "    return {\n"
            "        'compiled': True,\n"
            "        'correctness': {'passed': True, 'max_abs_error': 0.001},\n"
            "        'runtime': runtime,\n"
            "        'runtime_stats': {'mean_ms': runtime, 'min_ms': runtime},\n"
            "        'ref_runtime': args.baseline_ms,\n"
            "        'speedup': None if not args.baseline_ms else args.baseline_ms / runtime,\n"
            "        'metadata': {\n"
            "            'task': args.task,\n"
            "            'workload_id': 'tilelang-ascend/fake/svd',\n"
            "            'workload_shape': [64, 64],\n"
            "            'workload_dtype': 'float16',\n"
            "            'workload_cases': 1,\n"
            "            'kernel_payload_src': os.path.abspath(args.kernel_payload_src),\n"
            "            'warmups': args.warmups,\n"
            "            'repeats': args.repeats,\n"
            "            'baseline_override_ms': args.baseline_ms,\n"
            "        },\n"
            "        'error': None,\n"
            "    }\n"
            "\n"
            "def main():\n"
            "    ap = argparse.ArgumentParser()\n"
            "    ap.add_argument('--task', default='svd')\n"
            "    ap.add_argument('--kernel-payload-src', required=True)\n"
            "    ap.add_argument('--output')\n"
            "    ap.add_argument('--warmups', type=int, default=0)\n"
            "    ap.add_argument('--repeats', type=int, default=1)\n"
            "    ap.add_argument('--timeout-s', type=float, default=300.0)\n"
            "    ap.add_argument('--baseline-ms', type=float)\n"
            "    ap.add_argument('--baseline-std-ms', type=float)\n"
            "    ap.add_argument('--jit-debug-root')\n"
            "    ap.add_argument('--jit-verbose', action='store_true')\n"
            "    args = ap.parse_args()\n"
            "    result = build_result(args)\n"
            "    if args.output:\n"
            "        os.makedirs(os.path.dirname(args.output), exist_ok=True)\n"
            "        with open(args.output, 'w', encoding='utf-8') as f:\n"
            "            json.dump(result, f, indent=2, sort_keys=True)\n"
            "            f.write('\\n')\n"
            "    if os.environ.get('TILELANG_PROFILE_PHASE') == 'op_profile':\n"
            "        sys.stdout.write('2026-06-02 10:11:17 [INFO]  Op profiling analysis start.\\n')\n"
            "    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + '\\n')\n"
            "    correctness = result.get('correctness')\n"
            "    if isinstance(correctness, dict) and 'passed' in correctness:\n"
            "        correctness_ok = bool(correctness['passed'])\n"
            "    else:\n"
            "        correctness_ok = bool(correctness)\n"
            "    return 0 if result['compiled'] and correctness_ok and result['runtime'] is not None else 1\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    raise SystemExit(main())\n"
        ),
        encoding="utf-8",
    )
    return repo, payload


def write_fake_msprof(path: Path) -> Path:
    path.write_text(
        (
            "#!/usr/bin/env python3\n"
            "import os\n"
            "import subprocess\n"
            "import sys\n"
            "from pathlib import Path\n"
            "\n"
            "args = sys.argv[1:]\n"
            "is_op = bool(args and args[0] == 'op')\n"
            "\n"
            "def option_value(name):\n"
            "    prefix = name + '='\n"
            "    for index, arg in enumerate(args):\n"
            "        if arg.startswith(prefix):\n"
            "            return arg.split('=', 1)[1]\n"
            "        if arg == name and index + 1 < len(args):\n"
            "            return args[index + 1]\n"
            "    raise SystemExit(f'missing {name}')\n"
            "\n"
            "out = Path(option_value('--output'))\n"
            "app = option_value('--application')\n"
            "out.mkdir(parents=True, exist_ok=True)\n"
            "child = subprocess.run([app], capture_output=True, text=True)\n"
            "print('2026-05-31 13:04:28 [INFO]  Profiling start')\n"
            "sys.stdout.write(child.stdout)\n"
            "sys.stderr.write(child.stderr)\n"
            "if is_op:\n"
            "    if os.environ.get('FAKE_MSPROF_SKIP_OP') != '1':\n"
            "        prof = out / 'OPPROF_001'\n"
            "        prof.mkdir(parents=True, exist_ok=True)\n"
            "        (prof / 'OpBasicInfo.csv').write_text('Op Name,Task Duration(us)\\nop_kernel,10\\n', encoding='utf-8')\n"
            "        (prof / 'PipeUtilization.csv').write_text('Pipe,Utilization(%)\\nVector,83\\n', encoding='utf-8')\n"
            "        print(f'2026-05-31 13:04:31 [INFO]  Profiling results saved in {prof}')\n"
            "else:\n"
            "    if os.environ.get('FAKE_MSPROF_SKIP_APP') != '1':\n"
            "        prof = out / 'PROF_001' / 'mindstudio_profiler_output'\n"
            "        prof.mkdir(parents=True, exist_ok=True)\n"
            "        (prof / 'op_summary_001.csv').write_text('Op Name,Task Duration(us)\\napp_kernel,42\\n', encoding='utf-8')\n"
            "        (prof / 'task_time_001.csv').write_text('Task Name,Task Duration(us)\\ntask_kernel,21\\n', encoding='utf-8')\n"
            "        (prof / 'api_statistic_001.csv').write_text('API Name,Time(us)\\naclrtSynchronizeStream,5\\n', encoding='utf-8')\n"
            "        (prof / 'msprof_001.json').write_text('{\"traceEvents\":[{\"name\":\"app_kernel\",\"dur\":42}]}\\n', encoding='utf-8')\n"
            "        print(f'2026-05-31 13:04:30 [INFO]  Process profiling data complete. Data is saved in {prof.parent}')\n"
            "if is_op and os.environ.get('FAKE_MSPROF_OP_EXIT_ZERO') == '1':\n"
            "    raise SystemExit(0)\n"
            "if not is_op and os.environ.get('FAKE_MSPROF_APP_FORCE_ERROR') == '1':\n"
            "    raise SystemExit(7)\n"
            "if not is_op and os.environ.get('FAKE_MSPROF_APP_EXIT_ZERO') == '1':\n"
            "    raise SystemExit(0)\n"
            "raise SystemExit(child.returncode)\n"
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


class HelperTests(unittest.TestCase):
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
        )

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
        )

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
        )

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
        )

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

    def test_validate_covers_readme_tilelang_python_guidance(self):
        validate_text = (ROOT / "scripts" / "validate.py").read_text(encoding="utf-8")
        readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn('"README.md", "SKILL.md", "reference/01-workflow.md", "helpers/README.md"', validate_text)
        self.assertIn("--python-bin", readme_text)
        self.assertIn("confirm the benchmark repository's", readme_text)
        self.assertNotRegex(readme_text, r"/(?:[^\s`'\"<>|]+/)*\.venv/bin/python")

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
            self.assertIsNone(summary["stdout_sections"]["occupancy_summary"])
            self.assertFalse(any("occupancy" in warning.lower() for warning in summary["warnings"]))
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

    def test_analyze_real_occupancy_stdout_summary_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_occupancy_stdout_run(Path(tmp))
            run(["python3", "helpers/analyze_msprof_outputs.py", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            occupancy = summary["stdout_sections"]["occupancy_summary"]
            key_metrics = (run_dir / "analysis" / "key_metrics.txt").read_text()

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
            self.assertIn("## Occupancy Summary", key_metrics)
            self.assertIn("| 1 | core3 vector0 took more time than other vector cores. | logs/msprof_occupancy.stdout |", key_metrics)

    def test_analyze_real_roofline_stdout_summary_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_roofline_stdout_run(Path(tmp))
            run(["python3", "helpers/analyze_msprof_outputs.py", "--run-dir", str(run_dir)])
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
            run(["python3", "helpers/extract_simulator_hotspots.py", "--run-dir", str(run_dir)])
            text = (run_dir / "analysis" / "simulator_hotspots.txt").read_text()
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
            for forbidden in ["bottleneck", "diagnosis", "optimization", "advice"]:
                self.assertNotIn(forbidden, text.lower())

    def test_extract_pmsampling_mte_throughput_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_pmsampling_simulator_run(Path(tmp))
            run(["python3", "helpers/extract_simulator_hotspots.py", "--run-dir", str(run_dir)])
            text = (run_dir / "analysis" / "simulator_hotspots.txt").read_text()
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
            for forbidden in ["bottleneck", "diagnosis", "optimization", "advice"]:
                self.assertNotIn(forbidden, text.lower())

    def test_pmsampling_mte_throughput_top_sorts_by_throughput(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_pmsampling_simulator_run(Path(tmp))
            run(["python3", "helpers/extract_simulator_hotspots.py", "--run-dir", str(run_dir), "--top", "3"])
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

    def test_collect_environment_prefers_invoked_msprof_version_cfg(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            invoked_toolkit = root / "invoked-toolkit"
            env_toolkit = root / "env-toolkit"
            logs = root / "logs"
            msprof = invoked_toolkit / "bin" / "msprof"
            msprof.parent.mkdir(parents=True)
            env_toolkit.mkdir()
            logs.mkdir()
            msprof.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
            msprof.chmod(0o755)
            (invoked_toolkit / "version.cfg").write_text(
                "toolkit_running_version=[invoked-msprof-version]\n",
                encoding="utf-8",
            )
            (env_toolkit / "version.cfg").write_text(
                "toolkit_running_version=[env-root-version]\n",
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"ASCEND_TOOLKIT_HOME": str(env_toolkit)}, clear=False):
                collect_environment(logs, str(msprof))

            self.assertIn(
                "toolkit_running_version=[invoked-msprof-version]",
                (logs / "cann_version.cfg").read_text(encoding="utf-8"),
            )
            self.assertNotIn(
                "env-root-version",
                (logs / "cann_version.cfg").read_text(encoding="utf-8"),
            )

    def test_generate_provenance_preserves_profile_output_artifact_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            (run_dir / "logs" / "msprof_default.stdout").write_text(
                (
                    "2026-05-30 19:11:37 [INFO]  Profiling results saved in "
                    "/opt/profiler-runs/ascend-msprof-skill/profile/default/reports/"
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

    def test_generate_provenance_prefers_legacy_msprof_before_msprof_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "legacy_msprof_with_op"
            logs = run_dir / "logs"
            reports = run_dir / "reports"
            logs.mkdir(parents=True)
            (reports / "app").mkdir(parents=True)
            (reports / "op").mkdir(parents=True)
            (logs / "msprof.stdout").write_text(
                (
                    "2026-06-02 10:00:01 [INFO]  Legacy app profiling start.\n"
                    f"2026-06-02 10:00:09 [INFO]  Profiling results saved in {reports / 'app'}\n"
                ),
                encoding="utf-8",
            )
            (logs / "msprof.status").write_text("0\n", encoding="utf-8")
            (logs / "msprof_op.stdout").write_text(
                (
                    "2026-06-02 10:01:01 [INFO]  Op profiling start.\n"
                    f"2026-06-02 10:01:09 [INFO]  Profiling results saved in {reports / 'op'}\n"
                ),
                encoding="utf-8",
            )
            (logs / "msprof_op.status").write_text("0\n", encoding="utf-8")

            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual(provenance["profile_date"]["value"], "2026-06-02 10:00:01")
            self.assertEqual(provenance["profile_date"]["source"]["artifact"], "logs/msprof.stdout")
            self.assertEqual(provenance["profile_output"]["value"], "reports/app")
            self.assertEqual(provenance["profile_output"]["source"]["artifact"], "logs/msprof.stdout")
            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/app", "reports/op"])
            self.assertEqual(
                [item["source"]["artifact"] for item in provenance["profiler_status"]],
                ["logs/msprof.status", "logs/msprof_op.status"],
            )

    def test_generate_provenance_prefers_command_msprof_before_msprof_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "legacy_command_msprof_with_op"
            logs = run_dir / "logs"
            reports = run_dir / "reports"
            logs.mkdir(parents=True)
            (reports / "app").mkdir(parents=True)
            (reports / "op").mkdir(parents=True)
            (logs / "command_msprof.stdout").write_text(
                (
                    "2026-06-02 10:20:01 [INFO]  Legacy command app profiling start.\n"
                    f"2026-06-02 10:20:09 [INFO]  Profiling results saved in {reports / 'app'}\n"
                ),
                encoding="utf-8",
            )
            (logs / "command_msprof.status").write_text("0\n", encoding="utf-8")
            (logs / "msprof_op.stdout").write_text(
                (
                    "2026-06-02 10:21:01 [INFO]  Op profiling start.\n"
                    f"2026-06-02 10:21:09 [INFO]  Profiling results saved in {reports / 'op'}\n"
                ),
                encoding="utf-8",
            )
            (logs / "msprof_op.status").write_text("0\n", encoding="utf-8")

            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual(provenance["profile_date"]["value"], "2026-06-02 10:20:01")
            self.assertEqual(provenance["profile_date"]["source"]["artifact"], "logs/command_msprof.stdout")
            self.assertEqual(provenance["profile_output"]["value"], "reports/app")
            self.assertEqual(provenance["profile_output"]["source"]["artifact"], "logs/command_msprof.stdout")
            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/app", "reports/op"])
            self.assertEqual(
                [item["source"]["artifact"] for item in provenance["profiler_status"]],
                ["logs/command_msprof.status", "logs/msprof_op.status"],
            )

    def test_generate_provenance_infers_outputs_without_profiler_stdout_or_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "missing_profiler_logs"
            logs = run_dir / "logs"
            reports = run_dir / "reports"
            logs.mkdir(parents=True)
            (reports / "app").mkdir(parents=True)
            (reports / "op").mkdir(parents=True)
            (logs / "command_msprof.txt").write_text(
                f"msprof --output={reports / 'app'} --application={run_dir / 'harness' / 'app.sh'}\n",
                encoding="utf-8",
            )
            (logs / "command_msprof_op.txt").write_text(
                f"msprof op --output={reports / 'op'} --application={run_dir / 'harness' / 'op.sh'}\n",
                encoding="utf-8",
            )

            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/app", "reports/op"])
            self.assertEqual(provenance["profile_output"]["value"], "reports/app")
            self.assertIn("Missing profiler stdout/status logs", "\n".join(provenance["warnings"]))

            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("- Profile outputs: app: reports/app (source: `logs/command_msprof.txt`; `--output`)", report)
            self.assertIn("reports/op (source: `logs/command_msprof_op.txt`; `--output`)", report)
            self.assertNotIn("- Profile output: not recorded", report)

    def test_generate_provenance_infers_outputs_from_multiline_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "multiline_command_logs"
            logs = run_dir / "logs"
            reports = run_dir / "reports"
            logs.mkdir(parents=True)
            (reports / "app").mkdir(parents=True)
            (reports / "op").mkdir(parents=True)
            (logs / "command_msprof.txt").write_text(
                (
                    "msprof \\\n"
                    f"  --output={reports / 'app'} \\\n"
                    f"  --application={run_dir / 'harness' / 'app.sh'}\n"
                ),
                encoding="utf-8",
            )
            (logs / "command_msprof_op.txt").write_text(
                (
                    "msprof op \\\n"
                    f"  --output={reports / 'op'} \\\n"
                    f"  --application={run_dir / 'harness' / 'op.sh'}\n"
                ),
                encoding="utf-8",
            )

            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/app", "reports/op"])
            self.assertEqual(provenance["profile_output"]["value"], "reports/app")
            self.assertEqual(provenance["profile_command"]["value"], "msprof --output=reports/app --application=<abs-path>")
            self.assertNotIn("\\", provenance["profile_command"]["value"])

            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("- Profile outputs: app: reports/app (source: `logs/command_msprof.txt`; `--output`)", report)
            self.assertIn("reports/op (source: `logs/command_msprof_op.txt`; `--output`)", report)
            self.assertNotIn("- Profile output: not recorded", report)

    def test_generate_provenance_does_not_infer_empty_report_dirs_as_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "empty_report_dirs"
            (run_dir / "logs").mkdir(parents=True)
            (run_dir / "reports" / "app").mkdir(parents=True)
            (run_dir / "reports" / "op").mkdir(parents=True)

            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertNotIn("profile_output", provenance)
            self.assertNotIn("profile_outputs", provenance)
            self.assertIn("Missing profiler stdout/status logs", "\n".join(provenance["warnings"]))

            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("- Profile output: not recorded", report)

    def test_generate_provenance_infers_nonempty_report_dirs_without_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "nonempty_report_dirs"
            app_prof = run_dir / "reports" / "app" / "PROF_001" / "mindstudio_profiler_output"
            op_prof = run_dir / "reports" / "op" / "OPPROF_001"
            (run_dir / "logs").mkdir(parents=True)
            app_prof.mkdir(parents=True)
            op_prof.mkdir(parents=True)
            (app_prof / "op_summary_001.csv").write_text("Op Name,Task Duration(us)\napp_kernel,1\n", encoding="utf-8")
            (op_prof / "OpBasicInfo.csv").write_text("Op Name,Task Duration(us)\nop_kernel,1\n", encoding="utf-8")

            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/app", "reports/op"])
            self.assertEqual(provenance["profile_outputs"][0]["source"]["field"], "existing_report_dir")
            self.assertEqual(provenance["profile_outputs"][1]["source"]["field"], "existing_report_dir")
            self.assertEqual(provenance["profile_output_segments"]["app"]["output"]["value"], "reports/app")
            self.assertEqual(
                provenance["profile_output_segments"]["app"]["output"]["source"]["field"],
                "existing_report_dir",
            )
            self.assertEqual(provenance["profile_output_segments"]["op"]["output"]["value"], "reports/op")
            self.assertEqual(
                provenance["profile_output_segments"]["op"]["output"]["source"]["field"],
                "existing_report_dir",
            )

    def test_generate_provenance_records_app_op_statuses_and_inferred_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "tilelang_app_op"
            logs = run_dir / "logs"
            reports = run_dir / "reports"
            (reports / "app").mkdir(parents=True)
            (reports / "op").mkdir(parents=True)
            logs.mkdir(parents=True)
            (logs / "command_msprof.txt").write_text(
                f"msprof --output={reports / 'app'} --application={run_dir / 'harness' / 'app.sh'}\n",
                encoding="utf-8",
            )
            (logs / "command_msprof_op.txt").write_text(
                f"msprof op --output={reports / 'op'} --application={run_dir / 'harness' / 'op.sh'}\n",
                encoding="utf-8",
            )
            (logs / "msprof_default.stdout").write_text(
                "2026-06-02 09:00:01 [INFO]  App profiling start.\n",
                encoding="utf-8",
            )
            (logs / "msprof_default.status").write_text("0\n", encoding="utf-8")
            (logs / "msprof_op.stdout").write_text(
                "2026-06-02 09:00:11 [INFO]  Op profiling start.\n",
                encoding="utf-8",
            )
            (logs / "msprof_op.status").write_text("1\n", encoding="utf-8")
            (logs / "msprof_op_help.stdout").write_text(
                "2026-01-01 00:00:00 [INFO]  Profiling results saved in /tmp/help/reports/OPPROF_HELP\n",
                encoding="utf-8",
            )
            (logs / "msprof_op_help.status").write_text("9\n", encoding="utf-8")

            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual(provenance["profile_date"]["value"], "2026-06-02 09:00:01")
            self.assertEqual([item["value"] for item in provenance["profiler_status"]], ["0", "1"])
            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/app", "reports/op"])
            self.assertEqual(provenance["profile_output"]["value"], "reports/app")
            for source in [
                "logs/msprof_default.stdout",
                "logs/msprof_default.status",
                "logs/msprof_op.stdout",
                "logs/msprof_op.status",
                "logs/command_msprof_op.txt",
            ]:
                self.assertIn(source, provenance["sources"])
            self.assertNotIn("logs/msprof_op_help.stdout", provenance["sources"])
            self.assertNotIn("logs/msprof_op_help.status", provenance["sources"])

    def test_generate_provenance_records_app_op_output_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "tilelang_app_op_segments"
            logs = run_dir / "logs"
            reports = run_dir / "reports"
            (reports / "app").mkdir(parents=True)
            (reports / "op").mkdir(parents=True)
            logs.mkdir(parents=True)
            (logs / "command_msprof.txt").write_text(
                f"msprof --output={reports / 'app'} --application={run_dir / 'harness' / 'app.sh'}\n",
                encoding="utf-8",
            )
            (logs / "command_msprof_op.txt").write_text(
                f"msprof op --output={reports / 'op'} --application={run_dir / 'harness' / 'op.sh'}\n",
                encoding="utf-8",
            )
            (logs / "msprof_default.stdout").write_text(
                (
                    "2026-06-02 09:00:01 [INFO]  App profiling start.\n"
                    "2026-06-02 09:00:09 [INFO]  Process profiling data complete. Data is saved in "
                    f"{reports / 'app' / 'PROF_000001_20260602090001_APPAPPAPP'}\n"
                ),
                encoding="utf-8",
            )
            (logs / "msprof_default.status").write_text("0\n", encoding="utf-8")
            (logs / "msprof_op.stdout").write_text(
                (
                    "2026-06-02 09:00:11 [INFO]  Op profiling start.\n"
                    "2026-06-02 09:00:19 [INFO]  Profiling results saved in "
                    f"{reports / 'op' / 'OPPROF_20260602090011_OPOPOPOP'}\n"
                ),
                encoding="utf-8",
            )
            (logs / "msprof_op.status").write_text("0\n", encoding="utf-8")

            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            segments = provenance["profile_output_segments"]

            self.assertEqual(segments["app"]["output"]["value"], "reports/app")
            self.assertEqual(segments["app"]["output"]["source"]["artifact"], "logs/command_msprof.txt")
            self.assertEqual(segments["app"]["output"]["source"]["field"], "--output")
            self.assertEqual(segments["app"]["resolved_output"]["value"], "reports/app/PROF_<sanitized>")
            self.assertEqual(
                segments["app"]["resolved_output"]["source"]["artifact"],
                "logs/msprof_default.stdout",
            )
            self.assertEqual(
                segments["app"]["resolved_output"]["source"]["field"],
                "Data is saved in",
            )
            self.assertEqual(segments["op"]["output"]["value"], "reports/op")
            self.assertEqual(segments["op"]["output"]["source"]["artifact"], "logs/command_msprof_op.txt")
            self.assertEqual(segments["op"]["output"]["source"]["field"], "--output")
            self.assertEqual(segments["op"]["resolved_output"]["value"], "reports/op/OPPROF_<sanitized>")
            self.assertEqual(segments["op"]["resolved_output"]["source"]["artifact"], "logs/msprof_op.stdout")
            self.assertEqual(
                segments["op"]["resolved_output"]["source"]["field"],
                "Profiling results saved in",
            )
            self.assertEqual(provenance["profile_output"]["value"], "reports/app/PROF_<sanitized>")

            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("- Profile outputs: app: reports/app", report)
            self.assertIn("resolved reports/app/PROF_<sanitized>", report)
            self.assertIn("op: reports/op", report)
            self.assertIn("resolved reports/op/OPPROF_<sanitized>", report)
            self.assertNotIn("- Profile output: reports/app/PROF_<sanitized>, reports/op/OPPROF_<sanitized>", report)

    def test_real_app_op_stdout_fixture_records_segmented_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_app_op_stdout_run(Path(tmp) / "profile")
            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            segments = provenance["profile_output_segments"]

            self.assertEqual(segments["app"]["output"]["value"], "reports/app")
            self.assertEqual(segments["app"]["output"]["source"]["artifact"], "logs/command_msprof.txt")
            self.assertEqual(segments["app"]["resolved_output"]["value"], "reports/app/PROF_<sanitized>")
            self.assertEqual(segments["app"]["resolved_output"]["source"]["field"], "Data is saved in")
            self.assertEqual(segments["op"]["output"]["value"], "reports/op")
            self.assertEqual(segments["op"]["output"]["source"]["artifact"], "logs/command_msprof_op.txt")
            self.assertEqual(segments["op"]["resolved_output"]["value"], "reports/op/OPPROF_<sanitized>")
            self.assertEqual(segments["op"]["resolved_output"]["source"]["field"], "Profiling results saved in")
            self.assertEqual(provenance["profile_output"]["value"], "reports/app/PROF_<sanitized>")
            self.assertEqual(
                [item["value"] for item in provenance["profile_outputs"]],
                ["reports/app/PROF_<sanitized>", "reports/op/OPPROF_<sanitized>", "reports/app", "reports/op"],
            )
            self.assertNotIn("APPHASH1", json.dumps(provenance, sort_keys=True))
            self.assertNotIn("OPHASH12", json.dumps(provenance, sort_keys=True))

            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("- Profile outputs: app: reports/app", report)
            self.assertIn("resolved reports/app/PROF_<sanitized>", report)
            self.assertIn("op: reports/op", report)
            self.assertIn("resolved reports/op/OPPROF_<sanitized>", report)
            self.assertNotIn("- Profile output: reports/app/PROF_<sanitized>", report)

    def test_generate_provenance_merges_mixed_stdout_and_command_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "tilelang_mixed_outputs"
            logs = run_dir / "logs"
            reports = run_dir / "reports"
            (reports / "app").mkdir(parents=True)
            (reports / "op").mkdir(parents=True)
            logs.mkdir(parents=True)
            (logs / "command_msprof.txt").write_text(
                f"msprof --output={reports / 'app'} --application={run_dir / 'harness' / 'app.sh'}\n",
                encoding="utf-8",
            )
            (logs / "command_msprof_op.txt").write_text(
                f"msprof op --output={reports / 'op'} --application={run_dir / 'harness' / 'op.sh'}\n",
                encoding="utf-8",
            )
            (logs / "msprof_default.stdout").write_text(
                (
                    "2026-06-02 09:10:01 [INFO]  App profiling start.\n"
                    f"2026-06-02 09:10:09 [INFO]  Profiling results saved in {reports / 'app'}\n"
                ),
                encoding="utf-8",
            )
            (logs / "msprof_default.status").write_text("0\n", encoding="utf-8")
            (logs / "msprof_op.stdout").write_text(
                "2026-06-02 09:10:11 [INFO]  Op profiling start.\n",
                encoding="utf-8",
            )
            (logs / "msprof_op.status").write_text("0\n", encoding="utf-8")

            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/app", "reports/op"])
            self.assertEqual(provenance["profile_output"]["value"], "reports/app")
            self.assertEqual(provenance["profile_output"]["source"]["artifact"], "logs/msprof_default.stdout")
            self.assertEqual(provenance["profile_outputs"][1]["source"]["artifact"], "logs/command_msprof_op.txt")

            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("- Profile outputs: app: reports/app (source: `logs/command_msprof.txt`; `--output`)", report)
            self.assertIn("resolved reports/app (source: `logs/msprof_default.stdout`", report)
            self.assertIn("reports/op (source: `logs/command_msprof_op.txt`; `--output`)", report)
            self.assertNotIn("- Profile output: not recorded", report)

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

    def test_generate_report_includes_app_op_correlation_without_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_app_op_stdout_run(Path(tmp) / "profile")
            run(["python3", "helpers/generate_provenance.py", "--run-dir", str(run_dir)])
            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            diagnosis = report.split("## 3. Diagnosis", 1)[1].split("## 4. Optimization Directions", 1)[0]

            self.assertIn("### App/Op Correlation", report)
            self.assertIn(
                "| App top operator | sanitized_app_kernel | 42.5 | "
                "`reports/app/PROF_000001_20260602101101_APPHASH1/mindstudio_profiler_output/op_summary_001.csv`; "
                "`headlines.op_summary.value; headlines.op_summary.raw_row.Task Duration(us); "
                "headlines.op_summary.field_kind=duration_or_time` |",
                report,
            )
            self.assertIn(
                "| App top task | sanitized_app_task | 43 | "
                "`reports/app/PROF_000001_20260602101101_APPHASH1/mindstudio_profiler_output/task_time_001.csv`; "
                "`headlines.task_time.value; headlines.task_time.raw_row.task_time(us); "
                "headlines.task_time.field_kind=duration_or_time` |",
                report,
            )
            self.assertIn(
                "| Op metadata | sanitized_op_kernel | 5.75 | "
                "`reports/op/OPPROF_20260602101111_OPHASH12/OpBasicInfo.csv`; "
                "`headlines.op_basic_info.value; headlines.op_basic_info.first_row.Task Duration(us); "
                "headlines.op_basic_info.field_kind=basic_info` |",
                report,
            )
            self.assertIn(
                "| Op pipe signal | vector0 / aiv_scalar_ratio | 0.5 | "
                "`reports/op/OPPROF_20260602101111_OPHASH12/PipeUtilization.csv`; "
                "`headlines.pipe_utilization.value; headlines.pipe_utilization.raw_row.aiv_scalar_ratio; "
                "headlines.pipe_utilization.field=aiv_scalar_ratio; headlines.pipe_utilization.field_kind=utilization_or_ratio` |",
                report,
            )
            self.assertNotIn("App/Op Correlation", diagnosis)
            self.assertNotIn("Op metadata", diagnosis)
            self.assertNotIn("sanitized_op_kernel", diagnosis)
            self.assertNotIn("aiv_scalar_ratio", diagnosis)
            self.assertNotIn("bottleneck", report.lower())

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

    def test_generate_report_surfaces_occupancy_summary_without_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_occupancy_stdout_run(Path(tmp) / "profile", "real_occupancy_stdout_minimal")
            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            diagnosis = report.split("## 3. Diagnosis", 1)[1].split("## 4. Optimization Directions", 1)[0]
            optimization = report.split("## 4. Optimization Directions", 1)[1].split("## 5. Confidence And Caveats", 1)[0]

            self.assertIn("### Occupancy Summary", report)
            self.assertIn(
                "| 1 | core3 vector0 took more time than other vector cores. | `logs/msprof_occupancy.stdout` |",
                report,
            )
            self.assertIn(
                "| 2 | core0 vector0 cache hit rate lower than other vector cores. | `logs/msprof_occupancy.stdout` |",
                report,
            )
            self.assertNotIn("Occupancy", diagnosis)
            self.assertNotIn("core3 vector0", diagnosis)
            self.assertNotIn("cache hit rate lower", diagnosis)
            self.assertNotIn("Occupancy", optimization)
            self.assertNotIn("core3 vector0", optimization)
            self.assertNotIn("cache hit rate lower", optimization)
            self.assertNotIn("bottleneck", report.lower())
            self.assertNotIn(str(ROOT), report)

    def test_generate_report_surfaces_roofline_summary_without_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_roofline_stdout_run(Path(tmp) / "profile", "real_roofline_stdout_minimal")
            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            diagnosis = report.split("## 3. Diagnosis", 1)[1].split("## 4. Optimization Directions", 1)[0]
            optimization = report.split("## 4. Optimization Directions", 1)[1].split("## 5. Confidence And Caveats", 1)[0]

            self.assertIn("### RoofLine Summary", report)
            self.assertIn(
                "| latency bound:pipeline caused | `logs/msprof_roofline.stdout` |",
                report,
            )
            self.assertNotIn("RoofLine", diagnosis)
            self.assertNotIn("Roofline", diagnosis)
            self.assertNotIn("latency bound", diagnosis)
            self.assertNotIn("pipeline caused", diagnosis)
            self.assertNotIn("RoofLine", optimization)
            self.assertNotIn("Roofline", optimization)
            self.assertNotIn("latency bound", optimization)
            self.assertNotIn("pipeline caused", optimization)
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

    def test_generate_report_prefers_profile_outputs_and_falls_back_to_profile_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp) / "profile", "mock_run")
            provenance_path = run_dir / "analysis" / "provenance.json"
            provenance_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_dir": "profile/mock_run",
                        "sources": ["logs/msprof_default.stdout", "logs/msprof_op.stdout"],
                        "warnings": [],
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
                            {
                                "value": "reports/app",
                                "source": {"artifact": "logs/command_msprof.txt", "field": "--output"},
                            },
                            {
                                "value": "reports/op",
                                "source": {"artifact": "logs/command_msprof_op.txt", "field": "--output"},
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
                                    "source": {
                                        "artifact": "logs/msprof_default.stdout",
                                        "field": "Profiling results saved in",
                                    },
                                },
                            },
                            "op": {
                                "output": {
                                    "value": "reports/op",
                                    "source": {"artifact": "logs/command_msprof_op.txt", "field": "--output"},
                                },
                                "resolved_output": {
                                    "value": "reports/op/OPPROF_<sanitized>",
                                    "source": {"artifact": "logs/msprof_op.stdout", "field": "Profiling results saved in"},
                                },
                            },
                        },
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")

            self.assertIn("- Profile outputs: app: reports/app (source: `logs/command_msprof.txt`; `--output`)", report)
            self.assertIn(
                "resolved reports/app/PROF_<sanitized> (source: `logs/msprof_default.stdout`; "
                "`Profiling results saved in`)",
                report,
            )
            self.assertIn("op: reports/op (source: `logs/command_msprof_op.txt`; `--output`)", report)
            self.assertIn(
                "resolved reports/op/OPPROF_<sanitized> (source: `logs/msprof_op.stdout`; "
                "`Profiling results saved in`)",
                report,
            )
            self.assertNotIn(
                "- Profile output: reports/app/PROF_<sanitized> (source: `logs/msprof_default.stdout`",
                report,
            )
            self.assertNotIn("reports/legacy", report)
            self.assertNotIn("- Profile output: not recorded", report)

            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance.pop("profile_output_segments")
            provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn(
                "- Profile output: reports/app/PROF_<sanitized> "
                "(source: `logs/msprof_default.stdout`; `Profiling results saved in`)",
                report,
            )
            self.assertIn("reports/op/OPPROF_<sanitized>", report)

            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance.pop("profile_outputs")
            provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("reports/legacy (source: `logs/legacy.stdout`; `Profiling results saved in`)", report)

    def test_collect_tilelang_context_writes_analysis_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = fresh_run(root / "profile", "tilelang_run")
            reports_before = reports_file_snapshot(run_dir)
            payload, benchmark = write_tilelang_inputs(root)
            jit_root = root / "tilelang-jit-debug"
            (jit_root / "module").mkdir(parents=True)
            (jit_root / "config.json").write_text('{"debug": true}\n', encoding="utf-8")
            (jit_root / "module" / "kernel.cce").write_text("// lowered kernel\n", encoding="utf-8")

            run([
                "python3",
                "helpers/collect_tilelang_context.py",
                "--run-dir",
                str(run_dir),
                "--payload-src",
                str(payload),
                "--benchmark-json",
                str(benchmark),
                "--jit-debug-root",
                str(jit_root),
            ])
            context = json.loads((run_dir / "analysis" / "tilelang_context.json").read_text(encoding="utf-8"))

            self.assertEqual(context["schema_version"], 1)
            self.assertEqual(context["sources"]["payload"]["artifact"], "tilelang_kernel_payload.py")
            self.assertIn("def kernel_payload", context["sources"]["payload"]["content"])
            self.assertEqual(
                context["benchmark"]["workload"]["id"],
                "tilelang-ascend/kernel/v1/4096x2048-f16-cases2",
            )
            self.assertEqual(context["benchmark"]["workload"]["shape"], [4096, 2048])
            self.assertEqual(context["benchmark"]["workload"]["dtype"], "float16")
            self.assertEqual(context["benchmark"]["workload"]["case_count"], 2)
            self.assertEqual(context["benchmark"]["candidate"]["runtime_stats"]["mean_ms"], 1.25)
            self.assertEqual(context["benchmark"]["correctness"]["maxima"][0]["field"], "max_abs_error")
            self.assertEqual(context["jit_debug"]["artifact_count"], 2)
            self.assertEqual(context["warnings"], [])
            self.assertTrue((run_dir / "reports").exists())
            self.assertEqual(reports_before, reports_file_snapshot(run_dir))

    def test_collect_tilelang_context_missing_jit_debug_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = fresh_run(root / "profile", "tilelang_run")
            payload, benchmark = write_tilelang_inputs(root)
            missing_debug = root / "missing-jit-debug"

            result = subprocess.run(
                [
                    "python3",
                    "helpers/collect_tilelang_context.py",
                    "--run-dir",
                    str(run_dir),
                    "--payload-src",
                    str(payload),
                    "--benchmark-json",
                    str(benchmark),
                    "--jit-debug-root",
                    str(missing_debug),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            context = json.loads((run_dir / "analysis" / "tilelang_context.json").read_text(encoding="utf-8"))

            self.assertIn("warning: Optional JIT debug root missing: missing-jit-debug", result.stderr)
            self.assertEqual(context["jit_debug"]["provided"], "missing-jit-debug")
            self.assertFalse(context["jit_debug"]["found"])
            self.assertIn("Optional JIT debug root missing: missing-jit-debug", context["warnings"])

    def test_prepare_tilelang_profile_run_creates_layout_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "profile" / "tilelang_kernel"
            payload, benchmark = write_tilelang_inputs(root)

            result = subprocess.run(
                [
                    "python3",
                    "helpers/prepare_tilelang_profile_run.py",
                    "--run-dir",
                    str(run_dir),
                    "--payload-src",
                    str(payload),
                    "--benchmark-json",
                    str(benchmark),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            workflow = json.loads((run_dir / "analysis" / "tilelang_profile_run.json").read_text(encoding="utf-8"))
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")

            self.assertTrue((run_dir / "reports").is_dir())
            self.assertTrue((run_dir / "analysis" / "tilelang_context.json").exists())
            self.assertIn("wrote", result.stdout)
            self.assertIn("warning: Created empty reports/ directory", result.stderr)
            self.assertEqual(workflow["workflow"], "TileLang kernel profiling workflow")
            self.assertTrue(workflow["artifacts"]["reports"]["created_by_prepare"])
            self.assertFalse(workflow["artifacts"]["reports"]["modified_by_prepare"])
            self.assertIn("### TileLang Benchmark Context", report)
            self.assertIn("tilelang-ascend/kernel/v1/4096x2048-f16-cases2", report)

    def test_prepare_tilelang_profile_run_preserves_existing_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = fresh_run(root / "profile", "tilelang_kernel")
            reports_before = reports_file_snapshot(run_dir)
            payload, benchmark = write_tilelang_inputs(root)

            run([
                "python3",
                "helpers/prepare_tilelang_profile_run.py",
                "--run-dir",
                str(run_dir),
                "--payload-src",
                str(payload),
                "--benchmark-json",
                str(benchmark),
            ])
            workflow = json.loads((run_dir / "analysis" / "tilelang_profile_run.json").read_text(encoding="utf-8"))

            self.assertEqual(reports_before, reports_file_snapshot(run_dir))
            self.assertFalse(workflow["artifacts"]["reports"]["created_by_prepare"])
            self.assertTrue(workflow["artifacts"]["reports"]["existed_before_prepare"])
            self.assertTrue((run_dir / "REPORT.md").exists())

    def test_prepare_tilelang_profile_run_missing_jit_debug_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = fresh_run(root / "profile", "tilelang_kernel")
            payload, benchmark = write_tilelang_inputs(root)
            missing_debug = root / "missing-jit-debug"

            result = subprocess.run(
                [
                    "python3",
                    "helpers/prepare_tilelang_profile_run.py",
                    "--run-dir",
                    str(run_dir),
                    "--payload-src",
                    str(payload),
                    "--benchmark-json",
                    str(benchmark),
                    "--jit-debug-root",
                    str(missing_debug),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            workflow = json.loads((run_dir / "analysis" / "tilelang_profile_run.json").read_text(encoding="utf-8"))

            self.assertIn("warning: Optional JIT debug root missing: missing-jit-debug", result.stderr)
            self.assertIn("Optional JIT debug root missing: missing-jit-debug", workflow["warnings"])

    def test_profile_tilelang_benchmark_run_orchestrates_fake_msprof_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark_repo, payload = write_fake_tilelang_benchmark_repo(root)
            fake_msprof = write_fake_msprof(root / "msprof")
            run_dir = root / "profile" / "tilelang_orchestrated"
            toolkit_home = root / "ascend-toolkit"
            toolkit_home.mkdir()
            (toolkit_home / "version.cfg").write_text(
                "toolkit_running_version=[8.3.0.2.220:8.3.RC2]\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["ASCEND_TOOLKIT_HOME"] = str(toolkit_home)

            result = subprocess.run(
                [
                    "python3",
                    "helpers/profile_tilelang_benchmark_run.py",
                    "--run-dir",
                    str(run_dir),
                    "--benchmark-repo",
                    str(benchmark_repo),
                    "--payload-src",
                    payload.relative_to(benchmark_repo).as_posix(),
                    "--task",
                    "svd",
                    "--warmups",
                    "0",
                    "--repeats",
                    "1",
                    "--baseline-ms",
                    "1.0",
                    "--msprof-bin",
                    str(fake_msprof),
                    "--python-bin",
                    sys.executable,
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            context = json.loads((run_dir / "analysis" / "tilelang_context.json").read_text(encoding="utf-8"))
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            summary = json.loads((run_dir / "analysis" / "tilelang_benchmark_profile_run.json").read_text(encoding="utf-8"))
            op_benchmark = json.loads((run_dir / "harness" / "op_profile_benchmark_result.json").read_text(encoding="utf-8"))
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            diagnosis = report.split("## 3. Diagnosis", 1)[1].split("## 4. Optimization Directions", 1)[0]

            self.assertTrue((run_dir / "harness").is_dir())
            self.assertTrue((run_dir / "logs").is_dir())
            self.assertTrue((run_dir / "reports").is_dir())
            self.assertTrue((run_dir / "analysis").is_dir())
            self.assertTrue((run_dir / "harness" / "run_benchmark_canonical.sh").exists())
            self.assertTrue((run_dir / "harness" / "run_benchmark_app_profile.sh").exists())
            self.assertTrue((run_dir / "harness" / "run_benchmark_op_profile.sh").exists())
            canonical_script = (run_dir / "harness" / "run_benchmark_canonical.sh").read_text(encoding="utf-8")
            app_script = (run_dir / "harness" / "run_benchmark_app_profile.sh").read_text(encoding="utf-8")
            op_script = (run_dir / "harness" / "run_benchmark_op_profile.sh").read_text(encoding="utf-8")
            self.assertIn("--task svd", canonical_script)
            self.assertIn("--warmups 0", canonical_script)
            self.assertIn("--repeats 1", canonical_script)
            self.assertIn("--baseline-ms 1.0", canonical_script)
            self.assertIn(str(payload), canonical_script)
            self.assertIn("TILELANG_PROFILE_PHASE=canonical", canonical_script)
            self.assertIn("TILELANG_PROFILE_PHASE=app_profile", app_script)
            self.assertIn("TILELANG_PROFILE_PHASE=op_profile", op_script)
            self.assertNotIn("warning: msprof op benchmark process returned non-zero", result.stderr)
            self.assertNotIn("failed benchmark JSON", result.stderr)
            self.assertNotIn("TileLang benchmark orchestrator warning: msprof op benchmark process returned non-zero", report)
            self.assertTrue(op_benchmark["compiled"])
            self.assertTrue(op_benchmark["correctness"]["passed"])
            self.assertEqual(op_benchmark["runtime"], 3.44)
            self.assertEqual(context["sources"]["benchmark_json"]["artifact"], "benchmark_result.json")
            self.assertEqual(context["benchmark"]["workload"]["id"], "tilelang-ascend/fake/svd")
            self.assertEqual(context["benchmark"]["candidate"]["runtime"], 0.77)
            self.assertEqual(summary["task"], "svd")
            self.assertEqual(summary["warmups"], 0)
            self.assertEqual(summary["repeats"], 1)
            self.assertEqual(summary["baseline_ms"], 1.0)
            self.assertIn(str(benchmark_repo), summary["benchmark_repo"])
            self.assertIn(str(payload), summary["payload_src"])
            self.assertEqual(provenance["cann_version"]["value"], "8.3.0.2.220:8.3.RC2")
            self.assertEqual(provenance["cann_version"]["source"]["artifact"], "logs/cann_version.cfg")
            self.assertEqual([item["value"] for item in provenance["profiler_status"]], ["0", "0"])
            self.assertEqual(
                [item["value"] for item in provenance["profile_outputs"]],
                ["reports/app/PROF_001", "reports/op/OPPROF_001", "reports/app", "reports/op"],
            )
            self.assertEqual(provenance["profile_output"]["value"], "reports/app/PROF_001")
            self.assertEqual(provenance["profile_output_segments"]["app"]["output"]["value"], "reports/app")
            self.assertEqual(provenance["profile_output_segments"]["app"]["resolved_output"]["value"], "reports/app/PROF_001")
            self.assertEqual(provenance["profile_output_segments"]["op"]["output"]["value"], "reports/op")
            self.assertEqual(provenance["profile_output_segments"]["op"]["resolved_output"]["value"], "reports/op/OPPROF_001")
            self.assertIn("logs/msprof_default.status", provenance["sources"])
            self.assertIn("logs/msprof_op.status", provenance["sources"])
            self.assertIn("logs/command_msprof_op.txt", provenance["sources"])
            self.assertIn("benchmark_result.json", summary["artifacts"]["benchmark_json"])
            self.assertIn("app_profile_benchmark_result.json", summary["artifacts"]["app_benchmark_json"])
            self.assertIn("op_profile_benchmark_result.json", summary["artifacts"]["op_benchmark_json"])
            self.assertIn("reports/app/PROF_001/mindstudio_profiler_output/op_summary_001.csv", report)
            self.assertIn("reports/app/PROF_001/mindstudio_profiler_output/task_time_001.csv", report)
            self.assertIn("reports/op/OPPROF_001/OpBasicInfo.csv", report)
            self.assertIn("reports/op/OPPROF_001/PipeUtilization.csv", report)
            self.assertIn("**CANN / driver / firmware:** 8.3.0.2.220:8.3.RC2", report)
            self.assertIn("- Profile outputs: app: reports/app", report)
            self.assertIn("reports/op (source: `logs/command_msprof_op.txt`; `--output`)", report)
            self.assertNotIn("- Profile output: not recorded", report)
            self.assertIn("| Workload id | tilelang-ascend/fake/svd |", report)
            self.assertNotIn("Analyzer warning: missing arithmetic_utilization:", report)
            self.assertNotIn("Analyzer warning: missing l2_cache:", report)
            self.assertNotIn("Analyzer warning: missing memory:", report)
            self.assertNotIn("Analyzer warning: missing resource_conflict:", report)
            self.assertNotIn("0.77", diagnosis)
            self.assertNotIn("tilelang-ascend/fake/svd", diagnosis)

    def test_profile_tilelang_benchmark_run_warns_for_failed_app_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark_repo, payload = write_fake_tilelang_benchmark_repo(root)
            fake_msprof = write_fake_msprof(root / "msprof")
            run_dir = root / "profile" / "tilelang_app_profile_failure"
            env = dict(os.environ)
            env["FAKE_APP_PROFILE_CORRECTNESS_FAILURE"] = "1"

            result = subprocess.run(
                [
                    "python3",
                    "helpers/profile_tilelang_benchmark_run.py",
                    "--run-dir",
                    str(run_dir),
                    "--benchmark-repo",
                    str(benchmark_repo),
                    "--payload-src",
                    str(payload),
                    "--msprof-bin",
                    str(fake_msprof),
                    "--python-bin",
                    sys.executable,
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            context = json.loads((run_dir / "analysis" / "tilelang_context.json").read_text(encoding="utf-8"))
            summary = json.loads((run_dir / "analysis" / "tilelang_benchmark_profile_run.json").read_text(encoding="utf-8"))
            app_benchmark = json.loads((run_dir / "harness" / "app_profile_benchmark_result.json").read_text(encoding="utf-8"))
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")

            self.assertIn("warning: app-level msprof benchmark process returned non-zero", result.stderr)
            self.assertIn("TileLang benchmark orchestrator warning: app-level msprof benchmark process returned non-zero", report)
            self.assertIn("reports/app/PROF_001/mindstudio_profiler_output/op_summary_001.csv", report)
            self.assertFalse(app_benchmark["correctness"]["passed"])
            self.assertEqual(context["sources"]["benchmark_json"]["artifact"], "benchmark_result.json")
            self.assertEqual(context["benchmark"]["candidate"]["runtime"], 0.77)
            self.assertTrue(
                any(warning.startswith("app-level msprof benchmark process returned non-zero") for warning in summary["warnings"])
            )

    def test_profile_tilelang_benchmark_run_warns_when_app_child_fails_but_msprof_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark_repo, payload = write_fake_tilelang_benchmark_repo(root)
            fake_msprof = write_fake_msprof(root / "msprof")
            run_dir = root / "profile" / "tilelang_app_child_failed_msprof_zero"
            env = dict(os.environ)
            env["FAKE_APP_PROFILE_CORRECTNESS_FAILURE"] = "1"
            env["FAKE_MSPROF_APP_EXIT_ZERO"] = "1"

            result = subprocess.run(
                [
                    "python3",
                    "helpers/profile_tilelang_benchmark_run.py",
                    "--run-dir",
                    str(run_dir),
                    "--benchmark-repo",
                    str(benchmark_repo),
                    "--payload-src",
                    str(payload),
                    "--msprof-bin",
                    str(fake_msprof),
                    "--python-bin",
                    sys.executable,
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            context = json.loads((run_dir / "analysis" / "tilelang_context.json").read_text(encoding="utf-8"))
            summary = json.loads((run_dir / "analysis" / "tilelang_benchmark_profile_run.json").read_text(encoding="utf-8"))
            app_benchmark = json.loads((run_dir / "harness" / "app_profile_benchmark_result.json").read_text(encoding="utf-8"))
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")

            self.assertIn("warning: app-level msprof benchmark process returned non-zero", result.stderr)
            self.assertEqual((run_dir / "logs" / "msprof_default.status").read_text(encoding="utf-8"), "0\n")
            self.assertFalse(app_benchmark["correctness"]["passed"])
            self.assertIn("TileLang benchmark orchestrator warning: app-level msprof benchmark process returned non-zero", report)
            self.assertEqual(context["sources"]["benchmark_json"]["artifact"], "benchmark_result.json")
            self.assertEqual(context["benchmark"]["candidate"]["runtime"], 0.77)
            self.assertTrue(
                any(warning.startswith("app-level msprof benchmark process returned non-zero") for warning in summary["warnings"])
            )

    def test_profile_tilelang_benchmark_run_fails_when_app_profiler_fails_after_successful_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark_repo, payload = write_fake_tilelang_benchmark_repo(root)
            fake_msprof = write_fake_msprof(root / "msprof")
            run_dir = root / "profile" / "tilelang_app_profiler_failed"
            env = dict(os.environ)
            env["FAKE_MSPROF_APP_FORCE_ERROR"] = "1"

            result = subprocess.run(
                [
                    "python3",
                    "helpers/profile_tilelang_benchmark_run.py",
                    "--run-dir",
                    str(run_dir),
                    "--benchmark-repo",
                    str(benchmark_repo),
                    "--payload-src",
                    str(payload),
                    "--msprof-bin",
                    str(fake_msprof),
                    "--python-bin",
                    sys.executable,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=env,
            )

            app_benchmark = json.loads((run_dir / "harness" / "app_profile_benchmark_result.json").read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("app-level msprof failed", result.stderr)
            self.assertEqual((run_dir / "logs" / "msprof_default.status").read_text(encoding="utf-8"), "7\n")
            self.assertTrue(app_benchmark["compiled"])
            self.assertTrue(app_benchmark["correctness"]["passed"])
            self.assertTrue((run_dir / "reports" / "app" / "PROF_001" / "mindstudio_profiler_output" / "op_summary_001.csv").exists())
            self.assertFalse((run_dir / "analysis" / "summary.json").exists())
            self.assertFalse((run_dir / "REPORT.md").exists())

    def test_profile_tilelang_benchmark_run_warns_for_failed_correctness_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark_repo, payload = write_fake_tilelang_benchmark_repo(root)
            fake_msprof = write_fake_msprof(root / "msprof")
            run_dir = root / "profile" / "tilelang_op_correctness_dict"
            env = dict(os.environ)
            env["FAKE_OP_CORRECTNESS_DICT_FAILURE"] = "1"

            result = subprocess.run(
                [
                    "python3",
                    "helpers/profile_tilelang_benchmark_run.py",
                    "--run-dir",
                    str(run_dir),
                    "--benchmark-repo",
                    str(benchmark_repo),
                    "--payload-src",
                    str(payload),
                    "--msprof-bin",
                    str(fake_msprof),
                    "--python-bin",
                    sys.executable,
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            context = json.loads((run_dir / "analysis" / "tilelang_context.json").read_text(encoding="utf-8"))
            summary = json.loads((run_dir / "analysis" / "tilelang_benchmark_profile_run.json").read_text(encoding="utf-8"))
            op_benchmark = json.loads((run_dir / "harness" / "op_profile_benchmark_result.json").read_text(encoding="utf-8"))
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")

            self.assertIn("warning: msprof op benchmark process returned non-zero", result.stderr)
            self.assertIn("TileLang benchmark orchestrator warning: msprof op benchmark process returned non-zero", report)
            self.assertFalse(op_benchmark["correctness"]["passed"])
            self.assertEqual(context["sources"]["benchmark_json"]["artifact"], "benchmark_result.json")
            self.assertEqual(context["benchmark"]["candidate"]["runtime"], 0.77)
            self.assertTrue(
                any(warning.startswith("msprof op benchmark process returned non-zero") for warning in summary["warnings"])
            )

    def test_profile_tilelang_benchmark_run_warns_when_op_child_fails_but_msprof_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark_repo, payload = write_fake_tilelang_benchmark_repo(root)
            fake_msprof = write_fake_msprof(root / "msprof")
            run_dir = root / "profile" / "tilelang_op_child_failed_msprof_zero"
            env = dict(os.environ)
            env["FAKE_MSPROF_OP_EXIT_ZERO"] = "1"
            env["FAKE_OP_WORKER_FAILURE"] = "1"

            result = subprocess.run(
                [
                    "python3",
                    "helpers/profile_tilelang_benchmark_run.py",
                    "--run-dir",
                    str(run_dir),
                    "--benchmark-repo",
                    str(benchmark_repo),
                    "--payload-src",
                    str(payload),
                    "--msprof-bin",
                    str(fake_msprof),
                    "--python-bin",
                    sys.executable,
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            summary = json.loads((run_dir / "analysis" / "tilelang_benchmark_profile_run.json").read_text(encoding="utf-8"))
            op_benchmark = json.loads((run_dir / "harness" / "op_profile_benchmark_result.json").read_text(encoding="utf-8"))
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")

            self.assertIn("warning: msprof op benchmark process returned non-zero", result.stderr)
            self.assertEqual((run_dir / "logs" / "msprof_op.status").read_text(encoding="utf-8"), "0\n")
            self.assertFalse(op_benchmark["compiled"])
            self.assertIn("TileLang benchmark orchestrator warning: msprof op benchmark process returned non-zero", report)
            self.assertTrue(
                any(warning.startswith("msprof op benchmark process returned non-zero") for warning in summary["warnings"])
            )

    def test_profile_tilelang_benchmark_run_fails_when_app_artifacts_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark_repo, payload = write_fake_tilelang_benchmark_repo(root)
            fake_msprof = write_fake_msprof(root / "msprof")
            run_dir = root / "profile" / "tilelang_missing_app"
            env = dict(os.environ)
            env["FAKE_MSPROF_SKIP_APP"] = "1"

            result = subprocess.run(
                [
                    "python3",
                    "helpers/profile_tilelang_benchmark_run.py",
                    "--run-dir",
                    str(run_dir),
                    "--benchmark-repo",
                    str(benchmark_repo),
                    "--payload-src",
                    str(payload),
                    "--msprof-bin",
                    str(fake_msprof),
                    "--python-bin",
                    sys.executable,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("app-level msprof artifacts missing", result.stderr)

    def test_profile_tilelang_benchmark_run_requires_op_artifacts_unless_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark_repo, payload = write_fake_tilelang_benchmark_repo(root)
            fake_msprof = write_fake_msprof(root / "msprof")
            env = dict(os.environ)
            env["FAKE_MSPROF_SKIP_OP"] = "1"

            failed = subprocess.run(
                [
                    "python3",
                    "helpers/profile_tilelang_benchmark_run.py",
                    "--run-dir",
                    str(root / "profile" / "tilelang_missing_op"),
                    "--benchmark-repo",
                    str(benchmark_repo),
                    "--payload-src",
                    str(payload),
                    "--msprof-bin",
                    str(fake_msprof),
                    "--python-bin",
                    sys.executable,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("msprof op artifacts missing", failed.stderr)

            succeeded = subprocess.run(
                [
                    "python3",
                    "helpers/profile_tilelang_benchmark_run.py",
                    "--run-dir",
                    str(root / "profile" / "tilelang_op_disabled"),
                    "--benchmark-repo",
                    str(benchmark_repo),
                    "--payload-src",
                    str(payload),
                    "--msprof-bin",
                    str(fake_msprof),
                    "--python-bin",
                    sys.executable,
                    "--disable-op-profile",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertIn("wrote", succeeded.stdout)
            summary = json.loads(
                (root / "profile" / "tilelang_op_disabled" / "analysis" / "tilelang_benchmark_profile_run.json").read_text(
                    encoding="utf-8"
                )
            )
            report = (root / "profile" / "tilelang_op_disabled" / "REPORT.md").read_text(encoding="utf-8")
            self.assertFalse(summary["profiles"]["op_pipe"])
            self.assertIsNone(summary["artifacts"]["op_benchmark_json"])
            self.assertNotIn("OpBasicInfo.csv", report)
            self.assertNotIn("PipeUtilization.csv", report)
            self.assertNotIn("reports/op/", report)

    def test_profile_tilelang_benchmark_run_rejects_reused_collection_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark_repo, payload = write_fake_tilelang_benchmark_repo(root)
            fake_msprof = write_fake_msprof(root / "msprof")
            run_dir = root / "profile" / "tilelang_reused"
            cmd = [
                "python3",
                "helpers/profile_tilelang_benchmark_run.py",
                "--run-dir",
                str(run_dir),
                "--benchmark-repo",
                str(benchmark_repo),
                "--payload-src",
                str(payload),
                "--msprof-bin",
                str(fake_msprof),
                "--python-bin",
                sys.executable,
            ]

            subprocess.run(cmd, cwd=ROOT, check=True, text=True, capture_output=True)
            report_before = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            env = dict(os.environ)
            env["FAKE_MSPROF_SKIP_APP"] = "1"
            rerun = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, env=env)

            self.assertNotEqual(rerun.returncode, 0)
            self.assertIn("already contains collection evidence", rerun.stderr)
            self.assertIn("choose a fresh --run-dir", rerun.stderr)
            self.assertIn("benchmark_result.json", rerun.stderr)
            self.assertEqual(report_before, (run_dir / "REPORT.md").read_text(encoding="utf-8"))

    def test_profile_tilelang_benchmark_run_rejects_stale_raw_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark_repo, payload = write_fake_tilelang_benchmark_repo(root)
            fake_msprof = write_fake_msprof(root / "msprof")
            stale_run = root / "profile" / "tilelang_stale_raw_reports"
            stale_report_dir = stale_run / "reports" / "PROF_OLD" / "mindstudio_profiler_output"
            stale_report_dir.mkdir(parents=True)
            (stale_report_dir / "op_summary_001.csv").write_text(
                "Model ID,Op Name,Task Duration(us)\n1,stale_op,1\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    "helpers/profile_tilelang_benchmark_run.py",
                    "--run-dir",
                    str(stale_run),
                    "--benchmark-repo",
                    str(benchmark_repo),
                    "--payload-src",
                    str(payload),
                    "--msprof-bin",
                    str(fake_msprof),
                    "--python-bin",
                    sys.executable,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("reports/PROF_OLD/mindstudio_profiler_output/op_summary_001.csv", result.stderr)
            self.assertFalse((stale_run / "logs").exists())
            self.assertFalse((stale_run / "analysis" / "summary.json").exists())
            self.assertFalse((stale_run / "REPORT.md").exists())

    def test_profile_tilelang_benchmark_run_rejects_stale_run_local_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark_repo, payload = write_fake_tilelang_benchmark_repo(root)
            fake_msprof = write_fake_msprof(root / "msprof")
            stale_run = root / "profile" / "tilelang_stale_run_local"
            stale_log = stale_run / "logs" / "msprof_occupancy.stdout"
            stale_analysis = stale_run / "analysis" / "simulator_hotspots.txt"
            stale_harness = stale_run / "harness" / "app_profile_benchmark_result.json"
            stale_report = stale_run / "REPORT.md"
            stale_log.parent.mkdir(parents=True)
            stale_analysis.parent.mkdir(parents=True)
            stale_harness.parent.mkdir(parents=True)
            stale_log.write_text("stale occupancy headline\n", encoding="utf-8")
            stale_analysis.write_text("stale simulator hotspot\n", encoding="utf-8")
            stale_harness.write_text("{}\n", encoding="utf-8")
            stale_report.write_text("stale report\n", encoding="utf-8")

            result = subprocess.run(
                [
                    "python3",
                    "helpers/profile_tilelang_benchmark_run.py",
                    "--run-dir",
                    str(stale_run),
                    "--benchmark-repo",
                    str(benchmark_repo),
                    "--payload-src",
                    str(payload),
                    "--msprof-bin",
                    str(fake_msprof),
                    "--python-bin",
                    sys.executable,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("logs/msprof_occupancy.stdout", result.stderr)
            self.assertIn("analysis/simulator_hotspots.txt", result.stderr)
            self.assertIn("harness/app_profile_benchmark_result.json", result.stderr)
            self.assertIn("REPORT.md", result.stderr)
            self.assertEqual(stale_log.read_text(encoding="utf-8"), "stale occupancy headline\n")
            self.assertEqual(stale_analysis.read_text(encoding="utf-8"), "stale simulator hotspot\n")
            self.assertEqual(stale_report.read_text(encoding="utf-8"), "stale report\n")
            self.assertFalse((stale_run / "benchmark_result.json").exists())
            self.assertFalse((stale_run / "analysis" / "summary.json").exists())
            self.assertFalse((stale_run / "logs" / "benchmark.stdout").exists())

    def test_profile_tilelang_benchmark_run_rejects_stale_op_artifacts_unless_op_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark_repo, payload = write_fake_tilelang_benchmark_repo(root)
            fake_msprof = write_fake_msprof(root / "msprof")
            stale_run = root / "profile" / "tilelang_stale_op"
            stale_op_dir = stale_run / "reports" / "op" / "OPPROF_001"
            stale_op_dir.mkdir(parents=True)
            (stale_op_dir / "OpBasicInfo.csv").write_text("Op Name,Task Duration(us)\nstale_op,1\n", encoding="utf-8")
            (stale_op_dir / "PipeUtilization.csv").write_text("Pipe,Utilization(%)\nVector,1\n", encoding="utf-8")
            base_cmd = [
                "python3",
                "helpers/profile_tilelang_benchmark_run.py",
                "--run-dir",
                str(stale_run),
                "--benchmark-repo",
                str(benchmark_repo),
                "--payload-src",
                str(payload),
                "--msprof-bin",
                str(fake_msprof),
                "--python-bin",
                sys.executable,
            ]

            failed = subprocess.run(base_cmd, cwd=ROOT, text=True, capture_output=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("reports/op/OPPROF_001/OpBasicInfo.csv", failed.stderr)
            self.assertFalse((stale_run / "logs").exists())

            disabled_run = root / "profile" / "tilelang_stale_op_disabled"
            disabled_op_dir = disabled_run / "reports" / "op" / "OPPROF_001"
            disabled_op_dir.mkdir(parents=True)
            (disabled_op_dir / "OpBasicInfo.csv").write_text("Op Name,Task Duration(us)\nstale_op,1\n", encoding="utf-8")
            (disabled_op_dir / "PipeUtilization.csv").write_text("Pipe,Utilization(%)\nVector,1\n", encoding="utf-8")
            disabled = subprocess.run(
                [
                    "python3",
                    "helpers/profile_tilelang_benchmark_run.py",
                    "--run-dir",
                    str(disabled_run),
                    "--benchmark-repo",
                    str(benchmark_repo),
                    "--payload-src",
                    str(payload),
                    "--msprof-bin",
                    str(fake_msprof),
                    "--python-bin",
                    sys.executable,
                    "--disable-op-profile",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(disabled.returncode, 0)
            self.assertIn("reports/op/OPPROF_001/OpBasicInfo.csv", disabled.stderr)
            self.assertFalse((disabled_run / "logs").exists())
            self.assertFalse((disabled_run / "analysis" / "summary.json").exists())
            self.assertFalse((disabled_run / "REPORT.md").exists())

    def test_profile_tilelang_benchmark_run_missing_inputs_fail_before_profiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark_repo, _payload = write_fake_tilelang_benchmark_repo(root)
            fake_msprof = write_fake_msprof(root / "msprof")
            result = subprocess.run(
                [
                    "python3",
                    "helpers/profile_tilelang_benchmark_run.py",
                    "--run-dir",
                    str(root / "profile" / "tilelang_missing_payload"),
                    "--benchmark-repo",
                    str(benchmark_repo),
                    "--payload-src",
                    "examples/missing.py",
                    "--msprof-bin",
                    str(fake_msprof),
                    "--python-bin",
                    sys.executable,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("payload source not found", result.stderr)

    def test_profile_tilelang_benchmark_run_missing_repo_fails_before_profiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_msprof = write_fake_msprof(root / "msprof")
            run_dir = root / "profile" / "tilelang_missing_repo"
            result = subprocess.run(
                [
                    "python3",
                    "helpers/profile_tilelang_benchmark_run.py",
                    "--run-dir",
                    str(run_dir),
                    "--benchmark-repo",
                    str(root / "missing-benchmark-repo"),
                    "--payload-src",
                    "examples/kernel_payload_baseline.py",
                    "--msprof-bin",
                    str(fake_msprof),
                    "--python-bin",
                    sys.executable,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("benchmark repo not found", result.stderr)
            self.assertFalse(run_dir.exists())

    def test_generate_report_includes_tilelang_context_without_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "profile" / "tilelang_empty"
            run_dir.mkdir(parents=True)
            payload, benchmark = write_tilelang_inputs(root)
            run([
                "python3",
                "helpers/collect_tilelang_context.py",
                "--run-dir",
                str(run_dir),
                "--payload-src",
                str(payload),
                "--benchmark-json",
                str(benchmark),
            ])
            run(["python3", "helpers/generate_report.py", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            diagnosis = report.split("## 3. Diagnosis", 1)[1].split("## 4. Optimization Directions", 1)[0]
            optimization = report.split("## 4. Optimization Directions", 1)[1].split("## 5. Confidence And Caveats", 1)[0]

            self.assertIn("### TileLang Benchmark Context", report)
            self.assertIn(
                "| Workload id | tilelang-ascend/kernel/v1/4096x2048-f16-cases2 | `analysis/tilelang_context.json`; `benchmark.workload.id` |",
                report,
            )
            self.assertIn("mean_ms", report)
            self.assertIn("max_abs_error=0.000244", report)
            self.assertIn(
                "| Payload source | tilelang_kernel_payload.py | `analysis/tilelang_context.json`; `sources.payload.artifact` |",
                report,
            )
            self.assertIn("analysis/tilelang_context.json", report)
            self.assertIn("No headline diagnosis generated", diagnosis)
            self.assertNotIn("TileLang", diagnosis)
            self.assertNotIn("tilelang-ascend/kernel/v1/4096x2048-f16-cases2", diagnosis)
            self.assertNotIn("TileLang", optimization)
            self.assertNotIn("tilelang-ascend/kernel/v1/4096x2048-f16-cases2", optimization)
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
