"""Map Amap POI typecodes onto Yuntu canonical place fields."""

from __future__ import annotations

import re
from dataclasses import dataclass

PROTECTED_SOURCE_TYPES = frozenset({"official", "manual"})

DEFAULT_VISIT_MINUTES = {
    "attraction": 90,
    "park": 90,
    "museum": 75,
    "photo_spot": 45,
    "restaurant": 90,
    "market": 90,
    "business_area": 60,
}

MAJOR_NAME_MARKERS = ("景区", "风景区", "古镇", "老街", "世界遗产", "国家公园", "度假区", "度假村", "艺术区", "植物园", "动物园", "国家", "体育场", "游泳中心", "大剧院", "乐园", "海水浴场", "沙滩", "大学")

_JUNK_NAME = re.compile(
    r"(停车场|停车楼|停车位|停车点|P\d+|卫生间|公厕|厕所|出入口|售票处|检票|"
    r"闸机|充电站|加油站|收费站|公交站|地铁站|候车室|服务区|办公区|居民小区|"
    r"物业|充电桩|肯德基|麦当劳|汉堡王|华莱士|德克士|必胜客|KFC|McDonald|不对外开放|不开放|内部开放|暂未开放|筹建|暂停营业|培训|驾校|考研|补习|专修|进修)"
)
_GATE_NAME = re.compile(r"(东门|西门|南门|北门|正门|后门|侧门|入口|出口)$")
_CAMPUS_SUB_SPOT = re.compile(r"(学院|系|教研室|行政楼|办公楼|处|部|分部|分院|研究院|后勤|招生|就业|校医院|宿舍|食堂|实验楼|教学楼|综合楼)$")

# Longest prefix first. Unlisted prefixes are rejected.
_TYPE_RULES: tuple[tuple[str, str, int], ...] = (
    ("080501", "attraction", 96),
    ("080400", "attraction", 88),
    ("080603", "attraction", 88),
    ("080602", "attraction", 88),
    ("080101", "photo_spot", 88),
    ("080109", "attraction", 90),
    ("141201", "attraction", 85),
    ("060702", "market", 75),
    ("060700", "market", 72),
    ("110201", "attraction", 100),
    ("110202", "attraction", 98),
    ("110210", "attraction", 92),
    ("110203", "attraction", 90),
    ("110208", "attraction", 88),
    ("110206", "attraction", 76),
    ("110207", "attraction", 76),
    ("110205", "attraction", 78),
    ("110209", "photo_spot", 80),
    ("110204", "museum", 82),
    ("110106", "park", 85),
    ("110101", "park", 82),
    ("110102", "park", 90),
    ("110103", "park", 90),
    ("110104", "attraction", 75),
    ("110105", "photo_spot", 70),
    ("110100", "park", 75),
    ("110200", "attraction", 80),
    ("110000", "attraction", 70),
    ("140100", "museum", 85),
    ("140400", "museum", 82),
    ("140600", "museum", 80),
    ("140200", "museum", 75),
    ("0610", "business_area", 88),
    ("060400", "market", 72),
    ("060401", "market", 74),
    ("0601", "business_area", 65),
    ("0505", "restaurant", 62),
    ("0509", "restaurant", 58),
    ("0508", "restaurant", 58),
    ("0507", "restaurant", 55),
    ("0506", "restaurant", 60),
    ("0504", "restaurant", 58),
    ("0503", "restaurant", 52),
    ("050", "restaurant", 60),
)

_REJECT_PREFIXES = (
    "01",
    "02",
    "03",
    "04",
    "07",
    "08",
    "09",
    "10",
    "12",
    "13",
    "15",
    "16",
    "17",
    "18",
    "19",
    "20",
    "22",
    "97",
    "99",
)


@dataclass(frozen=True)
class MappedPlace:
    place_type: str
    contextual_only: bool
    typical_visit_minutes: int | None
    base_priority: int
    category_tags: tuple[str, ...]
    reject_reason: str | None = None


