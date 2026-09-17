"""Unit tests for Amap → canonical place mapping and import ranking."""

from __future__ import annotations

import unittest

from src.pipeline.amap_place_search import PlaceSearchHit, SearchGroup, default_search_groups, parse_place_hit
from src.pipeline.amap_type_map import (
    is_junk_name,
    map_amap_poi,
    normalize_city_name,
    parse_category_tags,
)
from src.pipeline.canonical_amap_import import is_disconnect_error, prepare_hits
from src.pipeline.city_catalog import city_meta, city_slug


class TypeMapTests(unittest.TestCase):
    def test_normalize_city_strips_suffix(self) -> None:
        self.assertEqual(normalize_city_name("成都市"), "成都")
        self.assertEqual(normalize_city_name("重庆"), "重庆")

    def test_national_scenic_maps_to_attraction(self) -> None:
        mapped = map_amap_poi(
            name="宽窄巷子",
            typecode="110202",
            type_name="风景名胜;风景名胜;国家级景点",
            rating=4.8,
            city="成都",
        )
        self.assertIsNotNone(mapped)
        assert mapped is not None
        self.assertEqual(mapped.place_type, "attraction")
        self.assertGreaterEqual(mapped.base_priority, 95)
        self.assertFalse(mapped.contextual_only)

    def test_viewpoint_is_photo_spot(self) -> None:
        mapped = map_amap_poi(
            name="望江楼观景台",
            typecode="110209",
            type_name="风景名胜;风景名胜;观景点",
            city="成都",
        )
        self.assertIsNotNone(mapped)
        assert mapped is not None
        self.assertEqual(mapped.place_type, "photo_spot")

    def test_park_type(self) -> None:
        mapped = map_amap_poi(
            name="人民公园",
            typecode="110101",
            type_name="风景名胜;公园广场;公园",
            city="成都",
        )
        self.assertIsNotNone(mapped)
        assert mapped is not None
        self.assertEqual(mapped.place_type, "park")
        self.assertEqual(mapped.typical_visit_minutes, 90)

    def test_museum_from_name_override(self) -> None:
        mapped = map_amap_poi(
            name="成都博物馆",
            typecode="110202",
            type_name="风景名胜;风景名胜;国家级景点",
            city="成都",
        )
        self.assertIsNotNone(mapped)
        assert mapped is not None
        self.assertEqual(mapped.place_type, "museum")

    def test_company_rejected(self) -> None:
        self.assertIsNone(
            map_amap_poi(
                name="某科技有限公司",
                typecode="170200",
                type_name="公司企业;公司",
                city="成都",
            )
        )

    def test_beach_and_university_support(self) -> None:
        p_beach = map_amap_poi(
            name="青岛第一海水浴场",
            typecode="080109",
            type_name="体育休闲服务;运动场馆;海滨浴场",
            rating=4.8,
            city="青岛",
        )
        self.assertIsNotNone(p_beach)
        assert p_beach is not None
        self.assertEqual(p_beach.place_type, "attraction")
        self.assertGreaterEqual(p_beach.base_priority, 98)

        p_univ = map_amap_poi(
            name="武汉大学",
            typecode="141201",
            type_name="科教文化服务;学校;高等院校",
            rating=4.9,
            city="武汉",
        )
        self.assertIsNotNone(p_univ)
        assert p_univ is not None
        self.assertEqual(p_univ.place_type, "attraction")
        self.assertGreaterEqual(p_univ.base_priority, 95)

        # Campus sub-department buildings should be rejected
        self.assertTrue(is_junk_name("武汉大学艺术学院", city="武汉"))
        self.assertTrue(is_junk_name("清华大学第1教学楼", city="北京"))
        self.assertTrue(is_junk_name("新东方考研培训学校", city="北京"))

    def test_botanical_garden_and_zoo_priority(self) -> None:
        mapped_bot = map_amap_poi(
            name="国家植物园",
            typecode="110103",
            type_name="风景名胜;公园广场;植物园",
            rating=4.8,
            city="北京",
        )
        self.assertIsNotNone(mapped_bot)
        assert mapped_bot is not None
        self.assertEqual(mapped_bot.place_type, "park")
        self.assertGreaterEqual(mapped_bot.base_priority, 98)

        mapped_zoo = map_amap_poi(
            name="北京动物园",
            typecode="110102",
            type_name="风景名胜;公园广场;动物园",
            rating=4.7,
            city="北京",
        )
        self.assertIsNotNone(mapped_zoo)
        assert mapped_zoo is not None
        self.assertEqual(mapped_zoo.place_type, "park")
        self.assertGreaterEqual(mapped_zoo.base_priority, 98)

    def test_junk_names(self) -> None:
        self.assertTrue(is_junk_name("宽窄巷子停车场", city="成都"))
        self.assertTrue(is_junk_name("南门", city="成都"))
        self.assertTrue(is_junk_name("成都", city="成都"))
        self.assertTrue(is_junk_name("肯德基(春熙路店)", city="成都"))
        self.assertTrue(is_junk_name("药用植物园(不对外开放)", city="北京"))
        self.assertFalse(is_junk_name("宽窄巷子", city="成都"))

    def test_force_accommodation_area(self) -> None:
        mapped = map_amap_poi(
            name="春熙路商圈",
            typecode="061000",
            type_name="购物服务;特色商业街;步行街",
            city="成都",
            force_type="accommodation_area",
        )
        self.assertIsNotNone(mapped)
        assert mapped is not None
        self.assertEqual(mapped.place_type, "accommodation_area")
        self.assertTrue(mapped.contextual_only)
        self.assertIsNone(mapped.typical_visit_minutes)

    def test_category_tags_dedup(self) -> None:
        self.assertEqual(
            parse_category_tags("风景名胜;风景名胜;世界遗产"),
            ("风景名胜", "世界遗产"),
        )


