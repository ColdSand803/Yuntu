"""Import Amap POIs into travel_canonical_place for a city."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from src.jobs.city_quality import CityQualityMetrics, inspect_city_quality
from src.jobs.city_store import get_or_create_city
from src.pipeline.amap_place_search import (
    PlaceSearchHit,
    SearchGroup,
    default_search_groups,
    search_group_pages,
)
from src.pipeline.amap_type_map import (
    PROTECTED_SOURCE_TYPES,
    MappedPlace,
    map_amap_poi,
    normalize_city_name,
)
from src.pipeline.db import get_session_factory, reset_engine
from src.pipeline.poi_resolve import (
    AmapClient,
    AmapDefinitiveNotFound,
    _adcode_matches_city,
)

logger = logging.getLogger(__name__)

WRITE_BATCH_SIZE = 8
WRITE_MAX_RETRIES = 5


@dataclass(frozen=True)
class ImportConfig:
    dry_run: bool = False
    activate: bool = False
    max_attractions: int = 45
    max_food: int = 20
    max_areas: int = 8
    min_food_rating: float = 4.3
    max_pages: int = 4


@dataclass
class ImportStats:
    city: str
    scanned: int = 0
    prepared: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_junk: int = 0
    skipped_rating: int = 0
    skipped_city: int = 0
    skipped_dup: int = 0
    protected: int = 0
    quality: CityQualityMetrics | None = None
    city_status: str | None = None
    preview: list[PreparedPlace] = field(default_factory=list)


@dataclass(frozen=True)
class PreparedPlace:
    poi_id: str
    canonical_name: str
    district: str | None
    address: str | None
    adcode: str | None
    latitude: float
    longitude: float
    mapped: MappedPlace
    rating: float | None
    avg_price: float | None
    open_time: str | None
    group_name: str


def _city_belongs(hit: PlaceSearchHit, city: str, geocode_city: str | None) -> bool:
    req = city.rstrip("市")
    for candidate in (hit.cityname, geocode_city):
        if candidate and req in candidate.rstrip("市"):
            return True
    if hit.adcode:
        return _adcode_matches_city(hit.adcode, city, hit.cityname or geocode_city)
    # No adcode and no city name: keep, citylimit=true already applied.
    return True


def prepare_hits(
    hits: list[PlaceSearchHit],
    *,
    city: str,
    group: SearchGroup,
    geocode_city: str | None,
    seen_ids: set[str],
    seen_names: set[str],
) -> tuple[list[PreparedPlace], dict[str, int]]:
    counters = {
        "scanned": 0,
        "skipped_junk": 0,
        "skipped_rating": 0,
        "skipped_city": 0,
        "skipped_dup": 0,
    }
    prepared: list[PreparedPlace] = []
    ranked: list[tuple[int, float, int, PreparedPlace]] = []
    local_ids: set[str] = set()
    local_names: set[str] = set()
    for index, hit in enumerate(hits):
        counters["scanned"] += 1
        if hit.poi_id in seen_ids or hit.poi_id in local_ids:
            counters["skipped_dup"] += 1
            continue
        if not _city_belongs(hit, city, geocode_city):
            counters["skipped_city"] += 1
            continue
        if group.min_rating is not None:
            if hit.rating is None or hit.rating < group.min_rating:
                counters["skipped_rating"] += 1
                continue
        mapped = map_amap_poi(
            name=hit.name,
            typecode=hit.typecode,
            type_name=hit.type_name,
            rating=hit.rating,
            city=city,
            force_type=group.force_type,
        )
        if mapped is None:
            counters["skipped_junk"] += 1
            continue
        key = hit.name.strip()
        if key in seen_names or key in local_names:
            counters["skipped_dup"] += 1
            continue
        local_ids.add(hit.poi_id)
        local_names.add(key)
        place = PreparedPlace(
            poi_id=hit.poi_id,
            canonical_name=hit.name.strip(),
            district=hit.adname,
            address=hit.address,
            adcode=hit.adcode,
            latitude=hit.latitude,
            longitude=hit.longitude,
            mapped=mapped,
            rating=hit.rating,
            avg_price=hit.avg_price,
            open_time=hit.open_time,
            group_name=group.name,
        )
        ranked.append((mapped.base_priority, hit.rating or 0.0, index, place))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    for item in ranked:
        place = item[3]
        if len(prepared) >= group.max_keep:
            break
        seen_ids.add(place.poi_id)
        seen_names.add(place.canonical_name)
        prepared.append(place)
    return prepared, counters



def is_disconnect_error(exc: BaseException) -> bool:
    """True when the Postgres socket died mid-statement (common on Windows/Docker)."""
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, OSError)):
        winerr = getattr(exc, "winerror", None)
        if winerr in {121, 1236, 10054, 10053, 10060}:
            return True
        if exc.__class__ is OSError and winerr:
            return True
    text = str(exc).lower()
    tokens = (
        "connectiondoesnotexist",
        "connection was closed",
        "connection is closed",
        "connectiondoesnotexisterror",
        "winerror 121",
        "winerror 1236",
        "信号灯超时",
        "server closed the connection",
        "the connection is closed",
        "cannot use a connection that is closed",
    )
    if any(token in text for token in tokens):
        return True
    orig = getattr(exc, "orig", None)
    if orig is not None and orig is not exc and is_disconnect_error(orig):
        return True
    cause = exc.__cause__ or exc.__context__
    return bool(cause) and cause is not exc and is_disconnect_error(cause)


def _record_action(stats: ImportStats, action: str) -> None:
    if action == "inserted":
        stats.inserted += 1
    elif action == "updated":
        stats.updated += 1
    elif action == "protected":
        stats.protected += 1


async def persist_prepared_places(
    city: str,
    prepared: list[PreparedPlace],
    stats: ImportStats,
) -> None:
    index = 0
    retries = 0
    while index < len(prepared):
        batch = prepared[index:index + WRITE_BATCH_SIZE]
        try:
            async with get_session_factory()() as session:
                await session.execute(text("SELECT 1"))
                for place in batch:
                    try:
                        async with session.begin_nested():
                            action = await _upsert_place(session, city, place)
                    except IntegrityError:
                        logger.warning(
                            "canonical upsert conflict city=%s name=%s poi=%s",
                            city,
                            place.canonical_name,
                            place.poi_id,
                        )
                        continue
                    _record_action(stats, action)
                await session.commit()
            index += len(batch)
            retries = 0
            logger.info(
                "wrote canonical batch city=%s done=%s/%s",
                city,
                index,
                len(prepared),
            )
        except (DBAPIError, OSError) as exc:
            if not is_disconnect_error(exc) or retries >= WRITE_MAX_RETRIES:
                raise
            retries += 1
            logger.warning(
                "postgres connection dropped city=%s index=%s retry=%s error=%s",
                city,
                index,
                retries,
                exc,
            )
            await reset_engine()
            await asyncio.sleep(min(2 ** retries, 8))

async def _geocode_city(client: AmapClient, city: str) -> str | None:
    try:
        result = await client.geocode(city=city, address=city)
    except (AmapDefinitiveNotFound, Exception) as exc:
        logger.warning("city geocode failed city=%s error=%s", city, exc)
        return None
    return result.city or result.formatted_address


async def _upsert_place(session, city: str, place: PreparedPlace) -> str:
    existing = (
        await session.execute(
            text(
                """
                SELECT place_id, source_type, amap_poi_id, canonical_name,
                       typical_visit_minutes, base_priority, amap_rating
                FROM travel_canonical_place
                WHERE amap_poi_id = :poi_id
                   OR (city = :city AND canonical_name = :name)
                ORDER BY CASE WHEN amap_poi_id = :poi_id THEN 0 ELSE 1 END
                LIMIT 2
                """
            ),
            {"poi_id": place.poi_id, "city": city, "name": place.canonical_name},
        )
    ).all()
    if len(existing) > 1:
        # Prefer the amap_poi_id match when name and id point at different rows.
        poi_match = [row for row in existing if row.amap_poi_id == place.poi_id]
        row = poi_match[0] if poi_match else existing[0]
    elif existing:
        row = existing[0]
    else:
        row = None

    tags_json = json.dumps(list(place.mapped.category_tags), ensure_ascii=False)
    now = datetime.now(timezone.utc)
    params = {
        "name": place.canonical_name,
        "city": city,
        "district": place.district,
        "address": place.address,
        "adcode": place.adcode,
        "latitude": place.latitude,
        "longitude": place.longitude,
        "amap_poi_id": place.poi_id,
        "place_type": place.mapped.place_type,
        "category_tags": tags_json,
        "typical_visit_minutes": place.mapped.typical_visit_minutes,
        "base_priority": place.mapped.base_priority,
        "contextual_only": place.mapped.contextual_only,
        "amap_rating": place.rating,
        "amap_avg_price": place.avg_price,
        "amap_open_time": place.open_time,
        "captured_at": now,
    }

    if row is None:
        inserted = (
            await session.execute(
                text(
                    """
                    INSERT INTO travel_canonical_place (
                        canonical_name, city, district, address, adcode,
                        latitude, longitude, amap_poi_id, place_type, category_tags,
                        typical_visit_minutes, typical_visit_source,
                        typical_visit_confidence, typical_visit_updated_at,
                        source_type, trust_level, review_status, is_active,
                        contextual_only, geo_status, base_priority,
                        amap_rating, amap_avg_price, amap_open_time,
                        amap_data_captured_at
                    ) VALUES (
                        :name, :city, :district, :address, :adcode,
                        :latitude, :longitude, :amap_poi_id, :place_type,
                        CAST(:category_tags AS jsonb),
                        :typical_visit_minutes, 'amap',
                        0.50, :captured_at,
                        'amap', 'trusted', 'auto_accepted', TRUE,
                        :contextual_only, 'resolved', :base_priority,
                        :amap_rating, :amap_avg_price, :amap_open_time,
                        :captured_at
                    )
                    RETURNING place_id
                    """
                ),
                params,
            )
        ).one()
        await _ensure_source(session, int(inserted.place_id), place)
        return "inserted"

    if row.source_type in PROTECTED_SOURCE_TYPES:
        await session.execute(
            text(
                """
                UPDATE travel_canonical_place
                SET amap_poi_id = COALESCE(amap_poi_id, :amap_poi_id),
                    amap_rating = COALESCE(amap_rating, :amap_rating),
                    amap_avg_price = COALESCE(amap_avg_price, :amap_avg_price),
                    amap_open_time = COALESCE(amap_open_time, :amap_open_time),
                    amap_data_captured_at = COALESCE(amap_data_captured_at, :captured_at),
                    adcode = COALESCE(adcode, :adcode),
                    address = COALESCE(NULLIF(address, ''), :address)
                WHERE place_id = :place_id
                """
            ),
            {**params, "place_id": int(row.place_id)},
        )
        await _ensure_source(session, int(row.place_id), place)
        return "protected"

    await session.execute(
        text(
            """
            UPDATE travel_canonical_place
            SET district = COALESCE(:district, district),
                address = COALESCE(:address, address),
                adcode = COALESCE(:adcode, adcode),
                latitude = :latitude,
                longitude = :longitude,
                amap_poi_id = :amap_poi_id,
                category_tags = CASE
                    WHEN CAST(:category_tags AS jsonb) = '[]'::jsonb THEN category_tags
                    ELSE CAST(:category_tags AS jsonb)
                END,
                typical_visit_minutes = COALESCE(typical_visit_minutes, :typical_visit_minutes),
                typical_visit_source = COALESCE(typical_visit_source, 'amap'),
                geo_status = 'resolved',
                is_active = TRUE,
                trust_level = CASE
                    WHEN trust_level = 'rejected' THEN trust_level
                    ELSE 'trusted'
                END,
                review_status = CASE
                    WHEN review_status = 'rejected' THEN review_status
                    ELSE 'auto_accepted'
                END,
                base_priority = GREATEST(base_priority, :base_priority),
                amap_rating = COALESCE(:amap_rating, amap_rating),
                amap_avg_price = COALESCE(:amap_avg_price, amap_avg_price),
                amap_open_time = COALESCE(:amap_open_time, amap_open_time),
                amap_data_captured_at = :captured_at
            WHERE place_id = :place_id
            """
        ),
        {**params, "place_id": int(row.place_id)},
    )
    await _ensure_source(session, int(row.place_id), place)
    return "updated"


async def _ensure_source(session, place_id: int, place: PreparedPlace) -> None:
    summary = " / ".join(
        part
        for part in (
            place.mapped.place_type,
            f"rating {place.rating:.1f}" if place.rating is not None else None,
            place.address,
        )
        if part
    )
    await session.execute(
        text(
            """
            INSERT INTO travel_canonical_place_source (
                canonical_place_id, source_type, source_name, source_url,
                source_place_name, evidence_summary
            ) VALUES (
                :place_id, 'amap_list', 'Amap POI', NULL,
                :source_place_name, :evidence_summary
            )
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "place_id": place_id,
            "source_place_name": place.canonical_name,
            "evidence_summary": summary[:200],
        },
    )


