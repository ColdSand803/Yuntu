"""Public place detail API for result-page POI popups."""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text

from src.api.poi_catalog import (
    PoiCatalogResponse,
    PoiCatalogValidationError,
    PoiSelectionResponse,
    normalize_catalog_city,
    query_poi_catalog,
    query_poi_selection,
)
from src.api.public_guard import (
    verify_bff_internal_credential,
    verify_public_api_client,
)
from src.jobs.city_store import resolve_city
from src.pipeline.db import get_session_factory

router = APIRouter(dependencies=[Depends(verify_public_api_client)])
internal_router = APIRouter(
    prefix="/internal/v1",
    dependencies=[Depends(verify_bff_internal_credential)],
)

HOT_LIST_EXCLUDED_PLACE_TYPES = (
    "restaurant",
    "hotel",
    "food",
    "cafe",
    "snack",
    "dessert",
)
DISPLAY_TRUST_LEVEL = "trusted"
DISPLAY_REVIEW_STATUSES = {"reviewed", "auto_accepted"}
DISPLAY_GEO_STATUSES = {"resolved", "coordinate_only"}
PLACE_LIST_POOL_LIMIT = 250
MAX_DETAIL_ITEMS = 3
MAX_DETAIL_TEXT_LENGTH = 80
MAX_SUMMARY_LENGTH = 60
# Hotlist-only guard for known city-coordinate pollution. Keep broad enough for
# prefecture-level POIs; it is not used by place detail or generation paths.
HOT_LIST_CITY_BOUNDS = {
    "杭州": (118.0, 121.1, 29.0, 31.1),  # min_lng, max_lng, min_lat, max_lat
}
_URL_RE = re.compile(r"https?://\S+|www\.\S+", flags=re.IGNORECASE)
_INTERNAL_TEXT_RE = re.compile(
    r"\b(?:source|provider|provider_id|crawler_id|recommend_score|quality_score|effective_score)\b"
    r"\s*[:=：]\s*[^,，;；。|｜\s]+",
    flags=re.IGNORECASE,
)


class PlaceUnsupported(Exception):
    """Canonical place exists but is not safe to expose as public detail."""


