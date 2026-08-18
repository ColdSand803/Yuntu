"""Background worker for internal XHS crawl runs."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from src.config import get_settings
from src.jobs.crawl_metrics import StepMetrics, parse_step_metrics
from src.jobs.crawl_store import (
    abort_crawl_run,
    claim_next_crawl_run,
    finalize_crawl_run,
    get_crawl_run,
    mark_step_finished,
    mark_step_running,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 2.0
ROOT = Path(__file__).resolve().parents[2]
PROC_TERMINATE_TIMEOUT_SECONDS = 5


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


class CrawlWorker:
    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._current_task: asyncio.Task | None = None
        self._active_proc: asyncio.subprocess.Process | None = None
        self._active_run_id: int | None = None
        self._active_step_name: str | None = None
        self._proc_lock = asyncio.Lock()

    async def run(self) -> None:
        logger.info("crawl worker started")
        try:
            while not self._stop.is_set():
                if self._current_task and self._current_task.done():
                    if self._current_task.cancelled():
                        logger.warning("crawl worker task was cancelled")
                    else:
                        exc = self._current_task.exception()
                        if exc is not None:
                            logger.error(
                                "crawl worker task ended with error",
                                exc_info=(type(exc), exc, exc.__traceback__),
                            )
                    self._current_task = None

                if self._current_task and not self._current_task.done():
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue

                run_id = await claim_next_crawl_run()
                if run_id is None:
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue

                self._current_task = asyncio.create_task(self._execute_run(run_id))
        finally:
            if self._current_task and not self._current_task.done():
                self._current_task.cancel()
                try:
                    await self._current_task
                except asyncio.CancelledError:
                    pass
            await self._terminate_active_proc()
            logger.info("crawl worker stopped")

    async def stop(self) -> None:
        self._stop.set()
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass
        await self._terminate_active_proc()

    async def _execute_run(self, run_id: int) -> None:
        run = await get_crawl_run(run_id)
        if run is None:
            return

        logger.info(
            "crawl worker executing run_id=%s city=%s keyword=%s",
            run_id,
            run.city,
            run.keyword,
        )

        try:
            crawl_ok = await self._run_step(
                run_id,
                "CRAWL",
                [
                    sys.executable,
                    "-m",
                    "scripts.crawl",
                    "--city",
                    run.city or "重庆",
                    "--keyword",
                    run.keyword or "",
                    "--limit",
                    str(await self._fetch_limit_count(run_id)),
                    "--crawl-run-id",
                    str(run_id),
                ],
                get_settings().crawl_subprocess_timeout_seconds,
            )
            if not crawl_ok:
                await finalize_crawl_run(run_id)
                return

            if run.run_extract:
                extract_ok = await self._run_step(
                    run_id,
                    "EXTRACT",
                    [
                        sys.executable,
                        "-m",
                        "scripts.extract",
                        "--limit",
                        str(await self._fetch_limit_count(run_id)),
                        "--crawl-run-id",
                        str(run_id),
                    ],
                    get_settings().extract_subprocess_timeout_seconds,
                )
                if not extract_ok:
                    await finalize_crawl_run(run_id)
                    return

                poi_resolve_ok = await self._run_step(
                    run_id,
                    "POI_RESOLVE",
                    [
                        sys.executable,
                        "-m",
                        "scripts.poi_resolve_for_run",
                        "--crawl-run-id",
                        str(run_id),
                    ],
                    get_settings().poi_resolve_timeout_seconds,
                )
                if not poi_resolve_ok:
                    await finalize_crawl_run(run_id)
                    return

            if run.refresh_summary:
                refresh_ok = await self._run_step(
                    run_id,
                    "REFRESH_SUMMARY",
                    [
                        sys.executable,
                        "-m",
                        "scripts.refresh_summary",
                        "--city",
                        run.city or "重庆",
                    ],
                    get_settings().refresh_summary_timeout_seconds,
                )
                if not refresh_ok:
                    await finalize_crawl_run(run_id)
                    return

            await finalize_crawl_run(run_id)
            logger.info("crawl worker finished run_id=%s", run_id)
        except asyncio.CancelledError:
            await self._terminate_active_proc()
            await abort_crawl_run(
                run_id,
                step_name=self._active_step_name,
                error_code="TIMEOUT",
                error_message="采集任务已取消",
                step_status="TIMEOUT",
            )
            raise
        except Exception as exc:
            await self._terminate_active_proc()
            logger.exception("crawl worker failed run_id=%s", run_id)
            await abort_crawl_run(
                run_id,
                step_name=self._active_step_name,
                error_code="WORKER_ERROR",
                error_message=str(exc) or exc.__class__.__name__,
                step_status="FAILED",
            )

    async def _fetch_limit_count(self, run_id: int) -> int:
        from sqlalchemy import text

        from src.pipeline.db import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                text("SELECT limit_count FROM travel_crawl_run WHERE id = :run_id"),
                {"run_id": run_id},
            )
            row = result.one_or_none()
            return int(row.limit_count) if row else 10

    async def _run_step(
        self,
        run_id: int,
        step_name: str,
        command: list[str],
        timeout_seconds: int,
    ) -> bool:
        await mark_step_running(run_id, step_name)
        self._active_run_id = run_id
        self._active_step_name = step_name

        env = os.environ.copy()

        proc: asyncio.subprocess.Process | None = None
        stdout_bytes = b""
        stderr_bytes = b""
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
            if proc is not None:
                await self._terminate_proc(proc)
            await mark_step_finished(
                run_id,
                step_name,
                status="TIMEOUT",
                error_code="TIMEOUT",
                error_message=f"{step_name} 执行超时",
            )
            self._active_run_id = None
            self._active_step_name = None
            return False
        except asyncio.CancelledError:
            if proc is not None:
                await self._terminate_proc(proc)
            raise
        finally:
            async with self._proc_lock:
                if proc is not None and self._active_proc is proc:
                    self._active_proc = None

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        stdout_summary = _sanitize_summary(stdout)
        stderr_summary = _sanitize_summary(stderr)
        metrics = parse_step_metrics(step_name, stdout, stderr)

        tikhub_error = _detect_tikhub_error(stdout, stderr)
        if tikhub_error:
            await mark_step_finished(
                run_id,
                step_name,
                status="FAILED",
                error_code=tikhub_error,
                error_message=f"TikHub request failed: {tikhub_error}",
                stdout_summary=stdout_summary,
                stderr_summary=stderr_summary,
                metrics=metrics,
            )
            self._active_run_id = None
            self._active_step_name = None
            return False

        if proc is not None and proc.returncode != 0:
            await mark_step_finished(
                run_id,
                step_name,
                status="FAILED",
                error_code="STEP_FAILED",
                error_message=f"{step_name} 执行失败",
                stdout_summary=stdout_summary,
                stderr_summary=stderr_summary,
                metrics=metrics,
            )
            self._active_run_id = None
            self._active_step_name = None
            return False

        await mark_step_finished(
            run_id,
            step_name,
            status="SUCCESS",
            stdout_summary=stdout_summary,
            stderr_summary=stderr_summary,
            metrics=metrics,
        )
        self._active_run_id = None
        self._active_step_name = None
        return True

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
            await asyncio.wait_for(proc.wait(), timeout=PROC_TERMINATE_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
