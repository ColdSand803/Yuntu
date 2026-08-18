import { useState, useMemo, useEffect, useRef } from "react";
import { Link, useNavigate } from "react-router-dom";
import { DemoSwitcher } from "@/components/demo/DemoSwitcher";
import { UserMenu } from "@/components/layout/UserMenu";
import {
  useRotatingBackground,
  cityNameOfImage,
} from "@/components/input/RotatingBackground";
import { submitTrip, fetchHotPlaces, type HotPlace, ApiRequestError } from "@/services/api";
import { useTripStore } from "@/stores/tripStore";
import { useAuthStore } from "@/stores/authStore";
import { useTripTaskStore } from "@/stores/tripTaskStore";
import {
  savePendingSubmission,
  clearPendingSubmission,
} from "@/utils/pendingSubmission";
import type { TripFormData, MustIncludeItem, RequestedCommuteMode } from "@/types/form";

const SUPPORTED_CITIES = [
  { name: "杭州", tag: "烟雨江南 · 西子湖畔" },
  { name: "重庆", tag: "立体山城 · 赛博夜景" },
  { name: "成都", tag: "天府之国 · 慢享生活" },
  { name: "西安", tag: "十三朝古都 · 丝路起点" },
  { name: "北京", tag: "千年古都 · 皇家气韵" },
  { name: "上海", tag: "摩登海派 · 璀璨江景" },
  { name: "南京", tag: "六朝古都 · 金陵风雅" },
  { name: "长沙", tag: "星城烟火 · 时尚长歌" },
  { name: "青岛", tag: "红瓦绿树 · 碧海蓝天" },
  { name: "桂林", tag: "山水甲天下 · 漓江美景" },
  { name: "广州", tag: "岭南花城 · 珠江烟火" },
  { name: "武汉", tag: "江城相逢 · 湖光桥影" },
  { name: "苏州", tag: "园林水巷 · 吴韵江南" },
  { name: "厦门", tag: "鹭岛海风 · 闽南慢调" },
  { name: "昆明", tag: "四季春城 · 云南风物" },
  { name: "三亚", tag: "热带海岛 · 椰风海韵" },
];

const PREFERENCE_OPTIONS = [
  "自然风光", "文化历史", "美食", "亲子", "购物", "citywalk", "拍照", "夜景"
];

const COMMUTE_OPTIONS: { value: RequestedCommuteMode; label: string; icon: string }[] = [
  { value: "driving", label: "打车 / 驾车", icon: "fa-car" },
  { value: "transit", label: "公共交通", icon: "fa-bus" },
  { value: "cycling", label: "骑行优先", icon: "fa-bicycle" },
];

const PACE_OPTIONS = [
  { id: "relaxed", tag: "轻松", label: "轻松悠闲", desc: "少走路、慢节奏探索" },
  { id: "moderate", tag: "适中", label: "适中充实", desc: "经典地标全景体验" },
  { id: "tight", tag: "紧凑", label: "特种兵打卡", desc: "高密度、极致高效" },
];

const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];

function isoDateAfter(daysFromNow: number): string {
  const d = new Date();
  d.setDate(d.getDate() + daysFromNow);
  return d.toISOString().slice(0, 10);
}

function parseDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function toISO(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

/** 生成某月日历网格 */
function generateMonthGrid(year: number, month: number): Date[] {
  const first = new Date(year, month, 1);
  const offset = (first.getDay() + 6) % 7;
  const gridStart = new Date(year, month, 1 - offset);
  return Array.from({ length: 35 }, (_, i) => {
    return new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + i);
  });
}

