import type { TripResult } from "@/types/trip";
import type { CostEstimateSummary } from "@/types/cost";

export const DEFAULT_COST_ESTIMATE: CostEstimateSummary = {
  snapshot_version: "1",
  completeness: "complete",
  currency: "CNY",
  estimated_at: "2026-08-04T00:00:00Z",
  scenarios: [
    {
      scenario_id: "train_round_trip",
      intercity_mode: "train",
      label: "高铁往返方案",
      total_scope: "full_trip",
      total_range: { min_cny: 1200, max_cny: 1800 },
      categories: [
        { category: "intercity_transport", coverage: "priced", range: { min_cny: 300, max_cny: 340 }, price_basis: "sourced", basis_label: "实时车次方案" },
        { category: "accommodation", coverage: "priced", range: { min_cny: 400, max_cny: 700 }, price_basis: "reference", basis_label: "解放碑舒适型酒店" },
        { category: "local_transport", coverage: "priced", range: { min_cny: 100, max_cny: 160 }, price_basis: "reference", basis_label: "市内公共交通与打车" },
        { category: "admission", coverage: "priced", range: { min_cny: 100, max_cny: 200 }, price_basis: "sourced", basis_label: "行程景点门票" },
        { category: "meals", coverage: "priced", range: { min_cny: 300, max_cny: 400 }, price_basis: "reference", basis_label: "餐饮消费参考" },
      ],
      missing_categories: [],
    },
    {
      scenario_id: "flight_round_trip",
      intercity_mode: "flight",
      label: "机票往返方案",
      total_scope: "full_trip",
      total_range: { min_cny: 1800, max_cny: 2400 },
      categories: [
        { category: "intercity_transport", coverage: "priced", range: { min_cny: 900, max_cny: 940 }, price_basis: "reference", basis_label: "机票参考价" },
        { category: "accommodation", coverage: "priced", range: { min_cny: 400, max_cny: 700 }, price_basis: "reference", basis_label: "解放碑舒适型酒店" },
        { category: "local_transport", coverage: "priced", range: { min_cny: 100, max_cny: 160 }, price_basis: "reference", basis_label: "市内公共交通与打车" },
        { category: "admission", coverage: "priced", range: { min_cny: 100, max_cny: 200 }, price_basis: "sourced", basis_label: "行程景点门票" },
        { category: "meals", coverage: "priced", range: { min_cny: 300, max_cny: 400 }, price_basis: "reference", basis_label: "餐饮消费参考" },
      ],
      missing_categories: [],
    },
  ],
  assumptions: [{ code: "two_travellers_per_room", label: "每间房两位旅客" }],
  exclusions: [{ code: "cycling_cost_not_included", label: "骑行费用暂未计入" }],
  notice: "费用为规划参考，实际支付金额请以预订或现场结算为准",
};

/**
 * v0.8.12 P6 视觉验收 fixtures（仅 /demo 路由懒加载，不进主包）。
 * 数据形状对齐 yuntu-travel P5 验收产物：
 * docs/acceptance/v0.8.12-p5-backend/*.json 与 tests/fixtures/v0812_p3_result_schema_1_5.json。
 * 覆盖场景：无固定时间 / partial must-include / 仅 period / 合法 exact time /
 * 单主景点 Day / 多停留点 Day / Schema 1.4 旧结果 / Schema 1.5 新结果。
 */

export interface FixtureEntry {
  key: string;
  title: string;
  description: string;
  covers: string[];
  result: TripResult;
}

