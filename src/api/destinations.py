"""Destinations API — public directory for supported cinematic cities."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from src.pipeline.city_catalog import CITY_CATALOG, city_meta
from src.pipeline.db import get_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(tags=["destinations"])


def _serialize_city(
    *,
    name: str,
    status: str | None = None,
    quality: dict[str, Any] | None = None,
    lat: float | None = None,
    lng: float | None = None,
) -> dict[str, Any]:
    meta = city_meta(name)
    latitude = meta.lat or lat
    longitude = meta.lng or lng
    has_coords = latitude is not None and longitude is not None and (latitude != 0 or longitude != 0)
    return {
        "id": meta.id,
        "name": meta.name,
        "en_name": meta.en_name,
        "iata": meta.iata,
        "region": meta.region,
        "coordinates": {"lat": latitude, "lng": longitude} if has_coords else None,
        "map_label_offset": {"x": meta.map_label_offset[0], "y": meta.map_label_offset[1]},
        "tags": list(meta.tags),
        "quality": quality,
        "card_cover_url": meta.card_cover_url,
        "background_image_url": meta.background_image_url or None,
        "reference_images": [],
        "isActive": status in {None, "ACTIVE", "GRAY"},
    }


def _fallback_destinations() -> list[dict[str, Any]]:
    chongqing = CITY_CATALOG["重庆"]
    return [
        _serialize_city(
            name=chongqing.name,
            status="ACTIVE",
            quality={"canonical_pass": True, "evidence_pass": True, "last_check_at": None},
        )
    ]


async def _load_cities_from_db() -> list[dict[str, Any]]:
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT
                        city.canonical_name,
                        city.status,
                        q.canonical_quality_pass,
                        q.evidence_quality_pass,
                        q.checked_time,
                        centroid.lat,
                        centroid.lng
                    FROM travel_city AS city
                    LEFT JOIN LATERAL (
                        SELECT
                            canonical_quality_pass,
                            evidence_quality_pass,
                            checked_time
                        FROM travel_city_quality_snapshot
                        WHERE city_id = city.id
                        ORDER BY checked_time DESC, id DESC
                        LIMIT 1
                    ) AS q ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT
                            AVG(latitude)::float AS lat,
                            AVG(longitude)::float AS lng
                        FROM travel_canonical_place AS p
                        WHERE p.city = city.canonical_name
                          AND p.is_active = TRUE
                          AND p.trust_level = 'trusted'
                          AND p.latitude IS NOT NULL
                          AND p.longitude IS NOT NULL
                    ) AS centroid ON TRUE
                    WHERE city.status IN ('GRAY', 'ACTIVE')
                      AND EXISTS (
                          SELECT 1
                          FROM travel_canonical_place AS p
                          WHERE p.city = city.canonical_name
                            AND p.is_active = TRUE
                            AND p.trust_level = 'trusted'
                            AND p.latitude IS NOT NULL
                            AND p.longitude IS NOT NULL
                      )
                    ORDER BY
                        CASE WHEN city.canonical_name = '重庆' THEN 0 ELSE 1 END,
                        city.canonical_name
                    """
                )
            )
        ).all()
    destinations: list[dict[str, Any]] = []
    for row in rows:
        checked = row.checked_time.isoformat() if row.checked_time is not None else None
        destinations.append(
            _serialize_city(
                name=row.canonical_name,
                status=row.status,
                quality={
                    "canonical_pass": (
                        bool(row.canonical_quality_pass)
                        if row.canonical_quality_pass is not None
                        else None
                    ),
                    "evidence_pass": (
                        bool(row.evidence_quality_pass)
                        if row.evidence_quality_pass is not None
                        else None
                    ),
                    "last_check_at": checked,
                },
                lat=float(row.lat) if row.lat is not None else None,
                lng=float(row.lng) if row.lng is not None else None,
            )
        )
    return destinations


@router.get("/destinations")
@router.get("/api/destinations")
async def get_destinations() -> dict[str, Any]:
    try:
        destinations = await _load_cities_from_db()
    except Exception:
        logger.exception("destinations lookup failed; using fallback catalog")
        destinations = []
    if not destinations:
        destinations = _fallback_destinations()
    return {
        "success": True,
        "destinations": destinations,
        "total": len(destinations),
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }