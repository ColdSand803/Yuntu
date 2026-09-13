"""Read-only POI catalog query core.

HTTP A/B routes are registered on ``trip_places.internal_router`` only.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import text

from src.agents.diversity import is_specific_place_name
from src.agents.route_feasibility import valid_coordinate
from src.pipeline.db import get_session_factory

CATALOG_EXCLUDED_PLACE_TYPES = (
    "restaurant",
    "hotel",
    "food",
    "cafe",
    "snack",
    "dessert",
)
DISPLAY_TRUST_LEVEL = "trusted"
DISPLAY_REVIEW_STATUSES = frozenset({"reviewed", "auto_accepted"})
DISPLAY_GEO_STATUSES = frozenset({"resolved", "coordinate_only"})

CATALOG_SCAN_BATCH_SIZE = 64
MIN_CITY_LENGTH = 1
MAX_CITY_LENGTH = 64
MAX_QUERY_LENGTH = 100
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 50
MIN_SELECTION_IDS = 1
MAX_SELECTION_IDS = 5
MIN_PLACE_NAME_LENGTH = 1
MAX_PLACE_NAME_LENGTH = 100

_CATALOG_COLUMNS_SQL = """
                    c.place_id,
                    c.canonical_name AS name,
                    c.city,
                    c.district,
                    c.longitude,
                    c.latitude,
                    c.place_type,
                    c.trust_level,
                    c.review_status,
                    c.is_active,
                    c.geo_status,
                    c.contextual_only,
                    c.base_priority
"""

_CATALOG_ELIGIBILITY_SQL = """
                  AND c.trust_level = 'trusted'
                  AND c.review_status IN ('reviewed', 'auto_accepted')
                  AND c.is_active = TRUE
                  AND c.contextual_only = FALSE
                  AND c.base_priority > 0
                  AND c.geo_status IN ('resolved', 'coordinate_only')
                  AND c.latitude IS NOT NULL
                  AND c.longitude IS NOT NULL
                  AND c.latitude BETWEEN -90 AND 90
                  AND c.longitude BETWEEN -180 AND 180
                  AND c.canonical_name <> c.city
                  AND NOT (c.place_type = ANY(CAST(:excluded_types AS text[])))
