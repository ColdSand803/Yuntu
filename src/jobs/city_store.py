"""Persistence helpers for the v0.5 canonical city domain."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text

from src.pipeline.db import get_session_factory


class CityAliasConflictError(ValueError):
    """Raised when an alias is already owned by a different canonical city."""


@dataclass(frozen=True)
class CityRecord:
    city_id: int
    canonical_name: str
    status: str
    active_confirmed_time: datetime | None
    request_count_30d: int
    last_requested_time: datetime | None
    last_quality_check_time: datetime | None
    last_refresh_time: datetime | None
    next_refresh_time: datetime | None
    disabled_reason: str | None
    active_batch_id: int | None = None
    active_batch_status: str | None = None
    latest_batch_id: int | None = None
    latest_batch_status: str | None = None
    latest_batch_error_code: str | None = None
    canonical_quality_pass: bool | None = None
    evidence_quality_pass: bool | None = None


@dataclass(frozen=True)
class CityDemandWrite:
    city: CityRecord | None
    created: bool


@dataclass(frozen=True)
class CityQualitySnapshotRecord:
    snapshot_id: int
    city_id: int
    valid_place_count: int
    valid_evidence_count: int
    covered_categories: list[str]
    successful_base_keywords: list[str]
    blocking_issues: list[str]
    gray_eligible: bool
    active_eligible: bool
    checked_time: datetime
    route_eligible_activity_count: int = 0
    route_eligible_food_count: int = 0
    route_eligible_type_coverage: int = 0
    canonical_geo_resolved_ratio: float = 0.0
    canonical_quality_pass: bool = False
    summary_effective_places: int = 0
    summary_effective_evidence: int = 0
    summary_type_coverage: int = 0
    evidence_quality_pass: bool = False


@dataclass(frozen=True)
class CityDetailRecord:
    city: CityRecord
    aliases: list[str]
    latest_quality: CityQualitySnapshotRecord | None
    active_batch_id: int | None


@dataclass(frozen=True)
class CityDispatchCandidate:
    city: CityRecord
    reason: str


def _normalize_city_name(value: str) -> str:
    city = value.strip()
    if not city:
        raise ValueError("city name must not be empty")
    return city


def _row_to_city(row) -> CityRecord:
    mapping = row._mapping

    def optional_value(key: str):
        return mapping.get(key)

    latest_quality = optional_value("latest_quality_json") or {}

    return CityRecord(
        city_id=int(row.id),
        canonical_name=row.canonical_name,
        status=row.status,
        active_confirmed_time=row.active_confirmed_time,
        request_count_30d=int(row.request_count_30d),
        last_requested_time=row.last_requested_time,
        last_quality_check_time=row.last_quality_check_time,
        last_refresh_time=row.last_refresh_time,
        next_refresh_time=row.next_refresh_time,
        disabled_reason=row.disabled_reason,
        active_batch_id=(
            int(optional_value("active_batch_id"))
            if optional_value("active_batch_id") is not None
            else None
        ),
        active_batch_status=optional_value("active_batch_status"),
        latest_batch_id=(
            int(optional_value("latest_batch_id"))
            if optional_value("latest_batch_id") is not None
            else None
        ),
        latest_batch_status=optional_value("latest_batch_status"),
        latest_batch_error_code=optional_value("latest_batch_error_code"),
        canonical_quality_pass=_quality_flag(latest_quality, "canonical_quality_pass"),
        evidence_quality_pass=_quality_flag(latest_quality, "evidence_quality_pass"),
    )


def _quality_flag(value, key: str) -> bool | None:
    if not isinstance(value, dict) or key not in value:
        return None
    return bool(value[key])


def _city_select_sql(tail_sql: str, *, extra_join_sql: str = "") -> str:
    return f"""
        SELECT city.*,
            active_batch.id AS active_batch_id,
            active_batch.status AS active_batch_status,
            latest_batch.id AS latest_batch_id,
            latest_batch.status AS latest_batch_status,
            latest_batch.error_code AS latest_batch_error_code,
            latest_quality.latest_quality_json AS latest_quality_json
        FROM travel_city AS city
        LEFT JOIN LATERAL (
            SELECT id, status
            FROM travel_city_crawl_batch
            WHERE city_id = city.id AND status IN ('PENDING', 'RUNNING')
            ORDER BY created_time ASC
            LIMIT 1
        ) AS active_batch ON TRUE
        LEFT JOIN LATERAL (
            SELECT id, status, error_code
            FROM travel_city_crawl_batch
            WHERE city_id = city.id
            ORDER BY created_time DESC, id DESC
            LIMIT 1
        ) AS latest_batch ON TRUE
        LEFT JOIN LATERAL (
            SELECT to_jsonb(snapshot) AS latest_quality_json
            FROM travel_city_quality_snapshot AS snapshot
            WHERE snapshot.city_id = city.id
            ORDER BY checked_time DESC, id DESC
            LIMIT 1
        ) AS latest_quality ON TRUE
        {extra_join_sql}
        {tail_sql}
    """


def _json_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parsed = json.loads(value)
    else:
        parsed = value
    return [str(item) for item in parsed]


def _row_to_quality_snapshot(row) -> CityQualitySnapshotRecord:
    mapping = getattr(row, "_mapping", {})

    def optional_value(key: str):
        return mapping.get(key) if mapping else getattr(row, key, None)

    return CityQualitySnapshotRecord(
        snapshot_id=int(row.id),
        city_id=int(row.city_id),
        valid_place_count=int(row.valid_place_count),
        valid_evidence_count=int(row.valid_evidence_count),
        covered_categories=_json_list(row.covered_categories),
        successful_base_keywords=_json_list(row.successful_base_keywords),
        blocking_issues=_json_list(row.blocking_issues),
        gray_eligible=bool(row.gray_eligible),
        active_eligible=bool(row.active_eligible),
        checked_time=row.checked_time,
        route_eligible_activity_count=int(
            optional_value("canonical_route_eligible_activity_count") or 0
        ),
        route_eligible_food_count=int(
            optional_value("canonical_route_eligible_food_count") or 0
        ),
        route_eligible_type_coverage=int(
            optional_value("canonical_route_eligible_type_coverage") or 0
        ),
        canonical_geo_resolved_ratio=float(
            optional_value("canonical_geo_resolved_ratio") or 0.0
        ),
        canonical_quality_pass=bool(optional_value("canonical_quality_pass")),
        summary_effective_places=int(optional_value("summary_effective_places") or 0),
        summary_effective_evidence=int(optional_value("summary_effective_evidence") or 0),
        summary_type_coverage=int(optional_value("summary_type_coverage") or 0),
        evidence_quality_pass=bool(optional_value("evidence_quality_pass")),
    )


async def resolve_city(name: str) -> CityRecord | None:
    """Resolve a canonical name or administrator-maintained alias."""
    city_name = _normalize_city_name(name)
    async with get_session_factory()() as session:
        row = (await session.execute(text(_city_select_sql("""
            WHERE city.canonical_name = :name OR alias.alias = :name
            ORDER BY CASE WHEN city.canonical_name = :name THEN 0 ELSE 1 END
            LIMIT 1
        """, extra_join_sql="""
            LEFT JOIN travel_city_alias AS alias ON alias.city_id = city.id
        """)), {"name": city_name})).one_or_none()
    return _row_to_city(row) if row else None


async def get_city(city_id: int) -> CityRecord | None:
    async with get_session_factory()() as session:
        row = (await session.execute(text(_city_select_sql("""
            WHERE city.id = :city_id
        """)), {"city_id": city_id})).one_or_none()
    return _row_to_city(row) if row else None


async def list_cities(
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[CityDetailRecord]:
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    if offset < 0:
        raise ValueError("offset must be >= 0")
    params: dict[str, object] = {"limit": limit, "offset": offset}
    status_sql = ""
    if status:
        normalized_status = status.strip().upper()
        if normalized_status not in {"DISCOVERED", "GRAY", "ACTIVE", "DISABLED"}:
            raise ValueError("invalid city status")
        status_sql = "WHERE city.status = :status"
        params["status"] = normalized_status
    async with get_session_factory()() as session:
        rows = (await session.execute(text(f"""
            SELECT city.*,
                latest_quality.id AS quality_id,
                latest_quality.valid_place_count,
                latest_quality.valid_evidence_count,
                latest_quality.covered_categories,
                latest_quality.successful_base_keywords,
                latest_quality.blocking_issues,
                latest_quality.gray_eligible,
                latest_quality.active_eligible,
                latest_quality.checked_time,
                to_jsonb(latest_quality) AS latest_quality_json,
                active_batch.id AS active_batch_id,
                COALESCE(alias.aliases, ARRAY[]::varchar[]) AS aliases
            FROM travel_city AS city
            LEFT JOIN LATERAL (
                SELECT *
                FROM travel_city_quality_snapshot
                WHERE city_id = city.id
                ORDER BY checked_time DESC, id DESC
                LIMIT 1
            ) AS latest_quality ON TRUE
            LEFT JOIN LATERAL (
                SELECT id
                FROM travel_city_crawl_batch
                WHERE city_id = city.id AND status IN ('PENDING', 'RUNNING')
                ORDER BY created_time ASC
                LIMIT 1
            ) AS active_batch ON TRUE
            LEFT JOIN LATERAL (
                SELECT ARRAY_AGG(alias ORDER BY alias) AS aliases
                FROM travel_city_alias
                WHERE city_id = city.id
            ) AS alias ON TRUE
            {status_sql}
            ORDER BY
                city.last_requested_time DESC NULLS LAST,
                city.created_time DESC,
                city.id DESC
            LIMIT :limit OFFSET :offset
        """), params)).all()
    return [_detail_from_joined_row(row) for row in rows]


async def get_city_detail(city_id: int) -> CityDetailRecord | None:
    async with get_session_factory()() as session:
        row = (await session.execute(text("""
            SELECT city.*,
                latest_quality.id AS quality_id,
                latest_quality.valid_place_count,
                latest_quality.valid_evidence_count,
                latest_quality.covered_categories,
                latest_quality.successful_base_keywords,
                latest_quality.blocking_issues,
                latest_quality.gray_eligible,
                latest_quality.active_eligible,
                latest_quality.checked_time,
                to_jsonb(latest_quality) AS latest_quality_json,
                active_batch.id AS active_batch_id,
                COALESCE(alias.aliases, ARRAY[]::varchar[]) AS aliases
            FROM travel_city AS city
            LEFT JOIN LATERAL (
                SELECT *
                FROM travel_city_quality_snapshot
                WHERE city_id = city.id
                ORDER BY checked_time DESC, id DESC
                LIMIT 1
            ) AS latest_quality ON TRUE
            LEFT JOIN LATERAL (
                SELECT id
                FROM travel_city_crawl_batch
                WHERE city_id = city.id AND status IN ('PENDING', 'RUNNING')
                ORDER BY created_time ASC
                LIMIT 1
            ) AS active_batch ON TRUE
            LEFT JOIN LATERAL (
                SELECT ARRAY_AGG(alias ORDER BY alias) AS aliases
                FROM travel_city_alias
                WHERE city_id = city.id
            ) AS alias ON TRUE
            WHERE city.id = :city_id
        """), {"city_id": city_id})).one_or_none()
    return _detail_from_joined_row(row) if row else None


def _detail_from_joined_row(row) -> CityDetailRecord:
    city = _row_to_city(row)
    latest_quality = None
    if row.quality_id is not None:
        class _QualityRow:
            pass
        quality_row = _QualityRow()
        quality_row.id = row.quality_id
        quality_row.city_id = row.id
        quality_row.valid_place_count = row.valid_place_count
        quality_row.valid_evidence_count = row.valid_evidence_count
        quality_row.covered_categories = row.covered_categories
        quality_row.successful_base_keywords = row.successful_base_keywords
        quality_row.blocking_issues = row.blocking_issues
        quality_row.gray_eligible = row.gray_eligible
        quality_row.active_eligible = row.active_eligible
        latest_quality_json = row.latest_quality_json or {}
        quality_row.canonical_route_eligible_activity_count = latest_quality_json.get(
            "canonical_route_eligible_activity_count", 0
        )
        quality_row.canonical_route_eligible_food_count = latest_quality_json.get(
            "canonical_route_eligible_food_count", 0
        )
        quality_row.canonical_route_eligible_type_coverage = latest_quality_json.get(
            "canonical_route_eligible_type_coverage", 0
        )
        quality_row.canonical_geo_resolved_ratio = latest_quality_json.get(
            "canonical_geo_resolved_ratio", 0.0
        )
        quality_row.canonical_quality_pass = latest_quality_json.get(
            "canonical_quality_pass", False
        )
        quality_row.summary_effective_places = latest_quality_json.get(
            "summary_effective_places", 0
        )
        quality_row.summary_effective_evidence = latest_quality_json.get(
            "summary_effective_evidence", 0
        )
        quality_row.summary_type_coverage = latest_quality_json.get(
            "summary_type_coverage", 0
        )
        quality_row.evidence_quality_pass = latest_quality_json.get(
            "evidence_quality_pass", False
        )
        quality_row.checked_time = row.checked_time
        latest_quality = _row_to_quality_snapshot(quality_row)
    return CityDetailRecord(
        city=city,
        aliases=[str(alias) for alias in (row.aliases or [])],
        latest_quality=latest_quality,
        active_batch_id=int(row.active_batch_id) if row.active_batch_id is not None else None,
    )


async def get_or_create_city(canonical_name: str) -> CityRecord:
    """Return one canonical city, creating a DISCOVERED city when absent."""
    city_name = _normalize_city_name(canonical_name)
    async with get_session_factory()() as session:
        row = (await session.execute(text("""
            INSERT INTO travel_city (canonical_name, status)
            VALUES (:canonical_name, 'DISCOVERED')
            ON CONFLICT (canonical_name) DO UPDATE
            SET canonical_name = EXCLUDED.canonical_name
            RETURNING *
        """), {"canonical_name": city_name})).one()
        await session.commit()
    return _row_to_city(row)


async def create_city_alias(city_id: int, alias: str) -> None:
    """Create one unambiguous alias, rejecting canonical-name collisions."""
    normalized_alias = _normalize_city_name(alias)
    async with get_session_factory()() as session:
        canonical_owner = (await session.execute(text("""
            SELECT id
            FROM travel_city
            WHERE canonical_name = :alias
        """), {"alias": normalized_alias})).scalar_one_or_none()
        if canonical_owner is not None and int(canonical_owner) != city_id:
            raise CityAliasConflictError(
                f"alias {normalized_alias!r} is another canonical city"
            )
        result = await session.execute(text("""
            INSERT INTO travel_city_alias (city_id, alias)
            VALUES (:city_id, :alias)
            ON CONFLICT (alias) DO NOTHING
            RETURNING city_id
        """), {"city_id": city_id, "alias": normalized_alias})
        owner = result.scalar_one_or_none()
        if owner is None:
            owner = (await session.execute(text("""
                SELECT city_id FROM travel_city_alias WHERE alias = :alias
            """), {"alias": normalized_alias})).scalar_one()
        if int(owner) != city_id:
            raise CityAliasConflictError(
                f"alias {normalized_alias!r} is already assigned"
            )
        await session.commit()


async def disable_city(city_id: int, reason: str) -> CityRecord:
    reason_text = reason.strip()
    if not reason_text:
        raise ValueError("disable reason must not be empty")
    async with get_session_factory()() as session:
        row = (await session.execute(text("""
            UPDATE travel_city
            SET status = 'DISABLED',
                disabled_reason = :reason
            WHERE id = :city_id
            RETURNING *
        """), {"city_id": city_id, "reason": reason_text})).one_or_none()
        if row is None:
            raise ValueError("city not found")
        await session.commit()
    return _row_to_city(row)


async def enable_city(city_id: int) -> CityRecord:
    async with get_session_factory()() as session:
        row = (await session.execute(text("""
            UPDATE travel_city
            SET status = 'DISCOVERED',
                disabled_reason = NULL
            WHERE id = :city_id
            RETURNING *
        """), {"city_id": city_id})).one_or_none()
        if row is None:
            raise ValueError("city not found")
        await session.commit()
    return _row_to_city(row)


class CityActivationError(RuntimeError):
    """Raised when ACTIVE confirmation would bypass quality gates."""


async def activate_city(city_id: int) -> CityRecord:
    async with get_session_factory()() as session:
        row = (await session.execute(text("""
            SELECT city.*, latest_quality.active_eligible
            FROM travel_city AS city
            LEFT JOIN LATERAL (
                SELECT active_eligible
                FROM travel_city_quality_snapshot
                WHERE city_id = city.id
                ORDER BY checked_time DESC, id DESC
                LIMIT 1
            ) AS latest_quality ON TRUE
            WHERE city.id = :city_id
            FOR UPDATE OF city
        """), {"city_id": city_id})).one_or_none()
        if row is None:
            raise ValueError("city not found")
        if row.status == "DISABLED":
            raise CityActivationError("disabled city cannot be activated")
        if not bool(row.active_eligible):
            raise CityActivationError("city is not active_eligible")
        updated = (await session.execute(text("""
            UPDATE travel_city
            SET status = 'ACTIVE',
                active_confirmed_time = COALESCE(active_confirmed_time, NOW()),
                disabled_reason = NULL
            WHERE id = :city_id
            RETURNING *
        """), {"city_id": city_id})).one()
        await session.commit()
    return _row_to_city(updated)


async def select_city_refresh_dispatch_candidate() -> CityDispatchCandidate | None:
    """Select one eligible city for Stage 5 deterministic dispatch.

    The caller still creates the batch through city_batch_store, which enforces
    the global active batch lock. This function only encodes priority.
    """
    async with get_session_factory()() as session:
        active = (await session.execute(text("""
            SELECT id
            FROM travel_city_crawl_batch
            WHERE status IN ('PENDING', 'RUNNING')
            LIMIT 1
        """))).one_or_none()
        if active is not None:
            return None

        row = (await session.execute(text("""
            WITH candidates AS (
                SELECT city.*,
                    CASE
                        WHEN city.status = 'DISCOVERED'
                         AND NOT EXISTS (
                            SELECT 1
                            FROM travel_city_crawl_batch AS batch
                            WHERE batch.city_id = city.id
                         )
                            THEN 'first_request'
                        WHEN city.status = 'DISCOVERED'
                            THEN 'below_gray_replenish'
                        WHEN city.status IN ('GRAY', 'ACTIVE')
                         AND city.next_refresh_time IS NOT NULL
                         AND city.next_refresh_time <= NOW()
                            THEN 'scheduled_refresh'
                        ELSE NULL
                    END AS dispatch_reason,
                    CASE
                        WHEN city.status = 'DISCOVERED'
                         AND NOT EXISTS (
                            SELECT 1
                            FROM travel_city_crawl_batch AS batch
                            WHERE batch.city_id = city.id
                         )
                            THEN 1
                        WHEN city.status = 'DISCOVERED'
                            THEN 2
                        WHEN city.status IN ('GRAY', 'ACTIVE')
                         AND city.next_refresh_time IS NOT NULL
                         AND city.next_refresh_time <= NOW()
                            THEN 3
                        ELSE 99
                    END AS priority
                FROM travel_city AS city
                WHERE city.status <> 'DISABLED'
            )
            SELECT *
            FROM candidates
            WHERE dispatch_reason IS NOT NULL
            ORDER BY
                priority ASC,
                last_requested_time DESC NULLS LAST,
                next_refresh_time ASC NULLS LAST,
                created_time ASC,
                id ASC
            LIMIT 1
        """))).one_or_none()
    if row is None:
        return None
    return CityDispatchCandidate(city=_row_to_city(row), reason=row.dispatch_reason)


async def _recalculate_city_demand(session, city_id: int) -> None:
    await session.execute(text("""
        UPDATE travel_city AS city
        SET request_count_30d = demand.request_count_30d,
            last_requested_time = demand.last_requested_time,
            next_refresh_time = LEAST(
                COALESCE(city.next_refresh_time, demand.candidate_next_refresh_time),
                demand.candidate_next_refresh_time
            )
        FROM (
            SELECT
                CAST(:city_id AS bigint) AS city_id,
                COUNT(*) FILTER (
                    WHERE created_time >= NOW() - INTERVAL '30 days'
                )::int AS request_count_30d,
                MAX(created_time) AS last_requested_time,
                NOW() + CASE
                    WHEN COUNT(*) FILTER (
                        WHERE created_time >= NOW() - INTERVAL '30 days'
                    ) >= 20 THEN INTERVAL '3 days'
                    WHEN COUNT(*) FILTER (
                        WHERE created_time >= NOW() - INTERVAL '30 days'
                    ) >= 5 THEN INTERVAL '7 days'
                    WHEN COUNT(*) FILTER (
                        WHERE created_time >= NOW() - INTERVAL '30 days'
                    ) >= 1 THEN INTERVAL '15 days'
                    ELSE INTERVAL '30 days'
                END AS candidate_next_refresh_time
            FROM travel_city_demand
            WHERE city_id = :city_id
        ) AS demand
        WHERE city.id = demand.city_id
    """), {"city_id": city_id})


async def recalculate_city_demand(city_id: int) -> CityRecord:
    """Refresh one city's rolling 30-day demand count and refresh schedule."""
    async with get_session_factory()() as session:
        await _recalculate_city_demand(session, city_id)
        row = (await session.execute(
            text("SELECT * FROM travel_city WHERE id = :city_id"),
            {"city_id": city_id},
        )).one()
        await session.commit()
    return _row_to_city(row)


