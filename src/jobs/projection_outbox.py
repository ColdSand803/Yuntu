"""Atomic, privacy-safe source snapshots for Admin Control Plane v0.2."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.pipeline.db import get_session_factory


EVENT_TYPE = "TRIP_PROJECTION_COMMITTED"
EVENT_SCHEMA_VERSION = "1.0"
AGGREGATE_TYPE = "TRIP_JOB"
MAX_CHANGED_STEPS = 500

JOB_PAYLOAD_FIELDS = frozenset(
    {
        "source_id",
        "job_id",
        "source_version",
        "source",
        "city",
        "days",
        "status",
        "current_stage",
        "result_type",
        "result_record_id",
        "generator",
        "guide_result_state",
        "error_code",
        "safe_error",
        "detailed_reason",
        "created_at",
        "started_at",
        "finished_at",
        "retry_count",
        "failed_draft_available",
        "trace_completeness",
        "source_updated_at",
    }
)
STEP_PAYLOAD_FIELDS = frozenset(
    {
        "source_step_id",
        "job_id",
        "source_version",
        "stage",
        "status",
        "attempt",
        "publish_retry_round",
        "started_at",
        "finished_at",
        "duration_ms",
        "source_updated_at",
    }
)
FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "email",
        "masked_email",
        "request",
        "request_body",
        "user_query",
        "trip_request_json",
        "reply_text",
        "guide_body",
        "final_guide",
        "failed_draft",
        "artifact_bytes",
        "prompt",
        "model_context",
        "metadata",
        "error_detail",
    }
)

SAFE_ERROR_MESSAGES = {
    "PUBLISH_GATE_FAILED": "攻略未通过发布校验",
    "SAFE_RENDER_FAILED": "基础行程渲染失败",
    "TIMEOUT": "规划超时",
    "LLM_ERROR": "规划服务暂时不可用",
    "DB_ERROR": "规划保存失败",
    "WORKFLOW_ERROR": "规划流程失败",
    "UNKNOWN": "规划失败",
    "CANCELLED": "规划已取消",
    "CITY_PREPARING": "城市数据准备中",
    "CITY_COLLECTION_FAILED": "城市数据采集失败",
    "CITY_DATA_INSUFFICIENT": "城市数据不足",
    "CITY_DISABLED": "城市暂不可用",
    "CITY_CLARIFICATION_REQUIRED": "需要补充目的地城市",
}
DETAILED_REASON_BY_ERROR_CODE = {
    "PUBLISH_GATE_FAILED": "publish_gate_failed",
    "SAFE_RENDER_FAILED": "safe_render_failed",
    "TIMEOUT": "timeout",
    "LLM_ERROR": "llm_error",
    "DB_ERROR": "db_error",
    "WORKFLOW_ERROR": "workflow_error",
    "UNKNOWN": "unknown",
    "CANCELLED": "cancelled",
    "CITY_PREPARING": "city_preparing",
    "CITY_COLLECTION_FAILED": "city_collection_failed",
    "CITY_DATA_INSUFFICIENT": "city_data_insufficient",
    "CITY_DISABLED": "city_disabled",
    "CITY_CLARIFICATION_REQUIRED": "city_clarification_required",
}


async def insert_trip_step(
    session: AsyncSession,
    *,
    job_id: str,
    stage: str,
    status: str,
    attempt: int = 1,
    publish_retry_round: int = 0,
    latency_ms: int | None = None,
    metadata: dict[str, Any] | None = None,
    finished: bool = False,
) -> int:
    """Insert one source step at projection version 1 in the caller transaction."""
    row = (
        await session.execute(
            text(
                """
                INSERT INTO travel_trip_job_step (
                    job_id, stage, attempt, publish_retry_round, status,
                    started_time, finished_time, latency_ms, metadata,
                    projection_version
                ) VALUES (
                    :job_id, :stage, :attempt, :publish_retry_round, :status,
                    NOW(), CASE WHEN :finished THEN NOW() ELSE NULL END,
                    :latency_ms, CAST(:metadata AS jsonb), 1
                )
                RETURNING id
                """
            ),
            {
                "job_id": job_id,
                "stage": stage,
                "attempt": attempt,
                "publish_retry_round": publish_retry_round,
                "status": status,
                "finished": finished,
                "latency_ms": latency_ms,
                "metadata": json.dumps(metadata or {}, ensure_ascii=False),
            },
        )
    ).one()
    return int(row.id)


async def finish_latest_running_step(
    session: AsyncSession,
    *,
    job_id: str,
    stage: str,
    status: str,
    attempt: int = 1,
    publish_retry_round: int = 0,
    latency_ms: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> int | None:
    """Finish the newest matching RUNNING step and advance its version once."""
    row = (
        await session.execute(
            text(
                """
                WITH target AS (
                    SELECT id
                    FROM travel_trip_job_step
                    WHERE job_id = :job_id
                      AND stage = :stage
                      AND attempt = :attempt
                      AND publish_retry_round = :publish_retry_round
                      AND status = 'RUNNING'
                    ORDER BY started_time DESC, id DESC
                    LIMIT 1
                    FOR UPDATE
                )
                UPDATE travel_trip_job_step step
                SET status = :status,
                    finished_time = NOW(),
                    latency_ms = :latency_ms,
                    metadata = step.metadata || CAST(:metadata AS jsonb),
                    projection_version = step.projection_version + 1
                FROM target
                WHERE step.id = target.id
                RETURNING step.id
                """
            ),
            {
                "job_id": job_id,
                "stage": stage,
                "attempt": attempt,
                "publish_retry_round": publish_retry_round,
                "status": status,
                "latency_ms": latency_ms,
                "metadata": json.dumps(metadata or {}, ensure_ascii=False),
            },
        )
    ).one_or_none()
    return int(row.id) if row is not None else None


async def close_all_running_steps(
    session: AsyncSession,
    *,
    job_id: str,
    status: str,
    metadata: dict[str, Any] | None = None,
) -> list[int]:
    """Close every RUNNING step as one part of a terminal source transaction."""
    if status not in {"SUCCESS", "FAILED", "TIMEOUT"}:
        raise ValueError("running trip steps require a terminal step status")
    rows = (
        await session.execute(
            text(
                """
                UPDATE travel_trip_job_step
                SET status = :status,
                    finished_time = NOW(),
                    latency_ms = GREATEST(
                        0,
                        CAST(EXTRACT(EPOCH FROM (NOW() - started_time)) * 1000 AS INT)
                    ),
                    metadata = metadata || CAST(:metadata AS jsonb),
                    projection_version = projection_version + 1
                WHERE job_id = :job_id
                  AND status = 'RUNNING'
                RETURNING id
                """
            ),
            {
                "job_id": job_id,
                "status": status,
                "metadata": json.dumps(metadata or {}, ensure_ascii=False),
            },
        )
    ).all()
    return [int(row.id) for row in rows]


def iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def nullable_iso_utc(value: datetime | None) -> str | None:
    return iso_utc(value) if value is not None else None


def compute_guide_result_state(
    *,
    status: str,
    result_type: str | None,
    result_record_id: int | None,
) -> str:
    """Return the frozen Guide Result State truth-table outcome."""
    if status == "SUCCESS":
        if result_type == "PLAN_READY" and result_record_id is not None:
            return "AVAILABLE"
        if (
            result_type in {"NO_CANDIDATES", "NO_USABLE_ROUTE"}
            and result_record_id is None
        ):
            return "LEGAL_NO_GUIDE"
        return "INCONSISTENT"
    if result_type is None and result_record_id is None:
        return "NOT_APPLICABLE"
    return "INCONSISTENT"


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _safe_days(request_data: dict[str, Any]) -> int | None:
    raw = request_data.get("days")
    if isinstance(raw, bool):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if 1 <= value <= 30 else None


def _duration_ms(
    *,
    started_at: datetime,
    finished_at: datetime | None,
    latency_ms: int | None,
) -> int | None:
    if latency_ms is not None:
        return max(0, int(latency_ms))
    if finished_at is None:
        return None
    start = started_at
    end = finished_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(0, int((end - start).total_seconds() * 1000))


def validate_projection_event(event: dict[str, Any]) -> None:
    """Enforce application invariants and the payload privacy allowlist."""
    payload = event.get("payload")
    if not isinstance(payload, dict) or set(payload) != {"job", "changed_steps"}:
        raise ValueError("projection payload shape is invalid")
    job = payload.get("job")
    steps = payload.get("changed_steps")
    if not isinstance(job, dict) or set(job) != JOB_PAYLOAD_FIELDS:
        raise ValueError("projection job payload is not allowlisted")
    if not isinstance(steps, list) or len(steps) > MAX_CHANGED_STEPS:
        raise ValueError("projection changed_steps exceeds the contract bound")
    if event.get("aggregate_id") != job.get("job_id"):
        raise ValueError("aggregate_id must equal payload.job.job_id")
    if event.get("aggregate_version") != job.get("source_version"):
        raise ValueError("aggregate_version must equal payload.job.source_version")
    for step in steps:
        if not isinstance(step, dict) or set(step) != STEP_PAYLOAD_FIELDS:
            raise ValueError("projection step payload is not allowlisted")
        if step.get("job_id") != job.get("job_id"):
            raise ValueError("projection step belongs to another job")
    safe_error = job.get("safe_error")
    if job.get("error_code") is None:
        if safe_error is not None:
            raise ValueError("safe_error must be null with a null error_code")
    elif not isinstance(safe_error, dict) or safe_error.get("code") != job.get(
        "error_code"
    ):
        raise ValueError("safe_error.code must equal error_code")

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            forbidden = FORBIDDEN_PAYLOAD_KEYS.intersection(value)
            if forbidden:
                raise ValueError(
                    f"projection payload contains forbidden keys: {sorted(forbidden)}"
                )
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(payload)


def _project_job_snapshot_row(row: Any) -> dict[str, Any]:
    request_data = _json_object(row["trip_request_json"])
    error_code = row["error_code"]
    safe_error = None
    if error_code is not None:
        safe_error = {
            "code": str(error_code),
            "message": SAFE_ERROR_MESSAGES.get(str(error_code), "规划失败"),
        }
    return {
        "source_id": int(row["source_id"]),
        "job_id": str(row["job_id"]),
        "source_version": int(row["source_version"]),
        "source": str(row["source"]),
        "city": str(request_data.get("to_city") or "").strip() or None,
        "days": _safe_days(request_data),
        "status": str(row["status"]),
        "current_stage": (
            str(row["current_stage"]) if row["current_stage"] is not None else None
        ),
        "result_type": row["result_type"],
        "result_record_id": (
            int(row["result_record_id"])
            if row["result_record_id"] is not None
            else None
        ),
        "generator": (
            str(row["generator"]) if row["generator"] is not None else None
        ),
        "guide_result_state": str(row["guide_result_state"]),
        "error_code": str(error_code) if error_code is not None else None,
        "safe_error": safe_error,
        "detailed_reason": DETAILED_REASON_BY_ERROR_CODE.get(str(error_code or "")),
        "created_at": iso_utc(row["created_time"]),
        "started_at": nullable_iso_utc(row["started_time"]),
        "finished_at": nullable_iso_utc(row["finished_time"]),
        "retry_count": int(row["retry_count"] or 0),
        "failed_draft_available": bool(row["failed_draft_available"]),
        "trace_completeness": str(row["trace_completeness"]),
        "source_updated_at": iso_utc(row["source_updated_at"]),
    }


_JOB_SNAPSHOT_SELECT = """
    SELECT
        j.id AS source_id,
        j.job_id,
        j.projection_version AS source_version,
        j.source,
        j.trip_request_json,
        j.status,
        j.current_stage,
        j.result_type,
        j.result_record_id,
        CASE
            WHEN MAX(p.quality_metrics ->> 'generator') IN (
                'opus', 'ds_flash', 'safe'
            ) THEN MAX(p.quality_metrics ->> 'generator')
            WHEN MAX(p.quality_metrics ->> 'published_variant') = 'safe'
                THEN 'safe'
            ELSE NULL
        END AS generator,
        j.guide_result_state,
        j.error_code,
        j.created_time,
        j.started_time,
        j.finished_time,
        j.trace_completeness,
        j.updated_time AS source_updated_at,
        COUNT(DISTINCT s.id) FILTER (
            WHERE s.attempt > 1 OR s.publish_retry_round > 0
        )::int AS retry_count,
        EXISTS (
            SELECT 1
            FROM travel_trip_failed_draft d
            WHERE d.job_id = j.job_id
              AND j.status IN ('FAILED', 'TIMEOUT')
              AND COALESCE(j.result_type, '') NOT IN (
                  'NO_CANDIDATES', 'NO_USABLE_ROUTE'
              )
        ) AS failed_draft_available
    FROM travel_trip_job j
    LEFT JOIN travel_trip_job_step s ON s.job_id = j.job_id
    LEFT JOIN travel_plan_record p ON p.id = j.result_record_id
