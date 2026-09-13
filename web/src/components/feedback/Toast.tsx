import { useEffect, useRef } from "react";
import { useToastStore } from "@/stores/toastStore";
import { CheckCircle2, CircleX } from "lucide-react";

export function Toast() {
  const { message, type, visible, hideToast } = useToastStore();
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    if (!visible) return;
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(hideToast, 3000);
    return () => clearTimeout(timerRef.current);
  }, [visible, hideToast]);

  return (
    <div
      aria-live="polite"
      className={`fixed bottom-8 left-1/2 z-[100] -translate-x-1/2 transition-all duration-300 ${
        visible ? "translate-y-0 opacity-100" : "translate-y-4 opacity-0 pointer-events-none"
      }`}
    >
      <div
        className={`flex items-center gap-2 rounded-xl px-5 py-3 text-sm font-medium shadow-lg ${
          type === "success"
            ? "bg-primary-600 text-white"
            : "bg-red-500 text-white"
        }`}
      >
        {type === "success" ? (
          <CheckCircle2 size={16} aria-hidden="true" />
        ) : (
          <CircleX size={16} aria-hidden="true" />
        )}
        {message}
      </div>
    </div>
  );
}
