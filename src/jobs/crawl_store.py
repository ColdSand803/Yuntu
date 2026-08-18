"""Persistence and queries for travel_crawl_run / travel_crawl_run_step."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from src.pipeline.db import get_session_factory

logger = logging.getLogger(__name__)

STEP_NAMES = ("CRAWL", "EXTRACT", "POI_RESOLVE", "REFRESH_SUMMARY")
TERMINAL_STATUSES = frozenset({
    "SUCCESS", "FAILED", "COOKIE_EXPIRED", "PARTIAL_SUCCESS", "TIMEOUT",
})
CRAWL_CLAIM_LOCK_ID = 2026052402


@dataclass(frozen=True)
class CrawlRunStepRecord:
    step_name: str
    status: str
    raw_count: int
    insert_count: int
    duplicate_count: int
    failed_count: int
    error_code: str | None
    error_message: str | None
    started_time: datetime | None
    finished_time: datetime | None


@dataclass(frozen=True)
class CrawlRunRecord:
    run_id: int
    platform: str
    city: str | None
    keyword: str | None
    status: str
    run_extract: bool
    refresh_summary: bool
    raw_count: int
    insert_count: int
    duplicate_count: int
    failed_count: int
    error_code: str | None
    error_message: str | None
    started_time: datetime | None
    finished_time: datetime | None
    steps: list[CrawlRunStepRecord]


def _row_to_step(row) -> CrawlRunStepRecord:
    return CrawlRunStepRecord(
        step_name=row.step_name,
        status=row.status,
        raw_count=row.raw_count,
        insert_count=row.insert_count,
        duplicate_count=row.duplicate_count,
        failed_count=row.failed_count,
        error_code=row.error_code,
        error_message=row.error_message,
        started_time=row.started_time,
        finished_time=row.finished_time,
    )


@dataclass(frozen=True)
class CrawlInventoryKeyword:
    keyword: str
    raw_count: int
    parsed_count: int
    pending_count: int
    failed_count: int
    latest_raw_time: datetime | None
    latest_success_run_id: int | None
    latest_success_time: datetime | None


@dataclass(frozen=True)
class CrawlInventoryCity:
    city: str
    raw_count: int
    parsed_count: int
    pending_count: int
    failed_count: int
    summary_count: int
    latest_success_run_id: int | None
    latest_success_keyword: str | None
    latest_success_time: datetime | None
    keywords: list[CrawlInventoryKeyword] = field(default_factory=list)


async def get_crawl_inventory(city_filter: str | None = None) -> list[CrawlInventoryCity]:
    """Return per-city (and per-keyword) data inventory summary.

    Queries travel_raw_item for parse stats, travel_place_summary for summary
    counts, and travel_crawl_run for the latest successful run metadata.
    SQL clause for city is always parameterized; no user input is interpolated
    into the query string.
    """
    params: dict = {}
    city_clause = ""
    if city_filter is not None:
        city_clause = "AND city = :city"
        params["city"] = city_filter

    factory = get_session_factory()
    async with factory() as session:
        raw_rows = (await session.execute(text(f"""
            SELECT city,
                   COUNT(*)                                          AS raw_count,
                   COUNT(*) FILTER (WHERE parse_status = 'PARSED')  AS parsed_count,
                   COUNT(*) FILTER (WHERE parse_status = 'PENDING') AS pending_count,
                   COUNT(*) FILTER (WHERE parse_status = 'FAILED')  AS failed_count,
                   MAX(created_time)                                 AS latest_raw_time
            FROM travel_raw_item
            WHERE city IS NOT NULL {city_clause}
            GROUP BY city
        """), params)).fetchall()

        summary_rows = (await session.execute(text(f"""
            SELECT city, COUNT(*) AS summary_count
            FROM travel_place_summary
            WHERE city IS NOT NULL {city_clause}
            GROUP BY city
        """), params)).fetchall()

        city_run_rows = (await session.execute(text(f"""
            SELECT DISTINCT ON (city) id AS run_id, city, keyword, finished_time
            FROM travel_crawl_run
            WHERE status = 'SUCCESS' AND city IS NOT NULL {city_clause}
            ORDER BY city, finished_time DESC NULLS LAST
        """), params)).fetchall()

        kw_raw_rows = (await session.execute(text(f"""
            SELECT city, keyword,
                   COUNT(*)                                          AS raw_count,
                   COUNT(*) FILTER (WHERE parse_status = 'PARSED')  AS parsed_count,
                   COUNT(*) FILTER (WHERE parse_status = 'PENDING') AS pending_count,
                   COUNT(*) FILTER (WHERE parse_status = 'FAILED')  AS failed_count,
                   MAX(created_time)                                 AS latest_raw_time
            FROM travel_raw_item
            WHERE city IS NOT NULL AND keyword IS NOT NULL {city_clause}
            GROUP BY city, keyword
        """), params)).fetchall()

        kw_run_rows = (await session.execute(text(f"""
            SELECT DISTINCT ON (city, keyword) id AS run_id, city, keyword, finished_time
            FROM travel_crawl_run
            WHERE status = 'SUCCESS'
              AND city IS NOT NULL AND keyword IS NOT NULL {city_clause}
            ORDER BY city, keyword, finished_time DESC NULLS LAST
        """), params)).fetchall()

    city_summary = {r.city: int(r.summary_count) for r in summary_rows}
    city_run = {r.city: r for r in city_run_rows}
    kw_raw: dict[str, list] = {}
    for r in kw_raw_rows:
        kw_raw.setdefault(r.city, []).append(r)
    kw_run = {(r.city, r.keyword): r for r in kw_run_rows}

    result: list[CrawlInventoryCity] = []
    for raw_row in sorted(raw_rows, key=lambda r: r.city):
        city = raw_row.city
        run_row = city_run.get(city)
        keywords = []
        for kw_row in sorted(kw_raw.get(city, []), key=lambda r: r.keyword):
            kw_r = kw_run.get((city, kw_row.keyword))
            keywords.append(CrawlInventoryKeyword(
                keyword=kw_row.keyword,
                raw_count=int(kw_row.raw_count),
                parsed_count=int(kw_row.parsed_count),
                pending_count=int(kw_row.pending_count),
                failed_count=int(kw_row.failed_count),
                latest_raw_time=kw_row.latest_raw_time,
                latest_success_run_id=int(kw_r.run_id) if kw_r else None,
                latest_success_time=kw_r.finished_time if kw_r else None,
            ))
        result.append(CrawlInventoryCity(
            city=city,
            raw_count=int(raw_row.raw_count),
            parsed_count=int(raw_row.parsed_count),
            pending_count=int(raw_row.pending_count),
            failed_count=int(raw_row.failed_count),
            summary_count=city_summary.get(city, 0),
            latest_success_run_id=int(run_row.run_id) if run_row else None,
            latest_success_keyword=run_row.keyword if run_row else None,
            latest_success_time=run_row.finished_time if run_row else None,
            keywords=keywords,
        ))
    return result


@dataclass(frozen=True)
class ActiveRunResult:
    found: bool
    run_id: int | None
    status: str | None


async def get_active_duplicate_run(city: str, keyword: str) -> ActiveRunResult:
    """Return the earliest PENDING/RUNNING run for city+keyword, if any.

    This check is not bypassable by force — a task already in the queue
    should not be duplicated regardless of caller intent.
    """
    factory = get_session_factory()
    async with factory() as session:
        row = (await session.execute(text("""
            SELECT id AS run_id, status
            FROM travel_crawl_run
            WHERE city = :city AND keyword = :keyword
              AND status IN ('PENDING', 'RUNNING')
            ORDER BY created_time ASC
            LIMIT 1
        """), {"city": city, "keyword": keyword})).one_or_none()

    if row is None:
        return ActiveRunResult(found=False, run_id=None, status=None)
    return ActiveRunResult(found=True, run_id=int(row.run_id), status=row.status)


@dataclass(frozen=True)
class DuplicateInventoryResult:
    found: bool
    raw_count: int
    parsed_count: int
    pending_count: int
    failed_count: int
    summary_count: int
    latest_success_run_id: int | None
    latest_success_time: datetime | None
    latest_raw_time: datetime | None


async def get_recent_duplicate_inventory(
    city: str, keyword: str, recent_hours: int
) -> DuplicateInventoryResult:
    """Check whether city+keyword has recent crawl data within recent_hours.

    Primary check: travel_crawl_run with status='SUCCESS' within the window.
    Fallback check: travel_raw_item rows created within the window.
    Total stats (raw_count etc.) are NOT time-filtered — they reflect all
    existing inventory for the city+keyword pair.
    All user inputs are passed as SQL bound parameters.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=recent_hours)
    params_ck: dict = {"city": city, "keyword": keyword, "cutoff": cutoff}
    params_base: dict = {"city": city, "keyword": keyword}

    factory = get_session_factory()
    async with factory() as session:
        # Primary: recent SUCCESS run
        run_row = (await session.execute(text("""
            SELECT id AS run_id, finished_time
            FROM travel_crawl_run
            WHERE city = :city AND keyword = :keyword
              AND status = 'SUCCESS'
              AND finished_time >= :cutoff
            ORDER BY finished_time DESC NULLS LAST
            LIMIT 1
        """), params_ck)).one_or_none()

        found = run_row is not None
        latest_success_run_id = int(run_row.run_id) if run_row else None
        latest_success_time = run_row.finished_time if run_row else None

        # Fallback: recent raw items
        if not found:
            raw_check = (await session.execute(text("""
                SELECT COUNT(*) AS cnt
                FROM travel_raw_item
                WHERE city = :city AND keyword = :keyword
                  AND created_time >= :cutoff
            """), params_ck)).one()
            found = int(raw_check.cnt) > 0

        # Total stats (not time-filtered) for 409 inventory payload
        stats_row = (await session.execute(text("""
            SELECT COUNT(*)                                          AS raw_count,
                   COUNT(*) FILTER (WHERE parse_status = 'PARSED')  AS parsed_count,
                   COUNT(*) FILTER (WHERE parse_status = 'PENDING') AS pending_count,
                   COUNT(*) FILTER (WHERE parse_status = 'FAILED')  AS failed_count,
                   MAX(created_time)                                 AS latest_raw_time
            FROM travel_raw_item
            WHERE city = :city AND keyword = :keyword
        """), params_base)).one()

        summary_row = (await session.execute(text("""
            SELECT COUNT(*) AS summary_count
            FROM travel_place_summary
            WHERE city = :city
        """), {"city": city})).one()

    return DuplicateInventoryResult(
        found=found,
        raw_count=int(stats_row.raw_count),
        parsed_count=int(stats_row.parsed_count),
        pending_count=int(stats_row.pending_count),
        failed_count=int(stats_row.failed_count),
        summary_count=int(summary_row.summary_count),
        latest_success_run_id=latest_success_run_id,
        latest_success_time=latest_success_time,
        latest_raw_time=stats_row.latest_raw_time,
    )


