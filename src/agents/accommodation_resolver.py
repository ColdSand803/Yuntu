"""Deterministic accommodation-anchor resolution for v0.9.1."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from src.agents import route_planning
from src.agents.schema import (
    AccommodationSuggestion,
    CandidatePlace,
    RetrievalResult,
    TripRequest,
)
from src.pipeline.poi_resolve import (
    AmapClient,
    AmapDefinitiveNotFound,
    AmapTransientError,
    GeocodeResult,
)

logger = logging.getLogger(__name__)

COORDINATE_ONLY_ACCOMMODATION_NAME = "用户指定住宿位置"
AUTO_RECOMMENDATION_REASON = "步行可达多数主景点"
_MATCHABLE_PLACE_TYPES = frozenset({
    "accommodation_area",
    "business_area",
    "hotel",
})
_PLACE_TYPE_PRIORITY = {
    "accommodation_area": 3,
    "business_area": 2,
    "hotel": 1,
}

PLACE_BY_ID_SQL = """
    SELECT
        place_id, canonical_name, city, latitude, longitude, place_type,
        base_priority
    FROM travel_canonical_place
    WHERE place_id = :place_id
      AND city = :city
      AND is_active = TRUE
      AND latitude IS NOT NULL
      AND longitude IS NOT NULL
    LIMIT 1
"""

NAME_CANDIDATES_SQL = """
    SELECT
        place_id, canonical_name, city, latitude, longitude, place_type,
        base_priority
    FROM travel_canonical_place
    WHERE city = :city
      AND is_active = TRUE
      AND latitude IS NOT NULL
      AND longitude IS NOT NULL
      AND place_type IN (
          'accommodation_area',
          'business_area',
          'hotel'
      )
    ORDER BY base_priority DESC, place_id ASC
"""

CANDIDATE_AREAS_SQL = """
    SELECT
        place_id, canonical_name, city, latitude, longitude, place_type,
        base_priority
    FROM travel_canonical_place
    WHERE city = :city
      AND place_type = 'accommodation_area'
      AND contextual_only = TRUE
      AND is_active = TRUE
      AND latitude IS NOT NULL
      AND longitude IS NOT NULL
    ORDER BY base_priority DESC, place_id ASC
