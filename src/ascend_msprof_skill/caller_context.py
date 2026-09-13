"""Typed projections of caller-owned context; these are not natural measurements."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, TypeVar

from pydantic import ConfigDict, Field, FiniteFloat, JsonValue, TypeAdapter, ValidationError, model_validator

from .artifact_reader import read_json
from .ascend_profile_utils import to_float
from .collection_context import PROFILE_ARTIFACT, TILELANG_ARTIFACT, WorkloadContext, normalize_workloads
from .evidence_types import ArtifactPath, EvidenceFact, ParseIssue, SourceRef
from .provenance_types import Sourced

_STRICT = ConfigDict(strict=True, allow_inf_nan=False)
_STRING = TypeAdapter(str, config=_STRICT)
_BOOL = TypeAdapter(bool, config=_STRICT)
_COUNT = TypeAdapter(Annotated[int, Field(ge=0)], config=_STRICT)
_CASES = TypeAdapter(Annotated[int, Field(gt=0)], config=_STRICT)
_JSON = TypeAdapter(JsonValue, config=_STRICT)
_WARNINGS = TypeAdapter(list[str], config=_STRICT)
T = TypeVar("T")


class ContextFile(EvidenceFact):
    artifact: str | None = None
    sha256: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)


class ContextSources(EvidenceFact):
    payload: ContextFile | None = None
    application: ContextFile | None = None
    profile_harness_manifest: ContextFile | None = None
    verify_json: ContextFile | None = None


class JitDebug(EvidenceFact):
    found: bool | None
    provided: str | None
    artifact_count: int = Field(ge=0)
    artifacts: Annotated[tuple[ContextFile, ...], Field(strict=False)]


class CorrectnessMaximum(EvidenceFact):
    field: str
    value: FiniteFloat


class ContextRuntime(EvidenceFact):
    value_ms: FiniteFloat
    statistic: str
    mean_ms: FiniteFloat | None
    samples_ms: Annotated[tuple[FiniteFloat, ...], Field(strict=False)]
    authority: str | None
    latency_source: str | None
    runtime: JsonValue
    runtime_stats: JsonValue
    ref_runtime: JsonValue
    source: ArtifactPath
    citations: dict[str, SourceRef]


class BenchmarkContext(EvidenceFact):
    compiled: bool | None = None
    passed: Sourced[bool] | None = None
    error: JsonValue = None
    maxima: Annotated[tuple[CorrectnessMaximum, ...], Field(strict=False)] = ()
    jit_config: JsonValue = None
    runtime: ContextRuntime | None = None


class VerificationContext(EvidenceFact):
    compiled: bool | None = None
    passed: Sourced[bool] | None = None
    error: JsonValue = None
    case_count: int | None = Field(default=None, gt=0)
    runtime: ContextRuntime | None = None


class CallerContext(EvidenceFact):
    artifact: Literal["analysis/profile_context.json", "analysis/tilelang_context.json"]
    sources: ContextSources
    workloads: Annotated[tuple[WorkloadContext, ...], Field(strict=False)]
    benchmark: BenchmarkContext
    verification: VerificationContext
    jit_debug: JitDebug | None
    harness_workload: JsonValue
    harness_jit_config: JsonValue
    warnings: Annotated[tuple[str, ...], Field(strict=False)]
    issues: Annotated[tuple[ParseIssue, ...], Field(strict=False)]

    @model_validator(mode="after")
    def source_scope(self) -> CallerContext:
        refs = [item.source for item in self.workloads]
        if len({ref.field for ref in refs}) != len(refs):
            raise ValueError("caller workload sources must be unique")
        refs.extend(item.source for item in (self.benchmark.passed, self.verification.passed) if item is not None)
        refs.extend(issue.source for issue in self.issues)
        for runtime in (self.benchmark.runtime, self.verification.runtime):
            if runtime is not None:
                if runtime.source != self.artifact:
                    raise ValueError("caller timing belongs to a different context artifact")
                refs.extend(runtime.citations.values())
        if any(ref.artifact != self.artifact for ref in refs):
            raise ValueError("caller facts must cite their own context artifact")
        return self

    def workload(self, field: str) -> WorkloadContext | None:
        return next((item for item in self.workloads if item.source.field == field), None)


def _issue(issues: list[ParseIssue], artifact: str, field: str, reason: str) -> None:
    issues.append(ParseIssue(code="caller_context_field", source=SourceRef(artifact=artifact, field=field),
                             reason=reason, impact="structure"))


def _field(adapter: TypeAdapter[T], value: object, artifact: str, field: str, issues: list[ParseIssue]) -> T | None:
    if value is None:
        return None
    try:
        return adapter.validate_python(value)
    except ValidationError as exc:
        _issue(issues, artifact, field, "; ".join(error["msg"] for error in exc.errors(include_input=False, include_url=False)))
        return None


def _object(value: object, artifact: str, field: str, issues: list[ParseIssue]) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        _issue(issues, artifact, field, "expected a JSON object")
        return {}
    return value


def _file(value: object, artifact: str, prefix: str, issues: list[ParseIssue]) -> ContextFile | None:
    data = _object(value, artifact, prefix, issues)
    fields = {key: _field(adapter, data.get(key), artifact, f"{prefix}.{key}", issues)
              for key, adapter in (("artifact", _STRING), ("sha256", _STRING), ("size_bytes", _COUNT))}
    return ContextFile(**fields) if any(value is not None for value in fields.values()) else None


def _jit(value: object, artifact: str, issues: list[ParseIssue]) -> JitDebug | None:
    if value is None:
        return None
    data = _object(value, artifact, "jit_debug", issues)
    rows = data.get("artifacts", [])
    if not isinstance(rows, list):
        _issue(issues, artifact, "jit_debug.artifacts", "expected an array")
        rows = []
    files = tuple(item for index, row in enumerate(rows)
                  if (item := _file(row, artifact, f"jit_debug.artifacts[{index}]", issues)) is not None)
    count = _field(_COUNT, data.get("artifact_count"), artifact, "jit_debug.artifact_count", issues)
    return JitDebug(found=_field(_BOOL, data.get("found"), artifact, "jit_debug.found", issues),
                    provided=_field(_STRING, data.get("provided"), artifact, "jit_debug.provided", issues),
                    artifact_count=count if count is not None else len(rows), artifacts=files)


def _correctness(value: object, artifact: str, prefix: str, issues: list[ParseIssue]) -> Sourced[bool] | None:
    if isinstance(value, bool):
        return Sourced[bool](value=value, source=SourceRef(artifact=artifact, field=prefix))
    data = _object(value, artifact, prefix, issues)
    for key in ("passed", "correctness_ok", "tolerance_passed"):
        flag = _field(_BOOL, data.get(key), artifact, f"{prefix}.{key}", issues)
        if flag is not None:
            return Sourced[bool](value=flag, source=SourceRef(artifact=artifact, field=f"{prefix}.{key}"))
    return None


def _maxima(value: object, artifact: str, issues: list[ParseIssue]) -> tuple[CorrectnessMaximum, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        _issue(issues, artifact, "benchmark.correctness.maxima", "expected an array")
        return ()
    out = []
    for index, item in enumerate(value):
        try:
            out.append(CorrectnessMaximum.model_validate(item))
        except ValidationError as exc:
            _issue(issues, artifact, f"benchmark.correctness.maxima[{index}]",
                   "; ".join(error["msg"] for error in exc.errors(include_input=False, include_url=False)))
    return tuple(out)


def _number(value: object, artifact: str, field: str, issues: list[ParseIssue]) -> float | None:
    number = to_float(value)
    if number is None and value not in (None, ""):
        _issue(issues, artifact, field, "expected a finite numeric value")
    return number


def _runtime(candidate: dict, artifact: str, issues: list[ParseIssue], *, official: bool = False) -> ContextRuntime | None:
    prefix = "verify_context.raw.official_timing" if official else "benchmark.candidate.runtime_stats"
    stats = candidate if official else _object(candidate.get("runtime_stats"), artifact, prefix, issues)
    value_key = "latency_ms" if official else "value_ms"
    value = _number(stats.get(value_key), artifact, f"{prefix}.{value_key}", issues)
    statistic_key = "aggregation" if official else "statistic"
    statistic = _field(_STRING, stats.get(statistic_key), artifact, f"{prefix}.{statistic_key}", issues)
    if not official and not statistic:
        statistic_key = "aggregation"
        statistic = _field(_STRING, stats.get(statistic_key), artifact, f"{prefix}.{statistic_key}", issues)
    value_field = f"{prefix}.{value_key}"
    statistic_field = f"{prefix}.{statistic_key}"
    mean = None if official else _number(stats.get("mean_ms"), artifact, f"{prefix}.mean_ms", issues)
    raw_runtime = _field(_JSON, candidate.get("runtime"), artifact, "benchmark.candidate.runtime", issues) if not official else value
    if value is None and mean is not None:
        value, statistic = mean, "mean"
        value_field = statistic_field = f"{prefix}.mean_ms"
    if not official and value is None:
        value = _number(raw_runtime, artifact, "benchmark.candidate.runtime", issues)
        if value is not None:
            statistic = statistic or "legacy_runtime"
            value_field = "benchmark.candidate.runtime"
            if statistic == "legacy_runtime":
                statistic_field = value_field
            if statistic in {"mean", "legacy_runtime"}:
                mean = value
    if value is None:
        return None
    if not statistic:
        statistic, statistic_field = "unspecified", value_field
    if official:
        mean = value if statistic == "mean" else None
    elif statistic not in {"mean", "legacy_runtime"}:
        mean = None
    rows = stats.get("samples_ms")
    if rows is not None and not isinstance(rows, list):
        _issue(issues, artifact, f"{prefix}.samples_ms", "expected an array")
        rows = []
    samples = tuple(number for index, raw in enumerate(rows or [])
                    if (number := _number(raw, artifact, f"{prefix}.samples_ms[{index}]", issues)) is not None)
    authority = _field(_STRING, stats.get("authority"), artifact, f"{prefix}.authority", issues)
    latency_source = _field(_STRING, stats.get("latency_source"), artifact, f"{prefix}.latency_source", issues)
    raw_stats = _field(_JSON, stats, artifact, prefix, issues)
    ref = None if official else _field(_JSON, candidate.get("ref_runtime"), artifact, "benchmark.candidate.ref_runtime", issues)
    citations = {"runtime.value_ms": SourceRef(artifact=artifact, field=value_field),
                 "runtime.statistic": SourceRef(artifact=artifact, field=statistic_field)}
    for key, raw, field in (("runtime", raw_runtime, value_field if official else "benchmark.candidate.runtime"),
                            ("runtime_stats", raw_stats, prefix), ("ref_runtime", ref, "benchmark.candidate.ref_runtime")):
        if raw not in (None, "", [], {}):
            citations[f"runtime.{key}"] = SourceRef(artifact=artifact, field=field)
    for key in ("samples_ms", "authority", "latency_source"):
        if key in stats:
            citations[f"runtime.{key}"] = SourceRef(artifact=artifact, field=f"{prefix}.{key}")
    if official:
        raw_stats = {"value_ms": value, "statistic": statistic, "samples_ms": list(samples) if rows is not None else None,
                     "authority": authority, "latency_source": latency_source}
    return ContextRuntime(value_ms=value, statistic=statistic, mean_ms=mean, samples_ms=samples, authority=authority,
        latency_source=latency_source, runtime=raw_runtime, runtime_stats=raw_stats, ref_runtime=ref, source=artifact, citations=citations)


def normalize_caller_context(payload: dict, artifact: str) -> CallerContext:
    issues: list[ParseIssue] = []
    data = _object(payload, artifact, "", issues)
    sources = _object(data.get("sources"), artifact, "sources", issues)
    benchmark = _object(data.get("benchmark"), artifact, "benchmark", issues)
    candidate = _object(benchmark.get("candidate"), artifact, "benchmark.candidate", issues)
    correctness = _object(benchmark.get("correctness"), artifact, "benchmark.correctness", issues)
    harness = _object(data.get("profile_harness"), artifact, "profile_harness", issues)
    verify = _object(data.get("verify_context"), artifact, "verify_context", issues)
    raw = _object(verify.get("raw"), artifact, "verify_context.raw", issues)
    raw_candidate = _object(raw.get("candidate"), artifact, "verify_context.raw.candidate", issues)
    raw_correctness = raw.get("correctness")
    receipt = _object(raw_correctness.get("receipt") if isinstance(raw_correctness, dict) else None,
                      artifact, "verify_context.raw.correctness.receipt", issues)
    official = _object(raw.get("official_timing"), artifact, "verify_context.raw.official_timing", issues)
    workloads = normalize_workloads(data, artifact, issues)
    return CallerContext(artifact=artifact,
        sources=ContextSources(**{key: _file(sources.get(key), artifact, f"sources.{key}", issues)
                                  for key in ("payload", "application", "profile_harness_manifest", "verify_json")}),
        workloads=workloads,
        benchmark=BenchmarkContext(
            compiled=_field(_BOOL, candidate.get("compiled"), artifact, "benchmark.candidate.compiled", issues),
            passed=_correctness(correctness.get("raw"), artifact, "benchmark.correctness.raw", issues),
            error=_field(_JSON, candidate.get("error"), artifact, "benchmark.candidate.error", issues),
            maxima=_maxima(correctness.get("maxima"), artifact, issues),
            jit_config=_field(_JSON, benchmark.get("jit_config"), artifact, "benchmark.jit_config", issues),
            runtime=_runtime(candidate, artifact, issues)),
        verification=VerificationContext(
            compiled=_field(_BOOL, raw_candidate.get("compiled"), artifact, "verify_context.raw.candidate.compiled", issues),
            passed=_correctness(raw_correctness, artifact, "verify_context.raw.correctness", issues),
            error=_field(_JSON, raw_candidate.get("error"), artifact, "verify_context.raw.candidate.error", issues),
            case_count=_field(_CASES, receipt.get("case_count"), artifact, "verify_context.raw.correctness.receipt.case_count", issues),
            runtime=_runtime(official, artifact, issues, official=True)),
        jit_debug=_jit(data.get("jit_debug"), artifact, issues),
        harness_workload=_field(_JSON, harness.get("workload"), artifact, "profile_harness.workload", issues),
        harness_jit_config=_field(_JSON, harness.get("jit_config"), artifact, "profile_harness.jit_config", issues),
        warnings=_field(_WARNINGS, data.get("warnings"), artifact, "warnings", issues) or [], issues=issues)


def load_caller_context(run_dir: Path, artifact: str, warnings: list[str], *, warn_missing: bool = True) -> CallerContext | None:
    try:
        payload = read_json(run_dir / artifact)
    except FileNotFoundError:
        if warn_missing:
            warnings.append(f"missing {artifact}")
        return None
    except (OSError, ValueError) as exc:
        warnings.append(f"invalid {artifact}: {exc}")
        return None
    if not isinstance(payload, dict):
        warnings.append(f"invalid {artifact}: expected a JSON object")
        return None
    return normalize_caller_context(payload, artifact)