/** Schema 1.5 · 无固定时间 + 单主景点/多停留点 + partial must-include + 通勤降级 */
const V15_NO_TIME: TripResult = {
  schema_version: "1.5",
  result_id: 91500,
  city: { name: "重庆" },
  request: {
    days: 2,
    people_count: 1,
    preferences: ["citywalk", "轻松"],
    avoid: [],
  },
  weather: { status: "skipped_disabled", city: "重庆", days: [] },
  // 无固定时间：后端不返回 time_preferences 字段
  plans: [
    {
      plan_id: "plan_a",
      title: "重庆动物园与渝中江岸",
      summary: "首日整日沉浸动物园，次日渝中半岛多点串联，节奏松弛",
      tags: ["citywalk", "轻松", "亲子"],
      pace: { level: "RELAXED", commute_status: "WITHIN_LIMIT", total_commute_minutes: 42 },
      cost_estimate: DEFAULT_COST_ESTIMATE,
      days: [
        {
          day: 1,
          title: "重庆动物园全日深游",
          places: [
            {
              place_id: 311,
              name: "重庆动物园",
              category: "attraction",
              longitude: 106.5102,
              latitude: 29.5051,
              role: "anchor_activity",
              optional: false,
              brief: "西南地区代表性动物园，大熊猫馆常年热门",
              activity_note:
                "按大熊猫馆、金鱼池、两爬馆的园区分区逐段游览，中途在草坪区安排休息；旺季熊猫馆建议优先排队。",
              schedule: { period: "morning", exact_start: null, exact_end: null, exact_time_source: null },
            },
          ],
          commute_legs: [],
          commute_summary: "当日集中在动物园园区内，无跨点通勤",
          pace_status: "WITHIN_LIMIT",
          narrative: "整日只安排动物园一个主景点，园区面积大、动线长，无固定时间约束下按体力自由推进。",
        },
        {
          day: 2,
          title: "山城巷至千厮门大桥",
          places: [
            {
              place_id: 321,
              name: "山城巷",
              category: "attraction",
              longitude: 106.5716,
              latitude: 29.5537,
              role: "anchor_activity",
              optional: false,
              brief: "依山而建的老城步道，保留山城原生街巷肌理",
              activity_note: "沿崖边栈道自下而上慢走，重点看领事巷一段的老建筑与江景开口。",
              schedule: { period: "morning", exact_start: null, exact_end: null, exact_time_source: null },
            },
            {
              place_id: 322,
              name: "解放碑",
              category: "business_area",
              longitude: 106.5784,
              latitude: 29.5574,
              role: "secondary_activity",
              optional: false,
              brief: "渝中商圈核心地标",
              activity_note: "以步行街环线为主，顺路解决午餐，不作长停留。",
              schedule: { period: "afternoon", exact_start: null, exact_end: null, exact_time_source: null },
            },
            {
              place_id: 323,
              name: "洪崖洞",
              category: "attraction",
              longitude: 106.5827,
              latitude: 29.5631,
              role: "anchor_activity",
              optional: false,
              brief: "吊脚楼建筑群，临江立面为城市名片",
              activity_note: "从顶层平台向下逐层逛，傍晚亮灯前后立面观感差异大，可在观景平台多留一段。",
              schedule: { period: "evening", exact_start: null, exact_end: null, exact_time_source: null },
            },
            {
              place_id: 324,
              name: "千厮门大桥",
              category: "photo_spot",
              longitude: 106.5807,
              latitude: 29.5672,
              role: "photo_stop",
              optional: true,
              brief: "步行可上的跨江大桥，回望洪崖洞的经典机位",
              activity_note: "桥面人行道回望洪崖洞全景，夜间灯光完全点亮后构图最完整。",
              schedule: { period: "night", exact_start: null, exact_end: null, exact_time_source: null },
            },
          ],
          commute_legs: [
            {
              from_place_id: 321,
              to_place_id: 322,
              mode: "transit",
              duration_source: "amap",
              duration_minutes: 22,
              distance_meters: 2600,
              transit_steps: [
                { kind: "walking", duration_minutes: 4, distance_meters: 300, line_name: null, provider_type: null, from_stop: null, to_stop: null, stop_count: null },
                { kind: "rail", duration_minutes: 6, distance_meters: 1900, line_name: "轨道交通1号线", provider_type: "地铁线路", from_stop: "较场口站", to_stop: "小什字站", stop_count: 2 },
                { kind: "walking", duration_minutes: 8, distance_meters: 500, line_name: null, provider_type: null, from_stop: null, to_stop: null, stop_count: null },
              ],
              transit_summary: "公共交通预计 22 分钟：乘轨道交通1号线（较场口站上车，小什字站下车，2站）",
            },
            {
              from_place_id: 322,
              to_place_id: 323,
              mode: "walking",
              duration_source: "amap",
              duration_minutes: 10,
              distance_meters: 750,
            },
            {
              // provider 降级：无结构化线路，仅后端通用提示
              from_place_id: 323,
              to_place_id: 324,
              mode: "transit",
              duration_source: "estimate",
              duration_minutes: 12,
              distance_meters: 900,
              transit_steps: [],
              transit_summary: "公共交通预计 12 分钟：线路明细暂不可用，请以现场导航为准",
            },
          ],
          commute_summary: "公共交通与步行结合，总通勤约 44 分钟",
          pace_status: "WITHIN_LIMIT",
          narrative: "从山城巷老街开场，经解放碑短暂过渡，傍晚洪崖洞收束，夜间可选千厮门大桥拍照。",
        },
      ],
    },
  ],
  must_include: [
    { name: "重庆动物园", status: "scheduled", place_id: 311, matched_city: "重庆" },
    {
      name: "洪崖洞夜景",
      status: "not_scheduled",
      reason: "同日路线与时长预算未能容纳",
    },
    {
      name: "武隆天生三桥",
      status: "cross_city",
      reason: "地点位于武隆区，超出本次重庆市内行程范围",
    },
  ],
};