"""


@dataclass(frozen=True)
class AccommodationPlace:
    """Small canonical-place projection used by the resolver."""

    place_id: int
    canonical_name: str
    city: str
    latitude: float
    longitude: float
    place_type: str
    base_priority: int = 0


def _place_from_row(row: Any) -> AccommodationPlace:
    mapping = row if isinstance(row, Mapping) else row._mapping
    return AccommodationPlace(
        place_id=int(mapping["place_id"]),
        canonical_name=str(mapping["canonical_name"]),
        city=str(mapping["city"]),
        latitude=float(mapping["latitude"]),
        longitude=float(mapping["longitude"]),
        place_type=str(mapping["place_type"]),
        base_priority=int(mapping.get("base_priority") or 0),
    )


async def _fetch_place_by_id(
    session: Any,
    *,
    place_id: int,
    city: str,
) -> AccommodationPlace | None:
    result = await session.execute(
        text(PLACE_BY_ID_SQL),
        {"place_id": place_id, "city": city},
    )
    row = result.mappings().first()
    return _place_from_row(row) if row is not None else None


async def _fetch_name_candidates(
    session: Any,
    *,
    city: str,
) -> list[AccommodationPlace]:
    result = await session.execute(text(NAME_CANDIDATES_SQL), {"city": city})
    return [_place_from_row(row) for row in result.mappings().all()]


async def _fetch_candidate_areas(
    session: Any,
    *,
    city: str,
) -> list[AccommodationPlace]:
    result = await session.execute(text(CANDIDATE_AREAS_SQL), {"city": city})
    return [_place_from_row(row) for row in result.mappings().all()]


def _compact_name(value: str) -> str:
    return "".join(value.split())


def _name_match_key(value: str) -> str:
    """Normalize only frozen accommodation-area suffixes for fuzzy matching."""

    key = _compact_name(value)
    for suffix in ("附近", "周边"):
        if key.endswith(suffix):
            key = key[:-len(suffix)]
            break
    for suffix in ("(商圈)", "（商圈）", "商圈"):
        if key.endswith(suffix):
            key = key[:-len(suffix)]
            break
    return key


def _ranked_name_match(
    input_name: str,
    candidates: list[AccommodationPlace],
) -> AccommodationPlace | None:
    """Apply the frozen exact-then-containment matching contract."""

    original = input_name.strip()
    compact_input = _compact_name(original)
    if not compact_input:
        return None
    input_match_key = _name_match_key(original)

    eligible = [
        candidate
        for candidate in candidates
        if candidate.place_type in _MATCHABLE_PLACE_TYPES
    ]
    exact = [
        candidate
        for candidate in eligible
        if (
            candidate.canonical_name == original
            or _compact_name(candidate.canonical_name) == compact_input
        )
    ]
    if exact:
        return _pick_name_match(original, exact, log_ambiguity=False)

    contained = [
        candidate
        for candidate in eligible
        if (
            input_match_key
            and (candidate_key := _name_match_key(candidate.canonical_name))
            and (
                input_match_key in candidate_key
                or candidate_key in input_match_key
            )
        )
    ]
    if not contained:
        return None
    return _pick_name_match(original, contained, log_ambiguity=True)


def _pick_name_match(
    input_name: str,
    candidates: list[AccommodationPlace],
    *,
    log_ambiguity: bool,
) -> AccommodationPlace:
    best_type_priority = max(
        _PLACE_TYPE_PRIORITY[candidate.place_type]
        for candidate in candidates
    )
    same_priority = [
        candidate
        for candidate in candidates
        if _PLACE_TYPE_PRIORITY[candidate.place_type] == best_type_priority
    ]
    ranked = sorted(
        same_priority,
        key=lambda candidate: (-candidate.base_priority, candidate.place_id),
    )
    picked = ranked[0]
    if log_ambiguity and len(ranked) > 1:
        logger.info(
            "accommodation name match ambiguous input=%s picked=%s candidates=%s",
            input_name,
            picked.canonical_name,
            [candidate.canonical_name for candidate in ranked],
        )
    return picked


async def _geocode_name(name: str, city: str) -> GeocodeResult | None:
    client = AmapClient()
    try:
        return await client.geocode(city=city, address=name)
    except (AmapDefinitiveNotFound, AmapTransientError) as exc:
        logger.info(
            "accommodation geocode failed city=%s name=%s error=%s",
            city,
            name,
            type(exc).__name__,
        )
        return None
    finally:
        await client.close()


def _suggestion_from_place(
    place: AccommodationPlace,
    *,
    source: str,
    reason: str = "",
    user_input_unmatched: str = "",
) -> AccommodationSuggestion:
    return AccommodationSuggestion(
        name=place.canonical_name,
        latitude=place.latitude,
        longitude=place.longitude,
        source=source,
        reason=reason,
        user_input_unmatched=user_input_unmatched,
    )


def _urban_candidate_pool(
    trip_request: TripRequest,
    retrieval: RetrievalResult,
) -> list[CandidatePlace]:
    pool = (
        retrieval.route_planning_candidates
        or retrieval.candidates
    )
    urban, _ = route_planning._split_remote_day_trips(
        list(pool),
        days=trip_request.days,
        remote_context=" ".join([
            trip_request.to_city,
            *trip_request.preferences,
            trip_request.notes,
        ]),
    )
    return [
        place
        for place in urban
        if place.latitude is not None and place.longitude is not None
    ]


def _proximity_scoring(
    trip_request: TripRequest,
    retrieval: RetrievalResult,
    candidate_areas: list[AccommodationPlace],
) -> AccommodationPlace | None:
    """Pick the area with the shortest mean distance to top urban POIs."""

    if not candidate_areas:
        return None
    pool = _urban_candidate_pool(trip_request, retrieval)
    top_pois = sorted(
        pool,
        key=lambda place: place.effective_score,
        reverse=True,
    )[:20]
    if not top_pois:
        return None

    def mean_distance(area: AccommodationPlace) -> float:
        distances = [
            route_planning._haversine_coords(
                area.latitude,
                area.longitude,
                float(place.latitude),
                float(place.longitude),
            )
            for place in top_pois
        ]
        return sum(distances) / len(distances)

    return min(
        candidate_areas,
        key=lambda area: (
            mean_distance(area),
            -area.base_priority,
            area.place_id,
        ),
    )


async def resolve_accommodation(
    trip_request: TripRequest,
    retrieval: RetrievalResult,
    session: Any,
) -> AccommodationSuggestion | None:
    """Resolve a user anchor or recommend the closest accommodation area."""

    request = trip_request.accommodation
    city = trip_request.to_city.strip()
    unmatched = ""

    if request is not None and request.place_id is not None:
        place = await _fetch_place_by_id(
            session,
            place_id=request.place_id,
            city=city,
        )
        if place is not None:
            return _suggestion_from_place(place, source="user_specified")
        logger.info(
            "accommodation place_id unmatched city=%s place_id=%s",
            city,
            request.place_id,
        )
    elif (
        request is not None
        and request.latitude is not None
        and request.longitude is not None
    ):
        name = (request.name or "").strip() or COORDINATE_ONLY_ACCOMMODATION_NAME
        return AccommodationSuggestion(
            name=name,
            latitude=request.latitude,
            longitude=request.longitude,
            source="user_specified",
        )
    elif request is not None and (request.name or "").strip():
        input_name = str(request.name).strip()
        candidates = await _fetch_name_candidates(session, city=city)
        matched = _ranked_name_match(input_name, candidates)
        if matched is not None:
            return _suggestion_from_place(matched, source="user_specified")

        geocoded = await _geocode_name(input_name, city)
        if geocoded is not None:
            return AccommodationSuggestion(
                name=input_name,
                latitude=geocoded.latitude,
                longitude=geocoded.longitude,
                source="user_specified",
            )
        unmatched = input_name

    candidate_areas = await _fetch_candidate_areas(session, city=city)
    best_area = _proximity_scoring(
        trip_request,
        retrieval,
        candidate_areas,
    )
    if best_area is None:
        return None
    return _suggestion_from_place(
        best_area,
        source="auto_recommended",
        reason=AUTO_RECOMMENDATION_REASON,
        user_input_unmatched=unmatched,
    )
