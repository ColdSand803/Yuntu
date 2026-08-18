"""Deterministic validation for semantic A/B candidate grouping."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.agents.composition_blueprint import is_food_place
from src.agents.diversity import (
    IN_RESPONSE_OVERLAP_TARGET,
    MAX_CANDIDATES_PER_GROUP,
    MIN_PLACES_PER_PLAN,
    overlap_ratio,
)
from src.agents.schema import CandidateGroup, CandidatePlace

MIN_GROUP_SIZE = MIN_PLACES_PER_PLAN
MAX_GROUP_SIZE = MAX_CANDIDATES_PER_GROUP
MIN_GROUPING_CANDIDATES = MIN_PLACES_PER_PLAN * 2


@dataclass
class GroupValidationResult:
    accepted: bool = False
    groups: list[CandidateGroup] = field(default_factory=list)
    group_overlap_ratio: float | None = None
    unused_candidate_count: int = 0
    unused_candidate_ratio: float | None = None
    unused_high_score_count: int = 0
    group_truncated_count: int = 0
    validation_failures: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)


def _failure(reason: str) -> GroupValidationResult:
    return GroupValidationResult(validation_failures=[reason])


def _high_score(place: CandidatePlace) -> bool:
    return place.recommend_score >= 8.0


def _candidate_ids(group: CandidateGroup) -> list[int]:
    return [candidate.place_id for candidate in group.candidates]


def _unused_metrics(
    groups: list[CandidateGroup],
    pool: list[CandidatePlace],
) -> tuple[int, float | None, int]:
    used_ids = {
        candidate.place_id
        for group in groups
        for candidate in group.candidates
    }
    unused = [
        candidate for candidate in pool
        if candidate.place_id not in used_ids
    ]
    ratio = len(unused) / len(pool) if pool else None
    return len(unused), ratio, sum(1 for candidate in unused if _high_score(candidate))


def validate_grouping_payload(
    payload: dict[str, Any],
    candidate_pool: list[CandidatePlace],
) -> GroupValidationResult:
    """Return accepted groups or blocking validation failures.

    The only non-blocking mutation is truncating oversized groups before every
    size, overlap, and composition check.
    """
    if not candidate_pool:
        return _failure("empty_candidates")
    if not isinstance(payload, dict):
        return _failure("schema_validation_error")
    raw_groups = payload.get("groups")
    if not isinstance(raw_groups, list) or len(raw_groups) != 2:
        return _failure("schema_validation_error")

    pool_by_id = {candidate.place_id: candidate for candidate in candidate_pool}
    parsed_by_label: dict[str, tuple[str, list[int]]] = {}
    for item in raw_groups:
        if not isinstance(item, dict):
            return _failure("schema_validation_error")
        label = item.get("label")
        ids = item.get("candidate_place_ids")
        if label not in {"A", "B"} or not isinstance(ids, list):
            return _failure("schema_validation_error")
        if label in parsed_by_label:
            return _failure("schema_validation_error")
        if not all(isinstance(place_id, int) for place_id in ids):
            return _failure("schema_validation_error")
        if len(set(ids)) != len(ids):
            return _failure("schema_validation_error")
        internal_theme = item.get("internal_theme", "")
        parsed_by_label[label] = (
            internal_theme.strip() if isinstance(internal_theme, str) else "",
            ids,
        )

    if set(parsed_by_label) != {"A", "B"}:
        return _failure("schema_validation_error")

    for _, ids in parsed_by_label.values():
        if any(place_id not in pool_by_id for place_id in ids):
            return _failure("unknown_place_id")

    groups: list[CandidateGroup] = []
    truncated = 0
    for label in ("A", "B"):
        internal_theme, ids = parsed_by_label[label]
        if len(ids) > MAX_GROUP_SIZE:
            ids = ids[:MAX_GROUP_SIZE]
            truncated += 1
        groups.append(CandidateGroup(
            label=label,
            internal_theme=internal_theme,
            candidates=[pool_by_id[place_id] for place_id in ids],
        ))

    failures = []
    for group in groups:
        if len(group.candidates) < MIN_GROUP_SIZE:
            failures.append("group_too_small")
            break
    overlap = overlap_ratio(_candidate_ids(groups[0]), _candidate_ids(groups[1]))
    if overlap is None or overlap > IN_RESPONSE_OVERLAP_TARGET:
        failures.append("overlap_too_high")
    for group in groups:
        if not any(not is_food_place(candidate) for candidate in group.candidates):
            failures.append("missing_activity_place")
            break
    for group in groups:
        if group.candidates and all(is_food_place(candidate) for candidate in group.candidates):
            failures.append("all_food_group")
            break
    if failures:
        return GroupValidationResult(
            groups=groups,
            group_overlap_ratio=overlap,
            group_truncated_count=truncated,
            validation_failures=failures,
        )

    unused_count, unused_ratio, unused_high_count = _unused_metrics(groups, candidate_pool)
    warnings = []
    if unused_ratio is not None and unused_ratio > 0.4:
        warnings.append("unused_candidate_ratio_high")
    if unused_high_count:
        warnings.append("unused_high_score_count")
    if truncated:
        warnings.append("group_truncated")
    return GroupValidationResult(
        accepted=True,
        groups=groups,
        group_overlap_ratio=overlap,
        unused_candidate_count=unused_count,
        unused_candidate_ratio=unused_ratio,
        unused_high_score_count=unused_high_count,
        group_truncated_count=truncated,
        validation_warnings=warnings,
    )
