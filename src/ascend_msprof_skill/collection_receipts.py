"""Consumed collection results, loaded once and shared across evidence decisions."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from .artifact_reader import read_json
from .evidence_types import ArtifactPath, EvidenceFact, ParseIssue, SourceRef
from ._profiler_segments import (
    followup_segment, is_supported_followup_action_id, segment_receipt_artifact,
)


ExecutionStatus = Literal["succeeded", "failed", "core_dump", "timeout"]
_STATUS = TypeAdapter(ExecutionStatus)


class CollectionReceipt(EvidenceFact):
    segment: str
    artifact: ArtifactPath
    status: ExecutionStatus | None
    issue: ParseIssue | None

    @model_validator(mode="after")
    def consistent_result(self) -> CollectionReceipt:
        if self.artifact != segment_receipt_artifact(self.segment):
            raise ValueError("receipt artifact disagrees with collection segment")
        if (self.status is None) != (self.issue is not None):
            raise ValueError("receipt requires either an execution status or a parsing issue")
        if self.issue is not None and self.issue.source.artifact != self.artifact:
            raise ValueError("receipt issue must cite its artifact")
        return self


class CollectionReceipts(EvidenceFact):
    records: Annotated[tuple[CollectionReceipt, ...], Field(strict=False)]

    @model_validator(mode="after")
    def unique_segments(self) -> CollectionReceipts:
        segments = [item.segment for item in self.records]
        if segments != sorted(set(segments)):
            raise ValueError("receipt segments must be unique and sorted")
        return self

    def allows(self, segment: str) -> bool:
        return all(item.status == "succeeded" for item in self.records if item.segment == segment)

    @property
    def excluded_segments(self) -> set[str]:
        return {item.segment for item in self.records if item.status != "succeeded"}


def load_collection_receipts(run_dir: Path) -> CollectionReceipts:
    segments = {"app", "op", "simulator"}
    prefix, suffix = "msprof_followup_", ".result.json"
    for path in (run_dir / "logs").glob(f"{prefix}*{suffix}"):
        action = path.name[len(prefix):-len(suffix)]
        if is_supported_followup_action_id(action):
            segments.add(followup_segment(action))
    records = []
    for segment in sorted(segments):
        artifact = segment_receipt_artifact(segment)
        source = SourceRef(artifact=artifact)
        try:
            payload = read_json(run_dir / artifact)
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as exc:
            issue = ParseIssue(code="receipt_decode", source=source, reason=str(exc), impact="decode")
            status = None
        else:
            if not isinstance(payload, dict):
                issue = ParseIssue(code="receipt_structure", source=source,
                                   reason="collection receipt must be a JSON object", impact="structure")
                status = None
            else:
                try:
                    status = _STATUS.validate_python(payload.get("status"), strict=True)
                except ValidationError as exc:
                    issue = ParseIssue(code="receipt_status", source=SourceRef(artifact=artifact, field="status"),
                                       reason=exc.errors(include_url=False, include_input=False)[0]["msg"], impact="scope")
                    status = None
                else:
                    issue = None
        records.append(CollectionReceipt(segment=segment, artifact=artifact, status=status, issue=issue))
    return CollectionReceipts(records=records)
