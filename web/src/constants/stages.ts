import type { StageCode } from "@/types/trip";

interface StageInfo {
  step: number;
  label: string;
}

export const STAGE_MAP: Record<StageCode, StageInfo> = {
  ANALYZING: { step: 1, label: "正在理解旅行需求" },
  PLANNING: { step: 2, label: "正在筛选地点并规划路线" },
  COMPOSING: { step: 3, label: "正在生成旅行方案" },
  FINALIZING: { step: 4, label: "正在校验并整理方案" },
};

export const TOTAL_STAGES = 4;

/**
 * 后端原始阶段名（current_stage）→ 前端 4 步进度码。
 * 后端流水线阶段比前端展示粒度更细，这里做归并。
 */
const BACKEND_STAGE_TO_CODE: Record<string, StageCode> = {
  PENDING: "ANALYZING",
  INTENT_PARSER: "ANALYZING",
  DATA_RETRIEVAL: "PLANNING",
  ROUTE_PLANNING: "PLANNING",
  FINAL_WRITER: "COMPOSING",
  HERMES_REVIEW: "COMPOSING",
  PUBLISH_RETRY: "COMPOSING",
  PERSISTING: "FINALIZING",
  SUCCESS: "FINALIZING",
};

export function mapBackendStage(rawStage: string | null | undefined): StageCode {
  if (!rawStage) return "ANALYZING";
  return BACKEND_STAGE_TO_CODE[rawStage] ?? "ANALYZING";
}
