"""LLM-proposed, deterministic-validated candidate grouping."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from src.agents import llm
from src.agents.diversity import (
    IN_RESPONSE_OVERLAP_TARGET,
    MIN_PLACES_PER_PLAN,
    build_candidate_groups,
    overlap_ratio,
)
from src.agents.group_validator import (
    MIN_GROUPING_CANDIDATES,
    GroupValidationResult,
    validate_grouping_payload,
)
from src.agents.schema import CandidateGroup, CandidatePlace, RetrievalResult, TripRequest
from src.config import get_settings

logger = logging.getLogger(__name__)

_EVENING_MARKERS = ("夜景", "夜市", "晚上", "傍晚", "日落", "灯光")
_MORNING_MARKERS = ("早餐", "早晨", "上午", "清晨")
_DAYTIME_MARKERS = ("博物馆", "公园", "古镇", "街区", "徒步", "citywalk")


@dataclass
class SemanticGroupingMetrics:
    attempted: bool = False
    succeeded: bool = False
    fallback_used: bool = False
    fallback_reason: str = ""

    provider: str = ""
    model: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    group_count: int = 0
    group_sizes: list[int] = field(default_factory=list)
    group_overlap_ratio: float | None = None
    group_truncated_count: int = 0

    unused_candidate_count: int = 0
    unused_candidate_ratio: float | None = None
    unused_high_score_count: int = 0
    must_include_backstop_appended: int = 0

    internal_themes: list[str] = field(default_factory=list)
    validation_failures: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_stage_metadata(self) -> dict[str, Any]:
        return {
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "group_sizes": self.group_sizes,
            "internal_themes": self.internal_themes,
            "unused_candidate_ratio": self.unused_candidate_ratio,
            "must_include_backstop_appended": self.must_include_backstop_appended,
        }


def _bounded_text(value: Any, *, limit: int = 80) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _reason_snippets(items: list[dict], *, limit: int) -> list[str]:
    snippets = []
    for item in items:
        if not isinstance(item, dict) or not item.get("reason"):
            continue
        snippets.append(_bounded_text(item.get("reason")))
        if len(snippets) >= limit:
            break
    return snippets


def _score_bucket(score: float) -> str:
    if score >= 8.0:
        return "high"
    if score >= 5.0:
        return "medium"
    return "low"


def _candidate_text(candidate: CandidatePlace) -> str:
    parts = [candidate.name, candidate.place_type, *(candidate.category_tags or [])]
    for item in [*candidate.top_reasons, *candidate.warnings]:
        if isinstance(item, dict) and item.get("reason"):
            parts.append(str(item["reason"]))
    return " ".join(parts).lower()


def _time_tags(candidate: CandidatePlace) -> list[str]:
    text = _candidate_text(candidate)
    tags = []
    if any(marker.lower() in text for marker in _EVENING_MARKERS):
        tags.append("evening")
    if any(marker.lower() in text for marker in _MORNING_MARKERS):
        tags.append("morning")
    if any(marker.lower() in text for marker in _DAYTIME_MARKERS):
        tags.append("daytime")
    return tags or ["daytime"]


def _preference_tags(candidate: CandidatePlace, preferences: list[str]) -> list[str]:
    text = _candidate_text(candidate)
    pref_text = " ".join(preferences).lower()
    tags = []
    if candidate.place_type.lower() in {"restaurant", "food", "snack", "cafe", "dessert", "market"}:
        tags.append("food")
    if any(marker in text for marker in ("拍照", "打卡", "photo", "夜景", "观景")):
        tags.append("photo")
    if any(marker in text or marker in pref_text for marker in ("citywalk", "街区", "散步", "逛")):
        tags.append("citywalk")
    if any(marker in text for marker in ("经典", "地标", "必去", "老城")):
        tags.append("classic")
    if any(marker in pref_text for marker in ("亲子", "family")):
        tags.append("family")
    if any(marker in pref_text for marker in ("自然", "公园", "湖", "山")):
        tags.append("nature")
    return list(dict.fromkeys(tags))[:5]


def _build_grouping_input(
    trip_request: TripRequest,
    candidates: list[CandidatePlace],
) -> dict[str, Any]:
    return {
        "request": {
            "to_city": trip_request.to_city,
            "days": trip_request.days,
            "people_count": trip_request.people_count,
            "preferences": trip_request.preferences,
            "avoid": trip_request.avoid,
            "notes": trip_request.notes,
        },
        "candidates": [
            {
                "place_id": candidate.place_id,
                "name": candidate.name,
                "place_type": candidate.place_type,
                "district": candidate.district or "",
                "category_tags": [str(item) for item in candidate.category_tags[:3]],
                "reason_snippets": _reason_snippets(candidate.top_reasons, limit=2),
                "warning_snippets": _reason_snippets(candidate.warnings, limit=2),
                "recommend_score_bucket": _score_bucket(candidate.recommend_score),
                "time_tags": _time_tags(candidate),
                "preference_tags": _preference_tags(candidate, trip_request.preferences),
            }
            for candidate in candidates
        ],
    }


def _fallback_groups(
    retrieval: RetrievalResult,
    metrics: SemanticGroupingMetrics,
    reason: str,
) -> None:
    groups, overlap, diversity_gap = build_candidate_groups(retrieval.candidates)
    retrieval.candidate_groups = groups
    retrieval.in_response_candidate_overlap = overlap
    retrieval.diversity_gap = diversity_gap
    metrics.fallback_used = True
    metrics.fallback_reason = reason
    metrics.must_include_backstop_appended = _append_missing_must_include_candidates(
        retrieval
    )
    if metrics.must_include_backstop_appended:
        retrieval.in_response_candidate_overlap = candidate_group_overlap(
            retrieval.candidate_groups
        )
        retrieval.diversity_gap = _legacy_diversity_gap(
            retrieval.candidate_groups,
            retrieval.in_response_candidate_overlap,
        )
    _record_final_group_metrics(
        metrics,
        retrieval.candidate_groups,
        retrieval.in_response_candidate_overlap,
    )


def _record_final_group_metrics(
    metrics: SemanticGroupingMetrics,
    groups: list[CandidateGroup],
    overlap: float | None,
) -> None:
    metrics.group_count = len(groups)
    metrics.group_sizes = [len(group.candidates) for group in groups]
    metrics.group_overlap_ratio = overlap
    metrics.internal_themes = [
        group.internal_theme for group in groups
        if group.internal_theme
    ]


def _coordinate(candidate: CandidatePlace) -> tuple[float, float] | None:
    if candidate.latitude is None or candidate.longitude is None:
        return None
    return (float(candidate.latitude), float(candidate.longitude))


def _mean_group_coordinate(group: CandidateGroup) -> tuple[float, float] | None:
    coordinates = [
        coordinate
        for candidate in group.candidates
        for coordinate in [_coordinate(candidate)]
        if coordinate is not None
    ]
    if not coordinates:
        return None
    return (
        sum(latitude for latitude, _ in coordinates) / len(coordinates),
        sum(longitude for _, longitude in coordinates) / len(coordinates),
    )


def _coordinate_distance(
    left: tuple[float, float] | None,
    right: tuple[float, float] | None,
) -> float:
    if left is None or right is None:
        return float("inf")
    return (left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2


def _nearest_group_index(
    candidate: CandidatePlace,
    groups: list[CandidateGroup],
) -> int:
    candidate_coordinate = _coordinate(candidate)
    group_coordinates = [_mean_group_coordinate(group) for group in groups]
    return min(
        range(len(groups)),
        key=lambda index: (
            _coordinate_distance(candidate_coordinate, group_coordinates[index]),
            -len(groups[index].candidates),
            index,
        ),
    )


def _append_missing_must_include_candidates(retrieval: RetrievalResult) -> int:
    groups = retrieval.candidate_groups
    if not groups:
        return 0
    grouped_ids = {
        candidate.place_id
        for group in groups
        for candidate in group.candidates
    }
    appended = 0
    for candidate in retrieval.candidates:
        if not candidate.must_include or candidate.place_id in grouped_ids:
            continue
        group_index = _nearest_group_index(candidate, groups)
        groups[group_index].candidates.append(candidate)
        grouped_ids.add(candidate.place_id)
        appended += 1
    return appended


def _legacy_diversity_gap(groups: list[CandidateGroup], overlap: float | None) -> bool:
    return (
        len(groups) < 2
        or any(len(group.candidates) < MIN_PLACES_PER_PLAN for group in groups)
        or overlap is None
        or overlap > IN_RESPONSE_OVERLAP_TARGET
    )


def _apply_accepted(
    retrieval: RetrievalResult,
    metrics: SemanticGroupingMetrics,
    validation: GroupValidationResult,
) -> None:
    retrieval.candidate_groups = validation.groups
    retrieval.in_response_candidate_overlap = validation.group_overlap_ratio
    retrieval.diversity_gap = _legacy_diversity_gap(
        validation.groups,
        validation.group_overlap_ratio,
    )
    metrics.succeeded = True
    metrics.group_truncated_count = validation.group_truncated_count
    metrics.unused_candidate_count = validation.unused_candidate_count
    metrics.unused_candidate_ratio = validation.unused_candidate_ratio
    metrics.unused_high_score_count = validation.unused_high_score_count
    metrics.validation_warnings = validation.validation_warnings
    metrics.must_include_backstop_appended = _append_missing_must_include_candidates(
        retrieval
    )
    if metrics.must_include_backstop_appended:
        retrieval.in_response_candidate_overlap = candidate_group_overlap(
            retrieval.candidate_groups
        )
        retrieval.diversity_gap = _legacy_diversity_gap(
            retrieval.candidate_groups,
            retrieval.in_response_candidate_overlap,
        )
    _record_final_group_metrics(
        metrics,
        retrieval.candidate_groups,
        retrieval.in_response_candidate_overlap,
    )


def _system_prompt() -> str:
    return (
        "你是旅行候选 POI 语义分组器。只返回一个 JSON object，不要输出解释。"
        "你只能基于输入 place_id 把候选地点分成 A/B 两组；"
        "不能发明地点，不能规划路线，不能安排日期或时间槽，不能过滤 avoid。"
        "输出 exactly two groups: A and B。每组 5-15 个 place_id，"
        "至少一个非餐饮活动地点，不能全是餐饮。"
        "按主题、体验类型、用户偏好和大致地理接近性分组，不要按分数奇偶或高低排序。"
        "internal_theme 是内部观察字段，不是用户标题。"
        '必须严格使用这个 JSON schema: '
        '{"groups":[{"label":"A","internal_theme":"string",'
        '"candidate_place_ids":[1,2,3,4,5]},'
        '{"label":"B","internal_theme":"string",'
        '"candidate_place_ids":[6,7,8,9,10]}]}。'
        "candidate_place_ids 必须是整数数组，只能使用输入中已有的 place_id。"
    )


async def group_candidates(
    trip_request: TripRequest,
    retrieval: RetrievalResult,
) -> SemanticGroupingMetrics:
    """Populate retrieval.candidate_groups, with deterministic fallback."""
    metrics = SemanticGroupingMetrics()
    if not retrieval.candidates:
        _fallback_groups(retrieval, metrics, "empty_candidates")
        return metrics
    if len(retrieval.candidates) < MIN_GROUPING_CANDIDATES:
        _fallback_groups(retrieval, metrics, "candidate_pool_too_small")
        return metrics

    metrics.attempted = True
    payload = _build_grouping_input(trip_request, retrieval.candidates)
    try:
        with llm.llm_call_context(
            call_reason="semantic_grouping",
            max_tokens_request=1600,
            relay_request_timeout_seconds=30,
            relay_hedge_delay_seconds=1,
        ):
            raw, usage = await llm.chat_with_usage(
                _system_prompt(),
                json.dumps(payload, ensure_ascii=False),
                role="grouping",
                temperature=float(get_settings().grouping_temperature),
                json_mode=True,
            )
        metrics.provider = str(usage.get("provider", ""))
        metrics.model = str(usage.get("model", ""))
        metrics.latency_ms = int(usage.get("latency_ms", 0) or 0)
        metrics.prompt_tokens = int(usage.get("token_input", 0) or 0)
        metrics.completion_tokens = int(usage.get("token_output", 0) or 0)
        metrics.total_tokens = metrics.prompt_tokens + metrics.completion_tokens
    except Exception as exc:
        logger.warning("Semantic Grouping LLM failed; falling back: %s", exc)
        metrics.validation_failures = ["llm_error"]
        _fallback_groups(retrieval, metrics, "llm_error")
        return metrics

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        metrics.validation_failures = ["json_parse_error"]
        _fallback_groups(retrieval, metrics, "json_parse_error")
        return metrics

    validation = validate_grouping_payload(parsed, retrieval.candidates)
    metrics.validation_failures = validation.validation_failures
    metrics.validation_warnings = validation.validation_warnings
    if not validation.accepted:
        reason = validation.validation_failures[0] if validation.validation_failures else "schema_validation_error"
        _fallback_groups(retrieval, metrics, f"validation_failed:{reason}")
        return metrics

    _apply_accepted(retrieval, metrics, validation)
    return metrics


def candidate_group_overlap(groups: list[CandidateGroup]) -> float | None:
    if len(groups) < 2:
        return None
    return overlap_ratio(
        (candidate.place_id for candidate in groups[0].candidates),
        (candidate.place_id for candidate in groups[1].candidates),
    )
