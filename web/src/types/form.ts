/**
 * 创建行程请求的出行方式（POST /trip/async）。
 * walking 已从合法值移除（传入返回 422）。
 * 结果接口仍可能返回 walking（历史兼容），请用 ResultCommuteMode。
 */
export type RequestedCommuteMode = "driving" | "transit" | "cycling";

/** 后端 MustIncludeItem 模型（yuntu-travel src/agents/schema.py）。
 * place_id 可选但会被优先消费（查库校验城市/trusted），仅勾选热门 POI 时携带；手输只传 name */
export interface MustIncludeItem {
  name: string;
  place_id?: number;
}

export interface AccommodationInput {
  name: string;
  place_id?: number;
  latitude?: number;
  longitude?: number;
}

export interface TripFormData {
  /** 出发城市（选填）。后端 TripRequest.from_city 默认空串，仅拼入 user_query 供规划参考 */
  from_city?: string;
  to_city: string;
  start_date: string;
  end_date: string;
  days: number;
  people_count: number;
  preferences: string[];
  avoid: string[];
  notes: string;
  /** 人均预算上限（元），旧版本表单控件（已废弃/可选） */
  budget?: number;
  /** v0.8.9 更多偏好（选填，不传走后端默认） */
  must_include?: MustIncludeItem[];
  /** v0.8.10 市内出行方式（walking 已从合法选项移除） */
  commute_mode?: RequestedCommuteMode;
  daily_start?: string; // "HH:mm"，排程软约束
  daily_end?: string; // "HH:mm"，排程软约束
  /** 住宿点（选填） */
  accommodation?: AccommodationInput;
}

export const DEFAULT_FORM: TripFormData = {
  to_city: "",
  start_date: "",
  end_date: "",
  days: 3,
  people_count: 1,
  preferences: [],
  avoid: [],
  notes: "",
};
