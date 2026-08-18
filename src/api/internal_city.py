"""Internal city supervision and dispatch routes for v0.5 Stage 5."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.config import get_settings
from src.internal.auth import verify_internal_token
from src.jobs.city_batch_store import (
    CityBatchActiveError,
    CityBatchRecord,
    create_city_crawl_batch,
    create_retry_city_crawl_batch,
    get_active_city_batch,
    get_city_batch,
    list_city_batches,
)
from src.jobs.city_keywords import PREFERENCE_EXTENSION_KEYWORDS, city_batch_keywords
from src.jobs.city_quality import inspect_city_quality
from src.jobs.crawl_store import DuplicateInventoryResult, get_recent_duplicate_inventory
from src.jobs.city_store import (
    CityActivationError,
    CityDetailRecord,
    CityQualitySnapshotRecord,
    activate_city,
    disable_city,
    enable_city,
    get_city,
    get_city_detail,
    list_cities,
    select_city_refresh_dispatch_candidate,
)

router = APIRouter(prefix="/internal", dependencies=[Depends(verify_internal_token)])


class CityQualitySnapshotResponse(BaseModel):
    snapshot_id: int
    valid_place_count: int
    valid_evidence_count: int
    covered_categories: list[str]
    successful_base_keywords: list[str]
    blocking_issues: list[str]
    gray_eligible: bool
    active_eligible: bool
    route_eligible_activity_count: int = 0
    route_eligible_food_count: int = 0
    route_eligible_type_coverage: int = 0
    canonical_geo_resolved_ratio: float = 0.0
    canonical_quality_pass: bool = False
    summary_effective_places: int = 0
    summary_effective_evidence: int = 0
    summary_type_coverage: int = 0
    evidence_quality_pass: bool = False
    checked_time: str


class CityResponse(BaseModel):
    city_id: int
    canonical_name: str
    status: str
    aliases: list[str] = Field(default_factory=list)
    request_count_30d: int
    last_requested_time: str | None
    last_quality_check_time: str | None
    last_refresh_time: str | None
    next_refresh_time: str | None
    active_confirmed_time: str | None
    disabled_reason: str | None
    active_batch_id: int | None
    latest_quality: CityQualitySnapshotResponse | None


class CityListResponse(BaseModel):
    success: bool = True
    cities: list[CityResponse]


class CityBatchItemResponse(BaseModel):
    item_id: int
    keyword: str
    keyword_type: str
    status: str
    crawl_run_id: int | None
    error_code: str | None
    error_message: str | None
    started_time: str | None
    finished_time: str | None


class CityBatchResponse(BaseModel):
    batch_id: int
    city_id: int
    canonical_name: str
    trigger_source: str
    reason: str
    limit_per_keyword: int
    status: str
    extract_status: str
    poi_resolve_status: str
    refresh_status: str
    quality_status: str
    heartbeat_time: str | None
    started_time: str | None
    finished_time: str | None
    error_code: str | None
    error_message: str | None
    items: list[CityBatchItemResponse]


class CityBatchListResponse(BaseModel):
    success: bool = True
    batches: list[CityBatchResponse]


class CityBatchCreateRequest(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=8)
    limit_per_keyword: int = Field(default=20, ge=1, le=50)
    force_recent: bool = False


class CityBatchCreateResponse(BaseModel):
    success: bool = True
    batch: CityBatchResponse


class CityDispatchResponse(BaseModel):
    success: bool
    dispatched: bool
    reason: str | None = None
    batch: CityBatchResponse | None = None


class CityDisableRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class CityMutationResponse(BaseModel):
    success: bool = True
    city: CityResponse


def _iso(dt) -> str | None:
    if dt is None:
        return None
    return dt.isoformat().replace("+00:00", "Z")


def _quality_to_response(
    snapshot: CityQualitySnapshotRecord | None,
) -> CityQualitySnapshotResponse | None:
    if snapshot is None:
        return None
    return CityQualitySnapshotResponse(
        snapshot_id=snapshot.snapshot_id,
        valid_place_count=snapshot.valid_place_count,
        valid_evidence_count=snapshot.valid_evidence_count,
        covered_categories=snapshot.covered_categories,
        successful_base_keywords=snapshot.successful_base_keywords,
        blocking_issues=snapshot.blocking_issues,
        gray_eligible=snapshot.gray_eligible,
        active_eligible=snapshot.active_eligible,
        route_eligible_activity_count=snapshot.route_eligible_activity_count,
        route_eligible_food_count=snapshot.route_eligible_food_count,
        route_eligible_type_coverage=snapshot.route_eligible_type_coverage,
        canonical_geo_resolved_ratio=snapshot.canonical_geo_resolved_ratio,
        canonical_quality_pass=snapshot.canonical_quality_pass,
        summary_effective_places=snapshot.summary_effective_places,
        summary_effective_evidence=snapshot.summary_effective_evidence,
        summary_type_coverage=snapshot.summary_type_coverage,
        evidence_quality_pass=snapshot.evidence_quality_pass,
        checked_time=_iso(snapshot.checked_time) or "",
    )


def _city_to_response(detail: CityDetailRecord) -> CityResponse:
    city = detail.city
    return CityResponse(
        city_id=city.city_id,
        canonical_name=city.canonical_name,
        status=city.status,
        aliases=detail.aliases,
        request_count_30d=city.request_count_30d,
        last_requested_time=_iso(city.last_requested_time),
        last_quality_check_time=_iso(city.last_quality_check_time),
        last_refresh_time=_iso(city.last_refresh_time),
        next_refresh_time=_iso(city.next_refresh_time),
        active_confirmed_time=_iso(city.active_confirmed_time),
        disabled_reason=city.disabled_reason,
        active_batch_id=detail.active_batch_id,
        latest_quality=_quality_to_response(detail.latest_quality),
    )


def _batch_to_response(batch: CityBatchRecord) -> CityBatchResponse:
    return CityBatchResponse(
        batch_id=batch.batch_id,
        city_id=batch.city_id,
        canonical_name=batch.canonical_name,
        trigger_source=batch.trigger_source,
        reason=batch.reason,
        limit_per_keyword=batch.limit_per_keyword,
        status=batch.status,
        extract_status=batch.extract_status,
        poi_resolve_status=batch.poi_resolve_status,
        refresh_status=batch.refresh_status,
        quality_status=batch.quality_status,
        heartbeat_time=_iso(batch.heartbeat_time),
        started_time=_iso(batch.started_time),
        finished_time=_iso(batch.finished_time),
        error_code=batch.error_code,
        error_message=batch.error_message,
        items=[
            CityBatchItemResponse(
                item_id=item.item_id,
                keyword=item.keyword,
                keyword_type=item.keyword_type,
                status=item.status,
                crawl_run_id=item.crawl_run_id,
                error_code=item.error_code,
                error_message=item.error_message,
                started_time=_iso(item.started_time),
                finished_time=_iso(item.finished_time),
            )
            for item in batch.items
        ],
    )


def _active_batch_conflict(exc: CityBatchActiveError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "success": False,
            "reason": "GLOBAL_BATCH_ACTIVE",
            "message": str(exc),
        },
    )


def _recent_inventory_conflict(
    city: str,
    duplicates: list[tuple[str, DuplicateInventoryResult]],
    recent_hours: int,
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "success": False,
            "reason": "DUPLICATE_RECENT_INVENTORY",
            "message": "city batch keywords have recent crawl inventory",
            "city": city,
            "recent_hours": recent_hours,
            "need_confirm": True,
            "duplicates": [
                {
                    "keyword": keyword,
                    "raw_count": inventory.raw_count,
                    "parsed_count": inventory.parsed_count,
                    "pending_count": inventory.pending_count,
                    "failed_count": inventory.failed_count,
                    "summary_count": inventory.summary_count,
                    "latest_success_run_id": inventory.latest_success_run_id,
                    "latest_success_time": _iso(inventory.latest_success_time),
                    "latest_raw_time": _iso(inventory.latest_raw_time),
                }
                for keyword, inventory in duplicates
            ],
        },
    )


def _validate_tags(tags: list[str]) -> list[str]:
    unique_tags: list[str] = []
    for tag in tags:
        normalized = tag.strip()
        if not normalized:
            continue
        if normalized not in PREFERENCE_EXTENSION_KEYWORDS:
            allowed = ", ".join(sorted(PREFERENCE_EXTENSION_KEYWORDS))
            raise HTTPException(
                status_code=400,
                detail=f"tag must be one of: {allowed}",
            )
        if normalized not in unique_tags:
            unique_tags.append(normalized)
        if len(unique_tags) > 2:
            raise HTTPException(status_code=400, detail="at most 2 tags are accepted")
    return unique_tags


async def _get_recent_batch_inventory_duplicates(
    *,
    city: str,
    tags: list[str],
    recent_hours: int = 24,
) -> list[tuple[str, DuplicateInventoryResult]]:
    duplicates: list[tuple[str, DuplicateInventoryResult]] = []
    for keyword, _keyword_type in city_batch_keywords(city, preferences=tags):
        inventory = await get_recent_duplicate_inventory(city, keyword, recent_hours)
        if inventory.found:
            duplicates.append((keyword, inventory))
    return duplicates


@router.get("/cities", response_model=CityListResponse)
async def list_cities_endpoint(
    status: Literal["DISCOVERED", "GRAY", "ACTIVE", "DISABLED"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> CityListResponse:
    details = await list_cities(status=status, limit=limit, offset=offset)
    return CityListResponse(cities=[_city_to_response(detail) for detail in details])


@router.get("/cities/{city_id}", response_model=CityResponse)
async def get_city_endpoint(city_id: int) -> CityResponse:
    detail = await get_city_detail(city_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="city not found")
    return _city_to_response(detail)


@router.get("/cities/{city_id}/batches", response_model=CityBatchListResponse)
async def list_city_batches_endpoint(
    city_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> CityBatchListResponse:
    if await get_city(city_id) is None:
        raise HTTPException(status_code=404, detail="city not found")
    batches = await list_city_batches(city_id=city_id, limit=limit, offset=offset)
    return CityBatchListResponse(batches=[_batch_to_response(batch) for batch in batches])


@router.get("/city-crawl/batches/{batch_id}", response_model=CityBatchResponse)
async def get_city_batch_endpoint(batch_id: int) -> CityBatchResponse:
    batch = await get_city_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")
    return _batch_to_response(batch)


@router.post("/cities/refresh/dispatch", response_model=CityDispatchResponse)
async def dispatch_city_refresh_endpoint() -> CityDispatchResponse:
    active_batch = await get_active_city_batch()
    if active_batch is not None:
        return JSONResponse(
            status_code=409,
            content={
                "success": False,
                "dispatched": False,
                "reason": "GLOBAL_BATCH_ACTIVE",
                "message": f"active city batch exists: {active_batch.batch_id}",
                "active_batch_id": active_batch.batch_id,
            },
        )
    candidate = await select_city_refresh_dispatch_candidate()
    if candidate is None:
        return CityDispatchResponse(success=True, dispatched=False, reason="NO_ELIGIBLE_CITY")
    try:
        batch = await create_city_crawl_batch(
            city_id=candidate.city.city_id,
            trigger_source="refresh",
            reason=candidate.reason,
            limit_per_keyword=get_settings().city_batch_limit_per_keyword,
        )
    except CityBatchActiveError as exc:
        return _active_batch_conflict(exc)
    return CityDispatchResponse(
        success=True,
        dispatched=True,
        reason=candidate.reason,
        batch=_batch_to_response(batch),
    )


@router.post("/cities/{city_id}/crawl-batches", response_model=CityBatchCreateResponse)
async def create_city_batch_endpoint(
    city_id: int,
    req: CityBatchCreateRequest,
) -> CityBatchCreateResponse:
    city = await get_city(city_id)
    if city is None:
        raise HTTPException(status_code=404, detail="city not found")
    if city.status == "DISABLED":
        return JSONResponse(
            status_code=409,
            content={
                "success": False,
                "reason": "CITY_DISABLED",
                "message": "disabled city cannot create crawl batch",
            },
        )
    tags = _validate_tags(req.tags)
    if not req.force_recent:
        duplicates = await _get_recent_batch_inventory_duplicates(
            city=city.canonical_name,
            tags=tags,
        )
        if duplicates:
            return _recent_inventory_conflict(city.canonical_name, duplicates, 24)
    try:
        batch = await create_city_crawl_batch(
            city_id=city_id,
            trigger_source="manual",
            reason="manual",
            preferences=tags,
            limit_per_keyword=req.limit_per_keyword,
        )
    except CityBatchActiveError as exc:
        return _active_batch_conflict(exc)
    return CityBatchCreateResponse(batch=_batch_to_response(batch))


@router.post("/city-crawl/batches/{batch_id}/retry", response_model=CityBatchCreateResponse)
async def retry_city_batch_endpoint(batch_id: int) -> CityBatchCreateResponse:
    if await get_city_batch(batch_id) is None:
        raise HTTPException(status_code=404, detail="batch not found")
    try:
        batch = await create_retry_city_crawl_batch(failed_batch_id=batch_id)
    except CityBatchActiveError as exc:
        return _active_batch_conflict(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CityBatchCreateResponse(batch=_batch_to_response(batch))


@router.post("/cities/{city_id}/disable", response_model=CityMutationResponse)
async def disable_city_endpoint(
    city_id: int,
    req: CityDisableRequest,
) -> CityMutationResponse:
    try:
        await disable_city(city_id, req.reason)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    detail = await get_city_detail(city_id)
    return CityMutationResponse(city=_city_to_response(detail))  # type: ignore[arg-type]


@router.post("/cities/{city_id}/enable", response_model=CityMutationResponse)
async def enable_city_endpoint(city_id: int) -> CityMutationResponse:
    try:
        await enable_city(city_id)
        await inspect_city_quality(city_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    detail = await get_city_detail(city_id)
    return CityMutationResponse(city=_city_to_response(detail))  # type: ignore[arg-type]


@router.post("/cities/{city_id}/activate", response_model=CityMutationResponse)
async def activate_city_endpoint(city_id: int) -> CityMutationResponse:
    try:
        await activate_city(city_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CityActivationError as exc:
        return JSONResponse(
            status_code=409,
            content={
                "success": False,
                "reason": "CITY_NOT_ACTIVE_ELIGIBLE",
                "message": str(exc),
            },
        )
    detail = await get_city_detail(city_id)
    return CityMutationResponse(city=_city_to_response(detail))  # type: ignore[arg-type]