async def recalculate_all_city_demands() -> int:
    """Refresh rolling demand schedules for all cities using current time."""
    async with get_session_factory()() as session:
        city_ids = [
            int(row.id)
            for row in (await session.execute(
                text("SELECT id FROM travel_city ORDER BY id")
            )).all()
        ]
        for city_id in city_ids:
            await _recalculate_city_demand(session, city_id)
        await session.commit()
    return len(city_ids)


async def record_city_demand(
    *,
    canonical_name: str,
    source: str,
    request_id: str,
    conversation_id: str,
    raw_query: str,
    normalized_preferences: list[str] | dict | None = None,
    countable: bool = True,
) -> CityDemandWrite:
    """Idempotently record one complete recommendation request.

    Callers must set countable=False for follow-ups, sync debug traffic, and
    internal operations. Those calls have no city-domain side effects.
    """
    if not countable:
        return CityDemandWrite(city=None, created=False)

    city_name = _normalize_city_name(canonical_name)
    source = source.strip()
    request_id = request_id.strip()
    if not source or not request_id:
        raise ValueError("source and request_id must not be empty")
    city_id: int
    created: bool
    async with get_session_factory()() as session:
        await session.execute(text("""
            SELECT pg_advisory_xact_lock(
                hashtextextended(:idempotency_key, 2026050501)
            )
        """), {"idempotency_key": f"{len(source)}:{source}{request_id}"})
        existing = (await session.execute(text("""
            SELECT city.*
            FROM travel_city_demand AS demand
            JOIN travel_city AS city ON city.id = demand.city_id
            WHERE demand.source = :source AND demand.request_id = :request_id
        """), {"source": source, "request_id": request_id})).one_or_none()
        if existing is not None:
            city_id = int(existing.id)
            created = False
            await session.commit()
        else:
            city = (await session.execute(text("""
                INSERT INTO travel_city (canonical_name, status)
                VALUES (:canonical_name, 'DISCOVERED')
                ON CONFLICT (canonical_name) DO UPDATE
                SET canonical_name = EXCLUDED.canonical_name
                RETURNING *
            """), {"canonical_name": city_name})).one()
            inserted = (await session.execute(text("""
                INSERT INTO travel_city_demand (
                    city_id, request_id, source, conversation_id,
                    raw_query, normalized_preferences
                ) VALUES (
                    :city_id, :request_id, :source, :conversation_id,
                    :raw_query, CAST(:normalized_preferences AS jsonb)
                )
                ON CONFLICT (source, request_id) DO NOTHING
                RETURNING id
            """), {
                "city_id": city.id,
                "request_id": request_id,
                "source": source,
                "conversation_id": conversation_id,
                "raw_query": raw_query,
                "normalized_preferences": json.dumps(
                    normalized_preferences or [], ensure_ascii=False
                ),
            })).scalar_one_or_none()
            city_id = int(city.id)
            if inserted is None:
                city_id = int((await session.execute(text("""
                    SELECT city_id
                    FROM travel_city_demand
                    WHERE source = :source AND request_id = :request_id
                """), {"source": source, "request_id": request_id})).scalar_one())
            await _recalculate_city_demand(session, city_id)
            created = inserted is not None
            await session.commit()

    return CityDemandWrite(city=await get_city(city_id), created=created)
