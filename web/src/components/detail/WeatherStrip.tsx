import type { TripWeather, WeatherDay } from "@/types/trip";
import { weatherIcon, collectWeatherReminders } from "@/constants/weather";

interface WeatherStripProps {
  data: TripWeather | null | undefined;
}

const WEEK = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

function fmtDate(iso: string): { md: string; label: string } {
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return { md: iso, label: "" };
  const md = `${d.getMonth() + 1}/${d.getDate()}`;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.round((d.getTime() - today.getTime()) / 86400000);
  const label =
    diff === 0 ? "今天" : diff === 1 ? "明天" : diff === 2 ? "后天" : WEEK[d.getDay()];
  return { md, label };
}

export function WeatherStrip({ data }: WeatherStripProps) {
  if (!data) return null;

  const { status, days } = data;

  // weather.status 非 ok 或 days 为空时的处理
  if (status !== "ok" || !days || days.length === 0) {
    if (status === "skipped_date_out_of_range") {
      return (
        <div className="rounded-xl border border-gray-100 bg-white/70 px-4 py-3 text-xs text-gray-500 shadow-2xs">
          <i className="fas fa-calendar-alt text-primary-500 mr-2" aria-hidden="true" />
          <span>出发日期较远，临近出行时可查看天气预报</span>
        </div>
      );
    }
    return null;
  }

  // 聚合提醒收集（使用公共集成的 collectWeatherReminders 函数）
  const reminders = collectWeatherReminders(days);

  return (
    <div className="space-y-3">
      {/* N日天气细带 */}
      <div className="rounded-xl border border-gray-100 bg-white p-3.5 shadow-soft">
        <div className="mb-2.5 flex items-center justify-between px-1">
          <span className="text-[11px] font-bold uppercase tracking-wider text-gray-500">
            {data.city} · {days.length}日天气趋势
          </span>
          <span className="text-[10px] text-gray-400">未来 {days.length} 天</span>
        </div>

        <div className="flex items-center gap-2 overflow-x-auto hide-scrollbar pb-1 overscroll-x-contain">
          {days.map((d: WeatherDay) => {
            const { md, label } = fmtDate(d.date);
            return (
              <div
                key={d.date}
                className="flex shrink-0 min-w-[76px] flex-col items-center justify-center rounded-lg border border-gray-50 bg-gray-50/60 p-2 text-center transition-colors hover:bg-gray-100/70"
              >
                <span className="text-[11px] font-medium text-gray-700">{label}</span>
                <span className="text-[10px] text-gray-400 tabular-nums mb-1">{md}</span>
                <span className="text-base my-0.5 leading-none" aria-hidden="true">
                  {weatherIcon(d.icon_code)}
                </span>
                <span className="text-xs font-bold text-gray-800 tabular-nums">
                  {d.temp_max_c}°
                </span>
                <span className="text-[10px] text-gray-400 tabular-nums">
                  {d.temp_min_c}°
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* 聚合提醒条（仅 reminders 非空时渲染） */}
      {reminders.length > 0 && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-200/80 bg-amber-50/90 px-3.5 py-2.5 shadow-2xs">
          <i className="fas fa-exclamation-circle text-amber-500 text-xs mt-0.5 shrink-0" aria-hidden="true" />
          <div className="space-y-1 text-xs leading-relaxed text-amber-800">
            {reminders.map((rem: string, idx: number) => (
              <p key={`${rem}-${idx}`}>{rem}</p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
