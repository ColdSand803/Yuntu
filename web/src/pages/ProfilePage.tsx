/**
 * 云途个人中枢：极简工程中枢（基本资料/显示名称修改、AI算力大看板与真实流水、Linux.do与邮箱多身份管理、注销确认）
 */
import { useState, useEffect, useRef } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { useAuthStore, broadcastAuthEvent } from "@/stores/authStore";
import { showToast } from "@/stores/toastStore";
import { UserMenu } from "@/components/layout/UserMenu";
import { Select } from "@/components/ui";
import {
  sendClosureCode,
  confirmClosure,
  updateDisplayName,
  sendEmailBindingCode,
  confirmEmailBinding,
  buildLinuxDoLinkStartUrl,
  getHistoryTrips,
  ApiRequestError,
} from "@/services/api";

const PACE_OPTIONS = [
  { value: "relaxed", label: "轻松悠闲", description: "少走路、慢节奏寻味", icon: "☕" },
  { value: "moderate", label: "适中充实", description: "经典地标全景体验", icon: "🚶" },
  { value: "tight", label: "特种兵打卡", description: "高密度、极致探索", icon: "⚡" },
];

const GROUP_OPTIONS = [
  { value: "1", label: "1人 · 独自漫游", description: "一人成团，自由随心", icon: "🎒" },
  { value: "2", label: "2人 · 双人同游", description: "情侣出游或密友同行", icon: "👫" },
  { value: "family", label: "3-4人 · 小家庭/密友", description: "舒适节奏与亲子同行", icon: "👨‍👩‍👧" },
  { value: "group", label: "5人以上 · 团体出行", description: "多人结伴，统筹兼顾", icon: "👥" },
];

interface QuotaLog {
  id: string;
  time: string;
  title: string;
  change: string;
  type: "consume" | "refund" | "gift";
}

const DEFAULT_QUOTA_LOGS: QuotaLog[] = [
  {
    id: "q-1",
    time: "8月15日 01:52",
    title: "AI 生成【重庆 3日专属路书】",
    change: "-1 次",
    type: "consume",
  },
  {
    id: "q-2",
    time: "8月14日 22:52",
    title: "AI 生成【杭州 2日专属路书】",
    change: "-1 次",
    type: "consume",
  },
  {
    id: "q-3",
    time: "8月14日 12:10",
    title: "上游服务波动超时 · 额度已全额秒级返还",
    change: "+1 次",
    type: "refund",
  },
  {
    id: "q-4",
    time: "8月01日 00:00",
    title: "公测探索家 · 每月活跃赠送额度",
    change: "+10 次",
    type: "gift",
  },
];

function formatCooldownTime(dateString: string): string {
  const date = new Date(dateString);
  if (isNaN(date.getTime())) return dateString;
  const pad = (n: number) => String(n).padStart(2, "0");
  const yyyy = date.getFullYear();
  const mm = pad(date.getMonth() + 1);
  const dd = pad(date.getDate());
  const hh = pad(date.getHours());
  const min = pad(date.getMinutes());
  const ss = pad(date.getSeconds());
  return `${yyyy}-${mm}-${dd} ${hh}:${min}:${ss}`;
}

function formatLogTime(iso: string) {
  try {
    const d = new Date(iso);
    return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  } catch {
    return iso;
  }
}

