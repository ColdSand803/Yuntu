"""Persistence for explicit user feedback on the current travel plan."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.jobs.trip_store import _lock_conversation
from src.pipeline.db import get_session_factory

VALID_RATINGS = frozenset({"positive", "negative"})


class FeedbackRequestIdConflictError(Exception):
    """Same request_id was already used for different feedback."""


class FeedbackTargetNotFoundError(Exception):
    """The referenced travel plan record does not exist."""


class FeedbackTargetNotCurrentError(Exception):
    """The referenced plan is not current for this conversation."""


@dataclass(frozen=True)
class PlanFeedbackRecord:
    feedback_id: int
    request_id: str
    result_record_id: int
    source: str
    conversation_id: str
    rating: str
    feedback_text: str
    created_time: datetime


@dataclass(frozen=True)
class PlanFeedbackCreateResult:
    feedback: PlanFeedbackRecord
    cached: bool


def _row_to_record(row) -> PlanFeedbackRecord:
    return PlanFeedbackRecord(
        feedback_id=row.id,
        request_id=row.request_id,
        result_record_id=row.result_record_id,
        source=row.source,
        conversation_id=row.conversation_id,
        rating=row.rating,
        feedback_text=row.feedback_text,
        created_time=row.created_time,
    )


def _same_feedback(
    feedback: PlanFeedbackRecord,
    *,
    result_record_id: int,
    source: str,
    conversation_id: str,
    rating: str,
    feedback_text: str,
) -> bool:
    return (
        feedback.result_record_id == result_record_id
        and feedback.source == source
        and feedback.conversation_id == conversation_id
        and feedback.rating == rating
        and feedback.feedback_text == feedback_text
    )


async def get_plan_feedback_by_request_id(
    request_id: str,
) -> PlanFeedbackRecord | None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("""
                SELECT id, request_id, result_record_id, source,
                       conversation_id, rating, feedback_text, created_time
                FROM travel_plan_feedback
                WHERE request_id = :request_id
            """),
            {"request_id": request_id},
        )
        row = result.one_or_none()
        return _row_to_record(row) if row is not None else None


async def _validate_current_feedback_target(
    session,
    *,
    result_record_id: int,
    source: str,
    conversation_id: str,
) -> None:
    plan_exists = await session.execute(
        text("SELECT EXISTS(SELECT 1 FROM travel_plan_record WHERE id = :id)"),
        {"id": result_record_id},
    )
    if not plan_exists.scalar_one():
        raise FeedbackTargetNotFoundError("攻略记录不存在")

    current = await session.execute(
        text("""
            SELECT result_record_id
            FROM travel_trip_job
            WHERE source = :source
              AND conversation_id = :conversation_id
              AND status = 'SUCCESS'
              AND result_type = 'PLAN_READY'
              AND result_record_id IS NOT NULL
              AND finished_time >= NOW() - INTERVAL '24 hours'
            ORDER BY finished_time DESC NULLS LAST, created_time DESC
            LIMIT 1
        """),
        {
            "source": source,
            "conversation_id": conversation_id,
        },
    )
    if current.scalar_one_or_none() != result_record_id:
        raise FeedbackTargetNotCurrentError(
            "只能评价当前会话 24 小时内最近一份成功攻略",
        )


async def create_plan_feedback(
    *,
    request_id: str,
    result_record_id: int,
    source: str,
    conversation_id: str,
    rating: str,
    feedback_text: str,
) -> PlanFeedbackCreateResult:
    request_id = request_id.strip()
    source = source.strip()
    conversation_id = conversation_id.strip()
    rating = rating.strip()
    feedback_text = feedback_text.strip()

    if not request_id:
        raise ValueError("request_id is required")
    if not source:
        raise ValueError("source is required")
    if not conversation_id:
        raise ValueError("conversation_id is required")
    if rating not in VALID_RATINGS:
        raise ValueError("rating must be one of: positive, negative")
    if not feedback_text:
        raise ValueError("feedback_text is required")

    existing = await get_plan_feedback_by_request_id(request_id)
    if existing is not None:
        if _same_feedback(
            existing,
            result_record_id=result_record_id,
            source=source,
            conversation_id=conversation_id,
            rating=rating,
            feedback_text=feedback_text,
        ):
            return PlanFeedbackCreateResult(feedback=existing, cached=True)
        raise FeedbackRequestIdConflictError(
            "request_id 已存在，但反馈内容不一致",
        )

    factory = get_session_factory()
    try:
        async with factory() as session:
            await _lock_conversation(
                session,
                source=source,
                conversation_id=conversation_id,
            )
            # Repeat inside the lock so a concurrent idempotent request is cheap
            # without allowing a new current recommendation to interleave.
            existing = await session.execute(
                text("""
                    SELECT id, request_id, result_record_id, source,
                           conversation_id, rating, feedback_text, created_time
                    FROM travel_plan_feedback
                    WHERE request_id = :request_id
                """),
                {"request_id": request_id},
            )
            existing_row = existing.one_or_none()
            if existing_row is not None:
                feedback = _row_to_record(existing_row)
                if _same_feedback(
                    feedback,
                    result_record_id=result_record_id,
                    source=source,
                    conversation_id=conversation_id,
                    rating=rating,
                    feedback_text=feedback_text,
                ):
                    return PlanFeedbackCreateResult(feedback=feedback, cached=True)
                raise FeedbackRequestIdConflictError(
                    "request_id 已存在，但反馈内容不一致",
                )

            await _validate_current_feedback_target(
                session,
                result_record_id=result_record_id,
                source=source,
                conversation_id=conversation_id,
            )
            inserted = await session.execute(
                text("""
                    INSERT INTO travel_plan_feedback (
                        request_id, result_record_id, source,
                        conversation_id, rating, feedback_text
                    ) VALUES (
                        :request_id, :result_record_id, :source,
                        :conversation_id, :rating, :feedback_text
                    )
                    RETURNING id, request_id, result_record_id, source,
                              conversation_id, rating, feedback_text, created_time
                """),
                {
                    "request_id": request_id,
                    "result_record_id": result_record_id,
                    "source": source,
                    "conversation_id": conversation_id,
                    "rating": rating,
                    "feedback_text": feedback_text,
                },
            )
            feedback = _row_to_record(inserted.one())
            await session.commit()
            return PlanFeedbackCreateResult(feedback=feedback, cached=False)
    except IntegrityError:
        raced = await get_plan_feedback_by_request_id(request_id)
        if raced is not None and _same_feedback(
            raced,
            result_record_id=result_record_id,
            source=source,
            conversation_id=conversation_id,
            rating=rating,
            feedback_text=feedback_text,
        ):
            return PlanFeedbackCreateResult(feedback=raced, cached=True)
        if raced is not None:
            raise FeedbackRequestIdConflictError(
                "request_id 已存在，但反馈内容不一致",
            ) from None
        raise
