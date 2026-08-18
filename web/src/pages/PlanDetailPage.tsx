/**
 * 方案详情（杂志阅读流）
 * 路由：/plan/:resultId/:planId
 * 旧三栏详情见 PlanDetailClassicPage（/demo/detail-classic）
 */
import { useEffect, useMemo, useState, lazy, Suspense, useRef } from "react";
import { useNavigate, useParams, useSearchParams, Link } from "react-router-dom";

import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { DetailSkeleton } from "@/components/skeleton/DetailSkeleton";
import { TransportCard } from "@/components/detail/TransportCard";
import { WeatherStrip } from "@/components/detail/WeatherStrip";
import { TripSpine } from "@/components/detail/TripSpine";
import { PlaceDetailModal } from "@/components/detail/PlaceDetailModal";
import { AccommodationTimelineNode } from "@/components/detail/AccommodationCard";
import { ShareDialog } from "@/components/share/ShareDialog";
import { useTripStore } from "@/stores/tripStore";
import { fetchResult, ApiRequestError } from "@/services/api";

import { CostEstimateCard } from "@/components/detail/CostEstimateCard";
import { MustIncludeNotice } from "@/components/detail/MustIncludeNotice";
import { SafeDeliveryNotice } from "@/components/result/SafeDeliveryNotice";
import { getScenarioCostStatus, type CostScenarioSummary } from "@/types/cost";
import { useArtifact } from "@/hooks/useArtifact";
import { saveBlob } from "@/utils/download";
import { showToast } from "@/stores/toastStore";
import { getCityPhotoUrls } from "@/components/input/RotatingBackground";
import { weatherIcon } from "@/constants/weather";
import {
  formatDistance,
  formatMinutes,
  commuteModeName,
  commuteModeIcon,
  cleanBrief,
  cleanTags,
  cleanSummary,
} from "@/utils/format";
import { timePreferencesLabel } from "@/utils/schedule";
import { categoryIcon, categoryName, isAnchorRole } from "@/constants/places";
import type { TripDay, TripPlace, TripPlan, TripResult, WeatherDay } from "@/types/trip";

gsap.registerPlugin(ScrollTrigger);

const MapView = lazy(() =>
  import("@/components/detail/MapView").then((m) => ({ default: m.MapView })),
);

const PACE_LABEL: Record<string, string> = {
  RELAXED: "轻松",
  MODERATE: "适中",
  INTENSIVE: "紧凑",
  PACKED: "紧凑",
};

const PERIOD_LABEL: Record<string, string> = {
  morning: "上午",
  afternoon: "下午",
  evening: "傍晚",
  night: "夜间",
};


function formatStayDuration(minutes?: number | null): string {
  if (!minutes || minutes <= 0) return "自由漫游";
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return mins > 0 ? `建议 ${hours}小时${mins}分` : `建议 ${hours}小时`;
  }
  return `建议 ${minutes}分钟`;
}

function placeTimeLabel(place: TripPlace): string | null {
  const s = place.schedule;
  if (!s) return null;
  if (s.exact_start) {
    return s.exact_end ? `${s.exact_start} – ${s.exact_end}` : s.exact_start;
  }
  if (s.period && PERIOD_LABEL[s.period]) return PERIOD_LABEL[s.period];
  return null;
}

function dayWeatherLabel(
  day: number,
  weatherDays: WeatherDay[] | undefined,
): string | null {
  const w = weatherDays?.find((d) => d.day === day);
  if (!w) return null;
  return `${weatherIcon(w.icon_code)} ${w.temp_max_c}°C`;
}

