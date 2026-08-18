"""Persistence and queries for travel_trip_job (async trip planning)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.jobs.projection_outbox import (
    close_all_running_steps,
    emit_trip_projection_commit,
    finish_latest_running_step,
    insert_trip_step,
)
from src.pipeline.db import get_session_factory

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = frozenset({"SUCCESS", "FAILED", "TIMEOUT", "REJECTED"})
READ_RETRIES = 3

STAGE_USER_MESSAGES: dict[str, str] = {
    "PENDING": "已收到请求，正在排队规划",
    "INTENT_PARSER": "正在理解你的旅行需求",
    "DATA_RETRIEVAL": "正在检索地点数据",
    "SEMANTIC_GROUPING": "正在整理候选方案",
    "ROUTE_PLANNING": "正在优化每日路线",
    "FINAL_WRITER": "正在生成攻略",
    "HERMES_REVIEW": "正在审核攻略内容",
    "QUALITY_REVIEW": "正在审核攻略内容",
    "REVIEW_TAXONOMY": "正在归类攻略质量问题",
    "WRITER_REPAIR": "正在修复可修复的攻略问题",
    "REVIEW_TAXONOMY_AFTER_REPAIR": "正在复核修复后的攻略",
    "PUBLISH_RETRY": "正在重新生成一版更稳的攻略",
    "PERSISTING": "正在保存结果",
    "SUCCESS": "攻略已完成",
    "FAILED": "这次规划失败了，可以稍后再试一次",
    "TIMEOUT": "这次规划超时了，可以稍后再试一次",
}

NO_CANDIDATES_USER_MESSAGE = "暂时没有找到足够的真实地点数据"
NO_USABLE_ROUTE_USER_MESSAGE = "现有地点无法组成合规路线，请调整需求后重试"
REJECTED_USER_MESSAGES = {
    "CITY_CLARIFICATION_REQUIRED": (
        "我还差一个关键信息：你想去哪个城市？"
        "可以直接发“成都3天美食”或“重庆3天打卡”，"
        "我再继续帮你规划。"
    ),
    "CITY_PREPARING": (
        "这座城市的数据正在准备中，预计很快支持。"
        "你可以稍后再试，或先体验重庆等已开通城市。"
    ),
    "CITY_DATA_INSUFFICIENT": (
        "这座城市的数据还在完善中，暂时无法生成高品质攻略。"
        "你可以稍后再试，或先试试其他热门城市。"
    ),
    "CITY_COLLECTION_FAILED": (
        "这座城市的数据暂不可用，我们正在跟进。"
        "你可以稍后再试，或先体验其他已开通城市。"
    ),
    "CITY_DISABLED": (
        "这座城市暂时不在服务范围内，我们会持续扩大覆盖。"
    ),
}


async def _lock_conversation(session, *, source: str, conversation_id: str) -> None:
    """Serialize current-recommendation transitions for one conversation."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {
            "lock_key": json.dumps(
                [source, conversation_id],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    )


class RequestIdConflictError(Exception):
    """Same request_id with a different message."""


@dataclass(frozen=True)
class TripJobRecord:
    job_id: str
    request_id: str
    source: str
    conversation_id: str
    user_query: str
    status: str
    current_stage: str
    result_type: str | None
    trip_request_json: dict | None
    result_record_id: int | None
    reply_text: str | None
    plan_count: int | None
    error_message: str | None
    error_code: str | None
    created_time: datetime
    started_time: datetime | None
    finished_time: datetime | None
    updated_time: datetime
    user_display_name: str | None = None


@dataclass(frozen=True)
class AsyncTripJobCreateResult:
    job_id: str
    status: str
    current_stage: str
    queue_position: int
    message: str
    cached: bool


def _normalize_message(message: str) -> str:
    return message.strip()


