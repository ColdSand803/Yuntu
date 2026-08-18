-- ============================================================
-- Yuntu - 重庆精选真实种子数据 (Chongqing Seed Data)
-- 包含：城市激活状态、25+ 核心经典地点/美食/文化点、住宿商圈
-- ============================================================

BEGIN;

-- 1. 激活重庆城市记录
INSERT INTO travel_city (canonical_name, status, active_confirmed_time, created_time, updated_time)
VALUES ('重庆', 'ACTIVE', NOW(), NOW(), NOW())
ON CONFLICT (canonical_name) DO UPDATE 
SET status = 'ACTIVE', active_confirmed_time = NOW();

-- 2. 住宿推荐商圈 (accommodation_area)
INSERT INTO travel_canonical_place (
    canonical_name, city, district, address, adcode, latitude, longitude,
    amap_poi_id, place_type, category_tags, source_type, trust_level,
    review_status, is_active, contextual_only, geo_status, base_priority
) VALUES
('解放碑(商圈)', '重庆', '渝中区', '渝中区民权路', '500103', 29.556728, 106.576880, 'B0FFGI0JVF', 'accommodation_area', '["商圈", "市中心", "地标"]'::jsonb, 'amap', 'trusted', 'auto_accepted', TRUE, TRUE, 'resolved', 100),
('观音桥商圈', '重庆', '江北区', '江北区观音桥步行街', '500105', 29.576104, 106.533919, 'B0FFHOSTJ8', 'accommodation_area', '["商圈", "繁华", "美食"]'::jsonb, 'amap', 'trusted', 'auto_accepted', TRUE, TRUE, 'resolved', 95),
('南坪商圈', '重庆', '南岸区', '南岸区江南大道', '500108', 29.525042, 106.567212, 'B0LUPR3PAF', 'accommodation_area', '["商圈", "交通便利"]'::jsonb, 'amap', 'trusted', 'auto_accepted', TRUE, TRUE, 'resolved', 90),
('沙坪坝商圈', '重庆', '沙坪坝区', '沙坪坝区小龙坎新街', '500106', 29.554318, 106.457829, 'B0FFH1Q73E', 'accommodation_area', '["商圈", "高校区"]'::jsonb, 'amap', 'trusted', 'auto_accepted', TRUE, TRUE, 'resolved', 85)
ON CONFLICT DO NOTHING;

-- 3. 核心精选 POI 地点
INSERT INTO travel_canonical_place (
    canonical_name, city, district, address, adcode, latitude, longitude,
    amap_poi_id, place_type, category_tags, typical_visit_minutes, typical_visit_source,
    source_type, trust_level, review_status, is_active, contextual_only, geo_status, base_priority
) VALUES
-- 渝中区 (核心母城)
('洪崖洞民俗风貌区', '重庆', '渝中区', '渝中区嘉陵江滨江路88号', '500103', 29.562914, 106.582236, 'B0FFG8Y2L6', 'attraction', '["夜景", "吊脚楼", "网红打卡", "必去"]'::jsonb, 90, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 100),
('解放碑步行街', '重庆', '渝中区', '渝中区民族路177号', '500103', 29.557218, 106.577132, 'B0FFG0N645', 'attraction', '["地标", "历史纪念碑", "购物", "步行街"]'::jsonb, 60, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 98),
('长江索道', '重庆', '渝中区', '渝中区新华路151号', '500103', 29.558312, 106.584321, 'B001783TNL', 'attraction', '["索道", "江景", "空中巴士", "地标"]'::jsonb, 45, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 95),
('山城步道', '重庆', '渝中区', '渝中区中兴路234号', '500103', 29.551829, 106.570129, 'B0FFH7Q1A9', 'attraction', '["Citywalk", "老重庆", "江景", "步道"]'::jsonb, 90, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 92),
('十八梯传统风貌区', '重庆', '渝中区', '渝中区中兴路1号', '500103', 29.552431, 106.573512, 'B0J1K9L0M1', 'attraction', '["老街", "历史风貌", "夜景", "小吃"]'::jsonb, 75, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 90),
('李子坝轻轨穿楼', '重庆', '渝中区', '渝中区李子坝正街39号', '500103', 29.553924, 106.539218, 'B0FFH8M4P2', 'photo_spot', '["轻轨穿楼", "魔幻地形", "拍照打卡"]'::jsonb, 40, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 95),
('戴家巷崖壁步道', '重庆', '渝中区', '渝中区戴家巷', '500103', 29.563412, 106.580219, 'B0J2K3L4M5', 'photo_spot', '["悬崖步道", "咖啡馆", "江景", "文艺"]'::jsonb, 60, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 88),
('白象居', '重庆', '渝中区', '渝中区白象街4号', '500103', 29.556213, 106.586129, 'B0FFJ7K9L2', 'photo_spot', '["魔幻居民楼", "索道同框", "机位打卡"]'::jsonb, 50, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 87),
('湖广会馆', '重庆', '渝中区', '渝中区长滨路芭蕉园1号', '500103', 29.555219, 106.589124, 'B001783T6H', 'museum', '["古建筑群", "移民文化", "黄色封火墙", "历史"]'::jsonb, 75, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 85),
('重庆中国三峡博物馆', '重庆', '渝中区', '渝中区人民路236号', '500103', 29.565412, 106.550219, 'B001783U2L', 'museum', '["国家一级博物馆", "巴渝文化", "三峡历史"]'::jsonb, 120, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 90),
('重庆市人民大礼堂', '重庆', '渝中区', '渝中区人民路173号', '500103', 29.564819, 106.551912, 'B001783TNM', 'attraction', '["传统民族宫殿建筑", "地标", "广场"]'::jsonb, 45, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 86),
('罗汉寺', '重庆', '渝中区', '渝中区罗汉寺街7号', '500103', 29.560124, 106.581291, 'B001783TO1', 'attraction', '["千年古刹", "疯狂的石头取景地", "闹市净土"]'::jsonb, 60, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 82),

