import io
import json
import os
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
from ascend_msprof_skill import collection_plan, generate_report, profile_harness as profile_harness_module  # noqa: E402
from ascend_msprof_skill.generate_provenance import collect_environment  # noqa: E402
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
        "cann_version": {"value": "8.3.0.2.220:8.3.RC2"},
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
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (run_dir / "analysis" / "provenance.json").write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


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
        )

        self.assertEqual(section["source"], "logs/msprof_op.stdout")
        self.assertEqual(section["section"], "Performance Summary Report")
        self.assertEqual(
            section["messages"],
            [
                {
                    "ordinal": 1,
                    "message": "aicore MTE3 bandwidth utilization lower than 80% when active.",
                    "source": "logs/msprof_op.stdout",
                },
                {
                    "ordinal": 2,
                    "message": "aivector compute usage lower than 20%.",
                    "source": "logs/msprof_op.stdout",
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
        for rel in validate.COMMAND_DOC_PATHS:
            text = (ROOT / rel).read_text(encoding="utf-8")
            for setup in validate.REQUIRED_COMMAND_SETUP:
                self.assertIn(setup, text)
        self.assertNotIn("--benchmark-repo", readme_text)
        self.assertNotIn("render-profile-harness", readme_text)

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

    def test_profile_harness_manifest_orchestrates_fake_msprof_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "candidate"
            manifest, application = write_profile_harness_fixture(run_dir)
            verify_json = write_verify_json(run_dir / "context" / "verify.json")
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--verify-json",
                    str(verify_json),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertIn("wrote", result.stdout)
            self.assertTrue((run_dir / "logs" / "command_msprof.txt").exists())
            self.assertTrue((run_dir / "logs" / "command_msprof_op.txt").exists())
            self.assertFalse((run_dir / "logs" / "command_msprof_simulator.txt").exists())
            self.assertIn(str(application.resolve()), (run_dir / "logs" / "command_msprof.txt").read_text())
            self.assertTrue((run_dir / "reports" / "app" / "PROF_001" / "mindstudio_profiler_output" / "op_summary_001.csv").exists())
            self.assertTrue((run_dir / "reports" / "op" / "OPPROF_001" / "PipeUtilization.csv").exists())
            self.assertTrue((run_dir / "analysis" / "provenance.json").exists())
            self.assertTrue((run_dir / "analysis" / "summary.json").exists())
            self.assertTrue((run_dir / "analysis" / "raw_artifact_index.json").exists())
            self.assertTrue((run_dir / "analysis" / "key_metrics.txt").exists())
            self.assertTrue((run_dir / "analysis" / "profile_context.json").exists())
            self.assertTrue((run_dir / "REPORT.md").exists())

            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["workflow"], "generic profile harness profiling workflow")
            self.assertEqual(workflow["inputs"]["manifest"], "harness/profile_harness.json")
            self.assertEqual(workflow["inputs"]["application"], "harness/run.sh")
            self.assertEqual(workflow["inputs"]["application_resolved_path"], str(application.resolve()))
            self.assertEqual(workflow["inputs"]["verify_json"], "context/verify.json")
            self.assertEqual(workflow["boundary"]["benchmark_renderer_owned_by"], "caller_or_benchmark_skill")
            self.assertEqual(workflow["profile_harness"]["workload"]["id"], "generic/profile-harness/v1")
            self.assertEqual(workflow["collection_plan"]["preset_id"], "triage")
            self.assertEqual(workflow["collection_plan"]["source"], "profile_harness_preset")
            self.assertEqual(
                [segment["segment_id"] for segment in workflow["collection_plan"]["segments"]],
                ["app", "op"],
            )
            self.assertEqual(workflow["collection_plan"]["segments"][1]["metric_scope"], "PipeUtilization")

            context = json.loads((run_dir / "analysis" / "profile_context.json").read_text(encoding="utf-8"))
            self.assertEqual(context["sources"]["profile_harness_manifest"]["artifact"], "harness/profile_harness.json")
            self.assertEqual(context["sources"]["application"]["artifact"], "harness/run.sh")
            self.assertEqual(context["sources"]["application"]["resolved_path"], str(application.resolve()))
            self.assertEqual(context["sources"]["verify_json"]["artifact"], "context/verify.json")
            self.assertEqual(context["profile_harness"]["workload"]["id"], "generic/profile-harness/v1")
            self.assertEqual(context["benchmark"]["workload"]["id"], "verify/generic")
            self.assertEqual(context["verify_context"]["evidence_role"], "correctness_and_timing_context_only")

            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("### Profile Harness Context", report)
            self.assertIn("- Collection plan: triage; segments: app, op; source: profile_harness_preset", report)
            self.assertIn("`analysis/profile_context.json`; `sources.verify_json.artifact`", report)
            self.assertIn("context only; source: `analysis/profile_context.json`; `benchmark.workload`", report)
            self.assertIn("Highest application-level operator duration", report)

            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["headlines"]["op_summary"]["name"], "harness_kernel")
            self.assertEqual(summary["headlines"]["pipe_utilization"]["value"], 66.5)
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["collection_plan"]["preset_id"], "triage")
            self.assertIn("analysis/profile_harness_run.json", provenance["sources"])

    def test_profile_harness_explicit_triage_preset_matches_default_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "triage_preset"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--preset",
                    "triage",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertTrue((run_dir / "logs" / "command_msprof.txt").exists())
            self.assertTrue((run_dir / "logs" / "command_msprof_op.txt").exists())
            self.assertFalse(
                (run_dir / "logs" / "command_msprof_followup_collect_default_metric_followup.txt").exists()
            )
            self.assertFalse((run_dir / "logs" / "command_msprof_simulator.txt").exists())
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["collection_plan"]["preset_id"], "triage")
            self.assertEqual(
                [segment["segment_id"] for segment in workflow["collection_plan"]["segments"]],
                ["app", "op"],
            )

    def test_profile_harness_default_depth_preset_collects_default_followup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "default_depth"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--preset",
                    "default-depth",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            followup_command = run_dir / "logs" / "command_msprof_followup_collect_default_metric_followup.txt"
            self.assertTrue(followup_command.exists())
            self.assertIn("--aic-metrics=Default", followup_command.read_text(encoding="utf-8"))
            self.assertTrue(
                (
                    run_dir
                    / "reports"
                    / "followups"
                    / "collect_default_metric_followup"
                    / "OPPROF_001"
                    / "ArithmeticUtilization.csv"
                ).exists()
            )
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["collection_plan"]["preset_id"], "default-depth")
            self.assertEqual(
                [segment["segment_id"] for segment in workflow["collection_plan"]["segments"]],
                ["app", "op", "default"],
            )
            self.assertEqual(
                workflow["outputs"]["default"],
                "reports/followups/collect_default_metric_followup",
            )
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            self.assertIn("collect_default_metric_followup", provenance["profile_output_segments"]["followups"])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["headlines"]["arithmetic_utilization"]["metric_scope"], "Default")

    def test_profile_harness_follow_next_actions_collects_default_followup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "follow_next_default"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            initial_summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            self.assertIn(
                "collect_default_metric_followup",
                {action["id"] for action in initial_summary["next_collection_actions"]},
            )

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                    "--continue-from-summary",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            followup_command = run_dir / "logs" / "command_msprof_followup_collect_default_metric_followup.txt"
            self.assertTrue(followup_command.exists())
            self.assertIn("--aic-metrics=Default", followup_command.read_text(encoding="utf-8"))
            self.assertTrue(
                (
                    run_dir
                    / "reports"
                    / "followups"
                    / "collect_default_metric_followup"
                    / "OPPROF_001"
                    / "ArithmeticUtilization.csv"
                ).exists()
            )
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["commands"]["msprof_default_followup"], "logs/command_msprof_followup_collect_default_metric_followup.txt")
            self.assertEqual(workflow["outputs"]["default"], "reports/followups/collect_default_metric_followup")
            self.assertEqual(workflow["follow_up_actions"][0]["id"], "collect_default_metric_followup")
            self.assertEqual(workflow["follow_up_actions"][0]["status"], "succeeded")
            self.assertEqual(workflow["follow_up_actions"][0]["command_key"], "msprof_default_followup")
            self.assertEqual(workflow["follow_up_actions"][0]["output_key"], "default")
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["headlines"]["arithmetic_utilization"]["metric_scope"], "Default")
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            self.assertIn("collect_default_metric_followup", provenance["profile_output_segments"]["followups"])

    def test_profile_harness_follow_next_actions_skips_unsupported_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "follow_next_unsupported"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            summary_path = run_dir / "analysis" / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["next_collection_actions"] = [
                {"id": "collect_source_or_context", "reason": "needs simulator context"},
                {"id": "unknown_action", "reason": "not supported"},
            ]
            summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                    "--continue-from-summary",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertFalse(
                (run_dir / "logs" / "command_msprof_followup_collect_default_metric_followup.txt").exists()
            )
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            actions = {item["id"]: item for item in workflow["follow_up_actions"]}
            self.assertEqual(actions["collect_source_or_context"]["status"], "skipped")
            self.assertEqual(actions["unknown_action"]["status"], "skipped")
            self.assertNotIn("msprof_default_followup", workflow["commands"])
            self.assertNotIn("default", workflow["outputs"])

    def test_profile_harness_follow_next_actions_uses_readiness_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "follow_next_readiness_fallback"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            summary_path = run_dir / "analysis" / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["next_collection_actions"] = []
            summary["evidence_readiness"]["recommended_followups"] = [
                {"id": "collect_default_metric_followup", "reason": "fallback Default action"}
            ]
            summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                    "--continue-from-summary",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            record = workflow["follow_up_actions"][0]
            self.assertEqual(record["id"], "collect_default_metric_followup")
            self.assertEqual(record["status"], "succeeded")
            self.assertIn("fallback Default action", record["reason"])
            self.assertTrue(
                (
                    run_dir
                    / "reports"
                    / "followups"
                    / "collect_default_metric_followup"
                    / "OPPROF_001"
                    / "ArithmeticUtilization.csv"
                ).exists()
            )

    def test_profile_harness_follow_next_actions_blocks_existing_default_followup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "follow_next_existing_default"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--preset",
                    "default-depth",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            summary_path = run_dir / "analysis" / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["next_collection_actions"] = [{"id": "collect_default_metric_followup", "reason": "recollect"}]
            summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                    "--continue-from-summary",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            record = workflow["follow_up_actions"][0]
            self.assertEqual(record["id"], "collect_default_metric_followup")
            self.assertEqual(record["status"], "blocked")
            self.assertIn("would be overwritten", record["reason"])

    def test_profile_harness_follow_next_actions_failed_default_does_not_record_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "follow_next_default_failure"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            env["FAKE_MSPROF_DEFAULT_FAIL"] = "1"
            env["FAKE_MSPROF_DEFAULT_FAIL_STATUS"] = "8"

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                    "--continue-from-summary",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Default follow-up failed", result.stderr)
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            record = workflow["follow_up_actions"][0]
            self.assertEqual(record["id"], "collect_default_metric_followup")
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["returncode"], 8)
            self.assertEqual(workflow["commands"]["msprof_default_followup"], "logs/command_msprof_followup_collect_default_metric_followup.txt")
            self.assertNotIn("default", workflow["outputs"])

    def test_profile_harness_full_preset_does_not_collect_simulator_without_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "full_without_simulator"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--preset",
                    "full",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertTrue((run_dir / "logs" / "command_msprof_followup_collect_default_metric_followup.txt").exists())
            self.assertFalse((run_dir / "logs" / "command_msprof_simulator.txt").exists())
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["collection_plan"]["preset_id"], "full")
            self.assertEqual(
                [segment["segment_id"] for segment in workflow["collection_plan"]["segments"]],
                ["app", "op", "default"],
            )

    def test_profile_harness_full_preset_with_simulator_records_optional_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "full_with_simulator"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--preset",
                    "full",
                    "--simulator",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["collection_plan"]["preset_id"], "full")
            self.assertEqual(
                [segment["segment_id"] for segment in workflow["collection_plan"]["segments"]],
                ["app", "op", "default", "simulator"],
            )
            simulator_segment = workflow["collection_plan"]["segments"][3]
            self.assertFalse(simulator_segment["required"])
            self.assertEqual(simulator_segment["status"], "succeeded")

    def test_profile_harness_manifest_optional_simulator_collects_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "candidate_simulator"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--simulator",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertTrue((run_dir / "logs" / "command_msprof_simulator.txt").exists())
            self.assertTrue((run_dir / "logs" / "msprof_simulator.stdout").exists())
            self.assertEqual((run_dir / "logs" / "msprof_simulator.status").read_text(encoding="utf-8"), "0\n")
            self.assertTrue((run_dir / "reports" / "sim" / "OPPROF_001" / "simulator" / "trace.json").exists())
            self.assertTrue(
                (
                    run_dir
                    / "reports"
                    / "sim"
                    / "OPPROF_001"
                    / "simulator"
                    / "core0.veccore0"
                    / "core0.veccore0_code_exe.csv"
                ).exists()
            )
            self.assertTrue((run_dir / "analysis" / "simulator_hotspots.json").exists())
            self.assertTrue((run_dir / "REPORT.md").exists())

            command = (run_dir / "logs" / "command_msprof_simulator.txt").read_text(encoding="utf-8")
            self.assertIn("op simulator", command)
            self.assertIn("--aic-metrics=PipeUtilization", command)
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["commands"]["msprof_simulator"], "logs/command_msprof_simulator.txt")
            self.assertEqual(workflow["outputs"]["simulator"], "reports/sim")
            self.assertEqual(
                workflow["simulator"],
                {
                    "aic_metrics": "PipeUtilization",
                    "enabled": True,
                    "required": False,
                    "status": "succeeded",
                },
            )
            self.assertEqual(
                [segment["segment_id"] for segment in workflow["collection_plan"]["segments"]],
                ["app", "op", "simulator"],
            )
            simulator_segment = workflow["collection_plan"]["segments"][2]
            self.assertFalse(simulator_segment["required"])
            self.assertEqual(simulator_segment["status"], "succeeded")
            self.assertEqual(simulator_segment["command_log"], "logs/command_msprof_simulator.txt")
            context = json.loads((run_dir / "analysis" / "profile_context.json").read_text(encoding="utf-8"))
            self.assertEqual(context["warnings"], [])

    def test_profile_harness_application_optional_simulator_collects_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            application = root / "external_run.sh"
            application.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            application.chmod(0o755)
            run_dir = root / "profile" / "direct_application_simulator"
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--application",
                    str(application),
                    "--simulator",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["simulator"]["status"], "succeeded")
            self.assertTrue((run_dir / "reports" / "sim" / "OPPROF_001" / "simulator" / "trace.json").exists())
            self.assertTrue((run_dir / "analysis" / "summary.json").exists())
            self.assertTrue((run_dir / "REPORT.md").exists())

    def test_profile_harness_optional_simulator_failure_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "simulator_failure"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)
            env["FAKE_MSPROF_SIMULATOR_FAIL"] = "1"
            env["FAKE_MSPROF_SIMULATOR_FAIL_STATUS"] = "9"

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--simulator",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertEqual((run_dir / "logs" / "msprof_simulator.status").read_text(encoding="utf-8"), "9\n")
            self.assertTrue((run_dir / "reports" / "app" / "PROF_001" / "mindstudio_profiler_output" / "op_summary_001.csv").exists())
            self.assertTrue((run_dir / "reports" / "op" / "OPPROF_001" / "PipeUtilization.csv").exists())
            self.assertTrue((run_dir / "analysis" / "summary.json").exists())
            self.assertTrue((run_dir / "REPORT.md").exists())

            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["simulator"]["status"], "failed")
            self.assertTrue(any("optional simulator collection failed" in warning for warning in workflow["warnings"]))
            context = json.loads((run_dir / "analysis" / "profile_context.json").read_text(encoding="utf-8"))
            self.assertTrue(any("optional simulator collection failed" in warning for warning in context["warnings"]))

    def test_profile_harness_optional_simulator_timeout_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "simulator_timeout"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)
            env["FAKE_MSPROF_SIMULATOR_SLEEP"] = "1"

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                    "--simulator",
                    "--simulator-timeout-s",
                    "0.01",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertEqual((run_dir / "logs" / "msprof_simulator.status").read_text(encoding="utf-8"), "timeout\n")
            self.assertTrue((run_dir / "analysis" / "summary.json").exists())
            self.assertTrue((run_dir / "REPORT.md").exists())
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["simulator"]["status"], "timeout")
            self.assertTrue(any("optional simulator collection timed out" in warning for warning in workflow["warnings"]))
            context = json.loads((run_dir / "analysis" / "profile_context.json").read_text(encoding="utf-8"))
            self.assertTrue(any("optional simulator collection timed out" in warning for warning in context["warnings"]))

    def test_profile_harness_rejects_simulator_timeout_without_simulator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            application = root / "external_run.sh"
            application.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            application.chmod(0o755)
            run_dir = root / "profile" / "timeout_without_simulator"

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--application",
                    str(application),
                    "--simulator-timeout-s",
                    "1",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--simulator-timeout-s requires --simulator", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())

    def test_profile_harness_rejects_follow_next_without_continue_from_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "follow_without_continue"

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--follow-next-actions and --continue-from-summary must be used together", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())

    def test_profile_harness_continue_from_summary_rejects_fresh_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            application = root / "external_run.sh"
            application.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            application.chmod(0o755)
            run_dir = root / "profile" / "continue_with_application"

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--application",
                    str(application),
                    "--follow-next-actions",
                    "--continue-from-summary",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--continue-from-summary reuses existing workflow inputs", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())

    def test_profile_harness_continue_from_summary_rejects_manual_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = fresh_pipe_l2_run(root / "manual_run")
            run([*CLI, "analyze", "--run-dir", str(run_dir)])

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                    "--continue-from-summary",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("analysis/profile_harness_run.json not found", result.stderr)

    def test_profile_harness_follow_next_actions_blocks_target_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "follow_next_target_mismatch"
            manifest, application = write_profile_harness_fixture(run_dir)
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            summary_path = run_dir / "analysis" / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["target_identity"] = {"status": "mismatch"}
            summary["next_collection_actions"] = [{"id": "collect_default_metric_followup", "reason": "needs Default"}]
            summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--follow-next-actions",
                    "--continue-from-summary",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertFalse(
                (run_dir / "logs" / "command_msprof_followup_collect_default_metric_followup.txt").exists()
            )
            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            record = workflow["follow_up_actions"][0]
            self.assertEqual(record["status"], "blocked")
            self.assertEqual(record["consistency"], "blocked")
            self.assertIn("target identity status is mismatch", record["reason"])

    def test_profile_harness_rejects_unknown_preset_before_msprof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            application = root / "external_run.sh"
            application.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            application.chmod(0o755)
            run_dir = root / "profile" / "unknown_preset"

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--application",
                    str(application),
                    "--preset",
                    "memory-depth",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid choice", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())

    def test_profile_harness_application_orchestrates_fake_msprof_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            application = root / "external_run.sh"
            application.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            application.chmod(0o755)
            run_dir = root / "profile" / "direct_application"
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--application",
                    str(application),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertIsNone(workflow["inputs"]["manifest"])
            self.assertEqual(workflow["inputs"]["application"], application.name)
            self.assertEqual(workflow["inputs"]["application_resolved_path"], str(application.resolve()))
            context = json.loads((run_dir / "analysis" / "profile_context.json").read_text(encoding="utf-8"))
            self.assertEqual(context["sources"]["application"]["artifact"], application.name)
            self.assertEqual(context["sources"]["application"]["resolved_path"], str(application.resolve()))
            self.assertTrue((run_dir / "analysis" / "summary.json").exists())
            self.assertTrue((run_dir / "REPORT.md").exists())

    def test_profile_harness_manifest_records_external_application_resolved_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            application = root / "external" / "run.sh"
            application.parent.mkdir()
            application.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            application.chmod(0o755)
            run_dir = root / "profile" / "external_manifest_application"
            manifest = run_dir / "harness" / "profile_harness.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "task": "generic",
                        "application": str(application),
                        "workload": {"id": "generic/external-manifest", "shape": [4, 4], "dtype": "float16"},
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            env = profile_harness_env_expect_cwd(fake_bin, application.parent)

            subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )

            workflow = json.loads((run_dir / "analysis" / "profile_harness_run.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow["inputs"]["manifest"], "harness/profile_harness.json")
            self.assertEqual(workflow["inputs"]["application"], application.name)
            self.assertEqual(workflow["inputs"]["application_resolved_path"], str(application.resolve()))
            context = json.loads((run_dir / "analysis" / "profile_context.json").read_text(encoding="utf-8"))
            self.assertEqual(context["sources"]["application"]["artifact"], application.name)
            self.assertEqual(context["sources"]["application"]["resolved_path"], str(application.resolve()))
            self.assertIn(str(application.resolve()), (run_dir / "logs" / "command_msprof.txt").read_text())

    def test_profile_harness_rejects_missing_manifest_before_msprof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "missing_manifest"

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(run_dir / "harness" / "profile_harness.json"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("profile harness manifest not found", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())
            self.assertFalse((run_dir / "reports").exists())

    def test_profile_harness_rejects_invalid_manifest_before_msprof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "bad_manifest"
            manifest = run_dir / "harness" / "profile_harness.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"schema_version": 1}) + "\n", encoding="utf-8")

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing non-empty application", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())
            self.assertFalse((run_dir / "reports").exists())

    def test_profile_harness_rejects_manifest_missing_application_file_before_msprof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "missing_manifest_application"
            manifest = run_dir / "harness" / "profile_harness.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"schema_version": 1, "application": "missing_run.sh"}) + "\n", encoding="utf-8")

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("profile harness application not found", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())
            self.assertFalse((run_dir / "reports").exists())

    def test_profile_harness_rejects_manifest_application_directory_before_msprof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "directory_manifest_application"
            application_dir = run_dir / "harness" / "app_dir"
            application_dir.mkdir(parents=True)
            manifest = run_dir / "harness" / "profile_harness.json"
            manifest.write_text(json.dumps({"schema_version": 1, "application": "app_dir"}) + "\n", encoding="utf-8")

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("profile harness application is not a file", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())
            self.assertFalse((run_dir / "reports").exists())

    def test_profile_harness_rejects_missing_direct_application_before_msprof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "missing_direct_application"

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--application",
                    str(root / "missing_run.sh"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("application not found", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())
            self.assertFalse((run_dir / "reports").exists())

    def test_profile_harness_rejects_stale_collection_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            run_dir = root / "profile" / "stale"
            manifest, _application = write_profile_harness_fixture(run_dir)
            stale_report = run_dir / "reports" / "old.csv"
            stale_report.parent.mkdir(parents=True)
            stale_report.write_text("stale\n", encoding="utf-8")

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--manifest",
                    str(manifest),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already contains collection artifacts", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())

    def test_profile_harness_rejects_stale_direct_application_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            write_fake_msprof(fake_bin)
            application = root / "external_run.sh"
            application.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            application.chmod(0o755)
            run_dir = root / "profile" / "stale_direct"
            stale_report = run_dir / "reports" / "old.csv"
            stale_report.parent.mkdir(parents=True)
            stale_report.write_text("stale\n", encoding="utf-8")

            result = subprocess.run(
                [
                    *CLI,
                    "profile-harness",
                    "--run-dir",
                    str(run_dir),
                    "--application",
                    str(application),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                env=profile_harness_env(fake_bin),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already contains collection artifacts", result.stderr)
            self.assertFalse((run_dir / "logs" / "command_msprof.txt").exists())

    def test_verify_json_context_without_profiler_artifacts_does_not_create_profiler_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "profile" / "context_only"
            application = run_dir / "harness" / "run.sh"
            application.parent.mkdir(parents=True)
            application.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            application.chmod(0o755)
            verify_json = write_verify_json(run_dir / "context" / "verify.json")
            verify_data = json.loads(verify_json.read_text(encoding="utf-8"))
            profile_harness_module.write_profile_context(
                run_dir,
                manifest_path=None,
                manifest=None,
                application=application,
                verify_json_path=verify_json,
                verify_json=verify_data,
            )

            generate_report.main(["--run-dir", str(run_dir)])

            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("### Profile Harness Context", report)
            self.assertIn("No headline diagnosis generated", report)
            self.assertNotIn("Highest application-level operator duration", report)
            self.assertNotIn("Inspect Highest application-level operator duration", report)
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            self.assertTrue(all(value is None for value in summary.get("headlines", {}).values()))

    def test_analyze_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            self.assertEqual(summary["analysis_schema_version"], "1.3")
            self.assertEqual(summary["headlines"]["op_summary"]["name"], "MockMatMul")
            self.assertEqual(summary["headlines"]["op_summary"]["segment"], "app")
            self.assertIsNone(summary["headlines"]["op_summary"]["metric_scope"])
            self.assertEqual(summary["headlines"]["pipe_utilization"]["value"], 86.0)
            self.assertEqual(summary["headlines"]["pipe_utilization"]["segment"], "op")
            self.assertIsNone(summary["headlines"]["pipe_utilization"]["metric_scope"])
            self.assertEqual(summary["headlines"]["memory"]["name"], "metric")
            self.assertEqual(summary["headlines"]["memory"]["field"], "GM Read Bandwidth(GB/s)")
            self.assertEqual(summary["headlines"]["memory"]["value"], 700.0)
            self.assertEqual(summary["headlines"]["memory"]["field_kind"], "memory_bandwidth")
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            memory_signal = next(signal for signal in dimensions["memory_cache_movement"]["signals"] if signal["group"] == "memory")
            self.assertEqual(memory_signal["segment"], "op")
            self.assertIsNone(memory_signal["metric_scope"])
            self.assertEqual(memory_signal["field"], "Value")
            self.assertIn("headlines.memory.raw_row.Value", memory_signal["field_ref"])
            self.assertIn("headlines.memory.field=GM Read Bandwidth(GB/s)", memory_signal["field_ref"])
            self.assertNotIn("headlines.memory.raw_row.GM Read Bandwidth(GB/s)", memory_signal["field_ref"])
            self.assertIsNone(summary["stdout_sections"]["occupancy_summary"])
            self.assertFalse(any("occupancy" in warning.lower() for warning in summary["warnings"]))
            self.assertTrue((run_dir / "analysis" / "key_metrics.txt").exists())
            self.assertTrue((run_dir / "analysis" / "simulator_hotspots.json").exists())
            index = raw_artifact_index(run_dir)
            records = raw_artifacts_by_key(run_dir)
            self.assertEqual(index["raw_artifact_index_schema_version"], "1.0")
            self.assertTrue((run_dir / "analysis" / "raw_artifact_index.json").exists())
            self.assertNotIn("raw_artifact_index_schema_version", summary)
            self.assertEqual(
                records[("op_summary", "reports/PROF_001/mindstudio_profiler_output/op_summary_001.csv")]["segment"],
                "app",
            )
            self.assertEqual(
                records[("pipe_utilization", "reports/OPPROF_001/PipeUtilization.csv")]["parser"],
                "csv",
            )
            self.assertEqual(
                records[("app_timeline", "reports/PROF_001/mindstudio_profiler_output/msprof_001.json")]["row_count"],
                2,
            )
            self.assertEqual(
                records[("simulator_trace", "reports/OPPROF_001/trace.json")]["segment"],
                "simulator",
            )
            for artifact in [item["artifact"] for item in index["artifacts"]]:
                self.assertFalse(Path(artifact).is_absolute())
                self.assertNotIn(str(Path(tmp)), artifact)

    def test_analyze_real_cann_minimal_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_run(Path(tmp))
            opprof_dir = run_dir / "reports" / "OPPROF_001"
            (opprof_dir / "visualize_data.bin").write_bytes(b"viz")
            dump_dir = opprof_dir / "dump"
            dump_dir.mkdir()
            (dump_dir / "DeviceProf1.bin").write_bytes(b"device")
            (dump_dir / "duration.bin").write_bytes(b"duration")
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            self.assertEqual(summary["headlines"]["op_summary"]["name"], "sanitized_kernel")
            self.assertEqual(summary["headlines"]["op_summary"]["segment"], "app")
            self.assertIsNone(summary["headlines"]["op_summary"]["metric_scope"])
            self.assertEqual(summary["headlines"]["op_summary"]["value"], 42399.12)
            self.assertEqual(summary["headlines"]["task_time"]["name"], "sanitized_kernel")
            self.assertEqual(summary["headlines"]["op_basic_info"]["name"], "sanitized_operator_kernel")
            self.assertEqual(summary["files"]["memory"][0]["row_count"], 2)
            self.assertEqual(summary["files"]["memory"][0]["segment"], "op")
            self.assertIsNone(summary["files"]["memory"][0]["metric_scope"])
            self.assertEqual(summary["headlines"]["memory"]["name"], "vector0")
            self.assertEqual(summary["headlines"]["memory"]["file"], "reports/OPPROF_001/Memory.csv")
            self.assertEqual(summary["headlines"]["memory"]["segment"], "op")
            self.assertIsNone(summary["headlines"]["memory"]["metric_scope"])
            self.assertEqual(summary["headlines"]["memory"]["field"], "UB_to_GM_bw_usage_rate(%)")
            self.assertEqual(summary["headlines"]["memory"]["value"], 0.357273)
            self.assertEqual(summary["headlines"]["memory"]["field_kind"], "memory_usage_rate")
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            self.assertEqual(dimensions["hot_path_dispatch"]["status"], "available")
            self.assertEqual(dimensions["pipe_arithmetic_mix"]["status"], "available")
            self.assertEqual(dimensions["memory_cache_movement"]["status"], "available")
            self.assertIn("headlines.op_summary.raw_row.Task Duration(us)", dimensions["hot_path_dispatch"]["evidence_refs"][0])
            self.assertTrue(summary["optimization_directions"])
            first_direction = summary["optimization_directions"][0]
            self.assertEqual(first_direction["rank"], 1)
            self.assertIn("evidence", first_direction)
            self.assertTrue(first_direction["requires_artifacts"])
            self.assertEqual(first_direction["missing_artifacts"], [])
            self.assertIn("evidence_id", first_direction["evidence"][0])
            self.assertIn("confidence", first_direction)
            self.assertIn("effort", first_direction)
            self.assertEqual(summary["next_collection_actions"], [])
            records = raw_artifacts_by_key(run_dir)
            app_timeline = records[("app_timeline", "reports/PROF_001/mindstudio_profiler_output/msprof_001.json")]
            self.assertEqual(app_timeline["parser"], "json")
            self.assertEqual(app_timeline["segment"], "app")
            self.assertEqual(app_timeline["status"], "parsed")
            self.assertNotIn("app_timeline", summary["headlines"])
            readiness = summary["evidence_readiness"]
            self.assertEqual(readiness["level"], "directional")
            self.assertIn("app_timing", readiness["available_evidence_families"])
            self.assertIn("memory_cache", readiness["available_evidence_families"])
            self.assertTrue(readiness["unparsed_binary_artifacts"])
            binary = records[("unparsed_profiler_binary", "reports/OPPROF_001/visualize_data.bin")]
            self.assertEqual(binary["parser"], "none")
            self.assertEqual(binary["status"], "unparsed")
            self.assertEqual(binary["segment"], "op")
            self.assertEqual(binary["size_bytes"], 3)
            self.assertEqual(binary["known_role"], "MindStudio visualization artifact")
            self.assertEqual(binary["diagnosis_role"], "not_used")
            device = records[("unparsed_profiler_binary", "reports/OPPROF_001/dump/DeviceProf1.bin")]
            self.assertEqual(device["parser"], "none")
            self.assertEqual(device["status"], "unparsed")
            self.assertEqual(device["known_role"], "internal device profiling dump")
            duration = records[("unparsed_profiler_binary", "reports/OPPROF_001/dump/duration.bin")]
            self.assertEqual(duration["known_role"], "internal raw duration dump")
            self.assertNotIn("unparsed_profiler_binary", json.dumps(summary["headlines"]))

    def test_evidence_readiness_levels_for_minimal_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            empty = root / "empty"
            empty.mkdir()
            run([*CLI, "analyze", "--run-dir", str(empty)])
            self.assertEqual(summary_json(empty)["evidence_readiness"]["level"], "insufficient")

            timing_only = root / "timing_only"
            write_minimal_app_timing(timing_only)
            run([*CLI, "analyze", "--run-dir", str(timing_only)])
            timing_readiness = summary_json(timing_only)["evidence_readiness"]
            self.assertEqual(timing_readiness["level"], "triage_only")
            self.assertIn("app_timing", timing_readiness["available_evidence_families"])
            self.assertIn("operator_metric", timing_readiness["missing_evidence_families"])
            self.assertIn(
                "propose focused kernel code experiment without stronger context",
                timing_readiness["blocked_claims"],
            )

            pipe_only = root / "pipe_only"
            write_minimal_pipe_op(pipe_only)
            run([*CLI, "analyze", "--run-dir", str(pipe_only)])
            pipe_readiness = summary_json(pipe_only)["evidence_readiness"]
            self.assertEqual(pipe_readiness["level"], "triage_only")
            self.assertIn("pipe_utilization", pipe_readiness["available_evidence_families"])
            self.assertIn("app_timing", pipe_readiness["missing_evidence_families"])

            app_pipe = root / "app_pipe"
            write_minimal_app_timing(app_pipe)
            write_minimal_pipe_op(app_pipe)
            run([*CLI, "analyze", "--run-dir", str(app_pipe)])
            app_pipe_readiness = summary_json(app_pipe)["evidence_readiness"]
            self.assertEqual(app_pipe_readiness["level"], "directional")
            self.assertIn("rank first AI Core pipe inspection direction", app_pipe_readiness["allowed_claims"])
            self.assertIn("source-line or instruction attribution without simulator/source artifacts", app_pipe_readiness["blocked_claims"])

    def test_evidence_readiness_does_not_promote_simulator_or_binary_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            simulator_only = root / "simulator_only"
            sim_dir = simulator_only / "reports" / "OPPROF_001" / "simulator"
            sim_dir.mkdir(parents=True)
            (sim_dir / "trace.json").write_text(json.dumps({"traceEvents": [{"name": "VECTOR", "dur": 5}]}), encoding="utf-8")
            (sim_dir / "visualize_data.bin").write_bytes(b"simviz")
            run([*CLI, "analyze", "--run-dir", str(simulator_only)])
            sim_summary = summary_json(simulator_only)
            sim_readiness = sim_summary["evidence_readiness"]
            self.assertEqual(sim_readiness["level"], "insufficient")
            self.assertIn("simulator_source_pipeline", sim_readiness["available_evidence_families"])
            self.assertIn("app_timing", sim_readiness["missing_evidence_families"])
            self.assertIn("operator_metric", sim_readiness["missing_evidence_families"])
            sim_records = raw_artifacts_by_key(simulator_only)
            sim_binary = sim_records[("unparsed_profiler_binary", "reports/OPPROF_001/simulator/visualize_data.bin")]
            self.assertEqual(sim_binary["known_role"], "simulator visualization artifact")
            self.assertEqual(sim_binary["diagnosis_role"], "not_used")

            binary_only = root / "binary_only"
            op_dir = binary_only / "reports" / "OPPROF_001" / "dump"
            op_dir.mkdir(parents=True)
            (op_dir / "DeviceProf0.bin").write_bytes(b"device")
            (op_dir / "duration.bin").write_bytes(b"duration")
            run([*CLI, "analyze", "--run-dir", str(binary_only)])
            binary_readiness = summary_json(binary_only)["evidence_readiness"]
            self.assertEqual(binary_readiness["level"], "insufficient")
            self.assertEqual(binary_readiness["available_evidence_families"], [])
            self.assertTrue(binary_readiness["unparsed_binary_artifacts"])

    def test_analyze_real_l2cache_minimal_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_l2cache_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
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
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            self.assertEqual(dimensions["memory_cache_movement"]["status"], "available")
            self.assertEqual(summary["optimization_directions"], [])

    def test_analyze_real_default_vector_minimal_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
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
            self.assertEqual(summary["metric_scope"]["value"], "Default")
            self.assertTrue(summary["metric_scope"]["known"])
            self.assertEqual(summary["next_collection_actions"], [])

    def test_analyze_pipe_default_followup_fixture_clears_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_pipe_default_followup_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            self.assertEqual(summary["metric_scope"]["value"], "PipeUtilization")
            self.assertEqual(summary["next_collection_actions"], [])
            pipe_files = {
                Path(item["path"]).relative_to(run_dir).as_posix(): item
                for item in summary["files"]["pipe_utilization"]
            }
            self.assertEqual(pipe_files["reports/op/OPPROF_001/PipeUtilization.csv"]["segment"], "op")
            self.assertEqual(pipe_files["reports/op/OPPROF_001/PipeUtilization.csv"]["metric_scope"], "PipeUtilization")
            self.assertEqual(
                pipe_files["reports/followups/collect_default_metric_followup/OPPROF_001/PipeUtilization.csv"]["segment"],
                "followup:collect_default_metric_followup",
            )
            self.assertEqual(
                pipe_files["reports/followups/collect_default_metric_followup/OPPROF_001/PipeUtilization.csv"]["metric_scope"],
                "Default",
            )
            arithmetic = summary["headlines"]["arithmetic_utilization"]
            self.assertEqual(arithmetic["segment"], "followup:collect_default_metric_followup")
            self.assertEqual(arithmetic["metric_scope"], "Default")
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            arithmetic_signal = next(
                signal
                for signal in dimensions["pipe_arithmetic_mix"]["signals"]
                if signal["group"] == "arithmetic_utilization"
            )
            self.assertEqual(arithmetic_signal["segment"], "followup:collect_default_metric_followup")
            self.assertEqual(arithmetic_signal["metric_scope"], "Default")
            evidence = [
                item
                for direction in summary["optimization_directions"]
                for item in direction["evidence"]
                if item["artifact"] == "reports/followups/collect_default_metric_followup/OPPROF_001/ArithmeticUtilization.csv"
            ]
            self.assertTrue(evidence)
            self.assertTrue(all(item["segment"] == "followup:collect_default_metric_followup" for item in evidence))
            self.assertTrue(all(item["metric_scope"] == "Default" for item in evidence))
            self.assertEqual(
                summary["headlines"]["arithmetic_utilization"]["file"],
                "reports/followups/collect_default_metric_followup/OPPROF_001/ArithmeticUtilization.csv",
            )
            self.assertEqual(
                summary["headlines"]["resource_conflict"]["file"],
                "reports/followups/collect_default_metric_followup/OPPROF_001/ResourceConflictRatio.csv",
            )
            records = raw_artifacts_by_key(run_dir)
            self.assertEqual(
                records[("pipe_utilization", "reports/op/OPPROF_001/PipeUtilization.csv")]["segment"],
                "op",
            )
            self.assertEqual(
                records[("pipe_utilization", "reports/op/OPPROF_001/PipeUtilization.csv")]["metric_scope"],
                "PipeUtilization",
            )
            self.assertEqual(
                records[
                    (
                        "arithmetic_utilization",
                        "reports/followups/collect_default_metric_followup/OPPROF_001/ArithmeticUtilization.csv",
                    )
                ]["segment"],
                "followup:collect_default_metric_followup",
            )
            self.assertEqual(
                records[
                    (
                        "arithmetic_utilization",
                        "reports/followups/collect_default_metric_followup/OPPROF_001/ArithmeticUtilization.csv",
                    )
                ]["metric_scope"],
                "Default",
            )

    def test_analyze_real_occupancy_stdout_summary_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_occupancy_stdout_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            occupancy = summary["stdout_sections"]["occupancy_summary"]
            key_metrics = (run_dir / "analysis" / "key_metrics.txt").read_text()
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            op_basic_signal = next(
                signal
                for signal in dimensions["tiling_core_balance"]["signals"]
                if signal["group"] == "op_basic_info"
            )

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
            self.assertEqual(op_basic_signal["field"], "task_duration")
            self.assertIn("headlines.op_basic_info.first_row.task_duration", op_basic_signal["field_ref"])
            self.assertIn("## Occupancy Summary", key_metrics)
            self.assertIn("| 1 | core3 vector0 took more time than other vector cores. | logs/msprof_occupancy.stdout |", key_metrics)
            stdout_records = [
                item
                for item in raw_artifact_index(run_dir)["artifacts"]
                if item["group"] == "stdout_occupancy_summary"
            ]
            self.assertEqual(len(stdout_records), 1)
            self.assertEqual(stdout_records[0]["artifact"], "logs/msprof_occupancy.stdout")
            self.assertEqual(stdout_records[0]["parser"], "stdout")
            self.assertEqual(stdout_records[0]["segment"], "unknown")
            self.assertEqual(stdout_records[0]["row_count"], 2)

    def test_analyze_real_roofline_stdout_summary_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_roofline_stdout_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
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
            stdout_records = [
                item
                for item in raw_artifact_index(run_dir)["artifacts"]
                if item["group"] == "stdout_roofline_summary"
            ]
            self.assertEqual(len(stdout_records), 1)
            self.assertEqual(stdout_records[0]["artifact"], "logs/msprof_roofline.stdout")
            self.assertEqual(stdout_records[0]["row_count"], 1)

    def test_analyze_source_shape_op_summary_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_summary_variant_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
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
            directions = summary["optimization_directions"]
            self.assertEqual(len(directions), 1)
            self.assertEqual(directions[0]["id"], "focus_hot_path")
            self.assertIn("without enough corroborating metric families", directions[0]["impact_basis"])
            self.assertNotIn("rewrite", json.dumps(directions).lower())

    def test_analyze_target_identity_match_allows_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_target_identity_run(Path(tmp), expected="main_kernel", observed="main_kernel_mix_aic")
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            identity = summary["target_identity"]
            self.assertEqual(identity["status"], "match")
            self.assertEqual(identity["expected"]["names"], ["main_kernel"])
            self.assertEqual(identity["observed"][0]["name"], "main_kernel_mix_aic")
            self.assertFalse(any("target identity mismatch" in warning for warning in summary["warnings"]))
            self.assertTrue(summary["optimization_directions"])

    def test_analyze_target_identity_mismatch_blocks_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_target_identity_run(
                Path(tmp),
                expected="main_kernel",
                observed="Cast_15ccf3aee15572ed7572778d4afbef60_high_performance_210010000",
            )
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            identity = summary["target_identity"]
            self.assertEqual(identity["status"], "mismatch")
            self.assertEqual(identity["expected"]["names"], ["main_kernel"])
            self.assertEqual(identity["observed"][0]["name"], "Cast_15ccf3aee15572ed7572778d4afbef60_high_performance_210010000")
            self.assertTrue(any("target identity mismatch" in warning for warning in summary["warnings"]))
            self.assertEqual(summary["optimization_directions"], [])

    def test_analyze_target_identity_does_not_match_inner_substring(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_target_identity_run(
                Path(tmp),
                expected="Mul",
                observed="MatMul",
            )
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            identity = summary["target_identity"]
            self.assertEqual(identity["status"], "mismatch")
            self.assertEqual(identity["observed"][0]["status"], "mismatch")
            self.assertEqual(summary["optimization_directions"], [])

    def test_analyze_target_identity_partial_mismatch_blocks_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_target_identity_run(
                Path(tmp),
                expected="main_kernel",
                observed="main_kernel_mix_aic",
                app_observed="framework_helper_kernel",
            )
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            identity = summary["target_identity"]
            self.assertEqual(identity["status"], "partial_mismatch")
            statuses = {item["group"]: item["status"] for item in identity["observed"]}
            self.assertEqual(statuses["op_basic_info"], "match")
            self.assertEqual(statuses["op_summary"], "mismatch")
            self.assertTrue(any("target identity partial_mismatch" in warning for warning in summary["warnings"]))
            self.assertEqual(summary["optimization_directions"], [])

    def test_analyze_target_identity_missing_observed_blocks_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_missing_observed_target_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            identity = summary["target_identity"]
            self.assertEqual(identity["status"], "missing_observed")
            self.assertEqual(identity["expected"]["names"], ["main_kernel"])
            self.assertEqual(identity["observed"], [])
            self.assertTrue(any("target identity missing observed" in warning for warning in summary["warnings"]))
            self.assertEqual(summary["optimization_directions"], [])

    def test_analyze_target_identity_unverified_without_expected_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_target_identity_run(
                Path(tmp),
                observed="Cast_15ccf3aee15572ed7572778d4afbef60_high_performance_210010000",
                include_expected=False,
            )
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            self.assertEqual(summary["target_identity"]["status"], "unverified")
            self.assertFalse(any("target identity" in warning for warning in summary["warnings"]))
            self.assertTrue(summary["optimization_directions"])

    def test_analyze_tilelang_context_infers_main_kernel_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_target_identity_run(
                Path(tmp),
                observed="main_kernel_mix_aic",
                include_expected=False,
                tilelang_context=True,
            )
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            identity = summary["target_identity"]
            self.assertEqual(identity["status"], "match")
            self.assertEqual(identity["expected"]["names"], ["main_kernel"])
            self.assertTrue(identity["expected"]["inferred"])
            self.assertEqual(identity["expected"]["field_ref"], "inferred:tilelang_default_kernel")
            self.assertTrue(summary["optimization_directions"])

    def test_analyze_tilelang_context_inferred_target_catches_framework_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_target_identity_run(
                Path(tmp),
                observed="Cast_15ccf3aee15572ed7572778d4afbef60_high_performance_210010000",
                include_expected=False,
                tilelang_context=True,
            )
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            identity = summary["target_identity"]
            self.assertEqual(identity["status"], "mismatch")
            self.assertEqual(identity["expected"]["names"], ["main_kernel"])
            self.assertTrue(identity["expected"]["inferred"])
            self.assertTrue(any("target identity mismatch" in warning for warning in summary["warnings"]))
            self.assertEqual(summary["optimization_directions"], [])

    def test_analyze_explicit_target_overrides_tilelang_default_from_earlier_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_explicit_target_precedence_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            identity = summary["target_identity"]
            self.assertEqual(identity["status"], "match")
            self.assertEqual(identity["expected"]["names"], ["custom_kernel"])
            self.assertEqual(identity["expected"]["artifact"], "analysis/tilelang_context.json")
            self.assertNotIn("inferred", identity["expected"])
            self.assertTrue(summary["optimization_directions"])

    def test_analyze_simulator_context_records_raw_field_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_simulator_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            signals = dimensions["source_pipeline_context"]["signals"]
            model = json.loads((run_dir / "analysis" / "simulator_hotspots.json").read_text())

            self.assertEqual(model["simulator_hotspot_model_schema_version"], "1.1")
            self.assertEqual(dimensions["source_pipeline_context"]["model_artifact"], "analysis/simulator_hotspots.json")
            self.assertTrue(model["instructions"])
            self.assertTrue(model["pipeline_events"])
            self.assertEqual(model["inputs"][0]["parser_status"], "empty")
            self.assertTrue(any(signal["field"] == "running_time(us)" for signal in signals))
            self.assertTrue(any(signal["field"] == "traceEvents[].dur" for signal in signals))
            self.assertTrue(any("source_pipeline_context.signals.field=running_time(us)" in signal["field_ref"] for signal in signals))
            self.assertTrue(any("source_pipeline_context.signals.value" in signal["field_ref"] for signal in signals))
            self.assertTrue(any(signal.get("evidence_id") for signal in signals))
            self.assertTrue(any(signal["value"] is not None for signal in signals))
            self.assertTrue(signals)
            self.assertTrue(all(signal["segment"] == "simulator" for signal in signals))
            self.assertTrue(all(signal["metric_scope"] is None for signal in signals))
            self.assertEqual(summary["optimization_directions"], [])
            records = raw_artifacts_by_key(run_dir)
            self.assertIn(
                ("simulator_csv", "reports/OPPROF_001/simulator/core3.veccore0/core3.veccore0_code_exe.csv"),
                records,
            )
            self.assertIn(
                ("simulator_csv", "reports/OPPROF_001/simulator/core3.veccore0/core3.veccore0_instr_exe.csv"),
                records,
            )
            self.assertEqual(records[("simulator_trace", "reports/OPPROF_001/simulator/trace.json")]["segment"], "simulator")

    def test_analyze_simulator_trace_uses_largest_duration_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_multi_duration_trace_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            trace_signals = [
                signal
                for signal in dimensions["source_pipeline_context"]["signals"]
                if signal["artifact"].endswith("trace.json")
            ]

            self.assertEqual(len(trace_signals), 1)
            self.assertEqual(trace_signals[0]["field"], "traceEvents[].dur")
            self.assertEqual(trace_signals[0]["signal"], "dominant_pipeline")
            self.assertEqual(trace_signals[0]["value"], 640.0)

    def test_analyze_simulator_top_level_trace_uses_largest_duration_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_top_level_trace_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            trace_signals = [
                signal
                for signal in dimensions["source_pipeline_context"]["signals"]
                if signal["artifact"].endswith("trace.json")
            ]

            self.assertEqual(len(trace_signals), 1)
            self.assertEqual(trace_signals[0]["field"], "traceEvents[].dur")
            self.assertEqual(trace_signals[0]["signal"], "dominant_top_level")
            self.assertEqual(trace_signals[0]["value"], 900.0)

    def test_simulator_model_keeps_per_core_trace_pipeline_artifacts_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_per_core_trace_only_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            model = json.loads((run_dir / "analysis" / "simulator_hotspots.json").read_text())

            rows = sorted(model["pipeline_events"], key=lambda row: row["artifact"])
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                [(row["artifact"], row["duration"]) for row in rows],
                [
                    ("reports/OPPROF_001/simulator/core0.veccore0/trace.json", 10.0),
                    ("reports/OPPROF_001/simulator/core1.veccore0/trace.json", 20.0),
                ],
            )
            for row in rows:
                self.assertIn(row["artifact"], row["field_ref"])

    def test_simulator_model_uses_per_core_trace_when_aggregate_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_invalid_aggregate_with_valid_per_core_trace_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            model = json.loads((run_dir / "analysis" / "simulator_hotspots.json").read_text())
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            inputs = {row["artifact"]: row["parser_status"] for row in model["inputs"]}
            self.assertEqual(inputs["reports/OPPROF_001/simulator/trace.json"], "invalid")
            self.assertEqual(inputs["reports/OPPROF_001/simulator/core0.veccore0/trace.json"], "parsed")
            self.assertEqual(len(model["pipeline_events"]), 1)
            self.assertEqual(
                model["pipeline_events"][0]["artifact"],
                "reports/OPPROF_001/simulator/core0.veccore0/trace.json",
            )
            self.assertEqual(model["pipeline_events"][0]["value"], 123.0)

            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            trace_signals = [
                signal
                for signal in dimensions["source_pipeline_context"]["signals"]
                if signal["artifact"].endswith("core0.veccore0/trace.json")
            ]
            self.assertEqual(len(trace_signals), 1)
            self.assertEqual(trace_signals[0]["signal"], "per_core_valid")
            self.assertEqual(trace_signals[0]["value"], 123.0)

    def test_analyze_simulator_csv_uses_largest_running_time_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_multi_row_simulator_csv_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            csv_signals = [
                signal
                for signal in dimensions["source_pipeline_context"]["signals"]
                if signal["artifact"].endswith("core0_instr_exe.csv")
            ]

            self.assertEqual(len(csv_signals), 1)
            self.assertEqual(csv_signals[0]["field"], "running_time(us)")
            self.assertEqual(csv_signals[0]["signal"], "dominant_instr")
            self.assertEqual(csv_signals[0]["value"], 75.0)

    def test_analyze_unreadable_optional_simulator_csv_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_unreadable_simulator_csv_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            signals = dimensions["source_pipeline_context"]["signals"]

            self.assertTrue((run_dir / "analysis" / "key_metrics.txt").exists())
            self.assertTrue(any(warning.startswith("invalid simulator csv") for warning in summary["warnings"]))
            self.assertEqual(signals[0]["field"], "file")
            self.assertEqual(signals[0]["kind"], "simulator_artifact")
            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])

    def test_analyze_op_basic_plus_simulator_only_does_not_emit_tiling_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_simulator_only_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            op_basic_signal = dimensions["tiling_core_balance"]["signals"][0]

            self.assertEqual(op_basic_signal["field"], "task_duration")
            self.assertIn("headlines.op_basic_info.first_row.task_duration", op_basic_signal["field_ref"])
            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])
            self.assertNotIn("inspect_tiling_core_balance", json.dumps(summary["optimization_directions"]))

    def test_analyze_op_basic_block_dim_can_emit_tiling_direction_with_field_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_block_dim_with_timing_sim_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            op_basic_signal = dimensions["tiling_core_balance"]["signals"][0]
            directions = {item["id"]: item for item in summary["optimization_directions"]}

            self.assertIsNone(op_basic_signal["field"])
            self.assertIsNone(op_basic_signal["value"])
            self.assertEqual(op_basic_signal["tiling_field"], "Block Dim")
            self.assertEqual(op_basic_signal["tiling_value"], 8.0)
            self.assertNotIn("headlines.op_basic_info.first_row.Block Dim", op_basic_signal["field_ref"])
            self.assertIn("inspect_tiling_core_balance", directions)
            evidence = json.dumps(directions["inspect_tiling_core_balance"]["evidence"])
            self.assertIn("headlines.op_basic_info.tiling_value", evidence)
            self.assertIn("headlines.op_basic_info.first_row.Block Dim", evidence)
            self.assertIn("headlines.op_basic_info.tiling_field=Block Dim", evidence)

    def test_analyze_op_basic_block_dim_without_timing_does_not_emit_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_block_dim_sim_only_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            op_basic_signal = dimensions["tiling_core_balance"]["signals"][0]

            self.assertIsNone(op_basic_signal["field"])
            self.assertIsNone(op_basic_signal["value"])
            self.assertEqual(op_basic_signal["tiling_field"], "Block Dim")
            self.assertEqual(op_basic_signal["tiling_value"], 8.0)
            self.assertEqual(summary["optimization_directions"], [])

    def test_analyze_op_basic_blank_block_dim_does_not_emit_tiling_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_invalid_block_dim_with_timing_sim_run(Path(tmp), "")
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            op_basic_signal = dimensions["tiling_core_balance"]["signals"][0]

            self.assertEqual(op_basic_signal["tiling_field"], "Block Dim")
            self.assertIsNone(op_basic_signal["tiling_value"])
            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])
            self.assertNotIn("inspect_tiling_core_balance", json.dumps(summary["optimization_directions"]))

    def test_analyze_op_basic_non_numeric_block_dim_does_not_emit_tiling_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_invalid_block_dim_with_timing_sim_run(Path(tmp), "not_recorded")
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            op_basic_signal = dimensions["tiling_core_balance"]["signals"][0]

            self.assertEqual(op_basic_signal["tiling_field"], "Block Dim")
            self.assertIsNone(op_basic_signal["tiling_value"])
            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])
            self.assertNotIn("inspect_tiling_core_balance", json.dumps(summary["optimization_directions"]))

    def test_analyze_op_basic_duration_only_does_not_emit_tiling_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_duration_only_with_timing_sim_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            op_basic_signal = dimensions["tiling_core_balance"]["signals"][0]

            self.assertEqual(op_basic_signal["field"], "Task Duration(us)")
            self.assertIn("headlines.op_basic_info.first_row.Task Duration(us)", op_basic_signal["field_ref"])
            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])
            self.assertNotIn("inspect_tiling_core_balance", json.dumps(summary["optimization_directions"]))

    def test_analyze_op_basic_duration_plus_block_dim_uses_tiling_evidence_for_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_duration_block_dim_with_timing_sim_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            op_basic_signal = dimensions["tiling_core_balance"]["signals"][0]
            directions = {item["id"]: item for item in summary["optimization_directions"]}

            self.assertEqual(op_basic_signal["field"], "Task Duration(us)")
            self.assertEqual(op_basic_signal["tiling_field"], "Block Dim")
            self.assertIn("inspect_tiling_core_balance", directions)
            evidence = json.dumps(directions["inspect_tiling_core_balance"]["evidence"])
            self.assertIn("headlines.op_basic_info.tiling_value", evidence)
            self.assertIn("headlines.op_basic_info.first_row.Block Dim", evidence)
            self.assertIn("headlines.op_basic_info.tiling_field=Block Dim", evidence)
            self.assertNotIn("headlines.op_basic_info.field=Task Duration(us)", evidence)

    def test_analyze_name_only_op_basic_does_not_emit_tiling_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_name_only_op_basic_with_timing_sim_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            op_basic_signal = dimensions["tiling_core_balance"]["signals"][0]

            self.assertIsNone(op_basic_signal["field"])
            self.assertNotIn("headlines.op_basic_info.first_row.Task Duration(us)", op_basic_signal["field_ref"])
            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])
            self.assertNotIn("inspect_tiling_core_balance", json.dumps(summary["optimization_directions"]))

    def test_analyze_malformed_optional_trace_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_malformed_trace_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}

            self.assertTrue((run_dir / "analysis" / "key_metrics.txt").exists())
            self.assertTrue(any(warning.startswith("invalid simulator trace") for warning in summary["warnings"]))
            self.assertEqual(dimensions["source_pipeline_context"]["signals"][0]["field"], "file")
            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])
            self.assertNotIn("inspect_tiling_core_balance", json.dumps(summary["optimization_directions"]))
            trace_record = raw_artifacts_by_key(run_dir)[("simulator_trace", "reports/OPPROF_001/simulator/trace.json")]
            self.assertEqual(trace_record["status"], "invalid")
            self.assertEqual(trace_record["row_count"], 0)
            self.assertTrue(trace_record["warnings"][0].startswith("invalid json reports/OPPROF_001/simulator/trace.json"))
            self.assertIn(trace_record["warnings"][0], raw_artifact_index(run_dir)["warnings"])

    def test_generate_report_empty_direction_model_does_not_use_legacy_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_header_only_op_summary_run(Path(tmp) / "profile")
            run([*CLI, "report", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            optimization = report.split("## 4. Optimization Directions", 1)[1].split(
                "## 5. Confidence And Caveats",
                1,
            )[0]

            self.assertEqual(summary["optimization_directions"], [])
            self.assertIn("No ranked optimization direction generated from the available evidence.", optimization)
            self.assertNotIn("Inspect Highest application-level operator duration", optimization)
            self.assertNotIn("= n/a", optimization)
            op_summary_record = raw_artifacts_by_key(run_dir)[
                ("op_summary", "reports/PROF_001/mindstudio_profiler_output/op_summary_001.csv")
            ]
            self.assertEqual(op_summary_record["status"], "empty")
            self.assertEqual(op_summary_record["columns"], ["Op Name", "Task Duration(us)"])
            self.assertEqual(op_summary_record["row_count"], 0)

    def test_analyze_header_only_op_basic_does_not_emit_tiling_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_header_only_op_basic_with_timing_sim_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())

            self.assertEqual([item["id"] for item in summary["optimization_directions"]], ["focus_hot_path"])
            self.assertNotIn("inspect_tiling_core_balance", json.dumps(summary["optimization_directions"]))

    def test_analyze_prefers_op_statistic_timing_before_op_basic_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_statistic_op_basic_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            first_evidence = summary["optimization_directions"][0]["evidence"][0]

            self.assertEqual(summary["optimization_directions"][0]["id"], "focus_hot_path")
            self.assertEqual(first_evidence["artifact"], "reports/PROF_001/mindstudio_profiler_output/op_statistic_001.csv")
            self.assertIn("headlines.op_statistic.value", first_evidence["field_ref"])
            self.assertNotIn("OpBasicInfo.csv", first_evidence["artifact"])

    def test_analyze_pipe_l2_emits_memory_direction_without_memory_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_pipe_l2_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            directions = {item["id"]: item for item in summary["optimization_directions"]}

            self.assertIn("inspect_memory_movement", directions)
            evidence = json.dumps(directions["inspect_memory_movement"]["evidence"])
            self.assertIn("reports/OPPROF_001/L2Cache.csv", evidence)
            self.assertIn("headlines.l2_cache.value", evidence)

    def test_analyze_conflict_simulator_emits_conflict_direction_without_pipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_conflict_simulator_run(Path(tmp))
            run([*CLI, "analyze", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            directions = {item["id"]: item for item in summary["optimization_directions"]}

            self.assertIn("inspect_resource_conflict", directions)
            self.assertIn(
                "simulator source/pipeline context",
                directions["inspect_resource_conflict"]["impact_basis"],
            )
            self.assertNotIn("another operator-level metric family", directions["inspect_resource_conflict"]["impact_basis"])
            evidence = json.dumps(directions["inspect_resource_conflict"]["evidence"])
            self.assertIn("reports/OPPROF_001/ResourceConflictRatio.csv", evidence)
            self.assertIn("reports/OPPROF_001/simulator/trace.json", evidence)

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

            self.assertEqual(comparison["comparison_schema_version"], "1.2")
            self.assertIn("runs", comparison)
            self.assertIn("compatibility", comparison)
            self.assertIn("benchmark", comparison)
            self.assertIn("headlines", comparison)
            self.assertIn("evidence", comparison)
            self.assertIn("design_feedback", comparison)
            self.assertIn("verdict", comparison)
            self.assertIn("warnings", comparison)
            self.assertEqual(comparison["design_feedback"]["contract_version"], "1.0")
            self.assertIn(comparison["design_feedback"]["status"], {"ready", "incomplete", "blocked"})
            self.assertTrue(comparison["design_feedback"]["questions"])
            self.assertEqual(comparison["runs"]["a"]["run_dir"], "<abs-path>/run_a")
            self.assertEqual(comparison["runs"]["b"]["run_dir"], "<abs-path>/run_b")
            self.assertIn("# Ascend Run Comparison", report)
            self.assertIn("## Verdict", report)
            self.assertIn("## Profiler Headlines", report)
            self.assertIn("## Design Feedback", report)

    def test_summarize_candidate_writes_keep_and_preserves_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = fresh_run(root / "profile", "candidate")
            attach_tilelang_context(root, run_dir)
            reports_before = reports_file_snapshot(run_dir)

            run([*CLI, "summarize-candidate", "--run-dir", str(run_dir)])
            candidate = json.loads((run_dir / "analysis" / "candidate_summary.json").read_text(encoding="utf-8"))
            markdown = (run_dir / "analysis" / "candidate_summary.md").read_text(encoding="utf-8")

            self.assertEqual(candidate["candidate_summary_schema_version"], "1.1")
            self.assertEqual(candidate["verdict"]["decision"], "keep")
            self.assertEqual(candidate["run"]["workload"]["id"], "tilelang-ascend/kernel/v1/4096x2048-f16-cases2")
            self.assertEqual(candidate["run"]["runtime"]["mean_ms"], 1.25)
            self.assertTrue(candidate["run"]["profiler_evidence"]["evidence_present"])
            self.assertIn("design_feedback", candidate)
            self.assertEqual(candidate["design_feedback"]["contract_version"], "1.0")
            self.assertIn(candidate["design_feedback"]["status"], {"ready", "incomplete", "blocked"})
            self.assertTrue(candidate["design_feedback"]["questions"])
            self.assertTrue(any(item["source"] == "optimization_directions" for item in candidate["inspection_targets"]))
            self.assertTrue(any(item["source"] == "simulator_hotspots" for item in candidate["inspection_targets"]))
            self.assertIn("# TileLang Candidate Summary", markdown)
            self.assertIn("## Design Feedback", markdown)
            self.assertEqual(reports_before, reports_file_snapshot(run_dir))

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

    def test_generate_provenance_from_complete_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            reports_before = sorted(path.relative_to(run_dir).as_posix() for path in (run_dir / "reports").rglob("*"))
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
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
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
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

    def test_generate_provenance_cli_collects_missing_environment_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "profile" / "cli_env_capture"
            fake_toolkit = root / "fake-toolkit"
            fake_bin = fake_toolkit / "bin"
            fake_bin.mkdir(parents=True)
            msprof = fake_bin / "msprof"
            npu_smi = fake_bin / "npu-smi"
            msprof.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
            npu_smi.write_text(
                "#!/usr/bin/env sh\n"
                "if [ \"$1\" = \"info\" ]; then\n"
                "  printf '| 0 910B2 | OK |\\n'\n"
                "fi\n",
                encoding="utf-8",
            )
            msprof.chmod(0o755)
            npu_smi.chmod(0o755)
            (fake_toolkit / "version.cfg").write_text(
                "toolkit_running_version=[cli-captured-version]\n",
                encoding="utf-8",
            )
            env = test_env()
            env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
            env["ASCEND_HOME_PATH"] = str(fake_toolkit)

            subprocess.run(
                [*CLI, "provenance", "--run-dir", str(run_dir)],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual(provenance["cann_version"]["value"], "cli-captured-version")
            self.assertEqual(provenance["hardware"]["summary"]["value"], "1 x 910B2; health OK")
            self.assertEqual(
                provenance["environment"]["selected"]["ASCEND_HOME_PATH"]["source"]["artifact"],
                "logs/relevant_env.txt",
            )
            for source in ["logs/cann_version.cfg", "logs/npu_smi_info.stdout", "logs/relevant_env.txt"]:
                self.assertIn(source, provenance["sources"])
                self.assertTrue((run_dir / source).exists())

    def test_generate_provenance_cli_uses_msprof_from_command_log_for_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "profile" / "cli_command_msprof"
            logs = run_dir / "logs"
            reports = run_dir / "reports"
            logs.mkdir(parents=True)
            reports.mkdir(parents=True)

            profiled_toolkit = root / "profiled-toolkit"
            path_toolkit = root / "path-toolkit"
            profiled_msprof = profiled_toolkit / "bin" / "msprof"
            path_msprof = path_toolkit / "bin" / "msprof"
            profiled_msprof.parent.mkdir(parents=True)
            path_msprof.parent.mkdir(parents=True)
            profiled_msprof.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
            path_msprof.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
            profiled_msprof.chmod(0o755)
            path_msprof.chmod(0o755)
            (profiled_toolkit / "version.cfg").write_text(
                "toolkit_running_version=[profiled-msprof-version]\n",
                encoding="utf-8",
            )
            (path_toolkit / "version.cfg").write_text(
                "toolkit_running_version=[path-msprof-version]\n",
                encoding="utf-8",
            )
            (logs / "command_msprof.txt").write_text(
                f"{profiled_msprof} --output={reports / 'app'} --application={run_dir / 'harness' / 'run.sh'}\n",
                encoding="utf-8",
            )
            env = test_env()
            env["PATH"] = f"{path_msprof.parent}{os.pathsep}{env.get('PATH', '')}"

            subprocess.run(
                [*CLI, "provenance", "--run-dir", str(run_dir)],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual(provenance["cann_version"]["value"], "profiled-msprof-version")
            self.assertNotIn(
                "path-msprof-version",
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
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
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
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
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
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
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
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
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
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
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
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
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

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
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

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
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

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/app", "reports/op"])
            self.assertEqual(provenance["profile_output"]["value"], "reports/app")
            self.assertIn("Missing profiler stdout/status logs", "\n".join(provenance["warnings"]))

            run([*CLI, "report", "--run-dir", str(run_dir)])
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

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/app", "reports/op"])
            self.assertEqual(provenance["profile_output"]["value"], "reports/app")
            self.assertEqual(provenance["profile_command"]["value"], "msprof --output=reports/app --application=<abs-path>")
            self.assertNotIn("\\", provenance["profile_command"]["value"])

            run([*CLI, "report", "--run-dir", str(run_dir)])
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

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertNotIn("profile_output", provenance)
            self.assertNotIn("profile_outputs", provenance)
            self.assertIn("Missing profiler stdout/status logs", "\n".join(provenance["warnings"]))

            run([*CLI, "report", "--run-dir", str(run_dir)])
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

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
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

    def test_generate_provenance_infers_followup_segment_from_existing_report_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_pipe_default_followup_run(Path(tmp) / "profile")

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            segments = provenance["profile_output_segments"]
            followup = segments["followups"]["collect_default_metric_followup"]

            self.assertEqual(followup["output"]["value"], "reports/followups/collect_default_metric_followup")
            self.assertEqual(followup["output"]["source"]["field"], "existing_report_dir")
            self.assertEqual(
                followup["resolved_output"]["value"],
                "reports/followups/collect_default_metric_followup/OPPROF_001",
            )
            self.assertEqual(followup["resolved_output"]["source"]["field"], "existing_report_dir")
            self.assertEqual(segments["op"]["output"]["value"], "reports/op")
            self.assertNotIn("status", followup)
            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/op"])
            self.assertNotIn(
                "reports/followups/collect_default_metric_followup",
                [item["value"] for item in provenance["profile_outputs"]],
            )

    def test_generate_provenance_does_not_treat_followup_logs_as_primary_profiler_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "followup_only"
            logs = run_dir / "logs"
            output = run_dir / "reports" / "followups" / "collect_default_metric_followup"
            resolved = output / "OPPROF_001"
            logs.mkdir(parents=True)
            resolved.mkdir(parents=True)
            (resolved / "OpBasicInfo.csv").write_text("Op Name,Task Duration(us)\nop_kernel,1\n", encoding="utf-8")
            (logs / "command_msprof_followup_collect_default_metric_followup.txt").write_text(
                f"msprof op --output={output} --application={run_dir / 'harness' / 'op.sh'} --aic-metrics=Default\n",
                encoding="utf-8",
            )
            (logs / "msprof_followup_collect_default_metric_followup.stdout").write_text(
                f"2026-06-02 09:00:19 [INFO]  Profiling results saved in {resolved}\n",
                encoding="utf-8",
            )
            (logs / "msprof_followup_collect_default_metric_followup.status").write_text("0\n", encoding="utf-8")
            (logs / "msprof_followup_collect_default_metric_followup.stderr").write_text("", encoding="utf-8")

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            followup = provenance["profile_output_segments"]["followups"]["collect_default_metric_followup"]

            self.assertNotIn("profile_output", provenance)
            self.assertNotIn("profile_outputs", provenance)
            self.assertNotIn("profiler_status", provenance)
            self.assertNotIn("profile_date", provenance)
            self.assertEqual(followup["output"]["value"], "reports/followups/collect_default_metric_followup")
            self.assertEqual(followup["output"]["source"]["artifact"], "logs/command_msprof_followup_collect_default_metric_followup.txt")
            self.assertEqual(followup["resolved_output"]["value"], "reports/followups/collect_default_metric_followup/OPPROF_001")
            self.assertEqual(followup["resolved_output"]["source"]["artifact"], "logs/msprof_followup_collect_default_metric_followup.stdout")
            self.assertEqual(followup["status"]["value"], "0")
            self.assertEqual(followup["status"]["source"]["artifact"], "logs/msprof_followup_collect_default_metric_followup.status")
            self.assertIn("logs/msprof_followup_collect_default_metric_followup.stderr", provenance["sources"])

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

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
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
            self.assertNotIn("collection_plan", provenance)

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

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
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

            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("- Profile outputs: app: reports/app", report)
            self.assertIn("resolved reports/app/PROF_<sanitized>", report)
            self.assertIn("op: reports/op", report)
            self.assertIn("resolved reports/op/OPPROF_<sanitized>", report)
            self.assertNotIn("- Profile output: reports/app/PROF_<sanitized>, reports/op/OPPROF_<sanitized>", report)

    def test_real_app_op_stdout_fixture_records_segmented_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_app_op_stdout_run(Path(tmp) / "profile")
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
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

            run([*CLI, "report", "--run-dir", str(run_dir)])
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

            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))

            self.assertEqual([item["value"] for item in provenance["profile_outputs"]], ["reports/app", "reports/op"])
            self.assertEqual(provenance["profile_output"]["value"], "reports/app")
            self.assertEqual(provenance["profile_output"]["source"]["artifact"], "logs/msprof_default.stdout")
            self.assertEqual(provenance["profile_outputs"][1]["source"]["artifact"], "logs/command_msprof_op.txt")

            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("- Profile outputs: app: reports/app (source: `logs/command_msprof.txt`; `--output`)", report)
            self.assertIn("resolved reports/app (source: `logs/msprof_default.stdout`", report)
            self.assertIn("reports/op (source: `logs/command_msprof_op.txt`; `--output`)", report)
            self.assertNotIn("- Profile output: not recorded", report)

    def test_generate_provenance_missing_logs_collects_environment_without_touching_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            shutil.rmtree(run_dir / "logs")
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            provenance = json.loads((run_dir / "analysis" / "provenance.json").read_text(encoding="utf-8"))
            warnings = "\n".join(provenance["warnings"])

            self.assertNotIn("Missing logs/ directory", warnings)
            self.assertNotIn("Missing logs/cann_version.cfg", warnings)
            self.assertNotIn("Missing logs/npu_smi_info.stdout", warnings)
            self.assertTrue((run_dir / "logs" / "cann_version.cfg").exists())
            self.assertTrue((run_dir / "logs" / "npu_smi_info.stdout").exists())
            self.assertTrue((run_dir / "logs" / "relevant_env.txt").exists())
            self.assertTrue((run_dir / "reports").exists())

    def test_generate_report_from_existing_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_run(Path(tmp) / "profile", "mock_run")
            run([*CLI, "report", "--run-dir", str(run_dir)])
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
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            diagnosis = report.split("## 3. Diagnosis", 1)[1].split("## 4. Optimization Directions", 1)[0]
            optimization = report.split("## 4. Optimization Directions", 1)[1].split("## 5. Confidence And Caveats", 1)[0]
            performance = summary["stdout_sections"]["performance_summary"]
            directions = {item["id"]: item for item in summary["optimization_directions"]}

            self.assertIn("### App/Op Correlation", report)
            self.assertEqual(summary["headlines"]["op_summary"]["segment"], "app")
            self.assertIsNone(summary["headlines"]["op_summary"]["metric_scope"])
            self.assertEqual(summary["headlines"]["task_time"]["segment"], "app")
            self.assertIsNone(summary["headlines"]["task_time"]["metric_scope"])
            self.assertEqual(summary["headlines"]["op_basic_info"]["segment"], "op")
            self.assertEqual(summary["headlines"]["op_basic_info"]["metric_scope"], "PipeUtilization")
            self.assertEqual(summary["headlines"]["pipe_utilization"]["segment"], "op")
            self.assertEqual(summary["headlines"]["pipe_utilization"]["metric_scope"], "PipeUtilization")
            self.assertEqual(performance["source"], "logs/msprof_op.stdout")
            self.assertEqual(performance["section"], "Performance Summary Report")
            self.assertEqual(
                performance["messages"][0],
                {
                    "ordinal": 1,
                    "message": "aicore MTE3 bandwidth utilization lower than 80% when active.",
                    "source": "logs/msprof_op.stdout",
                },
            )
            self.assertNotIn("severity", performance["messages"][0])
            self.assertNotIn("advice", performance["messages"][0])
            self.assertIn("### CANN Performance Summary", report)
            self.assertIn("### Evidence Readiness", report)
            self.assertIn("- Level: `directional`.", report)
            readiness_section = report.split("### Evidence Readiness", 1)[1].split("### App/Op Correlation", 1)[0]
            for token in ["app_timing", "operator_metadata", "pipe_utilization", "stdout_performance_summary"]:
                self.assertIn(token, readiness_section)
            self.assertIn("- Next minimal collection action: `collect_default_metric_followup`", report)
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
                "| Op metadata | sanitized_op_kernel / Task Duration(us) | 5.75 | "
                "`reports/op/OPPROF_20260602101111_OPHASH12/OpBasicInfo.csv`; "
                "`headlines.op_basic_info.value; headlines.op_basic_info.first_row.Task Duration(us); "
                "headlines.op_basic_info.field=Task Duration(us); headlines.op_basic_info.field_kind=basic_info` |",
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
            self.assertIn("inspect_pipe_utilization_advisory", directions)
            self.assertIn("1. Inspect Pipe Utilization Advisory", optimization)
            self.assertIn("(`inspect_pipe_utilization_advisory`)", optimization)
            self.assertIn("Confidence: medium; effort: medium", optimization)
            self.assertIn("Requires artifacts:", optimization)
            advisory_evidence = json.dumps(directions["inspect_pipe_utilization_advisory"]["evidence"])
            self.assertIn("evidence_id", advisory_evidence)
            self.assertIn("stdout_sections.performance_summary.messages[].message", advisory_evidence)
            self.assertIn("stdout_sections.performance_summary.messages[ordinal=1].message", advisory_evidence)
            self.assertIn("stdout_sections.performance_summary.messages[ordinal=2].message", advisory_evidence)
            self.assertIn("aicore MTE3 bandwidth utilization lower than 80% when active.", advisory_evidence)
            self.assertIn("aivector compute usage lower than 20%.", advisory_evidence)
            self.assertIn("headlines.pipe_utilization.value", advisory_evidence)
            self.assertIn("headlines.op_summary.value", advisory_evidence)
            self.assertIn("headlines.op_basic_info.first_row.Block Dim", advisory_evidence)
            self.assertIn("headlines.op_basic_info.first_row.Mix Block Dim", advisory_evidence)
            performance_evidence = [
                item
                for item in directions["inspect_pipe_utilization_advisory"]["evidence"]
                if item["field_ref"].startswith("stdout_sections.performance_summary.messages[]")
            ]
            self.assertTrue(performance_evidence)
            self.assertTrue(all(item["segment"] == "op" for item in performance_evidence))
            self.assertTrue(all(item["metric_scope"] == "PipeUtilization" for item in performance_evidence))
            actions = {item["id"]: item for item in summary["next_collection_actions"]}
            self.assertIn("collect_default_metric_followup", actions)
            self.assertEqual(actions["collect_default_metric_followup"]["recommended_aic_metrics"], ["Default"])
            self.assertIn("ArithmeticUtilization.csv", actions["collect_default_metric_followup"]["required_artifacts"])
            self.assertIn("### Next Collection Actions", report)
            self.assertIn("collect_default_metric_followup", report)
            self.assertNotIn("bottleneck", report.lower())

    def test_analyze_fallback_performance_stdout_preserves_op_scope_when_selected(self):
        def write_run(root: Path, with_scope: bool) -> Path:
            run_dir = root / ("fallback_perf_scope" if with_scope else "fallback_perf_no_scope")
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
                    "1) fallback op performance message.\n"
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

            scoped_advisory = {
                item["id"]: item for item in scoped_summary["optimization_directions"]
            }["inspect_pipe_utilization_advisory"]
            unscoped_advisory = {
                item["id"]: item for item in unscoped_summary["optimization_directions"]
            }["inspect_pipe_utilization_advisory"]
            scoped_performance = [
                item
                for item in scoped_advisory["evidence"]
                if item["field_ref"].startswith("stdout_sections.performance_summary.messages[]")
            ]
            unscoped_performance = [
                item
                for item in unscoped_advisory["evidence"]
                if item["field_ref"].startswith("stdout_sections.performance_summary.messages[]")
            ]

            self.assertTrue(scoped_performance)
            self.assertTrue(unscoped_performance)
            self.assertEqual(scoped_summary["stdout_sections"]["performance_summary"]["source"], "logs/msprof_default.stdout")
            self.assertTrue(all(item["segment"] == "op" for item in scoped_performance))
            self.assertTrue(all(item["metric_scope"] == "PipeUtilization" for item in scoped_performance))
            self.assertTrue(all(item["segment"] == "unknown" for item in unscoped_performance))
            self.assertTrue(all(item["metric_scope"] is None for item in unscoped_performance))

    def test_generate_report_empty_run_collects_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "empty_run"
            run_dir.mkdir(parents=True)
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("**Run directory:** `profile/empty_run`", report)
            self.assertIn("No headline diagnosis generated", report)
            self.assertIn("Collect the missing profiler artifacts before changing kernel code.", report)
            self.assertNotIn("Inspect No headline diagnosis generated", report)

    def test_generate_report_surfaces_l2cache_without_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_l2cache_run(Path(tmp) / "profile", "real_l2cache_minimal")
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            assert_l2cache_report_evidence(self, report)
            self.assertIn("No headline diagnosis generated", report)
            self.assertNotIn("bottleneck", report.lower())
            self.assertNotIn("Inspect L2 cache", report)
            self.assertIn("### Analysis Dimensions", report)
            self.assertNotIn("Inspect Memory And Data Movement", report)
            self.assertNotIn(str(ROOT), report)

    def test_generate_report_surfaces_default_vector_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            run([*CLI, "report", "--run-dir", str(run_dir)])
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
            self.assertIn("### Analysis Dimensions", report)
            self.assertIn("## 4. Optimization Directions", report)
            self.assertIn("1. Inspect Pipe And Arithmetic Mix", report)
            self.assertIn("(`inspect_pipe_arithmetic_mix`)", report)
            self.assertIn("Impact basis: Timing evidence is corroborated by PipeUtilization and ArithmeticUtilization signals.", report)
            self.assertIn("Confidence: medium; effort: medium", report)
            self.assertIn("`reports/OPPROF_001/PipeUtilization.csv` `headlines.pipe_utilization.value", report)
            self.assertNotIn("Highest pipe utilization signal", report)
            self.assertNotIn("Highest memory signal", report)
            self.assertNotIn("Highest resource conflict signal", report)
            self.assertNotIn("Inspect Highest", report)
            self.assertNotIn("TimelineDetail", report)
            self.assertNotIn("bottleneck", report.lower())
            self.assertNotIn(str(ROOT), report)

    def test_generate_report_surfaces_tiling_metadata_in_analysis_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_block_dim_with_timing_sim_run(Path(tmp) / "profile")
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            dimensions = report.split("### Analysis Dimensions", 1)[1].split("### Duration And Calls", 1)[0]

            self.assertIn("block_dim_kernel / Block Dim = 8", dimensions)
            self.assertIn("reports/OPPROF_001/OpBasicInfo.csv", dimensions)
            self.assertIn("headlines.op_basic_info.tiling_value", dimensions)
            self.assertIn("headlines.op_basic_info.first_row.Block Dim", dimensions)
            self.assertIn("headlines.op_basic_info.tiling_field=Block Dim", dimensions)
            self.assertNotIn("block_dim_kernel | `reports/OPPROF_001/OpBasicInfo.csv`; `headlines.op_basic_info.value", dimensions)

    def test_generate_report_mentions_simulator_model_only_in_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_simulator_run(Path(tmp) / "profile")
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            analysis = report.split("## 2. Analysis", 1)[1].split("## 3. Diagnosis", 1)[0]
            diagnosis = report.split("## 3. Diagnosis", 1)[1].split("## 4. Optimization Directions", 1)[0]

            summary = json.loads((run_dir / "analysis" / "summary.json").read_text())
            dimensions = {item["id"]: item for item in summary["analysis_dimensions"]}
            self.assertIn("Structured simulator hotspot model is available at `analysis/simulator_hotspots.json`.", analysis)
            self.assertEqual(dimensions["source_pipeline_context"]["model_artifact"], "analysis/simulator_hotspots.json")
            self.assertNotIn("simulator_hotspots.json", diagnosis)
            self.assertNotIn("bottleneck", report.lower())

    def test_generate_report_surfaces_tiling_metadata_when_duration_present_without_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_op_basic_duration_block_dim_no_sim_run(Path(tmp) / "profile")
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            dimensions = report.split("### Analysis Dimensions", 1)[1].split("### Duration And Calls", 1)[0]
            optimization = report.split("## 4. Optimization Directions", 1)[1].split(
                "## 5. Confidence And Caveats",
                1,
            )[0]

            self.assertIn("duration_block_dim_no_sim_kernel / Task Duration(us) = 3.5", dimensions)
            self.assertIn("duration_block_dim_no_sim_kernel / Block Dim = 8", dimensions)
            self.assertIn("headlines.op_basic_info.first_row.Task Duration(us)", dimensions)
            self.assertIn("headlines.op_basic_info.tiling_value", dimensions)
            self.assertIn("headlines.op_basic_info.first_row.Block Dim", dimensions)
            self.assertIn("headlines.op_basic_info.tiling_field=Block Dim", dimensions)
            self.assertNotIn("Inspect Tiling And Core Balance", optimization)

    def test_generate_report_surfaces_occupancy_summary_without_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_occupancy_stdout_run(Path(tmp) / "profile", "real_occupancy_stdout_minimal")
            run([*CLI, "report", "--run-dir", str(run_dir)])
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
            run([*CLI, "report", "--run-dir", str(run_dir)])
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

    def test_generate_report_keeps_performance_summary_stdout_only_out_of_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "performance_stdout_only"
            logs = run_dir / "logs"
            logs.mkdir(parents=True)
            (logs / "msprof_op.stdout").write_text(
                (
                    "2026-06-02 12:56:11 [INFO]  Performance Summary Report:\n"
                    "\n"
                    "\t1) aicore compute usage lower than 20%.\n"
                    "\n"
                    "2026-06-02 12:56:11 [INFO]  Operator Basic Information:\n"
                ),
                encoding="utf-8",
            )

            run([*CLI, "report", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            diagnosis = report.split("## 3. Diagnosis", 1)[1].split("## 4. Optimization Directions", 1)[0]
            optimization = report.split("## 4. Optimization Directions", 1)[1].split("## 5. Confidence And Caveats", 1)[0]

            self.assertEqual(summary["optimization_directions"], [])
            self.assertEqual(summary["next_collection_actions"], [])
            self.assertIn("### CANN Performance Summary", report)
            self.assertIn("| 1 | aicore compute usage lower than 20%. | `logs/msprof_op.stdout` |", report)
            stdout_records = [
                item
                for item in raw_artifact_index(run_dir)["artifacts"]
                if item["group"] == "stdout_performance_summary"
            ]
            self.assertEqual(len(stdout_records), 1)
            self.assertEqual(stdout_records[0]["artifact"], "logs/msprof_op.stdout")
            self.assertEqual(stdout_records[0]["segment"], "op")
            self.assertEqual(stdout_records[0]["row_count"], 1)
            self.assertNotIn("CANN Performance Summary", diagnosis)
            self.assertNotIn("aicore compute", diagnosis)
            self.assertNotIn("Pipe Utilization Advisory", optimization)
            self.assertNotIn("aicore compute", optimization)
            self.assertNotIn("bottleneck", report.lower())
            self.assertNotIn("rewrite", report.lower())

    def test_generate_report_pipe_scope_keeps_required_op_artifact_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "pipe_scope_missing_required"
            logs = run_dir / "logs"
            logs.mkdir(parents=True)
            (logs / "command_msprof_op.txt").write_text(
                "msprof op --output=<abs-path>/reports/op --application=<abs-path>/harness/op.sh --aic-metrics=PipeUtilization\n",
                encoding="utf-8",
            )

            run([*CLI, "report", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")

            self.assertTrue(any(warning.startswith("missing op_basic_info:") for warning in summary["warnings"]))
            self.assertTrue(any(warning.startswith("missing pipe_utilization:") for warning in summary["warnings"]))
            self.assertEqual(summary["metric_scope"]["value"], "PipeUtilization")
            actions = {item["id"]: item for item in summary["next_collection_actions"]}
            self.assertIn("recollect_pipeutilization", actions)
            self.assertIn("collect_default_metric_followup", actions)
            self.assertIn("- Op metric scope: PipeUtilization (source: `logs/command_msprof_op.txt`; `--aic-metrics`).", report)
            self.assertIn("Analyzer warning: missing op_basic_info:", report)
            self.assertIn("Analyzer warning: missing pipe_utilization:", report)
            self.assertNotIn("Analyzer warning: missing arithmetic_utilization:", report)
            self.assertNotIn("Analyzer warning: missing l2_cache:", report)
            self.assertNotIn("Analyzer warning: missing memory:", report)
            self.assertNotIn("Analyzer warning: missing resource_conflict:", report)

    def test_generate_report_unknown_metric_scope_preserves_missing_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "profile" / "unknown_scope"
            logs = run_dir / "logs"
            logs.mkdir(parents=True)
            (logs / "command_msprof_op.txt").write_text(
                "msprof op --output=<abs-path>/reports/op --application=<abs-path>/harness/op.sh --aic-metrics=UnknownScope\n",
                encoding="utf-8",
            )

            run([*CLI, "report", "--run-dir", str(run_dir)])
            summary = json.loads((run_dir / "analysis" / "summary.json").read_text(encoding="utf-8"))
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")

            self.assertEqual(summary["metric_scope"]["value"], "UnknownScope")
            self.assertFalse(summary["metric_scope"]["known"])
            self.assertEqual(summary["next_collection_actions"], [])
            self.assertIn("Analyzer warning: missing pipe_utilization:", report)
            self.assertIn("Analyzer warning: missing arithmetic_utilization:", report)
            self.assertIn("Analyzer warning: missing memory:", report)
            self.assertIn("Analyzer warning: missing resource_conflict:", report)

    def test_generate_report_uses_provenance_without_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fresh_real_default_vector_run(Path(tmp) / "profile", "real_default_vector_minimal")
            run([*CLI, "provenance", "--run-dir", str(run_dir)])
            run([*CLI, "report", "--run-dir", str(run_dir)])
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
            self.assertIn("ascend-msprof provenance --run-dir <run-dir>", report)
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
                            "followups": {
                                "collect_default_metric_followup": {
                                    "output": {
                                        "value": "reports/followups/collect_default_metric_followup",
                                        "source": {
                                            "artifact": "logs/command_msprof_followup_collect_default_metric_followup.txt",
                                            "field": "--output",
                                        },
                                    },
                                    "resolved_output": {
                                        "value": "reports/followups/collect_default_metric_followup/OPPROF_<sanitized>",
                                        "source": {
                                            "artifact": "logs/msprof_followup_collect_default_metric_followup.stdout",
                                            "field": "Profiling results saved in",
                                        },
                                    },
                                    "status": {
                                        "value": "0",
                                        "source": {
                                            "artifact": "logs/msprof_followup_collect_default_metric_followup.status",
                                            "field": "exit_status",
                                        },
                                    },
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

            run([*CLI, "report", "--run-dir", str(run_dir)])
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
            self.assertIn(
                "followups.collect_default_metric_followup: "
                "reports/followups/collect_default_metric_followup "
                "(source: `logs/command_msprof_followup_collect_default_metric_followup.txt`; `--output`)",
                report,
            )
            self.assertIn(
                "resolved reports/followups/collect_default_metric_followup/OPPROF_<sanitized> "
                "(source: `logs/msprof_followup_collect_default_metric_followup.stdout`; "
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
            run([*CLI, "report", "--run-dir", str(run_dir)])
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
            run([*CLI, "report", "--run-dir", str(run_dir)])
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
                *CLI, "collect-tilelang",
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
                    *CLI, "collect-tilelang",
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
                env=test_env(),
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
                    *CLI, "prepare-tilelang",
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
                env=test_env(),
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
                *CLI, "prepare-tilelang",
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
                    *CLI, "prepare-tilelang",
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
                env=test_env(),
            )
            workflow = json.loads((run_dir / "analysis" / "tilelang_profile_run.json").read_text(encoding="utf-8"))

            self.assertIn("warning: Optional JIT debug root missing: missing-jit-debug", result.stderr)
            self.assertIn("Optional JIT debug root missing: missing-jit-debug", workflow["warnings"])

    def test_generate_report_includes_tilelang_context_without_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "profile" / "tilelang_empty"
            run_dir.mkdir(parents=True)
            payload, benchmark = write_tilelang_inputs(root)
            run([
                *CLI, "collect-tilelang",
                "--run-dir",
                str(run_dir),
                "--payload-src",
                str(payload),
                "--benchmark-json",
                str(benchmark),
            ])
            run([*CLI, "report", "--run-dir", str(run_dir)])
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
            run([*CLI, "report", "--run-dir", str(run_dir)])
            report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
            self.assertTrue((run_dir / "analysis" / "summary.json").exists())
            self.assertTrue((run_dir / "analysis" / "raw_artifact_index.json").exists())
            self.assertIn("# sanitized_operator_kernel Ascend Profiling Report", report)
            self.assertIn("analysis/raw_artifact_index.json", report)
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
