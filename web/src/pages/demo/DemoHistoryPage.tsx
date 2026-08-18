import { useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { DemoSwitcher } from "@/components/demo/DemoSwitcher";
import { getHistoryTrips } from "@/services/api";
import { useAuthStore } from "@/stores/authStore";
import type { HistoryTripItem } from "@/types/auth";
import {
  getCityPostcardCover,
  getCityPostcardMeta,
  getCityAllCovers,
  getCityDayRoutes,
} from "@/utils/cityPhotos";

interface ExtendedHistoryItem extends HistoryTripItem {
  itinerarySummary?: { day: number; route: string }[];
}

const MOCK_DEMO_ITEMS: ExtendedHistoryItem[] = [
  {
    trip_id: "trip-demo-cq-3d",
    job_id: "job-cq-9981",
    result_record_id: "demo-cq-record",
    city: "重庆",
    days: 3,
    status: "SUCCESS",
    created_at: new Date(Date.now() - 1000 * 3600 * 24 * 1).toISOString(),
    finished_at: new Date(Date.now() - 1000 * 3600 * 24 * 1 + 15000).toISOString(),
    expires_from_history_at: new Date(Date.now() + 1000 * 3600 * 24 * 6).toISOString(),
    error: null,
    itinerarySummary: [
      { day: 1, route: "解放碑 ➔ 戴家巷 ➔ 洪崖洞夜景" },
      { day: 2, route: "李子坝轻轨 ➔ 鹅岭二厂 ➔ 观音桥好吃街" },
      { day: 3, route: "白象居 ➔ 长江索道 ➔ 南滨路钟楼" },
    ],
    retry_input: {
      trip_request: {
        to_city: "重庆",
        start_date: "2026-08-15",
        end_date: "2026-08-17",
        days: 3,
        people_count: 2,
        preferences: ["美食", "夜景", "适中"],
        avoid: [],
        notes: "",
      },
    },
  },
  {
    trip_id: "trip-demo-hz-2d",
    job_id: "job-hz-8821",
    result_record_id: "demo-hz-record",
    city: "杭州",
    days: 2,
    status: "SUCCESS",
    created_at: new Date(Date.now() - 1000 * 3600 * 24 * 3).toISOString(),
    finished_at: new Date(Date.now() - 1000 * 3600 * 24 * 3 + 15000).toISOString(),
    expires_from_history_at: new Date(Date.now() + 1000 * 3600 * 24 * 4).toISOString(),
    error: null,
    itinerarySummary: [
      { day: 1, route: "西湖断桥 ➔ 孤山 ➔ 灵隐寺祈福" },
      { day: 2, route: "法喜寺 ➔ 龙井问茶 ➔ 钱江新城灯光秀" },
    ],
    retry_input: {
      trip_request: {
        to_city: "杭州",
        start_date: "2026-08-18",
        end_date: "2026-08-19",
        days: 2,
        people_count: 2,
        preferences: ["漫步", "古刹", "轻松"],
        avoid: [],
        notes: "",
      },
    },
  },
  {
    trip_id: "trip-demo-xa-4d",
    job_id: "job-xa-7711",
    result_record_id: "demo-xa-record",
    city: "西安",
    days: 4,
    status: "SUCCESS",
    created_at: new Date(Date.now() - 1000 * 3600 * 24 * 5).toISOString(),
    finished_at: new Date(Date.now() - 1000 * 3600 * 24 * 5 + 15000).toISOString(),
    expires_from_history_at: new Date(Date.now() + 1000 * 3600 * 24 * 2).toISOString(),
    error: null,
    itinerarySummary: [
      { day: 1, route: "秦始皇兵马俑 ➔ 华清宫长恨歌" },
      { day: 2, route: "大雁塔 ➔ 大唐不夜城沉浸夜游" },
      { day: 3, route: "古城墙骑行 ➔ 回民街碳水寻味" },
      { day: 4, route: "陕西历史博物馆 ➔ 永兴坊" },
    ],
    retry_input: {
      trip_request: {
        to_city: "西安",
        start_date: "2026-08-22",
        end_date: "2026-08-25",
        days: 4,
        people_count: 3,
        preferences: ["历史", "碳水", "适中"],
        avoid: [],
        notes: "",
      },
    },
  },
  {
    trip_id: "trip-demo-cd-failed",
    job_id: "job-cd-6655",
    result_record_id: null,
    city: "成都",
    days: 3,
    status: "FAILED",
    created_at: new Date(Date.now() - 1000 * 3600 * 12).toISOString(),
    finished_at: new Date(Date.now() - 1000 * 3600 * 12 + 10000).toISOString(),
    expires_from_history_at: new Date(Date.now() + 1000 * 3600 * 24 * 6.5).toISOString(),
    error: {
      code: "TASK_TIMEOUT",
      message: "生成超时，已自动为你全额秒级退回公测额度",
      retryable: true,
    },
    retry_input: {
      trip_request: {
        to_city: "成都",
        start_date: "2026-08-20",
        end_date: "2026-08-22",
        days: 3,
        people_count: 2,
        preferences: ["美食", "休闲", "适中"],
        avoid: [],
        notes: "",
      },
    },
  },
];

function formatTime(iso: string) {
  try {
    const d = new Date(iso);
    return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  } catch {
    return iso;
  }
}

export default function DemoHistoryPage() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);

  const [items, setItems] = useState<ExtendedHistoryItem[]>(MOCK_DEMO_ITEMS);
  const [filter, setFilter] = useState<"all" | "success" | "failed">("all");
  const [searchCity, setSearchCity] = useState("");
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // 用户手动切换的自定义卡片封面覆盖字典
  const [customCovers, setCustomCovers] = useState<Record<string, string>>({});

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => {
      setToastMessage(null);
    }, 2500);
  };

  // 尝试读取真实 BFF 历史行程
  useEffect(() => {
    let cancelled = false;
    getHistoryTrips()
      .then((res) => {
        if (!cancelled && res.ok && res.items && res.items.length > 0) {
          const realIds = new Set(res.items.map((i) => i.trip_id));
          const mockExtras = MOCK_DEMO_ITEMS.filter((m) => !realIds.has(m.trip_id));
          setItems([...res.items, ...mockExtras]);
        }
      })
      .catch(() => {
        /* fallback to mock */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      if (filter === "success" && item.status !== "SUCCESS") return false;
      if (filter === "failed" && item.status === "SUCCESS") return false;
      if (searchCity && !item.city.includes(searchCity.trim())) return false;
      return true;
    });
  }, [items, filter, searchCity]);

  // 按月份分组
  const groupedSections = useMemo(() => {
    const groups: Record<string, ExtendedHistoryItem[]> = {};
    filteredItems.forEach((item) => {
      const d = new Date(item.created_at);
      const key = `${d.getFullYear()}年 ${d.getMonth() + 1}月`;
      if (!groups[key]) groups[key] = [];
      groups[key].push(item);
    });
    return Object.entries(groups).map(([month, list]) => ({ month, list }));
  }, [filteredItems]);

  // 统计数据
  const totalCities = useMemo(() => new Set(items.map((i) => i.city)).size, [items]);
  const totalDays = useMemo(
    () => items.filter((i) => i.status === "SUCCESS").reduce((acc, cur) => acc + cur.days, 0),
    [items]
  );
  const totalSpots = useMemo(() => totalCities * 7, [totalCities]);

  // 轮换切换单张卡片封面
  const handleCycleCover = (tripId: string, city: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const allPhotos = getCityAllCovers(city);
    if (allPhotos.length <= 1) return;

    const current = customCovers[tripId] || getCityPostcardCover(city, tripId);
    const currentIndex = allPhotos.indexOf(current);
    const nextIndex = (currentIndex + 1) % allPhotos.length;
    const nextPhoto = allPhotos[nextIndex];

    setCustomCovers((prev) => ({
      ...prev,
      [tripId]: nextPhoto,
    }));
    showToast(`已切换【${city}】明信片风光封面 (${nextIndex + 1}/${allPhotos.length})`);
  };

  const handleCopyLink = (tripId: string, city: string, e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard?.writeText(window.location.origin + `/plan/demo-${tripId}`);
    showToast(`已复制【${city}】专属路书分享链接！`);
  };

  const handleDeleteTrip = (tripId: string, city: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (window.confirm(`确定要将【${city}】行程从足迹列表移除吗？`)) {
      setItems((prev) => prev.filter((i) => i.trip_id !== tripId));
      showToast(`已移除【${city}】行程`);
    }
  };

  return (
    <div className="min-h-screen w-full bg-[#f8f7f4] font-body text-gray-900 pb-28">
      {/* Toast 提示条 */}
      {toastMessage && (
        <div className="fixed top-6 left-1/2 -translate-x-1/2 z-50 rounded-full bg-gray-900/90 text-white text-xs font-semibold px-4 py-2 shadow-xl backdrop-blur-md flex items-center gap-2 border border-white/20 animate-in fade-in slide-in-from-top-4 duration-200">
          <i className="fa-solid fa-circle-check text-emerald-400 text-sm" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* 1. 顶部 Header */}
      <header className="border-b border-sand-200/80 bg-white/80 px-6 py-4 backdrop-blur-md sticky top-0 z-30">
        <div className="mx-auto max-w-6xl flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => navigate("/")}
              className="flex h-9 w-9 items-center justify-center rounded-xl border border-sand-200 text-gray-500 hover:text-gray-900 hover:bg-sand-50 transition-colors"
              title="返回首页"
            >
              <i className="fa-solid fa-chevron-left text-xs" />
            </button>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="font-display text-lg sm:text-xl font-bold text-gray-900 tracking-tight">
                  旅行足迹与路书画廊
                </h1>
                <span className="rounded-full bg-primary-50 border border-primary-200 px-2 py-0.5 text-[10px] font-bold text-primary-800">
                  Demo · 实体明信片
                </span>
              </div>
              <p className="text-xs text-gray-400 mt-0.5">
                {user?.display_name || "云途探索家"} 的专属旅行历史 · 每一份路书都是你的独特印记
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={() => navigate("/demo/input-capsule")}
            className="flex items-center gap-2 rounded-xl bg-primary-700 hover:bg-primary-800 active:scale-95 px-4 py-2 text-xs font-bold text-white shadow-sm transition-all self-start sm:self-auto"
          >
            <i className="fa-solid fa-plus text-[10px]" />
            <span>开启新旅程</span>
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 sm:px-6 pt-6 space-y-6">
        {/* 2. 旅行成就与足迹统计卡 */}
        <section className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#12241d] via-[#1a382e] to-[#0d1813] p-6 sm:p-7 text-white shadow-md border border-emerald-700/30">
          <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
            <div className="space-y-1">
              <span className="text-[11px] font-bold uppercase tracking-widest text-emerald-400">
                TRAVEL FOOTPRINT ARCHIVE
              </span>
              <h2 className="font-display text-xl sm:text-2xl font-black tracking-tight">
                你的云途探索档案
              </h2>
              <p className="text-xs text-primary-100/80 font-light">
                已点亮华夏多座名城，路书数据永久支持导出与高德同步
              </p>
            </div>

            {/* 3 大核心数字徽章 */}
            <div className="grid grid-cols-3 gap-2 sm:gap-4 bg-white/10 p-3.5 rounded-xl backdrop-blur-md border border-white/15">
              <div className="text-center px-3">
                <span className="text-xs text-primary-200 block">点亮城市</span>
                <span className="font-display text-2xl sm:text-3xl font-black text-white">{totalCities}</span>
                <span className="text-[10px] text-emerald-300 block">座名城</span>
              </div>
              <div className="h-9 w-px bg-white/20 my-auto" aria-hidden="true" />
              <div className="text-center px-3">
                <span className="text-xs text-primary-200 block">规划旅途</span>
                <span className="font-display text-2xl sm:text-3xl font-black text-white">{totalDays}</span>
                <span className="text-[10px] text-emerald-300 block">天时光</span>
              </div>
              <div className="h-9 w-px bg-white/20 my-auto" aria-hidden="true" />
              <div className="text-center px-3">
                <span className="text-xs text-primary-200 block">解锁地标</span>
                <span className="font-display text-2xl sm:text-3xl font-black text-white">{totalSpots}</span>
                <span className="text-[10px] text-emerald-300 block">处胜景</span>
              </div>
            </div>
          </div>
        </section>

        {/* 3. 筛选与搜索工具条 */}
        <section className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-1.5 p-1 rounded-xl bg-sand-200/60 border border-sand-300/60 text-xs font-semibold">
            <button
              type="button"
              onClick={() => setFilter("all")}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                filter === "all" ? "bg-white text-gray-900 shadow-xs font-bold" : "text-gray-600 hover:text-gray-900"
              }`}
            >
              全部行程 ({items.length})
            </button>
            <button
              type="button"
              onClick={() => setFilter("success")}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                filter === "success" ? "bg-white text-gray-900 shadow-xs font-bold" : "text-gray-600 hover:text-gray-900"
              }`}
            >
              已就绪 ({items.filter((i) => i.status === "SUCCESS").length})
            </button>
            <button
              type="button"
              onClick={() => setFilter("failed")}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                filter === "failed" ? "bg-white text-gray-900 shadow-xs font-bold" : "text-gray-600 hover:text-gray-900"
              }`}
            >
              待重试 ({items.filter((i) => i.status !== "SUCCESS").length})
            </button>
          </div>

          <div className="relative">
            <i className="fa-solid fa-magnifying-glass absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-xs" />
            <input
              type="text"
              value={searchCity}
              onChange={(e) => setSearchCity(e.target.value)}
              placeholder="搜索城市（如重庆、杭州）"
              className="w-full sm:w-64 rounded-xl bg-white pl-9 pr-4 py-2 text-xs border border-sand-300 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-300 shadow-2xs"
            />
          </div>
        </section>

        {/* 4. 按时间分组呈现明信片卡片瀑布流 */}
        {groupedSections.length > 0 ? (
          <div className="space-y-8">
            {groupedSections.map((sec) => (
              <section key={sec.month} className="space-y-4">
                {/* 时间轴标题 */}
                <div className="flex items-center gap-2.5">
                  <span className="flex h-2 w-2 rounded-full bg-primary-600" />
                  <h3 className="font-display text-sm font-bold text-gray-800">
                    {sec.month}
                  </h3>
                  <span className="text-[11px] text-gray-400 font-mono">
                    ({sec.list.length} 份路书)
                  </span>
                  <div className="flex-1 h-px bg-sand-200" />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {sec.list.map((item) => {
                    const isSuccess = item.status === "SUCCESS";
                    const meta = getCityPostcardMeta(item.city);
                    const coverUrl = customCovers[item.trip_id] || getCityPostcardCover(item.city, item.trip_id);
                    const routes = item.itinerarySummary || getCityDayRoutes(item.city, item.days);

                    return (
                      <div
                        key={item.trip_id}
                        className="group relative overflow-hidden rounded-2xl bg-white border border-sand-200/90 shadow-2xs hover:shadow-lg transition-all duration-300 hover:-translate-y-0.5 flex flex-col justify-between"
                      >
                        {/* 明信片顶部实景巨幅视窗 */}
                        <div className="relative h-48 sm:h-52 w-full overflow-hidden bg-gray-900">
                          <div
                            className="absolute inset-0 bg-cover bg-center transition-transform duration-700 group-hover:scale-105"
                            style={{ backgroundImage: `url('${coverUrl}')` }}
                          />
                          {/* 双层高对比度渐变罩层 */}
                          <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/30 to-black/20" />

                          {/* 顶部栏：城市英文标 + 📸 换风光按钮（高对比稳定版） + 拟物邮戳 */}
                          <div className="absolute top-3.5 left-4 right-4 flex items-start justify-between z-10">
                            <div className="flex items-center gap-2">
                              <span className="rounded-md bg-black/60 px-2.5 py-1 text-[10px] font-mono font-bold tracking-widest text-white backdrop-blur-md border border-white/20">
                                {meta.pinyin}
                              </span>

                              {/* 换一张封面按钮（高对比稳定深色遮罩） */}
                              <button
                                type="button"
                                onClick={(e) => handleCycleCover(item.trip_id, item.city, e)}
                                className="flex items-center gap-1 rounded-md bg-black/60 hover:bg-black/80 active:scale-95 px-2.5 py-1 text-[10px] font-bold text-white backdrop-blur-md border border-white/30 shadow-sm transition-all"
                                title="在 CDN 图库中换一张封面大片"
                              >
                                <i className="fa-solid fa-camera-rotate text-[10px] text-emerald-400" />
                                <span>换风光</span>
                              </button>
                            </div>

                            {/* 实体锯齿齿孔火漆邮戳 */}
                            <div className="flex h-11 w-11 rotate-12 flex-col items-center justify-center rounded-full border-2 border-dashed border-white/90 bg-emerald-950/80 text-white backdrop-blur-md shadow-md">
                              <span className="text-[6.5px] font-mono font-bold tracking-tighter text-emerald-300">YUNTU</span>
                              <span className="text-[10px] font-black leading-none">{item.days}D</span>
                            </div>
                          </div>

                          {/* 城市名称与天数大标 */}
                          <div className="absolute bottom-3.5 left-4 right-4 flex items-end justify-between z-10">
                            <div>
                              <h3 className="font-display text-2xl font-black text-white tracking-tight drop-shadow-md">
                                {item.city}
                              </h3>
                              <p className="text-xs text-white/90 font-medium mt-0.5 drop-shadow-sm">
                                {meta.moodTag}
                              </p>
                            </div>
                            <span className="rounded-lg bg-white/95 px-2.5 py-1 text-xs font-bold text-gray-900 shadow-sm">
                              {item.days} 天 {Math.max(1, item.days - 1)} 晚
                            </span>
                          </div>
                        </div>

                        {/* 明信片下半部分：每日路线动线与亮点 */}
                        <div className="p-5 space-y-4 flex-1 flex flex-col justify-between">
                          <div className="space-y-3">
                            {/* 每日核心路线主轴 (Daily Itinerary Track Preview - 100% 呈现) */}
                            <div className="space-y-2 rounded-xl bg-sand-50/90 p-3 border border-sand-200/80 shadow-2xs">
                              <div className="flex items-center justify-between">
                                <span className="text-[11px] font-bold text-gray-800 flex items-center gap-1.5">
                                  <i className="fa-solid fa-route text-primary-600 text-xs" />
                                  <span>每日游玩动线脉络 ({routes.length}天)</span>
                                </span>
                                <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${isSuccess ? "text-emerald-700 bg-emerald-50" : "text-amber-700 bg-amber-50"}`}>
                                  {isSuccess ? "✓ 已规划" : "参考动线"}
                                </span>
                              </div>

                              <div className="space-y-1.5 text-xs">
                                {routes.map((s) => (
                                  <div key={s.day} className="flex items-center gap-2 text-gray-800">
                                    <span className="flex h-4.5 w-6 shrink-0 items-center justify-center rounded bg-primary-700 text-white text-[10px] font-black font-mono shadow-2xs">
                                      D{s.day}
                                    </span>
                                    <span className="truncate text-xs font-medium text-gray-800">
                                      {s.route}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            </div>

                            {/* 亮点地标便签 */}
                            <div className="space-y-1.5">
                              <span className="text-[11px] font-bold text-gray-400 uppercase tracking-wider flex items-center gap-1">
                                <i className="fa-solid fa-compass text-primary-600 text-[10px]" />
                                <span>亮点打卡胜景</span>
                              </span>
                              <div className="flex flex-wrap gap-1.5">
                                {meta.highlights.map((h) => (
                                  <span
                                    key={h}
                                    className="rounded-lg bg-sand-100 px-2.5 py-0.8 text-xs font-medium text-gray-700 border border-sand-200/60"
                                  >
                                    {h}
                                  </span>
                                ))}
                              </div>
                            </div>

                            {/* 失败状态提示 */}
                            {!isSuccess && (
                              <div className="rounded-xl bg-red-50 border border-red-200/80 p-3 text-xs text-red-700 flex items-start gap-2">
                                <i className="fa-solid fa-circle-exclamation text-red-500 mt-0.5" />
                                <div>
                                  <span className="font-bold block">生成未就绪</span>
                                  <span className="text-[11px] text-red-600">
                                    {item.error?.message || "网络波动或超时，公测额度已自动全额秒级返还"}
                                  </span>
                                </div>
                              </div>
                            )}
                          </div>

                          {/* 底部操作与元数据 */}
                          <div className="pt-3 border-t border-sand-100 flex items-center justify-between text-xs">
                            <div className="flex items-center gap-3 text-gray-400 font-mono text-[11px]">
                              <span>
                                <i className="fa-regular fa-calendar mr-1" />
                                {formatTime(item.created_at)}
                              </span>
                            </div>

                            <div className="flex items-center gap-2">
                              {/* 快捷分享 */}
                              {isSuccess && (
                                <button
                                  type="button"
                                  onClick={(e) => handleCopyLink(item.trip_id, item.city, e)}
                                  className="rounded-lg border border-sand-300 bg-white p-2 text-gray-600 hover:text-primary-700 hover:bg-sand-50 transition-colors"
                                  title="复制专属路书链接"
                                >
                                  <i className="fa-solid fa-share-nodes text-xs" />
                                </button>
                              )}

                              {/* 删除 */}
                              <button
                                type="button"
                                onClick={(e) => handleDeleteTrip(item.trip_id, item.city, e)}
                                className="rounded-lg border border-sand-300 bg-white p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                                title="移除足迹"
                              >
                                <i className="fa-regular fa-trash-can text-xs" />
                              </button>

                              {/* 翻阅路书 / 立即重试 */}
                              {isSuccess ? (
                                <button
                                  type="button"
                                  onClick={() => navigate(item.result_record_id ? `/plan/${item.result_record_id}` : "/demo")}
                                  className="rounded-xl bg-primary-700 px-4 py-2 font-bold text-white shadow-xs hover:bg-primary-800 active:scale-95 transition-all flex items-center gap-1.5"
                                >
                                  <span>翻阅路书</span>
                                  <i className="fa-solid fa-arrow-right text-[10px]" />
                                </button>
                              ) : (
                                <button
                                  type="button"
                                  onClick={() => navigate("/demo/input-capsule")}
                                  className="rounded-xl bg-accent-600 px-4 py-2 font-bold text-white shadow-xs hover:bg-accent-700 active:scale-95 transition-all flex items-center gap-1.5"
                                >
                                  <i className="fa-solid fa-rotate-right text-[10px]" />
                                  <span>重新规划</span>
                                </button>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
        ) : (
          /* 5. 空状态 */
          <section className="rounded-2xl border border-dashed border-sand-300 bg-white p-12 text-center space-y-4">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-sand-100 text-gray-400 text-2xl">
              <i className="fa-solid fa-map-location-dot" />
            </div>
            <div>
              <h3 className="font-display text-base font-bold text-gray-800">
                {searchCity ? `未找到包含 “${searchCity}” 的行程足迹` : "暂无相关的旅行足迹"}
              </h3>
              <p className="text-xs text-gray-400 mt-1">
                {searchCity ? "请尝试搜索其他城市名称" : "随时开启你的第一场 AI 深度定制之旅"}
              </p>
            </div>
            {searchCity ? (
              <button
                type="button"
                onClick={() => setSearchCity("")}
                className="rounded-xl border border-sand-300 px-4 py-2 text-xs font-semibold text-gray-700 hover:bg-sand-50"
              >
                清除搜索条件
              </button>
            ) : (
              <button
                type="button"
                onClick={() => navigate("/demo/input-capsule")}
                className="rounded-xl bg-primary-700 px-5 py-2.5 text-xs font-bold text-white hover:bg-primary-800 shadow-sm"
              >
                即刻定制新行程
              </button>
            )}
          </section>
        )}
      </main>

      {/* Demo 方案切换悬浮条 */}
      <DemoSwitcher />
    </div>
  );
}
