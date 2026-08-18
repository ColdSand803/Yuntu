"""Amap route-fare parsing and requested-taxi intent gate."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from src.cost_reference.catalog import lookup_local_transport
from src.cost_reference.models import MoneyRangeFen, ReferenceCatalog

from .common import aware_datetime, cny_to_fen, reference_observation, utc_now
from .models import CostSourceResult, SourceObservation


# Destination-local sanity guards.  They are validation ceilings, not fallback
# prices: rejected values proceed to the reviewed reference/missing path.
MAX_TRANSIT_FARE_FEN = 10_000  # CNY 100 per traveller for one local leg.
TAXI_BASE_SANITY_FEN = 20_000  # CNY 200 before distance allowance.
TAXI_SANITY_FEN_PER_KM = 3_000  # CNY 30/km above the base allowance.


def _plausible_fare(
    *,
    mode: Literal["driving", "transit"],
    amount_fen: int,
    distance_meters: int,
) -> bool:
    if amount_fen <= 0 or distance_meters < 0:
        return False
    if mode == "transit":
        return amount_fen <= MAX_TRANSIT_FARE_FEN
    distance_km_ceiling = (max(distance_meters, 0) + 999) // 1000
    maximum = TAXI_BASE_SANITY_FEN + distance_km_ceiling * TAXI_SANITY_FEN_PER_KM
    return amount_fen <= maximum


def adapt_amap_route_fare(
    *,
    mode: str,
    path: dict[str, Any],
    distance_meters: int,
    route_identity: str,
    captured_at: datetime,
    observed_at: datetime | str | None = None,
) -> CostSourceResult:
    """Validate v5 ``taxi_cost``/``transit_fee`` without affecting the route."""

    if mode not in {"driving", "transit"}:
        return CostSourceResult(
            adapter_status="not_applicable",
            resolution="not_applicable",
            reason="route mode has no v0.9.4 provider fare field",
        )
    cost = path.get("cost")
    if not isinstance(cost, dict):
        return CostSourceResult(
            adapter_status="unavailable",
            resolution="missing",
            reason="Amap cost object is unavailable",
        )
    field = "taxi_cost" if mode == "driving" else "transit_fee"
    raw_value = cost.get(field)
    if raw_value in (None, ""):
        return CostSourceResult(
            adapter_status="unavailable",
            resolution="missing",
            reason=f"Amap {field} is unavailable",
        )
    amount_fen = cny_to_fen(raw_value, allow_zero=False)
    if amount_fen is None or not _plausible_fare(
        mode=mode,
        amount_fen=amount_fen,
        distance_meters=distance_meters,
    ):
        return CostSourceResult(
            adapter_status="malformed",
            resolution="missing",
            reason=f"Amap {field} is invalid or implausible",
        )
    provider_time = aware_datetime(observed_at) or captured_at
    observation = SourceObservation(
        source_id=f"amap_route_v5:{field}",
        source_type="amap_route_v5",
        price_basis="sourced",
        item_identity=route_identity,
        captured_at=captured_at,
        observed_at=provider_time,
        range_fen=MoneyRangeFen(min_fen=amount_fen, max_fen=amount_fen),
    )
    return CostSourceResult(
        adapter_status="success",
        resolution="sourced",
        selected=observation,
    )


def fare_for_locked_leg(
    observation: SourceObservation | None,
    *,
    effective_mode: str,
    requested_commute_mode: str,
) -> SourceObservation | None:
    """Paid taxi needs requested ``driving`` (consumer label 打车) intent."""

    if observation is None:
        return None
    if effective_mode == "driving" and requested_commute_mode != "driving":
        return None
    return observation


def resolve_local_transport_source(
    catalog: ReferenceCatalog,
    *,
    city: str,
    effective_mode: str,
    requested_commute_mode: str,
    provider_result: CostSourceResult,
    captured_at: datetime | None = None,
) -> CostSourceResult:
    """Select eligible route fare, then exact city/mode reference, then missing."""

    captured = captured_at or utc_now()
    if effective_mode == "driving" and requested_commute_mode != "driving":
        return CostSourceResult(
            adapter_status="not_applicable",
            resolution="not_applicable",
            reason="effective driving alone is not accepted paid taxi intent",
        )
    reference_mode = {
        "driving": "taxi",
        "transit": "public_transit",
    }.get(effective_mode)
    if reference_mode is None:
        return CostSourceResult(
            adapter_status="not_applicable",
            resolution="not_applicable",
            reason="route mode is outside the P2 paid local-fare adapter",
        )
    selected = fare_for_locked_leg(
        provider_result.selected,
        effective_mode=effective_mode,
        requested_commute_mode=requested_commute_mode,
    )
    if selected is not None and selected.price_basis == "sourced":
        return CostSourceResult(
            adapter_status="success",
            resolution="sourced",
            selected=selected,
        )
    reference = lookup_local_transport(
        catalog,
        city=city,
        mode=reference_mode,
    )
    if reference is not None:
        return CostSourceResult(
            adapter_status=provider_result.adapter_status,
            resolution="reference",
            selected=reference_observation(
                reference,
                range_fen=reference.range_fen,
                item_identity=f"local-transport:{city}:{reference_mode}",
                captured_at=captured,
            ),
            reason="route fare unavailable; exact city/mode reference used",
        )
    return CostSourceResult(
        adapter_status=provider_result.adapter_status,
        resolution="missing",
        reason="route fare and exact city/mode reference are unavailable",
    )


__all__ = [
    "adapt_amap_route_fare",
    "fare_for_locked_leg",
    "resolve_local_transport_source",
]
