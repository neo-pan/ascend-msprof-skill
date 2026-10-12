"""Environment collection bounds, partial evidence and historical isolation."""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

from tests.helpers_shared import unittest
from ascend_msprof_skill import generate_provenance as producer


INFO = """| npu-smi 25.5.6 Version: 25.5.6 |
| 4 910B2 | Alarm |
| 0 | 0000:01:00.0 |
| 5 910B2 | OK |
| 0 | 0000:02:00.0 |
"""
# Same field spellings as the documented npu-smi board query; no host identifiers.
BOARD = """NPU ID : 5
Software Version : 25.5.6
Firmware Version : 7.8.0.10.220
Compatibility : OK
"""


class EnvironmentProbeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.logs = self.root / "logs"
        self.logs.mkdir()

    def collect(self, **kwargs):
        with mock.patch.object(producer, "collect_cann_sources"):
            producer.collect_environment(self.logs, **kwargs)

    def test_board_identity_is_bound_to_queried_physical_npu(self):
        def query(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, INFO if command[-1] == "info" else
                BOARD if command[-1] == "5" else "NPU ID : 4\n", "")
        with mock.patch("shutil.which", return_value="/fake/npu-smi"), \
             mock.patch("subprocess.run", side_effect=query) as runner, \
             mock.patch.dict(os.environ, {"ASCEND_RT_VISIBLE_DEVICES": "1"}):
            self.collect()
        self.assertIn(["/fake/npu-smi", "info", "-t", "board", "-i", "5"],
                      [call.args[0] for call in runner.call_args_list])
        self.assertEqual(runner.call_count, 3)
        manifest = producer.build_manifest(self.root)
        first, second = manifest.hardware.devices
        self.assertIsNone(first.driver_version)
        self.assertEqual(second.driver_version.value, "25.5.6")
        self.assertEqual(second.driver_version.source.field, "Software Version")
        self.assertEqual(second.firmware_version.value, "7.8.0.10.220")
        self.assertEqual(second.chip.value, "0")
        self.assertEqual(second.bus_id.value, "0000:02:00.0")
        self.assertEqual(manifest.environment.selected["ASCEND_RT_VISIBLE_DEVICES"].value, "1")
        self.assertIn("ACL", " ".join(manifest.hardware.limitations))

    def test_timeout_preserves_partial_stdout_and_receipt(self):
        (self.logs / "cann_version.cfg").write_text("toolkit_running_version=[8.5.2]\n")
        with mock.patch("shutil.which", return_value="/fake/npu-smi"), \
             mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(
                 ["npu-smi", "info"], 0.1, output=INFO.encode(), stderr=b"slow query")) as runner:
            self.collect(probe_timeout_s=0.1)
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(runner.call_args.kwargs["timeout"], 0.1)
        receipt = json.loads((self.logs / "npu_smi_info.receipt.json").read_text())
        self.assertEqual(receipt["status"], "timeout")
        self.assertIsNone(receipt["exit_code"])
        self.assertEqual((self.logs / "npu_smi_info.stdout").read_text(), INFO)
        self.assertEqual((self.logs / "npu_smi_info.stderr").read_text(), "slow query")
        manifest = producer.build_manifest(self.root)
        self.assertEqual(len(manifest.hardware.devices), 2)
        self.assertEqual(manifest.cann_version.value, "8.5.2")

    def test_missing_tool_is_explicit_partial_evidence(self):
        with mock.patch("shutil.which", return_value=None), mock.patch("subprocess.run") as runner:
            self.collect()
        runner.assert_not_called()
        manifest = producer.build_manifest(self.root)
        self.assertIsNone(manifest.hardware)
        self.assertEqual(manifest.environment_probes[0].status, "tool_missing")

    def test_real_slow_query_is_killed_with_output_preserved(self):
        binary = self.root / "npu-smi"
        binary.write_text(f"#!{sys.executable}\nimport time\nprint('| 5 910B2 | OK |', flush=True)\ntime.sleep(10)\n")
        binary.chmod(0o755)
        started = time.monotonic()
        with mock.patch("shutil.which", return_value=str(binary)):
            self.collect(probe_timeout_s=0.25)
        self.assertLess(time.monotonic() - started, 3)
        manifest = producer.build_manifest(self.root)
        self.assertEqual(manifest.environment_probes[0].status, "timeout")
        self.assertEqual(manifest.hardware.devices[0].npu.value, "5")

    def test_one_board_timeout_preserves_other_board_identity(self):
        def query(command, **kwargs):
            if command[-1] == "4":
                raise subprocess.TimeoutExpired(command, 45, output=b"NPU ID : 4\n")
            return subprocess.CompletedProcess(command, 0, INFO if command[-1] == "info" else BOARD, "")
        with mock.patch("shutil.which", return_value="/fake/npu-smi"), \
             mock.patch("subprocess.run", side_effect=query):
            self.collect()
        manifest = producer.build_manifest(self.root)
        self.assertIsNone(manifest.hardware.devices[0].firmware_version)
        self.assertEqual(manifest.hardware.devices[1].firmware_version.value, "7.8.0.10.220")
        self.assertTrue(any("timeout" in warning for warning in manifest.warnings))

    def test_historical_info_never_triggers_current_board_backfill(self):
        (self.logs / "npu_smi_info.stdout").write_text(INFO)
        with mock.patch("subprocess.run") as runner:
            self.collect()
        runner.assert_not_called()
        manifest = producer.build_manifest(self.root)
        self.assertEqual(manifest.environment_probes, ())
        self.assertTrue(all(device.driver_version is None for device in manifest.hardware.devices))

    def test_failed_or_mismatched_board_does_not_assign_versions(self):
        for code, body in [(1, BOARD), (0, BOARD.replace("NPU ID : 5", "NPU ID : 4"))]:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as temp:
                self.root = Path(temp)
                self.logs = self.root / "logs"
                def query(command, **kwargs):
                    return subprocess.CompletedProcess(command, 0 if command[-1] == "info" else code,
                        INFO if command[-1] == "info" else body, "")
                with mock.patch("shutil.which", return_value="/fake/npu-smi"), \
                     mock.patch("subprocess.run", side_effect=query):
                    self.collect()
                manifest = producer.build_manifest(self.root)
                self.assertIsNone(manifest.hardware.devices[1].driver_version)
