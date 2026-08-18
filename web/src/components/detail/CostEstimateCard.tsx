import { useEffect, useMemo } from "react";
import {
  getScenarioCostStatus,
  type CostEstimateSummary,
  type CostScenarioSummary,
  type CostCategoryKey,
} from "@/types/cost";

interface CostEstimateCardProps {
  costEstimate?: CostEstimateSummary | null;
  activeScenarioId?: string | null;
  onScenarioSelect?: (scenarioId: string) => void;
}

const ALL_CATEGORIES: CostCategoryKey[] = [
  "intercity_transport",
  "accommodation",
  "local_transport",
  "admission",
  "meals",
];

const CATEGORY_META: Record<CostCategoryKey, { label: string; defaultIcon: string }> = {
  intercity_transport: { label: "交通", defaultIcon: "fa-plane" },
  accommodation: { label: "住宿", defaultIcon: "fa-hotel" },
  local_transport: { label: "市内交通", defaultIcon: "fa-bus" },
  admission: { label: "景点门票", defaultIcon: "fa-ticket" },
  meals: { label: "餐饮", defaultIcon: "fa-utensils" },
};

function formatEstimatedAt(isoString?: string): string | null {
  if (!isoString) return null;
  try {
    const d = new Date(isoString);
    if (Number.isNaN(d.getTime())) return null;
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  } catch {
    return null;
  }
}

