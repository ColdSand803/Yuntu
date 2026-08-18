import { create } from "zustand";
import { getArtifact, createArtifact, fetchArtifactBlob, ApiRequestError } from "@/services/api";

const LOCAL_STORAGE_KEY = "yuntu_share_image_tasks";
const MAX_OBSERVATION_MS = 8 * 60 * 1000; // 8 分钟客户端观察超时 (对应 yuntu-travel 420s 超时)
const POLL_INTERVAL_MS = 5000; // 5 秒轮询

export type ShareImageTaskStatus =
  | "checking"
  | "creating"
  | "polling"
  | "backend_ready"
  | "preview_loading"
  | "preview_ready"
  | "ready"
  | "failed"
  | "timeout";

export type TaskNotificationState = "none" | "unread" | "acknowledged";

export interface StoredTask {
  recordId: string;
  jobId?: string | null;
  artifactType: "share_image";
  status: ShareImageTaskStatus;
  startedAt: number;
  finishedAt?: number | null;
  notificationState: TaskNotificationState;
  downloadUrl?: string | null;
  filename?: string | null;
  error?: { code: string; message: string } | null;
}

export interface ImagePreview {
  blob: Blob;
  objectUrl: string;
  decoded: boolean;
}

// 运行时内存预览缓存（绝不序列化进 localStorage）
const previewRuntimeCache = new Map<string, ImagePreview>();
const previewInFlightMap = new Map<string, Promise<ImagePreview>>();
const previewAbortControllers = new Map<string, AbortController>();

export function getRuntimePreview(recordId: string): ImagePreview | undefined {
  return previewRuntimeCache.get(recordId);
}

export function cleanupRuntimePreviews() {
  for (const controller of previewAbortControllers.values()) {
    try {
      controller.abort();
    } catch {
      /* ignore */
    }
  }
  previewAbortControllers.clear();
  previewInFlightMap.clear();

  for (const preview of previewRuntimeCache.values()) {
    try {
      URL.revokeObjectURL(preview.objectUrl);
    } catch {
      /* ignore */
    }
  }
  previewRuntimeCache.clear();
}

async function decodeImageBlob(blob: Blob): Promise<string> {
  const objectUrl = URL.createObjectURL(blob);
  if (typeof Image !== "undefined") {
    const img = new Image();
    img.src = objectUrl;
    if ("decode" in img && typeof img.decode === "function") {
      try {
        await img.decode();
      } catch {
        /* ignore decode error in test environments */
      }
    }
  }
  return objectUrl;
}

export async function loadPreviewBlob(
  recordId: string,
  downloadUrl: string,
  requestEpoch: number,
): Promise<ImagePreview> {
  if (previewRuntimeCache.has(recordId)) {
    return previewRuntimeCache.get(recordId)!;
  }
  if (previewInFlightMap.has(recordId)) {
    return previewInFlightMap.get(recordId)!;
  }

  const controller = new AbortController();
  previewAbortControllers.set(recordId, controller);

  const promise = (async (): Promise<ImagePreview> => {
    try {
      const blob = await fetchArtifactBlob(downloadUrl, {
        signal: controller.signal,
      });
      if (currentEpoch !== requestEpoch) {
        throw new Error("EPOCH_EXPIRED");
      }
      const objectUrl = await decodeImageBlob(blob);
      if (currentEpoch !== requestEpoch) {
        try {
          URL.revokeObjectURL(objectUrl);
        } catch {
          /* ignore */
        }
        throw new Error("EPOCH_EXPIRED");
      }
      const preview: ImagePreview = { blob, objectUrl, decoded: true };
      previewRuntimeCache.set(recordId, preview);
      return preview;
    } finally {
      previewInFlightMap.delete(recordId);
      previewAbortControllers.delete(recordId);
    }
  })();

  previewInFlightMap.set(recordId, promise);
  return promise;
}

