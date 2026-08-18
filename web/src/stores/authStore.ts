import { create } from "zustand";
import type { User, Quota, ActiveTrip } from "@/types/auth";

export type AuthStatus = "unknown" | "authenticated" | "anonymous";

interface AuthStore {
  status: AuthStatus;
  user: User | null;
  quota: Quota | null;
  activeTrip: ActiveTrip | null;
  bootstrapped: boolean;
  bootstrapError: string | null;

  bootstrap: () => Promise<void>;
  refreshMe: () => Promise<boolean>;
  setAuth: (user: User, quota: Quota, activeTrip: ActiveTrip | null) => void;
  updateUser: (user: User) => void;
  clearAuth: () => void;
  logout: () => Promise<void>;
}

// 广播频道名
const CHANNEL_NAME = "yuntu_auth_channel";

let bc: BroadcastChannel | null = null;
if (typeof window !== "undefined" && "BroadcastChannel" in window) {
  try {
    bc = new BroadcastChannel(CHANNEL_NAME);
  } catch {
    bc = null;
  }
}

export function broadcastAuthEvent(
  type: "LOGIN" | "LOGOUT" | "EXPIRED" | "ME_UPDATED",
) {
  if (bc) {
    try {
      bc.postMessage({ type });
    } catch {
      /* ignore */
    }
  }
}

export const useAuthStore = create<AuthStore>((set, get) => {
  // 监听多标签页同步消息
  if (bc) {
    bc.onmessage = (event) => {
      const type = event.data?.type;
      if (type === "LOGOUT" || type === "EXPIRED") {
        set({
          status: "anonymous",
          user: null,
          quota: null,
          activeTrip: null,
          bootstrapped: true,
          bootstrapError: null,
        });
      } else if (type === "LOGIN" || type === "ME_UPDATED") {
        void get().refreshMe();
      }
    };
  }

  return {
    status: "unknown",
    user: null,
    quota: null,
    activeTrip: null,
    bootstrapped: false,
    bootstrapError: null,

    bootstrap: async () => {
      try {
        const { getMe } = await import("@/services/api");
        const data = await getMe();
        if (data.ok && data.user) {
          set({
            status: "authenticated",
            user: data.user,
            quota: data.quota,
            activeTrip: data.active_trip,
            bootstrapped: true,
            bootstrapError: null,
          });
        } else {
          set({
            status: "anonymous",
            user: null,
            quota: null,
            activeTrip: null,
            bootstrapped: true,
            bootstrapError: null,
          });
        }
      } catch (err: unknown) {
        const { ApiRequestError } = await import("@/services/api");
        if (
          err instanceof ApiRequestError &&
          (err.status === 401 || err.code === "AUTH_REQUIRED")
        ) {
          set({
            status: "anonymous",
            user: null,
            quota: null,
            activeTrip: null,
            bootstrapped: true,
            bootstrapError: null,
          });
        } else {
          const current = get().status;
          const msg =
            err instanceof ApiRequestError
              ? err.message
              : "网络连接中断或服务暂不可用";
          if (current === "authenticated") {
            set({ bootstrapped: true, bootstrapError: msg });
          } else {
            set({ status: "unknown", bootstrapped: true, bootstrapError: msg });
          }
        }
      }
    },

    refreshMe: async (): Promise<boolean> => {
      try {
        const { getMe } = await import("@/services/api");
        const data = await getMe();
        if (data.ok && data.user) {
          set({
            status: "authenticated",
            user: data.user,
            quota: data.quota,
            activeTrip: data.active_trip,
            bootstrapError: null,
          });
          return true;
        }
        return false;
      } catch (err: unknown) {
        const { ApiRequestError } = await import("@/services/api");
        if (
          err instanceof ApiRequestError &&
          (err.status === 401 || err.code === "AUTH_REQUIRED")
        ) {
          set({
            status: "anonymous",
            user: null,
            quota: null,
            activeTrip: null,
            bootstrapError: null,
          });
          broadcastAuthEvent("EXPIRED");
        }
        return false;
      }
    },

    setAuth: (user, quota, activeTrip) => {
      set({
        status: "authenticated",
        user,
        quota,
        activeTrip,
        bootstrapped: true,
        bootstrapError: null,
      });
      broadcastAuthEvent("LOGIN");
    },

    updateUser: (user: User) => {
      set({ user });
      broadcastAuthEvent("ME_UPDATED");
    },

    clearAuth: () => {
      set({
        status: "anonymous",
        user: null,
        quota: null,
        activeTrip: null,
        bootstrapped: true,
        bootstrapError: null,
      });
    },

    logout: async () => {
      try {
        const { logout: apiLogout } = await import("@/services/api");
        await apiLogout();
      } catch {
        /* ignore */
      }
      set({
        status: "anonymous",
        user: null,
        quota: null,
        activeTrip: null,
        bootstrapped: true,
        bootstrapError: null,
      });
      broadcastAuthEvent("LOGOUT");
    },
  };
});