export default function PlanDetailPage() {
  const { resultId, planId } = useParams<{ resultId: string; planId: string }>();
  const [searchParams] = useSearchParams();
  const jobId = searchParams.get("job_id");
  const navigate = useNavigate();
  const storeResult = useTripStore((s) => s.result);
  const setResult = useTripStore((s) => s.setResult);

  const [fetchedResult, setFetchedResult] = useState<TripResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{
    kind: "notfound" | "unsupported" | "generic";
    message: string;
  } | null>(null);

  const [activeTab, setActiveTab] = useState("overview");
  const [showMap, setShowMap] = useState(false);
  const [mapDay, setMapDay] = useState(1);
  const [activePlaceId, setActivePlaceId] = useState<number | null>(null);
  const [detailPlace, setDetailPlace] = useState<TripPlace | null>(null);
  const isShareParam = searchParams.get("share") === "1";
  const [shareOpen, setShareOpen] = useState(isShareParam);
  const [expandedCommutes, setExpandedCommutes] = useState<Set<string>>(new Set());

  const toggleCommute = (key: string) => {
    setExpandedCommutes((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  useEffect(() => {
    if (isShareParam) {
      setShareOpen(true);
    }
  }, [isShareParam]);

  const [isScrolled, setIsScrolled] = useState(false);
  const leftBrandRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onScroll = () => {
      setIsScrolled(window.scrollY > 120);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!leftBrandRef.current) return;
    const isMobile = window.innerWidth < 768;
    if (isMobile) return;

    if (isScrolled) {
      gsap.to(leftBrandRef.current, {
        opacity: 1,
        x: 0,
        scale: 1,
        duration: 0.45,
        ease: "back.out(1.4)",
        overwrite: "auto",
      });
    } else {
      gsap.to(leftBrandRef.current, {
        opacity: 0,
        x: -16,
        scale: 0.9,
        duration: 0.25,
        ease: "power2.in",
        overwrite: "auto",
      });
    }
  }, [isScrolled]);

  const pdf = useArtifact(resultId, "pdf");

  const matched =
    storeResult &&
    String(storeResult.resultId) === String(resultId) &&
    storeResult.jobId === (jobId ?? "");
  const result = matched ? storeResult.data : fetchedResult;

  useEffect(() => {
    setError(null);
    const cached = useTripStore.getState().result;
    const hit =
      cached &&
      String(cached.resultId) === String(resultId) &&
      cached.jobId === (jobId ?? "");
    if (hit) {
      setFetchedResult(cached.data);
      setLoading(false);
      return;
    }
    setFetchedResult(null);
    if (!resultId) return;

    let cancelled = false;
    setLoading(true);
    fetchResult(resultId, jobId ?? "")
      .then((data) => {
        if (cancelled) return;
        setFetchedResult(data);
        setResult(resultId, jobId ?? "", data);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiRequestError) {
          if (err.status === 404) {
            setError({ kind: "notfound", message: "攻略不存在" });
          } else if (
            err.status === 422 &&
            err.code === "RESULT_CONTRACT_UNSUPPORTED"
          ) {
            setError({
              kind: "unsupported",
              message: "该攻略由旧版本生成，暂不支持打开，请重新生成",
            });
          } else {
            setError({ kind: "generic", message: err.message });
          }
        } else {
          setError({ kind: "generic", message: "加载失败" });
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [resultId, jobId, setResult]);

  const plan: TripPlan | undefined = result?.plans?.find(
    (p) => p.plan_id === planId,
  );
  const people = result?.request.people_count ?? 1;

  const [activeScenarioId, setActiveScenarioId] = useState<string | null>(null);

  const costEstimate = plan?.cost_estimate;
  const scenarios = useMemo(() => costEstimate?.scenarios ?? [], [costEstimate]);
  const scenarioIds = scenarios.map((s) => s.scenario_id).join(",");

  // 单场景或 without_intercity 场景时自动选定，双大交通场景时保持 null 离散选择状态
  useEffect(() => {
    if (scenarios.length === 1 && scenarios[0]?.scenario_id) {
      setActiveScenarioId(scenarios[0].scenario_id);
    } else if (scenarios.length > 1) {
      setActiveScenarioId(null);
    }
  }, [plan?.plan_id, scenarioIds, scenarios]);

  const activeScenario: CostScenarioSummary | undefined = scenarios.find(
    (s) => s.scenario_id === activeScenarioId,
  ) ?? (scenarios.length === 1 ? scenarios[0] : undefined);

  const isDualMode = scenarios.length > 1;
  const isUnselected = isDualMode && !activeScenarioId;
  const heroCostStatus = getScenarioCostStatus(activeScenario, isUnselected);
  const city = result?.city.name ?? "";

  const activeDayNumber = useMemo(() => {
    if (activeTab.startsWith("day-")) {
      const n = Number(activeTab.replace("day-", ""));
      if (!Number.isNaN(n)) return n;
    }
    return mapDay ?? 1;
  }, [activeTab, mapDay]);

  // PDF 准备就绪自动下载 / 失败提示
  useEffect(() => {
    if (pdf.phase === "ready" && pdf.blob) {
      saveBlob(pdf.blob, `云途行程路书_${city || ""}_${plan?.title || "方案"}.pdf`);
      showToast("PDF 导出成功，已自动开始下载", "success");
      pdf.reset();
    } else if (pdf.phase === "failed" && pdf.error) {
      if (pdf.error.code === "AUTH_REQUIRED" || pdf.error.code === "401") {
        showToast("当前环境不支持账号导出，请稍后重试或检查后端配置", "error");
      } else {
        showToast(`PDF 导出失败: ${pdf.error.message}`, "error");
      }
      pdf.reset();
    }
  }, [pdf.phase, pdf.blob, pdf.error, city, plan?.title, pdf, navigate]);
  const cityCovers = useMemo(
    () => (city ? getCityPhotoUrls(city, 4) : []),
    [city],
  );
  const weatherDays =
    result?.weather?.status === "ok" && result.weather.days.length > 0
      ? result.weather.days
      : undefined;
  const timePrefText = result
    ? timePreferencesLabel(result.schema_version, result.time_preferences)
    : null;

  const dayForMap: TripDay | undefined =
    plan?.days?.find((d) => d.day === mapDay) ?? plan?.days?.[0];

  // plan 就绪后，初始化地图日
  useEffect(() => {
    if (plan?.days[0]?.day != null) setMapDay(plan.days[0].day);
  }, [plan?.plan_id, plan?.days]);

  // GSAP 微动效（数据就绪后绑定）
  useEffect(() => {
    if (loading || !plan) return;
    const timeout = setTimeout(() => {
      const ctx = gsap.context(() => {
        gsap.utils.toArray<HTMLElement>(".reveal-up").forEach((el) => {
          gsap.fromTo(
            el,
            { y: 40, opacity: 0 },
            {
              y: 0,
              opacity: 1,
              duration: 0.8,
              ease: "power3.out",
              scrollTrigger: {
                trigger: el,
                start: "top 85%",
                toggleActions: "play none none reverse",
              },
            },
          );
        });
        gsap.utils.toArray<HTMLElement>(".parallax-img").forEach((img) => {
          gsap.to(img, {
            y: "15%",
            ease: "none",
            scrollTrigger: {
              trigger: img.parentElement,
              start: "top bottom",
              end: "bottom top",
              scrub: true,
            },
          });
        });
      }, containerRef);
      return () => ctx.revert();
    }, 100);
    return () => clearTimeout(timeout);
  }, [loading, plan]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && showMap) setShowMap(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showMap]);


  // activeTab 变动时，在移动端横向胶囊导航中自动将高亮 Tab 居中平滑滚入视野
  useEffect(() => {
    if (!activeTab) return;
    const tabEl = document.getElementById(`nav-tab-${activeTab}`);
    if (tabEl) {
      tabEl.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
        inline: "center",
      });
    }
  }, [activeTab]);

  // 100% 精准 ScrollSpy：结合 getBoundingClientRect 判定当前视野中的 section
  useEffect(() => {
    if (!plan) return;

    const sectionIds = [
      "overview",
      ...plan.days.map((d) => `day-${d.day}`),
      "cost-estimate",
    ];

    let ticking = false;

    const handleScroll = () => {
      if (ticking) return;
      ticking = true;

      requestAnimationFrame(() => {
        ticking = false;
        let currentId = sectionIds[0];
        const offset = window.innerHeight * 0.4;
        const isBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 60;
        if (isBottom) {
          currentId = sectionIds[sectionIds.length - 1];
        } else {
          for (const id of sectionIds) {
            const el = document.getElementById(id);
            if (!el) continue;
            const rect = el.getBoundingClientRect();
            if (rect.top <= offset) {
              currentId = id;
            }
          }
        }

        if (currentId) {
          setActiveTab((prev) => (prev !== currentId ? currentId : prev));
          if (currentId.startsWith("day-")) {
            const n = Number(currentId.replace("day-", ""));
            if (!Number.isNaN(n)) {
              setMapDay((prev) => (prev !== n ? n : prev));
            }
          }
        }
      });
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();

    return () => {
      window.removeEventListener("scroll", handleScroll);
    };
  }, [plan]);

  function scrollTo(id: string) {
    setActiveTab(id);
    if (id.startsWith("day-")) {
      const n = Number(id.replace("day-", ""));
      if (!Number.isNaN(n)) {
        setMapDay(n);
      }
    }
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function openPlace(placeId: number) {
    if (!plan) return;
    setActivePlaceId(placeId);
    const found =
      plan.days.flatMap((d) => d.places).find((p) => p.place_id === placeId) ??
      null;
    if (found) {
      setShowMap(false);
      setDetailPlace(found);
    }
  }

  if (loading) return <DetailSkeleton />;

  if (error || !result || !plan) {
    const kind = error?.kind ?? "generic";
    const icon =
      kind === "notfound" ? "🔍" : kind === "unsupported" ? "🕰️" : "📋";
    const message = error?.message ?? "方案未找到";
    return (
      <div className="empty-state animate-fade-in">
        <span className="empty-state-icon">{icon}</span>
        <p className="max-w-xs text-sm font-medium text-primary-700">{message}</p>
        <button onClick={() => navigate("/")} className="btn-primary mt-2">
          {kind === "unsupported" ? "重新生成" : "重新规划"}
        </button>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="min-h-screen bg-sand-50 font-body text-gray-800 selection:bg-primary-100"
    >
      {/* 第一层：页顶全局统一导航栏（全宽两端通栏） */}
      <nav className="flex w-full items-center justify-between px-5 py-3.5 sm:px-10 lg:px-14 border-b border-sand-200/80 bg-white/90 backdrop-blur-md sticky top-0 z-30 shadow-2xs">
        <div className="flex items-center space-x-6">
          <Link to="/" className="flex items-center space-x-2">
            <img src="/logo.svg" alt="云途 YunTu" className="h-8 w-8" />
            <span className="text-xl font-black tracking-tight text-gray-900">
              云途 <span className="font-light text-emerald-600 text-sm">YunTu</span>
            </span>
          </Link>

          <div className="hidden sm:flex items-center space-x-2 text-xs font-semibold">
            <Link
              to="/"
              className="inline-flex items-center gap-1.5 text-gray-600 hover:text-gray-900 px-3 py-1.5 rounded-lg hover:bg-sand-100 transition-colors"
            >
              <i className="fa-solid fa-compass text-gray-400 text-[11px]" />
              <span>行程规划</span>
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <header
        id="overview"
        className="mx-auto max-w-3xl scroll-mt-24 px-5 pb-8 pt-8 text-center sm:px-8 sm:pt-10 reveal-up"
      >
        <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-primary-200/80 bg-primary-50/90 px-3.5 py-1 text-xs font-semibold tracking-wide text-primary-800 shadow-2xs">
          <i className="fa-solid fa-map-pin text-primary-600 text-[11px]" />
          <span>{city} · {result.request.days ? `${result.request.days} 天` : ""}{people ? ` · ${people} 人` : ""}{timePrefText ? ` · ${timePrefText}` : ""}</span>
        </div>
        <h1 className="font-display mb-4 text-3xl font-extrabold leading-tight tracking-tight text-gray-900 sm:text-5xl">
          {plan.title}
        </h1>
        {cleanSummary(plan.summary) && (
          <p className="mx-auto mb-6 max-w-2xl text-base leading-relaxed text-gray-600 sm:text-lg">
            “{cleanSummary(plan.summary)}”
          </p>
        )}
        <div className="flex flex-wrap justify-center gap-2">
          {cleanTags(plan.tags).map((tag) => (
            <span
              key={tag}
              className="rounded-full border border-primary-200/80 bg-white px-3 py-1 text-xs font-medium text-primary-800 shadow-2xs"
            >
              {tag}
            </span>
          ))}
          {plan.pace?.level && (
            <span className="rounded-full border border-accent-200 bg-accent-50 px-3 py-1 text-xs font-medium text-accent-700 shadow-2xs">
              节奏 {PACE_LABEL[plan.pace.level] ?? plan.pace.level}
            </span>
          )}
          {heroCostStatus.costText && heroCostStatus.costText !== "选择交通方式查看预估" && (
            <a
              href="#cost-estimate"
              onClick={(e) => {
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
                e.preventDefault();
                scrollTo("cost-estimate");
              }}
              className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 transition-colors hover:bg-emerald-100 flex xl:hidden items-center gap-1.5 shadow-2xs"
            >
              <span>
                {activeScenario?.label
                  ? `${activeScenario.label} · ${heroCostStatus.costText}`
                  : heroCostStatus.costText}
              </span>
              {heroCostStatus.costBadge && (
                <span className="rounded bg-amber-100 px-1.5 py-0.2 text-[10px] font-bold text-amber-800">
                  {heroCostStatus.costBadge}
                </span>
              )}
            </a>
          )}
          <span className="rounded-full border border-sand-200 bg-white px-3 py-1 text-xs text-gray-500 shadow-2xs">
            {plan.days.length} 日行程
          </span>
        </div>
      </header>

      {/* 必去地点异常提醒 banner */}
      <MustIncludeNotice items={result.must_include} />

      {/* 第二层：随屏吸顶工具栏（GSAP 物理弹性驱动 back.out(1.4) 缓动滑出） */}
      <div className="sticky top-0 z-40 border-b border-gray-100 bg-sand-50/95 shadow-sm shadow-gray-900/5 backdrop-blur-xl">
        <div className="flex h-14 w-full items-center justify-between gap-3 px-5 sm:px-10 lg:px-14">
          {/* 左侧：桌面端 GSAP 物理弹性滑出 Logo 与全局导航 */}
          <div
            ref={leftBrandRef}
            className="hidden md:flex shrink-0 items-center space-x-6 opacity-0"
            style={{ transform: "translateX(-16px) scale(0.9)" }}
          >
            <Link to="/" className="flex items-center space-x-2">
              <img src="/logo.svg" alt="云途 YunTu" className="h-7 w-7" />
              <span className="text-base font-black tracking-tight text-gray-900">
                云途 <span className="font-light text-emerald-600 text-xs">YunTu</span>
              </span>
            </Link>

            <div className="hidden lg:flex items-center space-x-2 text-xs font-semibold">
              <Link
                to="/"
                className="inline-flex items-center gap-1.5 text-gray-600 hover:text-gray-900 px-2.5 py-1 rounded-lg hover:bg-sand-100 transition-colors"
              >
                <i className="fa-solid fa-compass text-gray-400 text-[11px]" />
                <span>行程规划</span>
              </Link>
            </div>
          </div>

          {/* 中间：章节胶囊 Tab 切换（移动端占据左侧主区支持横滑，桌面端居中） */}
          <div className="flex flex-1 min-w-0 items-center justify-start md:justify-center">
            <div className="flex items-center gap-1.5 overflow-x-auto hide-scrollbar py-1 w-full md:w-auto">
              {(
                [
                  ["overview", "概览"],
                  ...plan.days.map((d) => [`day-${d.day}`, `第 ${d.day} 天`]),
                  ["cost-estimate", "出行费用"],
                ] as [string, string][]
              ).map(([id, label]) => (
                <button
                  key={id}
                  id={`nav-tab-${id}`}
                  type="button"
                  onClick={() => scrollTo(id)}
                  className={`shrink-0 rounded-full px-3 py-1 sm:px-3.5 text-[11px] font-bold tracking-wide transition-all duration-250 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 ${
                    activeTab === id
                      ? "bg-gray-900 text-white shadow-md"
                      : "text-gray-600 hover:bg-gray-200/60 hover:text-gray-900"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* 右侧：动作按钮 (PDF / 分享) */}
          <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
            <button
              type="button"
              className="flex h-8 items-center justify-center gap-1 rounded-full border border-gray-200 bg-white px-2.5 sm:px-3 text-[11px] font-bold text-gray-700 shadow-2xs transition-all hover:border-gray-300 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
              title="导出 PDF"
              disabled={pdf.loading}
              onClick={() => pdf.start()}
            >
              <i
                className={`fas ${pdf.loading ? "fa-spinner fa-spin" : "fa-file-pdf"} text-red-500`}
                aria-hidden="true"
              />
              <span className="hidden xs:inline sm:inline">{pdf.loading ? "导出中" : "PDF"}</span>
            </button>
            <button
              type="button"
              className="flex h-8 items-center justify-center gap-1.5 rounded-full bg-primary-600 px-2.5 sm:px-3.5 text-[11px] font-bold text-white shadow-md shadow-primary-600/20 transition-all hover:scale-105 hover:bg-primary-700"
              title="分享 AI 长图"
              onClick={() => setShareOpen(true)}
            >
              <i className="fas fa-sparkles text-primary-200" aria-hidden="true" />
              <span className="hidden sm:inline">分享 AI 长图</span>
              <span className="sm:hidden">分享</span>
            </button>

          </div>
        </div>
      </div>

      <div className="mx-auto max-w-6xl px-4 sm:px-8 py-10 pb-36 sm:py-14 flex flex-col xl:flex-row items-start justify-center gap-8 min-w-0">
        <main className="w-full max-w-3xl space-y-10 shrink-0 min-w-0 order-1 xl:order-2">
          {result.weather && (
            <section className="reveal-up xl:hidden">
              <WeatherStrip data={result.weather} />
            </section>
          )}

          {plan.days.map((day, dayIndex) => {
            const weatherLabel = dayWeatherLabel(day.day, weatherDays);

            return (
              <section
                key={day.day}
                id={`day-${day.day}`}
                className="scroll-mt-24"
              >
                <div className="relative overflow-hidden rounded-3xl bg-white p-6 sm:p-8 shadow-card border border-sand-200/80 transition-shadow hover:shadow-card-hover">
                  {/* 扉页顶栏：Day 标签 + 气象胶囊 */}
                  <div className="relative z-10 mb-4 flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2.5">
                      <span className="flex items-center gap-1.5 rounded-full bg-primary-600 px-3 py-1 font-display text-xs font-bold text-white shadow-xs tracking-wider">
                        <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-300 animate-pulse" />
                        DAY {String(day.day).padStart(2, "0")}
                      </span>
                      <span className="text-xs font-medium text-gray-500">
                        共 {day.places.length} 处漫游点
                      </span>
                    </div>

                    {weatherLabel && (
                      <span className="flex items-center gap-1.5 rounded-full border border-amber-200/80 bg-amber-50/90 px-3 py-1 text-xs font-semibold text-amber-800 shadow-2xs">
                        <i className="fa-solid fa-cloud-sun text-amber-500 text-xs" />
                        <span>{weatherLabel}</span>
                      </span>
                    )}
                  </div>

                  {/* 每日主题大标题 */}
                  <h2 className="relative z-10 text-2xl sm:text-3xl font-extrabold text-gray-900 tracking-tight mb-4">
                    {day.title}
                  </h2>

                  {/* 封面画报大图 */}
                  {cityCovers.length > 0 && (
                    <div className="relative z-10 mb-5 h-48 sm:h-60 w-full overflow-hidden rounded-2xl shadow-soft group">
                      <img
                        src={cityCovers[dayIndex % cityCovers.length]}
                        alt={`${city} 第 ${day.day} 天`}
                        loading={dayIndex === 0 ? "eager" : "lazy"}
                        className="h-full w-full object-cover transition-transform duration-700 ease-out group-hover:scale-105"
                      />
                      <div className="absolute inset-0 bg-gradient-to-t from-gray-950/40 via-transparent to-transparent pointer-events-none" />
                      <span className="absolute bottom-3 left-3 text-[11px] font-medium text-white/95 bg-black/40 backdrop-blur-md px-2.5 py-1 rounded-full flex items-center gap-1">
                        <i className="fa-solid fa-location-dot text-[10px] text-emerald-300" />
                        <span>{city} · 第 {day.day} 天实景印象</span>
                      </span>
                    </div>
                  )}

                  {/* 主编手账便签 */}
                  {day.narrative && (
                    <div className="relative z-10 mb-8 rounded-2xl border border-sand-200 bg-sand-50/85 p-4 sm:p-5">
                      <div className="mb-2 flex items-center gap-2 text-xs font-bold tracking-wider text-primary-800 uppercase">
                        <span className="flex h-5 w-5 items-center justify-center rounded-md bg-primary-600 text-white shadow-2xs">
                          <i className="fa-solid fa-feather-pointed text-[10px]" aria-hidden="true" />
                        </span>
                        <span>主编手账 · 路线要领</span>
                      </div>
                      <p className="text-sm sm:text-base leading-relaxed text-gray-700">
                        {day.narrative}
                      </p>
                      {day.commute_summary && (
                        <div className="mt-3 flex items-center gap-2 border-t border-sand-200/80 pt-2.5 text-xs text-primary-800 font-medium">
                          <i className="fas fa-route text-primary-500" aria-hidden="true" />
                          <span>全天出行参考：{day.commute_summary}</span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* 景点时间轴主干 */}
                  <div className="relative z-10 space-y-5">
                    <AccommodationTimelineNode
                      accommodation={plan.accommodation}
                      day={day.day}
                      onLocationClick={() => {
                        setShowMap(true);
                        setActivePlaceId(null);
                      }}
                    />

                    {day.places.map((place, placeIndex) => {
                      const nextLeg = day.commute_legs?.find(
                        (l) => l.from_place_id === place.place_id,
                      );
                      const isLast = placeIndex === day.places.length - 1;
                      const anchor = isAnchorRole(place.role);
                      const timeLabel = placeTimeLabel(place);
                      const stayDuration = formatStayDuration(place.stay_minutes);
                      const scheduledMustInclude = result.must_include?.find(
                        (mi) => mi.status === "scheduled" && mi.place_id != null && mi.place_id === place.place_id,
                      );

                      const fromPlace = place;
                      const toPlace = nextLeg ? day.places.find((p) => p.place_id === nextLeg.to_place_id) : undefined;
                      const legKey = nextLeg ? `day-${day.day}-leg-${place.place_id}-${nextLeg.to_place_id}` : "";
                      const isLegExpanded = legKey ? expandedCommutes.has(legKey) : false;

                      return (
                        <div key={place.place_id} className="relative">
                          {/* 时间轴竖导轨 */}
                          {!isLast && (
                            <div
                              className="absolute left-5 sm:left-6 top-14 bottom-0 w-0.5 bg-gradient-to-b from-primary-300 via-sand-300 to-sand-200"
                              aria-hidden="true"
                            />
                          )}

                          {/* 景点节点卡片（纯净统一的手账质感白卡） */}
                          <div
                            onClick={() => openPlace(place.place_id)}
                            className={`group relative flex flex-col rounded-2xl border transition-all duration-200 p-4 sm:p-5 cursor-pointer ${
                              activePlaceId === place.place_id
                                ? "border-primary-500 bg-primary-50/50 shadow-md ring-2 ring-primary-300/60"
                                : anchor
                                ? "border-sand-200/90 bg-white hover:border-primary-300 hover:shadow-md"
                                : "border-gray-100 bg-sand-50/40 hover:border-primary-200 hover:bg-white hover:shadow-sm"
                            }`}
                          >
                            {/* 头部：序号 + 标题 + 右侧属性 */}
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <div className="flex min-w-0 items-center gap-3">
                                <span
                                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl font-display text-sm font-bold shadow-xs ${
                                    anchor
                                      ? "bg-gradient-to-br from-primary-600 to-emerald-600 text-white ring-2 ring-primary-100"
                                      : "bg-sand-100 text-gray-700 border border-sand-200"
                                  }`}
                                >
                                  {String(placeIndex + 1).padStart(2, "0")}
                                </span>
                                <div className="min-w-0">
                                  <div className="flex items-center gap-2">
                                    <span className="text-base" aria-hidden="true">
                                      {categoryIcon(place.category)}
                                    </span>
                                    <h3 className="truncate text-lg font-bold text-gray-900 transition-colors group-hover:text-primary-700">
                                      {place.name}
                                    </h3>
                                    {scheduledMustInclude && (
                                      <span className="shrink-0 rounded-md bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 text-[10px] font-bold text-emerald-700">
                                        你的必去
                                      </span>
                                    )}
                                    {place.optional && (
                                      <span className="shrink-0 rounded-md bg-amber-50 border border-amber-200 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                                        可选
                                      </span>
                                    )}
                                    {!anchor && (
                                      <span className="shrink-0 rounded-md bg-sand-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-500">
                                        惬意小憩
                                      </span>
                                    )}
                                  </div>

                                  {/* 分类与时段标签 */}
                                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-500">
                                    <span className="font-medium text-gray-600">
                                      {categoryName(place.category)}
                                    </span>
                                    {timeLabel && (
                                      <>
                                        <span className="text-gray-300">·</span>
                                        <span className="text-primary-700 font-medium">{timeLabel}</span>
                                      </>
                                    )}
                                  </div>
                                </div>
                              </div>

                              <div className="flex shrink-0 items-center gap-2">
                                <span className="flex items-center gap-1 rounded-full bg-sand-100 border border-sand-200 px-2.5 py-0.5 text-xs font-medium text-gray-600">
                                  <i className="fa-regular fa-clock text-primary-600 text-[11px]" />
                                  <span>{stayDuration}</span>
                                </span>
                                <span className="ml-1 text-xs font-semibold text-primary-600 opacity-0 group-hover:opacity-100 transition-opacity hidden sm:inline-flex items-center gap-0.5">
                                  查看 <i className="fa-solid fa-chevron-right text-[10px]" />
                                </span>
                              </div>
                            </div>

                            {/* 详情与说明描述 */}
                            {(cleanBrief(place.brief) || place.activity_note) && (
                              <div className="mt-3 border-t border-gray-100/90 pt-3 text-sm leading-relaxed">
                                {place.activity_note ? (
                                  <p className="font-normal text-gray-700">{place.activity_note}</p>
                                ) : (
                                  <p className="text-gray-500">{cleanBrief(place.brief)}</p>
                                )}
                              </div>
                            )}
                          </div>

                          {/* 跨点通勤交互微卡片 */}
                          {nextLeg && (
                            <div className="my-3 ml-5 sm:ml-6 space-y-2">
                              {/* 胶囊控制条 */}
                              <div className="flex flex-wrap items-center gap-2">
                                <button
                                  type="button"
                                  onClick={() => toggleCommute(legKey)}
                                  className="group flex items-center gap-2 rounded-full border border-primary-200/90 bg-primary-50/90 px-3 py-1 text-xs font-medium text-primary-800 shadow-2xs transition-all hover:bg-primary-100/90 hover:shadow-xs active:scale-98"
                                  title="点击查看此段详细路线"
                                >
                                  <i className={`fa-solid ${commuteModeIcon(nextLeg.mode)} text-primary-600 text-[11px]`} />
                                  <span>
                                    {commuteModeName(nextLeg.mode)} {formatMinutes(nextLeg.duration_minutes)}
                                  </span>
                                  <span className="text-primary-300">·</span>
                                  <span className="text-primary-700 font-bold">
                                    {formatDistance(nextLeg.distance_meters)}
                                  </span>
                                  {toPlace && (
                                    <span className="ml-1 flex items-center gap-1 text-primary-700 font-semibold group-hover:text-primary-950 transition-colors">
                                      <i className="fa-solid fa-arrow-right text-[9px] text-primary-400" />
                                      <span className="truncate max-w-[120px]">{toPlace.name}</span>
                                      <i className={`fa-solid fa-chevron-down text-[9px] transition-transform duration-200 ${isLegExpanded ? "rotate-180" : ""}`} />
                                    </span>
                                  )}
                                </button>
                              </div>

                              {/* 展开态：详细路线指引卡 */}
                              {isLegExpanded && (
                                <div className="animate-fade-in relative overflow-hidden rounded-2xl border border-primary-200/90 bg-gradient-to-br from-primary-50/95 via-emerald-50/40 to-white p-4 shadow-sm space-y-2.5">
                                  <div className="flex items-center justify-between gap-2 border-b border-primary-100/80 pb-2">
                                    <div className="flex items-center gap-1.5 text-xs font-bold text-gray-800">
                                      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary-100 text-primary-800 text-[10px]">
                                        起
                                      </span>
                                      <span className="truncate max-w-[100px] sm:max-w-[160px]">{fromPlace.name}</span>
                                      <i className="fa-solid fa-arrow-right text-[10px] text-primary-400 mx-1" />
                                      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-100 text-emerald-800 text-[10px]">
                                        终
                                      </span>
                                      <span className="truncate max-w-[100px] sm:max-w-[160px]">{toPlace?.name || "下一站"}</span>
                                    </div>
                                    <span className="shrink-0 text-xs font-bold text-primary-700">
                                      {commuteModeName(nextLeg.mode)}约 {formatMinutes(nextLeg.duration_minutes)}
                                    </span>
                                  </div>

                                  {nextLeg.transit_summary && (
                                    <div className="flex items-start gap-1.5 text-xs text-gray-600 leading-relaxed">
                                      <i className="fa-solid fa-diamond-turn-right text-primary-500 mt-0.5 shrink-0 text-[11px]" />
                                      <span>{nextLeg.transit_summary}</span>
                                    </div>
                                  )}

                                  {fromPlace.longitude != null && fromPlace.latitude != null && toPlace?.longitude != null && toPlace?.latitude != null && (
                                    <div className="pt-1 flex justify-end">
                                      <a
                                        href={`https://uri.amap.com/navigation?from=${fromPlace.longitude},${fromPlace.latitude},${encodeURIComponent(fromPlace.name)}&to=${toPlace.longitude},${toPlace.latitude},${encodeURIComponent(toPlace.name)}&mode=${nextLeg.mode === "walking" ? "walk" : (nextLeg.mode === "transit" ? "bus" : "car")}`}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="inline-flex items-center gap-1 text-[11px] font-semibold text-primary-700 hover:text-primary-900 transition-colors"
                                      >
                                        <i className="fa-solid fa-location-arrow text-[10px]" />
                                        <span>在高德地图中导航此段路线 ↗</span>
                                      </a>
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </section>
            );
          })}

        {/* 出行与费用 附录区 */}
        <section
          id="cost-estimate"
          className="scroll-mt-24 border-t border-primary-100/50 pt-8 reveal-up space-y-8"
        >
          <div className="border-b border-gray-100 pb-3">
            <span className="text-xs font-bold uppercase tracking-widest text-primary-600">
              TRAVEL & COST APPENDIX
            </span>
            <h2 className="font-display text-3xl font-bold text-gray-900">
              出行与费用
            </h2>
          </div>

          {/* 大交通推荐卡片（放在费用模块前面） */}
          {plan.transport && (
            <div className="space-y-2">
              <TransportCard data={plan.transport} />
            </div>
          )}

          {/* 完整费用模块 */}
          <CostEstimateCard
            costEstimate={plan.cost_estimate}
            activeScenarioId={activeScenarioId}
            onScenarioSelect={setActiveScenarioId}
          />
        </section>

        <SafeDeliveryNotice result={result} jobId={jobId} />
      </main>

        {/* 行程脊柱 (PC ≥1280px) 放置在 DOM 顺序后方，但在视觉上呈现在正文左侧并固定跟随滑动 */}
        <div className="order-2 xl:order-1 shrink-0 xl:sticky xl:top-24">
          <TripSpine
            days={plan.days}
            weather={result.weather}
            costEstimate={plan.cost_estimate}
            activeScenarioId={activeScenarioId}
            activeDay={activeDayNumber}
            onDayClick={(dayNum) => scrollTo(`day-${dayNum}`)}
            onCostClick={() => scrollTo("cost-estimate")}
          />
        </div>
      </div>

      {/* 地图 FAB */}
      <div className="fixed bottom-8 right-5 z-50 flex flex-col items-end gap-3 sm:right-8">
        <button
          type="button"
          onClick={() => {
            setShowMap(true);
            setActivePlaceId(dayForMap?.places[0]?.place_id ?? null);
          }}
          className="flex items-center gap-2.5 rounded-full bg-primary-600 py-3.5 pl-5 pr-6 text-white shadow-xl shadow-primary-600/25 transition-transform hover:scale-[1.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 focus-visible:ring-offset-2"
        >
          <i
            className="fas fa-map-marked-alt text-primary-100"
            aria-hidden="true"
          />
          <span className="text-xs font-bold tracking-wide">查看地图</span>
        </button>
      </div>

      {/* 地图浮层 */}
      <div
        onClick={() => setShowMap(false)}
        className={`fixed inset-0 z-[100] flex items-center justify-center p-4 transition-all duration-300 sm:p-6 ${
          showMap
            ? "pointer-events-auto bg-gray-900/60 opacity-100 backdrop-blur-sm"
            : "pointer-events-none opacity-0"
        }`}
        aria-hidden={!showMap}
      >
        <div
          onClick={(e) => e.stopPropagation()}
          className={`flex h-[85vh] w-full max-w-5xl flex-col overflow-hidden rounded-[2rem] border border-white/10 bg-gray-800 shadow-2xl transition-transform duration-300 ${
            showMap ? "translate-y-0 scale-100" : "translate-y-4 scale-95"
          }`}
          role="dialog"
          aria-modal="true"
        >
          <div className="z-10 flex items-center justify-between gap-3 border-b border-white/5 bg-gray-900/60 px-6 py-4 backdrop-blur-md">
            <div className="flex min-w-0 items-center gap-4">
              <h3 className="font-display truncate text-lg font-medium text-white">
                {city} 地图
              </h3>
              <div className="hidden flex-wrap gap-1.5 border-l border-white/10 pl-4 sm:flex">
                {plan.days.map((d) => (
                  <button
                    type="button"
                    key={d.day}
                    onClick={() => setMapDay(d.day)}
                    tabIndex={showMap ? 0 : -1}
                    className={`rounded-full px-3 py-1 text-[11px] font-bold uppercase tracking-widest transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white ${
                      mapDay === d.day
                        ? "bg-primary-500 text-white"
                        : "bg-white/5 text-white/50 hover:bg-white/10 hover:text-white"
                    }`}
                  >
                    第 {d.day} 天
                  </button>
                ))}
              </div>
            </div>
            <button
              type="button"
              onClick={() => setShowMap(false)}
              tabIndex={showMap ? 0 : -1}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white/10 text-white/80 transition-all hover:scale-105 hover:bg-white/20 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
              aria-label="关闭地图"
            >
              <i className="fas fa-times" aria-hidden="true" />
            </button>
          </div>

          <div className="flex gap-2 overflow-x-auto border-b border-white/5 bg-gray-900/40 px-4 py-3 hide-scrollbar sm:hidden">
            {plan.days.map((d) => (
              <button
                type="button"
                key={d.day}
                onClick={() => setMapDay(d.day)}
                tabIndex={showMap ? 0 : -1}
                className={`shrink-0 rounded-full px-3 py-1.5 text-[10px] font-bold uppercase tracking-widest focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white ${
                  mapDay === d.day
                    ? "bg-primary-500 text-white"
                    : "bg-white/5 text-white/50"
                }`}
              >
                第 {d.day} 天
              </button>
            ))}
          </div>

          <div className="relative min-h-0 flex-1 bg-gray-800">
            {dayForMap && (
              <Suspense
                fallback={
                  <div className="flex h-full items-center justify-center text-sm uppercase tracking-widest text-white/40">
                    地图加载中…
                  </div>
                }
              >
                <MapView
                  day={dayForMap}
                  accommodation={plan.accommodation}
                  activePlaceId={activePlaceId}
                  onMarkerClick={(id) => openPlace(id)}
                />
              </Suspense>
            )}
          </div>

          <div className="border-t border-white/5 bg-gray-900/60 px-6 py-2 backdrop-blur-md">
            <p className="text-center text-[10px] uppercase tracking-widest text-white/40">
              点击标记查看地点详情
            </p>
          </div>
        </div>
      </div>

      <PlaceDetailModal
        place={detailPlace}
        isMustInclude={Boolean(
          detailPlace &&
            result?.must_include?.some(
              (mi) => mi.status === "scheduled" && mi.place_id != null && mi.place_id === detailPlace.place_id,
            ),
        )}
        onClose={() => setDetailPlace(null)}
      />
      {resultId && (
        <ShareDialog
          open={shareOpen}
          onClose={() => setShareOpen(false)}
          recordId={resultId}
          jobId={jobId ?? undefined}
        />
      )}
    </div>
  );
}
