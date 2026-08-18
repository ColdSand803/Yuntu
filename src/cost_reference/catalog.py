"""Deterministic loader and exact-key lookups for reference-estimate data."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import TypeVar

from .models import (
    AccommodationReference,
    AdmissionReference,
    IntercityMode,
    IntercityReference,
    LocalTransportReference,
    MealReference,
    ReferenceCatalog,
    ReverseIntercityRule,
)


DEFAULT_CATALOG_PATH = Path(__file__).with_name("v1.json")
T = TypeVar("T")


def load_reference_catalog(path: Path | None = None) -> ReferenceCatalog:
    payload = json.loads((path or DEFAULT_CATALOG_PATH).read_text(encoding="utf-8"))
    return ReferenceCatalog.model_validate(payload)


def catalog_digest(catalog: ReferenceCatalog) -> str:
    payload = catalog.model_dump(mode="json")
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _reviewed(items: tuple[T, ...]) -> tuple[T, ...]:
    return tuple(item for item in items if getattr(item, "review_status") == "reviewed")


def lookup_accommodation(
    catalog: ReferenceCatalog,
    *,
    city: str,
    area_identity: str,
    period_class: str = "ordinary",
    travel_date: date | None = None,
) -> AccommodationReference | None:
    if catalog.review_status != "reviewed":
        return None
    return next(
        (
            item
            for item in _reviewed(catalog.accommodation)
            if item.city == city
            and item.area_identity == area_identity
            and item.period_class == period_class
            and (
                (period_class == "ordinary" and travel_date is None)
                or (
                    period_class == "date_period"
                    and travel_date is not None
                    and item.date_start is not None
                    and item.date_end is not None
                    and item.date_start <= travel_date <= item.date_end
                )
            )
        ),
        None,
    )


def lookup_admission(
    catalog: ReferenceCatalog, *, place_identity: str
) -> AdmissionReference | None:
    if catalog.review_status != "reviewed":
        return None
    return next(
        (item for item in _reviewed(catalog.admission) if item.place_identity == place_identity),
        None,
    )


def lookup_meal(
    catalog: ReferenceCatalog, *, city: str, meal: str
) -> MealReference | None:
    if catalog.review_status != "reviewed":
        return None
    return next(
        (
            item
            for item in _reviewed(catalog.meals)
            if item.city == city and item.meal == meal
        ),
        None,
    )


def lookup_local_transport(
    catalog: ReferenceCatalog, *, city: str, mode: str
) -> LocalTransportReference | None:
    if catalog.review_status != "reviewed":
        return None
    return next(
        (
            item
            for item in _reviewed(catalog.local_transport)
            if item.city == city and item.mode == mode
        ),
        None,
    )


def get_reverse_intercity_rule(catalog: ReferenceCatalog) -> ReverseIntercityRule:
    if catalog.review_status != "reviewed":
        raise ValueError("reference catalog is not reviewed")
    reviewed = _reviewed(catalog.reverse_intercity_rules)
    if len(reviewed) != 1:
        raise ValueError("exactly one reviewed reverse intercity rule is required")
    return reviewed[0]


def lookup_return_intercity_reference(
    catalog: ReferenceCatalog,
    *,
    outbound_from_city: str,
    outbound_to_city: str,
    mode: IntercityMode,
) -> IntercityReference | None:
    """Look up only the explicit reverse key and only as reference data.

    An outbound sourced or reference amount is never accepted as input, so this
    function cannot relabel it as a sourced return fare.
    """

    get_reverse_intercity_rule(catalog)
    reverse_key = (outbound_to_city, outbound_from_city, mode)
    return next(
        (
            item
            for item in _reviewed(catalog.intercity)
            if (item.from_city, item.to_city, item.mode) == reverse_key
        ),
        None,
    )
