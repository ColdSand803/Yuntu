import { useEffect, useRef, useCallback } from "react";
import { subscribeJobStream } from "@/services/jobStream";
import type { JobResponse } from "@/types/trip";

interface UseJobStreamOptions {
  jobId: string | undefined;
  onData: (data: JobResponse) => boolean | void;
  onTimeout?: () => void;
  onConsecutiveErrors?: (count: number) => void;
  onInterrupted?: () => void;
  consecutiveErrorThreshold?: number;
  enabled?: boolean;
  timeoutMs?: number;
}

export function useJobStream({
  jobId,
  onData,
  onTimeout,
  onConsecutiveErrors,
  onInterrupted,
  consecutiveErrorThreshold = 3,
  enabled = true,
  timeoutMs = 360_000,
}: UseJobStreamOptions) {
  const stoppedRef = useRef(false);
  const errCountRef = useRef(0);
  const closeRef = useRef<(() => void) | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  const onDataRef = useRef(onData);
  onDataRef.current = onData;
  const onTimeoutRef = useRef(onTimeout);
  onTimeoutRef.current = onTimeout;
  const onConsecutiveErrorsRef = useRef(onConsecutiveErrors);
  onConsecutiveErrorsRef.current = onConsecutiveErrors;
  const onInterruptedRef = useRef(onInterrupted);
  onInterruptedRef.current = onInterrupted;

  const stop = useCallback(() => {
    stoppedRef.current = true;
    closeRef.current?.();
    closeRef.current = null;
    clearTimeout(timerRef.current);
  }, []);

  useEffect(() => {
    if (!enabled || !jobId) return;
    stoppedRef.current = false;
    errCountRef.current = 0;

    function connect() {
      if (stoppedRef.current || !jobId) return;

      closeRef.current = subscribeJobStream(jobId, {
        onData(data) {
          errCountRef.current = 0;
          if (stoppedRef.current) return;
          const terminal = onDataRef.current(data);
          if (terminal) stop();
        },
        onError() {
          if (stoppedRef.current) return;
          errCountRef.current++;
          if (errCountRef.current >= consecutiveErrorThreshold) {
            onConsecutiveErrorsRef.current?.(errCountRef.current);
          }
        },
        onInterrupted() {
          if (stoppedRef.current) return;
          stop();
          onInterruptedRef.current?.();
        },
      });
    }

    function handleVisibility() {
      if (document.hidden) {
        closeRef.current?.();
        closeRef.current = null;
      } else if (!stoppedRef.current) {
        connect();
      }
    }

    timerRef.current = setTimeout(() => {
      if (!stoppedRef.current) {
        stop();
        onTimeoutRef.current?.();
      }
    }, timeoutMs);

    document.addEventListener("visibilitychange", handleVisibility);
    connect();

    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
      stop();
    };
  }, [enabled, jobId, consecutiveErrorThreshold, timeoutMs, stop]);

  return { stop, errCountRef };
}