"""


async def _job_snapshot(
    session: AsyncSession,
    job_id: str,
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                f"""
                {_JOB_SNAPSHOT_SELECT}
                WHERE j.job_id = :job_id
                GROUP BY j.id
                """
            ),
            {"job_id": job_id},
        )
    ).mappings().one()
    return _project_job_snapshot_row(row)


async def _step_snapshots(
    session: AsyncSession,
    *,
    job_id: str,
    step_ids: list[int],
) -> list[dict[str, Any]]:
    if not step_ids:
        return []
    rows = (
        await session.execute(
            text(
                """
                SELECT id, job_id, projection_version, stage, status, attempt,
                       publish_retry_round, started_time, finished_time,
                       latency_ms, updated_time
                FROM travel_trip_job_step
                WHERE id = ANY(CAST(:step_ids AS bigint[]))
                ORDER BY id ASC
                """
            ),
            {"step_ids": step_ids},
        )
    ).mappings().all()
    if len(rows) != len(step_ids):
        raise ValueError("changed step snapshot is incomplete")
    snapshots: list[dict[str, Any]] = []
    for row in rows:
        if str(row["job_id"]) != job_id:
            raise ValueError("changed step belongs to another job")
        snapshots.append(_project_step_snapshot_row(row))
    return snapshots


def _project_step_snapshot_row(row: Any) -> dict[str, Any]:
    return {
        "source_step_id": int(row["id"]),
        "job_id": str(row["job_id"]),
        "source_version": int(row["projection_version"]),
        "stage": str(row["stage"]),
        "status": str(row["status"]),
        "attempt": int(row["attempt"]),
        "publish_retry_round": int(row["publish_retry_round"]),
        "started_at": iso_utc(row["started_time"]),
        "finished_at": nullable_iso_utc(row["finished_time"]),
        "duration_ms": _duration_ms(
            started_at=row["started_time"],
            finished_at=row["finished_time"],
            latency_ms=row["latency_ms"],
        ),
        "source_updated_at": iso_utc(row["updated_time"]),
    }


async def get_trip_job_snapshot_page(
    *,
    after_id: int,
    snapshot_max_id: int | None,
    limit: int,
) -> dict[str, Any]:
    """Return a frozen-ID keyset page of safe job source snapshots."""
    factory = get_session_factory()
    async with factory() as session:
        effective_max = snapshot_max_id
        if effective_max is None:
            effective_max = int(
                (
                    await session.execute(
                        text("SELECT COALESCE(MAX(id), 0)::bigint FROM travel_trip_job")
                    )
                ).scalar_one()
            )
        rows = (
            await session.execute(
                text(
                    f"""
                    {_JOB_SNAPSHOT_SELECT}
                    WHERE j.id > :after_id
                      AND j.id <= :snapshot_max_id
                    GROUP BY j.id
                    ORDER BY j.id ASC
                    LIMIT :fetch_limit
                    """
                ),
                {
                    "after_id": after_id,
                    "snapshot_max_id": effective_max,
                    "fetch_limit": limit + 1,
                },
            )
        ).mappings().all()
    has_more = len(rows) > limit
    visible = rows[:limit]
    items = [_project_job_snapshot_row(row) for row in visible]
    return {
        "snapshot_max_id": effective_max,
        "next_after_id": items[-1]["source_id"] if has_more else None,
        "has_more": has_more,
        "items": items,
    }


async def get_trip_step_snapshot_page(
    *,
    after_id: int,
    snapshot_max_id: int | None,
    limit: int,
) -> dict[str, Any]:
    """Return a frozen-ID keyset page of safe step source snapshots."""
    factory = get_session_factory()
    async with factory() as session:
        effective_max = snapshot_max_id
        if effective_max is None:
            effective_max = int(
                (
                    await session.execute(
                        text(
                            "SELECT COALESCE(MAX(id), 0)::bigint "
                            "FROM travel_trip_job_step"
                        )
                    )
                ).scalar_one()
            )
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, job_id, projection_version, stage, status,
                           attempt, publish_retry_round, started_time,
                           finished_time, latency_ms, updated_time
                    FROM travel_trip_job_step
                    WHERE id > :after_id
                      AND id <= :snapshot_max_id
                    ORDER BY id ASC
                    LIMIT :fetch_limit
                    """
                ),
                {
                    "after_id": after_id,
                    "snapshot_max_id": effective_max,
                    "fetch_limit": limit + 1,
                },
            )
        ).mappings().all()
    has_more = len(rows) > limit
    visible = rows[:limit]
    items = [_project_step_snapshot_row(row) for row in visible]
    return {
        "snapshot_max_id": effective_max,
        "next_after_id": items[-1]["source_step_id"] if has_more else None,
        "has_more": has_more,
        "items": items,
    }


