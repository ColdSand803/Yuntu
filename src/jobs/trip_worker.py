"""Background worker for async trip planning jobs."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from src.agents.llm import (
    bind_observation_sink,
    chat,
    llm_call_context,
    pop_job_observation_flush,
)
from src.agents.publish_gate import (
    PUBLISH_FAILURE_FALLBACK_MESSAGE,
    PublishGateError,
    validate_polished_failure_message,
)
from src.agents.schema import TripRequest
from src.agents.workflow import run_trip_workflow
from src.api.formatter import format_plans_markdown
from src.config import get_settings
from src.jobs.city_batch_store import (
    CityBatchActiveError,
    create_city_crawl_batch,
    get_active_city_batch,
)
from src.jobs.trip_store import (
    TripJobRecord,
    claim_next_pending_trip_job,
    close_running_trip_job_steps,
    ensure_terminal_observation_step,
    expire_stale_trip_jobs,
    get_recent_successful_plan_place_ids,
    mark_trip_job_failed,
    mark_trip_job_rejected,
    mark_trip_job_rejected_with_message,
    mark_trip_job_success,
    mark_trip_job_timeout,
    record_trip_job_stage_started,
    record_trip_job_step_event,
    update_trip_job_trip_request,
)
from src.jobs.city_gate import (
    CITY_CLARIFICATION_REQUIRED,
    CITY_PREPARING,
    CityGateDecision,
    CityGateRejected,
    NON_DEMAND_SOURCES,
    gate_async_trip_request,
)
from src.jobs.place_demand import MustIncludeResolution, match_and_record_must_include
from src.jobs.trip_failed_draft import (
    persist_failed_draft_if_eligible,
    project_failed_draft_plans,
)
from src.agents.safe_plan_renderer import SafeRenderError
from src.agents.writer_relay_router import WriterRelayError

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 1.0
SUCCESS_PERSIST_RETRIES = 3
CITY_CLARIFICATION_FALLBACK_MESSAGE = (
    "我还差一个关键信息：你想去哪个城市？"
    "可以直接发“成都3天美食”或“福州3天想去平潭”，"
    "我再继续帮你规划。"
)


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _datetime_delta_ms(end, start) -> int | None:
    if end is None or start is None:
        return None
    try:
        return max(0, int((end - start).total_seconds() * 1000))
    except Exception:
        return None


async def _chat_before_deadline(
    *,
    deadline_monotonic: float | None,
    job_id: str | None,
    request_id: str | None,
    call_reason: str,
    **kwargs,
) -> str:
    if deadline_monotonic is None:
        return await chat(**kwargs)
    remaining = deadline_monotonic - time.monotonic()
    if remaining <= 0:
        raise asyncio.TimeoutError("trip hard deadline exhausted before Writer polish")
    with llm_call_context(
        job_id=job_id,
        request_id=request_id,
        call_reason=call_reason,
        workflow_deadline_monotonic=deadline_monotonic,
    ):
        return await asyncio.wait_for(chat(**kwargs), timeout=remaining)


async def _polish_publish_failure_message(
    error: PublishGateError,
    *,
    deadline_monotonic: float | None = None,
    job_id: str | None = None,
    request_id: str | None = None,
) -> str:
    """Polish user-safe publish failure copy; never expose or repair bad plans."""
    categories = "、".join(error.result.failure_reasons) or "publish_quality_failed"
    system = """你是 YunTu Travel 的失败提示文案助手。
一次旅行攻略生成已经失败，原因是最终文本不适合直接发给用户。请生成一句自然、简短、礼貌的中文说明。

