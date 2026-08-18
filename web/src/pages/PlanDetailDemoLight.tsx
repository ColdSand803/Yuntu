/**
 * 详情页杂志阅读 demo（云途化）
 * - 单栏 Day 叙事 + sticky 日导航 + 地图浮层
 * - 数据：v0812 重庆 fixture + CostEstimateCard + 本城封面图
 * 访问：/demo/detail-light
 * 不改正式 PlanDetailPage
 */
import { useEffect, useState, lazy, Suspense, useRef } from "react";
import { Link } from "react-router-dom";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

import { V0812_FIXTURES } from "@/fixtures/v0812";
import { getCityPhotoUrls } from "@/components/input/RotatingBackground";
import { CostEstimateCard } from "@/components/detail/CostEstimateCard";
import { MustIncludeNotice } from "@/components/detail/MustIncludeNotice";
import { PlaceDetailModal } from "@/components/detail/PlaceDetailModal";
import { ShareDialog } from "@/components/share/ShareDialog";
import { useArtifact } from "@/hooks/useArtifact";
import { saveBlob } from "@/utils/download";
import { showToast } from "@/stores/toastStore";
import { weatherIcon } from "@/constants/weather";
import {
  formatDistance,
  formatMinutes,
  commuteModeName,
  commuteModeIcon,
} from "@/utils/format";
import type { TripDay, TripPlace, TripPlan, WeatherDay } from "@/types/trip";

gsap.registerPlugin(ScrollTrigger);

const MapView = lazy(() =>
  import("@/components/detail/MapView").then((m) => ({ default: m.MapView })),
);

const fixture = V0812_FIXTURES["v15-notime"];
const result = fixture.result;
const plan: TripPlan = result.plans[0];
const city = result.city.name;
const people = result.request.people_count ?? 1;
const cityCovers = getCityPhotoUrls(city, 4);
/** artifact / 地点详情接口用的 record id（demo fixture 若后端无此 id 会 404 降级） */
const recordId = String(result.result_id);

const PACE_LABEL: Record<string, string> = {
  RELAXED: "轻松",
  MODERATE: "适中",
  PACKED: "紧凑",
};

/** fixture 无天气时的展示降级（仅 demo） */
const FALLBACK_WEATHER = ["☀️ 28°C", "⛅ 26°C", "☁️ 24°C", "🌧️ 22°C", "🌤️ 27°C"];

function dayWeatherLabel(day: number, weatherDays: WeatherDay[] | undefined, fallbackIndex: number): string {
  const w = weatherDays?.find((d) => d.day === day);
  if (w) {
    return `${weatherIcon(w.icon_code)} ${w.temp_max_c}°C`;
  }
  return FALLBACK_WEATHER[fallbackIndex % FALLBACK_WEATHER.length];
}

const PERIOD_LABEL: Record<string, string> = {
  morning: "上午",
  afternoon: "下午",
  evening: "傍晚",
  night: "夜间",
};

function placeTimeLabel(place: TripPlace): string | null {
  const s = place.schedule;
  if (!s) return null;
  if (s.exact_start) {
    return s.exact_end ? `${s.exact_start} – ${s.exact_end}` : s.exact_start;
  }
  if (s.period && PERIOD_LABEL[s.period]) return PERIOD_LABEL[s.period];
  return null;
}

