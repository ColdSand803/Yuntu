"""Public-text sanitization shared by export artifact renderers."""

from __future__ import annotations

import re
from typing import Any


PUBLIC_TAXONOMY_LABELS = {
    "relaxed": "轻松慢游",
    "moderate": "适中节奏",
    "intensive": "紧凑游览",
    "compact": "紧凑游览",
    "attraction": "景点游览",
    "business_area": "城市街区",
    "photo_stop": "拍照停留",
    "landmark": "城市地标",
    "food": "在地美食",
    "culture": "人文体验",
    "shopping": "逛街购物",
    "nature": "自然风光",
    "citywalk": "城市漫步",
    "night_view": "城市夜景",
    "walking": "步行",
    "transit": "公共交通",
    "taxi": "出租车",
    "driving": "驾车",
    "within_limit": "节奏合理",
    "over_limit": "节奏偏紧",
    "within_budget": "预算范围内",
    "over_budget": "超出预算",
}
HIDDEN_TAXONOMY_LABELS = {
    "anchor",
    "filler",
    "optional",
}
_KNOWN_TOKEN_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?:"
    + "|".join(
        re.escape(value)
        for value in sorted(
            (*PUBLIC_TAXONOMY_LABELS, *HIDDEN_TAXONOMY_LABELS),
            key=len,
            reverse=True,
        )
    )
    + r")(?![A-Za-z0-9_])"
)
_UNKNOWN_SNAKE_CASE_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:"
    r"_+[a-z0-9]+(?:_[a-z0-9]+)*"
    r"|"
    r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+"
    r")(?![A-Za-z0-9])"
)


def public_text(value: Any, default: str = "") -> str:
    """Return display-safe text without internal or unknown snake_case tokens."""

    raw = _plain_text(value)
    if not raw:
        return default

    def replace_known(match: re.Match[str]) -> str:
        return PUBLIC_TAXONOMY_LABELS.get(match.group(0).lower(), "")

    clean = _KNOWN_TOKEN_PATTERN.sub(replace_known, raw)
    clean = _UNKNOWN_SNAKE_CASE_PATTERN.sub("", clean)
    clean = re.sub(r"\s*[/|]+\s*", " · ", clean)
    clean = re.sub(r"(?:\s*·\s*){2,}", " · ", clean)
    clean = re.sub(r"\s+([，。！？；、,:：;])", r"\1", clean)
    clean = re.sub(r"(?:^|[；;])\s*[A-Za-z][A-Za-z0-9 ]*=\s*(?=$|[；;])", "", clean)
    clean = clean.strip(" \t\r\n/|·,，;；:=：")
    return _plain_text(clean, default)


def public_items(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = public_text(item)
        if text and text not in seen:
            items.append(text)
            seen.add(text)
        if len(items) >= limit:
            break
    return items


def _plain_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text if text else default