/** 100% 自研高定范围日历组件 */
function CustomCalendarRange({
  startDate,
  endDate,
  onRangeChange,
}: {
  startDate: string;
  endDate: string;
  onRangeChange: (start: string, end: string) => void;
}) {
  const [viewDate, setViewDate] = useState(() => parseDate(startDate));
  const [pendingStart, setPendingStart] = useState<string | null>(null);
  const [hoverIso, setHoverIso] = useState<string | null>(null);

  const today = useMemo(() => startOfDay(new Date()), []);
  const year = viewDate.getFullYear();
  const month = viewDate.getMonth();

  const grid = useMemo(() => generateMonthGrid(year, month), [year, month]);

  const handlePrevMonth = () => {
    setViewDate(new Date(year, month - 1, 1));
  };

  const handleNextMonth = () => {
    setViewDate(new Date(year, month + 1, 1));
  };

  const handleDayClick = (dayIso: string) => {
    if (!pendingStart) {
      setPendingStart(dayIso);
    } else {
      const s = parseDate(pendingStart);
      const e = parseDate(dayIso);
      const diff = Math.round((e.getTime() - s.getTime()) / 86400000);

      if (diff >= 0 && diff <= 6) {
        onRangeChange(pendingStart, dayIso);
        setPendingStart(null);
        setHoverIso(null);
      } else if (diff < 0) {
        setPendingStart(dayIso);
      } else {
        const maxEnd = new Date(s);
        maxEnd.setDate(maxEnd.getDate() + 6);
        onRangeChange(pendingStart, toISO(maxEnd));
        setPendingStart(null);
        setHoverIso(null);
      }
    }
  };

  const effectiveStart = pendingStart || startDate;
  const effectiveEnd = pendingStart ? (hoverIso && hoverIso >= pendingStart ? hoverIso : pendingStart) : endDate;

  return (
    <div className="space-y-3">
      {/* 月份导航 */}
      <div className="flex items-center justify-between px-1">
        <button
          type="button"
          onClick={handlePrevMonth}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-sand-200 text-gray-600 hover:bg-sand-100 hover:text-gray-900 transition-colors"
          title="上一月"
        >
          <i className="fa-solid fa-chevron-left text-xs" />
        </button>

        <span className="font-display text-sm font-bold text-gray-900">
          {year}年 {month + 1}月
        </span>

        <button
          type="button"
          onClick={handleNextMonth}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-sand-200 text-gray-600 hover:bg-sand-100 hover:text-gray-900 transition-colors"
          title="下一月"
        >
          <i className="fa-solid fa-chevron-right text-xs" />
        </button>
      </div>

      {/* 星期表头 */}
      <div className="grid grid-cols-7 gap-1 text-center text-[11px] font-bold text-gray-400">
        {WEEKDAYS.map((w) => (
          <div key={w} className="py-1">
            {w}
          </div>
        ))}
      </div>

      {/* 日期网格 */}
      <div className="grid grid-cols-7 gap-y-1 gap-x-0.5">
        {grid.map((d) => {
          const iso = toISO(d);
          const isCurrentMonth = d.getMonth() === month;
          const isPast = d < today;
          const isStart = iso === effectiveStart;
          const isEnd = iso === effectiveEnd;
          const inRange = iso >= effectiveStart && iso <= effectiveEnd;

          let isOver7Days = false;
          if (pendingStart) {
            const s = parseDate(pendingStart);
            const diff = Math.round((d.getTime() - s.getTime()) / 86400000);
            if (diff > 6) isOver7Days = true;
          }

          let cellClass = "h-9 w-full flex items-center justify-center text-xs font-semibold transition-all relative ";

          if (isPast) {
            cellClass += "text-gray-300 cursor-not-allowed ";
          } else if (!isCurrentMonth) {
            cellClass += "text-gray-300 hover:text-gray-500 ";
          } else if (isStart || isEnd) {
            cellClass += "bg-primary-700 text-white font-black z-10 ";
            if (isStart && isEnd) {
              cellClass += "rounded-xl ";
            } else if (isStart) {
              cellClass += "rounded-l-xl ";
            } else if (isEnd) {
              cellClass += "rounded-r-xl ";
            }
          } else if (inRange) {
            cellClass += "bg-primary-100/80 text-primary-900 ";
          } else if (isOver7Days) {
            cellClass += "text-gray-400 hover:bg-red-50 hover:text-red-600 ";
          } else {
            cellClass += "text-gray-800 hover:bg-sand-100 rounded-lg ";
          }

          return (
            <button
              key={iso}
              type="button"
              disabled={isPast}
              onClick={() => handleDayClick(iso)}
              onMouseEnter={() => {
                if (pendingStart && iso >= pendingStart) {
                  setHoverIso(iso);
                }
              }}
              className={cellClass}
            >
              <span>{d.getDate()}</span>
              {iso === toISO(today) && !isStart && !isEnd && (
                <span className="absolute bottom-1 h-1 w-1 rounded-full bg-primary-600" />
              )}
            </button>
          );
        })}
      </div>

      <div className="flex items-center justify-between pt-2 text-[11px] text-gray-500 border-t border-sand-100">
        <span>
          {pendingStart ? "请点击返回日期（最多7天）" : "点击日期可重选出发时间"}
        </span>
        <span className="font-semibold text-primary-700">
          已选：{startDate.slice(5)} ~ {endDate.slice(5)}
        </span>
      </div>
    </div>
  );
}

