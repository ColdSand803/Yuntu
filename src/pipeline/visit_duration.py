"""Normalize and aggregate XHS visit-duration facts for canonical POIs."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from statistics import median
from typing import Any

MIN_VISIT_MINUTES = 15
MAX_VISIT_MINUTES = 480
HIGH_CONFIDENCE_THRESHOLD = 0.85

_CHINESE_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

_EXPLICIT_DURATION_HINT = re.compile(
    r"(游玩|逛|停留|玩|拍照|打卡|路过|建议|预留|安排|耗时|时长|够|足够|大概|左右)"
)
_MINUTE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:分钟|分|min|mins|minutes)", re.I)
_HOUR_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:小时|h|hr|hrs|hour|hours)", re.I)
_RANGE_HOUR_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?|[一二两三四五六七八九十])\s*(?:-|~|到|至)\s*"
    r"(\d+(?:\.\d+)?|[一二两三四五六七八九十])\s*(?:小时|h|hr|hrs)",
    re.I,
)
_RANGE_MINUTE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?|[一二两三四五六七八九十])\s*(?:-|~|到|至)\s*"
    r"(\d+(?:\.\d+)?|[一二两三四五六七八九十])\s*(?:分钟|分|min|mins)",
    re.I,
)
_CHINESE_HOUR_PATTERN = re.compile(r"([一二两三四五六七八九十])\s*(?:个)?小时")
_CHINESE_MINUTE_PATTERN = re.compile(r"([一二两三四五六七八九十])\s*(?:十)?\s*(?:分钟|分)")

_MAJOR_PLACE_NAME_MARKERS = (
    "景区",
    "风景区",
    "山",
    "峡",
    "谷",
    "湖",
    "古镇",
    "森林",
    "乐园",
    "度假区",
    "动物园",
    "植物园",
)
_SUPPORTED_PLACE_TYPES = {
    "attraction",
    "business_area",
    "market",
    "museum",
    "park",
    "photo_spot",
    "restaurant",
}


@dataclass(frozen=True)
class NormalizedVisitDuration:
    minutes: int
    raw: str
    strategy: str


@dataclass(frozen=True)
class VisitDurationFact:
    minutes: int
    raw: str
    evidence: str
    confidence: float


@dataclass(frozen=True)
class VisitDurationAggregate:
    minutes: int
    confidence: float
    fact_count: int
    source: str = "xhs_median"


def _to_number(value: str) -> float | None:
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        pass
    if value in _CHINESE_DIGITS:
        return float(_CHINESE_DIGITS[value])
    if value.startswith("十") and len(value) > 1 and value[1] in _CHINESE_DIGITS:
        return float(10 + _CHINESE_DIGITS[value[1]])
    if value.endswith("十") and len(value) > 1 and value[0] in _CHINESE_DIGITS:
        return float(_CHINESE_DIGITS[value[0]] * 10)
    return None


def _clamp_minutes(minutes: float) -> int:
    if not math.isfinite(minutes):
        return 0
    return max(MIN_VISIT_MINUTES, min(MAX_VISIT_MINUTES, int(round(minutes))))


def _is_major_place(*, place_name: str = "", place_type: str | None = None) -> bool:
    if place_type in {"park"} and any(marker in place_name for marker in ("森林", "湿地", "植物园", "动物园")):
        return True
    return any(marker in place_name for marker in _MAJOR_PLACE_NAME_MARKERS)


def has_visit_duration_marker_support(
    *, place_name: str = "", place_type: str | None = None
) -> bool:
    """Return whether one strong fact is enough to write canonical duration."""
    if place_type in _SUPPORTED_PLACE_TYPES:
        return True
    return any(marker in place_name for marker in _MAJOR_PLACE_NAME_MARKERS)


def normalize_visit_duration(
    value: Any,
    *,
    place_name: str = "",
    place_type: str | None = None,
    require_duration_hint: bool = False,
) -> NormalizedVisitDuration | None:
    """Normalize a raw visit-duration expression to minutes.

    The function only returns evidence-derived durations. It never fabricates a
    place-type rule default; callers should keep runtime defaults out of
    canonical persistence.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return NormalizedVisitDuration(
            minutes=_clamp_minutes(float(value)),
            raw=str(value),
            strategy="numeric_minutes",
        )
    if isinstance(value, dict):
        raw = (
            value.get("raw")
            or value.get("text")
            or value.get("value")
            or value.get("duration")
            or value.get("visit_duration")
        )
        minutes = value.get("minutes") or value.get("normalized_minutes")
        if minutes is not None:
            try:
                return NormalizedVisitDuration(
                    minutes=_clamp_minutes(float(minutes)),
                    raw=str(raw or minutes),
                    strategy="provided_minutes",
                )
            except (TypeError, ValueError):
                pass
        value = raw
    if not isinstance(value, str):
        return None

    raw = value.strip()
    if not raw:
        return None
    compact = re.sub(r"\s+", "", raw)
    if require_duration_hint and not _EXPLICIT_DURATION_HINT.search(compact):
        return None

    if any(token in compact for token in ("一个半小时", "一小时半", "1个半小时", "1小时半")):
        return NormalizedVisitDuration(minutes=90, raw=raw, strategy="one_and_half_hour")

    match = _RANGE_HOUR_PATTERN.search(compact)
    if match:
        left = _to_number(match.group(1))
        right = _to_number(match.group(2))
        if left is not None and right is not None:
            return NormalizedVisitDuration(
                minutes=_clamp_minutes((left + right) / 2 * 60),
                raw=raw,
                strategy="hour_range_median",
            )

    match = _RANGE_MINUTE_PATTERN.search(compact)
    if match:
        left = _to_number(match.group(1))
        right = _to_number(match.group(2))
        if left is not None and right is not None:
            return NormalizedVisitDuration(
                minutes=_clamp_minutes((left + right) / 2),
                raw=raw,
                strategy="minute_range_median",
            )

    match = _HOUR_PATTERN.search(compact)
    if match:
        return NormalizedVisitDuration(
            minutes=_clamp_minutes(float(match.group(1)) * 60),
            raw=raw,
            strategy="hour",
        )
    match = _CHINESE_HOUR_PATTERN.search(compact)
    if match:
        number = _to_number(match.group(1))
        if number is not None:
            return NormalizedVisitDuration(
                minutes=_clamp_minutes(number * 60),
                raw=raw,
                strategy="chinese_hour",
            )

    match = _MINUTE_PATTERN.search(compact)
    if match:
        return NormalizedVisitDuration(
            minutes=_clamp_minutes(float(match.group(1))),
            raw=raw,
            strategy="minute",
        )
    match = _CHINESE_MINUTE_PATTERN.search(compact)
    if match:
        number = _to_number(match.group(1))
        if number is not None:
            suffix_ten = "十" in match.group(0)
            return NormalizedVisitDuration(
                minutes=_clamp_minutes(
                    number * 10
                    if suffix_ten and match.group(1) != "十"
                    else number
                ),
                raw=raw,
                strategy="chinese_minute",
            )

    if any(token in compact for token in ("半小时", "半个小时")):
        return NormalizedVisitDuration(minutes=30, raw=raw, strategy="half_hour")
    if any(token in compact for token in ("半天", "一上午", "一下午")):
        minutes = 240 if _is_major_place(place_name=place_name, place_type=place_type) else 180
        return NormalizedVisitDuration(minutes=minutes, raw=raw, strategy="half_day")
    if any(token in compact for token in ("一天", "一整天", "全天")):
        minutes = 480 if _is_major_place(place_name=place_name, place_type=place_type) else 360
        return NormalizedVisitDuration(minutes=minutes, raw=raw, strategy="full_day")
    if any(token in compact for token in ("打卡一下", "简单打卡", "快速打卡", "随手拍")):
        return NormalizedVisitDuration(minutes=30, raw=raw, strategy="quick_checkin")
    if any(token in compact for token in ("路过拍拍", "路过拍照", "顺路拍", "路过看")):
        return NormalizedVisitDuration(minutes=45, raw=raw, strategy="pass_by_photo")

    return None