export function CostEstimateCard({
  costEstimate,
  activeScenarioId,
  onScenarioSelect,
}: CostEstimateCardProps) {
  const scenarios = useMemo(() => costEstimate?.scenarios ?? [], [costEstimate]);
  const scenarioIds = scenarios.map((s) => s.scenario_id).join(",");

  const isDualMode = scenarios.length > 1;
  const selectedScenario: CostScenarioSummary | undefined = scenarios.find(
    (s) => s.scenario_id === activeScenarioId,
  );

  // 动态金额条比例计算（以当前场景最高 max_cny 为 100% 基准）
  const maxCategoryMaxCny = useMemo(() => {
    if (!selectedScenario) return 1;
    const maxVals = selectedScenario.categories
      .map((c) => (c.coverage === "priced" ? c.range?.max_cny ?? 0 : 0))
      .filter((v) => v > 0);
    return maxVals.length > 0 ? Math.max(...maxVals) : 1;
  }, [selectedScenario]);

  // 只有一个可用场景时自动激活
  useEffect(() => {
    if (scenarios.length === 1 && !activeScenarioId && onScenarioSelect) {
      onScenarioSelect(scenarios[0].scenario_id);
    }
  }, [scenarioIds, activeScenarioId, onScenarioSelect, scenarios]);

  if (!costEstimate || scenarios.length === 0) {
    return (
      <div className="rounded-2xl border border-primary-100 bg-white p-6 sm:p-8 shadow-soft space-y-4 scroll-mt-24">
        <h2 className="font-display text-2xl sm:text-3xl font-extrabold text-gray-900 tracking-tight">
          预算参考
        </h2>
        <div className="flex items-center gap-2 py-4 text-sm text-gray-400">
          <i className="fa-solid fa-circle-info text-gray-300" aria-hidden="true" />
          <span>费用暂不可估算</span>
        </div>
      </div>
    );
  }

  const isUnselected = isDualMode && !selectedScenario;
  const statusInfo = getScenarioCostStatus(selectedScenario, isUnselected);
  const estimatedAtText = formatEstimatedAt(costEstimate.estimated_at);

  const peakAmount = selectedScenario?.total_range?.max_cny;

  return (
    <div className="rounded-2xl border border-primary-100 bg-white p-6 sm:p-8 shadow-soft space-y-6 scroll-mt-24">
      {/* 1. 顶栏：标题 + Segmented Control 场景切换器 */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="font-display text-2xl sm:text-3xl font-bold tracking-tight text-gray-900">
          预算参考
        </h2>

        {/* 双场景 Segmented Control */}
        {isDualMode && (
          <div
            className="inline-flex items-center gap-1 rounded-xl bg-gray-100/90 p-1 border border-gray-200/50 shrink-0 self-start sm:self-auto"
            role="radiogroup"
            aria-label="大交通出行场景选择"
          >
            {scenarios.map((sc) => {
              const active = sc.scenario_id === activeScenarioId;
              return (
                <button
                  key={sc.scenario_id}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => onScenarioSelect?.(sc.scenario_id)}
                  onKeyDown={(e) => {
                    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                      e.preventDefault();
                      const currentIdx = scenarios.findIndex((s) => s.scenario_id === sc.scenario_id);
                      const nextIdx = e.key === "ArrowRight"
                        ? (currentIdx + 1) % scenarios.length
                        : (currentIdx - 1 + scenarios.length) % scenarios.length;
                      onScenarioSelect?.(scenarios[nextIdx].scenario_id);
                    }
                  }}
                  className={`px-3.5 py-1.5 text-xs font-bold rounded-lg transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 ${
                    active
                      ? "bg-white text-gray-900 shadow-xs"
                      : "text-gray-500 hover:text-gray-800"
                  }`}
                >
                  {sc.label}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* 2. 主数字区：与交通卡统一美观结构 */}
      <div>
        {/* 行1：场景与预估范围状态 */}
        <div className="text-xs font-normal text-gray-400 mb-1">
          {isUnselected ? (
            <span>选择大交通出行方案以查看预估</span>
          ) : selectedScenario ? (
            <>
              <span>{selectedScenario.label}</span>
              <span className="mx-1 text-gray-300">·</span>
              <span className={selectedScenario.total_scope === "full_trip" ? "text-teal-600 font-medium" : "text-amber-600 font-medium"}>
                {selectedScenario.total_scope === "full_trip" ? "完整预估" : "部分预估"}
              </span>
            </>
          ) : (
            <span>缺少有效价格来源</span>
          )}
        </div>

        {/* 行2：精致大数字 (符号小灰字 + 48px 纤细大数字) */}
        <div>
          {statusInfo.status === "unselected" ? (
            <div className="py-2 text-base font-bold text-gray-600">
              选择交通方式查看预估
            </div>
          ) : statusInfo.status === "unavailable" ? (
            <div className="py-2 text-xl font-bold text-gray-800">
              费用暂不可估算
            </div>
          ) : (
            <div className="flex flex-wrap items-baseline gap-1 my-1">
              <span className="text-xl sm:text-2xl font-light text-gray-400 mr-1.5 select-none">
                ¥
              </span>
              <span className="font-display text-4xl sm:text-5xl font-light tracking-tight text-gray-900 tabular-nums whitespace-nowrap">
                {peakAmount != null ? peakAmount.toLocaleString() : "0"}
              </span>
              {statusInfo.costBadge && (
                <span className="ml-3 rounded-full bg-amber-50 border border-amber-200 px-2.5 py-0.5 text-xs font-bold text-amber-700">
                  {statusInfo.costBadge}
                </span>
              )}
            </div>
          )}
        </div>

        {/* 行3：预估日期或补充说明 */}
        {estimatedAtText && (
          <div className="text-xs font-normal text-gray-400 mt-1">
            预估于 {estimatedAtText}
          </div>
        )}
      </div>

      {/* 3. 五类横向明细：像素级复刻参考图（直投 Icon -> 标签 -> 细线条 -> 右侧金额） */}
      {selectedScenario && (
        <div className="pt-2 divide-y divide-gray-100/80">
          {ALL_CATEGORIES.map((catKey) => {
            const cat = selectedScenario.categories.find((c) => c.category === catKey);
            const meta = CATEGORY_META[catKey];
            const isTrain = selectedScenario.intercity_mode === "train";
            const iconClass =
              catKey === "intercity_transport"
                ? isTrain ? "fa-train" : "fa-plane"
                : meta.defaultIcon;

            const isPolicyZero = cat?.price_basis === "policy_zero";
            const isPriced = cat?.coverage === "priced" && cat.range && !isPolicyZero;
            const amountVal = isPriced && cat.range ? cat.range.max_cny : null;

            // 4px 细进度条相对比例计算
            const barPercent = isPriced && cat.range
              ? Math.min(100, Math.max(6, Math.round((cat.range.max_cny / maxCategoryMaxCny) * 100)))
              : 0;

            const priceBasisText =
              cat?.price_basis === "sourced"
                ? "来源查价"
                : cat?.price_basis === "reference"
                  ? "参考估算"
                  : cat?.price_basis === "mixed"
                    ? "来源与参考混合"
                    : cat?.price_basis === "policy_zero"
                      ? "按规则计为 ¥0"
                      : null;

            return (
              <div
                key={catKey}
                className="py-3.5 flex items-center justify-between gap-4 sm:gap-8"
              >
                {/* 左侧：青色直投图标 + 分类 Label */}
                <div className="flex items-center gap-3 shrink-0 w-28 sm:w-32">
                  <i
                    className={`fa-solid ${iconClass} text-teal-600 text-base w-5 text-center shrink-0`}
                    aria-hidden="true"
                  />
                  <span className="text-sm font-medium text-gray-700">
                    {meta.label}
                  </span>
                </div>

                {/* 中间：4px 细线条进度条 */}
                <div className="flex-1 mx-2 sm:mx-6">
                  {isPriced ? (
                    <div className="h-1 w-full rounded-full bg-gray-100/80 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-teal-600 transition-all duration-300"
                        style={{ width: `${barPercent}%` }}
                      />
                    </div>
                  ) : (
                    <div className="h-1 w-full rounded-full border border-dashed border-gray-200 bg-gray-50/50" />
                  )}
                </div>

                {/* 右侧：金额 (复刻参考图单行右对齐) */}
                <div className="text-right shrink-0 min-w-[80px]">
                  {isPriced && amountVal != null ? (
                    <div className="text-sm font-medium text-gray-800 tabular-nums">
                      ¥ {amountVal.toLocaleString()}
                    </div>
                  ) : isPolicyZero ? (
                    <div className="text-sm font-medium text-gray-800 tabular-nums">
                      ¥ 0
                    </div>
                  ) : (
                    <span className="inline-block rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-400">
                      待确认
                    </span>
                  )}
                  {priceBasisText && (
                    <div className="text-[10px] text-gray-400 mt-0.5 hidden sm:block">
                      {priceBasisText}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 4. 页脚：极简提示文字 (复刻参考图底部小字) */}
      <div className="pt-2 text-xs font-normal text-gray-400 border-t border-gray-100/80">
        <p>{costEstimate.notice || "费用为规划参考，实际花费以出行行为准"}</p>
      </div>
    </div>
  );
}
