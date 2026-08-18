"""Read-only PostgreSQL projections for the internal-admin v1 contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from src.jobs.trip_failed_draft import project_failed_draft_plans
from src.pipeline.db import get_session_factory


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
ERROR_CODE_BY_DETAILED_REASON = {
    reason: code for code, reason in DETAILED_REASON_BY_ERROR_CODE.items()
}

TRIP_JOB_STATUSES = frozenset(
    {"PENDING", "RUNNING", "SUCCESS", "FAILED", "TIMEOUT", "REJECTED"}
)
TRIP_RESULT_TYPES = frozenset(
    {"PLAN_READY", "NO_CANDIDATES", "NO_USABLE_ROUTE"}
)
ARTIFACT_TYPES = frozenset({"pdf", "share_image"})
ARTIFACT_STATUSES = frozenset(
    {"PENDING", "RUNNING", "READY", "FAILED", "EXPIRED"}
)


@dataclass(frozen=True)
class AdminArtifactRecord:
    artifact_id: str
    result_record_id: int
    artifact_type: str
    status: str
    filename: str | None
    mime_type: str | None
    byte_size: int | None
    sha256: str | None
    text_length: int | None
    width_px: int | None
    height_px: int | None
    page_count: int | None
    attempt_count: int
    error_code: str | None
    created_time: datetime
    started_time: datetime | None
    finished_time: datetime | None
    expires_time: datetime | None
    storage_backend: str
    storage_key: str | None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _artifact_status_sql(alias: str = "a") -> str:
    return (
        f"CASE WHEN {alias}.status = 'ready' "
        f"AND {alias}.expires_time IS NOT NULL "
        f"AND {alias}.expires_time <= :now "
        f"THEN 'EXPIRED' ELSE UPPER({alias}.status) END"
    )


def artifact_business_status(
    record: AdminArtifactRecord,
    *,
    now: datetime | None = None,
) -> str:
    current = now or _utc_now()
    expires = record.expires_time
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if record.status.lower() == "ready" and expires is not None and expires <= current:
        return "EXPIRED"
    return record.status.upper()


def _trip_filters(
    *,
    time_from: datetime | None,
    time_to: datetime | None,
    city: str | None,
    status: str | None,
    result_type: str | None,
    error_code: str | None,
    detailed_reason: str | None,
) -> tuple[str, dict[str, Any]]:
    clauses = ["TRUE"]
    params: dict[str, Any] = {}
    if time_from is not None:
        clauses.append("j.created_time >= :time_from")
        params["time_from"] = time_from
    if time_to is not None:
        clauses.append("j.created_time <= :time_to")
        params["time_to"] = time_to
    if city is not None:
        clauses.append("COALESCE(j.trip_request_json ->> 'to_city', '') = :city")
        params["city"] = city
    if status is not None:
        clauses.append("j.status = :status")
        params["status"] = status
    if result_type is not None:
        clauses.append("j.result_type = :result_type")
        params["result_type"] = result_type
    if error_code is not None:
        clauses.append("j.error_code = :error_code")
        params["error_code"] = error_code
    if detailed_reason is not None:
        clauses.append("j.error_code = :detailed_reason_error_code")
        params["detailed_reason_error_code"] = ERROR_CODE_BY_DETAILED_REASON[
            detailed_reason
        ]
    return " AND ".join(clauses), params


def _trip_row(row) -> dict[str, Any]:
    data = dict(row._mapping)
    return {
        "job_id": str(data["job_id"]),
        "result_record_id": data["result_record_id"],
        "status": data["status"],
        "current_stage": data["current_stage"],
        "city": data["city"] or None,
        "result_type": data["result_type"],
        "error_code": data["error_code"],
        "created_time": data["created_time"],
        "started_time": data["started_time"],
        "finished_time": data["finished_time"],
        "retry_count": int(data["retry_count"] or 0),
        "failed_draft_available": bool(data["failed_draft_available"]),
    }


def _step_duration_ms(
    started_time: datetime | None,
    finished_time: datetime | None,
    latency_ms: int | None,
) -> int | None:
    if latency_ms is not None:
        return max(0, int(latency_ms))
    if started_time is None or finished_time is None:
        return None
    start = started_time
    end = finished_time
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(0, int((end - start).total_seconds() * 1000))


_TRIP_SELECT = """
    SELECT
        j.job_id,
        j.result_record_id,
        j.status,
        j.current_stage,
        COALESCE(j.trip_request_json ->> 'to_city', '') AS city,
        j.result_type,
        j.error_code,
        j.created_time,
        j.started_time,
        j.finished_time,
        GREATEST(
            GREATEST(COALESCE(s.max_attempt, 1) - 1, 0),
            COALESCE(s.max_publish_retry_round, 0)
        )::int AS retry_count,
        (
            j.status IN ('FAILED', 'TIMEOUT')
            AND COALESCE(j.result_type, '') NOT IN (
                'NO_CANDIDATES',
                'NO_USABLE_ROUTE'
            )
            AND EXISTS (
                SELECT 1
                FROM travel_trip_failed_draft d
                WHERE d.job_id = j.job_id
            )
        ) AS failed_draft_available
    FROM travel_trip_job j
    LEFT JOIN (
        SELECT
            job_id,
            MAX(attempt) AS max_attempt,
            MAX(publish_retry_round) AS max_publish_retry_round
        FROM travel_trip_job_step
        GROUP BY job_id
    ) s ON s.job_id = j.job_id
