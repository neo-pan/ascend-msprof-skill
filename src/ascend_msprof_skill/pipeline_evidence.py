"""Collection diagnostics; retired device BIU data stays raw inventory."""
from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from .ascend_profile_utils import analysis_dir, write_json
from .evidence_types import EvidenceFact, SourceRef
from .metric_scope_policy import command_parts
from ._profiler_segments import APP_SEGMENT, segment_for_relpath
from .artifact_reader import decode_json


INSTRUCTION_SAMPLING_CLOSED_CODE = "device_instruction_sampling_closed"
INSTRUCTION_SAMPLING_CLOSED_MESSAGE = (
    "Device instruction/BIU sampling is closed for this skill's A2/A3 baseline. "
    "Ascend/msprof #130, final reply 188803618 (2026-09-09), advises against "
    "analysis of these data, including nonzero samples. Raw artifacts are retained "
    "for audit only; use ordinary application/operator PMU or simulation instead. "
    "https://gitcode.com/Ascend/msprof/issues/130"
)


class PipelineIssue(EvidenceFact):
    code: str
    source: SourceRef
    message: str
    source_sha256: str | None = None


class PipelineEvidence(EvidenceFact):
    schema_version: Literal[2] = 2
    device_instruction_sampling: Literal["closed"] = "closed"
    issues: Annotated[tuple[PipelineIssue, ...], Field(strict=False)]
    samples: Annotated[tuple[()], Field(strict=False)] = ()
    overlap_assessment: Literal["not_established"] = "not_established"


# These are observed CANN messages, not a generic search for the word "error".
LOG_DIAGNOSTICS = (
    ("incompatible_collection_flags", r'Params .*not allowed to set',
     "The recorded invocation rejected an option combination; this error alone does not establish a supported retry route."),
    ("source_debug_mapping_missing", r'Kernel missed debug_line information',
     "The tool reports missing debug-line information for source mapping."),
    ("source_hotspot_generation_failed", r'Generate hot spot function failed',
     "Source hotspot generation failed; inspect retained products independently."),
    ("target_not_selected", r'Kernel .* skipped: not selected',
     "This kernel was skipped by the selector; verify the generated entrypoint and selected launch coverage."),
    ("kernel_argument_dump_failed", r'Kernel context save failed|Addr info is null',
     "Kernel argument capture failed; an instruction timeline is not established by onboard metadata."),
    ("timeline_detail_failed", r'TimelineDetail data collection failed',
     "TimelineDetail collection failed even if the profiler process returned zero."),
    ("simulator_library_load_failed", r'Failed to load so libruntime_camodel.so',
     "The simulator runtime could not load; check the selected simulator and launcher environment."),
    ("framework_simulator_api_failed", r'SetDeterministicFromLevel:|set sys param failed',
     "A framework runtime setup API failed; this is not evidence that the target kernel failed simulation."),
    ("profiled_application_failed", r'Child process exited with status [1-9][0-9]*',
     "The profiled application failed; profiler process exit alone does not establish completion."),
)

def read_log_diagnostics(path: Path, run_dir: Path) -> tuple[PipelineIssue, ...]:
    issues = []
    seen = set()
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    for number, line in enumerate(raw.decode(errors="replace").splitlines(), 1):
        for code, pattern, message in LOG_DIAGNOSTICS:
            if code not in seen and re.search(pattern, line):
                seen.add(code)
                issues.append(PipelineIssue(code=code, source=SourceRef(
                    artifact=path.relative_to(run_dir).as_posix(), record=number),
                    message=f"{message} Observed: {line.strip()}", source_sha256=sha256))
    return tuple(issues)


def collection_log_paths(run_dir: Path) -> list[Path]:
    return sorted({path for pattern in ("msprof*.stdout", "msprof*.stderr", "command_msprof.stdout")
                   for path in (run_dir / "logs").glob(pattern)
                   if not any(word in path.name.lower() for word in ("help", "environment"))})