def _structured_trip_request_query(trip_request_json: dict) -> str:
    parts: list[str] = []
    for key in ("from_city", "to_city", "start_date", "end_date"):
        value = trip_request_json.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    for key, label in (("days", "days"), ("people_count", "people")):
        value = trip_request_json.get(key)
        if value not in (None, ""):
            parts.append(f"{label}:{value}")
    for key, label in (("preferences", "preferences"), ("avoid", "avoid")):
        value = trip_request_json.get(key)
        if isinstance(value, list) and value:
            parts.append(f"{label}:{','.join(str(item) for item in value)}")
    notes = trip_request_json.get("notes")
    if isinstance(notes, str) and notes.strip():
        parts.append(notes.strip())
    if parts:
        return " | ".join(parts)
    return json.dumps(trip_request_json, ensure_ascii=False, sort_keys=True)


def _effective_user_query(
    *,
    message: str | None,
    trip_request_json: dict | None,
) -> str:
    if trip_request_json is not None:
        return _structured_trip_request_query(trip_request_json)
    return _normalize_message(message or "")


def _normalized_query_hash(message: str) -> str:
    normalized = _normalize_message(message)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _row_to_record(row) -> TripJobRecord:
    trip_request_json = row.trip_request_json
    if isinstance(trip_request_json, str):
        import json

        trip_request_json = json.loads(trip_request_json) if trip_request_json else None

    return TripJobRecord(
        job_id=row.job_id,
        request_id=row.request_id,
        source=row.source,
        conversation_id=row.conversation_id,
        user_display_name=getattr(row, "user_display_name", None),
        user_query=row.user_query,
        status=row.status,
        current_stage=row.current_stage,
        result_type=row.result_type,
        trip_request_json=trip_request_json,
        result_record_id=row.result_record_id,
        reply_text=row.reply_text,
        plan_count=row.plan_count,
        error_message=row.error_message,
        error_code=row.error_code,
        created_time=row.created_time,
        started_time=row.started_time,
        finished_time=row.finished_time,
        updated_time=row.updated_time,
    )


def _coerce_place_ids(raw_place_ids) -> set[int]:
    """Normalize JSONB place IDs loaded from a historical plan record."""
    if isinstance(raw_place_ids, str):
        try:
            raw_place_ids = json.loads(raw_place_ids)
        except json.JSONDecodeError:
            return set()
    if not isinstance(raw_place_ids, list):
        return set()

    place_ids = set()
    for place_id in raw_place_ids:
        if isinstance(place_id, bool):
            continue
        try:
            place_ids.add(int(place_id))
        except (TypeError, ValueError):
            continue
    return place_ids


def user_message_for_job(job: TripJobRecord) -> str:
    if job.status == "REJECTED":
        return (
            job.error_message
            or REJECTED_USER_MESSAGES.get(job.error_code or "")
            or "该城市暂不支持规划，请稍后再试"
        )
    if job.status == "SUCCESS" and job.result_type == "NO_CANDIDATES":
        return NO_CANDIDATES_USER_MESSAGE
    if job.status == "SUCCESS" and job.result_type == "NO_USABLE_ROUTE":
        return NO_USABLE_ROUTE_USER_MESSAGE
    if job.status == "FAILED" and job.error_message:
        return job.error_message
    if job.status in STAGE_USER_MESSAGES:
        return STAGE_USER_MESSAGES[job.status]
    return STAGE_USER_MESSAGES.get(job.current_stage, "正在处理你的旅行规划")


def _elapsed_ms(start: datetime, end: datetime) -> int:
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    return max(0, int((end - start).total_seconds() * 1000))


def compute_queue_wait_ms(job: TripJobRecord) -> int:
    end = job.started_time or job.finished_time or datetime.now(timezone.utc)
    return _elapsed_ms(job.created_time, end)


def compute_run_elapsed_ms(job: TripJobRecord) -> int:
    if job.started_time is None:
        return 0
    end = job.finished_time or datetime.now(timezone.utc)
    return _elapsed_ms(job.started_time, end)