export default function PlanDetailDemoLight() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [activeTab, setActiveTab] = useState("overview");
  const [showMap, setShowMap] = useState(false);
  const [mapDay, setMapDay] = useState(1);
  const [activePlaceId, setActivePlaceId] = useState<number | null>(null);
  const [detailPlace, setDetailPlace] = useState<TripPlace | null>(null);
  const [shareOpen, setShareOpen] = useState(false);
  const [activeScenarioId, setActiveScenarioId] = useState<string | null>(null);

  const pdf = useArtifact(recordId, "pdf");
  const weatherDays =
    result.weather?.status === "ok" && result.weather.days.length > 0
      ? result.weather.days
      : undefined;

  // GSAP ScrollTrigger 微动效
  useEffect(() => {
    const timeout = setTimeout(() => {
      const ctx = gsap.context(() => {
        const revealElements = gsap.utils.toArray<HTMLElement>(".reveal-up");
        revealElements.forEach((el) => {
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

        const parallaxImages = gsap.utils.toArray<HTMLElement>(".parallax-img");
        parallaxImages.forEach((img) => {
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
  }, []);

  // Escape 关地图
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && showMap) setShowMap(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [showMap]);

  // PDF 就绪 → 下载
  const pdfReset = pdf.reset;
  useEffect(() => {
    if (pdf.phase === "ready" && pdf.blob && pdf.artifact) {
      saveBlob(pdf.blob, pdf.artifact.filename);
      showToast("PDF 已导出");
      pdfReset();
    }
  }, [pdf.phase, pdf.blob, pdf.artifact, pdfReset]);

  useEffect(() => {
    if (pdf.phase === "failed") {
      showToast(pdf.error?.message ?? "导出失败，请重试", "error");
    }
  }, [pdf.phase, pdf.error]);

  const dayForMap: TripDay =
    plan.days.find((d) => d.day === mapDay) ?? plan.days[0];

  function openPlace(placeId: number) {
    setActivePlaceId(placeId);
    const found =
      plan.days.flatMap((d) => d.places).find((p) => p.place_id === placeId) ??
      null;
    if (found) {
      // 地图 z-100 高于 PlaceDetailModal z-50，从地图点开时先收起地图
      setShowMap(false);
      setDetailPlace(found);
    }
  }

  const scrollTo = (id: string) => {
    setActiveTab(id);
    if (id.startsWith("day-")) {
      const n = Number(id.replace("day-", ""));
      if (!Number.isNaN(n)) setMapDay(n);
    }
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  // 🐛 FIX 5: 简易 scroll spy 改为 IntersectionObserver
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const id = entry.target.id;
            setActiveTab(id);
            if (id.startsWith("day-")) {
              const n = Number(id.replace("day-", ""));
              if (!Number.isNaN(n)) setMapDay(n);
            }
          }
        });
      },
      { rootMargin: "-120px 0px -50% 0px", threshold: 0 }
    );

    const ids = ["overview", ...plan.days.map((d) => `day-${d.day}`), "cost-estimate"];
    ids.forEach((id) => {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    });

    return () => observer.disconnect();
  }, []);

  return (
    <div ref={containerRef} className="min-h-screen bg-sand-50 font-body text-gray-800 selection:bg-primary-100">
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
        className="mx-auto max-w-3xl scroll-mt-24 px-5 pb-12 pt-28 text-center sm:px-8 sm:pt-32 reveal-up"
      >
        <p className="mb-3 text-xs font-medium tracking-widest text-primary-600">
          {city}
          {result.request.days ? ` · ${result.request.days} 天` : ""}
          {people ? ` · ${people} 人` : ""}
        </p>
        <h1 className="font-display mb-4 text-3xl font-bold leading-tight tracking-tight text-gray-900 sm:text-5xl">
          {plan.title}
        </h1>
        <p className="mx-auto mb-6 max-w-2xl text-base leading-relaxed text-gray-600 sm:text-lg">
          {plan.summary}
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          {plan.tags.map((tag) => (
            <span
              key={tag}
              className="rounded-full border border-primary-200 bg-primary-50/80 px-3 py-1 text-xs font-medium text-primary-700"
            >
              {tag}
            </span>
          ))}
          {plan.pace?.level && (
            <span className="rounded-full border border-accent-200 bg-accent-50 px-3 py-1 text-xs font-medium text-accent-700">
              节奏 {PACE_LABEL[plan.pace.level] ?? plan.pace.level}
            </span>
          )}
          <span className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs text-gray-500">
            {plan.days.length} 日行程
          </span>
        </div>
      </header>

      {/* Sticky 日导航 & 操作栏 */}
      <div className="sticky top-0 z-40 bg-sand-50/80 backdrop-blur-xl shadow-sm shadow-gray-900/5">
        <div className="mx-auto max-w-4xl px-5 sm:px-8 flex items-center justify-between">
          <div className="flex min-w-0 overflow-x-auto hide-scrollbar items-center gap-2 py-3.5 pr-4">
            <button
              type="button"
              onClick={() => scrollTo("overview")}
              className={`text-[11px] font-bold uppercase tracking-widest transition-all duration-300 rounded-full px-4 py-1.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 ${
                activeTab === "overview"
                  ? "bg-gray-900 text-white shadow-md"
                  : "text-gray-400 hover:text-gray-800 hover:bg-gray-200/50"
              }`}
            >
              OVERVIEW
            </button>
            {plan.days.map((day) => (
              <button
                type="button"
                key={day.day}
                onClick={() => scrollTo(`day-${day.day}`)}
                className={`text-[11px] font-bold uppercase tracking-widest transition-all duration-300 rounded-full px-4 py-1.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 ${
                  activeTab === `day-${day.day}`
                    ? "bg-gray-900 text-white shadow-md"
                    : "text-gray-400 hover:text-gray-800 hover:bg-gray-200/50"
                }`}
              >
                DAY {day.day.toString().padStart(2, '0')}
              </button>
            ))}
            <button
              type="button"
              onClick={() => scrollTo("cost-estimate")}
              className={`text-[11px] font-bold uppercase tracking-widest transition-all duration-300 rounded-full px-4 py-1.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 ${
                activeTab === "cost-estimate"
                  ? "bg-gray-900 text-white shadow-md"
                  : "text-gray-400 hover:text-gray-800 hover:bg-gray-200/50"
              }`}
            >
              COST
            </button>
          </div>
          
          {/* PDF + 分享 AI 图（对接 useArtifact / ShareDialog） */}
          <div className="flex items-center gap-2 shrink-0 border-l border-gray-200/60 pl-3 sm:pl-5 ml-1 sm:ml-2">
            <button
              type="button"
              className="hidden sm:flex h-8 items-center justify-center gap-2 rounded-full border border-gray-300 bg-white px-3 sm:px-4 text-[11px] font-bold uppercase tracking-widest text-gray-700 shadow-sm transition-all hover:bg-gray-50 hover:border-gray-400 disabled:cursor-not-allowed disabled:opacity-60"
              title="导出 PDF"
              disabled={pdf.loading}
              onClick={() => pdf.start()}
            >
              <i
                className={`fas ${pdf.loading ? "fa-spinner fa-spin" : "fa-file-pdf"} text-gray-400`}
                aria-hidden="true"
              />
              <span>{pdf.loading ? "导出中" : "PDF"}</span>
            </button>
            <button
              type="button"
              className="flex h-8 items-center justify-center gap-1.5 rounded-full bg-primary-600 px-3 sm:px-4 text-[11px] font-bold tracking-wide text-white shadow-md shadow-primary-600/20 transition-all hover:bg-primary-700 hover:scale-105"
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

      <main className="mx-auto max-w-3xl space-y-24 px-5 py-10 pb-36 sm:px-8 sm:py-14">
        {plan.days.map((day, dayIndex) => (
          <section
            key={day.day}
            id={`day-${day.day}`}
            className="scroll-mt-24"
          >
            {/* Day 头图：本城图轮换 */}
            <div className="mb-8 reveal-up">
              <div className="mb-5 flex flex-col items-start gap-1.5">
                <span className="font-display text-[11px] font-bold uppercase tracking-[0.2em] text-gray-500">
                  Day {day.day.toString().padStart(2, "0")}{" "}
                  <span className="text-gray-300 mx-1">|</span>{" "}
                  {dayWeatherLabel(day.day, weatherDays, dayIndex)}
                </span>
                <h2 className="text-3xl font-bold text-gray-900 sm:text-4xl">
                  {day.title}
                </h2>
              </div>
              <div className="mb-5 aspect-[2.2/1] w-full overflow-hidden rounded-2xl shadow-soft">
                {/* 🐛 FIX 3: Lazy load below the fold images */}
                <img
                  src={cityCovers[dayIndex % cityCovers.length]}
                  alt={`${city} 第 ${day.day} 天`}
                  loading={dayIndex === 0 ? "eager" : "lazy"}
                  className="h-[120%] w-full -mt-[10%] object-cover parallax-img"
                />
              </div>
              {day.narrative && (
                <p className="text-base leading-relaxed text-gray-600">{day.narrative}</p>
              )}
              {day.commute_summary && (
                <p className="mt-2 text-xs text-gray-400">
                  <i className="fas fa-route mr-1.5 text-primary-500" aria-hidden="true" />
                  {day.commute_summary}
                </p>
              )}
            </div>

            {/* 地点流（无时间轴线） */}
            <div className="space-y-12 sm:space-y-14 mt-10">
              {day.places.map((place, placeIndex) => {
                const nextLeg = day.commute_legs?.find(
                  (l) => l.from_place_id === place.place_id,
                );
                const timeLabel = placeTimeLabel(place);
                return (
                  <div key={place.place_id} className="relative reveal-up">
                    <div className="mb-2 flex flex-wrap items-center gap-3 sm:gap-4">
                      <span className="font-display text-2xl sm:text-3xl text-primary-200 font-bold opacity-60 tabular-nums leading-none">
                        {(placeIndex + 1).toString().padStart(2, "0")}
                      </span>
                      <button
                        type="button"
                        onClick={() => openPlace(place.place_id)}
                        className="group text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 rounded"
                      >
                        <h3 className="text-xl font-bold text-gray-900 sm:text-2xl leading-none transition-colors group-hover:text-primary-700">
                          {place.name}
                          <i
                            className="fas fa-chevron-right ml-2 text-[10px] text-gray-300 transition-colors group-hover:text-primary-500"
                            aria-hidden="true"
                          />
                        </h3>
                      </button>
                      {place.optional && (
                        <span className="rounded border border-gray-200 px-1.5 py-0.5 text-[10px] text-gray-400">
                          可选
                        </span>
                      )}
                      {timeLabel && (
                        <span className="rounded-full bg-primary-50 px-2 py-0.5 text-[11px] font-medium text-primary-700">
                          {timeLabel}
                        </span>
                      )}
                    </div>
                    
                    <div className="pl-[2.25rem] sm:pl-[2.75rem]">
                      {place.brief && (
                        <p className="mb-2 text-sm text-gray-500">{place.brief}</p>
                      )}
                      {place.activity_note && (
                        <p className="text-sm leading-relaxed text-gray-600">
                          {place.activity_note}
                        </p>
                      )}
                    </div>

                    {nextLeg && (
                      <div className="mt-6 ml-[2.25rem] sm:ml-[2.75rem] flex flex-wrap items-center gap-2.5 border-t border-primary-100/60 pt-4 text-[13px] text-primary-700/70">
                        <i
                          className={`fa-solid ${commuteModeIcon(nextLeg.mode)} text-primary-400`}
                          aria-hidden="true"
                        />
                        <span className="font-medium tracking-wide">
                          {commuteModeName(nextLeg.mode)} ·{" "}
                          {formatMinutes(nextLeg.duration_minutes)}
                        </span>
                        <span className="text-gray-300">·</span>
                        <span className="text-gray-500">
                          {formatDistance(nextLeg.distance_meters)}
                        </span>
                        {nextLeg.transit_summary && (
                          <span className="w-full text-xs text-gray-400 sm:w-auto">
                            {nextLeg.transit_summary}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        ))}

        {/* 费用与必去通知 */}
        <section id="cost-estimate" className="scroll-mt-24 pt-6 border-t border-primary-100/50 reveal-up">
          <CostEstimateCard
            costEstimate={plan.cost_estimate}
            activeScenarioId={activeScenarioId}
            onScenarioSelect={setActiveScenarioId}
          />
        </section>
        {result.must_include && (
          <MustIncludeNotice items={result.must_include} />
        )}
      </main>

      {/* 看地图 FAB (Solo) */}
      <div className="fixed bottom-8 right-5 z-50 flex flex-col items-end gap-3 sm:right-8">
        <button
          type="button"
          onClick={() => {
            setShowMap(true);
            setActivePlaceId(dayForMap.places[0]?.place_id ?? null);
          }}
          className="flex items-center gap-2.5 rounded-full bg-primary-600 py-3.5 pl-5 pr-6 text-white shadow-xl shadow-primary-600/25 transition-transform hover:scale-[1.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 focus-visible:ring-offset-2"
        >
          <i className="fas fa-map-marked-alt text-primary-100" aria-hidden="true" />
          <span className="text-xs font-bold tracking-wide">查看地图</span>
        </button>
      </div>

      {/* 🐛 FIX 1: 地图浮层：常驻加载，通过 CSS 控制显隐 */}
      <div 
        onClick={() => setShowMap(false)}
        className={`fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6 transition-all duration-300 ${
          showMap 
            ? "bg-gray-900/60 backdrop-blur-sm opacity-100 pointer-events-auto" 
            : "opacity-0 pointer-events-none"
        }`}
        aria-hidden={!showMap}
      >
        <div 
          onClick={(e) => e.stopPropagation()}
          className={`flex flex-col w-full max-w-5xl h-[85vh] bg-gray-800 rounded-[2rem] shadow-2xl border border-white/10 overflow-hidden transition-transform duration-300 ${
            showMap ? "scale-100 translate-y-0" : "scale-95 translate-y-4"
          }`}
          role="dialog"
          aria-modal="true"
        >
          {/* Header */}
          <div className="flex items-center justify-between gap-3 px-6 py-4 bg-gray-900/60 backdrop-blur-md z-10 border-b border-white/5">
            <div className="min-w-0 flex items-center gap-4">
              <h3 className="font-display truncate text-lg text-white font-medium">
                {city} Map
              </h3>
              <div className="hidden sm:flex flex-wrap gap-1.5 pl-4 border-l border-white/10">
                {plan.days.map((d) => (
                  <button
                    type="button"
                    key={d.day}
                    onClick={() => setMapDay(d.day)}
                    tabIndex={showMap ? 0 : -1}
                    className={`rounded-full px-3 py-1 text-[11px] font-bold tracking-widest uppercase transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white ${
                      mapDay === d.day
                        ? "bg-primary-500 text-white"
                        : "bg-white/5 text-white/50 hover:bg-white/10 hover:text-white"
                    }`}
                  >
                    Day {d.day.toString().padStart(2, '0')}
                  </button>
                ))}
              </div>
            </div>
            <button
              type="button"
              onClick={() => setShowMap(false)}
              tabIndex={showMap ? 0 : -1}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white/10 text-white/80 transition-all hover:bg-white/20 hover:scale-105 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
              aria-label="关闭地图"
            >
              <i className="fas fa-times" aria-hidden="true" />
            </button>
          </div>

          {/* Mobile Tabs */}
          <div className="flex sm:hidden overflow-x-auto hide-scrollbar gap-2 px-4 py-3 bg-gray-900/40 border-b border-white/5">
            {plan.days.map((d) => (
              <button
                type="button"
                key={d.day}
                onClick={() => setMapDay(d.day)}
                tabIndex={showMap ? 0 : -1}
                className={`rounded-full px-3 py-1.5 shrink-0 text-[10px] font-bold tracking-widest uppercase focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white ${
                  mapDay === d.day
                    ? "bg-primary-500 text-white"
                    : "bg-white/5 text-white/50"
                }`}
              >
                Day {d.day.toString().padStart(2, '0')}
              </button>
            ))}
          </div>

          {/* Map Area */}
          <div className="relative flex-1 min-h-0 bg-gray-800">
            <Suspense
              fallback={
                <div className="flex h-full items-center justify-center text-sm text-white/40 tracking-widest uppercase">
                  Loading Map...
                </div>
              }
            >
              <MapView
                day={dayForMap}
                activePlaceId={activePlaceId}
                onMarkerClick={(id) => openPlace(id)}
              />
            </Suspense>
          </div>

          {/* Footer */}
          <div className="px-6 py-2 bg-gray-900/60 backdrop-blur-md border-t border-white/5">
            <p className="text-center text-[10px] uppercase tracking-widest text-white/40">
              点击标记查看详情 · Demo：{fixture.title}
            </p>
          </div>
        </div>
      </div>

      {/* 地点详情（与正式页同一弹层） */}
      <PlaceDetailModal
        place={detailPlace}
        isMustInclude={Boolean(
          detailPlace &&
            result.must_include?.some(
              (mi) => mi.status === "scheduled" && mi.place_id != null && mi.place_id === detailPlace.place_id,
            ),
        )}
        onClose={() => setDetailPlace(null)}
      />

      {/* 分享 AI 图 */}
      <ShareDialog
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        recordId={recordId}
      />
    </div>
  );
}
