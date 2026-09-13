import type { DestinationsResponse } from "@/types/destination";
import { ApiRequestError } from "@/services/errors";
import { parseDestinationsResponse } from '@/utils/destinationResponse';

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

/**
 * 获取目的地列表（公开接口，无需认证）
 * GET /api/destinations
 */
export async function fetchDestinations(): Promise<DestinationsResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/destinations`, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    throw new ApiRequestError(
      "NETWORK_ERROR",
      "网络连接失败，请检查网络",
      0,
    );
  }

  let data: unknown;
  try {
    data = await res.json();
  } catch {
    throw new ApiRequestError("BAD_RESPONSE", "服务返回异常", res.status);
  }

  if (!res.ok) {
    const detail = (data as { detail?: unknown }).detail;
    if (detail && typeof detail === "object") {
      const d = detail as { code?: string; message?: string };
      throw new ApiRequestError(
        d.code ?? "HTTP_ERROR",
        d.message ?? "请求失败",
        res.status,
      );
    }
    const msg = typeof detail === "string" ? detail : "获取目的地列表失败";
    throw new ApiRequestError("HTTP_ERROR", msg, res.status);
  }

  return parseDestinationsResponse(data);
}