def compute_total_elapsed_ms(job: TripJobRecord) -> int:
    end = job.finished_time or datetime.now(timezone.utc)
    return _elapsed_ms(job.created_time, end)


def compute_elapsed_ms(job: TripJobRecord) -> int:
    if job.started_time is None:
        return compute_total_elapsed_ms(job)
    return compute_run_elapsed_ms(job)


async def get_trip_job_by_id(job_id: str) -> TripJobRecord | None:
    factory = get_session_factory()
    last_error: Exception | None = None
    for attempt in range(1, READ_RETRIES + 1):
        try:
            async with factory() as session:
                result = await session.execute(
                    text("""
                        SELECT job_id, request_id, source, conversation_id,
                               user_display_name, user_query,
                               status, current_stage, result_type, trip_request_json,
                               result_record_id, reply_text, plan_count, error_message, error_code,
                               created_time, started_time, finished_time, updated_time
                        FROM travel_trip_job
                        WHERE job_id = :job_id
                    """),
                    {"job_id": job_id},
                )
                row = result.one_or_none()
                if row is None:
                    return None
                return _row_to_record(row)
        except Exception as exc:
            last_error = exc
            if attempt >= READ_RETRIES:
                break
            logger.warning(
                "retry get_trip_job_by_id job_id=%s attempt=%s error=%s",
                job_id,
                attempt,
                exc,
            )
            await asyncio.sleep(0.2 * attempt)
    assert last_error is not None
    raise last_error


async def get_trip_job_by_request_id(request_id: str) -> TripJobRecord | None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("""
                SELECT job_id, request_id, source, conversation_id,
                       user_display_name, user_query,
                       status, current_stage, result_type, trip_request_json,
                       result_record_id, reply_text, plan_count, error_message, error_code,
                       created_time, started_time, finished_time, updated_time
                FROM travel_trip_job
                WHERE request_id = :request_id
            """),
            {"request_id": request_id},
        )
        row = result.one_or_none()
        if row is None:
            return None
        return _row_to_record(row)


async def get_trip_result_delivery_metadata(
    result_record_id: int | None,
) -> dict[str, str] | None:
    """Read authoritative delivery fields from the persisted result metrics."""
    if result_record_id is None:
        return None
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("""
                SELECT quality_metrics
                FROM travel_plan_record
                WHERE id = :result_record_id
            """),
            {"result_record_id": result_record_id},
        )
        row = result.one_or_none()
    if row is None:
        return None
    metrics = row.quality_metrics if isinstance(row.quality_metrics, dict) else {}
    variant = metrics.get("published_variant", "normal")
    status = metrics.get("delivery_status", "NORMAL")
    if variant not in {"normal", "safe"} or status not in {"NORMAL", "DEGRADED"}:
        return None
    if variant == "safe" and status != "DEGRADED":
        return None
    return {
        "published_variant": variant,
        "delivery_status": status,
    }


async def get_recent_successful_plan_place_ids(
    *,
    source: str,
    conversation_id: str,
    limit: int = 3,
) -> list[set[int]]:
    """Load recent reviewed PLAN_READY results for one async conversation."""
    factory = get_session_factory()
    async with factory() as session:
        rows = (await session.execute(
            text("""
                SELECT plan.used_place_ids
                FROM travel_trip_job AS job
                JOIN travel_plan_record AS plan
                  ON plan.id = job.result_record_id
                WHERE job.source = :source
                  AND job.conversation_id = :conversation_id
                  AND job.status = 'SUCCESS'
                  AND job.result_type = 'PLAN_READY'
                ORDER BY job.finished_time DESC NULLS LAST, job.created_time DESC
                LIMIT :limit
            """),
            {
                "source": source,
                "conversation_id": conversation_id,
                "limit": limit,
            },
        )).all()
    return [_coerce_place_ids(row.used_place_ids) for row in rows]


