"""Versioned v0.6.16 popular-city bootstrap ranking."""

from __future__ import annotations

from dataclasses import dataclass


RANKING_VERSION = "2026-06-12-v1"

RANKING_SOURCES = (
    {
        "name": "Ctrip 2025 May Day domestic top destinations",
        "url": "https://www.caacnews.com.cn/1/6/202505/t20250505_1387097.html",
    },
    {
        "name": "Xinhua 2025 May Day destination demand",
        "url": "https://www.news.cn/travel/20250421/8f5aaeda13df446588efb2a707a63419/c.html",
    },
    {
        "name": "Tongcheng 2025 graduate travel guide",
        "url": "https://www.news.cn/travel/20250610/0557d6d5dbc4412a93cda680768fd873/c.html",
    },
    {
        "name": "Mafengwo 2025 Spring Festival travel data",
        "url": "https://www.ccn.com.cn/Content/2025/02-07/1710484754.html",
    },
    {
        "name": "MCT 2025 summer travel trend forecast",
        "url": "https://www.mct.gov.cn/whzx/zsdw/whbxxzx_bnsj/202506/t20250618_960685.html",
    },
)


@dataclass(frozen=True)
class RankedCity:
    rank: int
    name: str
    category: str
    first_batch: bool = False
    benchmark: bool = False


POPULAR_CITIES = (
    RankedCity(1, "北京", "comprehensive_culture", True),
    RankedCity(2, "上海", "comprehensive_urban", True),
    RankedCity(3, "重庆", "food_urban", True, True),
    RankedCity(4, "成都", "food_leisure", True),
    RankedCity(5, "杭州", "comprehensive_leisure", True),
    RankedCity(6, "西安", "history_culture", True),
    RankedCity(7, "南京", "history_culture", True),
    RankedCity(8, "长沙", "food_urban", True),
    RankedCity(9, "青岛", "coastal", True),
    RankedCity(10, "桂林", "nature_leisure", True),
    RankedCity(11, "广州", "food_urban"),
    RankedCity(12, "武汉", "comprehensive_urban"),
    RankedCity(13, "苏州", "history_leisure"),
    RankedCity(14, "厦门", "coastal"),
    RankedCity(15, "昆明", "nature_leisure"),
    RankedCity(16, "三亚", "coastal"),
    RankedCity(17, "大理", "nature_leisure"),
    RankedCity(18, "丽江", "history_leisure"),
    RankedCity(19, "哈尔滨", "seasonal_culture"),
    RankedCity(20, "洛阳", "history_culture"),
    RankedCity(21, "泉州", "history_food"),
    RankedCity(22, "福州", "history_food"),
    RankedCity(23, "天津", "comprehensive_urban"),
    RankedCity(24, "深圳", "comprehensive_urban"),
    RankedCity(25, "珠海", "coastal"),
    RankedCity(26, "威海", "coastal"),
    RankedCity(27, "张家界", "nature"),
    RankedCity(28, "大同", "history_culture"),
    RankedCity(29, "乌鲁木齐", "regional_gateway"),
    RankedCity(30, "开封", "history_food"),
)


def first_batch_cities() -> tuple[RankedCity, ...]:
    return tuple(city for city in POPULAR_CITIES if city.first_batch)
