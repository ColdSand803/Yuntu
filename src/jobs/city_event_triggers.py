"""Persistence boundary for v0.10.3 city authority and outbox events.

Database triggers are installed by ``sql/v0.10.3-city-event-table.sql``.  This
module owns reads and acknowledgement semantics used by the internal API.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from src.db.models import CityAuthorityRecord, CityEventRecord, CityImageRecord
from src.pipeline.db import get_session_factory


class CityEventNotFoundError(LookupError):
    pass


class CityEventAlreadyConsumedError(RuntimeError):
    def __init__(self, consumed_by: str | None) -> None:
        self.consumed_by = consumed_by
        super().__init__("city event already acknowledged")


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _city_from_row(row: Any) -> CityAuthorityRecord:
    return CityAuthorityRecord(
        city_id=int(row.id),
        canonical_name=str(row.canonical_name),
        status=str(row.status),
        display_lng=float(row.display_lng) if row.display_lng is not None else None,
        display_lat=float(row.display_lat) if row.display_lat is not None else None,
        map_label_offset_x=int(row.map_label_offset_x or 0),
        map_label_offset_y=int(row.map_label_offset_y or 0),
        canonical_quality_pass=(
            bool(row.canonical_quality_pass)
            if row.canonical_quality_pass is not None else None
        ),
        evidence_quality_pass=(
            bool(row.evidence_quality_pass)
            if row.evidence_quality_pass is not None else None
        ),
        last_quality_check_at=row.last_quality_check_time,
        created_at=row.created_time,
        updated_at=row.updated_time,
        aliases=tuple(str(alias) for alias in (row.aliases or [])),
        request_count_30d=int(row.request_count_30d or 0),
        last_requested_time=row.last_requested_time,
        amap_adcode=str(row.amap_adcode) if row.amap_adcode else None,
        quality_failure_reasons=tuple(row.blocking_issues or ()),
    )


_CITY_SELECT = """
    SELECT city.*,
        latest.canonical_quality_pass,
        latest.evidence_quality_pass,
        latest.blocking_issues,
        COALESCE(alias.aliases, ARRAY[]::varchar[]) AS aliases
    FROM travel_city AS city
    LEFT JOIN LATERAL (
        SELECT canonical_quality_pass, evidence_quality_pass, blocking_issues
        FROM travel_city_quality_snapshot
        WHERE city_id = city.id
        ORDER BY checked_time DESC, id DESC
        LIMIT 1
    ) AS latest ON TRUE
    LEFT JOIN LATERAL (
        SELECT ARRAY_AGG(alias ORDER BY alias) AS aliases
        FROM travel_city_alias
        WHERE city_id = city.id
    ) AS alias ON TRUE