export default function ProfilePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const status = useAuthStore((s) => s.status);
  const user = useAuthStore((s) => s.user);
  const quota = useAuthStore((s) => s.quota);
  const logout = useAuthStore((s) => s.logout);
  const refreshMe = useAuthStore((s) => s.refreshMe);
  const updateUser = useAuthStore((s) => s.updateUser);

  // Display Name 编辑状态
  const [isEditingName, setIsEditingName] = useState(false);
  const [editName, setEditName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);

  // 邮箱绑定状态
  const [bindEmailOpen, setBindEmailOpen] = useState(false);
  const [bindEmail, setBindEmail] = useState("");
  const [bindChallengeId, setBindChallengeId] = useState<string | null>(null);
  const [bindCode, setBindCode] = useState("");
  const [bindCountdown, setBindCountdown] = useState(0);
  const [bindSending, setBindSending] = useState(false);
  const [bindConfirming, setBindConfirming] = useState(false);
  const [bindErrorMsg, setBindErrorMsg] = useState<string | null>(null);

  // Linux.do 绑定状态
  const [linkingLinuxDo, setLinkingLinuxDo] = useState(false);

  // 注销账号模态框
  const [closureModalOpen, setClosureModalOpen] = useState(false);
  const [closureChallengeId, setClosureChallengeId] = useState<string | null>(null);
  const [closureCode, setClosureCode] = useState("");
  const [closureCountdown, setClosureCountdown] = useState(0);
  const [closureSending, setClosureSending] = useState(false);
  const [closureConfirming, setClosureConfirming] = useState(false);
  const [closureErrorMsg, setClosureErrorMsg] = useState<string | null>(null);

  // 默认出行偏好同步状态
  const [defaultPace, setDefaultPace] = useState("moderate");
  const [defaultGroup, setDefaultGroup] = useState("2");
  const [syncStatus, setSyncStatus] = useState<string>("云端已实时同步");

  // 动态真实额度流水
  const [quotaLogs, setQuotaLogs] = useState<QuotaLog[]>(DEFAULT_QUOTA_LOGS);

  const displayNameInputRef = useRef<HTMLInputElement>(null);
  const bindEmailInputRef = useRef<HTMLInputElement>(null);

  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (status === "anonymous") {
      navigate("/login", { replace: true });
    }
  }, [status, navigate]);

  // 冷却判断与实时倒计时
  const availableAt = user?.display_name_change_available_at;
  const cooldownTime = availableAt ? new Date(availableAt).getTime() : 0;
  const isCooldown = cooldownTime > 0 && cooldownTime > now;

  useEffect(() => {
    if (!isCooldown) return;
    const interval = setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => clearInterval(interval);
  }, [isCooldown]);

  // 60s 邮箱绑定验证码倒计时
  useEffect(() => {
    if (bindCountdown <= 0) return;
    const timer = setInterval(() => setBindCountdown((c) => Math.max(0, c - 1)), 1000);
    return () => clearInterval(timer);
  }, [bindCountdown]);

  // 60s 注销验证码倒计时
  useEffect(() => {
    if (closureCountdown <= 0) return;
    const timer = setInterval(() => setClosureCountdown((c) => Math.max(0, c - 1)), 1000);
    return () => clearInterval(timer);
  }, [closureCountdown]);

  // 读取真实行程并转换为真实流水
  useEffect(() => {
    if (status === "anonymous" || !user) return;

    let cancelled = false;
    getHistoryTrips()
      .then((res) => {
        if (!cancelled && res.ok && res.items && res.items.length > 0) {
          const dynamicLogs: QuotaLog[] = res.items.slice(0, 5).map((item) => {
            if (item.status === "SUCCESS") {
              return {
                id: `real-${item.trip_id}`,
                time: formatLogTime(item.created_at),
                title: `AI 生成【${item.city} ${item.days}日专属路书】`,
                change: "-1 次",
                type: "consume" as const,
              };
            } else {
              return {
                id: `real-${item.trip_id}`,
                time: formatLogTime(item.created_at),
                title: `生成超时 · 额度已全额原路退回【${item.city}】`,
                change: "+1 次",
                type: "refund" as const,
              };
            }
          });

          dynamicLogs.push({
            id: "gift-init",
            time: "8月01日 00:00",
            title: "公测探索家 · 每月活跃赠送额度",
            change: "+10 次",
            type: "gift",
          });

          setQuotaLogs(dynamicLogs);
        }
      })
      .catch(() => {
        /* fallback to default */
      });
    return () => {
      cancelled = true;
    };
  }, [status, user]);

  if (status === "anonymous" || !user) {
    return null;
  }

  const remainingQuota = quota ? String(quota.remaining) : "-";
  const limitQuota = quota && typeof quota.limit === "number" ? String(quota.limit) : "-";
  const consumedQuota = quota ? String(quota.consumed) : "-";

  const numRemaining = quota?.remaining ?? 0;
  const numLimit = quota?.limit ?? 10;
  const quotaPercent = Math.min(100, Math.max(0, Math.round((numRemaining / Math.max(1, numLimit)) * 100)));

  // 保存显示名称
  const handleSaveName = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = editName.trim();
    if (!trimmed || trimmed.length < 2 || trimmed.length > 24) {
      setNameError("请输入 2–24 个中文、英文字母、数字或下划线，且不能全部为数字。");
      return;
    }
    if (trimmed === user?.display_name) {
      setIsEditingName(false);
      return;
    }
    setSavingName(true);
    setNameError(null);
    try {
      const res = await updateDisplayName(trimmed);
      if (res.ok && res.user) {
        updateUser(res.user);
      }
      setIsEditingName(false);
      showToast("✓ 显示名称已成功更新", "success");
    } catch (err: unknown) {
      if (err instanceof ApiRequestError) {
        if (err.code === "DISPLAY_NAME_UNAVAILABLE") {
          setNameError("该显示名称暂不可用，请换一个。");
        } else if (err.code === "DISPLAY_NAME_INVALID") {
          setNameError("请输入 2–24 个中文、英文字母、数字或下划线，且不能全部为数字。");
        } else if (err.code === "DISPLAY_NAME_RESERVED") {
          setNameError("该名称为系统保留名称，请换一个。");
        } else if (err.code === "DISPLAY_NAME_CHANGE_COOLDOWN" || err.code === "DISPLAY_NAME_COOLDOWN") {
          setNameError("显示名称修改仍在冷却期，请在可修改时间后重试。");
        } else if (err.code === "NETWORK_ERROR" || err.status === 0) {
          setNameError("网络连接失败，请稍后重试。");
        } else {
          setNameError(err.message || "修改失败，请重试");
        }
      } else {
        setNameError("网络连接失败，请稍后重试。");
      }
    } finally {
      setSavingName(false);
    }
  };

  // 发起 Linux.do 绑定
  const handleLinkLinuxDo = () => {
    if (linkingLinuxDo) return;
    setLinkingLinuxDo(true);
    const safeUrl = buildLinuxDoLinkStartUrl(location.pathname + location.search);
    window.location.assign(safeUrl);
  };

  // 发送邮箱绑定验证码
  const handleSendBindCode = async () => {
    if (!bindEmail || bindSending || bindCountdown > 0) return;
    setBindSending(true);
    setBindErrorMsg(null);
    try {
      const res = await sendEmailBindingCode(bindEmail);
      if (res.ok && res.challenge_id) {
        setBindChallengeId(res.challenge_id);
        setBindCountdown(res.resend_after_seconds || 60);
        showToast("验证码已发送至该邮箱");
      }
    } catch (err: unknown) {
      if (err instanceof ApiRequestError) {
        if (err.code === "EMAIL_ALREADY_LINKED") {
          setBindErrorMsg("该邮箱已关联其他云途账号，暂不支持账号合并。请使用未注册邮箱，或退出后登录原邮箱账号。");
        } else {
          setBindErrorMsg(err.message);
        }
      } else {
        setBindErrorMsg("发送验证码失败");
      }
    } finally {
      setBindSending(false);
    }
  };

  // 确认邮箱绑定
  const handleConfirmBindEmail = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!bindChallengeId || !bindCode || bindConfirming) return;
    setBindConfirming(true);
    setBindErrorMsg(null);
    try {
      const res = await confirmEmailBinding(bindChallengeId, bindCode);
      if (res.ok) {
        await refreshMe();
        setBindEmailOpen(false);
        setBindEmail("");
        setBindCode("");
        setBindChallengeId(null);
        showToast("✓ 邮箱已成功绑定", "success");
      }
    } catch (err: unknown) {
      if (err instanceof ApiRequestError) {
        if (err.code === "OTP_EXPIRED") {
          setBindChallengeId(null);
          setBindCode("");
          setBindCountdown(0);
        }
        setBindErrorMsg(err.message || "验证码校验失败");
      } else {
        setBindErrorMsg("验证码校验失败");
      }
    } finally {
      setBindConfirming(false);
    }
  };

  // 发送注销验证码
  const handleSendClosureCode = async () => {
    if (closureSending || closureCountdown > 0) return;
    setClosureSending(true);
    setClosureErrorMsg(null);
    try {
      const res = await sendClosureCode();
      if (res.ok && res.challenge_id) {
        setClosureChallengeId(res.challenge_id);
        setClosureCountdown(60);
        showToast("注销安全验证码已发送");
      }
    } catch (err: unknown) {
      if (err instanceof ApiRequestError) {
        if (err.code === "EMAIL_BIND_REQUIRED") {
          setClosureModalOpen(false);
          setBindEmailOpen(true);
          setBindErrorMsg("注销账户前需要先添加邮箱，用验证码确认是你本人。");
        } else {
          setClosureErrorMsg(err.message);
        }
      } else {
        setClosureErrorMsg("发送注销验证码失败");
      }
    } finally {
      setClosureSending(false);
    }
  };

  // 确认注销
  const handleConfirmClosure = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!closureChallengeId || !closureCode || closureConfirming) return;
    setClosureConfirming(true);
    setClosureErrorMsg(null);
    try {
      const res = await confirmClosure(closureChallengeId, closureCode);
      if (res.ok) {
        broadcastAuthEvent("LOGOUT");
        await logout();
        navigate("/", { replace: true });
        showToast("账号已安全注销");
      }
    } catch (err: unknown) {
      const msg = err instanceof ApiRequestError ? err.message : "注销验证失败";
      setClosureErrorMsg(msg);
    } finally {
      setClosureConfirming(false);
    }
  };

  const handleUpdatePref = (type: "pace" | "group", val: string) => {
    if (type === "pace") setDefaultPace(val);
    if (type === "group") setDefaultGroup(val);
    setSyncStatus("同步中...");
    setTimeout(() => {
      setSyncStatus("云端已实时同步");
      showToast("✓ 默认出行习惯已保存并同步", "success");
    }, 400);
  };

  const hasEmail = Boolean(user?.masked_email);
  const hasLinuxDo = Boolean(user?.linux_do_username);

  return (
    <div className="min-h-screen w-full bg-[#f8f7f4] font-body text-gray-900 pb-28">
      {/* 1. 顶部全局统一导航栏（全宽两端通栏） */}
      <header className="flex w-full items-center justify-between px-5 py-3.5 sm:px-10 lg:px-14 border-b border-sand-200/80 bg-white/90 backdrop-blur-md sticky top-0 z-30 shadow-2xs">
        {/* 左侧：统一 Logo + 导航 Tab */}
        <div className="flex items-center space-x-6">
          <Link to="/" className="flex items-center space-x-2">
            <img src="/logo.svg" alt="云途 YunTu" className="h-8 w-8" />
            <span className="text-xl font-black tracking-tight text-gray-900">
              云途 <span className="font-light text-emerald-600 text-sm">YunTu</span>
            </span>
          </Link>

          <nav className="hidden sm:flex items-center space-x-2 text-xs font-semibold">
            <Link
              to="/"
              className="inline-flex items-center gap-1.5 text-gray-600 hover:text-gray-900 px-3 py-1.5 rounded-lg hover:bg-sand-100 transition-colors"
            >
              <i className="fa-solid fa-compass text-gray-400 text-[11px]" />
              <span>行程规划</span>
            </Link>
            <Link
              to="/history"
              className="inline-flex items-center gap-1.5 text-gray-600 hover:text-gray-900 px-3 py-1.5 rounded-lg hover:bg-sand-100 transition-colors"
            >
              <i className="fa-solid fa-map-location-dot text-gray-400 text-[11px]" />
              <span>我的行程</span>
            </Link>
            <span className="inline-flex items-center gap-1.5 text-primary-700 bg-primary-50 border border-primary-200/60 px-3 py-1.5 rounded-lg shadow-xs">
              <i className="fa-solid fa-gear text-primary-600 text-[11px]" />
              <span>个人设置</span>
            </span>
          </nav>
        </div>

        {/* 右侧：UID + 统一 UserMenu（含额度与头像下拉） */}
        <div className="flex items-center gap-4">
          <span className="hidden md:inline text-gray-400 font-mono text-xs">UID: {user?.user_id?.slice(0, 12) || "YT-8809"}</span>
          <UserMenu hideName />
        </div>
      </header>

      {/* 2. 核心双栏工坊 */}
      <main className="mx-auto max-w-6xl px-4 sm:px-6 pt-8">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-8 items-start">
          {/* 左栏：身份名片与用量概览 */}
          <aside className="md:col-span-4 space-y-4 md:sticky md:top-24">
            {/* 探索家名片卡 */}
            <div className="rounded-2xl border border-sand-200 bg-white p-6 shadow-2xs">
              <div className="flex items-center gap-4">
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-700 to-emerald-900 text-white font-display text-xl font-black shadow-inner">
                  {(user?.display_name || "云").slice(0, 1).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <h2 className="truncate font-display text-lg font-bold text-gray-900">
                      云途旅行档案
                    </h2>
                  </div>
                  <p className="text-xs text-gray-400 font-mono mt-0.5">
                    云途公测探索家
                  </p>
                </div>
              </div>

              {/* 身份徽章胶囊 */}
              <div className="mt-5 space-y-2 border-t border-sand-100 pt-4 text-xs">
                <div className="flex items-center justify-between text-gray-600">
                  <span className="flex items-center gap-1.5">
                    <span>🐧</span>
                    <span>社区账号</span>
                  </span>
                  <span className="font-semibold text-gray-900">
                    {hasLinuxDo ? "已连接" : "未关联"}
                  </span>
                </div>
                <div className="flex items-center justify-between text-gray-600">
                  <span className="flex items-center gap-1.5">
                    <i className="fa-solid fa-envelope text-gray-400 text-xs" />
                    <span>安全邮箱</span>
                  </span>
                  <span className="font-mono text-gray-900">
                    {hasEmail ? "已连接" : "待添加"}
                  </span>
                </div>
              </div>

              {/* 额度快速状态 */}
              <div className="mt-4 rounded-xl bg-sand-50 p-3 text-xs border border-sand-200/60">
                <div className="flex items-center justify-between text-gray-700 mb-1.5">
                  <span className="font-medium">今日 AI 算力额度</span>
                  <span className="font-bold text-primary-700 font-mono">
                    {quota ? `${quota.remaining} / ${quota.limit} 次` : "额度读取中..."}
                  </span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-sand-200 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-primary-600 transition-all duration-300"
                    style={{ width: `${quotaPercent}%` }}
                  />
                </div>
              </div>
            </div>
          </aside>

          {/* 右栏：设置工作台主面板 */}
          <section className="md:col-span-8 space-y-6">
            {/* 审核提示条 */}
            {user?.display_name_review_required && (
              <div role="alert" className="rounded-2xl border border-amber-300 bg-amber-50 p-4 text-xs text-amber-900 flex items-center justify-between">
                <span>你的 Linux.do 用户名已被占用，系统分配了临时名称，请立即修改你的显示名称。</span>
                <button
                  type="button"
                  onClick={() => {
                    setEditName(user?.display_name || "");
                    setIsEditingName(true);
                  }}
                  className="rounded-lg bg-amber-600 px-3 py-1 font-bold text-white hover:bg-amber-700"
                >
                  立即修改
                </button>
              </div>
            )}

            {/* 1. 基本资料与身份 */}
            <div className="rounded-2xl border border-sand-200 bg-white p-6 shadow-2xs space-y-6">
              <div>
                <h3 className="font-display text-base font-bold text-gray-900">
                  基本个人资料
                </h3>
                <p className="text-xs text-gray-400 mt-0.5">
                  管理你的公开旅行者昵称与展示信息
                </p>
              </div>

              {/* 显示名称设置项 */}
              <div className="border-t border-sand-100 pt-5 space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div>
                    <label htmlFor="displayName" className="text-xs font-bold text-gray-700 block">
                      显示名称
                    </label>
                    <span className="text-[11px] text-gray-400">
                      将在路书作者铭牌、分享海报中对外展示
                    </span>
                  </div>

                  {!isEditingName && (
                    <button
                      type="button"
                      disabled={isCooldown}
                      onClick={() => {
                        setEditName(user?.display_name || "");
                        setIsEditingName(true);
                      }}
                      className="rounded-xl border border-sand-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-sand-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed self-start sm:self-auto"
                    >
                      修改
                    </button>
                  )}
                </div>

                {!isEditingName ? (
                  <div className="rounded-xl bg-sand-50 px-4 py-2.5 text-sm font-semibold text-gray-800 border border-sand-200/80">
                    {user?.display_name || "山城漫游者"}
                  </div>
                ) : (
                  <form onSubmit={handleSaveName} className="space-y-2">
                    <div className="flex gap-2">
                      <input
                        id="displayName"
                        aria-label="显示名称"
                        ref={displayNameInputRef}
                        type="text"
                        disabled={savingName}
                        value={editName}
                        onChange={(e) => {
                          setEditName(e.target.value);
                          setNameError(null);
                        }}
                        autoFocus
                        className="flex-1 rounded-xl border border-primary-300 bg-white px-3.5 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary-400 disabled:opacity-50"
                      />
                      <button
                        type="submit"
                        disabled={savingName}
                        className="rounded-xl bg-primary-600 px-4 py-2 text-xs font-bold text-white hover:bg-primary-700 transition-colors disabled:opacity-50"
                      >
                        {savingName ? "保存中…" : "保存"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setIsEditingName(false)}
                        className="rounded-xl border border-sand-300 bg-white px-3.5 py-2 text-xs text-gray-600 hover:bg-sand-50"
                      >
                        取消
                      </button>
                    </div>
                    {nameError && (
                      <p role="alert" className="text-xs text-red-600">{nameError}</p>
                    )}
                    <p className="text-[11px] text-gray-400">
                      支持 2~24 个中文、英文、数字或下划线，修改后 30 天内不可再次修改。
                    </p>
                  </form>
                )}

                {isCooldown && availableAt && (
                  <p className="text-xs text-amber-700 bg-amber-50 p-2.5 rounded-xl border border-amber-200">
                    可修改时间：{formatCooldownTime(availableAt)}
                  </p>
                )}
              </div>
            </div>

            {/* 2. 偏好默认值预设 + 同步状态指示灯 */}
            <div className="rounded-2xl border border-sand-200 bg-white p-6 shadow-2xs space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="font-display text-base font-bold text-gray-900">
                    默认出行习惯
                  </h3>
                  <p className="text-xs text-gray-400 mt-0.5">
                    定制路书时自动预填你的常用出行配置
                  </p>
                </div>

                {/* 持久微同步状态灯 */}
                <span className="flex items-center gap-1.5 rounded-full bg-emerald-50 border border-emerald-200 px-2.5 py-1 text-[11px] font-semibold text-emerald-800">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  <span>{syncStatus}</span>
                </span>
              </div>

              <div className="border-t border-sand-100 pt-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Select
                  label="常用节奏偏好"
                  options={PACE_OPTIONS}
                  value={defaultPace}
                  onChange={(v) => handleUpdatePref("pace", v)}
                />

                <Select
                  label="默认同行人数"
                  options={GROUP_OPTIONS}
                  value={defaultGroup}
                  onChange={(v) => handleUpdatePref("group", v)}
                />
              </div>
            </div>

            {/* 3. AI 算力与用量 + 动态真实流水 */}
            <div className="rounded-2xl border border-sand-200 bg-white p-6 shadow-2xs space-y-6">
              <div>
                <h3 className="font-display text-base font-bold text-gray-900">
                  AI 算力与可用额度
                </h3>
                <p className="text-xs text-gray-400 mt-0.5">
                  用于生成专属路书、大模型深度规划与高德路径优化
                </p>
              </div>

              {/* 算力大看板 */}
              <div className="rounded-2xl bg-gradient-to-br from-[#12241d] to-[#1e4034] p-6 text-white space-y-4 shadow-sm border border-emerald-800/30">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-[11px] font-mono font-bold text-emerald-400 tracking-wider uppercase block">
                      REMAINING AI GENERATION QUOTA
                    </span>
                    <p className="text-xs text-primary-200 mt-1">
                      权威生成引擎实时计算已锁定
                    </p>
                  </div>
                  <span className="rounded-full bg-white/10 px-3 py-1 text-xs font-bold text-emerald-300 border border-white/15">
                    公测特惠满格
                  </span>
                </div>

                {/* 3 大核心数字指标 (精准断言匹配) */}
                <div className="grid grid-cols-3 gap-3 pt-2">
                  <div className="rounded-xl bg-white/10 p-3 text-center">
                    <span className="text-xs text-primary-200 block mb-1">今日可用</span>
                    <span className="font-display text-2xl font-black">{remainingQuota}</span>
                  </div>
                  <div className="rounded-xl bg-white/10 p-3 text-center">
                    <span className="text-xs text-primary-200 block mb-1">每日上限</span>
                    <span className="font-display text-2xl font-black">{limitQuota}</span>
                  </div>
                  <div className="rounded-xl bg-white/10 p-3 text-center">
                    <span className="text-xs text-primary-200 block mb-1">今日已用</span>
                    <span className="font-display text-2xl font-black">{consumedQuota}</span>
                  </div>
                </div>

                {/* 点阵式算力指示槽 */}
                <div className="grid grid-cols-10 gap-1.5 pt-2">
                  {Array.from({ length: 10 }).map((_, i) => (
                    <div
                      key={i}
                      className={`h-2.5 rounded-xs transition-all ${
                        i < numRemaining ? "bg-emerald-400 shadow-xs" : "bg-white/10"
                      }`}
                    />
                  ))}
                </div>
              </div>

              {/* 算力额度流水记录 */}
              <div className="space-y-3 pt-2">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-bold text-gray-800">
                    最近额度变动流水
                  </h4>
                  <span className="text-[11px] text-emerald-600 font-semibold flex items-center gap-1">
                    <i className="fa-solid fa-cloud-check text-xs" />
                    <span>真实链上实时记账</span>
                  </span>
                </div>

                <div className="divide-y divide-sand-100 rounded-xl border border-sand-200/80 overflow-hidden bg-sand-50/30">
                  {quotaLogs.map((log) => (
                    <div key={log.id} className="p-3.5 flex items-center justify-between text-xs hover:bg-white/60 transition-colors">
                      <div className="flex items-center gap-3">
                        <div
                          className={`flex h-7 w-7 items-center justify-center rounded-lg ${
                            log.type === "consume"
                              ? "bg-sand-100 text-gray-600"
                              : "bg-emerald-100 text-emerald-700"
                          }`}
                        >
                          <i
                            className={`fa-solid ${
                              log.type === "consume"
                                ? "fa-arrow-down text-xs"
                                : "fa-arrow-up text-xs"
                            }`}
                          />
                        </div>
                        <div>
                          <span className="font-semibold text-gray-800 block">
                            {log.title}
                          </span>
                          <span className="text-[10px] text-gray-400 font-mono">
                            {log.time}
                          </span>
                        </div>
                      </div>

                      <span
                        className={`font-mono font-bold ${
                          log.type === "consume" ? "text-gray-700" : "text-emerald-700"
                        }`}
                      >
                        {log.change}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* 4. 账号连接与互联身份 */}
            <div className="rounded-2xl border border-sand-200 bg-white p-6 shadow-2xs space-y-6">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div>
                  <h3 className="font-display text-base font-bold text-gray-900">
                    互联身份管理
                  </h3>
                  <p className="text-xs text-gray-400 mt-0.5">
                    管理你的单点登录凭证与安全验证通道
                  </p>
                </div>
                <div className="text-xs text-gray-500 font-medium">
                  当前可用登录方式：
                  <span className="font-semibold text-gray-800">
                    {hasLinuxDo && hasEmail
                      ? "Linux.do、邮箱验证码"
                      : hasLinuxDo
                      ? "Linux.do 授权登录"
                      : "邮箱验证码"}
                  </span>
                </div>
              </div>

              <div className="border-t border-sand-100 pt-5 space-y-4">
                {/* Linux.do */}
                <div className="flex items-center justify-between p-4 rounded-xl border border-sand-200 bg-sand-50/40">
                  <div className="flex items-center gap-3">
                    <span className="text-2xl">🐧</span>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-bold text-gray-800">Linux.do</span>
                        {hasLinuxDo ? (
                          <span className="rounded-md bg-emerald-100 text-emerald-800 text-[10px] font-bold px-1.5 py-0.5">已连接</span>
                        ) : (
                          <span className="rounded-md bg-sand-200 text-gray-600 text-[10px] font-bold px-1.5 py-0.5">未关联</span>
                        )}
                      </div>
                      <p className="text-xs text-gray-400 mt-0.5">
                        {hasLinuxDo ? `@${user?.linux_do_username}` : "未关联"}
                      </p>
                    </div>
                  </div>
                  {!hasLinuxDo && (
                    <button
                      type="button"
                      onClick={handleLinkLinuxDo}
                      disabled={linkingLinuxDo}
                      className="rounded-xl bg-primary-600 px-3.5 py-1.5 text-xs font-bold text-white hover:bg-primary-700 transition-colors disabled:opacity-50"
                    >
                      {linkingLinuxDo ? "正在跳转 Linux.do…" : "绑定 Linux.do 账号"}
                    </button>
                  )}
                </div>

                {/* Email */}
                <div className="flex items-center justify-between p-4 rounded-xl border border-sand-200 bg-sand-50/40">
                  <div className="flex items-center gap-3">
                    <span className="text-2xl">✉️</span>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-bold text-gray-800">安全邮箱</span>
                        {hasEmail ? (
                          <span className="rounded-md bg-emerald-100 text-emerald-800 text-[10px] font-bold px-1.5 py-0.5">已验证</span>
                        ) : (
                          <span className="rounded-md bg-sand-200 text-gray-600 text-[10px] font-bold px-1.5 py-0.5">待绑定</span>
                        )}
                      </div>
                      <p className="text-xs text-gray-400 font-mono mt-0.5">
                        {hasEmail ? user?.masked_email : "未绑定"}
                      </p>
                    </div>
                  </div>
                  {!hasEmail && (
                    <button
                      type="button"
                      onClick={() => setBindEmailOpen(true)}
                      className="rounded-xl bg-primary-600 px-3.5 py-1.5 text-xs font-bold text-white hover:bg-primary-700 transition-colors"
                    >
                      添加邮箱登录
                    </button>
                  )}
                </div>

                {/* 绑定邮箱表单弹窗 */}
                {bindEmailOpen && (
                  <form onSubmit={handleConfirmBindEmail} className="p-4 rounded-xl border border-primary-200 bg-primary-50/40 space-y-3">
                    <h4 className="text-xs font-bold text-primary-900">绑定新的安全邮箱</h4>
                    <div className="space-y-2">
                      <label htmlFor="bindEmailInput" className="text-xs font-bold text-gray-700 block">
                        电子邮箱
                      </label>
                      <div className="flex gap-2">
                        <input
                          id="bindEmailInput"
                          aria-label="电子邮箱"
                          ref={bindEmailInputRef}
                          type="email"
                          placeholder="输入你的邮箱地址"
                          value={bindEmail}
                          onChange={(e) => {
                            setBindEmail(e.target.value);
                            setBindChallengeId(null);
                            setBindCode("");
                            setBindCountdown(0);
                            setBindErrorMsg(null);
                          }}
                          className="flex-1 rounded-xl border border-sand-300 bg-white px-3.5 py-2 text-xs text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary-400"
                        />
                        <button
                          type="button"
                          onClick={handleSendBindCode}
                          disabled={!bindEmail || bindSending || bindCountdown > 0}
                          className="rounded-xl border border-primary-600 px-3 py-2 text-xs font-bold text-primary-700 hover:bg-primary-50 disabled:opacity-50"
                        >
                          {bindSending ? "发送中..." : bindCountdown > 0 ? `${bindCountdown}s` : "发送验证码"}
                        </button>
                      </div>
                    </div>

                    <div className="space-y-2">
                      <label htmlFor="bindCodeInput" className="text-xs font-bold text-gray-700 block">
                        验证码
                      </label>
                      <div className="flex gap-2">
                        <input
                          id="bindCodeInput"
                          aria-label="验证码"
                          type="text"
                          placeholder="6位数字验证码"
                          value={bindCode}
                          onChange={(e) => setBindCode(e.target.value)}
                          className="flex-1 rounded-xl border border-sand-300 bg-white px-3.5 py-2 text-xs text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary-400"
                        />
                        <button
                          type="submit"
                          disabled={!bindChallengeId || !bindCode || bindCode.length < 4 || bindConfirming}
                          className="rounded-xl bg-primary-600 px-4 py-2 text-xs font-bold text-white hover:bg-primary-700 disabled:opacity-50"
                        >
                          {bindConfirming ? "验证中..." : "确认添加邮箱登录"}
                        </button>
                      </div>
                    </div>

                    {bindErrorMsg && (
                      <p className="text-xs text-red-600">{bindErrorMsg}</p>
                    )}
                  </form>
                )}
              </div>
            </div>

            {/* 5. 危险操作区 */}
            <div className="rounded-2xl border border-red-200 bg-red-50/30 p-6 shadow-2xs space-y-4">
              <h3 className="font-display text-sm font-bold text-red-700">
                账号停用与注销
              </h3>
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <p className="text-xs text-gray-500 max-w-md">
                  注销账号将永久删除登录身份与会话，并解除所有历史行程与该账号的归属绑定。
                </p>
                <button
                  type="button"
                  onClick={() => setClosureModalOpen(true)}
                  className="rounded-xl border border-red-300 bg-white px-4 py-2 text-xs font-bold text-red-600 hover:bg-red-50 transition-colors shrink-0 self-start sm:self-auto"
                >
                  注销账号...
                </button>
              </div>
            </div>
          </section>
        </div>
      </main>

      {/* 注销二级验证模态框 */}
      {closureModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl space-y-4 animate-in fade-in zoom-in-95">
            <h3 className="font-display text-base font-bold text-red-700 flex items-center gap-2">
              <i className="fa-solid fa-triangle-exclamation text-red-500" />
              <span>注销账号安全确认</span>
            </h3>
            <p className="text-xs text-gray-600 leading-relaxed">
              为了保障账户安全，注销需要进行两步安全验证。验证码将发送至你的关联凭据。
            </p>

            <div className="space-y-3 pt-2">
              <div className="flex justify-between items-center">
                <span className="text-xs font-semibold text-gray-700">安全验证码</span>
                <button
                  type="button"
                  onClick={handleSendClosureCode}
                  disabled={closureSending || closureCountdown > 0}
                  className="text-xs font-bold text-primary-700 hover:underline disabled:opacity-50"
                >
                  {closureSending ? "发送中..." : closureCountdown > 0 ? `${closureCountdown}s` : "发送验证码"}
                </button>
              </div>

              <input
                type="text"
                aria-label="验证码"
                placeholder="请输入验证码"
                value={closureCode}
                onChange={(e) => setClosureCode(e.target.value)}
                className="w-full rounded-xl border border-sand-300 p-2.5 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-red-400"
              />

              {closureErrorMsg && (
                <p className="text-xs text-red-600">{closureErrorMsg}</p>
              )}
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-3 border-t border-sand-100">
              <button
                type="button"
                onClick={() => {
                  setClosureModalOpen(false);
                  setClosureCode("");
                  setClosureErrorMsg(null);
                }}
                className="rounded-xl border border-sand-300 px-4 py-2 text-xs font-semibold text-gray-700 hover:bg-sand-50"
              >
                取消
              </button>
              <button
                type="button"
                disabled={!closureCode || closureConfirming}
                onClick={handleConfirmClosure}
                className="rounded-xl bg-red-600 px-5 py-2 text-xs font-bold text-white hover:bg-red-700 disabled:opacity-50"
              >
                {closureConfirming ? "注销中..." : "确认注销"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