def collection_diagnostics(run_dir: Path) -> dict:
    """Question view of existing log diagnostics, not a collection scheduler.

    Recovery is attached to the observed error, so an unrelated closed segment
    cannot prevent repairing an ordinary invocation in the same run.
    """
    issues = [item for path in collection_log_paths(run_dir)
              for item in read_log_diagnostics(path, run_dir)]
    result = []
    for issue in issues:
        closed = (issue.code == 'incompatible_collection_flags'
                  and re.search(r'instr[-_]profiling', issue.message, re.I))
        if closed:
            recovery = dict(route=INSTRUCTION_SAMPLING_CLOSED_CODE, retry_command=None,
                next_step='Keep independent formal timing and correctness records. Answer supported PMU questions from retained app/op evidence; '
                'select a validated alternative only for the remaining question. Changing flags or switching to msprof op does not reopen BIU sampling.',
                basis=INSTRUCTION_SAMPLING_CLOSED_MESSAGE)
        elif issue.code in {'source_debug_mapping_missing', 'source_hotspot_generation_failed'}:
            recovery = dict(route='inspect_retained_source_products', retry_command=None,
                next_step='Inspect the existing viewer input and receipt for usable instruction/count data and mapping. '
                'Missing debug-line information limits source mapping, not independent operator metrics. '
                'If source-line mapping is still needed and unavailable, check the build debug information; '
                'a matching -g build and supported Source collection is conditional and does not guarantee hotspots. '
                'source_sha256 hashes source bytes; build flags can change the object without changing those bytes. '
                'Keep old formal results bound to their original implementation; establish the new object binding and '
                'validate it separately before using its correctness or timing.')
        else:
            recovery = dict(route='inspect_supported_command', retry_command=None,
                next_step='Check the cited error, command and installed help for this route; correct supported arguments or prerequisites '
                'only if the question still needs this collection. Preserve independent valid records.')
        result.append({**issue.model_dump(mode='json'), 'recovery': recovery})
    return {'device_instruction_sampling': 'closed', 'policy_source': INSTRUCTION_SAMPLING_CLOSED_MESSAGE,
            'issues': result,
            'scope_note': 'These are observed log diagnostics, not certification of all outputs or segment success. '
                'retry_command=null means no concrete command was supplied; recovery depends on the route and its conditions. '
                'A save-success message does not prove current file availability, completeness or retention history. '
                'Unparsed viewer input means not inspected by this helper, not unusable. Inspect existing products before selecting new collection.'}


def retired_sample_issues(path: Path, run_dir: Path, *, sampling_requested: bool = False
                         ) -> tuple[PipelineIssue, ...]:
    """Identify a retired artifact from its schema without reading activity data."""
    artifact = path.relative_to(run_dir).as_posix()
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    issues = []
    field = None
    # Only inventory table names. Ordinary profiling can emit an empty DB;
    # that placeholder must not be treated as an attempted BIU collection.
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            connection.execute("PRAGMA query_only=ON")
            table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND lower(name) IN ('biucycles', 'biuflow', 'monitorcycles', 'monitorflow') LIMIT 1"
            ).fetchone()
            if table is None and not sampling_requested:
                return ()
            field = table[0] if table else None
    except sqlite3.Error as exc:
        issues.append(PipelineIssue(code="pipeline_sample_decode_failed",
            source=SourceRef(artifact=artifact, field="sqlite_master"),
            message=f"Retired BIU artifact inventory failed: {exc}", source_sha256=sha256))
    issues.append(PipelineIssue(code=INSTRUCTION_SAMPLING_CLOSED_CODE,
        source=SourceRef(artifact=artifact, field=field),
        message=INSTRUCTION_SAMPLING_CLOSED_MESSAGE, source_sha256=sha256))
    return tuple(issues)


def retired_biu_event_indices(events: list) -> set[int]:
    """Recognize CANN BIU export lanes, including their unnamed X intervals.

    CANN 8.5.2 BiuPerfModel/BiuPerfViewer exports unit_name as process_name;
    a kernel whose name merely contains 'biu' remains an ordinary task.
    """
    lane_name = re.compile(r"(?:biu_group\d+|aic_core\d+_group\d+|aiv[01]?_core\d+_group\d+)")
    pids = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        args = event.get('args')
        if (event.get('ph') == 'M' and event.get('name') == 'process_name'
                and event.get('pid') is not None and isinstance(args, dict)
                and lane_name.fullmatch(str(args.get('name', '')))):
            pids.add(str(event['pid']))
    retired = set()
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        args = event.get('args')
        unnamed_cycles = (event.get('ph') == 'X' and not event.get('name')
                          and isinstance(args, dict) and {'cycle_num', 'ratio'} <= args.keys())
        if str(event.get('pid')) in pids or unnamed_cycles:
            retired.add(index)
    return retired



