import { useEffect, useRef, useCallback } from "react";

interface UsePollingOptions<T> {
  fetcher: () => Promise<T>;
  onData: (data: T) => boolean | void;
  interval?: number;
  maxAttempts?: number;
  onTimeout?: () => void;
  onConsecutiveErrors?: (count: number) => void;
  consecutiveErrorThreshold?: number;
  enabled?: boolean;
}

export function usePolling<T>({
  fetcher,
  onData,
  interval = 2000,
  maxAttempts = 90,
  onTimeout,
  onConsecutiveErrors,
  consecutiveErrorThreshold = 3,
  enabled = true,
}: UsePollingOptions<T>) {
  const attemptRef = useRef(0);
  const consecutiveErrorsRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const stoppedRef = useRef(false);
  const inFlightRef = useRef(false);

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const onDataRef = useRef(onData);
  onDataRef.current = onData;
  const onTimeoutRef = useRef(onTimeout);
  onTimeoutRef.current = onTimeout;
  const onConsecutiveErrorsRef = useRef(onConsecutiveErrors);
  onConsecutiveErrorsRef.current = onConsecutiveErrors;

  const stop = useCallback(() => {
    stoppedRef.current = true;
    clearTimeout(timerRef.current);
  }, []);

  useEffect(() => {
    if (!enabled) return;

    stoppedRef.current = false;
    attemptRef.current = 0;
    consecutiveErrorsRef.current = 0;

    async function tick() {
      if (stoppedRef.current) return;
      inFlightRef.current = true;
      attemptRef.current++;

      try {
        const data = await fetcherRef.current();
        if (stoppedRef.current) return;
        if (consecutiveErrorsRef.current > 0) onConsecutiveErrorsRef.current?.(0);
        consecutiveErrorsRef.current = 0;
        const shouldStop = onDataRef.current(data);
        if (shouldStop) {
          stoppedRef.current = true;
          return;
        }
      } catch {
        if (stoppedRef.current) return;
        consecutiveErrorsRef.current++;
        if (consecutiveErrorsRef.current >= consecutiveErrorThreshold) {
          onConsecutiveErrorsRef.current?.(consecutiveErrorsRef.current);
        }
      } finally {
        inFlightRef.current = false;
      }

      if (attemptRef.current >= maxAttempts) {
        onTimeoutRef.current?.();
        return;
      }

      if (document.hidden) return;

      timerRef.current = setTimeout(tick, interval);
    }

    function handleVisibilityChange() {
      if (document.hidden) {
        clearTimeout(timerRef.current);
      } else if (
        !stoppedRef.current &&
        !inFlightRef.current &&
        attemptRef.current < maxAttempts
      ) {
        clearTimeout(timerRef.current);
        tick();
      }
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);
    tick();

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      stop();
    };
  }, [enabled, interval, maxAttempts, consecutiveErrorThreshold, stop]);

  return { stop };
}
