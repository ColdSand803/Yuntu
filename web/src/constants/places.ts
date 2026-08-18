/** 地点 role / category 的展示适配 —— 兼容后端真实取值与 mock 取值 */

/** 是否为「主锚点」类地点（决定时间轴圆点是否高亮主色） */
const ANCHOR_ROLES = new Set([
  "anchor",
  "anchor_activity",
  "secondary_activity",
]);

export function isAnchorRole(role: string): boolean {
  return ANCHOR_ROLES.has(role);
}

/** category → emoji 图标，覆盖后端真实值与 mock 值 */
const CATEGORY_ICON: Record<string, string> = {
  // 后端真实 category
  park: "🌳",
  photo_spot: "📷",
  attraction: "🎡",
  business_area: "🏙️",
  restaurant: "🍜",
  other: "📍",
  // mock / 旧值
  landmark: "🏛️",
  food: "🍜",
  scenic: "🌿",
  culture: "🎭",
  shopping: "🛍️",
  nightlife: "🌃",
};

export function categoryIcon(category: string): string {
  return CATEGORY_ICON[category] ?? "📍";
}

const CATEGORY_NAME: Record<string, string> = {
  park: "公园景点",
  photo_spot: "打卡胜地",
  attraction: "热门景点",
  business_area: "商圈街区",
  restaurant: "特色美食",
  other: "游览地点",
  landmark: "地标建筑",
  food: "特色美食",
  scenic: "自然风光",
  culture: "人文历史",
  shopping: "休闲购物",
  nightlife: "夜生活",
};

export function categoryName(category: string): string {
  return CATEGORY_NAME[category] ?? "游览地点";
}
