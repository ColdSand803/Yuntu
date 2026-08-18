"""Reusable city availability gate after Intent Parser."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from src.agents.schema import TripRequest
from src.config import get_settings
from src.jobs.city_store import CityRecord, record_city_demand, resolve_city

ALLOW_ACTIVE = "ALLOW_ACTIVE"
ALLOW_GRAY = "ALLOW_GRAY"
CITY_PREPARING = "CITY_PREPARING"
CITY_COLLECTION_FAILED = "CITY_COLLECTION_FAILED"
CITY_DATA_INSUFFICIENT = "CITY_DATA_INSUFFICIENT"
CITY_DISABLED = "CITY_DISABLED"
CITY_CLARIFICATION_REQUIRED = "CITY_CLARIFICATION_REQUIRED"
NON_DEMAND_SOURCES = frozenset({"smoke-test", "internal", "acceptance-trip"})
CITY_COLLECTION_FAILED_BATCH_STATUSES = frozenset({
    "COOKIE_EXPIRED",
    "FAILED",
    "TIMEOUT",
})
PROVINCE_LEVEL_DESTINATIONS = frozenset({
    "安徽",
    "福建",
    "甘肃",
    "广东",
    "广西",
    "贵州",
    "海南",
    "河北",
    "河南",
    "黑龙江",
    "湖北",
    "湖南",
    "吉林",
    "江苏",
    "江西",
    "辽宁",
    "内蒙古",
    "宁夏",
    "青海",
    "山东",
    "山西",
    "陕西",
    "四川",
    "台湾",
    "西藏",
    "新疆",
    "云南",
    "浙江",
})
AMBIGUOUS_REGION_DESTINATIONS = frozenset({
    "北疆",
    "长三角",
    "川北",
    "川东",
    "川南",
    "川西",
    "大湾区",
    "滇北",
    "滇东",
    "滇南",
    "滇西",
    "东北",
    "东疆",
    "广西沿海",
    "华北",
    "华东",
    "华南",
    "华中",
    "环渤海",
    "江南",
    "京津冀",
    "南疆",
    "西北",
    "西南",
    "粤北",
    "粤东",
    "粤西",
    "珠三角",
})
REGION_LEVEL_SUFFIXES = (
    "省",
    "自治区",
    "特别行政区",
)


@dataclass(frozen=True)
class CityGateDecision:
    status: str
    city: str | None
    city_id: int | None
    city_status: str | None
    allowed: bool
    city_notice_code: str | None = None
    city_batch_status: str | None = None
    city_batch_error_code: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class CityGateRejected(RuntimeError):
    """Controlled business stop when a city is not available for planning."""

    def __init__(self, decision: CityGateDecision) -> None:
        super().__init__(decision.status)
        self.decision = decision


def destination_requires_city_clarification(requested_name: str | None) -> bool:
    """Return True when a destination names a broad region, not one city."""
    normalized = "".join(str(requested_name or "").split())
    if not normalized:
        return True
    return (
        normalized in PROVINCE_LEVEL_DESTINATIONS
        or normalized in AMBIGUOUS_REGION_DESTINATIONS
        or normalized.endswith(REGION_LEVEL_SUFFIXES)
    )


def evaluate_city(city: CityRecord | None, *, requested_name: str | None) -> CityGateDecision:
    """Return one deterministic availability decision without side effects."""
    if not requested_name:
        return CityGateDecision(
            status=CITY_CLARIFICATION_REQUIRED,
            city=None,
            city_id=None,
            city_status=None,
            allowed=False,
        )
    if city is None:
        return CityGateDecision(
            status=CITY_PREPARING,
            city=requested_name,
            city_id=None,
            city_status="DISCOVERED",
            allowed=False,
        )
    if city.status == "ACTIVE":
        if city.canonical_quality_pass is False:
            return CityGateDecision(
                status=CITY_DATA_INSUFFICIENT,
                city=city.canonical_name,
                city_id=city.city_id,
                city_status=city.status,
                allowed=False,
            )
        if city.evidence_quality_pass is False:
            return CityGateDecision(
                status=ALLOW_GRAY,
                city=city.canonical_name,
                city_id=city.city_id,
                city_status="GRAY",
                allowed=True,
                city_notice_code="DATA_IMPROVING",
            )
        return CityGateDecision(
            status=ALLOW_ACTIVE,
            city=city.canonical_name,
            city_id=city.city_id,
            city_status=city.status,
            allowed=True,
        )
    if city.status == "GRAY":
        if city.canonical_quality_pass is False:
            return CityGateDecision(
                status=CITY_DATA_INSUFFICIENT,
                city=city.canonical_name,
                city_id=city.city_id,
                city_status=city.status,
                allowed=False,
            )
        return CityGateDecision(
            status=ALLOW_GRAY,
            city=city.canonical_name,
            city_id=city.city_id,
            city_status=city.status,
            allowed=True,
            city_notice_code="DATA_IMPROVING",
        )
    if city.status == "DISABLED":
        return CityGateDecision(
            status=CITY_DISABLED,
            city=city.canonical_name,
            city_id=city.city_id,
            city_status=city.status,
            allowed=False,
        )
    if city.active_batch_id is not None:
        return CityGateDecision(
            status=CITY_PREPARING,
            city=city.canonical_name,
            city_id=city.city_id,
            city_status=city.status,
            allowed=False,
            city_batch_status=city.active_batch_status,
            city_batch_error_code=city.latest_batch_error_code,
        )
    if city.latest_batch_status in CITY_COLLECTION_FAILED_BATCH_STATUSES:
        return CityGateDecision(
            status=CITY_COLLECTION_FAILED,
            city=city.canonical_name,
            city_id=city.city_id,
            city_status=city.status,
            allowed=False,
            city_batch_status=city.latest_batch_status,
            city_batch_error_code=city.latest_batch_error_code or city.latest_batch_status,
        )
    if city.last_quality_check_time is not None or city.last_refresh_time is not None:
        if get_settings().city_gate_allow_discovered_for_validation:
            return CityGateDecision(
                status=ALLOW_GRAY,
                city=city.canonical_name,
                city_id=city.city_id,
                city_status=city.status,
                allowed=True,
                city_notice_code="DATA_IMPROVING",
            )
        return CityGateDecision(
            status=CITY_DATA_INSUFFICIENT,
            city=city.canonical_name,
            city_id=city.city_id,
            city_status=city.status,
            allowed=False,
        )
    return CityGateDecision(
        status=CITY_PREPARING,
        city=city.canonical_name,
        city_id=city.city_id,
        city_status=city.status,
        allowed=False,
        city_batch_status=city.latest_batch_status,
        city_batch_error_code=city.latest_batch_error_code,
    )


async def gate_sync_trip_request(trip_request: TripRequest) -> CityGateDecision:
    """Resolve and gate sync debug traffic without city-domain writes."""
    requested_name = trip_request.to_city.strip()
    if destination_requires_city_clarification(requested_name):
        return evaluate_city(None, requested_name=None)
    city = await resolve_city(requested_name) if requested_name else None
    if city is not None:
        trip_request.to_city = city.canonical_name
    return evaluate_city(city, requested_name=requested_name or None)


async def gate_async_trip_request(
    trip_request: TripRequest,
    *,
    source: str,
    request_id: str,
    conversation_id: str,
    raw_query: str,
) -> CityGateDecision:
    """Resolve, idempotently record demand, and gate one async trip request."""
    requested_name = trip_request.to_city.strip()
    if destination_requires_city_clarification(requested_name):
        return evaluate_city(None, requested_name=None)

    resolved = await resolve_city(requested_name)
    canonical_name = resolved.canonical_name if resolved is not None else requested_name
    if source in NON_DEMAND_SOURCES:
        if resolved is not None:
            trip_request.to_city = resolved.canonical_name
        return evaluate_city(resolved, requested_name=canonical_name)
    demand = await record_city_demand(
        canonical_name=canonical_name,
        source=source,
        request_id=request_id,
        conversation_id=conversation_id,
        raw_query=raw_query,
        normalized_preferences=trip_request.preferences,
    )
    if demand.city is None:
        raise RuntimeError("countable async demand did not return a city")
    trip_request.to_city = demand.city.canonical_name
    return evaluate_city(demand.city, requested_name=demand.city.canonical_name)
