"""Sourced collection diagnostics and sampled-pipeline quality, without overlap claims."""
from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .ascend_profile_utils import analysis_dir, write_json
from .evidence_types import ArtifactPath, EvidenceFact, SourceRef
from .metric_scope_policy import command_parts
from ._profiler_segments import APP_SEGMENT, segment_for_relpath


class PipelineIssue(EvidenceFact):
    code: str
    source: SourceRef
    message: str
    source_sha256: str | None = None


class SampleQuality(EvidenceFact):
    artifact: ArtifactPath
    sha256: str
    rows: int | None = Field(ge=0)
    core_lanes: int | None = Field(ge=0)
    distinct_timestamps: int | None = Field(ge=0)
    nonzero_timestamps: int | None = Field(ge=0)
    nonzero_activity_rows: int | None = Field(ge=0)
    minimum_checks_passed: bool
    measurement_kind: Literal["sampled_window_activity"] = "sampled_window_activity"
    target_binding: Literal["not_established"] = "not_established"

    @model_validator(mode="after")
    def quality_agrees_with_counts(self) -> SampleQuality:
        expected = bool(self.rows and self.distinct_timestamps and self.distinct_timestamps > 1
                        and self.nonzero_timestamps and self.nonzero_activity_rows)
        if self.minimum_checks_passed != expected:
            raise ValueError("sample quality disagrees with observed counts")
        return self


class PipelineEvidence(EvidenceFact):
    schema_version: Literal[1] = 1
    issues: Annotated[tuple[PipelineIssue, ...], Field(strict=False)]
    samples: Annotated[tuple[SampleQuality, ...], Field(strict=False)]
    overlap_assessment: Literal["not_established"] = "not_established"


# These are observed CANN messages, not a generic search for the word "error".
LOG_DIAGNOSTICS = (
    ("incompatible_collection_flags", r'Params .*not allowed to set',
     "Instruction sampling rejects the selected application timing options."),
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

SAMPLE_QUERY = """
    SELECT count(*) AS rows, count(DISTINCT unit_name) AS core_lanes,
           count(DISTINCT timestamp) AS distinct_timestamps,
           coalesce(sum(CASE WHEN timestamp != 0 THEN 1 ELSE 0 END), 0) AS nonzero_timestamps,
           coalesce(sum(CASE WHEN cycle_num != 0 THEN 1 ELSE 0 END), 0) AS nonzero_activity_rows
    FROM BiuCycles
"""


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


def inspect_sample_database(path: Path, run_dir: Path, *, sampling_requested: bool = False
                            ) -> tuple[SampleQuality | None, tuple[PipelineIssue, ...]]:
    artifact = path.relative_to(run_dir).as_posix()
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    stats = dict.fromkeys(("rows", "core_lanes", "distinct_timestamps",
                          "nonzero_timestamps", "nonzero_activity_rows"))
    issues = []
    # Read-only URI: inspecting preserved evidence must not create a journal.
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND lower(name)='biucycles'"
            ).fetchone()
            # Ordinary application profiling can emit an empty biu_perf.db.
            # Its absence of sampled data is only a failure if requested.
            if table is None and not sampling_requested:
                return None, ()
            stats = dict(connection.execute(SAMPLE_QUERY).fetchone())
    except sqlite3.Error as exc:
        issues.append(PipelineIssue(code="pipeline_sample_decode_failed",
            source=SourceRef(artifact=artifact, field="BiuCycles"), message=str(exc), source_sha256=sha256))
    passed = bool(stats["rows"] and stats["distinct_timestamps"] > 1
                  and stats["nonzero_timestamps"] and stats["nonzero_activity_rows"])
    if not passed and not issues:
        issues.append(PipelineIssue(code="unusable_pipeline_samples",
            source=SourceRef(artifact=artifact, field="BiuCycles.{timestamp,cycle_num}"),
            message="Samples fail necessary timestamp/activity checks. All-zero counters are not evidence of idle pipelines.",
            source_sha256=sha256))
    quality = SampleQuality(artifact=artifact, sha256=sha256,
                            **stats, minimum_checks_passed=passed)
    return quality, tuple(issues)


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


def build_pipeline_evidence(run_dir: Path) -> PipelineEvidence:
    run_dir = run_dir.resolve()
    logs = sorted({path for pattern in ("msprof*.stdout", "msprof*.stderr", "command_msprof.stdout")
                   for path in (run_dir / "logs").glob(pattern)
                   if not any(word in path.name.lower() for word in ("help", "environment"))})
    issues = [item for path in logs for item in read_log_diagnostics(path, run_dir)]
    samples = []
    command_path = run_dir / 'logs/command_msprof.txt'
    parts = command_parts(command_path.read_text()) if command_path.exists() else []
    app_sampling_requested = any(
        part == '--instr-profiling=on' or (
            part == '--instr-profiling' and index + 1 < len(parts) and parts[index + 1] == 'on')
        for index, part in enumerate(parts or []))
    for path in sorted((run_dir / "reports").rglob("biu_perf.db")):
        requested = app_sampling_requested and segment_for_relpath(path.relative_to(run_dir).as_posix()) == APP_SEGMENT
        sample, sample_issues = inspect_sample_database(path, run_dir, sampling_requested=requested)
        if sample is not None:
            samples.append(sample)
        issues.extend(sample_issues)
    return PipelineEvidence(issues=tuple(issues), samples=tuple(samples))


def diagnostic_warnings(evidence: PipelineEvidence) -> list[str]:
    return [f"{issue.code}: {issue.source.artifact}"
            + (f":{issue.source.record}" if issue.source.record else "")
            + (f" ({issue.source.field})" if issue.source.field else "")
            + f": {issue.message}" for issue in evidence.issues]


def write_pipeline_evidence(run_dir: Path, evidence: PipelineEvidence | None = None) -> PipelineEvidence:
    evidence = evidence or build_pipeline_evidence(run_dir)
    write_json(analysis_dir(run_dir) / "pipeline_evidence.json", evidence.model_dump(mode="json"))
    return evidence


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    evidence = write_pipeline_evidence(args.run_dir.resolve())
    for warning in diagnostic_warnings(evidence):
        print(warning)
    for sample in evidence.samples:
        print(f"{sample.artifact}: rows={sample.rows}; minimum_checks_passed={sample.minimum_checks_passed}")
    print(f"wrote {args.run_dir / 'analysis/pipeline_evidence.json'}; overlap not established")
