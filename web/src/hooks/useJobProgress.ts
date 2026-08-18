import { useEffect, useRef, useCallback, useState } from "react";
import { useJobStream } from "./useJobStream";
import { usePolling } from "./usePolling";
import { pollJobStatus } from "@/services/api";
import type { JobResponse } from "@/types/trip";

const SSE_DISABLED = import.meta.env.VITE_JOB_STREAM === "off";
const FALLBACK_WINDOW_MS = 8_000;
const FALLBACK_ERROR_THRESHOLD = 3;

interface UseJobProgressOptions {
  jobId: string | undefined;
  onData: (data: JobResponse) => boolean | void;
  onTimeout?: () => void;
  onConsecutiveErrors?: (count: number) => void;
  consecutiveErrorThreshold?: number;
  enabled?: boolean;
}

export function useJobProgress({
  jobId,
  onData,
  onTimeout,
  onConsecutiveErrors,
  consecutiveErrorThreshold = 3,
  enabled = true,
}: UseJobProgressOptions) {
  const [degraded, setDegraded] = useState(SSE_DISABLED);
  const startTimeRef = useRef(0);

  useEffect(() => {
    if (enabled && jobId) {
      startTimeRef.current = Date.now();
    }
  }, [enabled, jobId]);

  const handleSSEErrors = useCallback(
    (count: number) => {
      if (
        count >= FALLBACK_ERROR_THRESHOLD &&
        Date.now() - startTimeRef.current < FALLBACK_WINDOW_MS
      ) {
        console.warn(
          "[useJobProgress] SSE endpoint unavailable, falling back to polling",
        );
        setDegraded(true);
        return;
      }
      onConsecutiveErrors?.(count);
    },
    [onConsecutiveErrors],
  );

  const handleSSEInterrupted = useCallback(() => {
    console.warn(
      "[useJobProgress] SSE interrupted by server, immediately switching to polling",
    );
    setDegraded(true);
  }, []);

  const { stop: stopSSE } = useJobStream({
    jobId,
    onData,
    onTimeout,
    onConsecutiveErrors: handleSSEErrors,
    onInterrupted: handleSSEInterrupted,
    consecutiveErrorThreshold: FALLBACK_ERROR_THRESHOLD,
    enabled: enabled && !degraded,
  });

  const fetcher = useCallback(() => pollJobStatus(jobId!), [jobId]);

  const { stop: stopPolling } = usePolling({
    fetcher,
    onData,
    interval: 2500,
    maxAttempts: 144,
    onTimeout,
    onConsecutiveErrors,
    consecutiveErrorThreshold,
    enabled: enabled && degraded && !!jobId,
  });

  const stop = useCallback(() => {
    stopSSE();
    stopPolling();
  }, [stopSSE, stopPolling]);

  return { stop };
}
