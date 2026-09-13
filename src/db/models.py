"""Database-facing records for the v0.10.3 city producer contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

CityEventType = Literal[
    "CITY_CREATED",
    "CITY_UPDATED",
    "CITY_STATUS_CHANGED",
    "CITY_IMAGE_UPDATED",
    "CITY_COORDINATES_UPDATED",
    "CITY_QUALITY_CHECKED",
]


@dataclass(frozen=True)
class CityAuthorityRecord:
    city_id: int
    canonical_name: str
    status: str
    display_lng: float | None
    display_lat: float | None
    map_label_offset_x: int
    map_label_offset_y: int
    canonical_quality_pass: bool | None
    evidence_quality_pass: bool | None
    last_quality_check_at: datetime | None
    created_at: datetime
    updated_at: datetime
    aliases: tuple[str, ...] = ()
    request_count_30d: int = 0
    last_requested_time: datetime | None = None
    amap_adcode: str | None = None
    quality_failure_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class CityImageRecord:
    image_id: int
    city_id: int
    image_type: str
    asset_url: str
    asset_url_mobile: str | None
    asset_url_thumbnail: str | None
    position: int
    width: int | None
    height: int | None
    format: str | None
    active: bool
    created_at: datetime


@dataclass(frozen=True)
class CityEventRecord:
    event_id: int
    city_id: int
    event_type: CityEventType
    event_payload: dict[str, Any]
    created_at: datetime
    consumed_at: datetime | None = None
    consumed_by: str | None = None
