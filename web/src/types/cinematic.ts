import type { TripFormData, RequestedCommuteMode } from "@/types/form";

export type CinematicStep =
  | "dates"
  | "companions"
  | "preferences"
  | "commute"
  | "review";

export type ReviewLayer = "poi-picker" | "accommodation" | "notes" | null;

export type CinematicRhythm = "轻松" | "适中" | "紧凑";

export const CINEMATIC_RHYTHM_OPTIONS: Array<{
  value: CinematicRhythm;
  label: string;
  desc: string;
}> = [
  { value: "轻松", label: "轻松悠闲", desc: "慢节奏，每天少而精" },
  { value: "适中", label: "适中充实", desc: "兼顾体验与休息，经典节奏" },
  { value: "紧凑", label: "特种兵打卡", desc: "高密度打卡，充实行程" },
];

export const CINEMATIC_INTEREST_OPTIONS = [
  "自然风光",
  "文化历史",
  "美食",
  "亲子",
  "购物",
  "citywalk",
  "拍照",
  "夜景",
] as const;

export type CinematicInterest = (typeof CINEMATIC_INTEREST_OPTIONS)[number];

export type CinematicCompanion = "独自旅行" | "两个人" | "带家人" | "和朋友";

export const CINEMATIC_COMPANION_OPTIONS: Array<{
  label: CinematicCompanion;
  defaultCount: number;
}> = [
  { label: "独自旅行", defaultCount: 1 },
  { label: "两个人", defaultCount: 2 },
  { label: "带家人", defaultCount: 3 },
  { label: "和朋友", defaultCount: 3 },
];

export const CINEMATIC_COMMUTE_OPTIONS: Array<{
  value: RequestedCommuteMode;
  label: string;
  desc: string;
}> = [
  { value: "driving", label: "打车 / 驾车", desc: "舒适便捷，直达目的地" },
  { value: "transit", label: "公共交通", desc: "地铁公交，体验城市肌理" },
  { value: "cycling", label: "骑行优先", desc: "微风穿街，随停随看" },
];

export const DRAFT_STORAGE_KEY = "yuntu-cinematic-draft-v1";
export const DRAFT_SCHEMA_VERSION = 1 as const;

export type CinematicIntent = "edit-pois" | "submit-trip" | `edit-pois:${string}` | `submit-trip:${string}`;

export interface CinematicDraft {
  version: typeof DRAFT_SCHEMA_VERSION;
  step: CinematicStep;
  cityId: string;
  cityName: string;
  form: Partial<TripFormData>;
  selectedPois?: { id: number; name: string }[];
  selectedPoiIds?: number[];
  returnLayer: ReviewLayer;
  ownerUserId?: string | null;
  intent?: CinematicIntent | null;
  updatedAt: number;
}
