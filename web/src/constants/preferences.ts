export const PREFERENCE_OPTIONS = [
  "美食",
  "citywalk",
  "拍照",
  "夜景",
  "文化历史",
  "自然风光",
  "亲子",
  "购物",
] as const;

export const AVOID_OPTIONS = [
  "网红打卡",
  "人太多",
  "太累",
  "爬山",
  "商业街",
] as const;

export const PACE_OPTIONS = [
  { value: "relaxed", label: "轻松" },
  { value: "moderate", label: "适中" },
] as const;

// 与 yuntu-travel 后端已开放城市（City Gate ACTIVE/GRAY）保持一致
export const SUPPORTED_CITIES = [
  "北京",
  "上海",
  "重庆",
  "成都",
  "杭州",
  "西安",
  "南京",
  "长沙",
  "青岛",
  "桂林",
  "广州",
  "武汉",
  "苏州",
  "厦门",
  "昆明",
  "三亚",
] as const;
