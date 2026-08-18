"""Serial city crawl batch worker for v0.5 Stage 4."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Awaitable, TypeVar

from src.config import get_settings
from src.jobs.city_batch_store import (
    CityBatchRecord,
    CityBatchItemRecord,
    claim_next_city_batch,
    expire_stale_city_batches,
    finish_city_batch,
    get_city_batch,
    heartbeat_city_batch,
    mark_city_batch_item_finished,
    mark_city_batch_item_running,
    mark_city_refresh_completed,
    update_city_batch_stage,
)
from src.jobs.city_quality import inspect_city_quality
from src.jobs.crawl_metrics import parse_step_metrics
from src.jobs.crawl_store import (
    create_crawl_run,
    finalize_crawl_run,
    get_crawl_run,
    mark_step_finished,
    mark_step_running,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 2.0
STALE_SWEEP_INTERVAL_SECONDS = 30.0
ROOT = Path(__file__).resolve().parents[2]
T = TypeVar("T")


def _sanitize_summary(text: str, limit: int = 2000) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "..."


def _detect_tikhub_error(stdout: str, stderr: str) -> str | None:
    combined = f"{stdout}\n{stderr}".lower()
    for code in (
        "tikhub_auth_failed",
        "tikhub_balance_insufficient",
        "tikhub_rate_limited",
        "tikhub_response_invalid",
        "tikhub_upstream_failed",
    ):
        if code in combined:
            return code.upper()
    return None


class CityBatchWorker:
    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._current_task: asyncio.Task | None = None
        self._active_proc: asyncio.subprocess.Process | None = None
        self._proc_lock = asyncio.Lock()

    async def run(self) -> None:
        settings = get_settings()
        logger.info("city batch worker started")
        next_stale_sweep = 0.0
        try:
            while not self._stop.is_set():
                if self._current_task and self._current_task.done():
                    if self._current_task.cancelled():
                        logger.warning("city batch worker task was cancelled")
                    else:
                        exc = self._current_task.exception()
                        if exc is not None:
                            logger.error(
                                "city batch worker task ended with error",
                                exc_info=(type(exc), exc, exc.__traceback__),
                            )
                    self._current_task = None

                now = asyncio.get_running_loop().time()
                if now >= next_stale_sweep:
                    expired = await expire_stale_city_batches(
                        timeout_seconds=settings.city_batch_timeout_seconds,
                    )
                    if expired:
                        logger.warning("expired stale city batches count=%s", expired)
                    next_stale_sweep = now + STALE_SWEEP_INTERVAL_SECONDS

                if self._current_task and not self._current_task.done():
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue

                batch_id = await claim_next_city_batch()
                if batch_id is None:
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue
                self._current_task = asyncio.create_task(self._execute_batch(batch_id))
        finally:
            if self._current_task and not self._current_task.done():
                self._current_task.cancel()
                try:
                    await self._current_task
                except asyncio.CancelledError:
                    pass
            await self._terminate_active_proc()
            logger.info("city batch worker stopped")

    async def stop(self) -> None:
        self._stop.set()
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass
        await self._terminate_active_proc()

    async def _execute_batch(self, batch_id: int) -> None:
        batch = await get_city_batch(batch_id)
        if batch is None:
            return

        logger.info(
            "city batch executing batch_id=%s city=%s items=%s",
            batch_id,
            batch.canonical_name,
            len(batch.items),
        )
        try:
            fatal_error: str | None = None
            for item in batch.items:
                if item.status != "PENDING":
                    continue
                status = await self._execute_keyword(batch, item)
                if status.startswith("TIKHUB_"):
                    fatal_error = status
                    break

            batch = await get_city_batch(batch_id)
            if batch is None:
                return
            if fatal_error:
                await finish_city_batch(
                    batch_id,
                    status="FAILED",
                    error_code=fatal_error,
                    error_message=f"TikHub request failed: {fatal_error}",
                )
                return

            successful_run_ids = [
                item.crawl_run_id
                for item in batch.items
                if item.status == "SUCCESS" and item.crawl_run_id is not None
            ]
            await self._run_extract(batch, successful_run_ids)
            await self._run_poi_resolve(batch, successful_run_ids)
            await self._run_refresh(batch)
            await self._run_canonical_onboarding(batch, successful_run_ids)
            await self._run_quality(batch)
            await mark_city_refresh_completed(batch.city_id)

            latest = await get_city_batch(batch_id)
            if latest is None:
                return
            if all(item.status == "SUCCESS" for item in latest.items):
                final_status = "SUCCESS"
            else:
                final_status = "PARTIAL_SUCCESS"
            await finish_city_batch(batch_id, status=final_status)
            logger.info("city batch finished batch_id=%s status=%s", batch_id, final_status)
        except asyncio.CancelledError:
            await self._terminate_active_proc()
            await finish_city_batch(
                batch_id,
                status="TIMEOUT",
                error_code="TIMEOUT",
                error_message="city batch task cancelled",
            )
            raise
        except Exception as exc:
            await self._terminate_active_proc()
            logger.exception("city batch failed batch_id=%s", batch_id)
            await finish_city_batch(
                batch_id,
                status="FAILED",
                error_code="WORKER_ERROR",
                error_message=str(exc) or exc.__class__.__name__,
            )

    async def _execute_keyword(
        self,
        batch: CityBatchRecord,
        item: CityBatchItemRecord,
    ) -> str:
        settings = get_settings()
        crawl_run_id = await create_crawl_run(
            city=batch.canonical_name,
            keyword=item.keyword,
            limit=batch.limit_per_keyword,
            run_extract=False,
            refresh_summary=False,
            trigger_source="hermes",
        )
        await mark_city_batch_item_running(item.item_id, crawl_run_id)
        await mark_step_running(crawl_run_id, "CRAWL")
        await heartbeat_city_batch(batch.batch_id)
        command = [
            sys.executable,
            "-m",
            "scripts.crawl",
            "--city",
            batch.canonical_name,
            "--keyword",
            item.keyword,
            "--limit",
            str(batch.limit_per_keyword),
            "--crawl-run-id",
            str(crawl_run_id),
        ]
        result = await self._run_with_periodic_heartbeat(
            batch.batch_id,
            self._run_command(
                command,
                timeout_seconds=settings.crawl_subprocess_timeout_seconds,
            ),
        )
        metrics = parse_step_metrics("CRAWL", result.stdout, result.stderr)
        if result.timed_out:
            await mark_step_finished(
                crawl_run_id,
                "CRAWL",
                status="TIMEOUT",
                error_code="TIMEOUT",
                error_message="crawl timed out",
                stdout_summary=_sanitize_summary(result.stdout),
                stderr_summary=_sanitize_summary(result.stderr),
                metrics=metrics,
            )
            await finalize_crawl_run(crawl_run_id)
            await mark_city_batch_item_finished(
                item.item_id,
                status="TIMEOUT",
                error_code="TIMEOUT",
                error_message="crawl timed out",
            )
            return "TIMEOUT"
        tikhub_error = _detect_tikhub_error(result.stdout, result.stderr)
        if tikhub_error:
            await mark_step_finished(
                crawl_run_id,
                "CRAWL",
                status="FAILED",
                error_code=tikhub_error,
                error_message=f"TikHub request failed: {tikhub_error}",
                stdout_summary=_sanitize_summary(result.stdout),
                stderr_summary=_sanitize_summary(result.stderr),
                metrics=metrics,
            )
            await finalize_crawl_run(crawl_run_id)
            await mark_city_batch_item_finished(
                item.item_id,
                status="FAILED",
                error_code=tikhub_error,
                error_message=f"TikHub request failed: {tikhub_error}",
            )
            return tikhub_error
        if result.returncode != 0:
            await mark_step_finished(
                crawl_run_id,
                "CRAWL",
                status="FAILED",
                error_code="STEP_FAILED",
                error_message="crawl failed",
                stdout_summary=_sanitize_summary(result.stdout),
                stderr_summary=_sanitize_summary(result.stderr),
                metrics=metrics,
            )
            await finalize_crawl_run(crawl_run_id)
            await mark_city_batch_item_finished(
                item.item_id,
                status="FAILED",
                error_code="STEP_FAILED",
                error_message="crawl failed",
            )
            return "FAILED"
        if metrics.insert_count <= 0:
            await mark_step_finished(
                crawl_run_id,
                "CRAWL",
                status="FAILED",
                error_code="NO_DATA",
                error_message="crawl completed with no raw items inserted",
                stdout_summary=_sanitize_summary(result.stdout),
                stderr_summary=_sanitize_summary(result.stderr),
                metrics=metrics,
            )
            await finalize_crawl_run(crawl_run_id)
            await mark_city_batch_item_finished(
                item.item_id,
                status="FAILED",
                error_code="NO_DATA",
                error_message="crawl completed with no raw items inserted",
            )
            return "FAILED"

        await mark_step_finished(
            crawl_run_id,
            "CRAWL",
            status="SUCCESS",
            stdout_summary=_sanitize_summary(result.stdout),
            stderr_summary=_sanitize_summary(result.stderr),
            metrics=metrics,
        )
        await finalize_crawl_run(crawl_run_id)
        run = await get_crawl_run(crawl_run_id)
        item_status = "SUCCESS" if run and run.status == "SUCCESS" else "FAILED"
        await mark_city_batch_item_finished(item.item_id, status=item_status)
        return item_status

    async def _run_extract(self, batch: CityBatchRecord, crawl_run_ids: list[int]) -> None:
        if not crawl_run_ids:
            await update_city_batch_stage(batch.batch_id, "extract", "SKIPPED")
            return
        await update_city_batch_stage(batch.batch_id, "extract", "RUNNING")
        command = [
            sys.executable,
            "-m",
            "scripts.extract",
            "--limit",
            str(len(crawl_run_ids) * batch.limit_per_keyword),
        ]
        for run_id in crawl_run_ids:
            command.extend(["--crawl-run-id", str(run_id)])
        result = await self._run_with_periodic_heartbeat(
            batch.batch_id,
            self._run_command(
                command,
                timeout_seconds=max(
                    get_settings().extract_subprocess_timeout_seconds,
                    len(crawl_run_ids) * batch.limit_per_keyword * 30,
                ),
            ),
        )
        if result.timed_out:
            await update_city_batch_stage(
                batch.batch_id,
                "extract",
                "TIMEOUT",
                error_code="TIMEOUT",
                error_message="extract timed out",
            )
            raise RuntimeError("extract timed out")
        if result.returncode != 0:
            await update_city_batch_stage(
                batch.batch_id,
                "extract",
                "FAILED",
                error_code="EXTRACT_FAILED",
                error_message="extract failed",
            )
            raise RuntimeError("extract failed")
        await update_city_batch_stage(batch.batch_id, "extract", "SUCCESS")

    async def _run_poi_resolve(
        self,
        batch: CityBatchRecord,
        crawl_run_ids: list[int],
    ) -> None:
        if not crawl_run_ids:
            await update_city_batch_stage(batch.batch_id, "poi_resolve", "SKIPPED")
            return
        await update_city_batch_stage(batch.batch_id, "poi_resolve", "RUNNING")
        command = [
            sys.executable,
            "-m",
            "scripts.poi_resolve_for_run",
            "--limit",
            "500",
        ]
        for run_id in crawl_run_ids:
            command.extend(["--crawl-run-id", str(run_id)])
        target_count = len(crawl_run_ids) * batch.limit_per_keyword
        result = await self._run_with_periodic_heartbeat(
            batch.batch_id,
            self._run_command(
                command,
                timeout_seconds=max(
                    get_settings().poi_resolve_timeout_seconds,
                    target_count * 20,
                ),
            ),
        )
        if result.timed_out:
            await update_city_batch_stage(
                batch.batch_id,
                "poi_resolve",
                "TIMEOUT",
                error_code="POI_RESOLVE_TIMEOUT",
                error_message="POI resolve timed out",
            )
            raise RuntimeError("POI resolve timed out")
        if result.returncode != 0:
            await update_city_batch_stage(
                batch.batch_id,
                "poi_resolve",
                "FAILED",
                error_code="POI_RESOLVE_FAILED",
                error_message="POI resolve failed",
            )
            raise RuntimeError("POI resolve failed")
        await update_city_batch_stage(batch.batch_id, "poi_resolve", "SUCCESS")

    async def _run_refresh(self, batch: CityBatchRecord) -> None:
        await update_city_batch_stage(batch.batch_id, "refresh", "RUNNING")
        result = await self._run_with_periodic_heartbeat(
            batch.batch_id,
            self._run_command(
                [
                    sys.executable,
                    "-m",
                    "scripts.refresh_summary",
                    "--city",
                    batch.canonical_name,
                ],
                timeout_seconds=get_settings().refresh_summary_timeout_seconds,
            ),
        )
        if result.timed_out:
            await update_city_batch_stage(
                batch.batch_id,
                "refresh",
                "TIMEOUT",
                error_code="REFRESH_TIMEOUT",
                error_message="refresh summary timed out",
            )
            raise RuntimeError("refresh summary timed out")
        if result.returncode != 0:
            await update_city_batch_stage(
                batch.batch_id,
                "refresh",
                "FAILED",
                error_code="REFRESH_FAILED",
                error_message="refresh summary failed",
            )
            raise RuntimeError("refresh summary failed")
        await update_city_batch_stage(batch.batch_id, "refresh", "SUCCESS")

    async def _run_quality(self, batch: CityBatchRecord) -> None:
        await update_city_batch_stage(batch.batch_id, "quality", "RUNNING")
        await self._run_with_periodic_heartbeat(
            batch.batch_id,
            inspect_city_quality(batch.city_id),
        )
        await update_city_batch_stage(batch.batch_id, "quality", "SUCCESS")

    async def _run_canonical_onboarding(
        self,
        batch: CityBatchRecord,
        crawl_run_ids: list[int],
    ) -> None:
        command = [
            sys.executable,
            "-m",
            "scripts.canonical_onboard",
            "--city",
            batch.canonical_name,
        ]
        for run_id in crawl_run_ids:
            command.extend(["--crawl-run-id", str(run_id)])
        result = await self._run_with_periodic_heartbeat(
            batch.batch_id,
            self._run_command(
                command,
                timeout_seconds=get_settings().poi_resolve_timeout_seconds,
            ),
        )
        if result.timed_out:
            raise RuntimeError("canonical onboarding timed out")
        if result.returncode != 0:
            raise RuntimeError(
                _sanitize_summary(result.stderr) or "canonical onboarding failed"
            )

    async def _run_with_periodic_heartbeat(
        self,
        batch_id: int,
        awaitable: Awaitable[T],
    ) -> T:
        task = asyncio.create_task(awaitable)
        heartbeat_task = asyncio.create_task(
            self._periodic_heartbeat(batch_id, task),
        )
        try:
            return await task
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    async def _periodic_heartbeat(self, batch_id: int, task: asyncio.Task) -> None:
        heartbeat_seconds = max(1, int(get_settings().city_batch_heartbeat_seconds))
        while not task.done():
            await asyncio.sleep(heartbeat_seconds)
            if not task.done():
                await heartbeat_city_batch(batch_id)

    async def _run_command(
        self,
        command: list[str],
        *,
        timeout_seconds: int,
    ) -> "_CommandResult":
        env = os.environ.copy()

        proc: asyncio.subprocess.Process | None = None
        stdout_bytes = b""
        stderr_bytes = b""
        timed_out = False
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(ROOT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            async with self._proc_lock:
                self._active_proc = proc
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            timed_out = True
            if proc is not None:
                await self._terminate_proc(proc)
        finally:
            async with self._proc_lock:
                if proc is not None and self._active_proc is proc:
                    self._active_proc = None
        return _CommandResult(
            returncode=proc.returncode if proc is not None and proc.returncode is not None else -1,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            timed_out=timed_out,
        )

    async def _terminate_active_proc(self) -> None:
        async with self._proc_lock:
            proc = self._active_proc
            self._active_proc = None
        if proc is not None:
            await self._terminate_proc(proc)

    async def _terminate_proc(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()


class _CommandResult:
    def __init__(
        self,
        *,
        returncode: int,
        stdout: str,
        stderr: str,
        timed_out: bool = False,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
