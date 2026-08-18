"""Accommodation reference baseline and governed optional provider adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

from pydantic import Field

from src.cost_reference.catalog import lookup_accommodation
from src.cost_reference.models import FrozenModel, ReferenceCatalog

from .common import aware_datetime, cny_range, reference_observation, utc_now
from .models import CostSourceResult, SourceObservation


class AccommodationProviderGate(FrozenModel):
    provider_name: str = Field(min_length=1)
    enabled: bool = False
    coverage_approved: bool = False
    contract_tests_passed: bool = False
    terms_accepted: bool = False

    @property
    def open(self) -> bool:
        return all((
            self.enabled,
            self.coverage_approved,
            self.contract_tests_passed,
            self.terms_accepted,
        ))


AccommodationProvider = Callable[[], Awaitable[dict[str, Any] | None]]


def _area_reference(
    catalog: ReferenceCatalog,
    *,
    city: str,
    area_identity: str,
    travel_date: date | None,
    captured_at: datetime,
) -> SourceObservation | None:
    entry = None
    if travel_date is not None:
        entry = lookup_accommodation(
            catalog,
            city=city,
            area_identity=area_identity,
            period_class="date_period",
            travel_date=travel_date,
        )
    if entry is None:
        entry = lookup_accommodation(
            catalog,
            city=city,
            area_identity=area_identity,
            period_class="ordinary",
            travel_date=None,
        )
    if entry is None:
        return None
    return reference_observation(
        entry,
        range_fen=entry.range_fen,
        item_identity=f"accommodation:{city}:{area_identity}:{entry.period_class}",
        captured_at=captured_at,
    )


def _provider_observation(
    payload: dict[str, Any] | None,
    *,
    provider_name: str,
    expected_city: str,
    expected_area_identity: str,
    captured_at: datetime,
) -> SourceObservation | None:
    if not isinstance(payload, dict):
        return None
    if str(payload.get("city") or "").strip() != expected_city:
        return None
    if str(payload.get("area_identity") or "").strip() != expected_area_identity:
        return None
    property_identity = str(payload.get("property_identity") or "").strip()
    rate_identity = str(payload.get("rate_identity") or "").strip()
    observed_at = aware_datetime(payload.get("observed_at"))
    range_fen = cny_range(
        payload.get("min_cny"),
        payload.get("max_cny"),
        allow_zero=False,
    )
    if not property_identity or not rate_identity or observed_at is None or range_fen is None:
        return None
    return SourceObservation(
        source_id=f"{provider_name}:{rate_identity}",
        source_type="accommodation_rate_provider",
        price_basis="sourced",
        item_identity=f"property:{property_identity}:rate:{rate_identity}",
        captured_at=captured_at,
        observed_at=observed_at,
        range_fen=range_fen,
    )


async def resolve_accommodation_source(
    catalog: ReferenceCatalog,
    *,
    city: str,
    area_identity: str,
    travel_date: date | None = None,
    provider_gate: AccommodationProviderGate | None = None,
    provider: AccommodationProvider | None = None,
    captured_at: datetime | None = None,
) -> CostSourceResult:
    """Prefer a gated property rate and always fail open to the area tier."""

    captured = captured_at or utc_now()
    baseline = _area_reference(
        catalog,
        city=city,
        area_identity=area_identity,
        travel_date=travel_date,
        captured_at=captured,
    )
    if provider_gate is None or provider is None or not provider_gate.open:
        if baseline is not None:
            return CostSourceResult(
                adapter_status="gated",
                resolution="reference",
                selected=baseline,
                reason="commercial provider gate is closed",
            )
        return CostSourceResult(
            adapter_status="gated",
            resolution="missing",
            reason="commercial provider gate is closed and area tier is missing",
        )
    try:
        payload = await provider()
    except asyncio.TimeoutError:
        status = "timeout"
        reason = "accommodation provider timed out"
    except Exception as exc:
        status = "unavailable"
        reason = f"accommodation provider unavailable: {type(exc).__name__}"
    else:
        observation = _provider_observation(
            payload,
            provider_name=provider_gate.provider_name,
            expected_city=city,
            expected_area_identity=area_identity,
            captured_at=captured,
        )
        if observation is not None:
            return CostSourceResult(
                adapter_status="success",
                resolution="sourced",
                selected=observation,
            )
        status = "malformed" if payload is not None else "unavailable"
        reason = "accommodation provider rate is malformed or unavailable"
    if baseline is not None:
        return CostSourceResult(
            adapter_status=status,
            resolution="reference",
            selected=baseline,
            reason=reason,
        )
    return CostSourceResult(
        adapter_status=status,
        resolution="missing",
        reason=reason,
    )


__all__ = ["AccommodationProviderGate", "resolve_accommodation_source"]
