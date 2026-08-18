export function formatMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes} 分钟`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m > 0 ? `${h} 小时 ${m} 分钟` : `${h} 小时`;
}

export function formatDistance(meters: number): string {
  if (meters < 1000) return `${meters}m`;
  return `${(meters / 1000).toFixed(1)}km`;
}

export function commuteModeName(mode: string): string {
  const map: Record<string, string> = {
    walking: "步行",
    transit: "公交",
    taxi: "打车",
    driving: "驾车",
    cycling: "骑行",
  };
  return map[mode] ?? mode;
}

/** 出行方式 → FontAwesome 图标（不含 fa-solid 前缀）。 */
export const COMMUTE_MODE_ICON: Record<string, string> = {
  walking: "fa-person-walking",
  transit: "fa-bus",
  taxi: "fa-car",
  driving: "fa-car-side",
  cycling: "fa-bicycle",
};

/** 出行方式对应图标，未知 mode 落到驾车图标。 */
export function commuteModeIcon(mode: string): string {
  return COMMUTE_MODE_ICON[mode] ?? "fa-car-side";
}

/**
 * 过滤景点 brief 里的生成期占位/指令残留文案，避免脏文案露给用户。
 * 例："写成咖啡/茶歇休息点"、"作为次要活动简洁说明"、"…但不要补充无来源事实"。
 * 命中占位返回空串（调用方据此隐藏）；正常文案原样返回。
 * 同时清除内部排序编号前缀，如"推荐路线第八站，"、"第一天行程第十一站"。
 */
const BRIEF_PLACEHOLDER_RE = /(写成|作为.{0,8}(说明|节点|停留点|展开)|不要补充|无来源事实|简洁说明)/;
const BRIEF_RANK_PREFIX_RE = /^(?:推荐路线)?(?:第[一二三四五六七八九十百零\d]+[天日](?:行程)?)?第[一二三四五六七八九十百零\d]+站[，,、]?\s*/;

export function cleanBrief(brief: string | null | undefined): string {
  if (!brief) return "";
  const t = brief.trim();
  if (BRIEF_PLACEHOLDER_RE.test(t)) return "";
  return t.replace(BRIEF_RANK_PREFIX_RE, "");
}

const TAG_BLACKLIST = new Set([
  "relaxed", "moderate", "intensive", "packed",
  "restaurant", "attraction", "museum", "park",
  "business_area", "hotel", "cafe", "shopping",
  "scenic_spot", "entertainment", "landmark",
]);

export function cleanTags(tags: string[]): string[] {
  return tags.filter((t) => !TAG_BLACKLIST.has(t.toLowerCase()));
}

const SUMMARY_TAIL_RE = /[，,]\s*适合用于对比方案.*$/;
const SUMMARY_DIGIT_BLOB_RE = /[、,，]\s*\d{4,}\s*/g;

export function cleanSummary(summary: string | null | undefined): string {
  if (!summary) return "";
  return summary.trim().replace(SUMMARY_DIGIT_BLOB_RE, "、").replace(SUMMARY_TAIL_RE, "");
}