def inspect_launcher(application: Path, run_dir: Path) -> tuple[PipelineIssue, ...]:
    """Recognize literal shell overrides that discard profiler-injected libraries."""
    issues = []
    try:
        text = application.read_text()
    except (OSError, UnicodeError):
        return ()  # A binary launcher is not a shell script to inspect.
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        match = re.match(r'^\s*(?:export\s+)?(LD_LIBRARY_PATH|LD_PRELOAD)=(.*)$', line)
        if match and not re.search(r'\$(?:' + match[1] + r'\b|\{' + match[1] + r'(?:\}|:))', match[2]):
            # The application may live outside the run. Register its digest and
            # line in the run-local preflight rather than inventing a relative source.
            issues.append(PipelineIssue(code="launcher_overwrites_profiler_environment",
                source=SourceRef(artifact="logs/pipeline_preflight.json",
                                 field=f"application.environment_overrides[{len(issues)}]"),
                message=f"{match[1]} is overwritten by the launcher at line {number}; preserve the profiler-injected environment."))
    return tuple(issues)


def build_pipeline_evidence(run_dir: Path, *,
                            trace_payloads: dict[Path, bytes] | None = None) -> PipelineEvidence:
    run_dir = run_dir.resolve()
    logs = collection_log_paths(run_dir)
    issues = [item for path in logs for item in read_log_diagnostics(path, run_dir)]
    command_path = run_dir / 'logs/command_msprof.txt'
    parts = command_parts(command_path.read_text()) if command_path.exists() else []
    app_sampling_requested = any(
        part == '--instr-profiling=on' or (
            part == '--instr-profiling' and index + 1 < len(parts) and parts[index + 1] == 'on')
        for index, part in enumerate(parts or []))
    if app_sampling_requested:
        issues.append(PipelineIssue(code=INSTRUCTION_SAMPLING_CLOSED_CODE,
            source=SourceRef(artifact='logs/command_msprof.txt'),
            message=INSTRUCTION_SAMPLING_CLOSED_MESSAGE,
            source_sha256=hashlib.sha256(command_path.read_bytes()).hexdigest()))
    for path in sorted((run_dir / "reports").rglob("biu_perf.db")):
        requested = app_sampling_requested and segment_for_relpath(path.relative_to(run_dir).as_posix()) == APP_SEGMENT
        issues.extend(retired_sample_issues(path, run_dir, sampling_requested=requested))
    traces = {path for pattern in ("msprof_*.json", "trace.json")
              for path in (run_dir / "reports").rglob(pattern)
              if not path.name.endswith(".result.json")}
    for path in sorted(traces):
        raw = path.read_bytes()
        if trace_payloads is not None and path.name == 'trace.json':
            trace_payloads[path] = raw
        try:
            obj = decode_json(raw)
        except (ValueError, UnicodeError):
            continue  # The existing timeline parser retains malformed JSON diagnostics.
        events, container = (obj, '') if isinstance(obj, list) else ([], '')
        if isinstance(obj, dict):
            for key in ('traceEvents', 'events', 'data'):
                if isinstance(obj.get(key), list):
                    events, container = obj[key], key
                    break
        retired = retired_biu_event_indices(events)
        if retired:
            issues.append(PipelineIssue(code=INSTRUCTION_SAMPLING_CLOSED_CODE,
                source=SourceRef(artifact=path.relative_to(run_dir).as_posix(),
                                 field=f"{container}[{min(retired)}]"),
                message=INSTRUCTION_SAMPLING_CLOSED_MESSAGE,
                source_sha256=hashlib.sha256(raw).hexdigest()))
    return PipelineEvidence(issues=tuple(issues))


def diagnostic_warnings(evidence: PipelineEvidence) -> list[str]:
    return [f"{issue.code}: {issue.source.artifact}"
            + (f":{issue.source.record}" if issue.source.record else "")
            + (f" ({issue.source.field})" if issue.source.field else "")
            + f": {issue.message}" for issue in evidence.issues]


def write_pipeline_evidence(run_dir: Path, evidence: PipelineEvidence | None = None, *,
                            trace_payloads: dict[Path, bytes] | None = None) -> PipelineEvidence:
    evidence = evidence or build_pipeline_evidence(run_dir, trace_payloads=trace_payloads)
    write_json(analysis_dir(run_dir) / "pipeline_evidence.json", evidence.model_dump(mode="json"))
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    evidence = write_pipeline_evidence(args.run_dir.resolve())
    for warning in diagnostic_warnings(evidence):
        print(warning)
    print(f"wrote {args.run_dir / 'analysis/pipeline_evidence.json'}; device instruction sampling closed; overlap not established")
    return 2 if any(issue.code == INSTRUCTION_SAMPLING_CLOSED_CODE for issue in evidence.issues) else 0
