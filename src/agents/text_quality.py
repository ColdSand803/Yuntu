"""Shared deterministic text-quality helpers for itinerary generation."""

from __future__ import annotations

import re


RARE_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x20000, 0x2A6DF),  # CJK Unified Ideographs Extension B
    (0x2A700, 0x2B73F),  # Extension C
    (0x2B740, 0x2B81F),  # Extension D
    (0x2B820, 0x2CEAF),  # Extension E
    (0x2CEB0, 0x2EBEF),  # Extension F
    (0x2EBF0, 0x2EE5F),  # Extension I
    (0x30000, 0x323AF),  # Extensions G and H
    (0x2F800, 0x2FA1F),  # CJK Compatibility Ideographs Supplement
)

BANNED_DATABASE_PHRASES = (
    "作者推荐",
    "作者很喜欢",
    "作者很爱",
    "博主推荐",
    "博主很喜欢",
    "博主很爱",
    "当地美食推荐",
    "当地人常去",
    "当地人推荐",
    "附近居民常去",
    "居民常去",
    "亲测",
    "据说",
    "听说",
    "网传",
    "数据推荐",
    "可以解决午饭",
    "解决午餐",
    "解决晚餐",
    "来源推荐",
    "根据数据",
    "美食推荐",
    "很多人推荐",
    "很多人喜欢",
    "不少人推荐",
    "不少人喜欢",
    "大家推荐",
    "大家喜欢",
)

PLACEHOLDER_PHRASES = (
    "该处",
    "该处该处",
)


def find_phrase_spans(text: str, phrases: tuple[str, ...] | list[str]) -> list[tuple[str, int, int]]:
    """Return (phrase, start, end) spans for exact phrase hits, longest-first."""
    value = text or ""
    if not value:
        return []
    ordered = sorted({phrase for phrase in phrases if phrase}, key=lambda item: (-len(item), item))
    claimed: list[tuple[int, int]] = []
    spans: list[tuple[str, int, int]] = []
    for phrase in ordered:
        for match in re.finditer(re.escape(phrase), value):
            span = (match.start(), match.end())
            if any(span[0] < used[1] and used[0] < span[1] for used in claimed):
                continue
            claimed.append(span)
            spans.append((phrase, span[0], span[1]))
    spans.sort(key=lambda item: (item[1], item[2], item[0]))
    return spans


def extract_claimed_names(text: str, candidate_names: list[str]) -> list[str]:
    """Extract mentioned candidate names with longest-name precedence."""
    claimed_ranges: list[tuple[int, int]] = []
    found: list[tuple[int, str]] = []
    for name in sorted(set(candidate_names), key=lambda value: (-len(value), value)):
        for occurrence in re.finditer(re.escape(name), text or ""):
            occurrence_range = (occurrence.start(), occurrence.end())
            if any(
                occurrence_range[0] < claimed_end
                and claimed_start < occurrence_range[1]
                for claimed_start, claimed_end in claimed_ranges
            ):
                continue
            claimed_ranges.append(occurrence_range)
            found.append((occurrence.start(), name))
    found.sort(key=lambda item: (item[0], -len(item[1]), item[1]))
    return list(dict.fromkeys(name for _, name in found))


def rare_cjk_characters(text: str) -> list[str]:
    """Return rare CJK characters that are risky for WeCom/Windows clients."""
    found: list[str] = []
    for char in text or "":
        codepoint = ord(char)
        if any(start <= codepoint <= end for start, end in RARE_CJK_RANGES):
            found.append(char)
    return list(dict.fromkeys(found))


def strip_rare_cjk_characters(text: str) -> tuple[str, list[str]]:
    """Remove rare CJK characters; return cleaned text and removed characters."""
    removed = rare_cjk_characters(text)
    if not removed:
        return text or "", []
    cleaned = text or ""
    for char in removed:
        cleaned = cleaned.replace(char, "")
    return cleaned, removed
