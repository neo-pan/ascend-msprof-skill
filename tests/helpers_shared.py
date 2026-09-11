import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
CLI = [sys.executable, "-m", "ascend_msprof_skill"]

from ascend_msprof_skill.analyze_msprof_outputs import (  # noqa: E402
    parse_occupancy_summary_stdout,
    parse_occupancy_summary_text,
    parse_performance_summary_stdout,
    parse_performance_summary_text,
    parse_roofline_summary_stdout,
    parse_roofline_summary_text,
    selected_profiler_stdout_paths,
    selected_roofline_stdout_paths,
)
from ascend_msprof_skill import collection_plan, evidence_model, generate_report, profile_harness as profile_harness_module  # noqa: E402
from ascend_msprof_skill import _profiler_segments as profiler_segments  # noqa: E402
from ascend_msprof_skill.generate_provenance import collect_environment  # noqa: E402
from ascend_msprof_skill.run_evidence import RunEvidence, RunEvidenceError  # noqa: E402
from ascend_msprof_skill.simulator_hotspot_model import classify_source_context  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "mock_run"
REAL_FIXTURE = ROOT / "tests" / "fixtures" / "real_cann_minimal"
REAL_SIMULATOR_FIXTURE = ROOT / "tests" / "fixtures" / "real_simulator_minimal"
REAL_PMSAMPLING_SIMULATOR_FIXTURE = ROOT / "tests" / "fixtures" / "real_pmsampling_simulator_minimal"
REAL_RESOURCECONFLICT_SIMULATOR_FIXTURE = ROOT / "tests" / "fixtures" / "real_resourceconflict_simulator_minimal"
REAL_L2CACHE_FIXTURE = ROOT / "tests" / "fixtures" / "real_l2cache_minimal"
REAL_DEFAULT_VECTOR_FIXTURE = ROOT / "tests" / "fixtures" / "real_default_vector_minimal"
REAL_PIPE_DEFAULT_FOLLOWUP_FIXTURE = ROOT / "tests" / "fixtures" / "real_pipe_default_followup_minimal"
REAL_APP_OP_STDOUT_FIXTURE = ROOT / "tests" / "fixtures" / "real_app_op_stdout_minimal"
REAL_OCCUPANCY_STDOUT_FIXTURE = ROOT / "tests" / "fixtures" / "real_occupancy_stdout_minimal"
REAL_ROOFLINE_STDOUT_FIXTURE = ROOT / "tests" / "fixtures" / "real_roofline_stdout_minimal"


class HelperAssertionsMixin:
    def assert_experiment_hint_shape(self, direction, required_artifacts=()):
        hint = direction.get("experiment_hint")
        self.assertIsInstance(hint, dict)
        for field in [
            "inspect_code_area",
            "next_experiment",
            "expected_profiler_change",
            "recollect_artifacts",
            "caveats",
        ]:
            self.assertIn(field, hint)
            self.assertTrue(hint[field])
        for artifact in required_artifacts:
            self.assertIn(artifact, hint["recollect_artifacts"])
        hint_text = json.dumps(hint).lower()
        self.assertNotIn("rewrite the kernel", hint_text)
        self.assertNotIn("fix by", hint_text)
        self.assertNotIn("guaranteed bottleneck", hint_text)

    def assert_source_context_shape(self, source_context):
        self.assertIsInstance(source_context, list)
        self.assertGreaterEqual(len(source_context), 1)
        self.assertLessEqual(len(source_context), 3)
        allowed_keys = {"artifact", "field_ref", "role", "signal", "value"}
        for item in source_context:
            self.assertIsInstance(item, dict)
            self.assertLessEqual(set(item), allowed_keys)
            self.assertEqual(item["artifact"], "analysis/simulator_hotspots.json")
            self.assertTrue(item["field_ref"])
            self.assertTrue(item["role"])


def test_env() -> dict[str, str]:
    env = os.environ.copy()
    src_path = str(ROOT / "src")
    env["PYTHONPATH"] = src_path + os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else src_path
    return env


def run(cmd, cwd=ROOT):
    env = test_env()
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True, env=env)


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


def fresh_real_pipe_default_followup_run(parent: Path, name: str = "real_pipe_default_followup_minimal") -> Path:
    return copy_fixture(REAL_PIPE_DEFAULT_FOLLOWUP_FIXTURE, parent, name, ignore_analysis=True)


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


def write_minimal_app_timing(run_dir: Path) -> None:
    app_dir = run_dir / "reports" / "app" / "PROF_001" / "mindstudio_profiler_output"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "op_summary_001.csv").write_text(
        "Op Name,Task Duration(us)\nminimal_kernel,12.5\n",
        encoding="utf-8",
    )


def write_minimal_pipe_op(run_dir: Path) -> None:
    logs = run_dir / "logs"
    op_dir = run_dir / "reports" / "op" / "OPPROF_001"
    logs.mkdir(parents=True, exist_ok=True)
    op_dir.mkdir(parents=True, exist_ok=True)
    (logs / "command_msprof_op.txt").write_text(
        "msprof op --output=<abs-path>/reports/op --application=<abs-path>/run.sh --aic-metrics=PipeUtilization\n",
        encoding="utf-8",
    )
    (op_dir / "OpBasicInfo.csv").write_text(
        "Op Name,Task Duration(us),Block Dim\nminimal_kernel,12.5,1\n",
        encoding="utf-8",
    )
    (op_dir / "PipeUtilization.csv").write_text(
        "Pipe,Utilization(%)\nVector,73\n",
        encoding="utf-8",
    )


