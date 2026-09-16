"""Display metadata for cinematic destination cards and map points."""

from __future__ import annotations

import base64
from dataclasses import dataclass

from src.pipeline.amap_type_map import normalize_city_name


@dataclass(frozen=True)
class CityMeta:
    id: str
    name: str
    en_name: str
    iata: str = ""
    region: str = ""
    lat: float = 0.0
    lng: float = 0.0
    tags: tuple[str, ...] = ()
    map_label_offset: tuple[int, int] = (0, 0)
    card_cover_url: str = "/city-placeholder.svg"
    background_image_url: str = ""


_CHONGQING_BG = (
    "https://images.unsplash.com/photo-1548685913-fe6678babe8d"
    "?w=1600&auto=format&fit=crop&q=80"
)

CITY_CATALOG: dict[str, CityMeta] = {
    "重庆": CityMeta(
        id="chongqing",
        name="重庆",
        en_name="Chongqing",
        iata="CKG",
        region="西南",
        lat=29.56301,
        lng=106.551557,
        tags=("8D魔幻", "赛博朋克", "火锅之都", "江畔夜景"),
        map_label_offset=(10, 6),
        background_image_url=_CHONGQING_BG,
    ),
    "成都": CityMeta(
        id="chengdu", name="成都", en_name="Chengdu", iata="CTU", region="西南",
        lat=30.5728, lng=104.0668, tags=("慢生活", "火锅", "熊猫"),
    ),
    "北京": CityMeta(
        id="beijing", name="北京", en_name="Beijing", iata="PEK", region="华北",
        lat=39.9042, lng=116.4074, tags=("古都", "故宫", "胡同"),
    ),
    "上海": CityMeta(
        id="shanghai", name="上海", en_name="Shanghai", iata="SHA", region="华东",
        lat=31.2304, lng=121.4737, tags=("外滩", "摩登", "江南"),
    ),
    "广州": CityMeta(
        id="guangzhou", name="广州", en_name="Guangzhou", iata="CAN", region="华南",
        lat=23.1291, lng=113.2644, tags=("早茶", "花城", "骑楼"),
    ),
    "深圳": CityMeta(
        id="shenzhen", name="深圳", en_name="Shenzhen", iata="SZX", region="华南",
        lat=22.5431, lng=114.0579, tags=("科技", "海岸", "都市"),
    ),
    "杭州": CityMeta(
        id="hangzhou", name="杭州", en_name="Hangzhou", iata="HGH", region="华东",
        lat=30.2741, lng=120.1551, tags=("西湖", "江南", "茶香"),
    ),
    "西安": CityMeta(
        id="xian", name="西安", en_name="Xi'an", iata="XIY", region="西北",
        lat=34.3416, lng=108.9398, tags=("兵马俑", "古城墙", "十三朝"),
    ),
    "南京": CityMeta(
        id="nanjing", name="南京", en_name="Nanjing", iata="NKG", region="华东",
        lat=32.0603, lng=118.7969, tags=("金陵", "梧桐", "民国"),
    ),
    "武汉": CityMeta(
        id="wuhan", name="武汉", en_name="Wuhan", iata="WUH", region="华中",
        lat=30.5928, lng=114.3055, tags=("江城", "黄鹤楼", "樱花"),
    ),
    "厦门": CityMeta(
        id="xiamen", name="厦门", en_name="Xiamen", iata="XMN", region="东南",
        lat=24.4798, lng=118.0894, tags=("鼓浪屿", "海边", "文艺"),
    ),
    "苏州": CityMeta(
        id="suzhou", name="苏州", en_name="Suzhou", iata="SZV", region="华东",
        lat=31.2989, lng=120.5853, tags=("园林", "昆曲", "江南"),
    ),
    "长沙": CityMeta(
        id="changsha", name="长沙", en_name="Changsha", iata="CSX", region="华中",
        lat=28.2282, lng=112.9388, tags=("湘菜", "橘子洲", "夜生活"),
    ),
    "昆明": CityMeta(
        id="kunming", name="昆明", en_name="Kunming", iata="KMG", region="西南",
        lat=25.0389, lng=102.7183, tags=("春城", "石林", "鲜花"),
    ),
    "大理": CityMeta(
        id="dali", name="大理", en_name="Dali", iata="DLU", region="西南",
        lat=25.6065, lng=100.2676, tags=("洱海", "苍山", "风花雪月"),
    ),
    "丽江": CityMeta(
        id="lijiang", name="丽江", en_name="Lijiang", iata="LJG", region="西南",
        lat=26.8721, lng=100.2299, tags=("古城", "玉龙雪山", "慢生活"),
    ),
    "青岛": CityMeta(
        id="qingdao", name="青岛", en_name="Qingdao", iata="TAO", region="华东",
        lat=36.0671, lng=120.3826, tags=("海边", "啤酒", "老洋房"),
    ),
    "桂林": CityMeta(
        id="guilin", name="桂林", en_name="Guilin", iata="KWL", region="华南",
        lat=25.2736, lng=110.29, tags=("山水", "漓江", "阳朔"),
    ),
    "三亚": CityMeta(
        id="sanya", name="三亚", en_name="Sanya", iata="SYX", region="华南",
        lat=18.2528, lng=109.5119, tags=("海滩", "度假", "热带"),
    ),
    "哈尔滨": CityMeta(
        id="harbin", name="哈尔滨", en_name="Harbin", iata="HRB", region="东北",
        lat=45.8038, lng=126.5349, tags=("冰雪", "俄式", "中央大街"),
    ),
    "天津": CityMeta(
        id="tianjin", name="天津", en_name="Tianjin", iata="TSN", region="华北",
        lat=39.3434, lng=117.3616, tags=("海河", "洋楼", "相声"),
    ),
    "宁波": CityMeta(
        id="ningbo", name="宁波", en_name="Ningbo", iata="NGB", region="华东",
        lat=29.8683, lng=121.544, tags=("港城", "老外滩", "海鲜"),
    ),
    "无锡": CityMeta(
        id="wuxi", name="无锡", en_name="Wuxi", iata="WUX", region="华东",
        lat=31.4912, lng=120.3119, tags=("太湖", "灵山", "江南"),
    ),
    "洛阳": CityMeta(
        id="luoyang", name="洛阳", en_name="Luoyang", iata="LYA", region="华中",
        lat=34.6197, lng=112.454, tags=("牡丹", "龙门石窟", "古都"),
    ),
    "张家界": CityMeta(
        id="zhangjiajie", name="张家界", en_name="Zhangjiajie", iata="DYG", region="华中",
        lat=29.1173, lng=110.4792, tags=("天门山", "阿凡达", "石英砂岩"),
    ),
    "黄山": CityMeta(
        id="huangshan", name="黄山", en_name="Huangshan", iata="TXN", region="华东",
        lat=29.7147, lng=118.3376, tags=("奇松", "云海", "徽州"),
    ),
    "敦煌": CityMeta(
        id="dunhuang", name="敦煌", en_name="Dunhuang", iata="DNH", region="西北",
        lat=40.1411, lng=94.6616, tags=("莫高窟", "鸣沙山", "丝路"),
    ),
    "拉萨": CityMeta(
        id="lhasa", name="拉萨", en_name="Lhasa", iata="LXA", region="西南",
        lat=29.652, lng=91.1721, tags=("布达拉宫", "高原", "转经"),
    ),
    "乌鲁木齐": CityMeta(
        id="urumqi", name="乌鲁木齐", en_name="Urumqi", iata="URC", region="西北",
        lat=43.8256, lng=87.6168, tags=("天山", "大巴扎", "羊肉"),
    ),
}


def city_slug(name: str) -> str:
    city = normalize_city_name(name)
    meta = CITY_CATALOG.get(city)
    if meta:
        return meta.id
    encoded = base64.urlsafe_b64encode(city.encode("utf-8")).decode("ascii").rstrip("=")
    return f"city-{encoded}"


def city_meta(name: str) -> CityMeta:
    city = normalize_city_name(name)
    meta = CITY_CATALOG.get(city)
    if meta:
        return meta
    return CityMeta(id=city_slug(city), name=city, en_name=city)