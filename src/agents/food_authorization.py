"""Evidence authorization for runtime-only food attachments."""

from __future__ import annotations

import json

from sqlalchemy import text

from src.agents.evidence_strength import build_structured_evidence_payload
from src.agents.food_resolver import (
    FoodAttachment,
    FoodAttachmentAuthorization,
    _haversine_meters,
)
from src.agents.schema import CandidatePlace, RetrievalResult


SUMMARY_SQL = """
SELECT COALESCE(top_reasons, '[]'::jsonb) AS top_reasons
FROM travel_place_summary
WHERE canonical_place_id = :food_place_id
"""

MEAL_SLOT_LABELS = {
    "lunch": "午餐",
    "dinner": "晚餐",
    "coffee": "茶歇",
    "snack": "小吃",
    "late_night_optional": "夜宵",
}


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _walk_minutes(
    food_lat: float | None,
    food_lng: float | None,
    anchor_lat: float | None,
    anchor_lng: float | None,
) -> int | None:
    """Estimate walking minutes from routed distance and 80m/min speed."""

    if None in (food_lat, food_lng, anchor_lat, anchor_lng):
        return None
    straight_distance = _haversine_meters(
        float(food_lat),
        float(food_lng),
        float(anchor_lat),
        float(anchor_lng),
    )
    return max(1, round(straight_distance * 1.5 / 80.0))


def _meal_type(place_type: str) -> str:
    return {
        "restaurant": "餐厅",
        "food": "餐厅",
        "snack": "小吃",
        "cafe": "咖啡店",
        "dessert": "甜品店",
        "market": "美食街",
    }.get(place_type.strip().lower(), "餐馆")


def _none_tier_text(meal_slot: str, meal_type: str) -> str:
    meal_slot_label = MEAL_SLOT_LABELS.get(meal_slot, "用餐")
    return f"{meal_slot_label}这一带可以随缘找家{meal_type}"


async def build_food_attachment_authorization(
    food_attachment: FoodAttachment | None,
    plan_index: int,
    day: int,
    anchor_place_id: int,
    meal_slot: str,
    session,
) -> FoodAttachmentAuthorization:
    """Classify evidence from the selected food place, never from the anchor."""

    if food_attachment is None:
        meal_type = _meal_type("")
        return FoodAttachmentAuthorization(
            plan_index=plan_index,
            day=day,
            anchor_place_id=anchor_place_id,
            meal_slot=meal_slot,
            food_place_id=-1,
            evidence_tier="none",
            food_name=None,
            amap_rating=None,
            amap_avg_price=None,
            walk_minutes=None,
            meal_type=meal_type,
            none_tier_text=_none_tier_text(meal_slot, meal_type),
            direct_facts=[],
            weak_experience=[],
        )

    result = await session.execute(
        text(SUMMARY_SQL),
        {"food_place_id": food_attachment.place_id},
    )
    top_reasons = _json_list(result.scalar_one_or_none())
    candidate = CandidatePlace(
        place_id=food_attachment.place_id,
        canonical_place_id=food_attachment.place_id,
        name=food_attachment.amap_name,
        place_type=food_attachment.place_type,
        latitude=food_attachment.latitude,
        longitude=food_attachment.longitude,
        amap_poi_id=food_attachment.amap_poi_id,
        amap_rating=food_attachment.amap_rating,
        amap_avg_price=food_attachment.amap_avg_price,
        top_reasons=[
            item for item in top_reasons if isinstance(item, dict)
        ],
    )
    payload = build_structured_evidence_payload(
        RetrievalResult(city="", candidates=[candidate])
    )
    place_payload = next(
        (
            place
            for place in payload.places
            if place.place_id == food_attachment.place_id
        ),
        None,
    )
    direct_facts = (
        list(place_payload.direct_facts)
        if place_payload is not None
        else []
    )
    weak_experience = (
        list(place_payload.weak_experience)
        if place_payload is not None
        else []
    )
    evidence_tier = (
        "full"
        if direct_facts or weak_experience
        else "structural"
    )
    return FoodAttachmentAuthorization(
        plan_index=plan_index,
        day=day,
        anchor_place_id=anchor_place_id,
        meal_slot=meal_slot,
        food_place_id=food_attachment.place_id,
        evidence_tier=evidence_tier,
        food_name=food_attachment.amap_name,
        amap_rating=food_attachment.amap_rating,
        amap_avg_price=food_attachment.amap_avg_price,
        walk_minutes=None,
        meal_type=_meal_type(food_attachment.place_type),
        none_tier_text=None,
        direct_facts=direct_facts,
        weak_experience=weak_experience,
    )