def write_minimal_arithmetic_op(run_dir: Path) -> None:
    op_dir = run_dir / "reports" / "op" / "OPPROF_001"
    op_dir.mkdir(parents=True, exist_ok=True)
    (op_dir / "ArithmeticUtilization.csv").write_text(
        "Pipe,aiv_vec_ratio\nVector,41\n",
        encoding="utf-8",
    )


def write_minimal_memory_op(run_dir: Path) -> None:
    op_dir = run_dir / "reports" / "op" / "OPPROF_001"
    op_dir.mkdir(parents=True, exist_ok=True)
    (op_dir / "Memory.csv").write_text(
        "Metric,Value\nGM_to_UB_bw_usage_rate(%),64\n",
        encoding="utf-8",
    )


def write_minimal_l2_op(run_dir: Path) -> None:
    op_dir = run_dir / "reports" / "op" / "OPPROF_001"
    op_dir.mkdir(parents=True, exist_ok=True)
    (op_dir / "L2Cache.csv").write_text(
        "sub_block_id,aic_total_hit_rate(%)\ncube0,72\n",
        encoding="utf-8",
    )


def write_minimal_resource_conflict_op(run_dir: Path) -> None:
    op_dir = run_dir / "reports" / "op" / "OPPROF_001"
    op_dir.mkdir(parents=True, exist_ok=True)
    (op_dir / "ResourceConflictRatio.csv").write_text(
        "Resource,aiv_vec_wait_ratio\nvec_bank,17\n",
        encoding="utf-8",
    )


def write_minimal_simulator_trace(run_dir: Path) -> None:
    sim_dir = run_dir / "reports" / "op" / "OPPROF_001" / "simulator"
    sim_dir.mkdir(parents=True, exist_ok=True)
    (sim_dir / "trace.json").write_text(
        json.dumps({"traceEvents": [{"name": "VECTOR", "dur": 5}, {"name": "MTE2", "dur": 9}]}),
        encoding="utf-8",
    )


def fresh_target_identity_run(
    parent: Path,
    name: str = "target_identity_run",
    *,
    expected: str = "main_kernel",
    observed: str = "main_kernel_mix_aic",
    app_observed: str | None = None,
    include_expected: bool = True,
    tilelang_context: bool = False,
) -> Path:
    dst = parent / name
    op_dir = dst / "reports" / "OPPROF_001"
    op_dir.mkdir(parents=True, exist_ok=True)
    (dst / "analysis").mkdir(parents=True, exist_ok=True)
    (op_dir / "OpBasicInfo.csv").write_text(
        f"Op Name,Task Duration(us),Block Dim\n{observed},12.5,8\n",
        encoding="utf-8",
    )
    if app_observed is not None:
        prof_dir = dst / "reports" / "PROF_001" / "mindstudio_profiler_output"
        prof_dir.mkdir(parents=True, exist_ok=True)
        (prof_dir / "op_summary_001.csv").write_text(
            f"Op Name,Task Duration(us)\n{app_observed},20\n",
            encoding="utf-8",
        )
    if include_expected:
        (dst / "analysis" / "profile_context.json").write_text(
            json.dumps({"profile_harness": {"metadata": {"expected_kernel_name": expected}}}) + "\n",
            encoding="utf-8",
        )
    elif tilelang_context:
        (dst / "analysis" / "tilelang_context.json").write_text(
            json.dumps({"benchmark": {"metadata": {"task_framework": "TileLang-Ascend"}}}) + "\n",
            encoding="utf-8",
        )
    return dst


def fresh_explicit_target_precedence_run(parent: Path, name: str = "target_identity_precedence_run") -> Path:
    dst = parent / name
    op_dir = dst / "reports" / "OPPROF_001"
    op_dir.mkdir(parents=True, exist_ok=True)
    (dst / "analysis").mkdir(parents=True, exist_ok=True)
    (op_dir / "OpBasicInfo.csv").write_text(
        "Op Name,Task Duration(us),Block Dim\ncustom_kernel,12.5,8\n",
        encoding="utf-8",
    )
    (dst / "analysis" / "profile_context.json").write_text(
        json.dumps({"profile_harness": {"metadata": {"task_framework": "TileLang-Ascend"}}}) + "\n",
        encoding="utf-8",
    )
    (dst / "analysis" / "tilelang_context.json").write_text(
        json.dumps({"benchmark": {"metadata": {"expected_kernel_name": "custom_kernel"}}}) + "\n",
        encoding="utf-8",
    )
    return dst


def fresh_missing_observed_target_run(parent: Path, name: str = "target_identity_missing_observed_run") -> Path:
    dst = parent / name
    (dst / "analysis").mkdir(parents=True, exist_ok=True)
    (dst / "analysis" / "profile_context.json").write_text(
        json.dumps({"profile_harness": {"metadata": {"expected_kernel_name": "main_kernel"}}}) + "\n",
        encoding="utf-8",
    )
    return dst