async def _force_activate(city_id: int) -> None:
    async with get_session_factory()() as session:
        await session.execute(
            text(
                """
                UPDATE travel_city
                SET status = 'ACTIVE',
                    active_confirmed_time = COALESCE(active_confirmed_time, NOW()),
                    disabled_reason = NULL
                WHERE id = :city_id
                """
            ),
            {"city_id": city_id},
        )
        await session.commit()


async def import_city(
    city: str,
    *,
    client: AmapClient,
    config: ImportConfig | None = None,
) -> ImportStats:
    config = config or ImportConfig()
    city = normalize_city_name(city)
    stats = ImportStats(city=city)
    groups = default_search_groups(
        max_attractions=config.max_attractions,
        max_food=config.max_food,
        max_areas=config.max_areas,
        min_food_rating=config.min_food_rating,
    )
    geocode_city = await _geocode_city(client, city)
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    prepared: list[PreparedPlace] = []

    for group in groups:
        hits = await search_group_pages(
            client,
            city=city,
            group=group,
            max_pages=config.max_pages,
        )
        batch, counters = prepare_hits(
            hits,
            city=city,
            group=group,
            geocode_city=geocode_city,
            seen_ids=seen_ids,
            seen_names=seen_names,
        )
        stats.scanned += counters["scanned"]
        stats.skipped_junk += counters["skipped_junk"]
        stats.skipped_rating += counters["skipped_rating"]
        stats.skipped_city += counters["skipped_city"]
        stats.skipped_dup += counters["skipped_dup"]
        prepared.extend(batch)
        logger.info(
            "prepared city=%s group=%s kept=%s scanned=%s",
            city,
            group.name,
            len(batch),
            counters["scanned"],
        )

    stats.prepared = len(prepared)
    stats.preview = prepared
    if config.dry_run:
        return stats

    await persist_prepared_places(city, prepared, stats)

    city_row = await get_or_create_city(city)
    quality = await inspect_city_quality(city_row.city_id)
    stats.quality = quality
    if config.activate:
        await _force_activate(city_row.city_id)
        stats.city_status = "ACTIVE"
    else:
        refreshed = await get_or_create_city(city)
        stats.city_status = refreshed.status
    return stats