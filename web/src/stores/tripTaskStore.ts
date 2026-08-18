import { create } from "zustand";
import { pollJobStatus, ApiRequestError } from "@/services/api";
import { useAuthStore } from "@/stores/authStore";

const LOCAL_STORAGE_KEY = "yuntu_trip_generation_tasks";
const POLL_INTERVAL_MS = 3000;

export type TripTaskStatus = "pending" | "ready" | "failed" | "timeout";
export type TaskNotificationState = "none" | "unread" | "acknowledged";

export interface StoredTripTask {
  accountId: string;
  jobId: string;
  requestId?: string | null;
  startedAt: number;
  finishedAt?: number | null;
  status: TripTaskStatus;
  resultRecordId?: string | number | null;
  destination: string;
  notificationState: TaskNotificationState;
  error?: { code: string; message: string } | null;
}

interface TripTaskStoreState {
  tasks: Record<string, StoredTripTask>;
  activePolling: boolean;
  initStore: () => void;
  clearAllTasks: () => void;
  getTask: (jobId: string) => StoredTripTask | undefined;
  addOrUpdateTask: (task: Partial<StoredTripTask> & { jobId: string }) => void;
  acknowledgeTask: (jobId: string) => void;
  checkAllActiveTasks: () => Promise<void>;
  ensurePollingLoop: () => void;
}

let pollingTimer: ReturnType<typeof setInterval> | null = null;
let initialized = false;
let authSubscribed = false;
let checkInFlight = false;
let currentEpoch = 0;
let lastUserId: string | null = null;

function getCurrentAccountId(): string {
  const user = useAuthStore.getState().user;
  return user?.user_id ? String(user.user_id) : "anonymous";
}

function loadFromLocalStorage(): Record<string, StoredTripTask> {
  try {
    const raw = localStorage.getItem(LOCAL_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (parsed && typeof parsed === "object") {
      const cleaned: Record<string, StoredTripTask> = {};
      const currentAcc = getCurrentAccountId();
      for (const [k, v] of Object.entries(parsed)) {
        if (v && typeof v === "object" && "jobId" in v && v.jobId) {
          const item = v as Record<string, unknown>;
          const accId = String(item.accountId || "anonymous");
          if (accId !== currentAcc) continue;

          let notifState: TaskNotificationState = "none";
          if (
            item.notificationState === "unread" ||
            item.notificationState === "acknowledged" ||
            item.notificationState === "none"
          ) {
            notifState = item.notificationState as TaskNotificationState;
          } else if (item.status === "ready" || item.status === "failed") {
            notifState = "unread";
          }

          cleaned[k] = {
            accountId: accId,
            jobId: String(item.jobId),
            requestId: (item.requestId as string | null) ?? null,
            startedAt: (item.startedAt as number) || Date.now(),
            finishedAt: (item.finishedAt as number | null) ?? null,
            status: (item.status as TripTaskStatus) || "pending",
            resultRecordId: (item.resultRecordId as string | number | null) ?? null,
            destination: (item.destination as string) || "目的地",
            notificationState: notifState,
            error: (item.error as { code: string; message: string } | null) ?? null,
          };
        }
      }
      return cleaned;
    }
    return {};
  } catch {
    try {
      localStorage.removeItem(LOCAL_STORAGE_KEY);
    } catch {
      /* ignore */
    }
    return {};
  }
}

function saveToLocalStorage(tasks: Record<string, StoredTripTask>) {
  try {
    const serializable: Record<string, StoredTripTask> = {};
    for (const [k, v] of Object.entries(tasks)) {
      serializable[k] = {
        accountId: v.accountId,
        jobId: v.jobId,
        requestId: v.requestId ?? null,
        startedAt: v.startedAt,
        finishedAt: v.finishedAt ?? null,
        status: v.status,
        resultRecordId: v.resultRecordId ?? null,
        destination: v.destination,
        notificationState: v.notificationState || "none",
        error: v.error ?? null,
      };
    }
    localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(serializable));
  } catch {
    /* ignore */
  }
}

function setupAuthListener() {
  if (authSubscribed) return;
  authSubscribed = true;

  useAuthStore.subscribe((state) => {
    if (state.status === "anonymous") {
      lastUserId = null;
      useTripTaskStore.getState().clearAllTasks();
    } else if (state.status === "authenticated" && state.user?.user_id) {
      const currentUserId = String(state.user.user_id);
      if (lastUserId !== null && lastUserId !== currentUserId) {
        useTripTaskStore.getState().clearAllTasks();
      }
      lastUserId = currentUserId;
    }
  });
}