async def emit_trip_projection_commit(
    session: AsyncSession,
    *,
    job_id: str,
    changed_step_ids: Iterable[int] = (),
    advance_job_version: bool = True,
) -> dict[str, Any]:
    """Create one complete commit event inside the caller's transaction."""
    step_ids = sorted({int(step_id) for step_id in changed_step_ids})
    if len(step_ids) > MAX_CHANGED_STEPS:
        raise ValueError("one source transaction changed more than 500 steps")

    state_row = (
        await session.execute(
            text(
                """
                SELECT status, result_type, result_record_id
                FROM travel_trip_job
                WHERE job_id = :job_id
                FOR UPDATE
                """
            ),
            {"job_id": job_id},
        )
    ).mappings().one()
    guide_result_state = compute_guide_result_state(
        status=str(state_row["status"]),
        result_type=state_row["result_type"],
        result_record_id=state_row["result_record_id"],
    )
    version_sql = ", projection_version = projection_version + 1" if advance_job_version else ""
    await session.execute(
        text(
            f"""
            UPDATE travel_trip_job
            SET guide_result_state = :guide_result_state{version_sql}
            WHERE job_id = :job_id
            """
        ),
        {"job_id": job_id, "guide_result_state": guide_result_state},
    )

    job = await _job_snapshot(session, job_id)
    changed_steps = await _step_snapshots(
        session,
        job_id=job_id,
        step_ids=step_ids,
    )
    allocation = (
        await session.execute(
            text(
                """
                UPDATE projection_stream_head
                SET head_sequence = head_sequence + 1,
                    updated_time = NOW()
                WHERE stream_id = 1
                RETURNING head_sequence, updated_time
                """
            )
        )
    ).mappings().one()
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": EVENT_TYPE,
        "schema_version": EVENT_SCHEMA_VERSION,
        "outbox_sequence": int(allocation["head_sequence"]),
        "aggregate_type": AGGREGATE_TYPE,
        "aggregate_id": job_id,
        "aggregate_version": int(job["source_version"]),
        "occurred_at": iso_utc(allocation["updated_time"]),
        "payload": {"job": job, "changed_steps": changed_steps},
    }
    validate_projection_event(event)
    await session.execute(
        text(
            """
            INSERT INTO trip_projection_outbox (
                outbox_sequence, event_id, event_type, schema_version,
                aggregate_type, aggregate_id, aggregate_version,
                occurred_at, payload
            ) VALUES (
                :outbox_sequence, CAST(:event_id AS uuid), :event_type,
                :schema_version, :aggregate_type, :aggregate_id,
                :aggregate_version, :occurred_at, CAST(:payload AS jsonb)
            )
            """
        ),
        {
            **{key: value for key, value in event.items() if key != "payload"},
            # asyncpg requires a datetime for TIMESTAMPTZ binds; the event dict
            # keeps the ISO string for broker/JSON consumers.
            "occurred_at": allocation["updated_time"],
            "payload": json.dumps(event["payload"], ensure_ascii=False),
        },
    )
    return event


def json_safe(value: Any) -> Any:
    """Small helper for metrics/debug responses without leaking object internals."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    return str(value)