export default function DemoInputCapsule() {
  const navigate = useNavigate();
  const setFormData = useTripStore((s) => s.setFormData);
  const clearResult = useTripStore((s) => s.clearResult);
  const authStatus = useAuthStore((s) => s.status);
  const user = useAuthStore((s) => s.user);
  const quota = useAuthStore((s) => s.quota);
  const activeTrip = useAuthStore((s) => s.activeTrip);
  const refreshMe = useAuthStore((s) => s.refreshMe);

  // 恢复历史暂存
  const stored = useMemo(() => useTripStore.getState().formData, []);
  const storedPrefs = stored?.preferences ?? null;

  // 1. 目的地与出发地
  const [fromCity, setFromCity] = useState(stored?.from_city ?? "");
  const [city, setCity] = useState(stored?.to_city || "重庆");

  // 2. 时间范围 (出发日期 & 返回日期，最多7天)
  const [startDate, setStartDate] = useState(() => stored?.start_date || isoDateAfter(1));
  const [endDate, setEndDate] = useState(() => stored?.end_date || isoDateAfter(3));

  // 3. 人数、节奏与偏好
  const [people, setPeople] = useState(stored?.people_count ?? 2);
  const [paceTag, setPaceTag] = useState<string>(() => {
    if (storedPrefs?.includes("轻松")) return "轻松";
    if (storedPrefs?.includes("紧凑")) return "紧凑";
    return "适中";
  });
  const [preferences, setPreferences] = useState<string[]>(
    storedPrefs ? storedPrefs.filter((p) => !["轻松", "适中", "紧凑"].includes(p)) : ["美食", "citywalk", "夜景"]
  );

  // 4. 必去地点与出行方式
  const [mustInclude, setMustInclude] = useState<MustIncludeItem[]>(stored?.must_include ?? []);
  const [mustIncludeInput, setMustIncludeInput] = useState("");
  const [hotPlaces, setHotPlaces] = useState<HotPlace[]>([]);
  const [commuteMode, setCommuteMode] = useState<RequestedCommuteMode>(
    stored?.commute_mode === "transit" || stored?.commute_mode === "cycling"
      ? stored.commute_mode
      : "driving"
  );
  const [accommodationName, setAccommodationName] = useState(stored?.accommodation?.name ?? "");
  const [notes, setNotes] = useState(stored?.notes ?? "");

  // 控制面板展开项: null | 'city' | 'date' | 'pace' | 'places'
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const panelRef = useRef<HTMLDivElement>(null);

  // 加载当前城市的官方热门 POI 推荐
  useEffect(() => {
    let cancelled = false;
    fetchHotPlaces(city)
      .then((places) => {
        if (!cancelled && Array.isArray(places)) {
          setHotPlaces(places);
        }
      })
      .catch(() => setHotPlaces([]));
    return () => {
      cancelled = true;
    };
  }, [city]);

  // 实时匹配的 POI 搜索联想列表 (Autocomplete)
  const matchedHotPlaces = useMemo(() => {
    const query = mustIncludeInput.trim();
    if (!query) return [];
    return hotPlaces.filter(
      (hp) =>
        hp.name.toLowerCase().includes(query.toLowerCase()) &&
        !mustInclude.some((m) => m.name === hp.name)
    );
  }, [mustIncludeInput, hotPlaces, mustInclude]);

  const { current: bgImage, incoming: bgIncoming } = useRotatingBackground([city]);
  const polaroidCity = cityNameOfImage(bgImage);
  const displayCity = polaroidCity || city;
  const currentCityMeta = SUPPORTED_CITIES.find((c) => c.name === city);

  // 计算天数
  const days = useMemo(() => {
    const s = parseDate(startDate);
    const e = parseDate(endDate);
    const diff = Math.round((e.getTime() - s.getTime()) / 86400000);
    return diff >= 0 ? diff + 1 : 1;
  }, [startDate, endDate]);

  const isDaysOverLimit = days > 7;

  // 点击空白区域关闭浮动面板
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setActiveTab(null);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const togglePreference = (pref: string) => {
    setPreferences((prev) => {
      const next = prev.includes(pref) ? prev.filter((p) => p !== pref) : [...prev, pref];
      // 亲子与人数智能联动
      if (pref === "亲子" && !prev.includes("亲子") && people < 2) {
        setPeople(2);
      }
      return next;
    });
  };

  const handleAddMustInclude = (name: string, placeId?: number) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    if (mustInclude.length >= 5) return;
    if (mustInclude.some((m) => m.name === trimmed)) return;

    setMustInclude((prev) => [
      ...prev,
      {
        name: trimmed,
        ...(placeId ? { place_id: placeId } : {}),
      },
    ]);
    setMustIncludeInput("");
  };

  const handleRemoveMustInclude = (idx: number) => {
    setMustInclude((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleSubmit = async () => {
    if (submitting) return;

    if (isDaysOverLimit) {
      setSubmitError("单次行程最多支持规划 7 天，请调整返回日期");
      return;
    }

    const formData: TripFormData = {
      from_city: fromCity.trim() || undefined,
      to_city: city,
      start_date: startDate,
      end_date: endDate,
      days: Math.min(7, Math.max(1, days)),
      people_count: people,
      preferences: [...preferences, paceTag],
      avoid: [],
      notes: notes.trim(),
      ...(mustInclude.length > 0 && { must_include: mustInclude }),
      ...(commuteMode !== "driving" && { commute_mode: commuteMode }),
      ...(accommodationName.trim() && { accommodation: { name: accommodationName.trim() } }),
    };

    setFormData(formData);
    clearResult();

    // 游客态拦截
    if (authStatus !== "authenticated") {
      savePendingSubmission(formData);
      navigate("/login?returnTo=/");
      return;
    }

    // 额度校验
    if (quota && quota.remaining <= 0) {
      const limitSuffix = typeof quota.limit === "number" ? ` (0/${quota.limit})` : "";
      setSubmitError(`公测免费额度已耗尽${limitSuffix}，无法创建新行程`);
      return;
    }

    // 活动任务拦截
    if (activeTrip) {
      setSubmitError("你已有正在生成的行程任务，请等待完成");
      navigate(`/planning/${activeTrip.job_id}`);
      return;
    }

    const pending = savePendingSubmission(formData);
    setSubmitting(true);
    setSubmitError(null);

    try {
      const res = await submitTrip(formData, pending.request_id);
      useTripTaskStore.getState().addOrUpdateTask({
        jobId: res.job_id,
        requestId: pending.request_id,
        destination: formData.to_city,
        startedAt: Date.now(),
        status: "pending",
        notificationState: "none",
      });
      clearPendingSubmission();
      await refreshMe();
      navigate(`/planning/${res.job_id}`);
    } catch (err: unknown) {
      if (err instanceof ApiRequestError) {
        if (err.status === 409 && err.code === "ACTIVE_TRIP_EXISTS") {
          const refreshed = await refreshMe();
          if (refreshed) {
            const latestTrip = useAuthStore.getState().activeTrip;
            if (latestTrip?.job_id) {
              clearPendingSubmission();
              navigate(`/planning/${latestTrip.job_id}`);
              return;
            }
          }
        }
        setSubmitError(err.message);
      } else {
        setSubmitError("提交失败，请检查网络后重试");
      }
      setSubmitting(false);
    }
  };

  return (
    <div className="relative min-h-screen w-full overflow-x-hidden overflow-y-auto bg-gray-950 font-body text-white">
      {/* 1. 全屏沉浸风光巨幕 */}
      <div
        className="fixed inset-0 bg-cover bg-center transition-all duration-1000 scale-105 pointer-events-none"
        style={{ backgroundImage: `url('${bgImage}')` }}
      />
      {bgIncoming && (
        <div
          className="fixed inset-0 animate-bg-fade-in bg-cover bg-center pointer-events-none"
          style={{ backgroundImage: `url('${bgIncoming}')` }}
        />
      )}
      <div className="fixed inset-0 bg-gradient-to-t from-black/85 via-black/40 to-black/60 pointer-events-none" />

      {/* 2. 顶栏标识与真实登录态 */}
      <header className="relative z-30 flex items-center justify-between px-5 py-4 sm:px-10 lg:px-12 backdrop-blur-xs">
        <div className="flex items-center space-x-6">
          <Link to="/" className="flex items-center space-x-2">
            <img src="/logo.svg" alt="云途 YunTu" className="h-8 w-8" />
            <span className="text-xl font-black tracking-tight text-white">
              云途 <span className="font-light text-emerald-400 text-sm">YunTu</span>
            </span>
          </Link>

          {authStatus === "authenticated" && (
            <Link
              to="/demo/history"
              className="hidden sm:inline-flex items-center gap-1.5 text-xs font-semibold text-white/80 hover:text-white transition-colors bg-white/10 px-3 py-1.5 rounded-lg backdrop-blur-md border border-white/10"
            >
              <i className="fa-solid fa-map-location-dot text-emerald-400" />
              <span>我的行程</span>
            </Link>
          )}
        </div>

        {/* 右侧：登录状态 / 额度 / 用户菜单 */}
        <div className="flex items-center space-x-4">
          {authStatus === "authenticated" && user ? (
            <div className="flex items-center gap-3">
              {quota && (
                <Link
                  to="/demo/profile"
                  className="hidden sm:flex items-center gap-1.5 rounded-full bg-emerald-950/70 border border-emerald-500/40 px-3 py-1 text-xs font-bold text-emerald-300 backdrop-blur-md"
                  title="剩余可用 AI 定制额度"
                >
                  <i className="fa-solid fa-bolt text-[11px]" />
                  <span>{quota.remaining} / {quota.limit} 次</span>
                </Link>
              )}

              <UserMenu />
            </div>
          ) : (
            <Link
              to="/login?returnTo=/"
              className="rounded-xl bg-white/20 hover:bg-white/30 border border-white/30 px-4 py-1.5 text-xs font-bold text-white backdrop-blur-md transition-all shadow-sm"
            >
              登录 / 注册
            </Link>
          )}
        </div>
      </header>

      {/* 3. 中央核心区域：大标题 + 4段式智能悬浮胶囊 */}
      <main className="relative z-20 mx-auto flex min-h-[calc(100vh-5rem)] max-w-6xl flex-col items-center justify-center px-4 py-6 text-center pb-28 sm:pb-24">
        {/* 灵感引言 */}
        <div className="mb-8 space-y-2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-950/60 px-3.5 py-1 text-xs font-semibold text-emerald-300 backdrop-blur-md border border-emerald-500/30 shadow-sm">
            <i className="fa-solid fa-sparkles text-[10px]" />
            100% 真实权威 POI 路线定制
          </span>
          <h1 className="font-display text-4xl font-black tracking-tight sm:text-6xl drop-shadow-xl text-balance">
            世界那么大，今天想去哪？
          </h1>
          <p className="text-xs sm:text-sm font-normal text-white/80 max-w-lg mx-auto">
            一键锁定官方名城，自由定制出发时间、必去地点、交通方式与专属节奏
          </p>
        </div>

        {/* 4 段式悬浮胶囊指挥台 (The 4-Segment Capsule Deck) */}
        <div ref={panelRef} className="relative w-full max-w-4xl">
          <div className="flex flex-col lg:flex-row items-center rounded-2xl lg:rounded-full bg-white/95 p-2 text-gray-800 shadow-[0_20px_50px_rgba(0,0,0,0.6)] backdrop-blur-xl border border-white/40 gap-1 lg:gap-0">
            {/* 1. 出发地 & 目的地 */}
            <button
              type="button"
              onClick={() => setActiveTab(activeTab === "city" ? null : "city")}
              className={`flex flex-1 items-center gap-2.5 w-full lg:w-auto px-3.5 py-2.5 rounded-xl lg:rounded-full text-left transition-all ${
                activeTab === "city" ? "bg-primary-50 ring-2 ring-primary-400" : "hover:bg-sand-100/70"
              }`}
            >
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary-100 text-primary-700">
                <i className="fa-solid fa-location-dot text-sm" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400">
                  {fromCity ? "出发 ➔ 目的地" : "目的地城市"}
                </p>
                <p className="truncate text-sm font-bold text-gray-900">
                  {fromCity ? (
                    <>
                      <span>{fromCity}</span>
                      <span className="mx-1 text-gray-400 font-normal">➔</span>
                      <span>{city}</span>
                    </>
                  ) : (
                    city
                  )}
                </p>
              </div>
            </button>

            <div className="hidden lg:block h-7 w-px bg-gray-200" aria-hidden="true" />

            {/* 2. 出发与返回日期 */}
            <button
              type="button"
              onClick={() => setActiveTab(activeTab === "date" ? null : "date")}
              className={`flex flex-1.1 items-center gap-2.5 w-full lg:w-auto px-3.5 py-2.5 rounded-xl lg:rounded-full text-left transition-all ${
                activeTab === "date" ? "bg-primary-50 ring-2 ring-primary-400" : "hover:bg-sand-100/70"
              }`}
            >
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-700">
                <i className="fa-regular fa-calendar-days text-sm" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400">出行日期 (最多7天)</p>
                <p className="truncate text-xs sm:text-sm font-bold text-gray-900">
                  {startDate.slice(5)} ~ {endDate.slice(5)} · {days}天
                </p>
              </div>
            </button>

            <div className="hidden lg:block h-7 w-px bg-gray-200" aria-hidden="true" />

            {/* 3. 节奏与同行 */}
            <button
              type="button"
              onClick={() => setActiveTab(activeTab === "pace" ? null : "pace")}
              className={`flex flex-1.1 items-center gap-2.5 w-full lg:w-auto px-3.5 py-2.5 rounded-xl lg:rounded-full text-left transition-all ${
                activeTab === "pace" ? "bg-primary-50 ring-2 ring-primary-400" : "hover:bg-sand-100/70"
              }`}
            >
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-emerald-100 text-emerald-700">
                <i className="fa-solid fa-gauge-high text-sm" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400">节奏与同行</p>
                <p className="truncate text-xs sm:text-sm font-bold text-gray-900">
                  {people === 1 ? "1人 · 独自漫游" : people === 2 ? "2人 · 双人同游" : people <= 4 ? `${people}人 · 家庭亲子` : `${people}人 · 多人结伴`} · {paceTag}
                </p>
              </div>
            </button>

            <div className="hidden lg:block h-7 w-px bg-gray-200" aria-hidden="true" />

            {/* 4. 必去与出行方式 */}
            <button
              type="button"
              onClick={() => setActiveTab(activeTab === "places" ? null : "places")}
              className={`flex flex-1.1 items-center gap-2.5 w-full lg:w-auto px-3.5 py-2.5 rounded-xl lg:rounded-full text-left transition-all ${
                activeTab === "places" ? "bg-primary-50 ring-2 ring-primary-400" : "hover:bg-sand-100/70"
              }`}
            >
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-sky-100 text-sky-700">
                <i className="fa-solid fa-map-pin text-sm" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400">必去与出行方式</p>
                <p className="truncate text-xs sm:text-sm font-bold text-gray-900">
                  {commuteMode === "transit" ? "公共交通" : commuteMode === "cycling" ? "骑行优先" : "打车出行"}
                  {mustInclude.length > 0 ? ` · 必去 ${mustInclude.length} 处` : " · 自由编排"}
                </p>
              </div>
            </button>

            {/* 提交行动按钮 */}
            <button
              type="button"
              onClick={handleSubmit}
              disabled={submitting}
              className="mt-2 lg:mt-0 lg:ml-2 flex w-full lg:w-auto h-12 items-center justify-center gap-2 rounded-xl lg:rounded-full bg-gradient-to-r from-accent-500 to-orange-500 px-6 text-sm font-bold text-white shadow-md shadow-accent-500/25 hover:scale-[1.03] active:scale-95 transition-all shrink-0"
            >
              {submitting ? (
                <>
                  <i className="fa-solid fa-circle-notch animate-spin" />
                  <span>定制中...</span>
                </>
              ) : (
                <>
                  <i className="fa-solid fa-paper-plane text-xs" />
                  <span>帮我排行程</span>
                </>
              )}
            </button>
          </div>

          {/* 错误提示 */}
          {submitError && (
            <div className="mt-3 rounded-xl bg-red-950/80 border border-red-500/50 p-2.5 text-xs text-red-200 backdrop-blur-md animate-in fade-in">
              <i className="fa-solid fa-circle-exclamation mr-1.5 text-red-400" />
              {submitError}
            </div>
          )}

          {/* 下拉面板 1: 权威城市选择 (16 座真数据名城) & 出发城市 */}
          {activeTab === "city" && (
            <div className="absolute left-0 right-0 top-full mt-3 z-40 rounded-2xl bg-white/95 p-5 text-gray-900 shadow-2xl backdrop-blur-xl border border-sand-200 text-left animate-in fade-in zoom-in-95 duration-150 max-h-[70vh] overflow-y-auto custom-scrollbar space-y-4">
              {/* 出发地设置 (选填 · 往返大交通班次规划) */}
              <div className="rounded-xl bg-sand-50/90 p-3.5 border border-sand-200/80">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold text-gray-700 flex items-center gap-1.5">
                    <i className="fa-solid fa-plane-departure text-primary-600 text-xs" />
                    出发城市（选填 · 将为您推荐往返高铁/航班方案）
                  </span>
                  {fromCity && (
                    <button
                      type="button"
                      onClick={() => setFromCity("")}
                      className="text-[10px] text-gray-400 hover:text-red-500 transition-colors"
                    >
                      清空出发地
                    </button>
                  )}
                </div>

                <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                  <div className="relative flex-1">
                    <input
                      type="text"
                      value={fromCity}
                      onChange={(e) => setFromCity(e.target.value.slice(0, 10))}
                      placeholder="输入出发城市，如：成都、北京、上海..."
                      className="w-full rounded-lg border border-sand-300 bg-white px-3 py-1.5 text-xs text-gray-800 focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-100"
                    />
                  </div>
                  <div className="flex flex-wrap items-center gap-1">
                    <span className="text-[10px] text-gray-400 mr-0.5">常用:</span>
                    {["北京", "上海", "广州", "深圳", "成都", "武汉", "杭州", "南京", "西安", "重庆"].map((fc) => (
                      <button
                        key={fc}
                        type="button"
                        onClick={() => setFromCity(fromCity === fc ? "" : fc)}
                        className={`px-2 py-1 rounded-md text-[11px] font-medium transition-colors ${
                          fromCity === fc
                            ? "bg-primary-600 text-white font-bold"
                            : "bg-white border border-sand-200 text-gray-600 hover:bg-sand-100"
                        }`}
                      >
                        {fc}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* 目的地选择 */}
              <div>
                <div className="flex items-center justify-between mb-2.5">
                  <span className="text-xs font-bold text-gray-700 flex items-center gap-1.5">
                    <i className="fa-solid fa-location-dot text-emerald-600 text-xs" />
                    目的地城市（必选 · 共 {SUPPORTED_CITIES.length} 座官方权威名城）
                  </span>
                  <span className="text-[11px] text-emerald-600 font-semibold">
                    ✓ 100% 真实景区覆盖
                  </span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                  {SUPPORTED_CITIES.map((c) => (
                    <button
                      key={c.name}
                      type="button"
                      onClick={() => {
                        setCity(c.name);
                        setMustInclude([]); // 切换城市清空必去
                        setActiveTab("date");
                      }}
                      className={`flex flex-col p-2.5 rounded-xl border text-left transition-all ${
                        city === c.name
                          ? "bg-primary-600 text-white border-primary-600 shadow-md font-bold"
                          : "bg-white border-sand-200 text-gray-800 hover:border-primary-400 hover:bg-sand-50"
                      }`}
                    >
                      <span className="text-sm font-black">{c.name}</span>
                      <span className={`text-[10px] truncate mt-0.5 ${city === c.name ? "text-primary-100" : "text-gray-400"}`}>
                        {c.tag}
                      </span>
                    </button>
                  ))}
                </div>
              </div>

              {/* 底部引导下一步按钮 */}
              <div className="text-right pt-2 border-t border-sand-200">
                <button
                  type="button"
                  onClick={() => setActiveTab("date")}
                  className="text-xs font-bold text-primary-700 hover:underline"
                >
                  下一步：设置出行日期 →
                </button>
              </div>
            </div>
          )}

          {/* 下拉面板 2: 100% 自定义高定交互日历 */}
          {activeTab === "date" && (
            <div className="absolute left-0 right-0 top-full mt-3 z-40 rounded-2xl bg-white/95 p-6 text-gray-900 shadow-2xl backdrop-blur-xl border border-sand-200 text-left animate-in fade-in zoom-in-95 duration-150 space-y-4 max-h-[65vh] overflow-y-auto custom-scrollbar">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-xs font-bold text-gray-400 uppercase tracking-wider block">
                    选择出发与返回日期
                  </span>
                  <span className="text-xs text-gray-500">
                    单次行程规划最多支持 7 天
                  </span>
                </div>
                <div className="text-right">
                  <span className={`text-sm font-black ${isDaysOverLimit ? "text-red-600" : "text-primary-700"}`}>
                    共 {days} 天 {Math.max(1, days - 1)} 晚
                  </span>
                </div>
              </div>

              {/* 嵌入高定交互日历 */}
              <div className="rounded-2xl border border-sand-200 bg-white p-4 shadow-2xs">
                <CustomCalendarRange
                  startDate={startDate}
                  endDate={endDate}
                  onRangeChange={(s, e) => {
                    setStartDate(s);
                    setEndDate(e);
                  }}
                />
              </div>

              {/* 快捷天数辅助 */}
              <div className="flex items-center justify-between text-xs pt-1">
                <span className="text-gray-400">常用行程跨度：</span>
                <div className="flex gap-1.5">
                  {[2, 3, 4, 5, 7].map((d) => (
                    <button
                      key={d}
                      type="button"
                      onClick={() => {
                        const s = parseDate(startDate);
                        s.setDate(s.getDate() + d - 1);
                        setEndDate(toISO(s));
                      }}
                      className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-colors ${
                        days === d ? "bg-primary-600 text-white" : "bg-sand-100 text-gray-700 hover:bg-sand-200"
                      }`}
                    >
                      {d}天
                    </button>
                  ))}
                </div>
              </div>

              <div className="text-right pt-2 border-t border-sand-200">
                <button
                  type="button"
                  onClick={() => setActiveTab("pace")}
                  className="text-xs font-bold text-primary-700 hover:underline"
                >
                  下一步：设置节奏与偏好 →
                </button>
              </div>
            </div>
          )}

          {/* 下拉面板 3: 节奏偏好与同行人数 */}
          {activeTab === "pace" && (
            <div className="absolute left-0 right-0 top-full mt-3 z-40 rounded-2xl bg-white/95 p-5 text-gray-900 shadow-2xl backdrop-blur-xl border border-sand-200 text-left animate-in fade-in zoom-in-95 duration-150 space-y-4 max-h-[65vh] overflow-y-auto custom-scrollbar">
              {/* 1. 行程节奏 (轻松/适中/紧凑) */}
              <div>
                <span className="text-xs font-bold text-gray-400 uppercase tracking-wider block mb-2">
                  行程节奏偏好
                </span>
                <div className="grid grid-cols-3 gap-2">
                  {PACE_OPTIONS.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => setPaceTag(p.tag)}
                      className={`p-3 rounded-xl border text-left transition-all ${
                        paceTag === p.tag
                          ? "bg-primary-50 border-primary-500 text-primary-900 ring-2 ring-primary-300 font-bold"
                          : "bg-white border-sand-200 text-gray-700 hover:bg-sand-50"
                      }`}
                    >
                      <div className="text-sm font-bold">{p.label}</div>
                      <div className="text-[10px] text-gray-400 mt-0.5">{p.desc}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* 2. 同行人数与出行场景 */}
              <div className="space-y-2.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-gray-400 uppercase tracking-wider block">
                    同行人数与出行场景
                  </span>
                  {/* 精工微步进器 */}
                  <div className="flex items-center gap-2 rounded-xl bg-sand-100/80 p-1 border border-sand-200">
                    <button
                      type="button"
                      disabled={people <= 1}
                      onClick={() => setPeople((p) => Math.max(1, p - 1))}
                      className="flex h-7 w-7 items-center justify-center rounded-lg bg-white text-gray-700 shadow-2xs hover:bg-sand-200 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                      title="减少人数"
                    >
                      <i className="fa-solid fa-minus text-[10px]" />
                    </button>

                    <span className="font-display font-black text-xs px-2 text-gray-900 min-w-[3.5rem] text-center">
                      {people} 位同行
                    </span>

                    <button
                      type="button"
                      disabled={people >= 20}
                      onClick={() => setPeople((p) => Math.min(20, p + 1))}
                      className="flex h-7 w-7 items-center justify-center rounded-lg bg-white text-gray-700 shadow-2xs hover:bg-sand-200 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                      title="增加人数"
                    >
                      <i className="fa-solid fa-plus text-[10px]" />
                    </button>
                  </div>
                </div>

                {/* 4 大场景快捷卡 */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {[
                    { id: "solo", count: 1, label: "独自漫游", icon: "🎒", desc: "自由随性 慢调漫步" },
                    { id: "couple", count: 2, label: "双人同游", icon: "👫", desc: "情侣蜜友 经典打卡" },
                    { id: "family", count: 3, label: "家庭亲子", icon: "👨‍👩‍👧", desc: "兼顾老幼 舒适省心" },
                    { id: "group", count: 6, label: "多人结伴", icon: "👥", desc: "5人以上 聚会团建" },
                  ].map((sc) => {
                    const isMatched =
                      (sc.id === "solo" && people === 1) ||
                      (sc.id === "couple" && people === 2) ||
                      (sc.id === "family" && people >= 3 && people <= 4) ||
                      (sc.id === "group" && people >= 5);

                    return (
                      <button
                        key={sc.id}
                        type="button"
                        onClick={() => setPeople(sc.count)}
                        className={`flex flex-col p-2.5 rounded-xl border text-left transition-all ${
                          isMatched
                            ? "bg-primary-50 border-primary-500 text-primary-900 ring-2 ring-primary-300 font-bold"
                            : "bg-white border-sand-200 text-gray-700 hover:bg-sand-50"
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-base">{sc.icon}</span>
                          <span className="text-[10px] font-mono font-bold text-gray-400">
                            {sc.id === "family" ? "3~4人" : sc.id === "group" ? "5人+" : `${sc.count}人`}
                          </span>
                        </div>
                        <span className="text-xs font-bold mt-1 text-gray-900">{sc.label}</span>
                        <span className="text-[9px] text-gray-400 mt-0.5 truncate">{sc.desc}</span>
                      </button>
                    );
                  })}
                </div>

                {/* 智能贴心出行小贴士 */}
                <div className="rounded-xl bg-sand-100/70 p-2.5 text-[11px] text-gray-600 flex items-center gap-2 border border-sand-200/60">
                  <i className="fa-solid fa-lightbulb text-amber-500 text-xs shrink-0" />
                  <span>
                    {people === 1 && "已开启独自探索模式，AI 将优先推荐独立慢调咖啡馆与沉浸 Citywalk 路线。"}
                    {people === 2 && "已开启双人同行模式，AI 将智能推荐兼顾浪漫夜景、打卡大片与双人寻味。"}
                    {people >= 3 && people <= 4 && "已开启小家庭/密友模式，打车 1 辆刚刚好，路线将适度放缓步行强度。"}
                    {people >= 5 && `当前 ${people} 人同行，已标记多人团体模式，建议分乘多辆出租车或包车出行。`}
                  </span>
                </div>
              </div>

              {/* 3. 玩法偏好标签 */}
              <div className="border-t border-sand-200 pt-3">
                <span className="text-xs font-bold text-gray-400 uppercase tracking-wider block mb-2">
                  兴趣偏好标签（多选）
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {PREFERENCE_OPTIONS.map((pref) => {
                    const isSelected = preferences.includes(pref);
                    return (
                      <button
                        key={pref}
                        type="button"
                        onClick={() => togglePreference(pref)}
                        className={`px-3 py-1.5 rounded-xl text-xs font-medium transition-all ${
                          isSelected
                            ? "bg-primary-600 text-white font-bold shadow-xs"
                            : "bg-sand-100 text-gray-600 hover:bg-sand-200"
                        }`}
                      >
                        {pref}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="text-right pt-2 border-t border-sand-200">
                <button
                  type="button"
                  onClick={() => setActiveTab("places")}
                  className="text-xs font-bold text-primary-700 hover:underline"
                >
                  下一步：添加必去地点与出行方式 →
                </button>
              </div>
            </div>
          )}

          {/* 下拉面板 4: 必去地点与市内出行方式 + 实时 POI 联想 */}
          {activeTab === "places" && (
            <div className="absolute left-0 right-0 top-full mt-3 z-40 rounded-2xl bg-white/95 p-5 text-gray-900 shadow-2xl backdrop-blur-xl border border-sand-200 text-left animate-in fade-in zoom-in-95 duration-150 space-y-4 max-h-[65vh] overflow-y-auto custom-scrollbar">
              {/* 1. 市内出行方式 */}
              <div>
                <span className="text-xs font-bold text-gray-400 uppercase tracking-wider block mb-2">
                  市内出行方式
                </span>
                <div className="grid grid-cols-3 gap-2">
                  {COMMUTE_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setCommuteMode(opt.value)}
                      className={`flex items-center justify-center gap-2 py-2.5 px-3 rounded-xl border text-xs font-bold transition-all ${
                        commuteMode === opt.value
                          ? "bg-emerald-700 text-white border-emerald-700 shadow-sm"
                          : "bg-white border-sand-300 text-gray-700 hover:bg-sand-50"
                      }`}
                    >
                      <i className={`fa-solid ${opt.icon}`} />
                      <span>{opt.label}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* 2. 你的必去地点 + 实时搜索联想 */}
              <div className="border-t border-sand-200 pt-3">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-bold text-gray-700">
                    你的必去地点 (最多 5 个，优先编排进路线)
                  </span>
                  <span className="text-[11px] text-gray-400 font-mono">
                    {mustInclude.length} / 5
                  </span>
                </div>

                {/* 输入框与联想下拉 */}
                <div className="relative">
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={mustIncludeInput}
                      onChange={(e) => setMustIncludeInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          if (matchedHotPlaces.length > 0) {
                            handleAddMustInclude(matchedHotPlaces[0].name, matchedHotPlaces[0].place_id);
                          } else {
                            handleAddMustInclude(mustIncludeInput);
                          }
                        }
                      }}
                      placeholder={`输入${city}地点名，支持实时联想推荐...`}
                      disabled={mustInclude.length >= 5}
                      className="flex-1 rounded-xl border border-sand-300 bg-sand-50 px-3.5 py-2 text-xs text-gray-800 focus:bg-white focus:outline-none focus:ring-2 focus:ring-primary-400 shadow-inner"
                    />
                    <button
                      type="button"
                      onClick={() => {
                        if (matchedHotPlaces.length > 0) {
                          handleAddMustInclude(matchedHotPlaces[0].name, matchedHotPlaces[0].place_id);
                        } else {
                          handleAddMustInclude(mustIncludeInput);
                        }
                      }}
                      disabled={!mustIncludeInput.trim() || mustInclude.length >= 5}
                      className="rounded-xl bg-primary-600 px-4 py-2 text-xs font-bold text-white hover:bg-primary-700 disabled:opacity-50 transition-colors shrink-0"
                    >
                      添加
                    </button>
                  </div>

                  {/* 实时 POI 联想气泡浮层 (Autocomplete Dropdown) */}
                  {matchedHotPlaces.length > 0 && mustInclude.length < 5 && (
                    <div className="absolute top-full left-0 right-16 mt-1 z-50 rounded-xl bg-white border border-sand-300 shadow-xl overflow-hidden divide-y divide-sand-100 max-h-40 overflow-y-auto custom-scrollbar animate-in fade-in duration-150">
                      {matchedHotPlaces.map((hp) => (
                        <button
                          key={hp.place_id || hp.name}
                          type="button"
                          onClick={() => handleAddMustInclude(hp.name, hp.place_id)}
                          className="w-full px-3 py-2 text-left text-xs text-gray-800 hover:bg-emerald-50 hover:text-emerald-900 flex items-center justify-between transition-colors"
                        >
                          <span className="font-semibold flex items-center gap-1.5">
                            <i className="fa-solid fa-location-dot text-emerald-600 text-[10px]" />
                            <span>{hp.name}</span>
                          </span>
                          <span className="text-[10px] text-emerald-600 font-bold bg-emerald-100 px-1.5 py-0.5 rounded">
                            + 点击添加
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* 已选必去标签 */}
                {mustInclude.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2.5">
                    {mustInclude.map((item, idx) => (
                      <span
                        key={item.name}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-100 text-emerald-900 border border-emerald-300 px-2.5 py-1 text-xs font-semibold"
                      >
                        <i className="fa-solid fa-location-dot text-[10px] text-emerald-600" />
                        <span>{item.name}</span>
                        <button
                          type="button"
                          onClick={() => handleRemoveMustInclude(idx)}
                          className="hover:text-red-600 text-emerald-700 ml-0.5"
                        >
                          ✕
                        </button>
                      </span>
                    ))}
                  </div>
                )}

                {/* 热门 POI 快捷气泡 */}
                {hotPlaces.length > 0 && mustInclude.length < 5 && (
                  <div className="mt-3">
                    <span className="text-[11px] text-gray-400 block mb-1.5">
                      {city}热门打卡地标推荐：
                    </span>
                    <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto custom-scrollbar">
                      {hotPlaces.map((hp) => {
                        const isAdded = mustInclude.some((m) => m.name === hp.name);
                        return (
                          <button
                            key={hp.place_id || hp.name}
                            type="button"
                            disabled={isAdded}
                            onClick={() => handleAddMustInclude(hp.name, hp.place_id)}
                            className={`rounded-lg px-2.5 py-1 text-xs transition-all ${
                              isAdded
                                ? "bg-sand-200/60 text-gray-400 line-through cursor-not-allowed"
                                : "bg-sand-100 hover:bg-emerald-50 hover:border-emerald-300 hover:text-emerald-800 border border-sand-200/70 text-gray-700"
                            }`}
                          >
                            + {hp.name}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>

              {/* 3. 已知住宿与个性化备注 */}
              <div className="border-t border-sand-200 pt-3 space-y-3">
                <div>
                  <label className="text-xs font-bold text-gray-700 block mb-1">
                    已知住宿地点（选填，系统将围绕你的住宿地排布路线）
                  </label>
                  <input
                    type="text"
                    value={accommodationName}
                    onChange={(e) => setAccommodationName(e.target.value)}
                    placeholder="如：解放碑皇冠假日酒店"
                    className="w-full rounded-xl border border-sand-300 bg-sand-50 px-3.5 py-2 text-xs text-gray-800 focus:bg-white focus:outline-none focus:ring-2 focus:ring-primary-400"
                  />
                </div>

                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-xs font-bold text-gray-700">
                      补充备注（选填，如：带老人、不吃辣、特定偏好）
                    </label>
                    <span className="text-[10px] text-gray-400 font-mono">
                      {notes.length}/200
                    </span>
                  </div>
                  <textarea
                    value={notes}
                    maxLength={200}
                    onChange={(e) => setNotes(e.target.value.slice(0, 200))}
                    placeholder="输入你的任何个性化需求..."
                    rows={2}
                    className="w-full rounded-xl border border-sand-300 p-2.5 text-xs text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-400"
                  />
                </div>
              </div>

              <div className="text-right pt-2 border-t border-sand-200">
                <button
                  type="button"
                  onClick={() => setActiveTab(null)}
                  className="rounded-xl bg-gray-900 px-5 py-2 text-xs font-bold text-white hover:bg-gray-800 shadow-sm"
                >
                  完成设置
                </button>
              </div>
            </div>
          )}
        </div>
      </main>

      {/* 5. 左下角风光拍立得印记 */}
      <div className="absolute bottom-6 left-6 z-20 hidden sm:flex items-center gap-2.5 rounded-xl bg-black/40 px-3.5 py-2 text-white/90 backdrop-blur-md border border-white/15">
        <i className="fa-solid fa-camera text-emerald-400 text-xs" />
        <div className="text-left">
          <p className="text-[11px] font-bold">{displayCity}</p>
          <p className="text-[9px] text-white/70 font-light">{currentCityMeta?.tag || "智能路线规划"}</p>
        </div>
      </div>

      {/* Demo 方案切换悬浮条 */}
      <DemoSwitcher />
    </div>
  );
}