要求：
- 只说明这次结果不够稳，建议用户换个说法再试。
- 不要提内部系统、审核、Publish Gate、Structural Gate、route lock、内部校验。
- 不要编排行程，不要推荐地点，不要修复攻略。
- 输出 JSON：{"message": "..."}"""
    try:
        raw = await _chat_before_deadline(
            deadline_monotonic=deadline_monotonic,
            job_id=job_id,
            request_id=request_id,
            call_reason="publish_failure_polish",
            system=system,
            user=f"failure_category: {categories}",
            role="writer",
            temperature=0.3,
            json_mode=True,
        )
        data = json.loads(raw)
        message = validate_polished_failure_message(
            str(data.get("message", "")).strip()
        )
    except Exception:
        logger.exception("publish failure polish failed")
        return PUBLISH_FAILURE_FALLBACK_MESSAGE
    return message or PUBLISH_FAILURE_FALLBACK_MESSAGE


def _city_gate_rejection_metadata(decision: CityGateDecision) -> dict[str, str]:
    metadata: dict[str, str] = {
        "city_gate_status": decision.status,
    }
    if decision.city_status:
        metadata["city_status"] = decision.city_status
    if decision.city_batch_status:
        metadata["city_batch_status"] = decision.city_batch_status
    if decision.city_batch_error_code:
        metadata["city_batch_error_code"] = decision.city_batch_error_code
    return metadata


async def _polish_city_clarification_message(
    user_query: str,
    *,
    deadline_monotonic: float | None = None,
    job_id: str | None = None,
    request_id: str | None = None,
) -> str:
    """Ask the Writer model for clarification copy; fall back deterministically."""
    system = """你是 YunTu Travel 的澄清话术助手。
用户的旅行需求缺少明确目的地城市。请生成一句自然、简短、礼貌的中文澄清文案。

