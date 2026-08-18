import type { CostEstimateSummary } from "@/types/cost";
import type { TripResult } from "@/types/trip";

export const COST_ESTIMATE_COMPLETE: CostEstimateSummary = {
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

export const COST_ESTIMATE_PARTIAL: CostEstimateSummary = {
  snapshot_version: "1",
  completeness: "partial",
  currency: "CNY",
  estimated_at: "2026-08-04T00:00:00Z",
  scenarios: [
    {
      scenario_id: "without_intercity",
      intercity_mode: null,
      label: "不含大交通方案",
      total_scope: "estimated_subset",
      total_range: { min_cny: 900, max_cny: 1460 },
      categories: [
        { category: "intercity_transport", coverage: "missing", range: null, price_basis: null, basis_label: "未提供出发城市" },
        { category: "accommodation", coverage: "priced", range: { min_cny: 400, max_cny: 700 }, price_basis: "reference", basis_label: "解放碑舒适型酒店" },
        { category: "local_transport", coverage: "priced", range: { min_cny: 100, max_cny: 160 }, price_basis: "reference", basis_label: "市内公共交通与打车" },
        { category: "admission", coverage: "priced", range: { min_cny: 100, max_cny: 200 }, price_basis: "sourced", basis_label: "行程景点门票" },
        { category: "meals", coverage: "priced", range: { min_cny: 300, max_cny: 400 }, price_basis: "reference", basis_label: "餐饮消费参考" },
      ],
      missing_categories: ["intercity_transport"],
    },
  ],
  assumptions: [{ code: "two_travellers_per_room", label: "每间房两位旅客" }],
  exclusions: [],
  notice: "费用为规划参考，实际支付金额请以预订或现场结算为准",
};

export const COST_ESTIMATE_UNAVAILABLE: CostEstimateSummary = {
  snapshot_version: "1",
  completeness: "unavailable",
  currency: "CNY",
  estimated_at: "2026-08-04T00:00:00Z",
  scenarios: [
    {
      scenario_id: "without_intercity",
      intercity_mode: null,
      label: "暂不可估算场景",
      total_scope: "unavailable",
      total_range: null,
      categories: [
        { category: "intercity_transport", coverage: "missing", range: null, price_basis: null, basis_label: "暂不可估算" },
        { category: "accommodation", coverage: "missing", range: null, price_basis: null, basis_label: "暂不可估算" },
        { category: "local_transport", coverage: "missing", range: null, price_basis: null, basis_label: "暂不可估算" },
        { category: "admission", coverage: "missing", range: null, price_basis: null, basis_label: "暂不可估算" },
        { category: "meals", coverage: "missing", range: null, price_basis: null, basis_label: "暂不可估算" },
      ],
      missing_categories: ["intercity_transport", "accommodation", "local_transport", "admission", "meals"],
    },
  ],
  assumptions: [],
  exclusions: [],
  notice: "费用为规划参考，实际支付金额请以预订或现场结算为准",
};

export const COST_ESTIMATE_SINGLE_TRAIN: CostEstimateSummary = {
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
  ],
  assumptions: [{ code: "two_travellers_per_room", label: "每间房两位旅客" }],
  exclusions: [],
  notice: "费用为规划参考，实际支付金额请以预订或现场结算为准",
};

export const COST_ESTIMATE_MIXED_POLICY_ZERO: CostEstimateSummary = {
  snapshot_version: "1",
  completeness: "partial",
  currency: "CNY",
  estimated_at: "2026-08-04T00:00:00Z",
  scenarios: [
    {
      scenario_id: "train_round_trip",
      intercity_mode: "train",
      label: "高铁混合方案",
      total_scope: "estimated_subset",
      total_range: { min_cny: 500, max_cny: 800 },
      categories: [
        { category: "intercity_transport", coverage: "priced", range: { min_cny: 200, max_cny: 300 }, price_basis: "mixed", basis_label: "高铁+中转车次混合" },
        { category: "accommodation", coverage: "priced", range: { min_cny: 300, max_cny: 500 }, price_basis: "reference", basis_label: "经济型连锁酒店" },
        { category: "local_transport", coverage: "priced", range: { min_cny: 0, max_cny: 0 }, price_basis: "policy_zero", basis_label: "步行全覆盖免市内交通费" },
        { category: "admission", coverage: "missing", range: null, price_basis: null, basis_label: "无付费景点" },
        { category: "meals", coverage: "missing", range: null, price_basis: null, basis_label: "餐饮自理未估" },
      ],
      missing_categories: ["admission", "meals"],
    },
  ],
  assumptions: [{ code: "two_travellers_per_room", label: "每间房两位旅客" }],
  exclusions: [],
  notice: "费用为规划参考，实际支付金额请以预订或现场结算为准",
};

export const SAMPLE_RESULT_V094: TripResult = {
  schema_version: "2.0",
  result_id: 801,
  city: { name: "重庆" },
  request: { days: 3, people_count: 2, preferences: ["美食"], avoid: [] },
  must_include: [
    { name: "解放碑", status: "scheduled", place_id: 1, reason: null },
    { name: "九寨沟", status: "cross_city", place_id: null, reason: "不在目的地城市范围内" },
  ],
  plans: [
    {
      plan_id: "plan_v094_1",
      title: "重庆经典 3 日游",
      summary: "经典地标与老街漫步方案",
      tags: ["经典", "美食"],
      pace: { level: "MODERATE", commute_status: "WITHIN_LIMIT", total_commute_minutes: 40 },
      cost_estimate: COST_ESTIMATE_COMPLETE,
      days: [
        {
          day: 1,
          title: "解放碑与洪崖洞",
          commute_summary: "总通勤约 20 分钟",
          pace_status: "WITHIN_LIMIT",
          narrative: "第一天打卡解放碑与洪崖洞。",
          places: [
            { place_id: 1, name: "解放碑", category: "landmark", longitude: 106.5784, latitude: 29.5574, role: "anchor", optional: false, brief: "核心地标" },
            { place_id: 2, name: "洪崖洞", category: "landmark", longitude: 106.5827, latitude: 29.5631, role: "anchor", optional: false, brief: "吊脚楼夜景" },
          ],
          commute_legs: [
            { from_place_id: 1, to_place_id: 2, mode: "walking", duration_minutes: 10, distance_meters: 700 },
          ],
        },
      ],
    },
  ],
};
