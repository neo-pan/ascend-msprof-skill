"""Declared profile target normalization shared by collection and analysis."""
from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Annotated, Any

from pydantic import Field, StringConstraints, field_validator, model_validator
from .evidence_types import EvidenceFact

from .ascend_profile_utils import normalized_key


TARGET_NAME_SUFFIXES = ("mixaic", "aic", "aiv", "cube", "vector")


def normalize_target_name(value: object) -> str:
    return normalized_key(str(value))


def target_name_match_rule(expected: str, observed: str) -> str:
    expected_norm = normalize_target_name(expected)
    observed_norm = normalize_target_name(observed)
    if not expected_norm or not observed_norm:
        return "unmatched"
    if expected_norm == observed_norm:
        return "exact"
    if observed_norm.startswith(expected_norm) and observed_norm[len(expected_norm):] in TARGET_NAME_SUFFIXES:
        return "known_suffix"
    return "unmatched"


TargetText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ExpectedLaunch(EvidenceFact):
    name: TargetText
    count: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def meaningful_name(cls, value: str) -> str:
        if not normalize_target_name(value):
            raise ValueError("target name must contain letters or digits")
        return value

    @property
    def normalized_name(self) -> str:
        return normalize_target_name(self.name)


class TargetSelection(EvidenceFact):
    kernel_selector: TargetText
    expected_launches: Annotated[tuple[ExpectedLaunch, ...], Field(strict=False, min_length=1)]

    @model_validator(mode="after")
    def unique_names(self) -> TargetSelection:
        names = [item.normalized_name for item in self.expected_launches]
        if len(set(names)) != len(names):
            raise ValueError("expected launch names must be unique after normalization")
        return self

    @property
    def launch_count(self) -> int:
        return sum(item.count for item in self.expected_launches)


def normalize_target_contract(manifest: dict[str, Any] | None) -> TargetSelection | None:
    if manifest is None or "target" not in manifest:
        return None
    return TargetSelection.model_validate(manifest["target"])


def normalize_persisted_target(value: object) -> TargetSelection | None:
    return TargetSelection.model_validate(value) if value is not None else None


def validate_target_subset(
    parent: TargetSelection | None,
    subset: TargetSelection | None,
) -> TargetSelection | None:
    if subset is None:
        return None
    if parent is None:
        raise ValueError("focused follow-up target requires a persisted program target")
    parent_counts = expected_counts(parent)
    parent_names = expected_display_names(parent)
    selector = subset.kernel_selector
    selected_names: set[str] = set()
    for item in subset.expected_launches:
        normalized_name = item.normalized_name
        name = item.name
        if normalized_name not in parent_counts:
            raise ValueError(f"focused follow-up target is not a program-target subset: {name}")
        if item.count > parent_counts[normalized_name]:
            raise ValueError(
                "focused follow-up launch count exceeds the persisted program target for "
                f"{name}: {item.count} > {parent_counts[normalized_name]}"
            )
        if not fnmatchcase(name, selector):
            raise ValueError(
                "focused follow-up target.kernel_selector must match every selected expected launch name: "
                f"{name}"
            )
        selected_names.add(normalized_name)
    unselected_matches = sorted(
        name
        for normalized_name, name in parent_names.items()
        if normalized_name not in selected_names and fnmatchcase(name, selector)
    )
    if unselected_matches:
        raise ValueError(
            "focused follow-up target.kernel_selector must not match unselected program target name(s): "
            + ", ".join(unselected_matches)
        )
    if expected_counts(subset) == parent_counts and (
        len(parent_counts) != 1 or sum(parent_counts.values()) != 1
    ):
        raise ValueError(
            "focused follow-up target must be a proper subset unless the program has exactly one target launch"
        )
    return subset


def expected_counts(target: TargetSelection | None) -> dict[str, int]:
    return {item.normalized_name: item.count for item in target.expected_launches} if target is not None else {}


def expected_display_names(target: TargetSelection | None) -> dict[str, str]:
    return {item.normalized_name: item.name for item in target.expected_launches} if target is not None else {}


def match_expected_name(target: TargetSelection | None, observed: object) -> tuple[str | None, str]:
    return match_expected_names(expected_display_names(target), observed)


def match_expected_names(names: dict[str, str], observed: object) -> tuple[str | None, str]:
    observed_name = str(observed or "")
    known_suffix_match: str | None = None
    for normalized_name, name in names.items():
        rule = target_name_match_rule(name, observed_name)
        if rule == "exact":
            return normalized_name, rule
        if rule == "known_suffix" and (
            known_suffix_match is None or len(normalized_name) > len(known_suffix_match)
        ):
            known_suffix_match = normalized_name
    return (known_suffix_match, "known_suffix") if known_suffix_match else (None, "unmatched")
