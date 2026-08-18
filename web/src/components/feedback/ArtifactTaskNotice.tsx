import { useNavigate } from "react-router-dom";
import { useShareImageTaskStore, StoredTask } from "@/stores/shareImageTaskStore";

export function ArtifactTaskNotice() {
  const navigate = useNavigate();
  const tasks = useShareImageTaskStore((s) => s.tasks);
  const acknowledgeTask = useShareImageTaskStore((s) => s.acknowledgeTask);

  // 筛选出待提示的持久通知 (notificationState === "unread")
  const unreadTasks = Object.values(tasks).filter(
    (t): t is StoredTask =>
      t.notificationState === "unread" &&
      (t.status === "preview_ready" || t.status === "ready" || t.status === "failed"),
  );

  if (unreadTasks.length === 0) return null;

  // 优先展示最新完成/失败的任务
  const activeTask = unreadTasks.sort((a, b) => (b.finishedAt || b.startedAt) - (a.finishedAt || a.startedAt))[0];
  const isReady = activeTask.status === "preview_ready" || activeTask.status === "ready";

  const handleClose = () => {
    acknowledgeTask(activeTask.recordId);
  };

  const handleAction = () => {
    acknowledgeTask(activeTask.recordId);
    if (!activeTask.jobId) {
      navigate("/history");
      return;
    }
    const encodedJobId = encodeURIComponent(activeTask.jobId);
    if (isReady) {
      navigate(`/result/${activeTask.recordId}?job_id=${encodedJobId}&share=1`);
    } else {
      navigate(`/result/${activeTask.recordId}?job_id=${encodedJobId}`);
    }
  };

  return (
    <aside
      aria-live="polite"
      aria-atomic="true"
      className="fixed bottom-4 left-4 right-4 z-[100] sm:bottom-6 sm:left-auto sm:right-6 sm:w-96 animate-slide-up"
    >
      <div
        role={isReady ? "status" : "alert"}
        className="relative overflow-hidden rounded-2xl border border-primary-100/80 bg-white/95 p-5 shadow-2xl backdrop-blur-md ring-1 ring-black/5"
      >
        {/* 顶部装饰浅条 */}
        <div
          className={`absolute top-0 left-0 right-0 h-1 ${
            isReady ? "bg-gradient-to-r from-primary-500 to-emerald-500" : "bg-gradient-to-r from-amber-500 to-red-500"
          }`}
        />

        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3.5">
            <div
              className={`mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl font-bold shadow-xs ${
                isReady
                  ? "bg-primary-50 text-primary-600 ring-1 ring-primary-200/50"
                  : "bg-red-50 text-red-600 ring-1 ring-red-200/50"
              }`}
            >
              <i
                className={`fa-solid ${isReady ? "fa-sparkles" : "fa-circle-exclamation"} text-lg`}
                aria-hidden="true"
              />
            </div>

            <div className="min-w-0">
              <h3 className="font-display text-base font-bold text-gray-900 tracking-tight">
                {isReady ? "AI 长图已生成" : "AI 长图生成失败"}
              </h3>
              <p className="mt-1 text-xs leading-relaxed font-medium text-gray-600">
                {isReady ? "你的旅行长图已经准备好了" : "可以回到行程详情后重新生成"}
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={handleClose}
            aria-label="关闭"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-50 text-gray-400 transition-colors hover:bg-gray-200 hover:text-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
          >
            <i className="fa-solid fa-xmark text-sm" aria-hidden="true" />
          </button>
        </div>

        {/* 底部按钮栏 */}
        <div className="mt-4 flex items-center justify-end gap-2.5 border-t border-gray-100 pt-3.5">
          <button
            type="button"
            onClick={handleClose}
            className="rounded-full px-4 py-1.5 text-xs font-bold text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
          >
            关闭
          </button>

          <button
            type="button"
            onClick={handleAction}
            className={`flex items-center gap-1.5 rounded-full px-5 py-1.5 text-xs font-bold text-white shadow-sm transition-all hover:scale-105 focus-visible:outline-none focus-visible:ring-2 ${
              isReady
                ? "bg-primary-600 hover:bg-primary-700 focus-visible:ring-primary-400"
                : "bg-gray-800 hover:bg-gray-900 focus-visible:ring-gray-400"
            }`}
          >
            {isReady ? (
              <>
                <span>查看长图</span>
                <i className="fa-solid fa-arrow-right text-[10px]" aria-hidden="true" />
              </>
            ) : (
              <span>查看行程</span>
            )}
          </button>
        </div>
      </div>
    </aside>
  );
}