def fresh_multi_expected_target_run(parent: Path, name: str = "target_identity_multi_expected_run") -> Path:
    dst = parent / name
    prof_dir = dst / "reports" / "PROF_001" / "mindstudio_profiler_output"
    op_dir = dst / "reports" / "OPPROF_001"
    prof_dir.mkdir(parents=True, exist_ok=True)
    op_dir.mkdir(parents=True, exist_ok=True)
    (dst / "analysis").mkdir(parents=True, exist_ok=True)
    (prof_dir / "op_summary_001.csv").write_text(
        "Op Name,Task Duration(us)\nkernel_a,20\n",
        encoding="utf-8",
    )
    (op_dir / "OpBasicInfo.csv").write_text(
        "Op Name,Task Duration(us)\nkernel_b,12.5\n",
        encoding="utf-8",
    )
    (dst / "analysis" / "profile_context.json").write_text(
        json.dumps({"profile_harness": {"metadata": {"expected_kernel_names": ["kernel_a", "kernel_b"]}}}) + "\n",
        encoding="utf-8",
    )
    return dst


def fresh_op_basic_simulator_only_run(parent: Path, name: str = "op_basic_simulator_only") -> Path:
    dst = parent / name
    op_dir = dst / "reports" / "OPPROF_001"
    sim_dir = op_dir / "simulator"
    sim_dir.mkdir(parents=True, exist_ok=True)
    (op_dir / "OpBasicInfo.csv").write_text(
        "op_name,task_duration\nsim_only_kernel,7.5\n",
        encoding="utf-8",
    )
    shutil.copy2(
        REAL_SIMULATOR_FIXTURE / "reports" / "OPPROF_001" / "simulator" / "trace.json",
        sim_dir / "trace.json",
    )
    return dst


def fresh_malformed_trace_run(parent: Path, name: str = "malformed_trace_run") -> Path:
    dst = parent / name
    prof_dir = dst / "reports" / "PROF_001" / "mindstudio_profiler_output"
    op_dir = dst / "reports" / "OPPROF_001"
    sim_dir = op_dir / "simulator"
    prof_dir.mkdir(parents=True, exist_ok=True)
    sim_dir.mkdir(parents=True, exist_ok=True)
    (prof_dir / "op_summary_001.csv").write_text(
        "Op Name,Task Duration(us)\nmalformed_trace_kernel,11\n",
        encoding="utf-8",
    )
    (op_dir / "OpBasicInfo.csv").write_text(
        "Op Name,Task Duration(us)\nmalformed_trace_kernel,11\n",
        encoding="utf-8",
    )
    (sim_dir / "trace.json").write_text("{not-json", encoding="utf-8")
    return dst


def fresh_trace_json_run(parent: Path, name: str, payload) -> Path:
    dst = parent / name
    sim_dir = dst / "reports" / "OPPROF_001" / "simulator"
    sim_dir.mkdir(parents=True, exist_ok=True)
    (sim_dir / "trace.json").write_text(json.dumps(payload), encoding="utf-8")
    return dst


def fresh_multi_duration_trace_run(parent: Path, name: str = "multi_duration_trace_run") -> Path:
    return fresh_trace_json_run(
        parent,
        name,
        {
            "traceEvents": [
                {"name": "short_setup", "dur": 4.0, "ph": "X"},
                {"name": "dominant_pipeline", "dur": 640.0, "ph": "X"},
                {"name": "middle_pipeline", "dur": 400.0, "ph": "X"},
            ]
        },
    )


def fresh_top_level_trace_run(parent: Path, name: str = "top_level_trace_run") -> Path:
    return fresh_trace_json_run(
        parent,
        name,
        [
            {"name": "short_top_level", "dur": 3.0, "ph": "X"},
            {"name": "dominant_top_level", "dur": 900.0, "ph": "X"},
        ],
    )


def fresh_per_core_trace_only_run(parent: Path, name: str = "per_core_trace_only_run") -> Path:
    dst = parent / name
    sim_dir = dst / "reports" / "OPPROF_001" / "simulator"
    for core, duration in [("core0.veccore0", 10.0), ("core1.veccore0", 20.0)]:
        core_dir = sim_dir / core
        core_dir.mkdir(parents=True, exist_ok=True)
        (core_dir / "trace.json").write_text(
            json.dumps(
                {
                    "displayTimeUnit": "ns",
                    "traceEvents": [
                        {"name": "same_pipe_op", "dur": duration, "ph": "X", "tid": "MTE2"},
                    ],
                }
            ),
            encoding="utf-8",
        )
    return dst