export const useTripTaskStore = create<TripTaskStoreState>((set, get) => ({
  tasks: {},
  activePolling: false,

  initStore: () => {
    setupAuthListener();

    if (initialized) return;
    initialized = true;

    const loaded = loadFromLocalStorage();
    set({ tasks: loaded });

    const hasActive = Object.values(loaded).some((t) => t.status === "pending");
    if (hasActive) {
      void get().checkAllActiveTasks();
      get().ensurePollingLoop();
    }
  },

  clearAllTasks: () => {
    currentEpoch++;
    if (pollingTimer) {
      clearInterval(pollingTimer);
      pollingTimer = null;
    }
    try {
      localStorage.removeItem(LOCAL_STORAGE_KEY);
    } catch {
      /* ignore */
    }
    set({ tasks: {}, activePolling: false });
  },

  getTask: (jobId: string) => {
    return get().tasks[jobId];
  },

  addOrUpdateTask: (item) => {
    set((s) => {
      const existing = s.tasks[item.jobId];
      const accId = item.accountId || existing?.accountId || getCurrentAccountId();
      const updated: StoredTripTask = {
        accountId: accId,
        jobId: item.jobId,
        requestId: item.requestId ?? existing?.requestId ?? null,
        startedAt: item.startedAt ?? existing?.startedAt ?? Date.now(),
        finishedAt: item.finishedAt ?? existing?.finishedAt ?? null,
        status: item.status ?? existing?.status ?? "pending",
        resultRecordId: item.resultRecordId ?? existing?.resultRecordId ?? null,
        destination: item.destination || existing?.destination || "目的地",
        notificationState: item.notificationState ?? existing?.notificationState ?? "none",
        error: item.error ?? existing?.error ?? null,
      };
      const next = { ...s.tasks, [item.jobId]: updated };
      saveToLocalStorage(next);
      return { tasks: next };
    });
    get().ensurePollingLoop();
  },

  acknowledgeTask: (jobId: string) => {
    set((s) => {
      const task = s.tasks[jobId];
      if (!task || task.notificationState === "acknowledged") return s;
      const updated: StoredTripTask = {
        ...task,
        notificationState: "acknowledged",
      };
      const next = { ...s.tasks, [jobId]: updated };
      saveToLocalStorage(next);
      return { tasks: next };
    });
  },

  ensurePollingLoop: () => {
    const state = get();
    const hasActive = Object.values(state.tasks).some((t) => t.status === "pending");
    const isHidden = typeof document !== "undefined" ? document.hidden : false;

    if (hasActive && !pollingTimer && !isHidden) {
      pollingTimer = setInterval(() => {
        void get().checkAllActiveTasks();
      }, POLL_INTERVAL_MS);
      set({ activePolling: true });
    } else if (!hasActive && pollingTimer) {
      clearInterval(pollingTimer);
      pollingTimer = null;
      set({ activePolling: false });
    }
  },

  checkAllActiveTasks: async () => {
    if (checkInFlight) return;
    checkInFlight = true;
    const requestEpoch = currentEpoch;

    try {
      const state = get();
      const activeKeys = Object.keys(state.tasks).filter(
        (k) => state.tasks[k]?.status === "pending",
      );

      if (activeKeys.length === 0) {
        if (currentEpoch === requestEpoch) get().ensurePollingLoop();
        return;
      }

      for (const jobId of activeKeys) {
        if (currentEpoch !== requestEpoch) break;
        const task = get().tasks[jobId];
        if (!task) continue;

        try {
          const res = await pollJobStatus(jobId);
          if (currentEpoch !== requestEpoch) break;

          if (res.status === "COMPLETED" && res.result_record_id) {
            set((s) => {
              if (currentEpoch !== requestEpoch) return s;
              const cur = s.tasks[jobId];
              if (!cur || cur.status === "ready") return s;

              const updated: StoredTripTask = {
                ...cur,
                status: "ready",
                resultRecordId: res.result_record_id,
                finishedAt: cur.finishedAt || Date.now(),
                notificationState:
                  cur.notificationState === "none" ? "unread" : cur.notificationState,
              };
              const next = { ...s.tasks, [jobId]: updated };
              saveToLocalStorage(next);
              return { tasks: next };
            });
          } else if (res.status === "FAILED") {
            set((s) => {
              if (currentEpoch !== requestEpoch) return s;
              const cur = s.tasks[jobId];
              if (!cur || cur.status === "failed") return s;

              const updated: StoredTripTask = {
                ...cur,
                status: "failed",
                finishedAt: cur.finishedAt || Date.now(),
                error: { code: "GENERATION_FAILED", message: "生成失败，请重试" },
                notificationState:
                  cur.notificationState === "none" ? "unread" : cur.notificationState,
              };
              const next = { ...s.tasks, [jobId]: updated };
              saveToLocalStorage(next);
              return { tasks: next };
            });
          }
        } catch (err) {
          if (
            err instanceof ApiRequestError &&
            (err.status === 401 || err.code === "AUTH_REQUIRED")
          ) {
            break;
          }
        }
      }
    } finally {
      checkInFlight = false;
      if (currentEpoch === requestEpoch) {
        get().ensurePollingLoop();
      }
    }
  },
}));