class PlaceSearchParseTests(unittest.TestCase):
    def test_parse_hit_reads_biz_ext(self) -> None:
        hit = parse_place_hit(
            {
                "id": "B001",
                "name": "宽窄巷子",
                "type": "风景名胜;国家级景点",
                "typecode": "110202",
                "address": "长顺上街",
                "location": "104.054,30.663",
                "adcode": "510105",
                "adname": "青羊区",
                "cityname": "成都市",
                "biz_ext": {"rating": "4.8", "cost": "[]", "opentime_today": "全天"},
            }
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.poi_id, "B001")
        self.assertEqual(hit.rating, 4.8)
        self.assertIsNone(hit.avg_price)
        self.assertEqual(hit.open_time, "全天")
        self.assertAlmostEqual(hit.longitude, 104.054)
        self.assertAlmostEqual(hit.latitude, 30.663)

    def test_parse_hit_skips_missing_location(self) -> None:
        self.assertIsNone(parse_place_hit({"id": "B001", "name": "x"}))


class PrepareHitsTests(unittest.TestCase):
    def test_ranks_and_caps(self) -> None:
        hits = [
            PlaceSearchHit(
                poi_id="low",
                name="普通小店",
                type_name="餐饮服务;中餐厅",
                typecode="050100",
                address="a",
                longitude=104.0,
                latitude=30.0,
                adcode="510105",
                cityname="成都市",
                rating=4.4,
            ),
            PlaceSearchHit(
                poi_id="high",
                name="网红餐厅",
                type_name="餐饮服务;中餐厅",
                typecode="050100",
                address="b",
                longitude=104.1,
                latitude=30.1,
                adcode="510105",
                cityname="成都市",
                rating=4.9,
            ),
            PlaceSearchHit(
                poi_id="unrated",
                name="没分餐厅",
                type_name="餐饮服务;中餐厅",
                typecode="050100",
                address="c",
                longitude=104.2,
                latitude=30.2,
                adcode="510105",
                cityname="成都市",
                rating=None,
            ),
        ]
        group = SearchGroup(name="food", types="050000", max_keep=1, min_rating=4.3)
        prepared, counters = prepare_hits(
            hits,
            city="成都",
            group=group,
            geocode_city="成都市",
            seen_ids=set(),
            seen_names=set(),
        )
        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared[0].canonical_name, "网红餐厅")
        self.assertEqual(counters["skipped_rating"], 1)
        self.assertEqual(counters["scanned"], 3)

    def test_dedup_by_id_and_name(self) -> None:
        hit = PlaceSearchHit(
            poi_id="B1",
            name="宽窄巷子",
            type_name="风景名胜;国家级景点",
            typecode="110202",
            address="x",
            longitude=104.0,
            latitude=30.0,
            adcode="510105",
            cityname="成都市",
        )
        group = SearchGroup(name="scenic", types="110000", max_keep=10)
        prepared, counters = prepare_hits(
            [hit, hit],
            city="成都",
            group=group,
            geocode_city="成都市",
            seen_ids=set(),
            seen_names=set(),
        )
        self.assertEqual(len(prepared), 1)
        self.assertEqual(counters["skipped_dup"], 1)


class CityCatalogTests(unittest.TestCase):
    def test_known_city_slug(self) -> None:
        self.assertEqual(city_slug("成都"), "chengdu")
        self.assertEqual(city_meta("成都市").en_name, "Chengdu")

    def test_unknown_city_stable_id(self) -> None:
        self.assertEqual(city_slug("测试城"), city_slug("测试城"))
        self.assertTrue(city_slug("测试城").startswith("city-"))


if __name__ == "__main__":
    unittest.main()

class DisconnectTests(unittest.TestCase):
    def test_detects_windows_semaphore_timeout(self) -> None:
        err = OSError(121, "semaphore timeout")
        err.winerror = 121
        self.assertTrue(is_disconnect_error(err))

    def test_detects_asyncpg_closed_connection(self) -> None:
        self.assertTrue(
            is_disconnect_error(
                Exception("connection was closed in the middle of operation")
            )
        )
        self.assertFalse(is_disconnect_error(ValueError("invalid city")))


class SearchGroupTests(unittest.TestCase):
    def test_includes_suburban_scenic_queries(self) -> None:
        groups = default_search_groups()
        names = [group.name for group in groups]
        self.assertIn("heritage", names)
        self.assertIn("scenic_area", names)
        self.assertIn("named_park", names)
        self.assertIn("cultural_blocks", names)
        self.assertIn("landmarks_resort", names)
        self.assertIn("specialty_food", names)
        scenic_area = next(group for group in groups if group.name == "scenic_area")
        self.assertIn("风景区", scenic_area.keywords)
        park = next(group for group in groups if group.name == "park")
        self.assertGreaterEqual(park.max_keep, 12)

    def test_type_rules_map_theme_park_and_stadium(self) -> None:
        mapped_park = map_amap_poi(name="北京环球度假区", typecode="080501", type_name="体育休闲服务;休闲场所;游乐场", city="北京")
        self.assertIsNotNone(mapped_park)
        self.assertEqual(mapped_park.place_type, "attraction")

        mapped_stadium = map_amap_poi(name="国家体育场", typecode="080101", type_name="体育休闲服务;运动场馆;综合体育馆", city="北京")
        self.assertIsNotNone(mapped_stadium)
        self.assertEqual(mapped_stadium.place_type, "photo_spot")

        mapped_market = map_amap_poi(name="潘家园旧货市场", typecode="060702", type_name="购物服务;综合市场;旧货市场", city="北京")
        self.assertIsNotNone(mapped_market)
        self.assertEqual(mapped_market.place_type, "market")