class GalleryVariant(BaseModel):
    url: str = Field(pattern=r"^https://assets\.kakarot8\.com/\S+\.webp$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class GalleryImage(BaseModel):
    asset_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    position: int = Field(ge=1, le=6)
    alt_text: str = Field(min_length=1, max_length=300)
    desktop: GalleryVariant
    mobile: GalleryVariant
    thumb: GalleryVariant


class PlaceDetailResponse(BaseModel):
    place_id: int
    name: str
    place_type: str
    district: str = ""
    longitude: float | None = None
    latitude: float | None = None
    summary: str = ""
    top_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_count: int = 0
    mention_count: int = 0
    gallery: list[GalleryImage] = Field(default_factory=list, max_length=6)


class PlaceListItem(BaseModel):
    place_id: int
    name: str
    place_type: str
    district: str = ""
    longitude: float | None = None
    latitude: float | None = None
    summary: str = ""
    mention_count: int = 0
    source_count: int = 0


class PlaceListResponse(BaseModel):
    ok: bool = True
    city: str
    places: list[PlaceListItem] = Field(default_factory=list)


def _coerce_json(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default
    return raw


def _json_list(raw: Any) -> list[Any]:
    value = _coerce_json(raw, [])
    return value if isinstance(value, list) else []


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _short_text(value: str, *, limit: int) -> str:
    collapsed = re.sub(r"\s+", " ", value).strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "..."


def _clean_detail_text(value: Any) -> str:
    text_value = str(value or "")
    text_value = _URL_RE.sub("", text_value)
    text_value = _INTERNAL_TEXT_RE.sub("", text_value)
    text_value = re.sub(r"\*\*|`|#+|---", " ", text_value)
    text_value = re.sub(r"\s+", " ", text_value).strip(" \t\r\n,，、。;；:：")
    return _short_text(text_value, limit=MAX_DETAIL_TEXT_LENGTH) if text_value else ""


def _extract_detail_text(item: Any) -> str:
    if isinstance(item, dict):
        for key in ("reason", "warning", "text", "summary", "value"):
            if key in item:
                return _clean_detail_text(item.get(key))
        return ""
    return _clean_detail_text(item)


def _detail_items(raw: Any) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for item in _json_list(raw):
        cleaned = _extract_detail_text(item)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        items.append(cleaned)
        if len(items) >= MAX_DETAIL_ITEMS:
            break
    return items


def _place_type(row: Any) -> str:
    direct = str(row.place_type or "").strip()
    if direct:
        return direct
    category_tags = _json_list(row.category_tags)
    for item in category_tags:
        category = str(item or "").strip()
        if category:
            return category
    return "place"


def _gallery_items(raw: Any) -> list[GalleryImage]:
    values = _json_list(raw)
    if not 1 <= len(values) <= 6:
        return []
    try:
        items = [GalleryImage.model_validate(value) for value in values]
    except ValidationError:
        return []
    items.sort(key=lambda item: item.position)
    if [item.position for item in items] != list(range(1, len(items) + 1)):
        return []
    if len({item.asset_id for item in items}) != len(items):
        return []
    return items


def _coordinate_within_hotlist_city(row: Any, *, city: str) -> bool:
    bounds = HOT_LIST_CITY_BOUNDS.get(city)
    if bounds is None:
        return True
    longitude = _to_float(row.longitude)
    latitude = _to_float(row.latitude)
    if longitude is None or latitude is None:
        return False
    min_lng, max_lng, min_lat, max_lat = bounds
    return min_lng <= longitude <= max_lng and min_lat <= latitude <= max_lat


def _assert_displayable(row: Any) -> None:
    name = str(row.name or "").strip()
    if not row.place_id or not name:
        raise PlaceUnsupported("place id and name are required")
    if name == str(row.city or "").strip():
        raise PlaceUnsupported("city-level pseudo place is not displayable")
    if str(row.trust_level or "") != DISPLAY_TRUST_LEVEL:
        raise PlaceUnsupported("place is not trusted")
    if str(row.review_status or "") not in DISPLAY_REVIEW_STATUSES:
        raise PlaceUnsupported("place review status is not public")
    if not bool(row.is_active):
        raise PlaceUnsupported("place is inactive")
    if str(row.geo_status or "") not in DISPLAY_GEO_STATUSES:
        raise PlaceUnsupported("place geo status is not displayable")
    if not _place_type(row):
        raise PlaceUnsupported("place type is not displayable")


def project_place_detail(row: Any) -> PlaceDetailResponse:
    _assert_displayable(row)
    top_reasons = _detail_items(row.top_reasons)
    warnings = _detail_items(row.warnings)
    summary = (
        _short_text(top_reasons[0], limit=MAX_SUMMARY_LENGTH) if top_reasons else ""
    )
    return PlaceDetailResponse(
        place_id=int(row.place_id),
        name=str(row.name).strip(),
        place_type=_place_type(row),
        district=str(row.district or "").strip(),
        longitude=_to_float(row.longitude),
        latitude=_to_float(row.latitude),
        summary=summary,
        top_reasons=top_reasons,
        warnings=warnings,
        source_count=_non_negative_int(row.source_count),
        mention_count=_non_negative_int(row.mention_count_30d),
        gallery=_gallery_items(getattr(row, "gallery", [])),
    )


def _is_list_displayable(row: Any, *, city: str) -> bool:
    name = str(row.name or "").strip()
    if not row.place_id or not name or name == city:
        return False
    if str(row.city or "").strip() != city:
        return False
    if str(row.trust_level or "") != DISPLAY_TRUST_LEVEL:
        return False
    if str(row.review_status or "") not in DISPLAY_REVIEW_STATUSES:
        return False
    if not bool(row.is_active):
        return False
    if str(row.geo_status or "") not in DISPLAY_GEO_STATUSES:
        return False
    if _to_float(row.latitude) is None or _to_float(row.longitude) is None:
        return False
    if not _coordinate_within_hotlist_city(row, city=city):
        return False
    return str(row.place_type or "").strip() not in HOT_LIST_EXCLUDED_PLACE_TYPES


def project_place_list_item(row: Any) -> PlaceListItem:
    top_reasons = _detail_items(row.top_reasons)
    summary = (
        _short_text(top_reasons[0], limit=MAX_SUMMARY_LENGTH) if top_reasons else ""
    )
    return PlaceListItem(
        place_id=int(row.place_id),
        name=str(row.name).strip(),
        place_type=_place_type(row),
        district=str(row.district or "").strip(),
        longitude=_to_float(row.longitude),
        latitude=_to_float(row.latitude),
        summary=summary,
        mention_count=_non_negative_int(row.mention_count_30d),
        source_count=_non_negative_int(row.source_count),
    )


def _place_list_sort_key(row: Any) -> tuple[int, int, float, int]:
    return (
        -_non_negative_int(getattr(row, "mention_count_30d", 0)),
        -_non_negative_int(getattr(row, "base_priority", 0)),
        -(_to_float(getattr(row, "recommend_score", 0)) or 0.0),
        _non_negative_int(getattr(row, "place_id", 0)),
    )


async def get_place_list(city: str, *, limit: int) -> list[PlaceListItem]:
    pool_limit = min(PLACE_LIST_POOL_LIMIT, max(limit * 5, limit))
    async with get_session_factory()() as session:
        result = await session.execute(
            text("""
                SELECT
                    c.place_id,
                    c.canonical_name AS name,
                    c.city,
                    c.district,
                    c.longitude,
                    c.latitude,
                    c.place_type,
                    c.category_tags,
                    c.base_priority,
                    c.trust_level,
                    c.review_status,
                    c.is_active,
                    c.geo_status,
                    COALESCE(s.top_reasons, '[]'::jsonb) AS top_reasons,
                    COALESCE(s.source_count, 0) AS source_count,
                    COALESCE(s.mention_count_30d, 0) AS mention_count_30d,
                    COALESCE(s.recommend_score, 0) AS recommend_score
                FROM travel_canonical_place AS c
                LEFT JOIN travel_place_summary AS s
                  ON s.canonical_place_id = c.place_id
                WHERE c.city = :city
                  AND c.trust_level = 'trusted'
                  AND c.review_status IN ('reviewed', 'auto_accepted')
                  AND c.is_active = TRUE
                  AND c.geo_status IN ('resolved', 'coordinate_only')
                  AND c.latitude IS NOT NULL
                  AND c.longitude IS NOT NULL
                  AND c.canonical_name <> c.city
                  AND NOT (c.place_type = ANY(CAST(:excluded_types AS text[])))
                ORDER BY COALESCE(s.mention_count_30d, 0) DESC,
                         c.base_priority DESC,
                         s.recommend_score DESC NULLS LAST,
                         c.place_id ASC
                LIMIT :pool_limit
            """),
            {
                "city": city,
                "excluded_types": list(HOT_LIST_EXCLUDED_PLACE_TYPES),
                "pool_limit": pool_limit,
            },
        )
        rows = result.fetchall()

    places: list[PlaceListItem] = []
    seen_names: set[str] = set()
    for row in sorted(rows, key=_place_list_sort_key):
        if not _is_list_displayable(row, city=city):
            continue
        item = project_place_list_item(row)
        if not item.name or item.name in seen_names:
            continue
        seen_names.add(item.name)
        places.append(item)
        if len(places) >= limit:
            break
    return places


async def get_place_detail(place_id: int) -> PlaceDetailResponse | None:
    async with get_session_factory()() as session:
        row = (
            await session.execute(
                text("""
                SELECT
                    c.place_id,
                    c.canonical_name AS name,
                    c.city,
                    c.district,
                    c.longitude,
                    c.latitude,
                    c.place_type,
                    c.category_tags,
                    c.trust_level,
                    c.review_status,
                    c.is_active,
                    c.geo_status,
                    COALESCE(s.top_reasons, '[]'::jsonb) AS top_reasons,
                    COALESCE(s.warnings, '[]'::jsonb) AS warnings,
                    COALESCE(s.source_count, 0) AS source_count,
                    COALESCE(s.mention_count_30d, 0) AS mention_count_30d,
                    COALESCE((
                        SELECT jsonb_agg(
                            jsonb_build_object(
                                'asset_id', image.asset_id,
                                'position', image.position,
                                'alt_text', image.alt_text,
                                'desktop', jsonb_build_object(
                                    'url', image.desktop_url,
                                    'width', image.desktop_width,
                                    'height', image.desktop_height
                                ),
                                'mobile', jsonb_build_object(
                                    'url', image.mobile_url,
                                    'width', image.mobile_width,
                                    'height', image.mobile_height
                                ),
                                'thumb', jsonb_build_object(
                                    'url', image.thumb_url,
                                    'width', image.thumb_width,
                                    'height', image.thumb_height
                                )
                            ) ORDER BY image.position
                        )
                        FROM travel_canonical_place_image AS image
                        WHERE image.place_id = c.place_id AND image.active = TRUE
                    ), '[]'::jsonb) AS gallery
                FROM travel_canonical_place AS c
                LEFT JOIN travel_place_summary AS s
                  ON s.canonical_place_id = c.place_id
                WHERE c.place_id = :place_id
            """),
                {"place_id": place_id},
            )
        ).one_or_none()
    if row is None:
        return None
    return project_place_detail(row)


@router.get("/trip/places", response_model=PlaceListResponse)
async def list_trip_places(
    city: str = Query(...),
    limit: int = Query(12, ge=1, le=50),
) -> PlaceListResponse:
    requested_city = city.strip()
    if not 1 <= len(requested_city) <= 64:
        raise HTTPException(status_code=422, detail="city must be 1..64 chars")

    resolved = await resolve_city(requested_city)
    if resolved is None:
        return PlaceListResponse(city=requested_city, places=[])

    canonical_city = resolved.canonical_name
    places = await get_place_list(canonical_city, limit=limit)
    return PlaceListResponse(city=canonical_city, places=places)


async def _trip_place_response(place_id: int):
    try:
        result = await get_place_detail(place_id)
    except PlaceUnsupported:
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "error": {
                    "code": "PLACE_UNSUPPORTED",
                    "message": "该地点暂不支持展示详情",
                },
            },
        )
    if result is None:
        return JSONResponse(
            status_code=404,
            content={
                "ok": False,
                "error": {
                    "code": "PLACE_NOT_FOUND",
                    "message": "地点不存在",
                },
            },
        )
    return result


