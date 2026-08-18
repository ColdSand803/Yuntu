import { useEffect, useState, useRef, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { getMe, buildLinuxDoStartUrl, buildLinuxDoLinkStartUrl } from "@/services/api";
import { useAuthStore } from "@/stores/authStore";
import { showToast } from "@/stores/toastStore";
import { sanitizeReturnTo } from "@/utils/url";

const ERROR_MESSAGES: Record<string, string> = {
  OAUTH_STATE_INVALID: "登录请求已失效，请重新发起 Linux.do 登录。",
  OAUTH_ACCOUNT_INELIGIBLE: "该 Linux.do 账户暂不符合首次接入条件。新用户需达到 1级，且账户状态正常。",
  OAUTH_ACCOUNT_INACTIVE: "该 Linux.do 账户当前无法登录，请确认账户未停用或禁言。",
  OAUTH_PROVIDER_ERROR: "Linux.do 未完成授权或返回了异常结果，请重新尝试。",
  OAUTH_PROVIDER_UNAVAILABLE: "暂时无法连接 Linux.do，请稍后重试。",
  OAUTH_DISABLED: "Linux.do 登录暂未开放，请使用邮箱登录。",
  OAUTH_RATE_LIMITED: "请求过于频繁，请稍后再试。",
  IDENTITY_ALREADY_LINKED: "该 Linux.do 账号已关联其他云途账号，暂不支持账号合并。",
  IDENTITY_LINK_SESSION_CHANGED: "当前登录状态已变化，请返回个人资料后重新绑定。",
  LINUX_DO_IDENTITY_ALREADY_BOUND: "当前账号已经绑定 Linux.do。",
  EMAIL_IDENTITY_REQUIRED: "当前账号缺少邮箱登录方式，请返回个人资料后重新检查。",
};

function getErrorMessage(errorCode: string | null, mode: "login" | "link"): string {
  const fallback = mode === "link" ? "Linux.do 绑定未完成，请重新尝试。" : "Linux.do 登录未完成，请重新尝试。";
  if (!errorCode) return fallback;
  if (errorCode === "OAUTH_ACCOUNT_INELIGIBLE") {
    return mode === "link"
      ? "该 Linux.do 账号不符合绑定条件，请确认账号已达到 1级且状态正常。"
      : "该 Linux.do 账户暂不符合首次接入条件。新用户需达到 1级，且账户状态正常。";
  }
  return ERROR_MESSAGES[errorCode] || fallback;
}

type CallbackStatus = "loading" | "error" | "bootstrap_failure";

export default function AuthCallbackPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const outcome = searchParams.get("outcome");
  const rawReturnTo = searchParams.get("return_to");
  const rawError = searchParams.get("error");
  const rawMode = searchParams.get("mode");

  const mode: "login" | "link" = rawMode === "link" ? "link" : "login";
  const safeReturnTo = sanitizeReturnTo(rawReturnTo, mode === "link" ? "/profile" : "/");
  const setAuth = useAuthStore((s) => s.setAuth);

  const [status, setStatus] = useState<CallbackStatus>(() => {
    return outcome === "success" ? "loading" : "error";
  });
  const [retryingBootstrap, setRetryingBootstrap] = useState(false);

  const errorTitleRef = useRef<HTMLHeadingElement>(null);
  const retryBtnRef = useRef<HTMLButtonElement>(null);

  const fetchAndSetUser = useCallback(async () => {
    try {
      const res = await getMe();
      if (res.ok && res.user) {
        setAuth(res.user, res.quota, res.active_trip);
        if (mode === "link") {
          showToast("Linux.do 登录方式已添加", "success");
          navigate(safeReturnTo || "/profile", { replace: true });
        } else {
          if (res.user.display_name_review_required) {
            navigate("/profile", { replace: true });
          } else {
            navigate(safeReturnTo, { replace: true });
          }
        }
      } else {
        setStatus("bootstrap_failure");
      }
    } catch {
      setStatus("bootstrap_failure");
    }
  }, [setAuth, navigate, safeReturnTo, mode]);

  useEffect(() => {
    if (outcome === "success") {
      void fetchAndSetUser();
    }
  }, [outcome, fetchAndSetUser]);

  useEffect(() => {
    if (status === "error" || status === "bootstrap_failure") {
      const timer = setTimeout(() => {
        if (errorTitleRef.current) {
          errorTitleRef.current.focus();
        } else if (retryBtnRef.current) {
          retryBtnRef.current.focus();
        }
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [status]);

  const handleRecheck = async () => {
    setRetryingBootstrap(true);
    await fetchAndSetUser();
    setRetryingBootstrap(false);
  };

  const handleRetryLinuxDo = () => {
    const startUrl =
      mode === "link"
        ? buildLinuxDoLinkStartUrl(safeReturnTo || "/profile")
        : buildLinuxDoStartUrl(safeReturnTo);
    window.location.assign(startUrl);
  };

  const handleSecondaryAction = () => {
    if (mode === "link") {
      navigate("/profile", { replace: true });
    } else {
      navigate("/login", { replace: true });
    }
  };

  return (
    <div className="flex min-h-screen w-full flex-col items-center justify-center bg-sand-50 p-4 font-body text-gray-800">
      <div className="w-full max-w-md rounded-3xl border border-gray-100 bg-white p-8 shadow-xl text-center">
        {status === "loading" && (
          <div aria-live="polite" className="flex flex-col items-center space-y-4 py-6">
            <div className="h-10 w-10 animate-spin rounded-full border-3 border-primary-200 border-t-primary-600" />
            <p className="text-sm font-bold text-gray-700">
              {mode === "link" ? "正在完成 Linux.do 绑定…" : "正在完成 Linux.do 登录…"}
            </p>
            <p className="text-xs text-gray-400">正在同步你的账户与额度信息</p>
          </div>
        )}

        {status === "bootstrap_failure" && (
          <div role="alert" className="flex flex-col items-center space-y-5 py-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-amber-50 text-amber-600 text-xl font-bold">
              ⚠️
            </div>
            <div>
              <h2
                ref={errorTitleRef}
                tabIndex={-1}
                className="text-base font-bold text-gray-800 focus:outline-none"
              >
                获取账号信息失败
              </h2>
              <p className="mt-2 text-xs leading-relaxed text-gray-600">
                {mode === "link"
                  ? "绑定可能已经完成，但暂时无法读取账户信息。"
                  : "登录可能已经完成，但暂时无法读取账户信息。"}
              </p>
            </div>
            <button
              ref={retryBtnRef}
              type="button"
              onClick={handleRecheck}
              disabled={retryingBootstrap}
              className="w-full rounded-xl bg-primary-600 py-3 text-xs font-bold text-white shadow-md transition-all hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:opacity-60"
            >
              {retryingBootstrap ? "读取中…" : "重新检查"}
            </button>
          </div>
        )}

        {status === "error" && (
          <div role="alert" className="flex flex-col items-center space-y-5 py-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-red-50 text-red-600 text-xl font-bold">
              ✕
            </div>
            <div>
              <h2
                ref={errorTitleRef}
                tabIndex={-1}
                className="text-base font-bold text-gray-900 focus:outline-none"
              >
                {mode === "link" ? "Linux.do 绑定未完成" : "Linux.do 登录未完成"}
              </h2>
              <p className="mt-2 text-xs leading-relaxed text-red-600 bg-red-50 border border-red-100 rounded-xl p-3">
                {getErrorMessage(rawError, mode)}
              </p>
            </div>

            <div className="w-full space-y-3 pt-2">
              <button
                ref={retryBtnRef}
                type="button"
                onClick={handleRetryLinuxDo}
                className="w-full rounded-xl bg-[#2c241c] py-3 text-xs font-serif font-bold text-[#f5efdf] shadow-md transition-all hover:bg-black focus:outline-none focus:ring-2 focus:ring-[#2c241c] focus:ring-offset-2"
              >
                {mode === "link" ? "重新发起 Linux.do 绑定" : "重新发起 Linux.do 登录"}
              </button>
              <button
                type="button"
                onClick={handleSecondaryAction}
                className="w-full rounded-xl border border-gray-200 bg-white py-3 text-xs font-bold text-gray-700 transition-all hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-2"
              >
                {mode === "link" ? "返回个人资料" : "返回邮箱登录"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
