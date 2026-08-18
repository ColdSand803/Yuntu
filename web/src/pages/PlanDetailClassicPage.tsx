/**
 * 旧三栏详情页（工具型：行程 / 地图 / 概览并排）
 * 新杂志详情已切到 PlanDetailPage；本页仅作对照保留。
 * 访问：/demo/detail-classic
 */
import { useEffect, useMemo, useState, lazy, Suspense } from "react";
import { useNavigate } from "react-router-dom";
import { Timeline } from "@/components/detail/Timeline";
import { PlaceDetailModal } from "@/components/detail/PlaceDetailModal";
import { CostEstimateCard } from "@/components/detail/CostEstimateCard";
import { WeatherCard } from "@/components/detail/WeatherCard";
import { MustIncludeNotice } from "@/components/detail/MustIncludeNotice";
import { ShareDialog } from "@/components/share/ShareDialog";
import { V0812_FIXTURES } from "@/fixtures/v0812";
import { useArtifact } from "@/hooks/useArtifact";
import { saveBlob } from "@/utils/download";
import { showToast } from "@/stores/toastStore";
import { formatDistance, formatMinutes, commuteModeIcon } from "@/utils/format";
import { timePreferencesLabel } from "@/utils/schedule";
import type { TripPlace } from "@/types/trip";

const MapView = lazy(() =>
  import("@/components/detail/MapView").then((m) => ({ default: m.MapView })),
);

const result = V0812_FIXTURES["v15-notime"].result;
const plan = result.plans[0];
const recordId = String(result.result_id);

