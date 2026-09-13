"""Consumed target, execution and workload context for pure analysis decisions."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, JsonValue, TypeAdapter, ValidationError, model_validator

from .artifact_reader import read_json
from .collection_receipts import ExecutionStatus
from .evidence_types import ArtifactPath, EvidenceFact, ParseIssue, SourceRef
from .identity_types import ExpectedTarget
from ._profile_target import TargetSelection, TargetText, expected_counts
from ._profiler_segments import DEFAULT_FOLLOWUP_ACTION_ID, is_supported_followup_action_id


WORKFLOW_ARTIFACT = "analysis/profile_harness_run.json"
PROFILE_ARTIFACT = "analysis/profile_context.json"
TILELANG_ARTIFACT = "analysis/tilelang_context.json"
TARGET_FIELDS = ("expected_kernel_names", "expected_op_names", "target_kernel_names", "target_op_names",
                 "expected_kernel_name", "expected_op_name", "target_kernel_name", "target_op_name")
TARGET_CONTAINERS = ("target", "kernel", "operator", "metadata", "jit_config", "profile_harness", "benchmark")
FRAMEWORK_FIELDS = {"task_framework", "task_language", "framework", "language"}
_NAMES = TypeAdapter(TargetText | Annotated[tuple[TargetText, ...], Field(strict=False, min_length=1)], config=ConfigDict(strict=True))
_ACTION_STATUS = TypeAdapter(ExecutionStatus | Literal["skipped", "blocked"])


class FollowupExecution(EvidenceFact):
    segment_id: str
    status: ExecutionStatus
    target_selection: TargetSelection | None
    source: SourceRef

    @model_validator(mode="after")
    def supported_execution(self) -> FollowupExecution:
        if not is_supported_followup_action_id(self.segment_id):
            raise ValueError("execution requires a supported follow-up segment")
        if self.status != "succeeded" and self.target_selection is not None:
            raise ValueError("failed execution cannot declare an admitted target")
        if self.source.artifact != WORKFLOW_ARTIFACT or re.fullmatch(r"follow_up_actions\[\d+\]", self.source.field or "") is None:
            raise ValueError("execution must cite its workflow action record")
        return self


class HarnessWorkflow(EvidenceFact):
    target_selection: TargetSelection | None
    executions: Annotated[tuple[FollowupExecution, ...], Field(strict=False)]


class DeclaredTarget(EvidenceFact):
    target: TargetSelection
    artifact: ArtifactPath
    field_ref: str


class WorkloadContext(EvidenceFact):
    source: SourceRef
    id: TargetText | None = None
    id_field: Literal["id", "task_name"] = "id"
    shape: JsonValue = None
    dtype: TargetText | None = None
    case_count: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def sourced_workload(self) -> WorkloadContext:
        if self.source.artifact not in {PROFILE_ARTIFACT, TILELANG_ARTIFACT} or self.source.field not in {
                "benchmark.workload", "profile_harness.workload", "verify_context.raw.workload"}:
            raise ValueError("workload must cite a consumed context record")
        if self.id_field == "task_name" and self.source.field != "verify_context.raw.workload":
            raise ValueError("task_name is a caller verification workload field")
        return self

    @property
    def present(self) -> bool:
        return any(getattr(self, key) not in (None, "", [], {}) for key in ("id", "shape", "dtype", "case_count"))


class AnalysisContext(EvidenceFact):
    workflow: HarnessWorkflow | None
    profile_target: TargetSelection | None
    metadata_target: ExpectedTarget | None
    workloads: Annotated[tuple[WorkloadContext, ...], Field(strict=False)]
    issues: Annotated[tuple[ParseIssue, ...], Field(strict=False)]

    @model_validator(mode="after")
    def context_facts(self) -> AnalysisContext:
        target = self.metadata_target
        if target is not None:
            if target.artifact not in {PROFILE_ARTIFACT, TILELANG_ARTIFACT} or target.explicit_target or target.counts is not None:
                raise ValueError("metadata names cannot declare launch-count authority")
            if target.inferred and (target.names != ("main_kernel",) or target.field_ref.split(".")[-1] not in FRAMEWORK_FIELDS):
                raise ValueError("inferred TileLang target requires framework source")
        sources = [(item.source.artifact, item.source.field) for item in self.workloads]
        if len(set(sources)) != len(sources) or any(not item.present for item in self.workloads):
            raise ValueError("workload records require unique sources and consumed values")
        return self

    @property
    def declared_target(self) -> DeclaredTarget | None:
        if self.workflow is not None and self.workflow.target_selection is not None:
            return DeclaredTarget(target=self.workflow.target_selection, artifact=WORKFLOW_ARTIFACT,
                                  field_ref="target_selection.expected_launches")
        if self.profile_target is not None:
            return DeclaredTarget(target=self.profile_target, artifact=PROFILE_ARTIFACT,
                                  field_ref="profile_harness.target.expected_launches")
        return None

    @property
    def expected_target(self) -> ExpectedTarget | None:
        declared = self.declared_target
        if declared is None:
            return self.metadata_target
        return ExpectedTarget(names=tuple(item.name for item in declared.target.expected_launches),
                              counts=expected_counts(declared.target), artifact=declared.artifact,
                              field_ref=declared.field_ref, explicit_target=True)

    @property
    def has_workload(self) -> bool:
        return any(item.present for item in self.workloads)

    @property
    def segment_target_sources(self) -> dict[str, SourceRef]:
        # Selection/admission is checked by bind_segment_targets. These are the
        # original locations of the latest recorded target declarations.
        latest = {item.segment_id: item for item in self.workflow.executions} if self.workflow is not None else {}
        return {f"followup:{name}": SourceRef(artifact=item.source.artifact,
                    field=f"{item.source.field}.target_selection.expected_launches")
                for name, item in latest.items() if item.target_selection is not None}


def _object(path: Path, artifact: str, issues: list[ParseIssue]) -> dict | None:
    try:
        value = read_json(path)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        issues.append(ParseIssue(code="context_decode", source=SourceRef(artifact=artifact), reason=str(exc), impact="decode"))
        return None
    if not isinstance(value, dict):
        issues.append(ParseIssue(code="context_structure", source=SourceRef(artifact=artifact),
                                 reason="context must be a JSON object", impact="structure"))
        return None
    return value


def _workflow(payload: dict) -> HarnessWorkflow:
    try:
        target = TargetSelection.model_validate(payload["target_selection"]) if payload.get("target_selection") is not None else None
    except ValueError as exc:
        raise ValueError(f"{WORKFLOW_ARTIFACT} target_selection is invalid: {exc}") from exc
    executions = []
    actions = payload.get("follow_up_actions", [])
    if not isinstance(actions, list):
        raise ValueError(f"{WORKFLOW_ARTIFACT} follow_up_actions must be an array")
    for index, item in enumerate(actions):
        if not isinstance(item, dict) or item.get("id") != DEFAULT_FOLLOWUP_ACTION_ID:
            continue
        try:
            status = _ACTION_STATUS.validate_python(item.get("status"), strict=True)
        except ValueError as exc:
            raise ValueError(f"{WORKFLOW_ARTIFACT} follow_up_actions[{index}].status is invalid: {exc}") from exc
        if status in {"skipped", "blocked"}:
            continue
        segment = item.get("segment_id") or item["id"]
        if not is_supported_followup_action_id(segment):
            continue
        try:
            selection = (TargetSelection.model_validate(item["target_selection"])
                         if status == "succeeded" and item.get("target_selection") is not None else None)
        except ValueError as exc:
            raise ValueError(f"{WORKFLOW_ARTIFACT} follow_up_actions target_selection is invalid: {exc}") from exc
        executions.append(FollowupExecution(segment_id=segment, status=status, target_selection=selection,
            source=SourceRef(artifact=WORKFLOW_ARTIFACT, field=f"follow_up_actions[{index}]")))
    return HarnessWorkflow(target_selection=target, executions=executions)


def _metadata_target(payload: object, artifact: str, issues: list[ParseIssue], prefix: str = "") -> ExpectedTarget | None:
    if not isinstance(payload, dict):
        return None
    for field in TARGET_FIELDS:
        if field not in payload:
            continue
        source_field = f"{prefix}{field}"
        try:
            names = _NAMES.validate_python(payload[field])
        except ValidationError as exc:
            issues.append(ParseIssue(code="target_names", source=SourceRef(artifact=artifact, field=source_field),
                                     reason=str(exc), impact="scope"))
        else:
            return ExpectedTarget(names=(names,) if isinstance(names, str) else names, artifact=artifact, field_ref=source_field)
    for key in TARGET_CONTAINERS:
        target = _metadata_target(payload.get(key), artifact, issues, f"{prefix}{key}.")
        if target is not None:
            return target
    return None


def _tilelang_source(payload: object, prefix: str = "") -> str | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in FRAMEWORK_FIELDS and isinstance(value, str) and "tilelang" in value.lower():
                return f"{prefix}{key}"
            found = _tilelang_source(value, f"{prefix}{key}.")
            if found is not None:
                return found
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found = _tilelang_source(value, f"{prefix}[{index}].")
            if found is not None:
                return found
    return None


def normalize_workloads(payload: dict, artifact: str, issues: list[ParseIssue]) -> list[WorkloadContext]:
    out = []
    for path in (("benchmark", "workload"), ("profile_harness", "workload"), ("verify_context", "raw", "workload")):
        value = payload
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        if not isinstance(value, dict):
            if value is not None:
                issues.append(ParseIssue(code="workload_structure", source=SourceRef(artifact=artifact, field=".".join(path)),
                                         reason="workload must be a JSON object", impact="structure"))
            continue
        fields = {key: value[key] for key in ("id", "shape", "dtype", "case_count") if key in value}
        if path[0] == "verify_context" and "task_name" in value:
            fields["id"] = value["task_name"]
            fields["id_field"] = "task_name"
        source = SourceRef(artifact=artifact, field=".".join(path))
        try:
            workload = WorkloadContext(source=source, **fields)
        except ValidationError as exc:
            for error in exc.errors(include_url=False, include_input=False):
                field = error["loc"][0]
                fields.pop(field, None)
                issues.append(ParseIssue(code="workload_field", source=SourceRef(artifact=artifact, field=f"{source.field}.{fields.get('id_field', 'id') if field == 'id' else field}"),
                                         reason=error["msg"], impact="structure"))
            workload = WorkloadContext(source=source, **fields)
        if workload.present:
            out.append(workload)
    return out


def load_analysis_context(run_dir: Path) -> AnalysisContext:
    issues: list[ParseIssue] = []
    workflow_payload = _object(run_dir / WORKFLOW_ARTIFACT, WORKFLOW_ARTIFACT, issues)
    if issues:
        raise ValueError(f"invalid {WORKFLOW_ARTIFACT}: {issues[0].reason}")
    workflow = _workflow(workflow_payload) if workflow_payload is not None else None
    profile_target = None
    metadata_target = None
    inferred_target = None
    workloads = []
    for artifact in (PROFILE_ARTIFACT, TILELANG_ARTIFACT):
        payload = _object(run_dir / artifact, artifact, issues)
        if payload is None:
            continue
        if artifact == PROFILE_ARTIFACT:
            harness = payload.get("profile_harness")
            if isinstance(harness, dict) and harness.get("target") is not None:
                try:
                    profile_target = TargetSelection.model_validate(harness["target"])
                except ValueError as exc:
                    if workflow is None or workflow.target_selection is None:
                        raise ValueError(f"{PROFILE_ARTIFACT} profile_harness.target is invalid: {exc}") from exc
                    issues.append(ParseIssue(code="unused_profile_target", source=SourceRef(
                        artifact=PROFILE_ARTIFACT, field="profile_harness.target"), reason=str(exc), impact="scope"))
        found = _metadata_target(payload, artifact, issues)
        if metadata_target is None:
            metadata_target = found
        framework_source = _tilelang_source(payload)
        if inferred_target is None and framework_source is not None:
            inferred_target = ExpectedTarget(names=("main_kernel",), artifact=artifact,
                                             field_ref=framework_source, inferred=True)
        workloads.extend(normalize_workloads(payload, artifact, issues))
    if metadata_target is None and not any(item.code == "target_names" for item in issues):
        metadata_target = inferred_target
    return AnalysisContext(workflow=workflow, profile_target=profile_target, metadata_target=metadata_target,
                           workloads=workloads, issues=issues)
