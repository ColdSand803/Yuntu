"""Stage observation utilities for trip workflow steps."""

from __future__ import annotations

import asyncio
import contextvars
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from src.agents.llm import (
    current_llm_observation_record_count,
    llm_call_context,
    project_current_llm_usage,
)
from src.agents.schema import TripRequest

StageCallback = Callable[[str], Awaitable[None] | None]
StageEventCallback = Callable[[str, str, dict[str, Any]], Awaitable[None] | None]
TripRequestCallback = Callable[[TripRequest], Awaitable[None] | None]
T = TypeVar("T")

_stage_timing_records: contextvars.ContextVar[list[dict[str, Any]] | None] = (
    contextvars.ContextVar("stage_timing_records", default=None)
)


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def start_stage_timing_observation() -> contextvars.Token:
    return _stage_timing_records.set([])


def stop_stage_timing_observation(token: contextvars.Token) -> None:
    _stage_timing_records.reset(token)


def summarize_stage_timing_observation(
    *,
    workflow_elapsed_ms: int | None = None,
    extra_action_latency_ms: int = 0,
) -> dict[str, int]:
    records = _stage_timing_records.get() or []
    action_total = sum(
        int(record.get("stage_action_latency_ms") or 0)
        for record in records
    ) + max(0, int(extra_action_latency_ms or 0))
    current_stage_total = sum(
        int(record.get("current_stage_update_latency_ms") or 0)
        for record in records
    )
    running_write_total = sum(
        int(record.get("stage_event_running_write_latency_ms") or 0)
        for record in records
    )
    terminal_write_total = sum(
        int(record.get("stage_event_success_write_latency_ms") or 0)
        + int(record.get("stage_event_failed_write_latency_ms") or 0)
        for record in records
    )
    step_event_write_total = running_write_total + terminal_write_total
    stage_start_write_total = sum(
        int(record.get("stage_start_write_latency_ms") or 0)
        for record in records
    )
    callback_write_total = current_stage_total + step_event_write_total
    summary = {
        "stage_action_latency_ms_total": action_total,
        "stage_start_write_latency_ms_total": stage_start_write_total,
        "step_event_write_latency_ms_total": step_event_write_total,
        "current_stage_update_latency_ms_total": current_stage_total,
        "callback_write_latency_ms_total": callback_write_total,
    }
    if workflow_elapsed_ms is not None:
        summary["workflow_unobserved_latency_ms"] = max(
            0,
            int(workflow_elapsed_ms) - action_total - callback_write_total,
        )
    return summary


async def _emit_stage(on_stage: StageCallback | None, stage: str) -> None:
    if on_stage is None:
        return
    maybe = on_stage(stage)
    if asyncio.iscoroutine(maybe):
        await maybe