/** Schema 1.5 · 固定时间窗 + 受治理 exact time（reservation/event/transport） */
const V15_EXACT_TIME: TripResult = {
  schema_version: "1.5",
  result_id: 91501,
  city: { name: "重庆" },
  request: {
    days: 1,
    people_count: 2,
    preferences: ["文化历史"],
    avoid: [],
  },
  weather: { status: "skipped_disabled", city: "重庆", days: [] },
  time_preferences: { daily_start: "09:00", daily_end: "21:00" },
  plans: [
    {
      plan_id: "plan_a",
      title: "两江文博一日线",
      summary: "索道过江开场，午后博物馆讲解预约，夜间川剧收尾",
      tags: ["文化历史", "适中"],
      pace: { level: "MODERATE", commute_status: "WITHIN_LIMIT", total_commute_minutes: 53 },
      cost_estimate: DEFAULT_COST_ESTIMATE,
      days: [
        {
          day: 1,
          title: "索道博物馆川剧一日",
          places: [
            {
              place_id: 411,
              name: "长江索道",
              category: "attraction",
              longitude: 106.5829,
              latitude: 29.5528,
              role: "anchor_activity",
              optional: false,
              brief: "横跨长江的城市过江索道",
              activity_note: "持预订班次凭码过闸，过江单程约 5 分钟，靠南侧车窗看江面视角更开阔。",
              schedule: {
                period: "morning",
                exact_start: "10:20",
                exact_end: null,
                exact_time_source: "transport",
              },
            },
            {
              place_id: 412,
              name: "湖广会馆",
              category: "attraction",
              longitude: 106.5862,
              latitude: 29.5556,
              role: "secondary_activity",
              optional: false,
              brief: "清代移民会馆建筑群",
              activity_note: "重点看戏楼藻井与封火墙，馆内展线不长，顺路安排即可。",
              schedule: { period: "afternoon", exact_start: null, exact_end: null, exact_time_source: null },
            },
            {
              place_id: 413,
              name: "重庆中国三峡博物馆",
              category: "attraction",
              longitude: 106.5483,
              latitude: 29.5631,
              role: "anchor_activity",
              optional: false,
              brief: "三峡文物与巴渝历史主馆",
              activity_note: "已预约人工讲解场次，从壮丽三峡展厅进馆，讲解结束后可自行补看抗战岁月展。",
              schedule: {
                period: "afternoon",
                exact_start: "14:30",
                exact_end: "16:00",
                exact_time_source: "reservation",
              },
            },
            {
              place_id: 414,
              name: "重庆川剧艺术中心",
              category: "attraction",
              longitude: 106.5313,
              latitude: 29.6009,
              role: "anchor_activity",
              optional: false,
              brief: "川剧常驻演出剧场",
              activity_note: "晚场折子戏含变脸与吐火段落，开演前 20 分钟入场选中区座位。",
              schedule: {
                period: "evening",
                exact_start: "19:30",
                exact_end: null,
                exact_time_source: "event",
              },
            },
          ],
          commute_legs: [
            {
              from_place_id: 411,
              to_place_id: 412,
              mode: "walking",
              duration_source: "amap",
              duration_minutes: 12,
              distance_meters: 900,
            },
            {
              from_place_id: 412,
              to_place_id: 413,
              mode: "transit",
              duration_source: "amap",
              duration_minutes: 23,
              distance_meters: 4300,
              transit_steps: [
                { kind: "walking", duration_minutes: 6, distance_meters: 450, line_name: null, provider_type: null, from_stop: null, to_stop: null, stop_count: null },
                { kind: "rail", duration_minutes: 12, distance_meters: 3400, line_name: "轨道交通2号线", provider_type: "地铁线路", from_stop: "临江门站", to_stop: "曾家岩站", stop_count: 4 },
                { kind: "walking", duration_minutes: 5, distance_meters: 400, line_name: null, provider_type: null, from_stop: null, to_stop: null, stop_count: null },
              ],
              transit_summary: "公共交通预计 23 分钟：乘轨道交通2号线（临江门站上车，曾家岩站下车，4站）",
            },
            {
              from_place_id: 413,
              to_place_id: 414,
              mode: "transit",
              duration_source: "amap",
              duration_minutes: 18,
              distance_meters: 5200,
              transit_steps: [
                { kind: "bus", duration_minutes: 15, distance_meters: 4800, line_name: "262路", provider_type: "普通公交线路", from_stop: "三峡博物馆站", to_stop: "川剧院站", stop_count: 6 },
                { kind: "walking", duration_minutes: 3, distance_meters: 250, line_name: null, provider_type: null, from_stop: null, to_stop: null, stop_count: null },
              ],
              transit_summary: "公共交通预计 18 分钟：乘262路（三峡博物馆站上车，川剧院站下车，6站）",
            },
          ],
          commute_summary: "公共交通与步行结合，总通勤约 53 分钟",
          pace_status: "WITHIN_LIMIT",
          narrative: "三个硬时间锚点（索道班次、讲解预约、晚场演出）串起全天，其余停留围绕锚点弹性安排。",
        },
      ],
    },
  ],
  must_include: [
    { name: "重庆中国三峡博物馆", status: "scheduled", place_id: 413, matched_city: "重庆" },
  ],
};

