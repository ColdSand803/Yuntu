"""Internal crawl HTTP routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from src.internal.auth import verify_internal_token
from src.jobs.crawl_store import (
    create_crawl_run,
    get_active_duplicate_run,
    get_crawl_inventory,
    get_crawl_run,
    get_recent_duplicate_inventory,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", dependencies=[Depends(verify_internal_token)])


class CrawlRunCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    city: str
    keyword: str
    limit: int = Field(default=10, ge=1, le=50)
    run_extract: bool = Field(default=False, alias="runExtract")
    refresh_summary: bool = Field(default=False, alias="refreshSummary")
    trigger_source: str = "hermes"
    force: bool = False
    confirm_duplicate: bool = False
    recent_hours: int = 24


class CrawlRunCreateResponse(BaseModel):
    success: bool = True
    run_id: int
    status: str
    message: str


class CrawlRunStepResponse(BaseModel):
    step_name: str
    status: str
    raw_count: int
    insert_count: int
    duplicate_count: int
    failed_count: int
    error_code: str | None
    error_message: str | None
    started_time: str | None
    finished_time: str | None


class CrawlRunStatusResponse(BaseModel):
    success: bool = True
    run_id: int
    platform: str
    city: str | None
    keyword: str | None
    status: str
    raw_count: int
    insert_count: int
    duplicate_count: int
    failed_count: int
    error_code: str | None
    error_message: str | None
    started_time: str | None
    finished_time: str | None
    steps: list[CrawlRunStepResponse]


class CrawlInventoryKeywordResponse(BaseModel):
    keyword: str
    raw_count: int
    parsed_count: int
    pending_count: int
    failed_count: int
    latest_raw_time: str | None
    latest_success_run_id: int | None
    latest_success_time: str | None


class CrawlInventoryCityResponse(BaseModel):
    city: str
    raw_count: int
    parsed_count: int
    pending_count: int
    failed_count: int
    summary_count: int
    latest_success_run_id: int | None
    latest_success_keyword: str | None
    latest_success_time: str | None
    keywords: list[CrawlInventoryKeywordResponse]


class CrawlInventoryResponse(BaseModel):
    success: bool = True
    cities: list[CrawlInventoryCityResponse]


def _iso(dt) -> str | None:
    if dt is None:
        return None
    return dt.isoformat().replace("+00:00", "Z")


@router.get("/crawl/inventory", response_model=CrawlInventoryResponse)
async def get_crawl_inventory_endpoint(city: str | None = None) -> CrawlInventoryResponse:
    city_filter = city.strip() if city else None
    cities = await get_crawl_inventory(city_filter=city_filter)
    return CrawlInventoryResponse(
        cities=[
            CrawlInventoryCityResponse(
                city=c.city,
                raw_count=c.raw_count,
                parsed_count=c.parsed_count,
                pending_count=c.pending_count,
                failed_count=c.failed_count,
                summary_count=c.summary_count,
                latest_success_run_id=c.latest_success_run_id,
                latest_success_keyword=c.latest_success_keyword,
                latest_success_time=_iso(c.latest_success_time),
                keywords=[
                    CrawlInventoryKeywordResponse(
                        keyword=kw.keyword,
                        raw_count=kw.raw_count,
                        parsed_count=kw.parsed_count,
                        pending_count=kw.pending_count,
                        failed_count=kw.failed_count,
                        latest_raw_time=_iso(kw.latest_raw_time),
                        latest_success_run_id=kw.latest_success_run_id,
                        latest_success_time=_iso(kw.latest_success_time),
                    )
                    for kw in c.keywords
                ],
            )
            for c in cities
        ]
    )


@router.post("/xhs/crawl/run", response_model=CrawlRunCreateResponse)
async def create_crawl_run_endpoint(req: CrawlRunCreateRequest):
    city = req.city.strip()
    keyword = req.keyword.strip()
    if not city or not keyword:
        raise HTTPException(status_code=400, detail="city and keyword are required")
    if req.refresh_summary and not req.run_extract:
        raise HTTPException(
            status_code=400,
            detail="refresh_summary requires run_extract=true",
        )

    trigger_source = req.trigger_source.strip() or "hermes"
    if trigger_source not in {"manual", "hermes", "cron"}:
        raise HTTPException(
            status_code=400,
            detail="trigger_source must be one of: manual, hermes, cron",
        )

    if not 1 <= req.recent_hours <= 168:
        raise HTTPException(
            status_code=400,
            detail="recent_hours must be between 1 and 168",
        )

    # Active run check — not bypassable by force or confirm_duplicate.
    active = await get_active_duplicate_run(city, keyword)
    if active.found:
        logger.info(
            "active run blocked city=%s keyword=%s run_id=%s status=%s",
            city, keyword, active.run_id, active.status,
        )
        return JSONResponse(
            status_code=409,
            content={
                "success": False,
                "need_confirm": False,
                "reason": "DUPLICATE_ACTIVE_RUN",
                "message": "该城市和关键词已有采集任务正在排队或执行，请等待完成",
                "city": city,
                "keyword": keyword,
                "active_run_id": active.run_id,
                "active_run_status": active.status,
            },
        )

    # Recent inventory check — bypassable by force or confirm_duplicate.
    if not req.force and not req.confirm_duplicate:
        dup = await get_recent_duplicate_inventory(city, keyword, req.recent_hours)
        if dup.found:
            logger.info(
                "duplicate crawl blocked city=%s keyword=%s recent_hours=%s",
                city, keyword, req.recent_hours,
            )
            return JSONResponse(
                status_code=409,
                content={
                    "success": False,
                    "need_confirm": True,
                    "reason": "DUPLICATE_RECENT_INVENTORY",
                    "message": "该城市和关键词近期已有采集库存，请确认是否继续补采",
                    "city": city,
                    "keyword": keyword,
                    "recent_hours": req.recent_hours,
                    "inventory": {
                        "raw_count": dup.raw_count,
                        "parsed_count": dup.parsed_count,
                        "pending_count": dup.pending_count,
                        "failed_count": dup.failed_count,
                        "summary_count": dup.summary_count,
                        "latest_success_run_id": dup.latest_success_run_id,
                        "latest_success_time": _iso(dup.latest_success_time),
                        "latest_raw_time": _iso(dup.latest_raw_time),
                    },
                },
            )

    run_id = await create_crawl_run(
        city=city,
        keyword=keyword,
        limit=req.limit,
        run_extract=req.run_extract,
        refresh_summary=req.refresh_summary,
        trigger_source=trigger_source,
    )
    logger.info("created crawl run_id=%s city=%s keyword=%s", run_id, city, keyword)
    return CrawlRunCreateResponse(
        run_id=run_id,
        status="PENDING",
        message="采集任务已创建",
    )


@router.get("/crawl/runs/{run_id}", response_model=CrawlRunStatusResponse)
async def get_crawl_run_endpoint(run_id: int) -> CrawlRunStatusResponse:
    run = await get_crawl_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    return CrawlRunStatusResponse(
        run_id=run.run_id,
        platform=run.platform,
        city=run.city,
        keyword=run.keyword,
        status=run.status,
        raw_count=run.raw_count,
        insert_count=run.insert_count,
        duplicate_count=run.duplicate_count,
        failed_count=run.failed_count,
        error_code=run.error_code,
        error_message=run.error_message,
        started_time=_iso(run.started_time),
        finished_time=_iso(run.finished_time),
        steps=[
            CrawlRunStepResponse(
                step_name=step.step_name,
                status=step.status,
                raw_count=step.raw_count,
                insert_count=step.insert_count,
                duplicate_count=step.duplicate_count,
                failed_count=step.failed_count,
                error_code=step.error_code,
                error_message=step.error_message,
                started_time=_iso(step.started_time),
                finished_time=_iso(step.finished_time),
            )
            for step in run.steps
        ],
    )