"""

_CATALOG_SCAN_SQL = text(
    f"""
                SELECT
{_CATALOG_COLUMNS_SQL}
                FROM travel_canonical_place AS c
                WHERE c.city = :city
                  AND c.place_id > :after_id
{_CATALOG_ELIGIBILITY_SQL}
                ORDER BY c.place_id ASC
                LIMIT :batch_limit
            """
)

_CATALOG_SCAN_SEARCH_SQL = text(
    f"""
                SELECT
{_CATALOG_COLUMNS_SQL}
                FROM travel_canonical_place AS c
                WHERE c.city = :city
                  AND c.place_id > :after_id
{_CATALOG_ELIGIBILITY_SQL}
                  AND LOWER(c.canonical_name) LIKE LOWER(:name_pattern) ESCAPE '\\'
                ORDER BY c.place_id ASC
                LIMIT :batch_limit
            """
)

_CATALOG_SELECTION_SQL = text(
    f"""
                SELECT
{_CATALOG_COLUMNS_SQL}
                FROM travel_canonical_place AS c
                WHERE c.place_id = ANY(CAST(:place_ids AS bigint[]))
            """
)


class PoiCatalogValidationError(ValueError):
    """Invalid catalog or selection input. Phase 1 maps this to HTTP 422."""


class SelectablePoi(BaseModel):
    place_id: int
    name: str
    place_type: str
    district: str | None = None


class PoiCatalogResponse(BaseModel):
    ok: Literal[True] = True
    city: str
    places: list[SelectablePoi] = Field(default_factory=list)
    next_after_id: int | None = None


class PoiSelectionAvailableItem(BaseModel):
    place_id: int
    status: Literal["available"] = "available"
    place: SelectablePoi


class PoiSelectionUnavailableItem(BaseModel):
    place_id: int
    status: Literal["unavailable"] = "unavailable"


class PoiSelectionResponse(BaseModel):
    ok: Literal[True] = True
    city: str
    items: list[PoiSelectionAvailableItem | PoiSelectionUnavailableItem] = Field(
        default_factory=list
    )


def _escape_like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _require_trimmed_city(city: str) -> str:
    if not isinstance(city, str):
        raise PoiCatalogValidationError("city must be 1..64 chars")
    requested = city.strip()
    if not MIN_CITY_LENGTH <= len(requested) <= MAX_CITY_LENGTH:
        raise PoiCatalogValidationError("city must be 1..64 chars")
    return requested


def normalize_catalog_city(city: str) -> str:
    """Trim and validate the catalog city query parameter."""
    return _require_trimmed_city(city)


def _require_query(q: str | None) -> str:
    if q is None:
        return ""
    if not isinstance(q, str):
        raise PoiCatalogValidationError("q must be 0..100 chars")
    requested = q.strip()
    if len(requested) > MAX_QUERY_LENGTH:
        raise PoiCatalogValidationError("q must be 0..100 chars")
    return requested


def _require_non_negative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PoiCatalogValidationError(f"{field} must be a non-negative integer")
    return value


def _require_page_limit(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not MIN_PAGE_LIMIT <= value <= MAX_PAGE_LIMIT
    ):
        raise PoiCatalogValidationError("limit must be 1..50")
    return value


def _require_place_ids(place_ids: Any) -> list[int]:
    if not isinstance(place_ids, list):
        raise PoiCatalogValidationError("place_ids must contain 1..5 distinct positive integers")
    if not MIN_SELECTION_IDS <= len(place_ids) <= MAX_SELECTION_IDS:
        raise PoiCatalogValidationError("place_ids must contain 1..5 distinct positive integers")
    normalized: list[int] = []
    seen: set[int] = set()
    for value in place_ids:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise PoiCatalogValidationError(
                "place_ids must contain 1..5 distinct positive integers"
            )
        if value in seen:
            raise PoiCatalogValidationError(
                "place_ids must contain 1..5 distinct positive integers"
            )
        seen.add(value)
        normalized.append(value)
    return normalized


def _positive_place_id(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_name(row: Any) -> str:
    raw = getattr(row, "name", None)
    if raw is None:
        raw = getattr(row, "canonical_name", "")
    return str(raw or "").strip()


def _row_city(row: Any) -> str:
    return str(getattr(row, "city", "") or "").strip()


def _row_place_type(row: Any) -> str:
    return str(getattr(row, "place_type", "") or "").strip()


def _row_district(row: Any) -> str | None:
    raw = getattr(row, "district", None)
    if raw is None:
        return None
    district = str(raw).strip()
    return district or None


def _coordinate_within_hotlist_city(row: Any, *, city: str) -> bool:
    from src.api.trip_places import _coordinate_within_hotlist_city as hotlist_guard

    return hotlist_guard(row, city=city)


def _base_priority(row: Any) -> int | None:
    value = getattr(row, "base_priority", None)
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_catalog_eligible(row: Any, *, city: str) -> bool:
    """Intersection of sightseeing display and route-candidate admission."""
    place_id = _positive_place_id(getattr(row, "place_id", None))
    name = _row_name(row)
    row_city = _row_city(row)
    place_type = _row_place_type(row)
    priority = _base_priority(row)
    latitude = _as_float(getattr(row, "latitude", None))
    longitude = _as_float(getattr(row, "longitude", None))
    contextual_only = getattr(row, "contextual_only", None)
    return (
        place_id is not None
        and MIN_PLACE_NAME_LENGTH <= len(name) <= MAX_PLACE_NAME_LENGTH
        and name != city
        and row_city == city
        and str(getattr(row, "trust_level", "") or "") == DISPLAY_TRUST_LEVEL
        and str(getattr(row, "review_status", "") or "") in DISPLAY_REVIEW_STATUSES
        and bool(getattr(row, "is_active", False))
        and str(getattr(row, "geo_status", "") or "") in DISPLAY_GEO_STATUSES
        and contextual_only is False
        and priority is not None
        and priority > 0
        and valid_coordinate(latitude, longitude)
        and _coordinate_within_hotlist_city(row, city=city)
        and place_type not in CATALOG_EXCLUDED_PLACE_TYPES
        and is_specific_place_name(name, city=city)
    )


def _project_selectable_poi(row: Any) -> SelectablePoi:
    return SelectablePoi(
        place_id=int(row.place_id),
        name=_row_name(row),
        place_type=_row_place_type(row),
        district=_row_district(row),
    )


def _scan_params(
    *,
    city: str,
    after_id: int,
    batch_limit: int,
    name_pattern: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "city": city,
        "after_id": after_id,
        "batch_limit": batch_limit,
        "excluded_types": list(CATALOG_EXCLUDED_PLACE_TYPES),
    }
    if name_pattern is not None:
        params["name_pattern"] = name_pattern
    return params


async def query_poi_catalog(
    *,
    city: str,
    q: str | None = "",
    after_id: int = 0,
    limit: int = 20,
) -> PoiCatalogResponse:
    canonical_city = _require_trimmed_city(city)
    query = _require_query(q)
    cursor = _require_non_negative_int(after_id, field="after_id")
    page_limit = _require_page_limit(limit)
    needed = page_limit + 1
    batch_limit = max(needed, CATALOG_SCAN_BATCH_SIZE)
    name_pattern = f"%{_escape_like_literal(query)}%" if query else None
    statement = _CATALOG_SCAN_SEARCH_SQL if name_pattern else _CATALOG_SCAN_SQL

    collected: list[SelectablePoi] = []
    async with get_session_factory()() as session:
        while len(collected) < needed:
            result = await session.execute(
                statement,
                _scan_params(
                    city=canonical_city,
                    after_id=cursor,
                    batch_limit=batch_limit,
                    name_pattern=name_pattern,
                ),
            )
            rows = list(result.fetchall())
            if not rows:
                break
            cursor = int(rows[-1].place_id)
            for row in rows:
                if is_catalog_eligible(row, city=canonical_city):
                    collected.append(_project_selectable_poi(row))
                    if len(collected) >= needed:
                        break
            if len(rows) < batch_limit:
                break

    page = collected[:page_limit]
    has_more = len(collected) > page_limit
    return PoiCatalogResponse(
        city=canonical_city,
        places=page,
        next_after_id=page[-1].place_id if has_more and page else None,
    )


async def query_poi_selection(
    *,
    city: str,
    place_ids: list[int],
) -> PoiSelectionResponse:
    canonical_city = _require_trimmed_city(city)
    requested_ids = _require_place_ids(place_ids)
    async with get_session_factory()() as session:
        result = await session.execute(
            _CATALOG_SELECTION_SQL,
            {"place_ids": requested_ids},
        )
        rows = list(result.fetchall())

    by_id: dict[int, Any] = {}
    for row in rows:
        place_id = _positive_place_id(getattr(row, "place_id", None))
        if place_id is None or place_id in by_id:
            continue
        by_id[place_id] = row

    items: list[PoiSelectionAvailableItem | PoiSelectionUnavailableItem] = []
    for place_id in requested_ids:
        row = by_id.get(place_id)
        if row is None or not is_catalog_eligible(row, city=canonical_city):
            items.append(PoiSelectionUnavailableItem(place_id=place_id))
            continue
        items.append(
            PoiSelectionAvailableItem(
                place_id=place_id,
                place=_project_selectable_poi(row),
            )
        )
    return PoiSelectionResponse(city=canonical_city, items=items)
