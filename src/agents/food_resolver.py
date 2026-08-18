"""Deterministic nearby-food resolution contracts for v0.9.0."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from src.agents.schema import CompositionBlueprint


FOOD_PLACE_TYPES = (
    "restaurant",
    "food",
    "snack",
    "cafe",
    "dessert",
    "market",
)
FOOD_RADIUS_METERS = 500.0
FOOD_BOUNDING_DELTA_DEGREES = 0.005


@dataclass(frozen=True)
class FoodAttachment:
    """Runtime-only nearby food identity selected after route locking."""

    place_id: int
    amap_name: str
    amap_poi_id: str | None
    amap_rating: str | None
    amap_avg_price: str | None
    latitude: float
    longitude: float
    place_type: str
    contextual_only: bool
    has_summary: bool
    source_observed_at: datetime | None = None


@dataclass(frozen=True)
class FoodAttachmentAuthorization:
    """Runtime-only authorization for one complete food attachment key."""

    plan_index: int
    day: int
    anchor_place_id: int
    meal_slot: str
    food_place_id: int
    evidence_tier: str
    food_name: str | None
    amap_rating: str | None
    amap_avg_price: str | None
    walk_minutes: int | None
    meal_type: str
    none_tier_text: str | None
    direct_facts: list[str] = field(default_factory=list)
    weak_experience: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple[int, int, int, str, int]:
        return (
            self.plan_index,
            self.day,
            self.anchor_place_id,
            self.meal_slot,
            self.food_place_id,
        )


@dataclass
class FoodEnrichmentResult:
    """Enriched blueprints plus the non-persistent authorization registry."""

    blueprints: list[CompositionBlueprint]
    attachment_auth_map: dict[
        tuple[int, int, int, str, int],
        FoodAttachmentAuthorization,
    ] = field(default_factory=dict)
    meal_attachment_map: dict[
        tuple[int, int, str],
        FoodAttachment,
    ] = field(default_factory=dict)


FOOD_RESOLVER_SQL = """
SELECT
    c.place_id,
    c.canonical_name AS amap_name,
    c.amap_poi_id,
    c.amap_rating,
    c.amap_avg_price,
    c.latitude,
    c.longitude,
    c.place_type,
    c.contextual_only,
    c.base_priority,
    c.amap_data_captured_at AS source_observed_at,
    COALESCE(s.top_reasons, '[]'::jsonb) AS top_reasons
FROM travel_canonical_place AS c
LEFT JOIN travel_place_summary AS s
  ON s.canonical_place_id = c.place_id
WHERE c.city = :city
  AND c.place_type IN ('restaurant', 'food', 'snack', 'cafe', 'dessert', 'market')
  AND c.trust_level = 'trusted'
  AND c.review_status IN ('reviewed', 'auto_accepted')
  AND c.is_active = TRUE
  AND c.geo_status IN ('resolved', 'coordinate_only')
  AND c.latitude IS NOT NULL
  AND c.longitude IS NOT NULL
  AND c.place_id <> :anchor_place_id
  AND c.latitude BETWEEN :lat_min AND :lat_max
  AND c.longitude BETWEEN :lng_min AND :lng_max
  AND (
      c.contextual_only = TRUE
      OR (
          c.contextual_only = FALSE
          AND c.place_type IN (
              'restaurant', 'food', 'snack', 'cafe', 'dessert', 'market'
          )
      )
  )
  AND :food_enabled = TRUE
ORDER BY
    c.base_priority DESC,
    c.amap_rating DESC NULLS LAST,
    c.place_id ASC
"""


def _haversine_meters(
    lat_a: float,
    lng_a: float,
    lat_b: float,
    lng_b: float,
) -> float:
    radius_meters = 6_371_000.0
    lat_a_rad = math.radians(lat_a)
    lat_b_rad = math.radians(lat_b)
    delta_lat = math.radians(lat_b - lat_a)
    delta_lng = math.radians(lng_b - lng_a)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a_rad)
        * math.cos(lat_b_rad)
        * math.sin(delta_lng / 2) ** 2
    )
    return radius_meters * 2 * math.atan2(
        math.sqrt(haversine),
        math.sqrt(1 - haversine),
    )


def _has_summary(top_reasons) -> bool:
    if isinstance(top_reasons, list):
        return bool(top_reasons)
    if isinstance(top_reasons, str):
        try:
            parsed = json.loads(top_reasons)
        except json.JSONDecodeError:
            return False
        return isinstance(parsed, list) and bool(parsed)
    return False


async def resolve_food_attachment(
    anchor_place_id: int,
    lat: float | None,
    lng: float | None,
    city: str,
    session,
    settings,
) -> FoodAttachment | None:
    """Select the highest-ranked food POI within 500m of the locked anchor."""

    food_enabled = bool(
        getattr(settings, "food_recommendation_enabled", False)
    )
    if not food_enabled or lat is None or lng is None or not city.strip():
        return None

    result = await session.execute(
        text(FOOD_RESOLVER_SQL),
        {
            "city": city.strip(),
            "anchor_place_id": int(anchor_place_id),
            "lat_min": float(lat) - FOOD_BOUNDING_DELTA_DEGREES,
            "lat_max": float(lat) + FOOD_BOUNDING_DELTA_DEGREES,
            "lng_min": float(lng) - FOOD_BOUNDING_DELTA_DEGREES,
            "lng_max": float(lng) + FOOD_BOUNDING_DELTA_DEGREES,
            "food_enabled": True,
        },
    )
    rows = result.mappings().all()
    candidates: list[tuple[int, float, float, int, FoodAttachment]] = []
    for row in rows:
        place_id = int(row["place_id"])
        if place_id == int(anchor_place_id):
            continue
        food_lat = float(row["latitude"])
        food_lng = float(row["longitude"])
        distance = _haversine_meters(
            float(lat),
            float(lng),
            food_lat,
            food_lng,
        )
        if distance > FOOD_RADIUS_METERS:
            continue
        raw_rating = row["amap_rating"]
        rating_sort = (
            -float(raw_rating)
            if raw_rating is not None
            else float("inf")
        )
        attachment = FoodAttachment(
            place_id=place_id,
            amap_name=str(row["amap_name"]),
            amap_poi_id=(
                str(row["amap_poi_id"])
                if row["amap_poi_id"]
                else None
            ),
            amap_rating=(
                str(raw_rating)
                if raw_rating is not None
                else None
            ),
            amap_avg_price=(
                str(row["amap_avg_price"])
                if row["amap_avg_price"] is not None
                else None
            ),
            latitude=food_lat,
            longitude=food_lng,
            place_type=str(row["place_type"]),
            contextual_only=bool(row["contextual_only"]),
            has_summary=_has_summary(row["top_reasons"]),
            source_observed_at=row.get("source_observed_at"),
        )
        candidates.append(
            (
                -int(row["base_priority"] or 0),
                rating_sort,
                distance,
                place_id,
                attachment,
            )
        )

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[:4])
    return candidates[0][4]