要求：
- 只询问用户想去哪个城市。
- 可以给 1-2 个很短示例，例如“成都3天美食”。
- 不要编排行程，不要推荐地点，不要提系统错误。
- 输出 JSON：{"message": "..."}"""
    try:
        raw = await _chat_before_deadline(
            deadline_monotonic=deadline_monotonic,
            job_id=job_id,
            request_id=request_id,
            call_reason="city_clarification_polish",
            system=system,
            user=f"用户原文：{user_query}",
            role="writer",
            temperature=0.3,
            json_mode=True,
        )
        data = json.loads(raw)
        message = str(data.get("message", "")).strip()
    except Exception:
        logger.exception("city clarification polish failed")
        return CITY_CLARIFICATION_FALLBACK_MESSAGE

    if not message or "城市" not in message:
        return CITY_CLARIFICATION_FALLBACK_MESSAGE
    return message[:160]


def _classify_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, WriterRelayError) and exc.code in {
        "WRITER_CAPACITY_BUSY",
        "WRITER_ENDPOINTS_UNAVAILABLE",
    }:
        return exc.code, "服务暂时不可用，请稍后再试"
    if isinstance(exc, PublishGateError):
        return "PUBLISH_GATE_FAILED", PUBLISH_FAILURE_FALLBACK_MESSAGE
    if isinstance(exc, SafeRenderError):
        return "SAFE_RENDER_FAILED", "暂时无法生成可用行程，请稍后再试"
    message = str(exc) or exc.__class__.__name__
    lowered = message.lower()
    if "llm" in lowered or "gemini" in lowered or "openai" in lowered:
        return "LLM_ERROR", "规划失败，请稍后重试"
    if "database" in lowered or "sql" in lowered or "asyncpg" in lowered:
        return "DB_ERROR", "规划失败，请稍后重试"
    return "WORKFLOW_ERROR", "规划失败，请稍后重试"


def _structured_trip_request_from_job(job: TripJobRecord) -> TripRequest | None:
    if job.trip_request_json is None:
        return None
    try:
        return TripRequest(**job.trip_request_json)
    except Exception as exc:
        raise ValueError("invalid trip_request_json on async trip job") from exc


class TripWorker:
    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()

    async def run(self) -> None:
        settings = get_settings()
        logger.info(
            "trip worker started concurrency=%s timeout=%ss",
            settings.trip_worker_concurrency,
            settings.trip_job_timeout_seconds,
        )
        next_stale_sweep = 0.0
        try:
            while not self._stop.is_set():
                try:
                    self._tasks = {task for task in self._tasks if not task.done()}
                    now = time.monotonic()
                    if now >= next_stale_sweep:
                        expired = await expire_stale_trip_jobs(
                            timeout_seconds=settings.trip_job_timeout_seconds,
                        )
                        if expired:
                            logger.warning("trip worker expired stale jobs count=%s", expired)
                        next_stale_sweep = (
                            now + settings.trip_stale_sweep_interval_seconds
                        )

                    if len(self._tasks) >= settings.trip_worker_concurrency:
                        await asyncio.sleep(POLL_INTERVAL_SECONDS)
                        continue

                    job = await claim_next_pending_trip_job(
                        max_concurrency=settings.trip_worker_concurrency,
                    )
                    if job is None:
                        await asyncio.sleep(POLL_INTERVAL_SECONDS)
                        continue

                    task = asyncio.create_task(self._execute_job(job))
                    self._tasks.add(task)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("trip worker loop failed; retrying")
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
        finally:
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)
            logger.info("trip worker stopped")

    async def stop(self) -> None:
        self._stop.set()

    async def _execute_job(self, job: TripJobRecord) -> None:
        settings = get_settings()
        job_id = job.job_id
        logger.info("trip worker executing job_id=%s", job_id)
        execute_t0 = time.monotonic()
        workflow_deadline_monotonic = (
            execute_t0 + settings.trip_job_timeout_seconds
        )
        runtime_metrics: dict[str, int] = {}
        queue_wait_ms = _datetime_delta_ms(job.started_time, job.created_time)
        if queue_wait_ms is not None:
            runtime_metrics["queue_wait_ms"] = queue_wait_ms
        city_notice_code: str | None = None
        pending_current_stage: str | None = None
        pending_success_event: dict | None = None
        structured_trip_request = _structured_trip_request_from_job(job)
        structured_pre_gate_done = False
        must_include_resolution: MustIncludeResolution | None = None
        persisted_trip_request_json: dict | None = None
        failed_draft_snapshot: list[dict] = []

        async def on_writer_output(plans) -> None:
            nonlocal failed_draft_snapshot
            snapshot = project_failed_draft_plans(plans)
            if snapshot:
                # Keep only the latest non-empty Writer projection in memory.
                # Nothing is persisted before a final FAILED/TIMEOUT state.
                failed_draft_snapshot = snapshot

        async def persist_captured_failed_draft() -> None:
            if not failed_draft_snapshot:
                return
            try:
                await persist_failed_draft_if_eligible(
                    job_id,
                    failed_draft_snapshot,
                )
            except Exception:
                # Draft capture is auxiliary and must not rewrite terminal job
                # state or alter Writer/Review/Publish Gate behavior.
                logger.warning(
                    "trip failed-draft persistence failed job_id=%s",
                    job_id,
                    exc_info=True,
                )

        async def on_stage(stage: str) -> None:
            nonlocal pending_current_stage
            pending_current_stage = stage

        async def flush_observation_writes() -> None:
            # P1 stage writes are awaited inline. Kept as a local compatibility
            # hook for the existing terminal flow and tests.
            return None

        async def on_stage_event(
            stage: str,
            status: str,
            metadata: dict,
        ) -> None:
            nonlocal pending_current_stage, pending_success_event
            event_metadata = dict(metadata)
            if stage == "PERSISTING" and status in {"SUCCESS", "FAILED"}:
                event_metadata.update(runtime_metrics)
            attempt = int(event_metadata.get("attempt") or 1)
            publish_retry_round = int(
                event_metadata.get("publish_retry_round") or 0
            )
            if status == "SUCCESS" and stage != "PERSISTING":
                pending_success_event = {
                    "stage": stage,
                    "attempt": attempt,
                    "publish_retry_round": publish_retry_round,
                    "latency_ms": (
                        int(event_metadata["latency_ms"])
                        if event_metadata.get("latency_ms") is not None
                        else None
                    ),
                    "metadata": event_metadata,
                }
                return
            if status == "RUNNING" and pending_current_stage == stage:
                pending_current_stage = None
                previous = pending_success_event
                pending_success_event = None
                await record_trip_job_stage_started(
                    job_id,
                    stage=stage,
                    attempt=attempt,
                    publish_retry_round=publish_retry_round,
                    metadata=event_metadata,
                    previous_success_event=previous,
                )
                return
            if pending_success_event is not None:
                previous = pending_success_event
                pending_success_event = None
                await record_trip_job_step_event(
                    job_id,
                    stage=str(previous.get("stage") or ""),
                    status="SUCCESS",
                    attempt=int(previous.get("attempt") or 1),
                    publish_retry_round=int(
                        previous.get("publish_retry_round") or 0
                    ),
                    latency_ms=previous.get("latency_ms"),
                    metadata=previous.get("metadata") or {},
                )
            if status == "RUNNING":
                await record_trip_job_step_event(
                    job_id,
                    stage=stage,
                    status=status,
                    attempt=attempt,
                    publish_retry_round=publish_retry_round,
                    latency_ms=(
                        int(event_metadata["latency_ms"])
                        if event_metadata.get("latency_ms") is not None
                        else None
                    ),
                    metadata=event_metadata,
                )
                return
            await flush_observation_writes()
            await record_trip_job_step_event(
                job_id,
                stage=stage,
                status=status,
                attempt=attempt,
                publish_retry_round=publish_retry_round,
                latency_ms=(
                    int(event_metadata["latency_ms"])
                    if event_metadata.get("latency_ms") is not None
                    else None
                ),
                metadata=event_metadata,
            )

        async def maybe_create_initial_city_batch(
            decision: CityGateDecision,
            trip_request: TripRequest,
        ) -> None:
            if decision.status != CITY_PREPARING or decision.city_id is None:
                return
            active_batch = await get_active_city_batch()
            if active_batch is not None:
                logger.info(
                    "skip initial city batch job_id=%s city_id=%s active_batch_id=%s",
                    job_id,
                    decision.city_id,
                    active_batch.batch_id,
                )
                return
            try:
                batch = await create_city_crawl_batch(
                    city_id=decision.city_id,
                    trigger_source="demand",
                    reason="first_request",
                    preferences=trip_request.preferences,
                    limit_per_keyword=settings.city_batch_limit_per_keyword,
                )
            except CityBatchActiveError:
                logger.info(
                    "initial city batch race lost job_id=%s city_id=%s",
                    job_id,
                    decision.city_id,
                )
                return
            logger.info(
                "initial city batch created job_id=%s city_id=%s batch_id=%s",
                job_id,
                decision.city_id,
                batch.batch_id,
            )

        async def persist_trip_request_after_city_gate(
            trip_request: TripRequest,
            decision: CityGateDecision,
        ) -> None:
            nonlocal city_notice_code, persisted_trip_request_json
            city_notice_code = decision.city_notice_code
            trip_request_json = trip_request.model_dump()
            if city_notice_code:
                trip_request_json["city_notice_code"] = city_notice_code
            if not decision.allowed:
                trip_request_json.update(_city_gate_rejection_metadata(decision))
            update_trip_request_t0 = time.monotonic()
            await update_trip_job_trip_request(job_id, trip_request_json)
            persisted_trip_request_json = trip_request_json
            runtime_metrics["trip_request_update_latency_ms"] = _elapsed_ms(
                update_trip_request_t0
            )

        async def pre_gate_structured_trip_request(trip_request: TripRequest) -> None:
            nonlocal structured_pre_gate_done, must_include_resolution
            city_gate_t0 = time.monotonic()
            decision = await gate_async_trip_request(
                trip_request,
                source=job.source,
                request_id=job.request_id,
                conversation_id=job.conversation_id,
                raw_query=job.user_query,
            )
            runtime_metrics["city_gate_latency_ms"] = _elapsed_ms(city_gate_t0)
            await persist_trip_request_after_city_gate(trip_request, decision)
            structured_pre_gate_done = True
            if not decision.allowed:
                await maybe_create_initial_city_batch(decision, trip_request)
                raise CityGateRejected(decision)
            resolution = await match_and_record_must_include(
                trip_request,
                source="user_must_include",
                request_id=job.request_id,
                conversation_id=job.conversation_id,
                countable=job.source not in NON_DEMAND_SOURCES,
            )
            if getattr(settings, "must_include_anchor_enabled", False):
                must_include_resolution = resolution

        async def on_trip_request(trip_request: TripRequest) -> None:
            nonlocal city_notice_code, persisted_trip_request_json
            callback_t0 = time.monotonic()
            try:
                if structured_pre_gate_done:
                    trip_request_json = trip_request.model_dump()
                    if city_notice_code:
                        trip_request_json["city_notice_code"] = city_notice_code
                    if trip_request_json != persisted_trip_request_json:
                        update_trip_request_t0 = time.monotonic()
                        await update_trip_job_trip_request(job_id, trip_request_json)
                        persisted_trip_request_json = trip_request_json
                        runtime_metrics["trip_request_update_latency_ms"] = _elapsed_ms(
                            update_trip_request_t0
                        )
                    return

                city_gate_t0 = time.monotonic()
                decision = await gate_async_trip_request(
                    trip_request,
                    source=job.source,
                    request_id=job.request_id,
                    conversation_id=job.conversation_id,
                    raw_query=job.user_query,
                )
                runtime_metrics["city_gate_latency_ms"] = _elapsed_ms(city_gate_t0)
                await persist_trip_request_after_city_gate(trip_request, decision)
                if not decision.allowed:
                    await maybe_create_initial_city_batch(decision, trip_request)
                    raise CityGateRejected(decision)
            finally:
                runtime_metrics["trip_request_callback_latency_ms"] = _elapsed_ms(
                    callback_t0
                )

        try:
            recent_history_t0 = time.monotonic()
            recent_place_id_sets = await get_recent_successful_plan_place_ids(
                source=job.source,
                conversation_id=job.conversation_id,
            )
            runtime_metrics["recent_history_query_latency_ms"] = _elapsed_ms(
                recent_history_t0
            )
            runtime_metrics["pre_workflow_latency_ms"] = _elapsed_ms(execute_t0)
            if (
                structured_trip_request is not None
                and getattr(settings, "place_demand_enabled", False)
            ):
                await pre_gate_structured_trip_request(structured_trip_request)
            remaining_seconds = workflow_deadline_monotonic - time.monotonic()
            if remaining_seconds <= 0:
                raise asyncio.TimeoutError("trip hard deadline exhausted before workflow")
            with llm_call_context(
                job_id=job_id,
                request_id=job.request_id,
                workflow_deadline_monotonic=workflow_deadline_monotonic,
            ):
                bind_observation_sink(job_id)
                result = await asyncio.wait_for(
                    run_trip_workflow(
                        job.user_query,
                        trip_request=structured_trip_request,
                        recent_place_id_sets=recent_place_id_sets,
                        on_stage=on_stage,
                        on_stage_event=on_stage_event,
                        on_trip_request=on_trip_request,
                        on_writer_output=on_writer_output,
                        must_include_resolution=must_include_resolution,
                        workflow_deadline_monotonic=workflow_deadline_monotonic,
                    ),
                    timeout=remaining_seconds,
                )
            if pending_success_event is not None:
                await flush_observation_writes()
                previous = pending_success_event
                pending_success_event = None
                await record_trip_job_step_event(
                    job_id,
                    stage=str(previous.get("stage") or ""),
                    status="SUCCESS",
                    attempt=int(previous.get("attempt") or 1),
                    publish_retry_round=int(
                        previous.get("publish_retry_round") or 0
                    ),
                    latency_ms=previous.get("latency_ms"),
                    metadata=previous.get("metadata") or {},
                )
        except asyncio.TimeoutError:
            logger.warning("trip worker timeout job_id=%s", job_id)
            await flush_observation_writes()
            flushed = pop_job_observation_flush(job_id) or {}
            summary_blob = {
                "llm_call_count_total": int(flushed.get("llm_call_count_total") or 0),
                "llm_error_count_total": int(flushed.get("llm_error_count_total") or 0),
                "termination_reason": "workflow_cancelled",
                "response_received": False,
            }
            detail = json.dumps(summary_blob, ensure_ascii=False)
            observation_meta = {
                "error": "trip worker timeout",
                "llm_observation": flushed or None,
            }
            await mark_trip_job_timeout(
                job_id,
                error_detail=detail,
                step_metadata=observation_meta,
                ensure_terminal_step=True,
            )
            await persist_captured_failed_draft()
            return
        except asyncio.CancelledError:
            logger.warning("trip worker cancelled job_id=%s", job_id)
            await flush_observation_writes()
            flushed = pop_job_observation_flush(job_id) or {}
            summary_blob = {
                "llm_call_count_total": int(flushed.get("llm_call_count_total") or 0),
                "llm_error_count_total": int(flushed.get("llm_error_count_total") or 0),
                "termination_reason": "workflow_cancelled",
                "response_received": False,
            }
            detail = json.dumps(summary_blob, ensure_ascii=False)
            observation_meta = {
                "error": "trip worker cancelled",
                "llm_observation": flushed or None,
            }
            await mark_trip_job_failed(
                job_id,
                error_code="CANCELLED",
                error_message="规划已取消",
                error_detail=detail,
                step_metadata=observation_meta,
                ensure_terminal_step=True,
            )
            await persist_captured_failed_draft()
            raise
        except CityGateRejected as exc:
            logger.info(
                "trip worker rejected job_id=%s error_code=%s",
                job_id,
                exc.decision.status,
            )
            # Always drop job-owned sink on non-success exits too.
            pop_job_observation_flush(job_id)
            await flush_observation_writes()
            if exc.decision.status == CITY_CLARIFICATION_REQUIRED:
                message = await _polish_city_clarification_message(
                    job.user_query,
                    deadline_monotonic=workflow_deadline_monotonic,
                    job_id=job_id,
                    request_id=job.request_id,
                )
                await mark_trip_job_rejected_with_message(
                    job_id,
                    error_code=exc.decision.status,
                    error_message=message,
                )
            else:
                await mark_trip_job_rejected(
                    job_id,
                    error_code=exc.decision.status,
                )
            return
        except Exception as exc:
            logger.exception("trip worker failed job_id=%s", job_id)
            await flush_observation_writes()
            flushed = pop_job_observation_flush(job_id) or {}
            summary_blob = {
                "error_type": type(exc).__name__,
                "llm_call_count_total": int(
                    flushed.get("llm_call_count_total") or 0
                ),
                "llm_error_count_total": int(
                    flushed.get("llm_error_count_total") or 0
                ),
                "termination_reason": "workflow_failed",
                "response_received": bool(
                    flushed.get("llm_response_received_count")
                ),
            }
            detail = json.dumps(summary_blob, ensure_ascii=False)
            observation_meta = {
                "error": str(exc),
                "llm_observation": flushed or None,
            }
            if isinstance(exc, WriterRelayError):
                observation_meta["writer_relay_capacity"] = {
                    "code": exc.code,
                    "waited_ms": exc.waited_ms,
                    "endpoints": [
                        {
                            "name": item.name,
                            "participation": item.participation,
                            "circuit_state": item.circuit_state,
                            "inflight": item.inflight,
                            "cap": item.cap,
                        }
                        for item in exc.snapshot
                    ],
                }
            error_code, error_message = _classify_error(exc)
            if isinstance(exc, PublishGateError):
                error_message = await _polish_publish_failure_message(
                    exc,
                    deadline_monotonic=workflow_deadline_monotonic,
                    job_id=job_id,
                    request_id=job.request_id,
                )
            await mark_trip_job_failed(
                job_id,
                error_code=error_code,
                error_message=error_message,
                error_detail=detail,
                step_metadata=observation_meta,
                ensure_terminal_step=True,
            )
            await persist_captured_failed_draft()
            return

        # Success path: clear job sink after workflow returns.
        pop_job_observation_flush(job_id)
        reply_text = format_plans_markdown(result)
        result_type = result.result_type
        plan_count = len(result.plans)

        try:
            await _mark_trip_job_success_with_retry(
                job_id=job_id,
                reply_text=reply_text,
                plan_count=plan_count,
                result_type=result_type,
                result_record_id=result.record_id,
                trip_request_json={
                    **result.trip_request.model_dump(),
                    **({"city_notice_code": city_notice_code} if city_notice_code else {}),
                },
            )
        except Exception as exc:
            logger.exception("trip worker persistence failed job_id=%s", job_id)
            pop_job_observation_flush(job_id)
            error_code, error_message = _classify_error(exc)
            await mark_trip_job_failed(
                job_id,
                error_code=error_code,
                error_message=error_message,
                error_detail=str(exc),
            )
            await persist_captured_failed_draft()
            return
        logger.info(
            "trip worker success job_id=%s result_type=%s plan_count=%s",
            job_id,
            result_type,
            plan_count,
        )


async def _mark_trip_job_success_with_retry(
    *,
    job_id: str,
    reply_text: str,
    plan_count: int,
    result_type: str,
    result_record_id: int | None,
    trip_request_json: dict,
) -> None:
    last_error: Exception | None = None
    for attempt in range(1, SUCCESS_PERSIST_RETRIES + 1):
        try:
            await mark_trip_job_success(
                job_id,
                reply_text=reply_text,
                plan_count=plan_count,
                result_type=result_type,
                result_record_id=result_record_id,
                trip_request_json=trip_request_json,
            )
            return
        except Exception as exc:
            last_error = exc
            if attempt >= SUCCESS_PERSIST_RETRIES:
                break
            logger.warning(
                "trip worker success persistence retry job_id=%s attempt=%s error=%s",
                job_id,
                attempt,
                exc,
            )
            await asyncio.sleep(0.5 * attempt)
    assert last_error is not None
    raise last_error