/** Schema 1.4 · 旧结果：无 activity_note/schedule/must_include，transit_steps 照常保留 */
const V14_LEGACY: TripResult = {
  schema_version: "1.4",
  result_id: 91400,
  city: { name: "重庆" },
  request: {
    days: 2,
    people_count: 1,
    preferences: ["美食", "citywalk"],
    avoid: ["太累"],
  },
  plans: [
    {
      plan_id: "plan_a",
      title: "渝中经典两日",
      summary: "渝中半岛经典地标与磁器口古镇，节奏轻松",
      tags: ["轻松", "经典"],
      pace: { level: "RELAXED", commute_status: "WITHIN_LIMIT", total_commute_minutes: 55 },
      cost_estimate: DEFAULT_COST_ESTIMATE,
      days: [
        {
          day: 1,
          title: "渝中半岛经典一日",
          places: [
            {
              place_id: 511,
              name: "解放碑",
              category: "business_area",
              longitude: 106.5784,
              latitude: 29.5574,
              role: "anchor_activity",
              optional: false,
              brief: "重庆地标，商圈核心",
            },
            {
              place_id: 512,
              name: "十八梯",
              category: "attraction",
              longitude: 106.5753,
              latitude: 29.5538,
              role: "secondary_activity",
              optional: false,
              brief: "山城老街巷，市井生活缩影",
            },
            {
              place_id: 513,
              name: "洪崖洞",
              category: "attraction",
              longitude: 106.5827,
              latitude: 29.5631,
              role: "anchor_activity",
              optional: false,
              brief: "吊脚楼建筑群，夜景绝佳",
            },
          ],
          commute_legs: [
            {
              from_place_id: 511,
              to_place_id: 512,
              mode: "walking",
              duration_source: "amap",
              duration_minutes: 10,
              distance_meters: 700,
            },
            {
              from_place_id: 512,
              to_place_id: 513,
              mode: "transit",
              duration_source: "amap",
              duration_minutes: 15,
              distance_meters: 1800,
              transit_steps: [
                { kind: "walking", duration_minutes: 5, distance_meters: 350, line_name: null, provider_type: null, from_stop: null, to_stop: null, stop_count: null },
                { kind: "rail", duration_minutes: 6, distance_meters: 1300, line_name: "轨道交通2号线", provider_type: "地铁线路", from_stop: "较场口站", to_stop: "临江门站", stop_count: 2 },
              ],
              transit_summary: "公共交通预计 15 分钟：乘轨道交通2号线（较场口站上车，临江门站下车，2站）",
            },
          ],
          commute_summary: "步行与轨道交通结合，总通勤约 25 分钟",
          pace_status: "WITHIN_LIMIT",
          narrative: "从解放碑出发，沿十八梯步行至洪崖洞，感受最经典的山城地标；晚上洪崖洞亮灯后是拍照最佳时机。",
        },
        {
          day: 2,
          title: "磁器口与鹅岭一日",
          places: [
            {
              place_id: 514,
              name: "磁器口古镇",
              category: "attraction",
              longitude: 106.4483,
              latitude: 29.5793,
              role: "anchor_activity",
              optional: false,
              brief: "千年古镇，山城老味道",
            },
            {
              place_id: 515,
              name: "鹅岭二厂",
              category: "attraction",
              longitude: 106.5325,
              latitude: 29.5525,
              role: "secondary_activity",
              optional: true,
              brief: "老厂房改造的文创园区",
            },
          ],
          commute_legs: [
            {
              from_place_id: 514,
              to_place_id: 515,
              mode: "transit",
              duration_source: "amap",
              duration_minutes: 30,
              distance_meters: 9500,
              transit_steps: [
                { kind: "rail", duration_minutes: 22, distance_meters: 8800, line_name: "轨道交通1号线", provider_type: "地铁线路", from_stop: "磁器口站", to_stop: "两路口站", stop_count: 7 },
                { kind: "walking", duration_minutes: 8, distance_meters: 700, line_name: null, provider_type: null, from_stop: null, to_stop: null, stop_count: null },
              ],
              transit_summary: "公共交通预计 30 分钟：乘轨道交通1号线（磁器口站上车，两路口站下车，7站）",
            },
          ],
          commute_summary: "轨道交通为主，总通勤约 30 分钟",
          pace_status: "WITHIN_LIMIT",
          narrative: "上午磁器口尝陈麻花、买火锅底料，下午鹅岭二厂看文创园区，慢慢逛不赶路。",
        },
      ],
    },
  ],
};