interface ShareImageTaskStoreState {
  tasks: Record<string, StoredTask>;
  activePolling: boolean;
  initStore: () => void;
  clearAllTasks: () => void;
  getTask: (recordId: string) => StoredTask | undefined;
  getPreview: (recordId: string) => ImagePreview | undefined;
  retryPreviewDownload: (recordId: string) => Promise<ImagePreview | undefined>;
  acknowledgeTask: (recordId: string) => void;
  startOrFetchTask: (
    recordId: string,
    options?: { isUserRetry?: boolean; jobId?: string },
  ) => Promise<StoredTask>;
  retryTask: (recordId: string, jobId?: string) => Promise<StoredTask>;
  recheckTask: (recordId: string) => Promise<StoredTask>;
  checkAllActiveTasks: () => Promise<void>;
  ensurePollingLoop: () => void;
}

let pollingTimer: ReturnType<typeof setInterval> | null = null;
let initialized = false;
let checkInFlight = false; // 轮询防重入全局锁
let currentEpoch = 0; // 全局 Store 生命周期 Epoch

// 并发请求防重入 in-flight Promise Map
const inFlightMap = new Map<string, Promise<StoredTask>>();

function loadFromLocalStorage(): Record<string, StoredTask> {
  try {
    const raw = localStorage.getItem(LOCAL_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (parsed && typeof parsed === "object") {
      const cleaned: Record<string, StoredTask> = {};
      for (const [k, v] of Object.entries(parsed)) {
        if (v && typeof v === "object" && "recordId" in v && v.recordId) {
          const item = v as Record<string, unknown>;
          let notifState: TaskNotificationState = "none";
          if (
            item.notificationState === "unread" ||
            item.notificationState === "acknowledged" ||
            item.notificationState === "none"
          ) {
            notifState = item.notificationState as TaskNotificationState;
          } else if (item.notified === true) {
            notifState = "acknowledged";
          } else if (
            item.status === "preview_ready" ||
            item.status === "ready" ||
            item.status === "failed"
          ) {
            notifState = "unread";
          } else {
            notifState = "none";
          }

          cleaned[k] = {
            recordId: String(item.recordId),
            jobId: (item.jobId as string | null) ?? null,
            artifactType: "share_image",
            status: (item.status as ShareImageTaskStatus) || "polling",
            startedAt: (item.startedAt as number) || Date.now(),
            finishedAt: (item.finishedAt as number | null) ?? null,
            notificationState: notifState,
            downloadUrl: (item.downloadUrl as string | null) ?? null,
            filename: (item.filename as string | null) ?? null,
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

function saveToLocalStorage(tasks: Record<string, StoredTask>) {
  try {
    const serializable: Record<string, StoredTask> = {};
    for (const [k, v] of Object.entries(tasks)) {
      serializable[k] = {
        recordId: String(v.recordId),
        jobId: v.jobId ?? null,
        artifactType: "share_image",
        status: v.status,
        startedAt: v.startedAt,
        finishedAt: v.finishedAt ?? null,
        notificationState: v.notificationState || "none",
        downloadUrl: v.downloadUrl ?? null,
        filename: v.filename ?? null,
        error: v.error ?? null,
      };
    }
    localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(serializable));
  } catch {
    // 忽略 localStorage 写入异常
  }
}



async function processBackendReadyTask(
  recordId: string,
  downloadUrl: string,
  filename: string | undefined,
  requestEpoch: number,
  initialStartedAt?: number,
): Promise<StoredTask> {
  // 1. 设置状态为 preview_loading
  useShareImageTaskStore.setState((s) => {
    if (currentEpoch !== requestEpoch) return s;
    const cur = s.tasks[recordId];
    const updated: StoredTask = {
      ...cur,
      recordId,
      artifactType: "share_image",
      status: "preview_loading",
      startedAt: cur?.startedAt || initialStartedAt || Date.now(),
      downloadUrl,
      filename: filename || cur?.filename,
      notificationState: cur?.notificationState || "none",
    };
    const next = { ...s.tasks, [recordId]: updated };
    saveToLocalStorage(next);
    return { tasks: next };
  });

  try {
    await loadPreviewBlob(recordId, downloadUrl, requestEpoch);
    if (currentEpoch !== requestEpoch) {
      return (
        useShareImageTaskStore.getState().tasks[recordId] || {
          recordId,
          artifactType: "share_image",
          status: "preview_loading",
          startedAt: Date.now(),
          notificationState: "none",
        }
      );
    }

    let finalTask: StoredTask = {
      recordId,
      artifactType: "share_image",
      status: "preview_ready",
      startedAt: Date.now(),
      finishedAt: Date.now(),
      downloadUrl,
      filename: filename || null,
      notificationState: "unread",
    };

    useShareImageTaskStore.setState((s) => {
      if (currentEpoch !== requestEpoch) return s;
      const cur = s.tasks[recordId];
      const targetNotifState: TaskNotificationState =
        cur?.notificationState === "none" ? "unread" : cur?.notificationState || "unread";

      finalTask = {
        ...cur,
        recordId,
        artifactType: "share_image",
        status: "preview_ready",
        finishedAt: cur?.finishedAt || Date.now(),
        downloadUrl,
        filename: filename || cur?.filename,
        notificationState: targetNotifState,
      };
      const next = { ...s.tasks, [recordId]: finalTask };
      saveToLocalStorage(next);
      return { tasks: next };
    });

    return finalTask;
  } catch {
    if (currentEpoch !== requestEpoch) {
      return (
        useShareImageTaskStore.getState().tasks[recordId] || {
          recordId,
          artifactType: "share_image",
          status: "failed",
          startedAt: Date.now(),
          notificationState: "none",
        }
      );
    }

    let failedTask: StoredTask = {
      recordId,
      artifactType: "share_image",
      status: "failed",
      startedAt: Date.now(),
      finishedAt: Date.now(),
      downloadUrl,
      filename: filename || null,
      error: { code: "PREVIEW_FAILED", message: "预览图片加载失败，点击重试" },
      notificationState: "none",
    };

    useShareImageTaskStore.setState((s) => {
      if (currentEpoch !== requestEpoch) return s;
      const cur = s.tasks[recordId];
      failedTask = {
        ...cur,
        recordId,
        artifactType: "share_image",
        status: "failed",
        finishedAt: Date.now(),
        downloadUrl,
        filename: filename || cur?.filename,
        error: { code: "PREVIEW_FAILED", message: "预览图片加载失败，点击重试" },
        notificationState: "none",
      };
      const next = { ...s.tasks, [recordId]: failedTask };
      saveToLocalStorage(next);
      return { tasks: next };
    });

    return failedTask;
  }
}

export const useShareImageTaskStore = create<ShareImageTaskStoreState>(
  (set, get) => ({
    tasks: {},
    activePolling: false,

    initStore: () => {
      if (initialized) return;
      initialized = true;

      const loaded = loadFromLocalStorage();
      set({ tasks: loaded });

      // 刷新恢复：后端 ready 的任务自动重新在后台下载并解码一次 Preview
      for (const [recordId, task] of Object.entries(loaded)) {
        if (
          (task.status === "preview_ready" ||
            task.status === "ready" ||
            task.status === "backend_ready" ||
            task.status === "preview_loading") &&
          task.downloadUrl
        ) {
          void processBackendReadyTask(
            recordId,
            task.downloadUrl,
            task.filename || undefined,
            currentEpoch,
            task.startedAt,
          );
        }
      }

      function handleVisibilityChange() {
        if (document.hidden) {
          if (pollingTimer) {
            clearInterval(pollingTimer);
            pollingTimer = null;
          }
          set({ activePolling: false });
        } else {
          void get().checkAllActiveTasks();
          get().ensurePollingLoop();
        }
      }

      if (typeof document !== "undefined") {
        document.addEventListener("visibilitychange", handleVisibilityChange);
      }

      const hasActive = Object.values(loaded).some(
        (t) => t.status === "creating" || t.status === "polling",
      );
      if (hasActive) {
        void get().checkAllActiveTasks();
        get().ensurePollingLoop();
      }
    },

    clearAllTasks: () => {
      currentEpoch++; // 递增 Epoch，使得之前所有在途请求被抛弃
      if (pollingTimer) {
        clearInterval(pollingTimer);
        pollingTimer = null;
      }
      inFlightMap.clear();
      cleanupRuntimePreviews();
      try {
        localStorage.removeItem(LOCAL_STORAGE_KEY);
      } catch {
        // 忽略
      }
      set({ tasks: {}, activePolling: false });
    },

    getTask: (recordId: string) => {
      return get().tasks[recordId];
    },

    getPreview: (recordId: string) => {
      return getRuntimePreview(recordId);
    },

    retryPreviewDownload: async (recordId: string) => {
      const task = get().tasks[recordId];
      if (!task || !task.downloadUrl) return undefined;
      const requestEpoch = currentEpoch;
      try {
        const preview = await loadPreviewBlob(recordId, task.downloadUrl, requestEpoch);
        set((s) => {
          if (currentEpoch !== requestEpoch) return s;
          const cur = s.tasks[recordId];
          if (!cur) return s;
          const updated: StoredTask = {
            ...cur,
            status: "preview_ready",
            finishedAt: cur.finishedAt || Date.now(),
            error: null,
          };
          const next = { ...s.tasks, [recordId]: updated };
          saveToLocalStorage(next);
          return { tasks: next };
        });
        return preview;
      } catch {
        return undefined;
      }
    },

    acknowledgeTask: (recordId: string) => {
      set((s) => {
        const task = s.tasks[recordId];
        if (!task || task.notificationState === "acknowledged") return s;
        const updated: StoredTask = {
          ...task,
          notificationState: "acknowledged",
        };
        const next = { ...s.tasks, [recordId]: updated };
        saveToLocalStorage(next);
        return { tasks: next };
      });
    },

    ensurePollingLoop: () => {
      const state = get();
      const hasActive = Object.values(state.tasks).some(
        (t) => t.status === "creating" || t.status === "polling",
      );

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
        const activeKeys = Object.keys(state.tasks).filter((k) => {
          const t = state.tasks[k];
          return t && (t.status === "creating" || t.status === "polling");
        });

        if (activeKeys.length === 0) {
          if (currentEpoch === requestEpoch) {
            get().ensurePollingLoop();
          }
          return;
        }

        const now = Date.now();

        for (const recordId of activeKeys) {
          if (currentEpoch !== requestEpoch) break; // Epoch 变化，立即中断

          const task = get().tasks[recordId];
          if (!task) continue;
          const taskStartedAt = task.startedAt;

          // 8 分钟观察超时断言
          if (now - taskStartedAt > MAX_OBSERVATION_MS) {
            set((s) => {
              if (currentEpoch !== requestEpoch) return s;
              const cur = s.tasks[recordId];
              if (!cur || cur.startedAt !== taskStartedAt) return s;
              const updated: StoredTask = {
                ...cur,
                status: "timeout",
                finishedAt: Date.now(),
              };
              const next = { ...s.tasks, [recordId]: updated };
              saveToLocalStorage(next);
              return { tasks: next };
            });
            continue;
          }

          // GET 查询后端真实状态
          try {
            const art = await getArtifact(recordId, "share_image");
            if (currentEpoch !== requestEpoch) break;

            if (art.status === "ready" && art.download_url) {
              await processBackendReadyTask(
                recordId,
                art.download_url,
                art.filename,
                requestEpoch,
                taskStartedAt,
              );
            } else if (art.status === "failed") {
              set((s) => {
                if (currentEpoch !== requestEpoch) return s;
                const cur = s.tasks[recordId];
                if (!cur || cur.startedAt !== taskStartedAt) return s;

                const notifState: TaskNotificationState =
                  cur.notificationState === "none"
                    ? "unread"
                    : cur.notificationState;

                const updated: StoredTask = {
                  ...cur,
                  status: "failed",
                  finishedAt: cur.finishedAt || Date.now(),
                  error: art.error ?? {
                    code: "GENERATION_FAILED",
                    message: "生成失败，请重试",
                  },
                  notificationState: notifState,
                };
                const next = { ...s.tasks, [recordId]: updated };
                saveToLocalStorage(next);
                return { tasks: next };
              });
            }
          } catch (err) {
            if (
              err instanceof ApiRequestError &&
              (err.status === 401 || err.code === "AUTH_REQUIRED")
            ) {
              // 401 交给全局认证处理，严禁把任务写回 failed/timeout 或复活 localStorage
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

    startOrFetchTask: async (
      recordId: string,
      options?: { isUserRetry?: boolean; jobId?: string },
    ) => {
      const isUserRetry = !!options?.isUserRetry;
      const requestEpoch = currentEpoch;

      // 1. 并发去重：若已有相同的在途 Request，直接返回该 Promise
      if (inFlightMap.has(recordId)) {
        return inFlightMap.get(recordId)!;
      }

      const existing = get().tasks[recordId];
      const effectiveJobId = options?.jobId || existing?.jobId || null;

      // 普通打开且任务在进行中或已完成 -> 直接复用，绝不 POST
      if (
        !isUserRetry &&
        existing &&
        (existing.status === "creating" ||
          existing.status === "polling" ||
          existing.status === "preview_loading" ||
          existing.status === "preview_ready" ||
          existing.status === "ready")
      ) {
        if (options?.jobId && existing.jobId !== options.jobId) {
          const updated: StoredTask = { ...existing, jobId: options.jobId };
          set((s) => {
            const next = { ...s.tasks, [recordId]: updated };
            saveToLocalStorage(next);
            return { tasks: next };
          });
          return updated;
        }
        return existing;
      }

      // 普通打开且处于 failed 终态 -> 保持 failed 终态展示，绝不自动 POST！
      if (!isUserRetry && existing && existing.status === "failed") {
        if (options?.jobId && existing.jobId !== options.jobId) {
          const updated: StoredTask = { ...existing, jobId: options.jobId };
          set((s) => {
            const next = { ...s.tasks, [recordId]: updated };
            saveToLocalStorage(next);
            return { tasks: next };
          });
          return updated;
        }
        return existing;
      }

      const promise = (async (): Promise<StoredTask> => {
        // 2. 执行 GET-first 判定
        try {
          const art = await getArtifact(recordId, "share_image");
          if (currentEpoch !== requestEpoch) {
            return (
              existing || {
                recordId,
                jobId: effectiveJobId,
                artifactType: "share_image",
                status: "checking",
                startedAt: Date.now(),
                notificationState: "none",
              }
            );
          }

          if (art.status === "ready" && art.download_url) {
            return await processBackendReadyTask(
              recordId,
              art.download_url,
              art.filename,
              requestEpoch,
              existing?.startedAt,
            );
          }
          if (art.status === "pending" || art.status === "running") {
            const updated: StoredTask = {
              recordId,
              jobId: effectiveJobId,
              artifactType: "share_image",
              status: "polling",
              startedAt: existing?.startedAt || Date.now(),
              downloadUrl: art.download_url,
              filename: art.filename,
              notificationState: "none",
            };
            set((s) => {
              if (currentEpoch !== requestEpoch) return s;
              const next = { ...s.tasks, [recordId]: updated };
              saveToLocalStorage(next);
              return { tasks: next };
            });
            if (currentEpoch === requestEpoch) get().ensurePollingLoop();
            return updated;
          }
          if (art.status === "failed") {
            // 如果不是用户显式重试，GET 到 failed 保持 failed，绝不 POST
            if (!isUserRetry) {
              const updated: StoredTask = {
                recordId,
                jobId: effectiveJobId,
                artifactType: "share_image",
                status: "failed",
                startedAt: existing?.startedAt || Date.now(),
                finishedAt: existing?.finishedAt || Date.now(),
                error: art.error ?? {
                  code: "GENERATION_FAILED",
                  message: "生成失败，请重试",
                },
                notificationState: existing?.notificationState || "none",
              };
              set((s) => {
                if (currentEpoch !== requestEpoch) return s;
                const next = { ...s.tasks, [recordId]: updated };
                saveToLocalStorage(next);
                return { tasks: next };
              });
              return updated;
            }
            // 用户显式重试且 GET 到 failed -> 落到后续 POST 流程重新创建
          }
        } catch (err) {
          if (
            err instanceof ApiRequestError &&
            (err.status === 401 || err.code === "AUTH_REQUIRED")
          ) {
            // 401 严禁将状态写回失败或复活 localStorage
            throw err;
          }
          if (err instanceof ApiRequestError && err.status === 404) {
            // 404 说明未创建，无论普通打开还是重试，均落到 POST
          } else {
            // 网络不确定性错 -> 不盲目 POST，设为 failed 提示重试/检查
            const updated: StoredTask = {
              recordId,
              jobId: effectiveJobId,
              artifactType: "share_image",
              status: "failed",
              startedAt: Date.now(),
              finishedAt: Date.now(),
              error:
                err instanceof ApiRequestError
                  ? { code: err.code, message: err.message }
                  : { code: "UNKNOWN", message: "网络连接失败，请检查网络" },
              notificationState: "none",
            };
            set((s) => {
              if (currentEpoch !== requestEpoch) return s;
              const next = { ...s.tasks, [recordId]: updated };
              saveToLocalStorage(next);
              return { tasks: next };
            });
            return updated;
          }
        }

        if (currentEpoch !== requestEpoch) {
          return (
            existing || {
              recordId,
              jobId: effectiveJobId,
              artifactType: "share_image",
              status: "checking",
              startedAt: Date.now(),
              notificationState: "none",
            }
          );
        }

        // 3. 执行 POST create (只有 GET 404，或者用户显式重试且 GET 为 failed 时)
        const creatingTask: StoredTask = {
          recordId,
          jobId: effectiveJobId,
          artifactType: "share_image",
          status: "creating",
          startedAt: Date.now(),
          notificationState: "none",
        };
        set((s) => {
          if (currentEpoch !== requestEpoch) return s;
          const next = { ...s.tasks, [recordId]: creatingTask };
          saveToLocalStorage(next);
          return { tasks: next };
        });

        try {
          const created = await createArtifact(recordId, "share_image");
          if (currentEpoch !== requestEpoch) return creatingTask;

          if (created.status === "ready" && created.download_url) {
            return await processBackendReadyTask(
              recordId,
              created.download_url,
              created.filename,
              requestEpoch,
              creatingTask.startedAt,
            );
          } else if (created.status === "failed") {
            const updated: StoredTask = {
              recordId,
              jobId: effectiveJobId,
              artifactType: "share_image",
              status: "failed",
              startedAt: creatingTask.startedAt,
              finishedAt: Date.now(),
              error: created.error ?? {
                code: "GENERATION_FAILED",
                message: "生成失败，请重试",
              },
              notificationState: "none",
            };
            set((s) => {
              if (currentEpoch !== requestEpoch) return s;
              const next = { ...s.tasks, [recordId]: updated };
              saveToLocalStorage(next);
              return { tasks: next };
            });
            return updated;
          } else {
            const updated: StoredTask = {
              recordId,
              jobId: effectiveJobId,
              artifactType: "share_image",
              status: "polling",
              startedAt: creatingTask.startedAt,
              downloadUrl: created.download_url,
              filename: created.filename,
              notificationState: "none",
            };
            set((s) => {
              if (currentEpoch !== requestEpoch) return s;
              const next = { ...s.tasks, [recordId]: updated };
              saveToLocalStorage(next);
              return { tasks: next };
            });
            if (currentEpoch === requestEpoch) get().ensurePollingLoop();
            return updated;
          }
        } catch (err) {
          if (
            err instanceof ApiRequestError &&
            (err.status === 401 || err.code === "AUTH_REQUIRED")
          ) {
            throw err;
          }
          const updated: StoredTask = {
            recordId,
            jobId: effectiveJobId,
            artifactType: "share_image",
            status: "failed",
            startedAt: creatingTask.startedAt,
            finishedAt: Date.now(),
            error:
              err instanceof ApiRequestError
                ? { code: err.code, message: err.message }
                : { code: "UNKNOWN", message: "生成失败，请重试" },
            notificationState: "none",
          };
          set((s) => {
            if (currentEpoch !== requestEpoch) return s;
            const next = { ...s.tasks, [recordId]: updated };
            saveToLocalStorage(next);
            return { tasks: next };
          });
          return updated;
        }
      })();

      inFlightMap.set(recordId, promise);
      try {
        return await promise;
      } finally {
        inFlightMap.delete(recordId);
      }
    },

    retryTask: async (recordId: string, jobId?: string) => {
      return get().startOrFetchTask(recordId, { isUserRetry: true, jobId });
    },

    recheckTask: async (recordId: string) => {
      const requestEpoch = currentEpoch;
      if (inFlightMap.has(recordId)) {
        return inFlightMap.get(recordId)!;
      }

      const promise = (async (): Promise<StoredTask> => {
        const existing = get().tasks[recordId];
        const effectiveJobId = existing?.jobId || null;
        try {
          const art = await getArtifact(recordId, "share_image");
          if (currentEpoch !== requestEpoch) {
            return (
              existing || {
                recordId,
                jobId: effectiveJobId,
                artifactType: "share_image",
                status: "checking",
                startedAt: Date.now(),
                notificationState: "none",
              }
            );
          }

          if (art.status === "ready" && art.download_url) {
            return await processBackendReadyTask(
              recordId,
              art.download_url,
              art.filename,
              requestEpoch,
              existing?.startedAt,
            );
          }
          if (art.status === "failed") {
            const updated: StoredTask = {
              recordId,
              jobId: effectiveJobId,
              artifactType: "share_image",
              status: "failed",
              startedAt: existing?.startedAt || Date.now(),
              finishedAt: Date.now(),
              error: art.error ?? {
                code: "GENERATION_FAILED",
                message: "生成失败，请重试",
              },
              notificationState: existing?.notificationState || "none",
            };
            set((s) => {
              if (currentEpoch !== requestEpoch) return s;
              const next = { ...s.tasks, [recordId]: updated };
              saveToLocalStorage(next);
              return { tasks: next };
            });
            return updated;
          }
          // pending / running -> 重置 startedAt 恢复新的观察窗口
          const updated: StoredTask = {
            recordId,
            jobId: effectiveJobId,
            artifactType: "share_image",
            status: "polling",
            startedAt: Date.now(), // 刷新观察窗口起点
            downloadUrl: art.download_url,
            filename: art.filename,
            notificationState: "none",
          };
          set((s) => {
            if (currentEpoch !== requestEpoch) return s;
            const next = { ...s.tasks, [recordId]: updated };
            saveToLocalStorage(next);
            return { tasks: next };
          });
          if (currentEpoch === requestEpoch) get().ensurePollingLoop();
          return updated;
        } catch (err) {
          if (
            err instanceof ApiRequestError &&
            (err.status === 401 || err.code === "AUTH_REQUIRED")
          ) {
            throw err;
          }
          const updated: StoredTask = {
            recordId,
            jobId: effectiveJobId,
            artifactType: "share_image",
            status: existing?.status || "timeout",
            startedAt: existing?.startedAt || Date.now(),
            error:
              err instanceof ApiRequestError
                ? { code: err.code, message: err.message }
                : { code: "NETWORK_ERROR", message: "网络连接失败，请检查网络" },
            notificationState: "none",
          };
          set((s) => {
            if (currentEpoch !== requestEpoch) return s;
            const next = { ...s.tasks, [recordId]: updated };
            saveToLocalStorage(next);
            return { tasks: next };
          });
          return updated;
        }
      })();

      inFlightMap.set(recordId, promise);
      try {
        return await promise;
      } finally {
        inFlightMap.delete(recordId);
      }
    },
  }),
);