async def count_pending_jobs_before(job_id: str) -> int:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("""
                SELECT COUNT(*)::int
                FROM travel_trip_job AS ahead
                JOIN travel_trip_job AS current
                  ON current.job_id = :job_id
                WHERE ahead.status = 'PENDING'
                  AND ahead.created_time < current.created_time
            """),
            {"job_id": job_id},
        )
        return int(result.scalar_one())


async def queue_position_for_job(job: TripJobRecord) -> int:
    if job.status != "PENDING":
        return 0
    return await count_pending_jobs_before(job.job_id)


async def create_async_trip_job(
    *,
    message: str | None,
    trip_request_json: dict | None = None,
    request_field_provenance: dict[str, str] | None = None,
    request_user_supplied_json: dict | None = None,
    request_id: str,
    source: str,
    conversation_id: str,
    user_display_name: str | None = None,
) -> AsyncTripJobCreateResult:
    user_query = _effective_user_query(
        message=message,
        trip_request_json=trip_request_json,
    )
    if not user_query:
        raise ValueError("message or trip_request is required")
    if not request_id.strip():
        raise ValueError("request_id is required")
    if not source.strip():
        raise ValueError("source is required")
    if not conversation_id.strip():
        raise ValueError("conversation_id is required")
    display_name = (user_display_name or "").strip() or None
    if display_name is not None:
        display_name = display_name[:100]

    existing = await get_trip_job_by_request_id(request_id.strip())
    if existing is not None:
        if existing.user_query == user_query:
            queue_position = await queue_position_for_job(existing)
            return AsyncTripJobCreateResult(
                job_id=existing.job_id,
                status=existing.status,
                current_stage=existing.current_stage,
                queue_position=queue_position,
                message=user_message_for_job(existing),
                cached=True,
            )
        raise RequestIdConflictError(
            "request_id 已存在，但请求内容不一致",
        )

    job_id = uuid.uuid4().hex
    query_hash = _normalized_query_hash(user_query)
    factory = get_session_factory()

    try:
        async with factory() as session:
            await session.execute(
                text("""
                    INSERT INTO travel_trip_job (
                        job_id, request_id, source, conversation_id,
                        user_display_name, user_query,
                        normalized_query, normalized_query_hash,
                        trip_request_json, status, current_stage,
                        projection_version, trace_completeness,
                        guide_result_state, request_field_provenance,
                        request_user_supplied_json
                    ) VALUES (
                        :job_id, :request_id, :source, :conversation_id,
                        :user_display_name, :user_query,
                        :normalized_query, :normalized_query_hash,
                        CAST(:trip_request_json AS jsonb), 'PENDING', 'PENDING',
                        1, 'COMPLETE', 'NOT_APPLICABLE',
                        CAST(:request_field_provenance AS jsonb),
                        CAST(:request_user_supplied_json AS jsonb)
                    )
                """),
                {
                    "job_id": job_id,
                    "request_id": request_id.strip(),
                    "source": source.strip(),
                    "conversation_id": conversation_id.strip(),
                    "user_display_name": display_name,
                    "user_query": user_query,
                    "normalized_query": user_query,
                    "normalized_query_hash": query_hash,
                    "trip_request_json": (
                        json.dumps(trip_request_json, ensure_ascii=False)
                        if trip_request_json is not None
                        else None
                    ),
                    "request_field_provenance": json.dumps(
                        request_field_provenance or {},
                        ensure_ascii=False,
                    ),
                    "request_user_supplied_json": json.dumps(
                        request_user_supplied_json or {},
                        ensure_ascii=False,
                    ),
                },
            )
            await emit_trip_projection_commit(
                session,
                job_id=job_id,
                advance_job_version=False,
            )
            await session.commit()
    except IntegrityError:
        logger.info("request_id race on create, re-reading request_id=%s", request_id)
        raced = await get_trip_job_by_request_id(request_id.strip())
        if raced is None:
            raise
        if raced.user_query == user_query:
            queue_position = await queue_position_for_job(raced)
            return AsyncTripJobCreateResult(
                job_id=raced.job_id,
                status=raced.status,
                current_stage=raced.current_stage,
                queue_position=queue_position,
                message=user_message_for_job(raced),
                cached=True,
            )
        raise RequestIdConflictError(
            "request_id 已存在，但请求内容不一致",
        ) from None

    queue_position = await count_pending_jobs_before(job_id)
    return AsyncTripJobCreateResult(
        job_id=job_id,
        status="PENDING",
        current_stage="PENDING",
        queue_position=queue_position,
        message=STAGE_USER_MESSAGES["PENDING"],
        cached=False,
    )


