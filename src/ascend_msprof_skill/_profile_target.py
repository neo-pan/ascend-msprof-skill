"""Declared profile target normalization shared by collection and analysis."""
from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any

from .ascend_profile_utils import normalized_key


TARGET_KEYS = {"kernel_selector", "expected_launches"}
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


def normalize_target_contract(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if manifest is None or "target" not in manifest:
        return None
    raw_target = manifest.get("target")
    if not isinstance(raw_target, dict):
        raise ValueError("profile harness target must contain an object")
    unexpected = sorted(set(raw_target) - TARGET_KEYS)
    if unexpected:
        raise ValueError(
            "profile harness target accepts only kernel_selector and expected_launches; "
            f"unexpected field(s): {', '.join(unexpected)}"
        )
    selector = raw_target.get("kernel_selector")
    if not isinstance(selector, str) or not selector.strip():
        raise ValueError("profile harness target.kernel_selector must be a non-empty string")
    raw_launches = raw_target.get("expected_launches")
    if not isinstance(raw_launches, list) or not raw_launches:
        raise ValueError("profile harness target.expected_launches must be a non-empty list")

    launches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_launches):
        label = f"profile harness target.expected_launches[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{label} must contain an object")
        unexpected_launch = sorted(set(item) - {"name", "count"})
        if unexpected_launch:
            raise ValueError(
                f"{label} accepts only name and count; unexpected field(s): {', '.join(unexpected_launch)}"
            )
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{label}.name must be a non-empty string")
        count = item.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise ValueError(f"{label}.count must be a positive integer")
        normalized_name = normalize_target_name(name)
        if not normalized_name:
            raise ValueError(f"{label}.name must contain letters or digits")
        if normalized_name in seen:
            raise ValueError(
                "profile harness target expected launch names must be unique after normalization: "
                f"{name.strip()}"
            )
        seen.add(normalized_name)
        launches.append(
            {
                "name": name.strip(),
                "normalized_name": normalized_name,
                "count": count,
            }
        )
    return {
        "kernel_selector": selector.strip(),
        "expected_launches": launches,
        "launch_count": sum(int(item["count"]) for item in launches),
    }


def normalize_persisted_target(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("persisted profile target must contain an object")
    launches = value.get("expected_launches")
    raw_launches = []
    if isinstance(launches, list):
        for item in launches:
            if not isinstance(item, dict):
                raise ValueError("persisted profile target expected_launches is invalid")
            raw_launches.append({"name": item.get("name"), "count": item.get("count")})
    return normalize_target_contract(
        {
            "target": {
                "kernel_selector": value.get("kernel_selector"),
                "expected_launches": raw_launches,
            }
        }
    )


def validate_target_subset(
    parent: dict[str, Any] | None,
    subset: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if subset is None:
        return None
    if parent is None:
        raise ValueError("focused follow-up target requires a persisted program target")
    parent_counts = expected_counts(parent)
    parent_names = expected_display_names(parent)
    selector = str(subset["kernel_selector"])
    selected_names: set[str] = set()
    for item in subset.get("expected_launches", []):
        normalized_name = str(item["normalized_name"])
        name = str(item["name"])
        if normalized_name not in parent_counts:
            raise ValueError(f"focused follow-up target is not a program-target subset: {name}")
        if int(item["count"]) > parent_counts[normalized_name]:
            raise ValueError(
                "focused follow-up launch count exceeds the persisted program target for "
                f"{name}: {item['count']} > {parent_counts[normalized_name]}"
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
    return subset


def expected_counts(target: dict[str, Any] | None) -> dict[str, int]:
    if not isinstance(target, dict):
        return {}
    return {
        str(item["normalized_name"]): int(item["count"])
        for item in target.get("expected_launches", [])
        if isinstance(item, dict) and item.get("normalized_name") and item.get("count")
    }


def expected_display_names(target: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(target, dict):
        return {}
    return {
        str(item["normalized_name"]): str(item["name"])
        for item in target.get("expected_launches", [])
        if isinstance(item, dict) and item.get("normalized_name") and item.get("name")
    }


def match_expected_name(target: dict[str, Any] | None, observed: object) -> tuple[str | None, str]:
    observed_name = str(observed or "")
    if not isinstance(target, dict):
        return None, "unmatched"
    known_suffix_match: str | None = None
    for item in target.get("expected_launches", []):
        if not isinstance(item, dict):
            continue
        normalized_name = str(item.get("normalized_name") or "")
        rule = target_name_match_rule(str(item.get("name") or normalized_name), observed_name)
        if rule == "exact":
            return normalized_name, rule
        if rule == "known_suffix" and (
            known_suffix_match is None or len(normalized_name) > len(known_suffix_match)
        ):
            known_suffix_match = normalized_name
    return (known_suffix_match, "known_suffix") if known_suffix_match else (None, "unmatched")