async def _emit_stage_event(
    on_stage_event: StageEventCallback | None,
    stage: str,
    status: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    if on_stage_event is None:
        return
    maybe = on_stage_event(stage, status, metadata or {})
    if asyncio.iscoroutine(maybe):
        await maybe


async def _run_observed_step(
    stage: str,
    action: Callable[[], Awaitable[T]],
    *,
    on_stage: StageCallback | None = None,
    on_stage_event: StageEventCallback | None = None,
    set_current_stage: bool = True,
    attempt: int = 1,
    publish_retry_round: int = 0,
    metadata: dict[str, Any] | None = None,
    finish_metadata: Callable[[], dict[str, Any]] | None = None,
) -> T:
    step_wall_t0 = time.monotonic()
    llm_record_start = current_llm_observation_record_count()
    current_stage_update_latency_ms = 0
    if set_current_stage:
        current_stage_t0 = time.monotonic()
        await _emit_stage(on_stage, stage)
        current_stage_update_latency_ms = _elapsed_ms(current_stage_t0)
    start_metadata = {
        "attempt": attempt,
        "publish_retry_round": publish_retry_round,
        "current_stage_update_latency_ms": current_stage_update_latency_ms,
        **(metadata or {}),
    }
    running_event_t0 = time.monotonic()
    await _emit_stage_event(on_stage_event, stage, "RUNNING", start_metadata)
    stage_event_running_write_latency_ms = _elapsed_ms(running_event_t0)
    stage_start_write_latency_ms = (
        current_stage_update_latency_ms + stage_event_running_write_latency_ms
    )
    t0 = time.monotonic()
    try:
        with llm_call_context(
            stage=stage,
            attempt=attempt,
            publish_retry_round=publish_retry_round,
            owning_stage=stage,
            owning_attempt=attempt,
            owning_publish_retry_round=publish_retry_round,
        ):
            result = await action()
    except Exception as exc:
        action_latency_ms = _elapsed_ms(t0)
        extra_metadata = finish_metadata() if finish_metadata is not None else {}
        extra_metadata["llm_usage"] = project_current_llm_usage(
            llm_record_start,
            complete=True,
            adopted_generator=extra_metadata.get("adopted_generator"),
        )
        failed_metadata = {
            **start_metadata,
            **extra_metadata,
            "stage_event_running_write_latency_ms": (
                stage_event_running_write_latency_ms
            ),
            "stage_start_write_latency_ms": stage_start_write_latency_ms,
            "stage_action_latency_ms": action_latency_ms,
            "stage_total_wall_latency_ms": _elapsed_ms(step_wall_t0),
            "latency_ms": action_latency_ms,
            "error": str(exc)[:500],
        }
        failed_event_t0 = time.monotonic()
        await _emit_stage_event(on_stage_event, stage, "FAILED", failed_metadata)
        stage_event_failed_write_latency_ms = _elapsed_ms(failed_event_t0)
        failed_metadata["stage_event_failed_write_latency_ms"] = (
            stage_event_failed_write_latency_ms
        )
        failed_metadata["stage_total_wall_latency_ms"] = _elapsed_ms(step_wall_t0)
        records = _stage_timing_records.get()
        if records is not None:
            records.append({
                **failed_metadata,
                "stage": stage,
                "status": "FAILED",
            })
        raise
    action_latency_ms = _elapsed_ms(t0)
    extra_metadata = finish_metadata() if finish_metadata is not None else {}
    extra_metadata["llm_usage"] = project_current_llm_usage(
        llm_record_start,
        complete=True,
        adopted_generator=extra_metadata.get("adopted_generator"),
    )
    if "stage_action_latency_ms_total" in extra_metadata:
        extra_metadata["stage_action_latency_ms_total"] = (
            int(extra_metadata["stage_action_latency_ms_total"])
            + action_latency_ms
        )
    if "workflow_unobserved_latency_ms" in extra_metadata:
        extra_metadata["workflow_unobserved_latency_ms"] = max(
            0,
            int(extra_metadata["workflow_unobserved_latency_ms"])
            - action_latency_ms,
        )
    done_metadata = {
        **start_metadata,
        **extra_metadata,
        "stage_event_running_write_latency_ms": (
            stage_event_running_write_latency_ms
        ),
        "stage_start_write_latency_ms": stage_start_write_latency_ms,
        "stage_action_latency_ms": action_latency_ms,
        "stage_total_wall_latency_ms": _elapsed_ms(step_wall_t0),
        "latency_ms": action_latency_ms,
    }
    success_event_t0 = time.monotonic()
    await _emit_stage_event(on_stage_event, stage, "SUCCESS", done_metadata)
    stage_event_success_write_latency_ms = _elapsed_ms(success_event_t0)
    done_metadata["stage_event_success_write_latency_ms"] = (
        stage_event_success_write_latency_ms
    )
    done_metadata["stage_total_wall_latency_ms"] = _elapsed_ms(step_wall_t0)
    records = _stage_timing_records.get()
    if records is not None:
        records.append({
            **done_metadata,
            "stage": stage,
            "status": "SUCCESS",
        })
    return result


async def _emit_trip_request(
    on_trip_request: TripRequestCallback | None,
    trip_request: TripRequest,
) -> None:
    if on_trip_request is None:
        return
    maybe = on_trip_request(trip_request)
    if asyncio.iscoroutine(maybe):
        await maybe