@router.get("/trip/places/{place_id}", response_model=PlaceDetailResponse)
async def trip_place(place_id: int = Path(..., ge=1)):
    return await _trip_place_response(place_id)


@internal_router.get("/trip/places/{place_id}", response_model=PlaceDetailResponse)
async def internal_trip_place(place_id: int = Path(..., ge=1)):
    return await _trip_place_response(place_id)


def _poi_catalog_http_error(exc: PoiCatalogValidationError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


async def _canonical_poi_catalog_city(city: str) -> str:
    try:
        requested = normalize_catalog_city(city)
    except PoiCatalogValidationError as exc:
        raise _poi_catalog_http_error(exc) from exc
    resolved = await resolve_city(requested)
    if resolved is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "POI_CATALOG_CITY_NOT_FOUND",
                "message": "City is not available",
            },
        )
    return resolved.canonical_name


@router.get("/trip/poi-catalog", response_model=PoiCatalogResponse)
@internal_router.get("/trip/poi-catalog", response_model=PoiCatalogResponse)
async def internal_poi_catalog(
    city: str = Query(...),
    q: str | None = Query(default=""),
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=50),
) -> PoiCatalogResponse:
    canonical_city = await _canonical_poi_catalog_city(city)
    try:
        return await query_poi_catalog(
            city=canonical_city,
            q=q,
            after_id=after_id,
            limit=limit,
        )
    except PoiCatalogValidationError as exc:
        raise _poi_catalog_http_error(exc) from exc


@router.get("/trip/poi-catalog/selection", response_model=PoiSelectionResponse)
@internal_router.get("/trip/poi-catalog/selection", response_model=PoiSelectionResponse)
async def internal_poi_catalog_selection(
    city: str = Query(...),
    place_ids: list[int] = Query(..., min_length=1, max_length=5),
) -> PoiSelectionResponse:
    canonical_city = await _canonical_poi_catalog_city(city)
    try:
        return await query_poi_selection(city=canonical_city, place_ids=place_ids)
    except PoiCatalogValidationError as exc:
        raise _poi_catalog_http_error(exc) from exc