async def get_crawl_run(run_id: int) -> CrawlRunRecord | None:
    factory = get_session_factory()
    async with factory() as session:
        run_result = await session.execute(
            text("""
                SELECT id, platform, city, keyword, status, run_extract, refresh_summary,
                       raw_count, insert_count, duplicate_count, failed_count,
                       error_code, error_message, started_time, finished_time
                FROM travel_crawl_run
                WHERE id = :run_id
            """),
            {"run_id": run_id},
        )
        run_row = run_result.one_or_none()
        if run_row is None:
            return None

        step_result = await session.execute(
            text("""
                SELECT step_name, status, raw_count, insert_count, duplicate_count,
                       failed_count, error_code, error_message, started_time, finished_time
                FROM travel_crawl_run_step
                WHERE run_id = :run_id
                ORDER BY CASE step_name
                    WHEN 'CRAWL' THEN 1
                    WHEN 'EXTRACT' THEN 2
                    WHEN 'POI_RESOLVE' THEN 3
                    WHEN 'REFRESH_SUMMARY' THEN 4
                    ELSE 99
                END
            """),
            {"run_id": run_id},
        )
        steps = [_row_to_step(row) for row in step_result.fetchall()]

    return CrawlRunRecord(
        run_id=run_row.id,
        platform=run_row.platform,
        city=run_row.city,
        keyword=run_row.keyword,
        status=run_row.status,
        run_extract=run_row.run_extract,
        refresh_summary=run_row.refresh_summary,
        raw_count=run_row.raw_count,
        insert_count=run_row.insert_count,
        duplicate_count=run_row.duplicate_count,
        failed_count=run_row.failed_count,
        error_code=run_row.error_code,
        error_message=run_row.error_message,
        started_time=run_row.started_time,
        finished_time=run_row.finished_time,
        steps=steps,
    )