-- 渝中区/江北区 美食代表
('八一好吃街', '重庆', '渝中区', '渝中区八一路177号', '500103', 29.556214, 106.576129, 'B0FFH9N2K1', 'market', '["小吃街", "酸辣粉", "山城小汤圆", "串串"]'::jsonb, 60, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 92),
('大井巷社区火锅', '重庆', '渝中区', '渝中区大井巷老居民楼下', '500103', 29.555812, 106.578192, 'B0J3K4L5M6', 'restaurant', '["老火锅", "社区美食", "地道市井"]'::jsonb, 90, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 85),
('杨记隆府(解放碑总店)', '重庆', '渝中区', '渝中区临江支路30号', '500103', 29.558912, 106.574129, 'B0FFGX78Y9', 'restaurant', '["江湖菜", "辣子鸡", "毛血旺", "特色餐饮"]'::jsonb, 90, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 88),

-- 沙坪坝区 / 九龙坡区 (文化与慢生活)
('磁器口古镇', '重庆', '沙坪坝区', '沙坪坝区磁南街1号', '500106', 29.582914, 106.448219, 'B001783TNN', 'attraction', '["千年古镇", "陈麻花", "嘉陵江畔", "民俗文化"]'::jsonb, 120, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 93),
('渣滓洞/白公馆', '重庆', '沙坪坝区', '沙坪坝区歌乐山下', '500106', 29.581219, 106.425129, 'B001783TO2', 'museum', '["红色历史", "爱国教育", "歌乐山"]'::jsonb, 90, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 80),
('鹅岭二厂文创公园', '重庆', '渝中区', '渝中区鹅岭正街1号', '500103', 29.550124, 106.538129, 'B0FFH9M2Q8', 'park', '["文创园区", "俯瞰江景", "从你的全世界路过", "文艺打卡"]'::jsonb, 90, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 90),
('交通茶馆', '重庆', '九龙坡区', '九龙坡区黄桷坪正街20号', '500107', 29.498214, 106.532129, 'B0FFG8M4X3', 'attraction', '["老茶馆", "盖碗茶", "市井风情", "年代感"]'::jsonb, 60, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 86),
('黄桷坪涂鸦艺术街', '重庆', '九龙坡区', '九龙坡区黄桷坪正街', '500107', 29.499124, 106.531219, 'B0FFG9N5Y1', 'photo_spot', '["当代艺术", "巨幅涂鸦", "川美老校区"]'::jsonb, 60, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 82),

-- 南岸区 / 江北区 (江景与夜景视角)
('弹子石老街', '重庆', '南岸区', '南岸区泰昌路69号', '500108', 29.566129, 106.599124, 'B0FFH8Q3M1', 'attraction', '["百年老街", "江海关", "绝美夜景", "两江交汇"]'::jsonb, 90, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 89),
('南山一棵树观景台', '重庆', '南岸区', '南岸区龙黄公路', '500108', 29.544129, 106.595124, 'B001783TNP', 'photo_spot', '["全景夜景", "俯瞰渝中半岛", "摄影胜地"]'::jsonb, 60, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 91),
('九街/观音桥夜市', '重庆', '江北区', '江北区北城天街', '500105', 29.578129, 106.538124, 'B0FFH7P2L9', 'market', '["年轻潮流", "夜生活", "酒吧街", "地道小吃"]'::jsonb, 90, 'manual', 'official', 'trusted', 'auto_accepted', TRUE, FALSE, 'resolved', 88)
ON CONFLICT DO NOTHING;

COMMIT;