export const V0812_FIXTURES: Record<string, FixtureEntry> = {
  "v15-notime": {
    key: "v15-notime",
    title: "Schema 1.5 · 无固定时间",
    description: "未设置每日时间窗；单主景点 Day + 多停留点 Day；partial must-include；含通勤降级段",
    covers: ["无固定时间", "单主景点 Day", "多停留点 Day", "仅 period 无 exact time", "partial must-include", "通勤降级提示", "Schema 1.5"],
    result: V15_NO_TIME,
  },
  "v15-exact": {
    key: "v15-exact",
    title: "Schema 1.5 · 受治理精确时间",
    description: "固定 09:00-21:00 时间窗；transport/reservation/event 三种合法 exact time 来源",
    covers: ["合法 exact time", "exact 来源标注", "固定时间窗", "结构化公交明细", "Schema 1.5"],
    result: V15_EXACT_TIME,
  },
  "v14-legacy": {
    key: "v14-legacy",
    title: "Schema 1.4 · 旧结果兼容",
    description: "无 activity_note/schedule/must_include；不显示任何时段与时间；transit_steps 照常展示",
    covers: ["Schema 1.4 旧结果", "brief 回退", "无伪造 period/时间", "transit_steps 保留"],
    result: V14_LEGACY,
  },
};