async def count_running_trip_jobs() -> int:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("SELECT COUNT(*)::int FROM travel_trip_job WHERE status = 'RUNNING'"),
        )
        return int(result.scalar_one())


async def expire_stale_trip_jobs(*, timeout_seconds: int) -> int:
    """Mark worker jobs that exceeded the configured SLA as timed out."""
    factory = get_session_factory()
    async with factory() as session:
        stale_rows = await session.execute(
            text("""
                SELECT job_id
                FROM travel_trip_job
                WHERE status IN ('PENDING', 'RUNNING')
                  AND COALESCE(started_time, created_time)
                      < NOW() - make_interval(secs => :timeout_seconds)
                ORDER BY id ASC
                FOR UPDATE
            """),
            {"timeout_seconds": timeout_seconds},
        )
        job_ids = [str(row.job_id) for row in stale_rows]
        for job_id in job_ids:
            await session.execute(
                text("""
                    UPDATE travel_trip_job
                    SET status = 'TIMEOUT',
                        current_stage = 'TIMEOUT',
                        error_code = 'TIMEOUT',
                        error_message = '规划超时，请稍后重试',
                        finished_time = NOW()
                    WHERE job_id = :job_id
                """),
                {"job_id": job_id},
            )
            step_ids = await close_all_running_steps(
                session,
                job_id=job_id,
                status="TIMEOUT",
                metadata={"error": "trip job exceeded configured timeout"},
            )
            await emit_trip_projection_commit(
                session,
                job_id=job_id,
                changed_step_ids=step_ids,
            )
        await session.commit()
    return len(job_ids)


async def claim_next_pending_trip_job(*, max_concurrency: int) -> TripJobRecord | None:
    """Atomically claim one PENDING job if concurrency allows."""
    factory = get_session_factory()
    async with factory() as session:
        running = await session.execute(
            text("SELECT COUNT(*)::int FROM travel_trip_job WHERE status = 'RUNNING'"),
        )
        if int(running.scalar_one()) >= max_concurrency:
            return None

        pick = await session.execute(
            text("""
                SELECT j.job_id
                FROM travel_trip_job j
                WHERE j.status = 'PENDING'
                  AND NOT EXISTS (
                    SELECT 1
                    FROM travel_trip_job r
                    WHERE r.status = 'RUNNING'
                      AND r.source = j.source
                      AND r.conversation_id = j.conversation_id
                  )
                ORDER BY j.created_time ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """),
        )
        row = pick.first()
        if row is None:
            return None

        job_id = row.job_id
        update = await session.execute(
            text("""
                UPDATE travel_trip_job
                SET status = 'RUNNING',
                    current_stage = 'PENDING',
                    started_time = COALESCE(started_time, NOW())
                WHERE job_id = :job_id
            """),
            {"job_id": job_id},
        )
        if update.rowcount != 1:
            return None
        await emit_trip_projection_commit(session, job_id=job_id)
        await session.commit()

    return await get_trip_job_by_id(job_id)


