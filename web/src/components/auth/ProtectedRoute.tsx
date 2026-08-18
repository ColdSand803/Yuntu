import React, { useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const status = useAuthStore((s) => s.status);
  const bootstrapped = useAuthStore((s) => s.bootstrapped);
  const bootstrapError = useAuthStore((s) => s.bootstrapError);
  const bootstrap = useAuthStore((s) => s.bootstrap);
  const location = useLocation();
  const [retrying, setRetrying] = useState(false);

  const isAuthEnabled = import.meta.env.VITE_ENABLE_AUTH === "true";
  if (!isAuthEnabled) {
    return <>{children}</>;
  }

  const isDemo =
    location.search.includes("job_id=demo") ||
    location.pathname.startsWith("/demo");
  if (isDemo) {
    return <>{children}</>;
  }

  if (!bootstrapped) {
    return (
      <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3">
        <div className="h-8 w-8 animate-spin rounded-full border-[3px] border-primary-200 border-t-primary-500" />
        <p className="text-sm text-gray-400">正在验证权限…</p>
      </div>
    );
  }

  if (status === "unknown" && bootstrapError) {
    return (
      <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4 px-4 text-center">
        <div className="rounded-full bg-amber-50 p-4 text-amber-500">
          <i className="fas fa-wifi text-2xl" />
        </div>
        <div>
          <h2 className="text-base font-bold text-gray-800">暂时无法验证登录状态</h2>
          <p className="mt-1 text-xs text-gray-500">{bootstrapError}</p>
        </div>
        <button
          type="button"
          disabled={retrying}
          onClick={async () => {
            setRetrying(true);
            await bootstrap();
            setRetrying(false);
          }}
          className="rounded-xl bg-accent-500 px-5 py-2.5 text-xs font-bold text-white shadow-md hover:bg-accent-600 disabled:opacity-60"
        >
          {retrying ? "正在重新验证…" : "重新验证"}
        </button>
      </div>
    );
  }

  if (status === "anonymous") {
    const returnTo = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?returnTo=${returnTo}`} replace />;
  }

  return <>{children}</>;
}
