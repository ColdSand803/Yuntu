"""Paginated Amap place/text search used by canonical city import."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from src.pipeline.poi_resolve import (
    AmapClient,
    AmapTransientError,
    _as_text,
    _parse_location,
)

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 25
DEFAULT_MAX_PAGES = 4
_RETRY_ATTEMPTS = 4


@dataclass(frozen=True)
class PlaceSearchHit:
    poi_id: str
    name: str
    type_name: str | None
    typecode: str | None
    address: str | None
    longitude: float
    latitude: float
    adcode: str | None = None
    adname: str | None = None
    cityname: str | None = None
    rating: float | None = None
    avg_price: float | None = None
    open_time: str | None = None


@dataclass(frozen=True)
class SearchGroup:
    name: str
    types: str = ""
    keywords: str = ""
    max_keep: int = 20
    min_rating: float | None = None
    force_type: str | None = None


def default_search_groups(
    *,
    max_attractions: int = 45,
    max_food: int = 20,
    max_areas: int = 8,
    min_food_rating: float = 4.3,
) -> tuple[SearchGroup, ...]:
    area_keep = max(1, max_areas // 2)
    park_keep = max(12, max_attractions // 3)
    food_specialty_keep = max(6, max_food // 2)
    return (
        SearchGroup(
            name="heritage",
            types="110201|110202|110203|110210|110208",
            max_keep=max(20, max_attractions // 2),
        ),
        SearchGroup(name="scenic", types="110000", max_keep=max_attractions),
        SearchGroup(
            name="scenic_area",
            types="110000|080109",
            keywords="风景区|海水浴场|沙滩|海湾",
            max_keep=20,
        ),
        SearchGroup(
            name="cultural_blocks",
            types="110200|110000|141201",
            keywords="街区|古镇|胡同|艺术区|798|大学",
            max_keep=12,
        ),
        SearchGroup(
            name="landmarks_resort",
            types="080501|080101|080400|080602|080603",
            keywords="度假区|体育场|游乐园|水立方|大剧院",
            max_keep=15,
        ),
        SearchGroup(name="museum", types="140100|140400|140200|140600", max_keep=max(18, max_attractions // 2)),
        SearchGroup(name="park", types="110100", max_keep=park_keep),
        SearchGroup(
            name="named_park",
            types="110100",
            keywords="公园|植物园|动物园",
            max_keep=park_keep,
        ),
        SearchGroup(
            name="specialty_food",
            types="050000",
            keywords="老字号|特色菜",
            max_keep=food_specialty_keep,
        ),
        SearchGroup(
            name="food",
            types="050000",
            max_keep=max_food - food_specialty_keep,
            min_rating=min_food_rating,
        ),
        SearchGroup(name="market", types="060400|060401|060700|060702", keywords="市场|旧货", max_keep=6),
        SearchGroup(
            name="areas",
            types="060000",
            keywords="商圈",
            max_keep=area_keep,
            force_type="accommodation_area",
        ),
        SearchGroup(
            name="streets",
            keywords="步行街|商业街",
            max_keep=max(1, max_areas - area_keep),
            force_type="accommodation_area",
        ),
    )


def _as_float(value: Any) -> float | None:
    if value in (None, "", [], "[]"):
        return None
    if isinstance(value, (list, tuple)):
        value = next((item for item in value if item not in (None, "", [])), None)
    if value in (None, "", [], "[]"):
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def _biz_ext(item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("biz_ext") or {}
    return raw if isinstance(raw, dict) else {}


def parse_place_hit(item: dict[str, Any]) -> PlaceSearchHit | None:
    location = _as_text(item.get("location"))
    poi_id = _as_text(item.get("id"))
    name = _as_text(item.get("name"))
    if not location or not poi_id or not name:
        return None
    try:
        longitude, latitude = _parse_location(location)
    except ValueError:
        return None
    ext = _biz_ext(item)
    rating = _as_float(ext.get("rating"))
    if rating is not None and not (0 <= rating <= 5):
        rating = None
    avg_price = _as_float(ext.get("cost"))
    open_time = _as_text(ext.get("opentime_today")) or _as_text(ext.get("opentime_week"))
    return PlaceSearchHit(
        poi_id=poi_id,
        name=name,
        type_name=_as_text(item.get("type")),
        typecode=_as_text(item.get("typecode")),
        address=_as_text(item.get("address")),
        longitude=longitude,
        latitude=latitude,
        adcode=_as_text(item.get("adcode")),
        adname=_as_text(item.get("adname")),
        cityname=_as_text(item.get("cityname")),
        rating=rating,
        avg_price=avg_price,
        open_time=open_time,
    )


async def _call_with_retry(factory):
    delay = 0.5
    last_error: Exception | None = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            return await factory()
        except AmapTransientError as exc:
            last_error = exc
            message = str(exc)
            if any(token in message for token in (
                "10001", "10003", "10009", "10010", "10013", "INVALID_USER_KEY",
            )):
                raise
            if attempt == _RETRY_ATTEMPTS - 1:
                raise
            logger.warning(
                "amap place search retry attempt=%s error=%s",
                attempt + 1,
                exc,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 8)
    raise last_error or AmapTransientError("amap place search failed")


async def search_group_pages(
    client: AmapClient,
    *,
    city: str,
    group: SearchGroup,
    max_pages: int = DEFAULT_MAX_PAGES,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> list[PlaceSearchHit]:
    hits: list[PlaceSearchHit] = []
    seen: set[str] = set()
    keywords = [k.strip() for k in group.keywords.split("|") if k.strip()] if group.keywords else [""]
    pages_per_kw = max(1, max_pages // len(keywords)) if len(keywords) > 1 else max_pages
    for kw in keywords:
        for page in range(1, pages_per_kw + 1):
            payload = await _call_with_retry(
                lambda page=page, kw=kw: client.search_place_text(
                    city=city,
                    keywords=kw,
                    types=group.types,
                    page=page,
                    offset=page_size,
                    extensions="all",
                    citylimit=True,
                )
            )
            pois = payload.get("pois") or []
            page_hits = 0
            for item in pois:
                if not isinstance(item, dict):
                    continue
                hit = parse_place_hit(item)
                if hit is None or hit.poi_id in seen:
                    continue
                seen.add(hit.poi_id)
                hits.append(hit)
                page_hits += 1
            count = 0
            try:
                count = int(payload.get("count") or 0)
            except (TypeError, ValueError):
                count = 0
            logger.info(
                "amap search city=%s group=%s kw=%s page=%s got=%s total=%s count=%s",
                city,
                group.name,
                kw,
                page,
                page_hits,
                len(hits),
                count,
            )
            if page_hits == 0:
                break
            if count and page * page_size >= count:
                break
    return hits