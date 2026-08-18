"""Internal API for recording explicit feedback on the current travel plan."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.internal.auth import verify_internal_token
from src.jobs.plan_feedback_store import (
    FeedbackRequestIdConflictError,
    FeedbackTargetNotCurrentError,
    FeedbackTargetNotFoundError,
    create_plan_feedback,
)

router = APIRouter(prefix="/internal", dependencies=[Depends(verify_internal_token)])


class PlanFeedbackCreateRequest(BaseModel):
    request_id: str = Field(max_length=512)
    result_record_id: int = Field(gt=0)
    source: str = Field(max_length=30)
    conversation_id: str = Field(max_length=200)
    rating: Literal["positive", "negative"]
    feedback_text: str


class PlanFeedbackCreateResponse(BaseModel):
    success: bool = True
    feedback_id: int
    cached: bool
    message: str


@router.post("/trip/feedback", response_model=PlanFeedbackCreateResponse)
async def create_plan_feedback_endpoint(
    req: PlanFeedbackCreateRequest,
) -> PlanFeedbackCreateResponse:
    try:
        created = await create_plan_feedback(
            request_id=req.request_id,
            result_record_id=req.result_record_id,
            source=req.source,
            conversation_id=req.conversation_id,
            rating=req.rating,
            feedback_text=req.feedback_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FeedbackTargetNotFoundError as exc:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "reason": "FEEDBACK_TARGET_NOT_FOUND",
                "message": str(exc),
            },
        )
    except FeedbackTargetNotCurrentError as exc:
        return JSONResponse(
            status_code=409,
            content={
                "success": False,
                "reason": "FEEDBACK_TARGET_NOT_CURRENT",
                "message": str(exc),
            },
        )
    except FeedbackRequestIdConflictError as exc:
        return JSONResponse(
            status_code=409,
            content={
                "success": False,
                "reason": "FEEDBACK_REQUEST_CONFLICT",
                "message": str(exc),
            },
        )

    return PlanFeedbackCreateResponse(
        feedback_id=created.feedback.feedback_id,
        cached=created.cached,
        message="反馈已记录",
    )
