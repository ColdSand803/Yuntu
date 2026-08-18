/**
 * Schema 2.0 Trip Cost Estimate (行程消费预估) 前端严格契约定义
 * 对应服务端 v0.9.4 / Schema 2.0 public contract (yuntu_travel_models.py)
 */

export type CostCompleteness = "complete" | "partial" | "unavailable";

export type CostScope = "full_trip" | "estimated_subset" | "unavailable";

export type CostCategoryKey =
  | "intercity_transport"
  | "accommodation"
  | "local_transport"
  | "admission"
  | "meals";

export type CostCoverage = "priced" | "missing";

export type CostPriceBasis = "sourced" | "reference" | "mixed" | "policy_zero" | null;

export type CostScenarioId = "train_round_trip" | "flight_round_trip" | "without_intercity";

export type CostAssumptionCode =
  | "two_travellers_per_room"
  | "itinerary_days_minus_one_nights"
  | "four_travellers_per_taxi"
  | "adult_full_fare"
  | "two_main_meals_per_day";

export type CostExclusionCode = "cycling_cost_not_included";

export interface CostMoneyRange {
  min_cny: number;
  max_cny: number;
}

export function formatMoneyRange(range: CostMoneyRange | null | undefined): string {
  if (!range) return "";
  if (range.min_cny === range.max_cny) {
    return `¥${range.min_cny.toLocaleString()}`;
  }
  return `¥${range.min_cny.toLocaleString()}–¥${range.max_cny.toLocaleString()}`;
}

export interface CostCategorySummary {
  category: CostCategoryKey;
  coverage: CostCoverage;
  range: CostMoneyRange | null;
  price_basis: CostPriceBasis;
  basis_label: string;
}

export interface CostScenarioSummary {
  scenario_id: CostScenarioId;
  intercity_mode: "train" | "flight" | null;
  label: string;
  total_scope: CostScope;
  total_range: CostMoneyRange | null;
  categories: CostCategorySummary[];
  missing_categories: CostCategoryKey[];
}

export interface CostAssumptionSummary {
  code: CostAssumptionCode;
  label: string;
}

export interface CostExclusionSummary {
  code: CostExclusionCode;
  label: string;
}

export interface CostEstimateSummary {
  snapshot_version: "1";
  completeness: CostCompleteness;
  currency: "CNY";
  estimated_at: string;
  scenarios: CostScenarioSummary[];
  assumptions: CostAssumptionSummary[];
  exclusions: CostExclusionSummary[];
  notice: string;
}

export interface ScenarioCostStatus {
  status: "unselected" | "complete" | "partial" | "unavailable";
  costText: string;
  costBadge: string | null;
  showAmount: boolean;
}

export function formatMoneyPeak(range?: CostMoneyRange | null): string {
  if (!range) return "";
  return `¥ ${range.max_cny.toLocaleString()}`;
}

/**
 * 统一场景消费状态计算函数
 * 页面 Hero、TripSpine、CostEstimateCard 统一根据当前 activeScenario.total_scope 映射
 * 顶部总额取 max_cny 峰值单数字展示，符合高颜值单数字与预算上限视觉层级
 */
export function getScenarioCostStatus(
  scenario?: CostScenarioSummary | null,
  isUnselected?: boolean,
): ScenarioCostStatus {
  if (isUnselected) {
    return {
      status: "unselected",
      costText: "选择交通方式查看预估",
      costBadge: null,
      showAmount: false,
    };
  }

  if (!scenario || scenario.total_scope === "unavailable") {
    return {
      status: "unavailable",
      costText: "费用暂不可估算",
      costBadge: null,
      showAmount: false,
    };
  }

  if (scenario.total_scope === "full_trip") {
    return {
      status: "complete",
      costText: `预估 ${formatMoneyPeak(scenario.total_range)}`,
      costBadge: null,
      showAmount: true,
    };
  }

  return {
    status: "partial",
    costText: `已估 ${formatMoneyPeak(scenario.total_range)}`,
    costBadge: "部分费用待确认",
    showAmount: true,
  };
}
