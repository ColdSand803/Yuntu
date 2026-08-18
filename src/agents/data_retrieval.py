"""Data Retrieval: query canonical places with optional summary evidence."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text

from src.agents.diversity import (
    is_specific_place_name,
    rank_candidates,
)
from src.agents.schema import CandidatePlace, RetrievalResult, TripRequest
from src.pipeline.db import get_session_factory

logger = logging.getLogger(__name__)

MAX_QUALIFIED_POOL_SIZE = 500
MAX_ROUTE_PLANNING_CANDIDATES = 120

_PLACE_TYPE_PREFERENCE_DIMENSIONS = {
    # English/generic food intent. Chinese meal phrases live under "meal"
    # so "本地小吃" does not get satisfied by cafes filling the route.
    "food": {
        "markers": ("food",),
        "place_types": ("restaurant", "food", "snack", "dessert", "market"),
    },
    "meal": {
        "markers": ("本地小吃", "小吃", "美食", "吃饭", "餐厅", "火锅", "吃"),
        "place_types": ("restaurant", "food", "snack", "market"),
    },
    "cafe": {
        "markers": ("咖啡", "咖啡店", "咖啡馆", "cafe"),
        "place_types": ("cafe",),
    },
    "night_view": {
        "markers": ("夜景", "夜晚", "夜间", "灯光"),
        "place_types": ("photo_spot", "attraction"),
    },
    "neighborhood": {
        "markers": ("生活街区", "街区", "市井", "烟火气"),
        "place_types": ("business_area", "market", "other"),
    },
    "photo": {
        "markers": ("拍照", "打卡", "photo"),
        "place_types": ("photo_spot", "attraction"),
    },
    "shopping": {
        "markers": ("逛街", "购物"),
        "place_types": ("business_area", "market"),
    },
    "park": {
        "markers": ("公园", "园林"),
        "place_types": ("park", "garden"),
    },
    "museum": {
        "markers": ("博物馆", "博物院", "美术馆", "museum"),
        "place_types": ("museum",),
    },
    "lodging": {
        "markers": ("住宿", "酒店"),
        "place_types": ("hotel",),
    },
}

_FOOD_PLACE_TYPES = {"restaurant", "food", "cafe", "snack", "dessert", "market"}
_ADMIN_SUFFIXES = ("市", "区", "县")

# Semantic avoid: when user says e.g. "不要太网红", expand to concrete POI names.
# Only well-known tourist-heavy landmarks per city. must_include overrides.
_SEMANTIC_AVOID_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "网红": (
        # 重庆
        "洪崖洞", "解放碑", "李子坝",
        # 成都
        "太古里", "宽窄巷子", "春熙路", "锦里",
        # 西安
        "大唐不夜城", "回民街",
        # 南京
        "夫子庙", "新街口",
        # 长沙
        "坡子街", "太平老街",
        # 杭州
        "河坊街",
        # 上海
        "南京路", "外滩", "田子坊",
        # 北京
        "南锣鼓巷", "王府井",
    ),
}

# Prefer offline-cleaned evidence when the cleaner left at least one usable
# reason. Empty cleaned_evidence [] means "processed, nothing survived" and must
# fall back to raw top_reasons so a place does not lose all authorization text.
_TOP_REASONS_SELECT_SQL = """
CASE
  WHEN s.cleaned_evidence IS NOT NULL
       AND jsonb_typeof(s.cleaned_evidence) = 'array'
       AND jsonb_array_length(s.cleaned_evidence) > 0
  THEN s.cleaned_evidence
  ELSE COALESCE(s.top_reasons, '[]'::jsonb)