async def create_crawl_run(
    *,
    city: str,
    keyword: str,
    limit: int,
    run_extract: bool,
    refresh_summary: bool,
    trigger_source: str,
) -> int:
    factory = get_session_factory()
    async with factory() as session:
        run_result = await session.execute(
            text("""
                INSERT INTO travel_crawl_run (
                    platform, city, keyword, limit_count, trigger_source,
                    status, run_extract, refresh_summary
                ) VALUES (
                    'xhs', :city, :keyword, :limit_count, :trigger_source,
                    'PENDING', :run_extract, :refresh_summary
                )
                RETURNING id
            """),
            {
                "city": city,
                "keyword": keyword,
                "limit_count": limit,
                "trigger_source": trigger_source,
                "run_extract": run_extract,
                "refresh_summary": refresh_summary,
            },
        )
        run_id = int(run_result.scalar_one())

        step_specs = [
            ("CRAWL", "PENDING"),
            ("EXTRACT", "PENDING" if run_extract else "SKIPPED"),
            ("POI_RESOLVE", "PENDING" if run_extract else "SKIPPED"),
            ("REFRESH_SUMMARY", "PENDING" if refresh_summary else "SKIPPED"),
        ]
        for step_name, status in step_specs:
            await session.execute(
                text("""
                    INSERT INTO travel_crawl_run_step (run_id, step_name, status)
                    VALUES (:run_id, :step_name, :status)
                """),
                {"run_id": run_id, "step_name": step_name, "status": status},
            )
        await session.commit()
    return run_id