async def update_trip_job_stage(job_id: str, stage: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("""
                UPDATE travel_trip_job
                SET current_stage = :stage
                WHERE job_id = :job_id
                  AND status = 'RUNNING'
            """),
            {"job_id": job_id, "stage": stage},
        )
        if result.rowcount:
            await emit_trip_projection_commit(session, job_id=job_id)
        await session.commit()


async def record_trip_job_stage_started(
    job_id: str,
    *,
    stage: str,
    attempt: int = 1,
    publish_retry_round: int = 0,
    metadata: dict | None = None,
    previous_success_event: dict | None = None,
) -> None:
    """Persist a stage boundary and one indivisible projection commit."""
    factory = get_session_factory()
    async with factory() as session:
        changed_step_ids: list[int] = []
        if previous_success_event:
            previous_id = await finish_latest_running_step(
                session,
                job_id=job_id,
                stage=str(previous_success_event.get("stage") or ""),
                status="SUCCESS",
                attempt=int(previous_success_event.get("attempt") or 1),
                publish_retry_round=int(
                    previous_success_event.get("publish_retry_round") or 0
                ),
                latency_ms=previous_success_event.get("latency_ms"),
                metadata=previous_success_event.get("metadata") or {},
            )
            if previous_id is None:
                previous_id = await insert_trip_step(
                    session,
                    job_id=job_id,
                    stage=str(previous_success_event.get("stage") or ""),
                    status="SUCCESS",
                    attempt=int(previous_success_event.get("attempt") or 1),
                    publish_retry_round=int(
                        previous_success_event.get("publish_retry_round") or 0
                    ),
                    latency_ms=previous_success_event.get("latency_ms"),
                    metadata=previous_success_event.get("metadata") or {},
                    finished=True,
                )
            changed_step_ids.append(previous_id)
        job_update = await session.execute(
            text("""
                UPDATE travel_trip_job
                SET current_stage = :stage
                WHERE job_id = :job_id
                  AND status = 'RUNNING'
            """),
            {"job_id": job_id, "stage": stage},
        )
        if not job_update.rowcount:
            raise RuntimeError("trip job is not RUNNING during stage transition")
        changed_step_ids.append(
            await insert_trip_step(
                session,
                job_id=job_id,
                stage=stage,
                status="RUNNING",
                attempt=attempt,
                publish_retry_round=publish_retry_round,
                metadata=metadata,
            )
        )
        await emit_trip_projection_commit(
            session,
            job_id=job_id,
            changed_step_ids=changed_step_ids,
        )
        await session.commit()


async def record_trip_job_step_event(
    job_id: str,
    *,
    stage: str,
    status: str,
    attempt: int = 1,
    publish_retry_round: int = 0,
    latency_ms: int | None = None,
    metadata: dict | None = None,
) -> None:
    """Persist one workflow step transition and its composite event."""
    factory = get_session_factory()
    async with factory() as session:
        step_id: int | None = None
        if status == "RUNNING":
            step_id = await insert_trip_step(
                session,
                job_id=job_id,
                stage=stage,
                status=status,
                attempt=attempt,
                publish_retry_round=publish_retry_round,
                latency_ms=latency_ms,
                metadata=metadata,
            )
        else:
            step_id = await finish_latest_running_step(
                session,
                job_id=job_id,
                stage=stage,
                status=status,
                attempt=attempt,
                publish_retry_round=publish_retry_round,
                latency_ms=latency_ms,
                metadata=metadata,
            )
            if step_id is None:
                step_id = await insert_trip_step(
                    session,
                    job_id=job_id,
                    stage=stage,
                    status=status,
                    attempt=attempt,
                    publish_retry_round=publish_retry_round,
                    latency_ms=latency_ms,
                    metadata=metadata,
                    finished=True,
                )
        await emit_trip_projection_commit(
            session,
            job_id=job_id,
            changed_step_ids=[step_id],
        )
        await session.commit()


