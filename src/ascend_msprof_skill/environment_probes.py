"""Bounded, read-only npu-smi snapshots for a new collection only."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import time


DEFAULT_PROBE_TIMEOUT_S = 60


def device_rows(text: str) -> list[dict[str, str]]:
    devices: list[dict[str, str]] = []
    for line in text.splitlines():
        row = re.match(r"^\|\s*(\d+)\s+(910\S*)\s+\|\s+([A-Za-z]+)\s+\|", line)
        if row:
            devices.append(dict(npu=row[1], name=row[2], health=row[3]))
            continue
        chip = re.match(r"^\|\s*(\d+)\s*\|\s*([0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7])\s*\|", line)
        if chip and devices:
            devices[-1].update(chip=chip[1], bus_id=chip[2])
    return devices


def _text(value: str | bytes | None) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""


def _probe(logs: Path, stem: str, command: list[str], timeout_s: float,
           *, available: bool = True, npu: str | None = None) -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    stdout, stderr, exit_code = "", "", None
    if not available:
        status, exit_code, stderr = "tool_missing", 127, "npu-smi not found\n"
    else:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s)
            stdout, stderr, exit_code = result.stdout, result.stderr, result.returncode
            status = "success" if exit_code == 0 else "failed"
        except subprocess.TimeoutExpired as exc:
            status, stdout, stderr = "timeout", _text(exc.stdout), _text(exc.stderr)
        except OSError as exc:
            status, stderr = "unavailable", str(exc)
    receipt = dict(command=command, started_at=started_at, elapsed_s=time.monotonic() - started,
                   timeout_s=timeout_s, status=status, exit_code=exit_code,
                   stdout=f"logs/{stem}.stdout", stderr=f"logs/{stem}.stderr", physical_npu=npu)
    for suffix, text in [("stdout", stdout), ("stderr", stderr),
                         ("status", str(exit_code) if exit_code is not None else status)]:
        (logs / f"{stem}.{suffix}").write_text(_text(text), encoding="utf-8")
    (logs / f"{stem}.receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def collect_npu_environment(logs: Path, timeout_s: float = DEFAULT_PROBE_TIMEOUT_S) -> None:
    # Existing output is historical evidence, including failed/partial captures.
    # Never fill in missing board identity using today's machine.
    if (logs / "npu_smi_info.stdout").exists() or (logs / "npu_smi_info.receipt.json").exists():
        return
    if timeout_s <= 0:
        raise ValueError("environment probe timeout must be positive")
    binary = shutil.which("npu-smi")
    receipt = _probe(logs, "npu_smi_info", [binary or "npu-smi", "info"], timeout_s,
                     available=binary is not None)
    if receipt["status"] != "success":
        return
    npu_ids = sorted({row["npu"] for row in device_rows((logs / "npu_smi_info.stdout").read_text())})
    # Each board is physical scope. Runtime-visible indices are not inferred.
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_probe, logs, f"npu_smi_board_{npu}",
                    [binary, "info", "-t", "board", "-i", npu], timeout_s, npu=npu)
                   for npu in npu_ids]
        for future in futures:
            future.result()