async def claim_next_crawl_run() -> int | None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": CRAWL_CLAIM_LOCK_ID},
        )

        running = await session.execute(
            text("SELECT COUNT(*)::int FROM travel_crawl_run WHERE status = 'RUNNING'"),
        )
        if int(running.scalar_one()) >= 1:
            return None

        pick = await session.execute(
            text("""
                SELECT id
                FROM travel_crawl_run
                WHERE status = 'PENDING'
                ORDER BY created_time ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """),
        )
        row = pick.first()
        if row is None:
            return None

        run_id = int(row.id)
        await session.execute(
            text("""
                UPDATE travel_crawl_run
                SET status = 'RUNNING',
                    started_time = COALESCE(started_time, NOW())
                WHERE id = :run_id
            """),
            {"run_id": run_id},
        )
        await session.commit()
    return run_id


async def mark_step_running(run_id: int, step_name: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("""
                UPDATE travel_crawl_run_step
                SET status = 'RUNNING',
                    started_time = COALESCE(started_time, NOW())
                WHERE run_id = :run_id AND step_name = :step_name
            """),
            {"run_id": run_id, "step_name": step_name},
        )
        await session.commit()


async def mark_step_finished(
    run_id: int,
    step_name: str,
    *,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
    stdout_summary: str | None = None,
    stderr_summary: str | None = None,
    metrics: "StepMetrics | None" = None,
) -> None:
    from src.jobs.crawl_metrics import StepMetrics

    if metrics is None:
        metrics = StepMetrics()

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("""
                UPDATE travel_crawl_run_step
                SET status = :status,
                    error_code = :error_code,
                    error_message = :error_message,
                    stdout_summary = :stdout_summary,
                    stderr_summary = :stderr_summary,
                    raw_count = :raw_count,
                    insert_count = :insert_count,
                    duplicate_count = :duplicate_count,
                    failed_count = :failed_count,
                    finished_time = NOW()
                WHERE run_id = :run_id AND step_name = :step_name
            """),
            {
                "run_id": run_id,
                "step_name": step_name,
                "status": status,
                "error_code": error_code,
                "error_message": error_message,
                "stdout_summary": stdout_summary,
                "stderr_summary": stderr_summary,
                "raw_count": metrics.raw_count,
                "insert_count": metrics.insert_count,
                "duplicate_count": metrics.duplicate_count,
                "failed_count": metrics.failed_count,
            },
        )
        await session.commit()


