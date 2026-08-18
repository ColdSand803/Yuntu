"""Conservative deterministic filtering for Xiaohongshu travel notes."""

from __future__ import annotations

import re

from src.xhs.models import XhsSearchItem

_TRAVEL_MARKERS = (
    "旅游", "旅行", "攻略", "景点", "路线", "citywalk", "美食",
    "拍照", "避坑", "周末", "一日游", "两日游", "三天两夜",
    "博物馆", "公园", "古镇", "老街", "夜景",
)
_CLEARLY_UNRELATED = (
    "招聘", "招人", "求职", "简历", "转租", "整租", "合租", "租房",
    "加盟", "微商", "代购", "课程报名", "医美", "应援", "站姐",
    "明星周边", "票务转让", "收票", "出票",
)
_PURE_SALES = re.compile(r"(下单|领券|优惠券|私信购买|加微|包邮|同款链接)")


def should_reject_search_item(item: XhsSearchItem, *, city: str) -> bool:
    """Reject only content that is clearly unrelated to city travel."""
    text = item.title.strip().lower()
    if not text:
        return False
    if any(marker.lower() in text for marker in _CLEARLY_UNRELATED):
        return True
    if _PURE_SALES.search(text):
        has_travel_context = city.lower() in text or any(
            marker.lower() in text for marker in _TRAVEL_MARKERS
        )
        return not has_travel_context
    return False


def rank_score(item: XhsSearchItem) -> float:
    """Use interactions only as an in-keyword ordering signal."""
    return (
        (item.collected_count or 0) * 2
        + (item.liked_count or 0)
        + (item.shared_count or 0) * 1.5
        + (item.comment_count or 0) * 0.25
    )


def filter_and_rank(
    notes: list[XhsSearchItem],
    *,
    city: str,
    top_n: int,
) -> list[XhsSearchItem]:
    passed = [note for note in notes if not should_reject_search_item(note, city=city)]
    passed.sort(key=rank_score, reverse=True)
    return passed[:top_n]
