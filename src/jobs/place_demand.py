"""Append-only store for user-specified place demand."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import text

from src.agents.poi_alias import normalize_place_name
from src.agents.schema import TripRequest
from src.pipeline.extract import _normalize_place_name as normalize_extract_place_name
from src.pipeline.db import get_session_factory

logger = logging.getLogger(__name__)


VALID_MATCH_STATUSES = frozenset({"matched", "candidate", "unmatched", "cross_city"})
VALID_SOURCES = frozenset({"user_must_include"})
DISPLAY_REVIEW_STATUSES = {"reviewed", "auto_accepted"}
DISPLAY_GEO_STATUSES = {"resolved", "coordinate_only"}
MatchStatus = Literal["matched", "candidate", "unmatched", "cross_city"]


@dataclass(frozen=True)
class PlaceDemandRow:
    city: str
    input_name: str
    match_status: str
    matched_place_id: int | None = None
    matched_city: str | None = None
    normalized_name: str = ""

    def __post_init__(self) -> None:
        city = self.city.strip()
        input_name = self.input_name.strip()
        normalized_name = (self.normalized_name or normalize_place_name(input_name)).strip()
        matched_city = self.matched_city.strip() if self.matched_city else None
        if not city:
            raise ValueError("city must not be empty")
        if not input_name:
            raise ValueError("input_name must not be empty")
        if not normalized_name:
            raise ValueError("normalized_name must not be empty")
        if self.match_status not in VALID_MATCH_STATUSES:
            raise ValueError(f"invalid match_status: {self.match_status}")
        object.__setattr__(self, "city", city)
        object.__setattr__(self, "input_name", input_name)
        object.__setattr__(self, "normalized_name", normalized_name)
        object.__setattr__(self, "matched_city", matched_city)


class MustIncludeReportItem(BaseModel):
    input_name: str
    normalized_name: str
    place_id: int | None = None
    matched_city: str | None = None
    match_status: MatchStatus
    matched_via: str = ""
    avoid_conflict: bool = False
    reason: str = ""


class MustIncludeResolution(BaseModel):
    report_items: list[MustIncludeReportItem] = Field(default_factory=list)

    @property
    def matched_place_ids(self) -> list[int]:
        return [
            item.place_id
            for item in self.report_items
            if item.match_status == "matched" and item.place_id is not None
        ]


def _is_displayable_trusted(row: Any) -> bool:
    name = str(getattr(row, "canonical_name", "") or "").strip()
    city = str(getattr(row, "city", "") or "").strip()
    return (
        bool(getattr(row, "place_id", None))
        and bool(name)
        and name != city
        and str(getattr(row, "trust_level", "") or "") == "trusted"
        and str(getattr(row, "review_status", "") or "") in DISPLAY_REVIEW_STATUSES
        and bool(getattr(row, "is_active", False))
        and str(getattr(row, "geo_status", "") or "") in DISPLAY_GEO_STATUSES
        and getattr(row, "latitude", None) is not None
        and getattr(row, "longitude", None) is not None
        and bool(str(getattr(row, "place_type", "") or "").strip())
    )


def _is_candidate(row: Any) -> bool:
    return str(getattr(row, "trust_level", "") or "") == "candidate"


def _rank_rows(rows: list[Any]) -> list[Any]:
    return sorted(
        rows,
        key=lambda row: (
            -int(getattr(row, "base_priority", 0) or 0),
            int(getattr(row, "place_id", 0) or 0),
        ),
    )


def _as_fetchall(result: Any) -> list[Any]:
    rows = result.fetchall()
    return list(rows)


async def _fetch_place_by_id(session: Any, place_id: int) -> Any | None:
    result = await session.execute(text("""
        SELECT
            place_id, canonical_name, city, trust_level, review_status,
            is_active, geo_status, latitude, longitude, place_type,
            base_priority
        FROM travel_canonical_place
        WHERE place_id = :place_id
        LIMIT 1
    """), {"place_id": place_id})
    rows = _as_fetchall(result)
    return rows[0] if rows else None


async def _fetch_same_city_exact(
    session: Any,
    *,
    city: str,
    raw_name: str,
    lookup_name: str,
) -> list[Any]:
    result = await session.execute(text("""
        SELECT
            place_id, canonical_name, city, trust_level, review_status,
            is_active, geo_status, latitude, longitude, place_type,
            base_priority,
            'canonical_exact' AS matched_via
        FROM travel_canonical_place
        WHERE city = :city
          AND canonical_name IN (:raw_name, :lookup_name)
        ORDER BY base_priority DESC, place_id ASC
        LIMIT 10
    """), {
        "city": city,
        "raw_name": raw_name,
        "lookup_name": lookup_name,
    })
    return _rank_rows(_as_fetchall(result))


async def _fetch_same_city_alias(
    session: Any,
    *,
    city: str,
    normalized_names: list[str],
) -> list[Any]:
    result = await session.execute(text("""
        SELECT
            c.place_id, c.canonical_name, c.city, c.trust_level,
            c.review_status, c.is_active, c.geo_status, c.latitude,
            c.longitude, c.place_type, c.base_priority,
            CASE
                WHEN a.status = 'confirmed' THEN 'confirmed_alias'
                ELSE 'candidate_alias'
            END AS matched_via,
            a.status AS alias_status
        FROM travel_place_alias AS a
        JOIN travel_canonical_place AS c
          ON c.place_id = a.canonical_place_id
        WHERE c.city = :city
          AND a.normalized_alias IN (:norm_0, :norm_1, :norm_2)
          AND a.status IN ('confirmed', 'candidate')
        ORDER BY c.base_priority DESC, c.place_id ASC
        LIMIT 10
    """), {
        "city": city,
        "norm_0": normalized_names[0],
        "norm_1": normalized_names[1],
        "norm_2": normalized_names[2],
    })
    return _rank_rows(_as_fetchall(result))


async def _fetch_cross_city_hits(
    session: Any,
    *,
    raw_name: str,
    lookup_name: str,
    normalized_names: list[str],
) -> list[Any]:
    result = await session.execute(text("""
        SELECT
            c.place_id, c.canonical_name, c.city, c.trust_level,
            c.review_status, c.is_active, c.geo_status, c.latitude,
            c.longitude, c.place_type, c.base_priority,
            'cross_city_exact' AS matched_via
        FROM travel_canonical_place AS c
        WHERE c.canonical_name IN (:raw_name, :lookup_name)
        UNION ALL
        SELECT
            c.place_id, c.canonical_name, c.city, c.trust_level,
            c.review_status, c.is_active, c.geo_status, c.latitude,
            c.longitude, c.place_type, c.base_priority,
            'cross_city_alias' AS matched_via
        FROM travel_place_alias AS a
        JOIN travel_canonical_place AS c
          ON c.place_id = a.canonical_place_id
        WHERE a.normalized_alias IN (:norm_0, :norm_1, :norm_2)
          AND a.status = 'confirmed'
        LIMIT 8
    """), {
        "raw_name": raw_name,
        "lookup_name": lookup_name,
        "norm_0": normalized_names[0],
        "norm_1": normalized_names[1],
        "norm_2": normalized_names[2],
    })
    return _rank_rows(_as_fetchall(result))


def _report_from_row(
    *,
    input_name: str,
    normalized_name: str,
    row: Any,
    status: MatchStatus,
    matched_via: str,
    reason: str,
    avoid_conflict: bool = False,
) -> MustIncludeReportItem:
    return MustIncludeReportItem(
        input_name=input_name,
        normalized_name=normalized_name,
        place_id=int(row.place_id) if getattr(row, "place_id", None) is not None else None,
        matched_city=str(getattr(row, "city", "") or "").strip() or None,
        match_status=status,
        matched_via=matched_via,
        avoid_conflict=avoid_conflict,
        reason=reason,
    )


def _report_unmatched(
    *,
    input_name: str,
    normalized_name: str,
    reason: str = "no exact canonical or confirmed alias match",
) -> MustIncludeReportItem:
    return MustIncludeReportItem(
        input_name=input_name,
        normalized_name=normalized_name,
        match_status="unmatched",
        matched_via="none",
        avoid_conflict=False,
        reason=reason,
    )


def _report_cross_city_ambiguous(
    *,
    input_name: str,
    normalized_name: str,
) -> MustIncludeReportItem:
    return MustIncludeReportItem(
        input_name=input_name,
        normalized_name=normalized_name,
        match_status="cross_city",
        matched_via="cross_city_probe",
        avoid_conflict=True,
        reason="place appears outside the requested city, but multiple cities match",
    )


async def _match_one_must_include(
    session: Any,
    *,
    trip_request: TripRequest,
    input_name: str,
    place_id: int | None,
) -> MustIncludeReportItem:
    city = trip_request.to_city.strip()
    normalized_name = normalize_place_name(input_name)
    lookup_name = normalized_name
    if city and lookup_name.startswith(city) and len(lookup_name) > len(city):
        lookup_name = lookup_name[len(city):]
    extract_normalized = normalize_extract_place_name(input_name)
    alias_norms = [
        normalized_name,
        lookup_name,
        extract_normalized or normalized_name,
    ]

    if place_id is not None:
        row = await _fetch_place_by_id(session, place_id)
        if row is None:
            return _report_unmatched(
                input_name=input_name,
                normalized_name=normalized_name,
                reason="client place_id was not found",
            )
        row_city = str(getattr(row, "city", "") or "").strip()
        if row_city and row_city != city:
            return _report_from_row(
                input_name=input_name,
                normalized_name=normalized_name,
                row=row,
                status="cross_city",
                matched_via="place_id",
                avoid_conflict=True,
                reason=f"place_id belongs to {row_city}, not {city}",
            )
        if row_city == city and _is_displayable_trusted(row):
            return _report_from_row(
                input_name=input_name,
                normalized_name=normalized_name,
                row=row,
                status="matched",
                matched_via="place_id",
                reason="client place_id verified in requested city",
            )
        if row_city == city and _is_candidate(row):
            return _report_from_row(
                input_name=input_name,
                normalized_name=normalized_name,
                row=row,
                status="candidate",
                matched_via="place_id",
                reason="client place_id points to candidate place in requested city",
            )
        return _report_unmatched(
            input_name=input_name,
            normalized_name=normalized_name,
            reason="client place_id is not a usable match in requested city",
        )

    same_city_exact = await _fetch_same_city_exact(
        session,
        city=city,
        raw_name=input_name,
        lookup_name=lookup_name,
    )
    for row in same_city_exact:
        if _is_displayable_trusted(row):
            return _report_from_row(
                input_name=input_name,
                normalized_name=normalized_name,
                row=row,
                status="matched",
                matched_via="canonical_exact",
                reason="exact canonical name match in requested city",
            )
        if _is_candidate(row):
            return _report_from_row(
                input_name=input_name,
                normalized_name=normalized_name,
                row=row,
                status="candidate",
                matched_via="canonical_exact",
                reason="same-city canonical match is candidate trust level",
            )

    same_city_alias = await _fetch_same_city_alias(
        session,
        city=city,
        normalized_names=alias_norms,
    )
    for row in same_city_alias:
        alias_status = str(getattr(row, "alias_status", "") or "")
        if alias_status == "candidate":
            return _report_from_row(
                input_name=input_name,
                normalized_name=normalized_name,
                row=row,
                status="candidate",
                matched_via="candidate_alias",
                reason="same-city alias is candidate status",
            )
        if _is_displayable_trusted(row):
            return _report_from_row(
                input_name=input_name,
                normalized_name=normalized_name,
                row=row,
                status="matched",
                matched_via="confirmed_alias",
                reason="confirmed alias match in requested city",
            )
        if _is_candidate(row):
            return _report_from_row(
                input_name=input_name,
                normalized_name=normalized_name,
                row=row,
                status="candidate",
                matched_via="confirmed_alias",
                reason="confirmed alias owner is candidate trust level",
            )

    cross_city_hits = await _fetch_cross_city_hits(
        session,
        raw_name=input_name,
        lookup_name=lookup_name,
        normalized_names=alias_norms,
    )
    distinct_cities = {
        str(getattr(row, "city", "") or "").strip()
        for row in cross_city_hits
        if str(getattr(row, "city", "") or "").strip() and str(getattr(row, "city", "") or "").strip() != city
    }
    if len(distinct_cities) == 1:
        matched_city = next(iter(distinct_cities))
        row = next(
            row
            for row in cross_city_hits
            if str(getattr(row, "city", "") or "").strip() == matched_city
        )
        return _report_from_row(
            input_name=input_name,
            normalized_name=normalized_name,
            row=row,
            status="cross_city",
            matched_via=str(getattr(row, "matched_via", "") or "cross_city_probe"),
            avoid_conflict=True,
            reason=f"place appears to be in {matched_city}, not {city}",
        )
    if len(distinct_cities) > 1:
        return _report_cross_city_ambiguous(
            input_name=input_name,
            normalized_name=normalized_name,
        )
    return _report_unmatched(input_name=input_name, normalized_name=normalized_name)


def _demand_rows_for_resolution(
    trip_request: TripRequest,
    resolution: MustIncludeResolution,
) -> list[PlaceDemandRow]:
    city = trip_request.to_city.strip()
    return [
        PlaceDemandRow(
            city=city,
            input_name=item.input_name,
            normalized_name=item.normalized_name,
            matched_place_id=item.place_id,
            matched_city=item.matched_city,
            match_status=item.match_status,
        )
        for item in resolution.report_items
    ]


async def match_and_record_must_include(
    trip_request: TripRequest,
    *,
    source: str,
    request_id: str,
    conversation_id: str,
    countable: bool,
) -> MustIncludeResolution:
    """Resolve structured must-include place names without fuzzy or LLM matching."""
    if not trip_request.must_include:
        return MustIncludeResolution()

    try:
        async with get_session_factory()() as session:
            report_items = [
                await _match_one_must_include(
                    session,
                    trip_request=trip_request,
                    input_name=item.name,
                    place_id=item.place_id,
                )
                for item in trip_request.must_include
            ]
    except Exception:
        logger.warning(
            "must_include matching failed request_id=%s",
            request_id,
            exc_info=True,
        )
        return MustIncludeResolution()

    resolution = MustIncludeResolution(report_items=report_items)
    if not countable:
        return resolution

    try:
        await record_place_demand_rows(
            rows=_demand_rows_for_resolution(trip_request, resolution),
            source=source,
            request_id=request_id,
            conversation_id=conversation_id,
            countable=True,
        )
    except Exception:
        logger.warning(
            "must_include demand recording failed request_id=%s",
            request_id,
            exc_info=True,
        )
    return resolution


def _normalize_source(source: str) -> str:
    value = source.strip()
    if value not in VALID_SOURCES:
        raise ValueError(f"invalid source: {source}")
    return value


def _prepare_rows(rows: list[PlaceDemandRow] | tuple[PlaceDemandRow, ...]) -> list[PlaceDemandRow]:
    prepared: dict[str, PlaceDemandRow] = {}
    for row in rows:
        if not isinstance(row, PlaceDemandRow):
            raise TypeError("rows must contain PlaceDemandRow values")
        prepared.setdefault(row.normalized_name, row)
    return list(prepared.values())


async def record_place_demand_rows(
    *,
    rows: list[PlaceDemandRow] | tuple[PlaceDemandRow, ...],
    source: str = "user_must_include",
    request_id: str,
    conversation_id: str = "",
    countable: bool = True,
) -> int:
    """Idempotently append user-specified place demand rows for one request."""
    if not countable:
        return 0

    prepared_rows = _prepare_rows(rows)
    if not prepared_rows:
        return 0

    source = _normalize_source(source)
    request_id = request_id.strip()
    conversation_id = conversation_id.strip() if conversation_id else ""
    if not request_id:
        raise ValueError("request_id must not be empty")

    params = [
        {
            "city": row.city,
            "input_name": row.input_name,
            "normalized_name": row.normalized_name,
            "matched_place_id": row.matched_place_id,
            "matched_city": row.matched_city,
            "match_status": row.match_status,
            "source": source,
            "request_id": request_id,
            "conversation_id": conversation_id,
        }
        for row in prepared_rows
    ]

    async with get_session_factory()() as session:
        await session.execute(text("""
            SELECT pg_advisory_xact_lock(
                hashtextextended(:idempotency_key, 2026070501)
            )
        """), {"idempotency_key": f"{len(source)}:{source}{request_id}"})
        await session.execute(text("""
            INSERT INTO travel_place_demand (
                city, input_name, normalized_name, matched_place_id, matched_city,
                match_status, source, request_id, conversation_id
            ) VALUES (
                :city, :input_name, :normalized_name, :matched_place_id, :matched_city,
                :match_status, :source, :request_id, :conversation_id
            )
            ON CONFLICT (source, request_id, normalized_name) DO NOTHING
        """), params)
        await session.commit()

    return len(params)
