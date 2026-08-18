"""Lunch/dinner-only Amap restaurant-price adapter with city fallback."""

from __future__ import annotations

from datetime import datetime

from src.agents.food_resolver import FoodAttachment
from src.cost_reference.catalog import lookup_meal
from src.cost_reference.models import MoneyRangeFen, ReferenceCatalog

from .common import aware_datetime, cny_to_fen, reference_observation, utc_now
from .models import CostSourceResult, SourceObservation


COUNTED_MEAL_SLOTS = frozenset({"lunch", "dinner"})
ELIGIBLE_RESTAURANT_TYPES = frozenset({"restaurant", "food"})


def resolve_meal_source(
    catalog: ReferenceCatalog,
    *,
    city: str,
    meal_slot: str,
    attachment: FoodAttachment | None,
    assigned_meal_slot: str | None = None,
    captured_at: datetime | None = None,
) -> CostSourceResult:
    captured = captured_at or utc_now()
    if meal_slot not in COUNTED_MEAL_SLOTS:
        return CostSourceResult(
            adapter_status="not_applicable",
            resolution="not_applicable",
            reason="only assigned lunch/dinner slots contribute",
        )

    provider_status = "unavailable"
    if attachment is not None:
        observed_at = aware_datetime(attachment.source_observed_at)
        amount_fen = cny_to_fen(attachment.amap_avg_price, allow_zero=False)
        identity = (
            f"amap-poi:{attachment.amap_poi_id}"
            if attachment.amap_poi_id
            else f"canonical-place:{attachment.place_id}"
        )
        if (
            assigned_meal_slot == meal_slot
            and attachment.place_type in ELIGIBLE_RESTAURANT_TYPES
            and observed_at is not None
            and amount_fen is not None
        ):
            observation = SourceObservation(
                source_id="amap_place:biz_ext.cost",
                source_type="amap_place_cached",
                price_basis="sourced",
                item_identity=f"meal:{meal_slot}:{identity}",
                captured_at=captured,
                observed_at=observed_at,
                range_fen=MoneyRangeFen(min_fen=amount_fen, max_fen=amount_fen),
            )
            return CostSourceResult(
                adapter_status="success",
                resolution="sourced",
                selected=observation,
            )
        provider_status = "malformed"

    reference = lookup_meal(catalog, city=city, meal=meal_slot)
    if reference is not None:
        return CostSourceResult(
            adapter_status=provider_status,
            resolution="reference",
            selected=reference_observation(
                reference,
                range_fen=reference.range_fen,
                item_identity=f"meal:{city}:{meal_slot}",
                captured_at=captured,
            ),
            reason="eligible restaurant price unavailable; city main-meal reference used",
        )
    return CostSourceResult(
        adapter_status=provider_status,
        resolution="missing",
        reason="eligible restaurant price and city main-meal reference are unavailable",
    )


__all__ = ["resolve_meal_source"]
