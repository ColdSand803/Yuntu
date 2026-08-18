"""Persistence helpers for v0.5 city-level crawl batches."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.jobs.city_keywords import city_batch_keywords
from src.pipeline.db import get_session_factory

ACTIVE_BATCH_STATUSES = ("PENDING", "RUNNING")
TERMINAL_BATCH_STATUSES = frozenset({
    "SUCCESS", "PARTIAL_SUCCESS", "FAILED", "COOKIE_EXPIRED", "TIMEOUT",
})
CITY_BATCH_CLAIM_LOCK_ID = 2026052604


class CityBatchActiveError(RuntimeError):
    """Raised when the global single active city batch slot is occupied."""


@dataclass(frozen=True)
class CityBatchItemRecord:
    item_id: int
    batch_id: int
    keyword: str
    keyword_type: str
    status: str
    crawl_run_id: int | None
    error_code: str | None
    error_message: str | None
    started_time: datetime | None
    finished_time: datetime | None


@dataclass(frozen=True)
class CityBatchRecord:
    batch_id: int
    city_id: int
    canonical_name: str
    trigger_source: str
    reason: str
    limit_per_keyword: int
    status: str
    extract_status: str
    poi_resolve_status: str
    refresh_status: str
    quality_status: str
    heartbeat_time: datetime | None
    started_time: datetime | None
    finished_time: datetime | None
    error_code: str | None
    error_message: str | None
    items: list[CityBatchItemRecord] = field(default_factory=list)


@dataclass(frozen=True)
class CookieExpiredRetryCandidate:
    batch: CityBatchRecord
    total_count: int


def _row_to_item(row) -> CityBatchItemRecord:
    return CityBatchItemRecord(
        item_id=int(row.id),
        batch_id=int(row.batch_id),
        keyword=row.keyword,
        keyword_type=row.keyword_type,
        status=row.status,
        crawl_run_id=int(row.crawl_run_id) if row.crawl_run_id is not None else None,
        error_code=row.error_code,
        error_message=row.error_message,
        started_time=row.started_time,
        finished_time=row.finished_time,
    )


def _row_to_batch(row, items: list[CityBatchItemRecord]) -> CityBatchRecord:
    return CityBatchRecord(
        batch_id=int(row.id),
        city_id=int(row.city_id),
        canonical_name=row.canonical_name,
        trigger_source=row.trigger_source,
        reason=row.reason,
        limit_per_keyword=int(row.limit_per_keyword),
        status=row.status,
        extract_status=row.extract_status,
        poi_resolve_status=getattr(row, "poi_resolve_status", "PENDING"),
        refresh_status=row.refresh_status,
        quality_status=row.quality_status,
        heartbeat_time=row.heartbeat_time,
        started_time=row.started_time,
        finished_time=row.finished_time,
        error_code=row.error_code,
        error_message=row.error_message,
        items=items,
    )


async def get_city_batch(batch_id: int) -> CityBatchRecord | None:
    async with get_session_factory()() as session:
        batch_row = (await session.execute(text("""
            SELECT batch.*, city.canonical_name
            FROM travel_city_crawl_batch AS batch
            JOIN travel_city AS city ON city.id = batch.city_id
            WHERE batch.id = :batch_id
        """), {"batch_id": batch_id})).one_or_none()
        if batch_row is None:
            return None
        item_rows = (await session.execute(text("""
            SELECT *
            FROM travel_city_crawl_batch_item
            WHERE batch_id = :batch_id
            ORDER BY id
        """), {"batch_id": batch_id})).all()
    return _row_to_batch(batch_row, [_row_to_item(row) for row in item_rows])


async def list_city_batches(
    *,
    city_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[CityBatchRecord]:
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    if offset < 0:
        raise ValueError("offset must be >= 0")
    params: dict[str, object] = {"limit": limit, "offset": offset}
    city_filter = ""
    if city_id is not None:
        city_filter = "WHERE batch.city_id = :city_id"
        params["city_id"] = city_id

    async with get_session_factory()() as session:
        batch_rows = (await session.execute(text(f"""
            SELECT batch.*, city.canonical_name
            FROM travel_city_crawl_batch AS batch
            JOIN travel_city AS city ON city.id = batch.city_id
            {city_filter}
            ORDER BY batch.created_time DESC, batch.id DESC
            LIMIT :limit OFFSET :offset
        """), params)).all()
        batch_ids = [int(row.id) for row in batch_rows]
        items_by_batch: dict[int, list[CityBatchItemRecord]] = {batch_id: [] for batch_id in batch_ids}
        if batch_ids:
            item_rows = (await session.execute(text("""
                SELECT *
                FROM travel_city_crawl_batch_item
                WHERE batch_id = ANY(CAST(:batch_ids AS bigint[]))
                ORDER BY batch_id, id
            """), {"batch_ids": batch_ids})).all()
            for row in item_rows:
                items_by_batch[int(row.batch_id)].append(_row_to_item(row))

    return [
        _row_to_batch(row, items_by_batch.get(int(row.id), []))
        for row in batch_rows
    ]


async def get_active_city_batch() -> CityBatchRecord | None:
    async with get_session_factory()() as session:
        row = (await session.execute(text("""
            SELECT batch.*, city.canonical_name
            FROM travel_city_crawl_batch AS batch
            JOIN travel_city AS city ON city.id = batch.city_id
            WHERE batch.status IN ('PENDING', 'RUNNING')
            ORDER BY batch.created_time ASC
            LIMIT 1
        """))).one_or_none()
    if row is None:
        return None
    return await get_city_batch(int(row.id))


async def create_city_crawl_batch(
    *,
    city_id: int,
    trigger_source: str,
    reason: str,
    preferences: list[str] | None = None,
    limit_per_keyword: int = 20,
) -> CityBatchRecord:
    if limit_per_keyword < 1 or limit_per_keyword > 50:
        raise ValueError("limit_per_keyword must be between 1 and 50")
    async with get_session_factory()() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": CITY_BATCH_CLAIM_LOCK_ID},
        )
        city_row = (await session.execute(text("""
            SELECT id, canonical_name
            FROM travel_city
            WHERE id = :city_id
            FOR UPDATE
        """), {"city_id": city_id})).one()
        active = (await session.execute(text("""
            SELECT id
            FROM travel_city_crawl_batch
            WHERE status IN ('PENDING', 'RUNNING')
            ORDER BY created_time ASC
            LIMIT 1
        """))).one_or_none()
        if active is not None:
            raise CityBatchActiveError(f"active city batch exists: {active.id}")

        try:
            batch_row = (await session.execute(text("""
                INSERT INTO travel_city_crawl_batch (
                    city_id, trigger_source, reason, limit_per_keyword, status,
                    extract_status, poi_resolve_status, refresh_status, quality_status
                ) VALUES (
                    :city_id, :trigger_source, :reason, :limit_per_keyword, 'PENDING',
                    'PENDING', 'PENDING', 'PENDING', 'PENDING'
                )
                RETURNING *
            """), {
                "city_id": city_id,
                "trigger_source": trigger_source,
                "reason": reason,
                "limit_per_keyword": limit_per_keyword,
            })).one()
        except IntegrityError as exc:
            raise CityBatchActiveError("active city batch exists") from exc

        for keyword, keyword_type in city_batch_keywords(
            city_row.canonical_name,
            preferences=preferences,
        ):
            await session.execute(text("""
                INSERT INTO travel_city_crawl_batch_item (
                    batch_id, keyword, keyword_type, status
                ) VALUES (:batch_id, :keyword, :keyword_type, 'PENDING')
            """), {
                "batch_id": batch_row.id,
                "keyword": keyword,
                "keyword_type": keyword_type,
            })
        await session.commit()
    return (await get_city_batch(int(batch_row.id)))  # type: ignore[return-value]


async def create_retry_city_crawl_batch(
    *,
    failed_batch_id: int,
) -> CityBatchRecord:
    source = await get_city_batch(failed_batch_id)
    if source is None:
        raise ValueError("source batch not found")
    retry_keywords = [item for item in source.items if item.status != "SUCCESS"]
    postprocess_failed = any(
        status in {"FAILED", "TIMEOUT"}
        for status in (
            source.extract_status,
            source.poi_resolve_status,
            source.refresh_status,
            source.quality_status,
        )
    )
    postprocess_failed = postprocess_failed or source.status in {
        "FAILED",
        "TIMEOUT",
    }
    if not retry_keywords and not postprocess_failed:
        raise ValueError("source batch has no failed stage to retry")

    async with get_session_factory()() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": CITY_BATCH_CLAIM_LOCK_ID},
        )
        active = (await session.execute(text("""
            SELECT id
            FROM travel_city_crawl_batch
            WHERE status IN ('PENDING', 'RUNNING')
            ORDER BY created_time ASC
            LIMIT 1
        """))).one_or_none()
        if active is not None:
            raise CityBatchActiveError(f"active city batch exists: {active.id}")
        batch_row = (await session.execute(text("""
            INSERT INTO travel_city_crawl_batch (
                city_id, trigger_source, reason, limit_per_keyword, status,
                extract_status, poi_resolve_status, refresh_status, quality_status
            ) VALUES (
                :city_id, 'retry', :reason, :limit_per_keyword, 'PENDING',
                'PENDING', 'PENDING', 'PENDING', 'PENDING'
            )
            RETURNING *
        """), {
            "city_id": source.city_id,
            "reason": f"retry:{failed_batch_id}",
            "limit_per_keyword": source.limit_per_keyword,
        })).one()
        for item in source.items:
            item_status = "SUCCESS" if item.status == "SUCCESS" else "PENDING"
            await session.execute(text("""
                INSERT INTO travel_city_crawl_batch_item (
                    batch_id, keyword, keyword_type, status, crawl_run_id,
                    started_time, finished_time
                ) VALUES (
                    :batch_id, :keyword, :keyword_type, :status, :crawl_run_id,
                    :started_time, :finished_time
                )
            """), {
                "batch_id": batch_row.id,
                "keyword": item.keyword,
                "keyword_type": item.keyword_type,
                "status": item_status,
                "crawl_run_id": item.crawl_run_id if item_status == "SUCCESS" else None,
                "started_time": item.started_time,
                "finished_time": item.finished_time,
            })
        await session.commit()
    return (await get_city_batch(int(batch_row.id)))  # type: ignore[return-value]


async def select_cookie_expired_retry_candidate() -> CookieExpiredRetryCandidate | None:
    """Pick one city whose latest batch still failed because the Cookie expired."""
    async with get_session_factory()() as session:
        row = (await session.execute(text("""
            WITH latest_batches AS (
                SELECT DISTINCT ON (batch.city_id)
                    batch.id,
                    city.request_count_30d,
                    city.last_requested_time,
                    batch.finished_time
                FROM travel_city_crawl_batch AS batch
                JOIN travel_city AS city ON city.id = batch.city_id
                WHERE city.status <> 'DISABLED'
                ORDER BY
                    batch.city_id,
                    batch.created_time DESC,
                    batch.id DESC
            ),
            candidates AS (
                SELECT latest_batches.*
                FROM latest_batches
                JOIN travel_city_crawl_batch AS batch ON batch.id = latest_batches.id
                WHERE batch.status = 'COOKIE_EXPIRED'
            )
            SELECT id, COUNT(*) OVER()::int AS total_count
            FROM candidates
            ORDER BY
                request_count_30d DESC,
                last_requested_time DESC NULLS LAST,
                finished_time ASC NULLS LAST,
                id ASC
            LIMIT 1
        """))).one_or_none()
    if row is None:
        return None
    batch = await get_city_batch(int(row.id))
    if batch is None:
        return None
    return CookieExpiredRetryCandidate(
        batch=batch,
        total_count=int(row.total_count),
    )


async def claim_next_city_batch() -> int | None:
    async with get_session_factory()() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": CITY_BATCH_CLAIM_LOCK_ID},
        )
        running = (await session.execute(text("""
            SELECT COUNT(*)::int
            FROM travel_city_crawl_batch
            WHERE status = 'RUNNING'
        """))).scalar_one()
        if int(running) >= 1:
            return None
        row = (await session.execute(text("""
            SELECT id
            FROM travel_city_crawl_batch
            WHERE status = 'PENDING'
            ORDER BY created_time ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """))).one_or_none()
        if row is None:
            return None
        batch_id = int(row.id)
        await session.execute(text("""
            UPDATE travel_city_crawl_batch
            SET status = 'RUNNING',
                started_time = COALESCE(started_time, NOW()),
                heartbeat_time = NOW()
            WHERE id = :batch_id
        """), {"batch_id": batch_id})
        await session.commit()
    return batch_id


async def heartbeat_city_batch(batch_id: int) -> None:
    async with get_session_factory()() as session:
        await session.execute(text("""
            UPDATE travel_city_crawl_batch
            SET heartbeat_time = NOW()
            WHERE id = :batch_id AND status = 'RUNNING'
        """), {"batch_id": batch_id})
        await session.commit()


async def mark_city_batch_item_running(item_id: int, crawl_run_id: int) -> None:
    async with get_session_factory()() as session:
        await session.execute(text("""
            UPDATE travel_city_crawl_batch_item
            SET status = 'RUNNING',
                crawl_run_id = :crawl_run_id,
                started_time = COALESCE(started_time, NOW())
            WHERE id = :item_id
        """), {"item_id": item_id, "crawl_run_id": crawl_run_id})
        await session.commit()


async def mark_city_batch_item_finished(
    item_id: int,
    *,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    async with get_session_factory()() as session:
        await session.execute(text("""
            UPDATE travel_city_crawl_batch_item
            SET status = :status,
                error_code = :error_code,
                error_message = :error_message,
                finished_time = NOW()
            WHERE id = :item_id
        """), {
            "item_id": item_id,
            "status": status,
            "error_code": error_code,
            "error_message": error_message,
        })
        await session.commit()


async def update_city_batch_stage(
    batch_id: int,
    stage: str,
    status: str,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    if stage not in {"extract", "poi_resolve", "refresh", "quality"}:
        raise ValueError("stage must be extract, poi_resolve, refresh, or quality")
    column = f"{stage}_status"
    async with get_session_factory()() as session:
        await session.execute(text(f"""
            UPDATE travel_city_crawl_batch
            SET {column} = :status,
                error_code = COALESCE(:error_code, error_code),
                error_message = COALESCE(:error_message, error_message),
                heartbeat_time = CASE WHEN status = 'RUNNING' THEN NOW() ELSE heartbeat_time END
            WHERE id = :batch_id
        """), {
            "batch_id": batch_id,
            "status": status,
            "error_code": error_code,
            "error_message": error_message,
        })
        await session.commit()


async def finish_city_batch(
    batch_id: int,
    *,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    async with get_session_factory()() as session:
        await session.execute(text("""
            UPDATE travel_city_crawl_batch
            SET status = :status,
                error_code = :error_code,
                error_message = :error_message,
                finished_time = NOW()
            WHERE id = :batch_id
        """), {
            "batch_id": batch_id,
            "status": status,
            "error_code": error_code,
            "error_message": error_message,
        })
        await session.commit()


async def expire_stale_city_batches(*, timeout_seconds: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
    async with get_session_factory()() as session:
        batch_rows = (await session.execute(text("""
            UPDATE travel_city_crawl_batch
            SET status = 'TIMEOUT',
                error_code = 'TIMEOUT',
                error_message = 'city batch heartbeat timed out',
                finished_time = NOW()
            WHERE status = 'RUNNING'
              AND COALESCE(heartbeat_time, started_time, created_time) < :cutoff
            RETURNING id
        """), {"cutoff": cutoff})).all()
        batch_ids = [int(row.id) for row in batch_rows]
        if batch_ids:
            await session.execute(text("""
                UPDATE travel_city_crawl_batch_item
                SET status = 'TIMEOUT',
                    error_code = 'TIMEOUT',
                    error_message = 'city batch heartbeat timed out',
                    finished_time = NOW()
                WHERE batch_id = ANY(CAST(:batch_ids AS bigint[]))
                  AND status IN ('PENDING', 'RUNNING')
            """), {"batch_ids": batch_ids})
        await session.commit()
    return len(batch_ids)


async def mark_city_refresh_completed(city_id: int) -> None:
    async with get_session_factory()() as session:
        await session.execute(text("""
            UPDATE travel_city
            SET last_refresh_time = NOW(),
                next_refresh_time = NOW() + CASE
                    WHEN request_count_30d >= 20 THEN INTERVAL '3 days'
                    WHEN request_count_30d >= 5 THEN INTERVAL '7 days'
                    WHEN request_count_30d >= 1 THEN INTERVAL '15 days'
                    ELSE INTERVAL '30 days'
                END
            WHERE id = :city_id
        """), {"city_id": city_id})
        await session.commit()