export default function PlanDetailClassicPage() {
  const navigate = useNavigate();
  const [selectedDay, setSelectedDay] = useState(plan.days[0]?.day ?? 1);
  const [activePlaceId, setActivePlaceId] = useState<number | null>(null);
  const [detailPlace, setDetailPlace] = useState<TripPlace | null>(null);
  const [shareOpen, setShareOpen] = useState(false);
  const [mobileTab, setMobileTab] = useState<"itinerary" | "map" | "overview">(
    "itinerary",
  );
  const pdf = useArtifact(recordId, "pdf");
  const [activeScenarioId, setActiveScenarioId] = useState<string | null>(null);

  const currentDay =
    plan.days.find((d) => d.day === selectedDay) ?? plan.days[0];
  const people = result.request.people_count ?? 1;
  const weather = result.weather ?? null;
  const timePrefText = timePreferencesLabel(
    result.schema_version,
    result.time_preferences,
  );

  const summary = useMemo(() => {
    if (!currentDay) return null;
    const meters = currentDay.commute_legs.reduce(
      (s, l) => s + l.distance_meters,
      0,
    );
    const minutes = currentDay.commute_legs.reduce(
      (s, l) => s + l.duration_minutes,
      0,
    );
    const modeCount = new Map<string, number>();
    for (const l of currentDay.commute_legs) {
      modeCount.set(l.mode, (modeCount.get(l.mode) ?? 0) + 1);
    }
    let mainMode = "driving";
    let max = 0;
    for (const [mode, count] of modeCount) {
      if (count > max) {
        max = count;
        mainMode = mode;
      }
    }
    return {
      distance: formatDistance(meters),
      duration: formatMinutes(minutes),
      spots: currentDay.places.length,
      legs: currentDay.commute_legs.length,
      mainMode,
    };
  }, [currentDay]);

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

  if (!currentDay) return null;

  return (
    <div
      className="flex h-screen flex-col overflow-hidden"
      style={{ backgroundColor: "var(--color-bg-secondary)" }}
    >
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-gray-100 bg-white px-3 py-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-2 sm:gap-4">
          <button
            onClick={() => navigate("/demo")}
            aria-label="返回"
            className="inline-flex shrink-0 items-center gap-1 rounded-lg px-2 py-1.5 text-sm text-sand-500 transition-colors hover:bg-primary-50 hover:text-primary-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
          >
            <i className="fa-solid fa-chevron-left text-xs" aria-hidden="true" />
            <span className="hidden sm:inline">返回 Demo</span>
          </button>
          <div className="min-w-0">
            <h1 className="truncate font-display text-base font-bold text-gray-800 sm:text-lg">
              {plan.title}
            </h1>
            <p className="truncate text-xs text-gray-500">
              {result.city.name} · {result.request.days}天 · {people}人
              {timePrefText ? ` · ${timePrefText}` : ""}
              <span className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                旧版对照
              </span>
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1 text-sm font-medium text-gray-600 sm:gap-4">
          <button
            aria-label="分享"
            onClick={() => setShareOpen(true)}
            className="flex items-center gap-1.5 rounded-lg p-2 text-gray-600 transition-colors hover:bg-primary-50 hover:text-primary-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 sm:p-0"
          >
            <i className="fa-solid fa-share-nodes" aria-hidden="true" />{" "}
            <span className="hidden sm:inline">分享</span>
          </button>
        </div>
      </div>

      <div
        role="tablist"
        aria-label="详情视图"
        className="flex shrink-0 border-b border-gray-100 bg-white lg:hidden"
      >
        {(
          [
            ["itinerary", "fa-route", "行程"],
            ["map", "fa-map-location-dot", "地图"],
            ["overview", "fa-wallet", "概览"],
          ] as const
        ).map(([key, icon, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={mobileTab === key}
            onClick={() => setMobileTab(key)}
            className={`flex flex-1 items-center justify-center gap-2 py-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary-300 ${
              mobileTab === key
                ? "border-b-2 border-primary-600 text-primary-600"
                : "text-gray-500"
            }`}
          >
            <i className={`fa-solid ${icon} text-xs`} aria-hidden="true" />{" "}
            {label}
          </button>
        ))}
      </div>

      <div className="flex flex-1 overflow-hidden">
        <aside
          className={`w-full shrink-0 flex-col gap-4 overflow-y-auto border-r border-gray-100 p-4 lg:flex lg:w-[300px] ${
            mobileTab === "overview" ? "flex" : "hidden"
          }`}
        >
        <CostEstimateCard
          costEstimate={plan.cost_estimate}
          activeScenarioId={activeScenarioId}
          onScenarioSelect={setActiveScenarioId}
        />
        {result.must_include && (
          <MustIncludeNotice items={result.must_include} />
        )}
          {weather && (
            <WeatherCard data={weather} activeDay={selectedDay} />
          )}
          <button
            onClick={pdf.start}
            disabled={pdf.loading}
            className="mt-auto flex w-full items-center justify-center gap-2 rounded-xl bg-primary-600 py-3.5 text-sm font-semibold text-white shadow-md transition-colors hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 focus-visible:ring-offset-2"
          >
            <i
              className={
                pdf.loading
                  ? "fa-solid fa-spinner fa-spin"
                  : "fa-solid fa-download"
              }
              aria-hidden="true"
            />
            {pdf.loading ? "正在导出..." : "导出行程"}
          </button>
        </aside>

        <section
          className={`w-full shrink-0 flex-col border-r border-gray-100 bg-white lg:flex lg:w-[480px] xl:w-[560px] ${
            mobileTab === "itinerary" ? "flex" : "hidden"
          }`}
        >
          <div className="hide-scrollbar flex shrink-0 gap-2 overflow-x-auto border-b border-gray-100 p-3">
            {plan.days.map((d) => {
              const active = selectedDay === d.day;
              return (
                <button
                  key={d.day}
                  onClick={() => {
                    setSelectedDay(d.day);
                    setActivePlaceId(null);
                  }}
                  className={`flex min-w-[68px] shrink-0 flex-col items-center justify-center rounded-xl border px-1.5 py-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 ${
                    active
                      ? "border-primary-600 bg-primary-600 text-white shadow-md"
                      : "border-gray-100 bg-white text-gray-600 hover:bg-gray-50"
                  }`}
                >
                  <span
                    className={`text-[13px] font-bold ${active ? "text-white" : "text-gray-800"}`}
                  >
                    Day {d.day}
                  </span>
                  <span
                    className={`mt-0.5 line-clamp-1 max-w-[72px] text-[10px] ${active ? "text-white/80" : "text-gray-400"}`}
                  >
                    {d.title}
                  </span>
                </button>
              );
            })}
          </div>

          {summary && (
            <div className="flex shrink-0 items-center gap-4 border-b border-gray-50 px-4 py-2.5 text-[11px] text-gray-500">
              <span>
                <i
                  className={`fa-solid ${commuteModeIcon(summary.mainMode)} mr-1 text-primary-500`}
                  aria-hidden="true"
                />
                {summary.distance}
              </span>
              <span>
                <i
                  className="fa-regular fa-clock mr-1 text-primary-500"
                  aria-hidden="true"
                />
                {summary.duration}
              </span>
              <span>
                <i
                  className="fa-solid fa-location-dot mr-1 text-primary-500"
                  aria-hidden="true"
                />
                {summary.spots} 个地点
              </span>
            </div>
          )}

          <div className="flex-1 overflow-y-auto p-4">
            <Timeline
              day={currentDay}
              activePlaceId={activePlaceId}
              onPlaceClick={(place) => {
                setActivePlaceId(place.place_id);
                setDetailPlace(place);
              }}
            />
          </div>
        </section>

        <section
          className={`min-h-0 w-full flex-1 flex-col lg:flex ${
            mobileTab === "map" ? "flex" : "hidden"
          }`}
        >
          <Suspense
            fallback={
              <div className="flex flex-1 items-center justify-center text-sm text-gray-400">
                地图加载中…
              </div>
            }
          >
            <MapView
              day={currentDay}
              activePlaceId={activePlaceId}
              onMarkerClick={(id) => {
                setActivePlaceId(id);
                const p = currentDay.places.find((x) => x.place_id === id);
                if (p) setDetailPlace(p);
              }}
            />
          </Suspense>
        </section>
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
      <ShareDialog
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        recordId={recordId}
      />
    </div>
  );
}