def fact_from_value(
    value: Any,
    *,
    confidence: float,
    place_name: str = "",
    place_type: str | None = None,
    evidence: str = "",
    require_duration_hint: bool = False,
) -> VisitDurationFact | None:
    normalized = normalize_visit_duration(
        value,
        place_name=place_name,
        place_type=place_type,
        require_duration_hint=require_duration_hint,
    )
    if normalized is None:
        return None
    return VisitDurationFact(
        minutes=normalized.minutes,
        raw=normalized.raw,
        evidence=evidence or normalized.raw,
        confidence=max(0.0, min(1.0, float(confidence))),
    )


def aggregate_visit_duration_facts(
    facts: list[VisitDurationFact],
    *,
    place_name: str = "",
    place_type: str | None = None,
) -> VisitDurationAggregate | None:
    valid = [fact for fact in facts if MIN_VISIT_MINUTES <= fact.minutes <= MAX_VISIT_MINUTES]
    if not valid:
        return None

    eligible = len(valid) >= 2 or (
        len(valid) == 1
        and valid[0].confidence >= HIGH_CONFIDENCE_THRESHOLD
        and has_visit_duration_marker_support(place_name=place_name, place_type=place_type)
    )
    if not eligible:
        return None

    minutes = int(round(median([fact.minutes for fact in valid])))
    avg_confidence = sum(fact.confidence for fact in valid) / len(valid)
    confidence = min(0.95, max(0.55, avg_confidence if len(valid) == 1 else avg_confidence + 0.05))
    return VisitDurationAggregate(
        minutes=minutes,
        confidence=round(confidence, 2),
        fact_count=len(valid),
    )