"""


async def list_admin_trip_jobs(
    *,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
    city: str | None = None,
    status: str | None = None,
    result_type: str | None = None,
    error_code: str | None = None,
    detailed_reason: str | None = None,
    page: int,
    limit: int,
) -> tuple[int, list[dict[str, Any]]]:
    where_sql, params = _trip_filters(
        time_from=time_from,
        time_to=time_to,
        city=city,
        status=status,
        result_type=result_type,
        error_code=error_code,
        detailed_reason=detailed_reason,
    )
    params.update({"limit": limit, "offset": (page - 1) * limit})
    factory = get_session_factory()
    async with factory() as session:
        total_result = await session.execute(
            text(f"SELECT COUNT(*)::bigint FROM travel_trip_job j WHERE {where_sql}"),
            params,
        )
        rows_result = await session.execute(
            text(
                f"""
                {_TRIP_SELECT}
                WHERE {where_sql}
                ORDER BY j.created_time DESC, j.id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        return int(total_result.scalar_one()), [_trip_row(row) for row in rows_result]


async def get_admin_trip_job(job_id: str) -> dict[str, Any] | None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                f"""
                {_TRIP_SELECT}
                WHERE j.job_id = :job_id
                """
            ),
            {"job_id": job_id},
        )
        row = result.first()
        if row is None:
            return None

        steps_result = await session.execute(
            text(
                """
                SELECT
                    stage,
                    status,
                    attempt,
                    publish_retry_round,
                    started_time,
                    finished_time,
                    latency_ms
                FROM travel_trip_job_step
                WHERE job_id = :job_id
                ORDER BY created_time ASC, id ASC
                """
            ),
            {"job_id": job_id},
        )
        item = _trip_row(row)
        item["steps"] = [
            {
                "stage": step.stage,
                "status": step.status,
                "attempt": int(step.attempt),
                "publish_retry_round": int(step.publish_retry_round),
                "started_time": step.started_time,
                "finished_time": step.finished_time,
                "duration_ms": _step_duration_ms(
                    step.started_time,
                    step.finished_time,
                    step.latency_ms,
                ),
            }
            for step in steps_result
        ]
        return item


async def get_admin_failed_draft(job_id: str) -> dict[str, Any] | None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                """
                SELECT d.plans_json, d.created_time
                FROM travel_trip_failed_draft d
                JOIN travel_trip_job j ON j.job_id = d.job_id
                WHERE d.job_id = :job_id
                  AND j.status IN ('FAILED', 'TIMEOUT')
                  AND COALESCE(j.result_type, '') NOT IN (
                      'NO_CANDIDATES',
                      'NO_USABLE_ROUTE'
                  )
                """
            ),
            {"job_id": job_id},
        )
        row = result.first()
        if row is None:
            return None
        plans = row.plans_json
        if isinstance(plans, str):
            try:
                plans = json.loads(plans)
            except json.JSONDecodeError:
                plans = []
        return {
            "job_id": job_id,
            "plans": project_failed_draft_plans(
                plans if isinstance(plans, list) else []
            ),
            "created_time": row.created_time,
        }


