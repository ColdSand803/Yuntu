import { useCallback, useEffect, useRef, useState } from "react";
import { usePolling } from "./usePolling";
import {
  createArtifact,
  getArtifact,
  fetchArtifactBlob,
  ApiRequestError,
} from "@/services/api";
import type { Artifact, ArtifactType } from "@/types/trip";

export type ArtifactPhase =
  | "idle"
  | "creating"
  | "polling"
  | "ready"
  | "failed";

interface ArtifactError {
  code: string;
  message: string;
}

function toErr(e: unknown, fallback: string): ArtifactError {
  if (e instanceof ApiRequestError) return { code: e.code, message: e.message };
  return { code: "UNKNOWN", message: fallback };
}

// 轮询超时窗口（× interval 2s）。share_image 对接 AI 图像生成，实测约 50s，
// 给到 120s 余量防偶发慢响应误判超时；pdf 是后端拼页，几秒即出。
const MAX_ATTEMPTS: Record<ArtifactType, number> = {
  pdf: 30, // 60s
  share_image: 60, // 120s
};

/**
 * 封装后端 artifact（PDF / 分享图）的 GET-first → POST → 轮询 → 取 blob 生命周期。
 * 复用 usePolling 处理可见性暂停/超时/清理。同一 record 的 blob 常驻内存，
 * 重复 start() 直接复用、连 GET 都省，避免浪费每日额度。
 */
export function useArtifact(recordId: string | undefined, type: ArtifactType) {
  const [phase, setPhase] = useState<ArtifactPhase>("idle");
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [error, setError] = useState<ArtifactError | null>(null);
  const [polling, setPolling] = useState(false);

  // 当前内存 blob 归属的 record；换 record 时判定缓存失效
  const blobRecordRef = useRef<string | null>(null);
  // 当前 objectURL，用于替换/卸载时 revoke，避免泄漏
  const blobUrlRef = useRef<string | null>(null);

  // ready 后拉取二进制并生成预览 URL
  const finishReady = useCallback(
    async (art: Artifact) => {
      try {
        const b = await fetchArtifactBlob(art.download_url);
        if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current);
        const url = URL.createObjectURL(b);
        blobUrlRef.current = url;
        blobRecordRef.current = recordId ?? null;
        setArtifact(art);
        setBlob(b);
        setBlobUrl(url);
        setError(null);
        setPhase("ready");
      } catch (e) {
        setError(toErr(e, "下载失败，请重试"));
        setPhase("failed");
      }
    },
    [recordId],
  );

  const fetcher = useCallback(
    () => getArtifact(recordId!, type),
    [recordId, type],
  );

  const onData = useCallback(
    (art: Artifact): boolean => {
      if (art.status === "ready") {
        setPolling(false);
        void finishReady(art);
        return true;
      }
      if (art.status === "failed") {
        setPolling(false);
        setError(art.error ?? { code: "GENERATION_FAILED", message: "生成失败，请重试" });
        setPhase("failed");
        return true;
      }
      return false; // pending / running → 继续轮询
    },
    [finishReady],
  );

  const handleTimeout = useCallback(() => {
    setPolling(false);
    setError({ code: "TIMEOUT", message: "生成超时，请稍后重试" });
    setPhase("failed");
  }, []);

  usePolling({
    fetcher,
    onData,
    interval: 2000,
    maxAttempts: MAX_ATTEMPTS[type],
    onTimeout: handleTimeout,
    enabled: polling && !!recordId,
  });

  // 每次渲染刷新实现，再由 stableStart 以固定 identity 暴露 —— 消费方
  // useEffect([open, start]) 不会因 start 变化而反复触发
  const startImplRef = useRef<() => Promise<void>>();
  startImplRef.current = async () => {
    if (!recordId) return;
    // 已就绪且同一 record → 复用内存 blob，跳过 GET
    if (phase === "ready" && blob && blobRecordRef.current === recordId) return;
    // 进行中防重入
    if (phase === "creating" || phase === "polling") return;

    setError(null);
    setPhase("creating");

    // GET-first：查后端已有产物
    let existing: Artifact | null = null;
    try {
      existing = await getArtifact(recordId, type);
    } catch (e) {
      if (e instanceof ApiRequestError && e.status === 404) {
        existing = null; // 从未创建 → 走 POST
      } else {
        setError(toErr(e, "网络连接失败，请重试"));
        setPhase("failed");
        return;
      }
    }

    if (existing) {
      if (existing.status === "ready") {
        await finishReady(existing);
        return;
      }
      if (existing.status === "pending" || existing.status === "running") {
        setArtifact(existing);
        setPhase("polling");
        setPolling(true);
        return;
      }
      // failed → 落到 POST 重新生成
    }

    try {
      const created = await createArtifact(recordId, type);
      if (created.status === "ready") {
        await finishReady(created);
      } else if (created.status === "failed") {
        setError(created.error ?? { code: "GENERATION_FAILED", message: "生成失败，请重试" });
        setPhase("failed");
      } else {
        setArtifact(created);
        setPhase("polling");
        setPolling(true);
      }
    } catch (e) {
      setError(toErr(e, "生成失败，请重试"));
      setPhase("failed");
    }
  };

  const start = useCallback(() => {
    void startImplRef.current?.();
  }, []);

  const reset = useCallback(() => {
    setPolling(false);
    if (blobUrlRef.current) {
      URL.revokeObjectURL(blobUrlRef.current);
      blobUrlRef.current = null;
    }
    blobRecordRef.current = null;
    setArtifact(null);
    setBlob(null);
    setBlobUrl(null);
    setError(null);
    setPhase("idle");
  }, []);

  // 卸载时清理未 revoke 的 objectURL
  useEffect(() => {
    return () => {
      if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current);
    };
  }, []);

  const loading = phase === "creating" || phase === "polling";

  return { phase, loading, artifact, blob, blobUrl, error, start, reset };
}