END AS top_reasons
""".strip()


def preference_place_type_dimensions(
    preferences: list[str],
) -> dict[str, set[str]]:
    """Map explicit preferences to reusable place-type dimensions."""
    preference_text = " ".join(preferences).lower()
    dimensions: dict[str, set[str]] = {}
    for dimension, rule in _PLACE_TYPE_PREFERENCE_DIMENSIONS.items():
        markers = rule["markers"]
        if any(marker.lower() in preference_text for marker in markers):
            dimensions[dimension] = set(rule["place_types"])
    return dimensions


def preferred_place_types(preferences: list[str]) -> set[str]:
    """Map user preferences to place_type values for deterministic boosting."""
    return {
        place_type
        for place_types in preference_place_type_dimensions(preferences).values()
        for place_type in place_types
    }


def is_food_place(place: CandidatePlace) -> bool:
    """Check if a place is food-related."""
    return place.place_type in _FOOD_PLACE_TYPES


def _json_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    return []


def resolve_top_reasons_for_candidate(
    top_reasons: Any,
    cleaned_evidence: Any = None,
) -> list[dict]:
    """Prefer non-empty cleaned_evidence; otherwise keep raw top_reasons.

    Used by candidate assembly so offline shell-cleaning can feed Writer
    authorization without changing CandidatePlace field names. Empty cleaned
    arrays intentionally fall back — they mean "ran cleaner, nothing passed".
    """
    cleaned_items = [
        item for item in _json_list(cleaned_evidence) if isinstance(item, dict)
    ]
    if cleaned_items:
        return cleaned_items
    return [item for item in _json_list(top_reasons) if isinstance(item, dict)]


def _admissible_canonical_candidate(candidate: CandidatePlace, *, city: str) -> bool:
    normalized_name = candidate.name.strip()
    return (
        candidate.base_priority > 0
        and candidate.latitude is not None
        and candidate.longitude is not None
        and is_specific_place_name(city=city, name=candidate.name)
        and not (
            len(normalized_name) <= 4
            and normalized_name.endswith(_ADMIN_SUFFIXES)
        )
    )


def _candidate_from_row(row: Any, *, must_include: bool = False) -> CandidatePlace:
    place_id = int(row.place_id)
    return CandidatePlace(
        place_id=place_id,
        canonical_place_id=place_id,
        name=str(row.name),
        place_type=str(row.place_type),
        district=str(row.district) if row.district else None,
        category_tags=[str(item) for item in _json_list(row.category_tags)],
        base_priority=int(row.base_priority or 0),
        typical_visit_minutes=(
            int(row.typical_visit_minutes)
            if getattr(row, "typical_visit_minutes", None) is not None
            else None
        ),
        typical_visit_source=(
            str(row.typical_visit_source)
            if getattr(row, "typical_visit_source", None)
            else None
        ),
        typical_visit_confidence=(
            float(row.typical_visit_confidence)
            if getattr(row, "typical_visit_confidence", None) is not None
            else None
        ),
        mention_count=int(row.mention_count_30d or 0),
        positive_count=int(row.positive_count_30d or 0),
        negative_count=int(row.negative_count_30d or 0),
        source_count=int(row.source_count or 0),
        quality_score=float(row.quality_score or 0.0),
        recommend_score=float(row.recommend_score or 0.0),
        longitude=float(row.longitude) if row.longitude is not None else None,
        latitude=float(row.latitude) if row.latitude is not None else None,
        adcode=str(row.adcode) if row.adcode else None,
        amap_poi_id=(
            str(row.amap_poi_id)
            if getattr(row, "amap_poi_id", None)
            else None
        ),
        amap_rating=(
            str(row.amap_rating)
            if getattr(row, "amap_rating", None)
            else None
        ),
        amap_avg_price=(
            str(row.amap_avg_price)
            if getattr(row, "amap_avg_price", None)
            else None
        ),
        amap_open_time=(
            str(row.amap_open_time)
            if getattr(row, "amap_open_time", None)
            else None
        ),
        top_reasons=resolve_top_reasons_for_candidate(
            getattr(row, "top_reasons", None),
            getattr(row, "cleaned_evidence", None),
        ),
        warnings=[
            item for item in _json_list(row.warnings) if isinstance(item, dict)
        ],
        must_include=must_include,
    )


def balance_candidate_types(
    candidates: list[CandidatePlace],
    limit: int,
    preferences: list[str],
) -> list[CandidatePlace]:
    """Balance food and activity candidates before writer truncation."""
    if not candidates or limit <= 0:
        return []

    is_food_focused = any(
        keyword in pref.lower()
        for pref in preferences
        for keyword in ("美食", "吃", "food", "火锅", "小吃", "餐厅")
    )
    food_places = [candidate for candidate in candidates if is_food_place(candidate)]
    activities = [candidate for candidate in candidates if not is_food_place(candidate)]
    food_ratio = 0.40 if is_food_focused else 0.27

    food_quota = min(len(food_places), max(0, round(limit * food_ratio)))
    activity_quota = min(len(activities), limit - food_quota)
    remaining = limit - food_quota - activity_quota
    if remaining > 0:
        extra_food = min(len(food_places) - food_quota, remaining)
        food_quota += extra_food
        remaining -= extra_food
    if remaining > 0:
        activity_quota += min(len(activities) - activity_quota, remaining)

    selected = food_places[:food_quota] + activities[:activity_quota]
    return sorted(
        selected,
        key=lambda candidate: (
            -candidate.effective_score,
            -candidate.recommend_score,
            -candidate.base_priority,
            candidate.place_id,
        ),
    )


async def query(
    trip_request: TripRequest,
    limit: int = 30,
    *,
    recent_place_id_sets: list[set[int]] | None = None,
    must_include_place_ids: list[int] | None = None,
) -> RetrievalResult:
    """Retrieve and rank the canonical candidate pool."""
    city = trip_request.to_city.strip()
    if not city:
        logger.warning("Data Retrieval skipped because destination city is empty")
        return RetrievalResult(
            city="",
            candidates=[],
            evidence_summary="Destination city is empty; no candidates queried.",
        )

    async with get_session_factory()() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    c.place_id,
                    c.canonical_name AS name,
                    c.place_type,
                    c.district,
                    c.latitude,
                    c.longitude,
                    c.adcode,
                    c.base_priority,
                    c.typical_visit_minutes,
                    c.typical_visit_source,
                    c.typical_visit_confidence,
                    c.category_tags,
                    c.amap_poi_id,
                    c.amap_rating,
                    c.amap_avg_price,
                    c.amap_open_time,
                    COALESCE(s.mention_count_30d, 0) AS mention_count_30d,
                    COALESCE(s.positive_count_30d, 0) AS positive_count_30d,
                    COALESCE(s.negative_count_30d, 0) AS negative_count_30d,
                    COALESCE(s.source_count, 0) AS source_count,
                    COALESCE(s.quality_score, 0) AS quality_score,
                    COALESCE(s.recommend_score, 0) AS recommend_score,
                """
                + _TOP_REASONS_SELECT_SQL
                + """,
                    COALESCE(s.warnings, '[]'::jsonb) AS warnings
                FROM travel_canonical_place AS c
                LEFT JOIN travel_place_summary AS s
                  ON s.canonical_place_id = c.place_id
                WHERE c.city = :city
                  AND c.trust_level = 'trusted'
                  AND c.review_status IN ('reviewed', 'auto_accepted')
                  AND c.is_active = TRUE
                  AND c.contextual_only = FALSE
                  AND c.place_type != 'hotel'
                  AND c.geo_status IN ('resolved', 'coordinate_only')
                  AND c.latitude IS NOT NULL
                  AND c.longitude IS NOT NULL
                  AND c.canonical_name <> c.city
                ORDER BY c.base_priority DESC, s.recommend_score DESC NULLS LAST, c.place_id ASC
                LIMIT :pool_limit
                """
            ),
            {
                "city": city,
                "pool_limit": MAX_QUALIFIED_POOL_SIZE,
            },
        )
        rows = result.fetchall()
        pinned_ids = list(dict.fromkeys(
            int(place_id)
            for place_id in (must_include_place_ids or [])
            if int(place_id or 0) > 0
        ))
        pinned_id_set = set(pinned_ids)
        fetched_pinned_rows = []
        existing_ids = {
            int(row.place_id)
            for row in rows
            if getattr(row, "place_id", None) is not None
        }
        for place_id in pinned_ids:
            if place_id in existing_ids:
                continue
            pinned_result = await session.execute(
                text(
                    """
                    SELECT
                        c.place_id,
                        c.canonical_name AS name,
                        c.place_type,
                        c.district,
                        c.latitude,
                        c.longitude,
                        c.adcode,
                        c.base_priority,
                        c.typical_visit_minutes,
                        c.typical_visit_source,
                        c.typical_visit_confidence,
                        c.category_tags,
                        c.amap_poi_id,
                        c.amap_rating,
                        c.amap_avg_price,
                        c.amap_open_time,
                        COALESCE(s.mention_count_30d, 0) AS mention_count_30d,
                        COALESCE(s.positive_count_30d, 0) AS positive_count_30d,
                        COALESCE(s.negative_count_30d, 0) AS negative_count_30d,
                        COALESCE(s.source_count, 0) AS source_count,
                        COALESCE(s.quality_score, 0) AS quality_score,
                        COALESCE(s.recommend_score, 0) AS recommend_score,
                    """
                    + _TOP_REASONS_SELECT_SQL
                    + """,
                        COALESCE(s.warnings, '[]'::jsonb) AS warnings
                    FROM travel_canonical_place AS c
                    LEFT JOIN travel_place_summary AS s
                      ON s.canonical_place_id = c.place_id
                    WHERE c.city = :city
                      AND c.trust_level = 'trusted'
                      AND c.review_status IN ('reviewed', 'auto_accepted')
                      AND c.is_active = TRUE
                      AND c.contextual_only = FALSE
                      AND c.geo_status IN ('resolved', 'coordinate_only')
                      AND c.latitude IS NOT NULL
                      AND c.longitude IS NOT NULL
                      AND c.canonical_name <> c.city
                      AND c.place_id = :place_id
                    LIMIT 1
                    """
                ),
                {
                    "city": city,
                    "place_id": place_id,
                },
            )
            fetched_pinned_rows.extend(pinned_result.fetchall())

    seen_names: set[str] = set()
    candidates: list[CandidatePlace] = []
    for row in rows:
        name = str(row.name)
        if name in seen_names:
            continue
        seen_names.add(name)
        candidate = _candidate_from_row(row, must_include=int(row.place_id) in pinned_id_set)
        if _admissible_canonical_candidate(candidate, city=city):
            candidates.append(candidate)
    by_place_id = {candidate.place_id: candidate for candidate in candidates}
    for row in fetched_pinned_rows:
        candidate = _candidate_from_row(row, must_include=True)
        if (
            candidate.place_id not in by_place_id
            and _admissible_canonical_candidate(candidate, city=city)
        ):
            by_place_id[candidate.place_id] = candidate
            candidates.append(candidate)
    for candidate in candidates:
        if candidate.place_id in pinned_id_set:
            candidate.must_include = True

    candidates = rank_candidates(
        candidates,
        recent_place_id_sets=recent_place_id_sets,
        preferred_place_types=preferred_place_types(trip_request.preferences),
    )

    avoid_keywords = [keyword.lower() for keyword in trip_request.avoid]

    # Expand semantic avoid keywords (e.g. "网红" → concrete POI names)
    expanded_avoid_names: set[str] = set()
    for keyword in avoid_keywords:
        if keyword in _SEMANTIC_AVOID_EXPANSIONS:
            expanded_avoid_names.update(
                name.lower() for name in _SEMANTIC_AVOID_EXPANSIONS[keyword]
            )

    if avoid_keywords or expanded_avoid_names:
        candidates = [
            candidate for candidate in candidates
            if candidate.must_include
            or not (
                any(keyword in candidate.name.lower() for keyword in avoid_keywords)
                or any(name in candidate.name.lower() for name in expanded_avoid_names)
            )
        ]

    qualified_candidate_count = len(candidates)
    route_planning_candidates = list(candidates[:MAX_ROUTE_PLANNING_CANDIDATES])
    bounded_limit = max(0, min(limit, MAX_QUALIFIED_POOL_SIZE))
    pinned_candidates = [candidate for candidate in candidates if candidate.must_include]
    remainder = [candidate for candidate in candidates if not candidate.must_include]
    balanced_remainder = balance_candidate_types(
        remainder,
        max(0, bounded_limit - len(pinned_candidates)),
        trip_request.preferences,
    )
    selected_ids: set[int] = set()
    selected = []
    for candidate in [*pinned_candidates, *balanced_remainder]:
        if candidate.place_id in selected_ids:
            continue
        selected_ids.add(candidate.place_id)
        selected.append(candidate)
    rank_order = {candidate.place_id: index for index, candidate in enumerate(candidates)}
    candidates = sorted(
        selected,
        key=lambda candidate: rank_order.get(candidate.place_id, len(rank_order)),
    )
    evidence_lines = []
    for candidate in candidates[:15]:
        reasons_text = "; ".join(
            str(reason.get("reason", ""))
            for reason in candidate.top_reasons[:2]
            if isinstance(reason, dict) and reason.get("reason")
        )
        warnings_text = "; ".join(
            str(warning.get("reason", ""))
            for warning in candidate.warnings[:1]
            if isinstance(warning, dict) and warning.get("reason")
        )
        line = (
            f"- {candidate.name}({candidate.place_type}): "
            f"base={candidate.base_priority}, evidence={candidate.recommend_score:.1f}, "
            f"effective={candidate.effective_score:.1f}, mentions={candidate.mention_count}"
        )
        if reasons_text:
            line += f" | reason: {reasons_text}"
        if warnings_text:
            line += f" | warning: {warnings_text}"
        evidence_lines.append(line)

    logger.info(
        "Retrieved %d/%d canonical candidates for city=%s",
        len(candidates),
        qualified_candidate_count,
        city,
    )
    return RetrievalResult(
        city=city,
        candidates=candidates,
        route_planning_candidates=route_planning_candidates,
        evidence_summary="\n".join(evidence_lines),
        candidate_groups=[],
        qualified_candidate_count=qualified_candidate_count,
        in_response_candidate_overlap=None,
        diversity_gap=False,
    )