def _artifact_filters(
    *,
    time_from: datetime | None,
    time_to: datetime | None,
    artifact_type: str | None,
    status: str | None,
    result_record_id: int | None,
) -> tuple[str, dict[str, Any]]:
    clauses = ["TRUE"]
    params: dict[str, Any] = {"now": _utc_now()}
    if time_from is not None:
        clauses.append("a.created_time >= :time_from")
        params["time_from"] = time_from
    if time_to is not None:
        clauses.append("a.created_time <= :time_to")
        params["time_to"] = time_to
    if artifact_type is not None:
        clauses.append("a.artifact_type = :artifact_type")
        params["artifact_type"] = artifact_type
    if status is not None:
        clauses.append(f"{_artifact_status_sql()} = :artifact_status")
        params["artifact_status"] = status
    if result_record_id is not None:
        clauses.append("a.result_record_id = :result_record_id")
        params["result_record_id"] = result_record_id
    return " AND ".join(clauses), params


_ARTIFACT_SAFE_SELECT = """
    SELECT
        a.artifact_id,
        a.result_record_id,
        a.artifact_type,
        a.status,
        a.filename,
        a.mime_type,
        a.byte_size,
        a.sha256,
        a.text_length,
        a.width_px,
        a.height_px,
        a.page_count,
        a.attempt_count,
        a.error_code,
        a.created_time,
        a.started_time,
        a.finished_time,
        a.expires_time
    FROM travel_export_artifact a
"""


def _artifact_safe_row(row, *, now: datetime) -> dict[str, Any]:
    data = dict(row._mapping)
    expires = data["expires_time"]
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    status = data["status"].upper()
    if status == "READY" and expires is not None and expires <= now:
        status = "EXPIRED"
    return {
        "artifact_id": str(data["artifact_id"]),
        "result_record_id": data["result_record_id"],
        "artifact_type": data["artifact_type"],
        "status": status,
        "filename": data["filename"],
        "mime_type": data["mime_type"],
        "byte_size": data["byte_size"],
        "sha256": data["sha256"],
        "text_length": data["text_length"],
        "width_px": data["width_px"],
        "height_px": data["height_px"],
        "page_count": data["page_count"],
        "attempt_count": int(data["attempt_count"] or 0),
        "error_code": data["error_code"],
        "created_time": data["created_time"],
        "started_time": data["started_time"],
        "finished_time": data["finished_time"],
        "expires_time": data["expires_time"],
    }


async def list_admin_artifacts(
    *,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
    artifact_type: str | None = None,
    status: str | None = None,
    result_record_id: int | None = None,
    page: int,
    limit: int,
) -> tuple[int, list[dict[str, Any]]]:
    where_sql, params = _artifact_filters(
        time_from=time_from,
        time_to=time_to,
        artifact_type=artifact_type,
        status=status,
        result_record_id=result_record_id,
    )
    params.update({"limit": limit, "offset": (page - 1) * limit})
    now = params["now"]
    factory = get_session_factory()
    async with factory() as session:
        total_result = await session.execute(
            text(
                f"""
                SELECT COUNT(*)::bigint
                FROM travel_export_artifact a
                WHERE {where_sql}
                """
            ),
            params,
        )
        rows_result = await session.execute(
            text(
                f"""
                {_ARTIFACT_SAFE_SELECT}
                WHERE {where_sql}
                ORDER BY a.created_time DESC, a.id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        return int(total_result.scalar_one()), [
            _artifact_safe_row(row, now=now) for row in rows_result
        ]


async def get_admin_artifact(
    artifact_id: str,
) -> AdminArtifactRecord | None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    artifact_id,
                    result_record_id,
                    artifact_type,
                    status,
                    filename,
                    mime_type,
                    byte_size,
                    sha256,
                    text_length,
                    width_px,
                    height_px,
                    page_count,
                    attempt_count,
                    error_code,
                    created_time,
                    started_time,
                    finished_time,
                    expires_time,
                    storage_backend,
                    storage_key
                FROM travel_export_artifact
                WHERE artifact_id = :artifact_id
                  AND artifact_type IN ('pdf', 'share_image')
                """
            ),
            {"artifact_id": artifact_id},
        )
        row = result.first()
        if row is None:
            return None
        return AdminArtifactRecord(**dict(row._mapping))
