"""Deterministic accommodation checks for the publish gate."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.agents.schema import AccommodationSuggestion, PlanOutput

if TYPE_CHECKING:
    from src.agents.publish_gate import PublishFinding


HOTEL_BRANDS = {
    "希尔顿",
    "香格里拉",
    "洲际",
    "万豪",
    "凯悦",
    "君悦",
    "悦榕庄",
    "四季",
    "丽思卡尔顿",
    "索菲特",
    "喜来登",
    "威斯汀",
    "康莱德",
    "瑞吉",
    "柏悦",
    "安缦",
    "艾迪逊",
    "如家",
    "汉庭",
    "7天",
    "锦江之星",
    "全季",
    "亚朵",
    "维也纳",
    "格林豪泰",
    "桔子",
    "布丁",
    "速8",
    "华住",
    "尚客优",
    "城市便捷",
}

ACCOMMODATION_CONTEXT = ("酒店", "入住", "住宿", "下榻", "住在", "房")

_SENTENCE_RE = re.compile(r"[^。！？\n]+")
_DAY_HEADING_RE = re.compile(r"(?m)^Day\s+")
_PRICE_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\d+元.{0,6}(?:一晚|每晚|/晚)",
        r"每晚.{0,6}\d+.{0,4}元",
        r"人均[^，,。！？\n]{0,10}住宿",
        r"(?:酒店|住宿|客房).{0,6}房价",
    )
)


def _name_spans(sentence: str, names: list[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for name in names:
        cleaned = (name or "").strip()
        if not cleaned:
            continue
        spans.extend(
            match.span()
            for match in re.finditer(re.escape(cleaned), sentence)
        )
    return spans


def _span_is_inside(
    span: tuple[int, int],
    containers: list[tuple[int, int]],
) -> bool:
    start, end = span
    return any(left <= start and end <= right for left, right in containers)


def mask_accommodation_prefix_for_route_scan(plan_text: str) -> str:
    """Mask backend-owned transport/accommodation prefixes, preserving offsets."""

    if not plan_text.startswith(("【出行建议】", "【住宿建议】")):
        return plan_text
    day_heading = _DAY_HEADING_RE.search(plan_text)
    if day_heading is None:
        return plan_text
    prefix = plan_text[:day_heading.start()]
    if not prefix.endswith("\n\n"):
        return plan_text
    masked_prefix = "".join(
        "\n" if character == "\n" else " "
        for character in prefix
    )
    return masked_prefix + plan_text[day_heading.start():]


def _fabricated_brand(
    plan_text: str,
    used_place_names: list[str],
) -> tuple[str, str] | None:
    for sentence_match in _SENTENCE_RE.finditer(plan_text):
        sentence = sentence_match.group(0)
        if not any(context in sentence for context in ACCOMMODATION_CONTEXT):
            continue
        place_spans = _name_spans(sentence, used_place_names)
        for brand in sorted(HOTEL_BRANDS, key=len, reverse=True):
            for brand_match in re.finditer(re.escape(brand), sentence):
                if _span_is_inside(brand_match.span(), place_spans):
                    continue
                return brand, sentence.strip()
    return None


def check_accommodation_violations(
    plan: PlanOutput,
    accommodation: AccommodationSuggestion | None,
) -> list[PublishFinding]:
    """Return fail-closed accommodation findings with conservative matching."""

    from src.agents.publish_gate import PublishFinding

    if accommodation is None:
        return []

    findings: list[PublishFinding] = []
    used_place_names = list(plan.used_place_names or [])

    if accommodation.name in used_place_names:
        findings.append(PublishFinding(
            reason="accommodation_in_route",
            message=(
                f"accommodation '{accommodation.name}' appears in "
                "used_place_names"
            ),
        ))

    for pattern in _PRICE_PATTERNS:
        match = pattern.search(plan.plan_text or "")
        if match:
            findings.append(PublishFinding(
                reason="accommodation_price_claim",
                message="plan text contains an accommodation price claim",
                snippet=match.group(0),
            ))
            break

    if accommodation.source == "auto_recommended":
        fabricated = _fabricated_brand(
            plan.plan_text or "",
            used_place_names,
        )
        if fabricated is not None:
            brand, sentence = fabricated
            findings.append(PublishFinding(
                reason="accommodation_fabrication",
                message=(
                    "auto-recommended accommodation text names hotel brand "
                    f"'{brand}'"
                ),
                snippet=sentence,
            ))

    return findings
