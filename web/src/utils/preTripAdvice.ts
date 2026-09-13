import type { PackingChecklistGroup, TravelTip } from "@/types/trip";

/**
 * 安全过滤行李清单：过滤空分类、空条目及空白字符串
 */
export function filterPackingChecklist(
  groups?: PackingChecklistGroup[] | null,
): PackingChecklistGroup[] {
  if (!groups || !Array.isArray(groups)) return [];
  return groups
    .map((g) => ({
      category: typeof g?.category === "string" ? g.category.trim() : "",
      items: Array.isArray(g?.items)
        ? g.items
            .map((item) => (typeof item === "string" ? item.trim() : ""))
            .filter((item) => item.length > 0)
        : [],
    }))
    .filter((g) => g.category.length > 0 && g.items.length > 0);
}

/**
 * 安全过滤实用避坑贴士：过滤空标题或空内容
 */
export function filterTravelTips(tips?: TravelTip[] | null): TravelTip[] {
  if (!tips || !Array.isArray(tips)) return [];
  return tips
    .map((t) => ({
      title: typeof t?.title === "string" ? t.title.trim() : "",
      content: typeof t?.content === "string" ? t.content.trim() : "",
    }))
    .filter((t) => t.title.length > 0 && t.content.length > 0);
}

/**
 * 判断是否存在任何有效的行前建议内容
 */
export function hasPreTripAdviceData(
  packingChecklist?: PackingChecklistGroup[] | null,
  travelTips?: TravelTip[] | null,
): boolean {
  return (
    filterPackingChecklist(packingChecklist).length > 0 ||
    filterTravelTips(travelTips).length > 0
  );
}