def normalize_city_name(value: str) -> str:
    city = (value or "").strip()
    if not city:
        raise ValueError("city name must not be empty")
    if city.endswith("市") and len(city) > 2:
        return city[:-1]
    return city


def is_junk_name(name: str, city: str | None = None) -> bool:
    compact = re.sub(r"\s+", "", name or "")
    if len(compact) < 2:
        return True
    if city:
        city_norm = normalize_city_name(city)
        if compact in {city_norm, city_norm + "市", city_norm + "旅游"}:
            return True
    if _JUNK_NAME.search(compact):
        return True
    if _GATE_NAME.search(compact) and len(compact) <= 8:
        return True
    if _CAMPUS_SUB_SPOT.search(compact) and ("大学" in compact or "学院" in compact) and len(compact) > 4:
        return True
    return False


def parse_category_tags(type_name: str | None) -> tuple[str, ...]:
    if not type_name:
        return ()
    seen: list[str] = []
    for part in type_name.split(";"):
        item = part.strip()
        if item and item not in seen:
            seen.append(item)
    return tuple(seen)


def _match_type_rule(typecode: str) -> tuple[str, int] | None:
    code = (typecode or "").strip()
    if not code:
        return None
    for prefix, place_type, priority in _TYPE_RULES:
        if code.startswith(prefix):
            return place_type, priority
    return None


def _name_type_override(name: str, place_type: str) -> str:
    if "博物馆" in name or "美术馆" in name or "科技馆" in name:
        return "museum"
    if place_type == "attraction" and any(token in name for token in ("公园", "植物园", "动物园")):
        return "park"
    if place_type == "attraction" and any(token in name for token in ("观景", "打卡", "玻璃栈道", "体育场", "体育馆", "游泳中心")):
        return "photo_spot"
    return place_type


def compute_priority(
    *,
    base_priority: int,
    rating: float | None,
    name: str,
    typecode: str,
) -> int:
    score = base_priority
    if rating is not None:
        score += int(round((rating - 3.5) * 8))
    if any(marker in name for marker in MAJOR_NAME_MARKERS + ("步行街", "商圈")):
        score += 6
    if typecode.startswith(("110201", "110202")):
        score = max(score, 95)
    return max(1, min(100, score))


def map_amap_poi(
    *,
    name: str,
    typecode: str | None,
    type_name: str | None,
    rating: float | None = None,
    city: str | None = None,
    force_type: str | None = None,
) -> MappedPlace | None:
    """Return canonical fields for one Amap POI, or None when it should be dropped."""
    if is_junk_name(name, city=city):
        return None

    tags = parse_category_tags(type_name)
    code = (typecode or "").strip()

    if force_type:
        visit = DEFAULT_VISIT_MINUTES.get(force_type)
        if force_type == "accommodation_area":
            visit = None
        if any(code.startswith(prefix) for prefix in ("15", "16", "17", "18", "19", "20", "01")):
            return None
        priority = compute_priority(
            base_priority=90 if force_type == "accommodation_area" else 70,
            rating=rating,
            name=name,
            typecode=code,
        )
        return MappedPlace(
            place_type=force_type,
            contextual_only=force_type == "accommodation_area",
            typical_visit_minutes=visit,
            base_priority=priority,
            category_tags=tags,
        )

    matched = _match_type_rule(code)
    if matched is None:
        return None
    place_type, base_priority = matched
    place_type = _name_type_override(name, place_type)
    visit = DEFAULT_VISIT_MINUTES.get(place_type)
    if visit and any(marker in name for marker in MAJOR_NAME_MARKERS):
        visit = max(visit, 120)
        visit = min(visit, 480)
    priority = compute_priority(
        base_priority=base_priority,
        rating=rating,
        name=name,
        typecode=code,
    )
    return MappedPlace(
        place_type=place_type,
        contextual_only=False,
        typical_visit_minutes=visit,
        base_priority=priority,
        category_tags=tags,
    )