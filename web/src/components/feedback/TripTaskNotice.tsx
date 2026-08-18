import { useNavigate } from "react-router-dom";
import { useTripTaskStore, StoredTripTask } from "@/stores/tripTaskStore";

export function TripTaskNotice() {
  const navigate = useNavigate();
  const tasks = useTripTaskStore((s) => s.tasks);
  const acknowledgeTask = useTripTaskStore((s) => s.acknowledgeTask);

  // 筛选待展示通知的持久任务 (notificationState === "unread")
  const unreadTasks = Object.values(tasks).filter(
    (t): t is StoredTripTask =>
      t.notificationState === "unread" &&
      (t.status === "ready" || t.status === "failed" || t.status === "timeout"),
  );

  if (unreadTasks.length === 0) return null;

  // 优先展示最新完成/失败的攻略任务
  const activeTask = unreadTasks.sort(
    (a, b) => (b.finishedAt || b.startedAt) - (a.finishedAt || a.startedAt),
  )[0];

  const isReady = activeTask.status === "ready";

  const handleClose = () => {
    acknowledgeTask(activeTask.jobId);
  };

  const handleAction = () => {
    acknowledgeTask(activeTask.jobId);
    if (isReady && activeTask.resultRecordId) {
      navigate(`/result/${activeTask.resultRecordId}?job_id=${activeTask.jobId}`);
    } else {
      navigate("/");
    }
  };

  return (
    <aside
      aria-live="polite"
      aria-atomic="true"
      className="fixed bottom-4 left-4 right-4 z-[100] sm:bottom-24 sm:left-auto sm:right-6 sm:w-96 animate-slide-up"
    >
      <div
        role={isReady ? "status" : "alert"}
        className="relative overflow-hidden rounded-2xl border border-emerald-100/80 bg-white/95 p-5 shadow-2xl backdrop-blur-md ring-1 ring-black/5"
      >
        {/* 顶部装饰条 */}
        <div
          className={`absolute top-0 left-0 right-0 h-1 ${
            isReady
              ? "bg-gradient-to-r from-emerald-500 to-teal-500"
              : "bg-gradient-to-r from-amber-500 to-red-500"
          }`}
        />

        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3.5">
            <div
              className={`mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl font-bold shadow-xs ${
                isReady
                  ? "bg-emerald-50 text-emerald-600 ring-1 ring-emerald-200/50"
                  : "bg-red-50 text-red-600 ring-1 ring-red-200/50"
              }`}
            >
              <i
                className={`fa-solid ${isReady ? "fa-map-location-dot" : "fa-circle-exclamation"} text-lg`}
                aria-hidden="true"
              />
            </div>

            <div className="min-w-0">
              <h3 className="font-display text-base font-bold text-gray-900 tracking-tight">
                {isReady ? "旅行攻略已生成" : "旅行攻略生成失败"}
              </h3>
              <p className="mt-1 text-xs leading-relaxed font-medium text-gray-600">
                {isReady
                  ? `为你准备好了 ${activeTask.destination || "目的地"} 的行程攻略`
                  : `${activeTask.destination || "目的地"} 行程生成未完成，可点击重新规划`}
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={handleClose}
            aria-label="关闭"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-50 text-gray-400 transition-colors hover:bg-gray-200 hover:text-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300"
          >
            <i className="fa-solid fa-xmark text-sm" aria-hidden="true" />
          </button>
        </div>

        {/* 底部按钮栏 */}
        <div className="mt-4 flex items-center justify-end gap-2.5 border-t border-gray-100 pt-3.5">
          <button
            type="button"
            onClick={handleClose}
            className="rounded-full px-4 py-1.5 text-xs font-bold text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300"
          >
            关闭
          </button>

          <button
            type="button"
            onClick={handleAction}
            className={`flex items-center gap-1.5 rounded-full px-5 py-1.5 text-xs font-bold text-white shadow-sm transition-all hover:scale-105 focus-visible:outline-none focus-visible:ring-2 ${
              isReady
                ? "bg-emerald-600 hover:bg-emerald-700 focus-visible:ring-emerald-400"
                : "bg-gray-800 hover:bg-gray-900 focus-visible:ring-gray-400"
            }`}
          >
            {isReady ? (
              <>
                <span>查看攻略</span>
                <i className="fa-solid fa-arrow-right text-[10px]" aria-hidden="true" />
              </>
            ) : (
              <span>重新规划</span>
            )}
          </button>
        </div>
      </div>
    </aside>
  );
}
