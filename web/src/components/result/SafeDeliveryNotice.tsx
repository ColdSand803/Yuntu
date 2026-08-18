import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { getHistoryTrips, submitTrip, ApiRequestError } from "@/services/api";
import { useAuthStore } from "@/stores/authStore";
import { useTripStore } from "@/stores/tripStore";
import { useTripTaskStore } from "@/stores/tripTaskStore";
import type { TripFormData } from "@/types/form";
import type { TripResult } from "@/types/trip";
import {
  clearPendingSubmission,
  savePendingSubmission,
} from "@/utils/pendingSubmission";

const NOTICE_TEXT = "已生成基础行程，部分详细介绍暂未展开。";

function shouldShowSafeDeliveryNotice(
  result: Pick<TripResult, "published_variant" | "delivery_status">,
): boolean {
  return (
    result.published_variant === "safe" && result.delivery_status === "DEGRADED"
  );
}

async function findRetryInput(jobId: string): Promise<TripFormData | null> {
  let cursor: string | undefined;

  do {
    const response = await getHistoryTrips({ cursor, limit: 50 });
    const matched = response.items.find((item) => item.job_id === jobId);
    if (matched?.retry_input?.trip_request)
      return matched.retry_input.trip_request;
    cursor = response.next_cursor ?? undefined;
  } while (cursor);

  return null;
}

interface SafeDeliveryNoticeProps {
  result: Pick<TripResult, "published_variant" | "delivery_status">;
  jobId?: string | null;
}

export function SafeDeliveryNotice({ result, jobId }: SafeDeliveryNoticeProps) {
  const navigate = useNavigate();
  const setFormData = useTripStore((state) => state.setFormData);
  const clearResult = useTripStore((state) => state.clearResult);
  const refreshMe = useAuthStore((state) => state.refreshMe);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!shouldShowSafeDeliveryNotice(result)) return null;

  const regenerate = async () => {
    if (!jobId || submitting) return;
    setSubmitting(true);
    setError(null);

    try {
      const requestData = await findRetryInput(jobId);
      if (!requestData) {
        setError("暂时无法读取原行程条件，请从“我的行程”重试。");
        return;
      }

      setFormData(requestData);
      clearResult();
      const pending = savePendingSubmission(requestData);

      try {
        const response = await submitTrip(requestData, pending.request_id);
        useTripTaskStore.getState().addOrUpdateTask({
          jobId: response.job_id,
          requestId: pending.request_id,
          destination: requestData.to_city || "目的地",
          startedAt: Date.now(),
          status: "pending",
          notificationState: "none",
        });
        clearPendingSubmission();
        await refreshMe();
        navigate(`/planning/${response.job_id}`);
      } catch (submissionError: unknown) {
        if (submissionError instanceof ApiRequestError) {
          if (
            submissionError.status === 409 &&
            submissionError.code === "ACTIVE_TRIP_EXISTS"
          ) {
            const refreshed = await refreshMe();
            const activeTrip = refreshed
              ? useAuthStore.getState().activeTrip
              : null;
            if (activeTrip?.job_id) {
              clearPendingSubmission();
              navigate(`/planning/${activeTrip.job_id}`);
              return;
            }
          }

          if (
            submissionError.status === 400 ||
            submissionError.status === 422 ||
            submissionError.status === 429 ||
            [
              "REQUEST_ID_CONFLICT",
              "CITY_NOT_SUPPORTED",
              "VALIDATION_ERROR",
              "QUOTA_EXHAUSTED",
            ].includes(submissionError.code)
          ) {
            clearPendingSubmission();
          }
          setError(submissionError.message);
        } else {
          setError("发起重新生成失败，请检查网络设置。");
        }
      }
    } catch (historyError: unknown) {
      setError(
        historyError instanceof ApiRequestError
          ? historyError.message
          : "暂时无法读取原行程条件，请稍后重试。",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section
      aria-label="行程说明"
      className="rounded-2xl border border-amber-200/80 bg-amber-50/90 px-5 py-4 shadow-sm"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm font-medium leading-6 text-amber-950">
          {NOTICE_TEXT}
        </p>
        <button
          type="button"
          disabled={!jobId || submitting}
          onClick={() => void regenerate()}
          className="shrink-0 rounded-full border border-amber-300 bg-white px-4 py-2 text-sm font-bold text-amber-900 transition-colors hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? "正在重新生成…" : "重新生成详细版"}
        </button>
      </div>
      {!jobId && (
        <p className="mt-2 text-xs text-amber-800">
          当前链接缺少任务信息，无法直接重新生成。
        </p>
      )}
      {error && (
        <p role="alert" className="mt-2 text-xs text-red-700">
          {error}
        </p>
      )}
    </section>
  );
}
