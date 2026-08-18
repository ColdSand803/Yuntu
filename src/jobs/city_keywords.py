"""Deterministic keyword generation for v0.5 city crawl batches."""

from __future__ import annotations

BASE_KEYWORD_SUFFIXES = (
    "\u65c5\u6e38",
    "\u653b\u7565",
    "citywalk",
    "\u7f8e\u98df",
    "\u62cd\u7167",
    "\u907f\u5751",
)

PREFERENCE_EXTENSION_KEYWORDS = {
    "old_street": "\u8001\u8857",
    "river_view": "\u6c5f\u666f",
    "museum": "\u535a\u7269\u9986",
    "niche": "\u5c0f\u4f17",
    "slow_travel": "\u6162\u65c5\u884c",
    "food": "\u7f8e\u98df",
    "photo": "\u62cd\u7167",
}


def base_city_keywords(city: str) -> list[tuple[str, str]]:
    canonical = city.strip()
    if not canonical:
        raise ValueError("city must not be empty")
    return [(f"{canonical}{suffix}", "BASE") for suffix in BASE_KEYWORD_SUFFIXES]


def extension_keywords_for_preferences(preferences: list[str] | None) -> list[str]:
    result: list[str] = []
    for pref in preferences or []:
        keyword = PREFERENCE_EXTENSION_KEYWORDS.get(pref)
        if keyword and keyword not in result:
            result.append(keyword)
        if len(result) >= 2:
            break
    return result


def city_batch_keywords(
    city: str,
    *,
    preferences: list[str] | None = None,
) -> list[tuple[str, str]]:
    keywords = base_city_keywords(city)
    for keyword in extension_keywords_for_preferences(preferences):
        full_keyword = f"{city}{keyword}"
        if full_keyword not in {item[0] for item in keywords}:
            keywords.append((full_keyword, "EXTENSION"))
    return keywords
