import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { DemoSwitcher } from "@/components/demo/DemoSwitcher";
import { Select } from "@/components/ui";
import { useAuthStore } from "@/stores/authStore";
import { updateDisplayName, getHistoryTrips, ApiRequestError } from "@/services/api";

const PACE_OPTIONS = [
  { value: "relaxed", label: "轻松悠闲", description: "少走路、慢节奏寻味", icon: "☕" },
  { value: "moderate", label: "适中充实", description: "经典地标全景体验", icon: "🚶" },
  { value: "packed", label: "特种兵打卡", description: "高密度、极致探索", icon: "⚡" },
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

function formatLogTime(iso: string) {
  try {
    const d = new Date(iso);
    return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  } catch {
    return iso;
  }
}

export default function DemoProfilePage() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const quota = useAuthStore((s) => s.quota);
  const logout = useAuthStore((s) => s.logout);
  const updateUser = useAuthStore((s) => s.updateUser);

  // Demo fallback user
  const effectiveUser = {
    user_id: user?.user_id || "user-demo-8809",
    display_name: user?.display_name || "云途探索家",
    email_login_enabled: user?.email_login_enabled ?? true,
    masked_email: user?.masked_email || "traveler***@gmail.com",
    linux_do_username: user?.linux_do_username || "NeoTraveler",
    display_name_review_required: user?.display_name_review_required ?? false,
    display_name_change_available_at: user?.display_name_change_available_at ?? null,
  };

  const [activeTab, setActiveTab] = useState<"general" | "quota" | "security">("general");
  const [isEditingName, setIsEditingName] = useState(false);
  const [nameInput, setNameInput] = useState(effectiveUser.display_name);
  const [savingName, setSavingName] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [syncStatus, setSyncStatus] = useState<string>("云端已实时同步");

  // 动态真实额度流水
  const [quotaLogs, setQuotaLogs] = useState<QuotaLog[]>(DEFAULT_QUOTA_LOGS);

  // Travel preferences default state
  const [defaultPace, setDefaultPace] = useState("moderate");
  const [defaultGroup, setDefaultGroup] = useState("2");

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => {
      setToastMessage(null);
    }, 2500);
  };

  // 读取真实行程并转换为真实流水
  useEffect(() => {
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

          // 补充公测初始赠送
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
        /* fallback to default mock */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const remainingQuota = quota?.remaining ?? 8;
  const limitQuota = quota?.limit ?? 10;
  const quotaPercent = Math.round((remainingQuota / Math.max(1, limitQuota)) * 100);

  const handleSaveName = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = nameInput.trim();
    if (!trimmed || trimmed.length < 2 || trimmed.length > 24) {
      setNameError("显示名称需在 2~24 个字符之间");
      return;
    }
    setSavingName(true);
    setNameError(null);
    try {
      if (user) {
        const res = await updateDisplayName(trimmed);
        if (res.ok && res.user) {
          updateUser(res.user);
        }
      }
      setIsEditingName(false);
      showToast("✓ 显示名称已成功更新");
    } catch (err: unknown) {
      if (err instanceof ApiRequestError) {
        setNameError(err.message);
      } else {
        setNameError("修改失败，请重试");
      }
    } finally {
      setSavingName(false);
    }
  };

  const handleUpdatePref = (type: "pace" | "group", val: string) => {
    if (type === "pace") setDefaultPace(val);
    if (type === "group") setDefaultGroup(val);
    setSyncStatus("同步中...");
    setTimeout(() => {
      setSyncStatus("云端已实时同步");
      showToast("✓ 默认出行习惯已保存并同步");
    }, 400);
  };

  return (
    <div className="min-h-screen w-full bg-[#f8f7f4] font-body text-gray-900 pb-28">
      {/* Toast 反馈胶囊 */}
      {toastMessage && (
        <div className="fixed top-6 left-1/2 -translate-x-1/2 z-50 rounded-full bg-gray-900/90 text-white text-xs font-semibold px-4 py-2 shadow-xl backdrop-blur-md flex items-center gap-2 border border-white/20 animate-in fade-in slide-in-from-top-4 duration-200">
          <i className="fa-solid fa-circle-check text-emerald-400 text-sm" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* 1. 极简现代 Header */}
      <header className="border-b border-sand-200/80 bg-white/80 px-6 py-4 backdrop-blur-md sticky top-0 z-30">
        <div className="mx-auto max-w-6xl flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => navigate("/")}
              className="flex h-8 w-8 items-center justify-center rounded-lg border border-sand-200 text-gray-500 hover:text-gray-900 hover:bg-sand-50 transition-colors"
              title="返回首页"
            >
              <i className="fa-solid fa-chevron-left text-xs" />
            </button>
            <div className="flex items-center gap-2">
              <span className="font-display text-base font-bold text-gray-900 tracking-tight">
                账号与个人设置
              </span>
              <span className="rounded-full bg-sand-200/80 px-2 py-0.5 text-[10px] font-bold text-gray-600">
                Demo · 极简中枢
              </span>
            </div>
          </div>

          <div className="flex items-center gap-4 text-xs">
            <span className="text-gray-400 font-mono">UID: {effectiveUser.user_id?.slice(0, 12) || "YT-8809"}</span>
            <button
              type="button"
              onClick={() => logout().then(() => navigate("/"))}
              className="font-medium text-gray-500 hover:text-red-600 transition-colors"
            >
              退出登录
            </button>
          </div>
        </div>
      </header>

      {/* 2. 核心双栏工坊 */}
      <main className="mx-auto max-w-6xl px-4 sm:px-6 pt-8">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-8 items-start">
          {/* 左栏：身份名片与设置导航 */}
          <aside className="md:col-span-4 space-y-4 md:sticky md:top-24">
            {/* 探索家名片卡 */}
            <div className="rounded-2xl border border-sand-200 bg-white p-6 shadow-2xs">
              <div className="flex items-center gap-4">
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-700 to-emerald-900 text-white font-display text-xl font-black shadow-inner">
                  {(effectiveUser.display_name || "云").slice(0, 1).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <h2 className="truncate font-display text-lg font-bold text-gray-900">
                      {effectiveUser.display_name || "云途探索家"}
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
                    <span>Linux.do 账号</span>
                  </span>
                  <span className="font-semibold text-gray-900">
                    @{effectiveUser.linux_do_username || "未关联"}
                  </span>
                </div>
                <div className="flex items-center justify-between text-gray-600">
                  <span className="flex items-center gap-1.5">
                    <i className="fa-solid fa-envelope text-gray-400 text-xs" />
                    <span>绑定安全邮箱</span>
                  </span>
                  <span className="font-mono text-gray-900">
                    {effectiveUser.masked_email || "未绑定"}
                  </span>
                </div>
              </div>

              {/* 额度快速状态 */}
              <div className="mt-4 rounded-xl bg-sand-50 p-3 text-xs border border-sand-200/60">
                <div className="flex items-center justify-between text-gray-700 mb-1.5">
                  <span className="font-medium">今日 AI 算力额度</span>
                  <span className="font-bold text-primary-700 font-mono">{remainingQuota} / {limitQuota} 次</span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-sand-200 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-primary-600 transition-all duration-300"
                    style={{ width: `${quotaPercent}%` }}
                  />
                </div>
              </div>
            </div>

            {/* 导航菜单 Tabs */}
            <nav className="rounded-2xl border border-sand-200 bg-white p-2 shadow-2xs space-y-1 text-xs font-semibold">
              {[
                { id: "general", label: "基本资料与身份", icon: "fa-user" },
                { id: "quota", label: "AI 算力与用量", icon: "fa-bolt" },
                { id: "security", label: "账号连接与安全", icon: "fa-shield-halved" },
              ].map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setActiveTab(t.id as typeof activeTab)}
                  className={`w-full flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl text-left transition-all ${
                    activeTab === t.id
                      ? "bg-primary-50 text-primary-900 font-bold"
                      : "text-gray-600 hover:bg-sand-50 hover:text-gray-900"
                  }`}
                >
                  <i className={`fa-solid ${t.icon} text-[11px] ${activeTab === t.id ? "text-primary-600" : "text-gray-400"}`} />
                  <span>{t.label}</span>
                </button>
              ))}
            </nav>
          </aside>

          {/* 右栏：设置工作台主面板 */}
          <section className="md:col-span-8 space-y-6">
            {/* Tab 1: 基本资料与身份 */}
            {activeTab === "general" && (
              <div className="space-y-6">
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
                        <label className="text-xs font-bold text-gray-700 block">
                          显示名称 (Display Name)
                        </label>
                        <span className="text-[11px] text-gray-400">
                          将在路书作者铭牌、分享海报中对外展示
                        </span>
                      </div>

                      {!isEditingName && (
                        <button
                          type="button"
                          onClick={() => {
                            setNameInput(effectiveUser.display_name);
                            setIsEditingName(true);
                          }}
                          className="rounded-xl border border-sand-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-sand-50 transition-colors self-start sm:self-auto"
                        >
                          修改名称
                        </button>
                      )}
                    </div>

                    {!isEditingName ? (
                      <div className="rounded-xl bg-sand-50 px-4 py-2.5 text-sm font-semibold text-gray-800 border border-sand-200/80">
                        {effectiveUser.display_name}
                      </div>
                    ) : (
                      <form onSubmit={handleSaveName} className="space-y-2">
                        <div className="flex gap-2">
                          <input
                            type="text"
                            value={nameInput}
                            onChange={(e) => {
                              setNameInput(e.target.value);
                              setNameError(null);
                            }}
                            autoFocus
                            className="flex-1 rounded-xl border border-primary-300 bg-white px-3.5 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary-400"
                          />
                          <button
                            type="submit"
                            disabled={savingName}
                            className="rounded-xl bg-primary-600 px-4 py-2 text-xs font-bold text-white hover:bg-primary-700 transition-colors"
                          >
                            {savingName ? "保存中..." : "保存"}
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
                          <p className="text-xs text-red-600">{nameError}</p>
                        )}
                        <p className="text-[11px] text-gray-400">
                          支持 2~24 个中文、英文、数字或下划线，修改后 30 天内不可再次修改。
                        </p>
                      </form>
                    )}
                  </div>
                </div>

                {/* 偏好默认值预设 + 同步状态指示灯 */}
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
              </div>
            )}

            {/* Tab 2: AI 算力与用量 + 动态真实流水 */}
            {activeTab === "quota" && (
              <div className="space-y-6">
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
                        <div className="flex items-baseline gap-2 mt-1">
                          <span className="font-display text-4xl font-black">{remainingQuota}</span>
                          <span className="text-xs text-primary-200">/ {limitQuota} 次可用</span>
                        </div>
                      </div>
                      <span className="rounded-full bg-white/10 px-3 py-1 text-xs font-bold text-emerald-300 border border-white/15">
                        公测特惠满格
                      </span>
                    </div>

                    {/* 点阵式算力指示槽 */}
                    <div className="grid grid-cols-10 gap-1.5 pt-2">
                      {Array.from({ length: 10 }).map((_, i) => (
                        <div
                          key={i}
                          className={`h-2.5 rounded-xs transition-all ${
                            i < remainingQuota ? "bg-emerald-400 shadow-xs" : "bg-white/10"
                          }`}
                        />
                      ))}
                    </div>
                  </div>

                  {/* 算力额度流水记录 (真实行程驱动) */}
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
              </div>
            )}

            {/* Tab 3: 账号连接与安全 */}
            {activeTab === "security" && (
              <div className="space-y-6">
                <div className="rounded-2xl border border-sand-200 bg-white p-6 shadow-2xs space-y-6">
                  <div>
                    <h3 className="font-display text-base font-bold text-gray-900">
                      互联身份管理
                    </h3>
                    <p className="text-xs text-gray-400 mt-0.5">
                      管理你的单点登录凭证与安全验证通道
                    </p>
                  </div>

                  <div className="border-t border-sand-100 pt-5 space-y-4">
                    {/* Linux.do */}
                    <div className="flex items-center justify-between p-4 rounded-xl border border-sand-200 bg-sand-50/40">
                      <div className="flex items-center gap-3">
                        <span className="text-2xl">🐧</span>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-bold text-gray-800">Linux.do 社区认证</span>
                            <span className="rounded-md bg-emerald-100 text-emerald-800 text-[10px] font-bold px-1.5 py-0.5">已连接</span>
                          </div>
                          <p className="text-xs text-gray-400 mt-0.5">@{effectiveUser.linux_do_username || "NeoTraveler"}</p>
                        </div>
                      </div>
                      <span className="text-xs font-semibold text-gray-400">主要身份</span>
                    </div>

                    {/* Email */}
                    <div className="flex items-center justify-between p-4 rounded-xl border border-sand-200 bg-sand-50/40">
                      <div className="flex items-center gap-3">
                        <span className="text-2xl">✉️</span>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-bold text-gray-800">安全验证邮箱</span>
                            <span className="rounded-md bg-emerald-100 text-emerald-800 text-[10px] font-bold px-1.5 py-0.5">已验证</span>
                          </div>
                          <p className="text-xs text-gray-400 font-mono mt-0.5">{effectiveUser.masked_email}</p>
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => showToast("换绑邮箱通道维护中")}
                        className="text-xs font-semibold text-primary-700 hover:text-primary-800"
                      >
                        修改邮箱
                      </button>
                    </div>
                  </div>
                </div>

                {/* 危险操作区 (保持极简) */}
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
                      onClick={() => showToast("公测保护状态中，暂不支持直接注销")}
                      className="rounded-xl border border-red-300 bg-white px-4 py-2 text-xs font-bold text-red-600 hover:bg-red-50 transition-colors shrink-0 self-start sm:self-auto"
                    >
                      注销账号
                    </button>
                  </div>
                </div>
              </div>
            )}
          </section>
        </div>
      </main>

      {/* Demo 方案切换悬浮条 */}
      <DemoSwitcher />
    </div>
  );
}