async def finalize_crawl_run(run_id: int) -> None:
    run = await get_crawl_run(run_id)
    if run is None:
        return

    status = _aggregate_run_status(run)
    error_code = None
    error_message = None
    if status in {"FAILED", "COOKIE_EXPIRED", "PARTIAL_SUCCESS", "TIMEOUT"}:
        for step in run.steps:
            if step.error_code:
                error_code = step.error_code
                error_message = step.error_message
                break

    raw_count, insert_count, duplicate_count, failed_count = _rollup_run_counts(run)

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("""
                UPDATE travel_crawl_run
                SET status = :status,
                    error_code = :error_code,
                    error_message = :error_message,
                    raw_count = :raw_count,
                    insert_count = :insert_count,
                    duplicate_count = :duplicate_count,
                    failed_count = :failed_count,
                    finished_time = NOW()
                WHERE id = :run_id
            """),
            {
                "run_id": run_id,
                "status": status,
                "error_code": error_code,
                "error_message": error_message,
                "raw_count": raw_count,
                "insert_count": insert_count,
                "duplicate_count": duplicate_count,
                "failed_count": failed_count,
            },
        )
        await session.commit()


def _aggregate_run_status(run: CrawlRunRecord) -> str:
    by_name = {step.step_name: step for step in run.steps}
    crawl = by_name.get("CRAWL")
    extract = by_name.get("EXTRACT")
    poi_resolve = by_name.get("POI_RESOLVE")
    refresh = by_name.get("REFRESH_SUMMARY")

    if crawl and crawl.error_code == "COOKIE_EXPIRED":
        return "COOKIE_EXPIRED"
    if crawl and crawl.status == "TIMEOUT":
        return "TIMEOUT"
    if crawl and crawl.status == "FAILED":
        return "FAILED"

    optional_failed = False
    for step in (extract, poi_resolve, refresh):
        if step is None or step.status == "SKIPPED":
            continue
        if step.status in {"FAILED", "TIMEOUT"}:
            optional_failed = True

    if optional_failed:
        return "PARTIAL_SUCCESS"

    return "SUCCESS"


def _rollup_run_counts(run: CrawlRunRecord) -> tuple[int, int, int, int]:
    by_name = {step.step_name: step for step in run.steps}
    crawl = by_name.get("CRAWL")
    extract = by_name.get("EXTRACT")
    poi_resolve = by_name.get("POI_RESOLVE")
    refresh = by_name.get("REFRESH_SUMMARY")

    raw_count = crawl.raw_count if crawl else 0
    insert_count = crawl.insert_count if crawl else 0
    duplicate_count = crawl.duplicate_count if crawl else 0
    failed_count = sum(step.failed_count for step in run.steps)

    if extract and extract.status not in {"SKIPPED", "PENDING", "RUNNING"}:
        insert_count = max(insert_count, extract.insert_count)
        raw_count = max(raw_count, extract.raw_count)
    if poi_resolve and poi_resolve.status not in {"SKIPPED", "PENDING", "RUNNING"}:
        insert_count = max(insert_count, poi_resolve.insert_count)
        raw_count = max(raw_count, poi_resolve.raw_count)
    if refresh and refresh.status not in {"SKIPPED", "PENDING", "RUNNING"}:
        insert_count = max(insert_count, refresh.insert_count)

    return raw_count, insert_count, duplicate_count, failed_count


async def abort_crawl_run(
    run_id: int,
    *,
    step_name: str | None,
    error_code: str,
    error_message: str,
    step_status: str = "FAILED",
) -> None:
    if step_name:
        await mark_step_finished(
            run_id,
            step_name,
            status=step_status,
            error_code=error_code,
            error_message=error_message,
        )

    run = await get_crawl_run(run_id)
    if run is None:
        return

    raw_count, insert_count, duplicate_count, failed_count = _rollup_run_counts(run)
    status = "TIMEOUT" if step_status == "TIMEOUT" else "FAILED"

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("""
                UPDATE travel_crawl_run
                SET status = :status,
                    error_code = :error_code,
                    error_message = :error_message,
                    raw_count = :raw_count,
                    insert_count = :insert_count,
                    duplicate_count = :duplicate_count,
                    failed_count = :failed_count,
                    finished_time = NOW()
                WHERE id = :run_id
            """),
            {
                "run_id": run_id,
                "status": status,
                "error_code": error_code,
                "error_message": error_message,
                "raw_count": raw_count,
                "insert_count": insert_count,
                "duplicate_count": duplicate_count,
                "failed_count": failed_count,
            },
        )
        await session.commit()