def fresh_invalid_aggregate_with_valid_per_core_trace_run(
    parent: Path,
    name: str = "invalid_aggregate_with_valid_per_core_trace_run",
) -> Path:
    dst = parent / name
    sim_dir = dst / "reports" / "OPPROF_001" / "simulator"
    core_dir = sim_dir / "core0.veccore0"
    core_dir.mkdir(parents=True, exist_ok=True)
    (sim_dir / "trace.json").write_text("{not-json", encoding="utf-8")
    (core_dir / "trace.json").write_text(
        json.dumps(
            {
                "displayTimeUnit": "ns",
                "traceEvents": [
                    {"name": "per_core_valid", "dur": 123.0, "ph": "X", "tid": "MTE2"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return dst


def fresh_multi_row_simulator_csv_run(parent: Path, name: str = "multi_row_simulator_csv_run") -> Path:
    dst = parent / name
    sim_dir = dst / "reports" / "OPPROF_001" / "simulator"
    sim_dir.mkdir(parents=True, exist_ok=True)
    (sim_dir / "core0_instr_exe.csv").write_text(
        (
            "instr,running_time(us),cycles,call_count\n"
            "first_instr,10.0,500,9\n"
            "dominant_instr,75.0,100,3\n"
            "later_instr,12.0,900,40\n"
        ),
        encoding="utf-8",
    )
    return dst


def fresh_line_only_simulator_code_run(parent: Path, name: str = "line_only_simulator_code_run") -> Path:
    dst = parent / name
    sim_dir = dst / "reports" / "OPPROF_001" / "simulator"
    sim_dir.mkdir(parents=True, exist_ok=True)
    (sim_dir / "core0_code_exe.csv").write_text(
        "line,running_time(us),cycles,call_count\n42,7.5,150,3\n",
        encoding="utf-8",
    )
    return dst


def fresh_run_local_source_simulator_code_run(parent: Path, name: str = "run_local_source_simulator_code_run") -> Path:
    dst = parent / name
    sim_dir = dst / "reports" / "OPPROF_001" / "simulator"
    src_dir = dst / "tilelang_tmp"
    sim_dir.mkdir(parents=True, exist_ok=True)
    src_dir.mkdir(parents=True, exist_ok=True)
    source = src_dir / "tmp_kernel.cpp"
    source.write_text(
        "\n".join(
            [
                "#include <cstdint>",
                "__aicore__ void main_kernel() {",
                "  AscendC::TPipe pipe;",
                "  auto block = AscendC::GetBlockIdx();",
                "  AscendC::DataCopy(dst_ub, src_gm, 128);",
                "  if (block == 0) {",
                "    AscendC::SyncAll();",
                "  }",
                "}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (sim_dir / "core0_code_exe.csv").write_text(
        f"code,running_time(us),cycles,call_count\n{source}:5,9.5,150,3\n",
        encoding="utf-8",
    )
    return dst


def fresh_external_source_simulator_code_run(parent: Path, name: str = "external_source_simulator_code_run") -> Path:
    dst = parent / name
    sim_dir = dst / "reports" / "OPPROF_001" / "simulator"
    sim_dir.mkdir(parents=True, exist_ok=True)
    external_source = parent / "outside_kernel.cpp"
    external_source.write_text("void external_kernel() {}\n", encoding="utf-8")
    (sim_dir / "core0_code_exe.csv").write_text(
        f"code,running_time(us),cycles,call_count\n{external_source}:1,2.5,10,1\n",
        encoding="utf-8",
    )
    return dst


def fresh_missing_source_simulator_code_run(parent: Path, name: str = "missing_source_simulator_code_run") -> Path:
    dst = parent / name
    sim_dir = dst / "reports" / "OPPROF_001" / "simulator"
    sim_dir.mkdir(parents=True, exist_ok=True)
    missing_source = dst / "tilelang_tmp" / "missing.cpp"
    (sim_dir / "core0_code_exe.csv").write_text(
        f"code,running_time(us),cycles,call_count\n{missing_source}:4,2.5,10,1\n",
        encoding="utf-8",
    )
    return dst


def fresh_invalid_line_simulator_code_run(parent: Path, name: str = "invalid_line_simulator_code_run") -> Path:
    dst = parent / name
    sim_dir = dst / "reports" / "OPPROF_001" / "simulator"
    src_dir = dst / "tilelang_tmp"
    sim_dir.mkdir(parents=True, exist_ok=True)
    src_dir.mkdir(parents=True, exist_ok=True)
    source = src_dir / "short.cpp"
    source.write_text("void short_kernel() {}\n", encoding="utf-8")
    (sim_dir / "core0_code_exe.csv").write_text(
        f"code,running_time(us),cycles,call_count\n{source}:9,2.5,10,1\n",
        encoding="utf-8",
    )
    return dst


def fresh_unreadable_simulator_csv_run(parent: Path, name: str = "unreadable_simulator_csv_run") -> Path:
    dst = parent / name
    prof_dir = dst / "reports" / "PROF_001" / "mindstudio_profiler_output"
    sim_dir = dst / "reports" / "OPPROF_001" / "simulator"
    prof_dir.mkdir(parents=True, exist_ok=True)
    sim_dir.mkdir(parents=True, exist_ok=True)
    (prof_dir / "op_summary_001.csv").write_text(
        "Op Name,Task Duration(us)\nunreadable_sim_csv_kernel,21\n",
        encoding="utf-8",
    )
    (sim_dir / "core0_instr_exe.csv").write_bytes(b"\xff\xfe\xfa\xfb")
    return dst


def fresh_op_basic_block_dim_with_timing_sim_run(
    parent: Path,
    name: str = "op_basic_block_dim_with_timing_sim",
) -> Path:
    dst = parent / name
    prof_dir = dst / "reports" / "PROF_001" / "mindstudio_profiler_output"
    op_dir = dst / "reports" / "OPPROF_001"
    sim_dir = op_dir / "simulator"
    prof_dir.mkdir(parents=True, exist_ok=True)
    sim_dir.mkdir(parents=True, exist_ok=True)
    (prof_dir / "op_summary_001.csv").write_text(
        "Op Name,Task Duration(us)\nblock_dim_kernel,20\n",
        encoding="utf-8",
    )
    (op_dir / "OpBasicInfo.csv").write_text(
        "Op Name,Block Dim\nblock_dim_kernel,8\n",
        encoding="utf-8",
    )
    shutil.copy2(
        REAL_SIMULATOR_FIXTURE / "reports" / "OPPROF_001" / "simulator" / "trace.json",
        sim_dir / "trace.json",
    )
    return dst


def fresh_op_basic_invalid_block_dim_with_timing_sim_run(
    parent: Path,
    block_dim_value: str,
    name: str = "op_basic_invalid_block_dim_with_timing_sim",
) -> Path:
    dst = parent / name
    prof_dir = dst / "reports" / "PROF_001" / "mindstudio_profiler_output"
    op_dir = dst / "reports" / "OPPROF_001"
    sim_dir = op_dir / "simulator"
    prof_dir.mkdir(parents=True, exist_ok=True)
    sim_dir.mkdir(parents=True, exist_ok=True)
    (prof_dir / "op_summary_001.csv").write_text(
        "Op Name,Task Duration(us)\ninvalid_block_dim_kernel,20\n",
        encoding="utf-8",
    )
    (op_dir / "OpBasicInfo.csv").write_text(
        f"Op Name,Block Dim\ninvalid_block_dim_kernel,{block_dim_value}\n",
        encoding="utf-8",
    )
    shutil.copy2(
        REAL_SIMULATOR_FIXTURE / "reports" / "OPPROF_001" / "simulator" / "trace.json",
        sim_dir / "trace.json",
    )
    return dst


def fresh_op_basic_block_dim_sim_only_run(
    parent: Path,
    name: str = "op_basic_block_dim_sim_only",
) -> Path:
    dst = parent / name
    op_dir = dst / "reports" / "OPPROF_001"
    sim_dir = op_dir / "simulator"
    sim_dir.mkdir(parents=True, exist_ok=True)
    (op_dir / "OpBasicInfo.csv").write_text(
        "Op Name,Block Dim\nblock_dim_sim_only_kernel,8\n",
        encoding="utf-8",
    )
    shutil.copy2(
        REAL_SIMULATOR_FIXTURE / "reports" / "OPPROF_001" / "simulator" / "trace.json",
        sim_dir / "trace.json",
    )
    return dst


def fresh_op_basic_duration_block_dim_with_timing_sim_run(
    parent: Path,
    name: str = "op_basic_duration_block_dim_with_timing_sim",
) -> Path:
    dst = parent / name
    prof_dir = dst / "reports" / "PROF_001" / "mindstudio_profiler_output"
    op_dir = dst / "reports" / "OPPROF_001"
    sim_dir = op_dir / "simulator"
    prof_dir.mkdir(parents=True, exist_ok=True)
    sim_dir.mkdir(parents=True, exist_ok=True)
    (prof_dir / "op_summary_001.csv").write_text(
        "Op Name,Task Duration(us)\nduration_block_dim_kernel,20\n",
        encoding="utf-8",
    )
    (op_dir / "OpBasicInfo.csv").write_text(
        "Op Name,Task Duration(us),Block Dim\nduration_block_dim_kernel,3.5,8\n",
        encoding="utf-8",
    )
    shutil.copy2(
        REAL_SIMULATOR_FIXTURE / "reports" / "OPPROF_001" / "simulator" / "trace.json",
        sim_dir / "trace.json",
    )
    return dst


def fresh_op_basic_duration_block_dim_no_sim_run(
    parent: Path,
    name: str = "op_basic_duration_block_dim_no_sim",
) -> Path:
    dst = parent / name
    prof_dir = dst / "reports" / "PROF_001" / "mindstudio_profiler_output"
    op_dir = dst / "reports" / "OPPROF_001"
    prof_dir.mkdir(parents=True, exist_ok=True)
    op_dir.mkdir(parents=True, exist_ok=True)
    (prof_dir / "op_summary_001.csv").write_text(
        "Op Name,Task Duration(us)\nduration_block_dim_no_sim_kernel,20\n",
        encoding="utf-8",
    )
    (op_dir / "OpBasicInfo.csv").write_text(
        "Op Name,Task Duration(us),Block Dim\nduration_block_dim_no_sim_kernel,3.5,8\n",
        encoding="utf-8",
    )
    return dst


def fresh_op_basic_duration_only_with_timing_sim_run(
    parent: Path,
    name: str = "op_basic_duration_only_with_timing_sim",
) -> Path:
    dst = parent / name
    prof_dir = dst / "reports" / "PROF_001" / "mindstudio_profiler_output"
    op_dir = dst / "reports" / "OPPROF_001"
    sim_dir = op_dir / "simulator"
    prof_dir.mkdir(parents=True, exist_ok=True)
    sim_dir.mkdir(parents=True, exist_ok=True)
    (prof_dir / "op_summary_001.csv").write_text(
        "Op Name,Task Duration(us)\nduration_only_kernel,20\n",
        encoding="utf-8",
    )
    (op_dir / "OpBasicInfo.csv").write_text(
        "Op Name,Task Duration(us)\nduration_only_kernel,3.5\n",
        encoding="utf-8",
    )
    shutil.copy2(
        REAL_SIMULATOR_FIXTURE / "reports" / "OPPROF_001" / "simulator" / "trace.json",
        sim_dir / "trace.json",
    )
    return dst


def fresh_name_only_op_basic_with_timing_sim_run(
    parent: Path,
    name: str = "name_only_op_basic_with_timing_sim",
) -> Path:
    dst = parent / name
    prof_dir = dst / "reports" / "PROF_001" / "mindstudio_profiler_output"
    op_dir = dst / "reports" / "OPPROF_001"
    sim_dir = op_dir / "simulator"
    prof_dir.mkdir(parents=True, exist_ok=True)
    sim_dir.mkdir(parents=True, exist_ok=True)
    (prof_dir / "op_summary_001.csv").write_text(
        "Op Name,Task Duration(us)\nname_only_kernel,20\n",
        encoding="utf-8",
    )
    (op_dir / "OpBasicInfo.csv").write_text(
        "Op Name,Task Duration(us)\nname_only_kernel,\n",
        encoding="utf-8",
    )
    shutil.copy2(
        REAL_SIMULATOR_FIXTURE / "reports" / "OPPROF_001" / "simulator" / "trace.json",
        sim_dir / "trace.json",
    )
    return dst


def fresh_header_only_op_summary_run(parent: Path, name: str = "header_only_op_summary") -> Path:
    dst = parent / name
    prof_dir = dst / "reports" / "PROF_001" / "mindstudio_profiler_output"
    prof_dir.mkdir(parents=True, exist_ok=True)
    (prof_dir / "op_summary_001.csv").write_text("Op Name,Task Duration(us)\n", encoding="utf-8")
    return dst


def fresh_header_only_op_basic_with_timing_sim_run(
    parent: Path,
    name: str = "header_only_op_basic_with_timing_sim",
) -> Path:
    dst = parent / name
    prof_dir = dst / "reports" / "PROF_001" / "mindstudio_profiler_output"
    op_dir = dst / "reports" / "OPPROF_001"
    sim_dir = op_dir / "simulator"
    prof_dir.mkdir(parents=True, exist_ok=True)
    sim_dir.mkdir(parents=True, exist_ok=True)
    (prof_dir / "op_summary_001.csv").write_text(
        "Op Name,Task Duration(us)\nheader_only_op_basic_kernel,12\n",
        encoding="utf-8",
    )
    (op_dir / "OpBasicInfo.csv").write_text("Op Name,Task Duration(us)\n", encoding="utf-8")
    shutil.copy2(
        REAL_SIMULATOR_FIXTURE / "reports" / "OPPROF_001" / "simulator" / "trace.json",
        sim_dir / "trace.json",
    )
    return dst


def fresh_op_statistic_op_basic_run(parent: Path, name: str = "op_statistic_op_basic") -> Path:
    dst = parent / name
    prof_dir = dst / "reports" / "PROF_001" / "mindstudio_profiler_output"
    op_dir = dst / "reports" / "OPPROF_001"
    prof_dir.mkdir(parents=True, exist_ok=True)
    op_dir.mkdir(parents=True, exist_ok=True)
    (prof_dir / "op_statistic_001.csv").write_text(
        "OP Type,Total Time(us)\nstat_kernel,99\n",
        encoding="utf-8",
    )
    (op_dir / "OpBasicInfo.csv").write_text(
        "Op Name,Task Duration(us)\nop_basic_kernel,1\n",
        encoding="utf-8",
    )
    return dst


def fresh_pipe_l2_run(parent: Path, name: str = "pipe_l2_run") -> Path:
    dst = parent / name
    op_dir = dst / "reports" / "OPPROF_001"
    op_dir.mkdir(parents=True, exist_ok=True)
    (op_dir / "OpBasicInfo.csv").write_text(
        "Op Name,Task Duration(us)\npipe_l2_kernel,11\n",
        encoding="utf-8",
    )
    (op_dir / "PipeUtilization.csv").write_text(
        "Pipe,Utilization(%)\nMTE2,0.8\n",
        encoding="utf-8",
    )
    (op_dir / "L2Cache.csv").write_text(
        "sub_block_id,aic_total_hit_rate(%)\ncube0,55\n",
        encoding="utf-8",
    )
    return dst


def fresh_conflict_simulator_run(parent: Path, name: str = "conflict_simulator_run") -> Path:
    dst = parent / name
    op_dir = dst / "reports" / "OPPROF_001"
    sim_dir = op_dir / "simulator"
    sim_dir.mkdir(parents=True, exist_ok=True)
    (op_dir / "OpBasicInfo.csv").write_text(
        "Op Name,Task Duration(us)\nconflict_sim_kernel,11\n",
        encoding="utf-8",
    )
    (op_dir / "ResourceConflictRatio.csv").write_text(
        "Resource,Ratio(%)\nvec_bank,0.7\n",
        encoding="utf-8",
    )
    shutil.copy2(
        REAL_SIMULATOR_FIXTURE / "reports" / "OPPROF_001" / "simulator" / "trace.json",
        sim_dir / "trace.json",
    )
    return dst


def one_line_read(report: str) -> str:
    return next(line for line in report.splitlines() if line.startswith("**One-line read:**"))


def timeline_text(run_dir: Path) -> str:
    return (run_dir / "analysis" / "timeline.txt").read_text()


def raw_artifact_index(run_dir: Path) -> dict:
    return json.loads((run_dir / "analysis" / "raw_artifact_index.json").read_text(encoding="utf-8"))


def summary_json(run_dir: Path) -> dict:
    return json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))


def raw_artifacts_by_key(run_dir: Path) -> dict[tuple[str, str], dict]:
    return {
        (item["group"], item["artifact"]): item
        for item in raw_artifact_index(run_dir)["artifacts"]
    }


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


def write_tilelang_inputs_variant(
    parent: Path,
    *,
    mean_ms: float = 1.25,
    passed: bool = True,
    compiled: bool = True,
    error: str | None = None,
    workload_id: str = "tilelang-ascend/kernel/v1/4096x2048-f16-cases2",
    payload_tile_m: int = 64,
    pipeline_depth: int = 3,
) -> tuple[Path, Path]:
    payload, benchmark = write_tilelang_inputs(parent)
    payload.write_text(
        (
            "def kernel_payload():\n"
            f"    return {{'op': 'generic_tilelang_kernel', 'tile_m': {payload_tile_m}, 'tile_n': 32}}\n"
        ),
        encoding="utf-8",
    )
    data = json.loads(benchmark.read_text(encoding="utf-8"))
    data["compiled"] = compiled
    data["correctness"]["passed"] = passed
    data["runtime"] = mean_ms
    data["runtime_stats"]["mean_ms"] = mean_ms
    data["error"] = error
    data["metadata"]["workload_id"] = workload_id
    data["metadata"]["jit_config"]["pipeline_depth"] = pipeline_depth
    benchmark.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload, benchmark


def attach_tilelang_context(root: Path, run_dir: Path, **kwargs) -> None:
    input_dir = root / f"inputs_{run_dir.parent.name}_{run_dir.name}"
    input_dir.mkdir()
    payload, benchmark = write_tilelang_inputs_variant(input_dir, **kwargs)
    run([
        *CLI, "collect-tilelang",
        "--run-dir",
        str(run_dir),
        "--payload-src",
        str(payload),
        "--benchmark-json",
        str(benchmark),
    ])


def make_comparison_verdict_compatible(*run_dirs: Path) -> None:
    provenance = {
        "cann_version": {"value": "8.3.0.2.220:8.3.RC2", "source": {"artifact": "logs/cann_version.cfg", "field": "toolkit_running_version"}},
        "hardware": {"summary": {"value": "1 x 910B2; health OK"}},
        "profile_command": {"value": "msprof op --application=<abs-path>"},
        "profile_output_segments": {"op": {"kind": "op"}},
    }
    for run_dir in run_dirs:
        summary_path = run_dir / "analysis" / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["metric_scope"] = {
            "value": "PipeUtilization",
            "artifact": "logs/command_msprof_op.txt",
            "field_ref": "--aic-metrics",
        }
        summary["evidence_readiness"] = {
            "level": "directional",
            "available_evidence_families": [
                "app_timing",
                "operator_metadata",
                "pipe_utilization",
                "arithmetic_utilization",
                "memory_cache",
                "resource_conflict",
                "simulator_source_pipeline",
                "stdout_performance_summary",
            ],
            "missing_evidence_families": [],
            "recommended_followups": [],
        }
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (run_dir / "analysis" / "provenance.json").write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def set_evidence_readiness(
    run_dir: Path,
    *,
    level: str = "directional",
    families: list[str] | None = None,
    followups: list[dict] | None = None,
) -> None:
    summary_path = run_dir / "analysis" / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["evidence_readiness"] = {
        "level": level,
        "available_evidence_families": families
        if families is not None
        else [
            "app_timing",
            "operator_metadata",
            "pipe_utilization",
            "arithmetic_utilization",
            "memory_cache",
            "resource_conflict",
            "simulator_source_pipeline",
        ],
        "missing_evidence_families": [],
        "recommended_followups": followups or [],
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def reports_file_snapshot(run_dir: Path) -> dict[str, bytes]:
    reports_dir = run_dir / "reports"
    if not reports_dir.exists():
        return {}
    return {
        path.relative_to(reports_dir).as_posix(): path.read_bytes()
        for path in sorted(candidate for candidate in reports_dir.rglob("*") if candidate.is_file())
    }


def write_profile_harness_fixture(run_dir: Path) -> tuple[Path, Path]:
    harness_dir = run_dir / "harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    application = harness_dir / "run.sh"
    application.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    application.chmod(0o755)
    manifest = harness_dir / "profile_harness.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "task": "generic",
                "application": str(application.resolve()),
                "workload": {
                    "id": "generic/profile-harness/v1",
                    "shape": [1, 2, 3],
                    "dtype": "float32",
                    "cases": 1,
                },
                "jit_config": {"out_idx": [0]},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest, application


def write_fake_msprof(bin_dir: Path) -> Path:
    (bin_dir.parent / "version.cfg").write_text("toolkit_running_version=[8.5.2]\n", encoding="utf-8")
    path = bin_dir / "msprof"
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
mode = "simulator" if args[:2] == ["op", "simulator"] else "op" if args[:1] == ["op"] else "app"
output = None
application = None
aic_metrics = None
for index, arg in enumerate(args):
    if arg.startswith("--output="):
        output = arg.split("=", 1)[1]
    elif arg == "--output" and index + 1 < len(args):
        output = args[index + 1]
    elif arg.startswith("--application="):
        application = arg.split("=", 1)[1]
    elif arg == "--application" and index + 1 < len(args):
        application = args[index + 1]
    elif arg.startswith("--aic-metrics="):
        aic_metrics = arg.split("=", 1)[1]
    elif arg == "--aic-metrics" and index + 1 < len(args):
        aic_metrics = args[index + 1]
if not output or not application:
    print("missing output or application", file=sys.stderr)
    sys.exit(2)
expected_cwd = os.environ.get("FAKE_MSPROF_EXPECT_CWD")
if expected_cwd and str(Path.cwd().resolve()) != str(Path(expected_cwd).resolve()):
    print(f"unexpected cwd: {Path.cwd().resolve()} != {Path(expected_cwd).resolve()}", file=sys.stderr)
    sys.exit(7)
out = Path(output)
out.mkdir(parents=True, exist_ok=True)
if mode == "simulator":
    if os.environ.get("FAKE_MSPROF_SIMULATOR_SLEEP"):
        time.sleep(float(os.environ["FAKE_MSPROF_SIMULATOR_SLEEP"]))
    if os.environ.get("FAKE_MSPROF_SIMULATOR_FAIL"):
        print("fake simulator failure", file=sys.stderr)
        sys.exit(int(os.environ.get("FAKE_MSPROF_SIMULATOR_FAIL_STATUS", "9")))
    sim = out / "OPPROF_001" / "simulator"
    core = sim / "core0.veccore0"
    core.mkdir(parents=True, exist_ok=True)
    (sim / "trace.json").write_text(json.dumps({"traceEvents": [{"name": "sim_harness_kernel", "dur": 21.0}]}), encoding="utf-8")
    (core / "core0.veccore0_code_exe.csv").write_text("line,filename,Running Time\\n7,kernel.cpp,21.0\\n", encoding="utf-8")
    print(f"2026-06-07 10:16:00 [INFO] Profiling results saved in {out / 'OPPROF_001'}")
elif mode == "op":
    if aic_metrics == "Default" and os.environ.get("FAKE_MSPROF_DEFAULT_FAIL"):
        print("fake Default failure", file=sys.stderr)
        sys.exit(int(os.environ.get("FAKE_MSPROF_DEFAULT_FAIL_STATUS", "8")))
    opprof = out / "OPPROF_001"
    opprof.mkdir(parents=True, exist_ok=True)
    (opprof / "OpBasicInfo.csv").write_text("Op Name,Task Duration(us),Block Dim\\nharness_kernel,12.5,8\\n", encoding="utf-8")
    (opprof / "PipeUtilization.csv").write_text("Pipe,Utilization(%)\\nvec0,66.5\\n", encoding="utf-8")
    if aic_metrics == "Default":
        (opprof / "ArithmeticUtilization.csv").write_text("Metric,Value\\nvec_ratio,33.5\\n", encoding="utf-8")
        (opprof / "ResourceConflictRatio.csv").write_text("Metric,Value\\nvec_wait_ratio,4.5\\n", encoding="utf-8")
    print(f"2026-06-07 10:15:00 [INFO] Profiling results saved in {opprof}")
else:
    prof = out / "PROF_001" / "mindstudio_profiler_output"
    prof.mkdir(parents=True, exist_ok=True)
    (prof / "op_summary_001.csv").write_text("Op Name,Task Duration(us)\\nharness_kernel,12.5\\n", encoding="utf-8")
    (prof / "task_time_001.csv").write_text("kernel_name,task_time(us)\\nharness_kernel,12.5\\n", encoding="utf-8")
    (prof / "api_statistic_001.csv").write_text("Name,Time(us)\\naclrtSynchronizeStream,1.5\\n", encoding="utf-8")
    (prof / "msprof_001.json").write_text(json.dumps({"traceEvents": [{"name": "harness_kernel", "dur": 12.5}]}), encoding="utf-8")
    print(f"2026-06-07 10:14:00 [INFO] Profiling results saved in {prof}")
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def profile_harness_env(fake_bin: Path) -> dict[str, str]:
    env = test_env()
    for key in ("ASCEND_TOOLKIT_HOME", "ASCEND_HOME_PATH", "CANN_PATH", "DDK_PATH"):
        env.pop(key, None)
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    return env


def profile_harness_env_expect_cwd(fake_bin: Path, cwd: Path) -> dict[str, str]:
    env = profile_harness_env(fake_bin)
    env["FAKE_MSPROF_EXPECT_CWD"] = str(cwd.resolve())
    return env


def write_verify_json(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "metadata": {
                    "workload_id": "verify/generic",
                    "shape": [16, 16],
                    "dtype": "float16",
                    "case_count": 1,
                },
                "compiled": True,
                "runtime": 7.5,
                "ref_runtime": 10.0,
                "speedup": 1.333,
                "correctness": {"max_abs_error": 0.0},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def write_continue_followup_inputs(
    run_dir: Path,
    *,
    summary: dict[str, object] | None = None,
) -> Path:
    manifest, application = write_profile_harness_fixture(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "analysis").mkdir(parents=True, exist_ok=True)
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    profile_harness_module.write_workflow_metadata(
        run_dir,
        manifest_path=manifest,
        application=application,
        manifest=manifest_data,
        verify_json_path=None,
        preset_id="triage",
    )
    if summary is None:
        summary = {
            "target_identity": {"status": "match"},
            "next_collection_actions": [
                {
                    "id": profile_harness_module.DEFAULT_FOLLOWUP_ACTION_ID,
                    "reason": "needs Default metric scope",
                }
            ],
        }
    (run_dir / "analysis" / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return application


class RecordingCommandRunner:
    def __init__(
        self,
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
        timeout: bool = False,
        responses: list[dict[str, object]] | None = None,
    ):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.timeout = timeout
        self.responses = list(responses or [])
        self.calls = []

    def run(self, command, *, cwd: Path, timeout_s: float | None = None):
        self.calls.append({"command": command, "cwd": cwd, "timeout_s": timeout_s})
        response = self.responses.pop(0) if self.responses else {}
        stdout = str(response.get("stdout", self.stdout))
        stderr = str(response.get("stderr", self.stderr))
        returncode = int(response.get("returncode", self.returncode))
        timeout = bool(response.get("timeout", self.timeout))
        if timeout:
            raise subprocess.TimeoutExpired(command, timeout_s, output=stdout, stderr=stderr)
        return profile_harness_module.CommandExecutionResult(
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
        )