async def close_running_trip_job_steps(
    job_id: str,
    *,
    status: str,
    metadata: dict | None = None,
) -> int:
    """Close RUNNING steps as one projection-relevant source transaction."""
    factory = get_session_factory()
    async with factory() as session:
        step_ids = await close_all_running_steps(
            session,
            job_id=job_id,
            status=status,
            metadata=metadata,
        )
        if step_ids:
            await emit_trip_projection_commit(
                session,
                job_id=job_id,
                changed_step_ids=step_ids,
            )
        await session.commit()
        return len(step_ids)


async def ensure_terminal_observation_step(
    job_id: str,
    *,
    status: str,
    metadata: dict | None = None,
) -> None:
    """Ensure a terminal observation step exists for timeout/cancel paths.

    If no RUNNING step was available to close, insert a finished PERSISTING step
    with event_type=OBSERVATION_FLUSH so full sanitized llm_observation is always
    durable. Stage value stays within the existing DB CHECK allowlist (no schema
    expansion in O4).
    """
    if status not in {"FAILED", "TIMEOUT"}:
        raise ValueError("terminal observation step status must be FAILED or TIMEOUT")
    factory = get_session_factory()
    meta = dict(metadata or {})
    meta.setdefault("event_type", "OBSERVATION_FLUSH")
    async with factory() as session:
        step_id = await insert_trip_step(
            session,
            job_id=job_id,
            stage="PERSISTING",
            status=status,
            latency_ms=0,
            metadata=meta,
            finished=True,
        )
        await emit_trip_projection_commit(
            session,
            job_id=job_id,
            changed_step_ids=[step_id],
        )
        await session.commit()


async def update_trip_job_trip_request(job_id: str, trip_request: dict) -> None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("""
                UPDATE travel_trip_job
                SET trip_request_json = CAST(:trip_request_json AS jsonb)
                WHERE job_id = :job_id
                  AND status = 'RUNNING'
            """),
            {
                "job_id": job_id,
                "trip_request_json": json.dumps(trip_request, ensure_ascii=False),
            },
        )
        if result.rowcount:
            await emit_trip_projection_commit(session, job_id=job_id)
        await session.commit()


