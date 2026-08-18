"""Shared deterministic parsing helpers for cost source adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from src.cost_reference.models import MAX_MONEY_FEN, MoneyRangeFen, ReferenceEntry

from .models import SourceObservation


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def aware_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo is not None else None


def cny_to_fen(value: Any, *, allow_zero: bool = True) -> int | None:
    """Convert one provider CNY value to strict integer fen without float math."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        text_value = repr(value)
    elif isinstance(value, (str, int, Decimal)):
        text_value = str(value).strip()
    else:
        return None
    if not text_value:
        return None
    try:
        amount = Decimal(text_value)
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount < 0 or (not allow_zero and amount == 0):
        return None
    fen = amount * 100
    if fen != fen.to_integral_value() or fen > MAX_MONEY_FEN:
        return None
    return int(fen)


def cny_range(
    minimum: Any,
    maximum: Any,
    *,
    allow_zero: bool = True,
) -> MoneyRangeFen | None:
    min_fen = cny_to_fen(minimum, allow_zero=allow_zero)
    max_fen = cny_to_fen(maximum, allow_zero=allow_zero)
    if min_fen is None or max_fen is None or min_fen > max_fen:
        return None
    return MoneyRangeFen(min_fen=min_fen, max_fen=max_fen)


def reference_observation(
    entry: ReferenceEntry,
    *,
    range_fen: MoneyRangeFen,
    item_identity: str,
    captured_at: datetime,
) -> SourceObservation:
    return SourceObservation(
        source_id="reference:" + ",".join(entry.source_ids),
        source_type="versioned_reference_catalog",
        price_basis="reference",
        item_identity=item_identity,
        captured_at=captured_at,
        observed_at=None,
        reference_version=entry.version,
        effective_date=entry.effective_date,
        provenance=entry.provenance,
        review_status=entry.review_status,
        range_fen=range_fen,
    )