"""


async def list_city_authority(
    *, include_disabled: bool = False, limit: int = 100, offset: int = 0
) -> tuple[list[CityAuthorityRecord], int]:
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    if offset < 0:
        raise ValueError("offset must be >= 0")
    where_sql = "" if include_disabled else "WHERE city.status <> 'DISABLED'"
    async with get_session_factory()() as session:
        rows = (await session.execute(text(
            f"{_CITY_SELECT} {where_sql} ORDER BY city.id LIMIT :limit OFFSET :offset"
        ), {"limit": limit, "offset": offset})).all()
        total = int((await session.execute(text(
            "SELECT COUNT(*) FROM travel_city"
            + ("" if include_disabled else " WHERE status <> 'DISABLED'")
        ))).scalar_one())
    return [_city_from_row(row) for row in rows], total


async def get_city_authority(city_id: int) -> CityAuthorityRecord | None:
    async with get_session_factory()() as session:
        row = (await session.execute(
            text(f"{_CITY_SELECT} WHERE city.id = :city_id"),
            {"city_id": city_id},
        )).one_or_none()
    return _city_from_row(row) if row is not None else None


async def list_city_images(
    city_id: int, *, active_only: bool = True
) -> list[CityImageRecord] | None:
    async with get_session_factory()() as session:
        exists = (await session.execute(
            text("SELECT 1 FROM travel_city WHERE id = :city_id"),
            {"city_id": city_id},
        )).scalar_one_or_none()
        if exists is None:
            return None
        active_sql = "AND active = TRUE" if active_only else ""
        rows = (await session.execute(text(f"""
            SELECT * FROM travel_city_image
            WHERE city_id = :city_id {active_sql}
            ORDER BY image_type, position, id
        """), {"city_id": city_id})).all()
    return [CityImageRecord(
        image_id=int(row.id), city_id=int(row.city_id), image_type=str(row.image_type),
        asset_url=str(row.asset_url), asset_url_mobile=row.asset_url_mobile,
        asset_url_thumbnail=row.asset_url_thumbnail, position=int(row.position),
        width=int(row.width) if row.width is not None else None,
        height=int(row.height) if row.height is not None else None,
        format=row.format, active=bool(row.active), created_at=row.created_at,
    ) for row in rows]


async def list_unconsumed_city_events(
    *, limit: int = 100
) -> tuple[list[CityEventRecord], int]:
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    async with get_session_factory()() as session:
        rows = (await session.execute(text("""
            SELECT * FROM travel_city_event
            WHERE consumed_at IS NULL
            ORDER BY created_at ASC, id ASC
            LIMIT :limit
        """), {"limit": limit})).all()
        total = int((await session.execute(text("""
            SELECT COUNT(*) FROM travel_city_event WHERE consumed_at IS NULL
        """))).scalar_one())
    return [CityEventRecord(
        event_id=int(row.id), city_id=int(row.city_id), event_type=row.event_type,
        event_payload=_json_object(row.event_payload), created_at=row.created_at,
        consumed_at=row.consumed_at, consumed_by=row.consumed_by,
    ) for row in rows], total


async def acknowledge_city_event(event_id: int, *, consumer_id: str) -> None:
    consumer = consumer_id.strip()
    if not consumer or len(consumer) > 64:
        raise ValueError("consumer_id must be between 1 and 64 characters")
    async with get_session_factory()() as session:
        row = (await session.execute(text("""
            SELECT consumed_at, consumed_by
            FROM travel_city_event
            WHERE id = :event_id
            FOR UPDATE
        """), {"event_id": event_id})).one_or_none()
        if row is None:
            raise CityEventNotFoundError(event_id)
        if row.consumed_at is not None:
            if row.consumed_by == consumer:
                await session.commit()
                return
            raise CityEventAlreadyConsumedError(row.consumed_by)
        await session.execute(text("""
            UPDATE travel_city_event
            SET consumed_at = NOW(), consumed_by = :consumer_id
            WHERE id = :event_id
        """), {"event_id": event_id, "consumer_id": consumer})
        await session.commit()


CITY_REFERENCE_IMAGES_SQL = """
    SELECT p.place_id, p.canonical_name AS place_name,
           image.asset_id, image.desktop_url AS asset_url,
           image.mobile_url AS asset_url_mobile, image.thumb_url AS asset_url_thumbnail
    FROM travel_city city
    JOIN travel_canonical_place p ON p.city = city.canonical_name
    JOIN LATERAL (
        SELECT * FROM travel_canonical_place_image i
        WHERE i.place_id = p.place_id AND i.active = TRUE
          AND i.desktop_url LIKE 'https://assets.kakarot8.com/%.webp'
        ORDER BY i.position, i.asset_id LIMIT 1
    ) image ON TRUE
    WHERE city.id = :city_id AND p.is_active = TRUE
      AND p.trust_level = 'trusted'
      AND p.review_status IN ('reviewed', 'auto_accepted')
      AND p.place_type NOT IN ('restaurant','food','cafe','snack','snack_shop','dessert','hotel')
    ORDER BY p.base_priority DESC, p.place_id
    LIMIT 8
"""


async def list_city_reference_images(city_id: int) -> list[dict]:
    """Read existing, explicitly linked POI galleries; never create city image rows."""
    async with get_session_factory()() as session:
        rows = (await session.execute(text(CITY_REFERENCE_IMAGES_SQL), {"city_id": city_id})).mappings().all()
    return [dict(row, image_type="poi_reference", position=index, active=True)
            for index, row in enumerate(rows)]