async def mark_trip_job_success(
    job_id: str,
    *,
    reply_text: str,
    plan_count: int,
    result_type: str,
    result_record_id: int | None,
    trip_request_json: dict,
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        scope = await session.execute(
            text("""
                SELECT source, conversation_id
                FROM travel_trip_job
                WHERE job_id = :job_id
            """),
            {"job_id": job_id},
        )
        row = scope.one_or_none()
        if row is None:
            return
        await _lock_conversation(
            session,
            source=row.source,
            conversation_id=row.conversation_id,
        )
        result = await session.execute(
            text("""
                UPDATE travel_trip_job
                SET status = 'SUCCESS',
                    current_stage = 'SUCCESS',
                    result_type = :result_type,
                    reply_text = :reply_text,
                    plan_count = :plan_count,
                    result_record_id = :result_record_id,
                    trip_request_json = CAST(:trip_request_json AS jsonb),
                    error_code = NULL,
                    error_message = NULL,
                    finished_time = NOW()
                WHERE job_id = :job_id
                  AND status = 'RUNNING'
            """),
            {
                "job_id": job_id,
                "result_type": result_type,
                "reply_text": reply_text,
                "plan_count": plan_count,
                "result_record_id": result_record_id,
                "trip_request_json": json.dumps(trip_request_json, ensure_ascii=False),
            },
        )
        if result.rowcount:
            step_ids = await close_all_running_steps(
                session,
                job_id=job_id,
                status="SUCCESS",
            )
            await emit_trip_projection_commit(
                session,
                job_id=job_id,
                changed_step_ids=step_ids,
            )
        await session.commit()


async def mark_trip_job_failed(
    job_id: str,
    *,
    error_code: str,
    error_message: str,
    error_detail: str,
    step_metadata: dict | None = None,
    ensure_terminal_step: bool = False,
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("""
                UPDATE travel_trip_job
                SET status = 'FAILED',
                    current_stage = 'FAILED',
                    error_code = :error_code,
                    error_message = :error_message,
                    error_detail = :error_detail,
                    finished_time = NOW()
                WHERE job_id = :job_id
                  AND status = 'RUNNING'
            """),
            {
                "job_id": job_id,
                "error_code": error_code,
                "error_message": error_message,
                "error_detail": error_detail[:4000],
            },
        )
        if result.rowcount:
            step_ids = await close_all_running_steps(
                session,
                job_id=job_id,
                status="FAILED",
                metadata=step_metadata,
            )
            if ensure_terminal_step and not step_ids:
                terminal_meta = dict(step_metadata or {})
                terminal_meta.setdefault("event_type", "OBSERVATION_FLUSH")
                step_ids.append(
                    await insert_trip_step(
                        session,
                        job_id=job_id,
                        stage="PERSISTING",
                        status="FAILED",
                        latency_ms=0,
                        metadata=terminal_meta,
                        finished=True,
                    )
                )
            await emit_trip_projection_commit(
                session,
                job_id=job_id,
                changed_step_ids=step_ids,
            )
        await session.commit()


async def mark_trip_job_rejected(job_id: str, *, error_code: str) -> None:
    await mark_trip_job_rejected_with_message(
        job_id,
        error_code=error_code,
        error_message=None,
    )


async def mark_trip_job_rejected_with_message(
    job_id: str,
    *,
    error_code: str,
    error_message: str | None = None,
    step_metadata: dict | None = None,
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("""
                UPDATE travel_trip_job
                SET status = 'REJECTED',
                    current_stage = 'CITY_GATE_REJECTED',
                    error_code = :error_code,
                    error_message = :error_message,
                    finished_time = NOW()
                WHERE job_id = :job_id
                  AND status = 'RUNNING'
            """),
            {
                "job_id": job_id,
                "error_code": error_code,
                "error_message": error_message,
            },
        )
        if result.rowcount:
            step_ids = await close_all_running_steps(
                session,
                job_id=job_id,
                status="FAILED",
                metadata=step_metadata,
            )
            await emit_trip_projection_commit(
                session,
                job_id=job_id,
                changed_step_ids=step_ids,
            )
        await session.commit()


async def mark_trip_job_timeout(
    job_id: str,
    *,
    error_detail: str | None = None,
    step_metadata: dict | None = None,
    ensure_terminal_step: bool = False,
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("""
                UPDATE travel_trip_job
                SET status = 'TIMEOUT',
                    current_stage = 'TIMEOUT',
                    error_code = 'TIMEOUT',
                    error_message = '规划超时，请稍后重试',
                    error_detail = COALESCE(:error_detail, error_detail),
                    finished_time = NOW()
                WHERE job_id = :job_id
                  AND status = 'RUNNING'
            """),
            {
                "job_id": job_id,
                # Keep short non-truncated-JSON summary only. Full observation is
                # stored in step metadata JSONB by the worker.
                "error_detail": (error_detail or "")[:1000] or None,
            },
        )
        if result.rowcount:
            step_ids = await close_all_running_steps(
                session,
                job_id=job_id,
                status="TIMEOUT",
                metadata=step_metadata,
            )
            if ensure_terminal_step and not step_ids:
                terminal_meta = dict(step_metadata or {})
                terminal_meta.setdefault("event_type", "OBSERVATION_FLUSH")
                step_ids.append(
                    await insert_trip_step(
                        session,
                        job_id=job_id,
                        stage="PERSISTING",
                        status="TIMEOUT",
                        latency_ms=0,
                        metadata=terminal_meta,
                        finished=True,
                    )
                )
            await emit_trip_projection_commit(
                session,
                job_id=job_id,
                changed_step_ids=step_ids,
            )
        await session.commit()
