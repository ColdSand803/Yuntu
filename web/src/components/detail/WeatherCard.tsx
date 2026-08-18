import type { TripWeather, WeatherDay } from "@/types/trip";
import { weatherIcon } from "@/constants/weather";

interface WeatherCardProps {
  data: TripWeather;
  /** 当前选中的 day（与行程 Day 标签联动）；缺省用 days[0] */
  activeDay?: number;
}

const WEEK = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

/** "2026-06-28" → { md: "6/28", label: "今天"|"明天"|"周X" }，相对今天 */
function fmtDate(iso: string): { md: string; label: string } {
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return { md: iso, label: "" };
  const md = `${d.getMonth() + 1}/${d.getDate()}`;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.round((d.getTime() - today.getTime()) / 86400000);
  const label = diff === 0 ? "今天" : diff === 1 ? "明天" : diff === 2 ? "后天" : WEEK[d.getDay()];
  return { md, label };
}

/** weather.status 非 ok 时的友好说明（days 为空的原因） */
const STATUS_HINT: Record<string, string> = {
  skipped_date_out_of_range: "出发日期较远，临近出行时可查看天气预报",
  skipped_disabled: "天气服务暂未开启",
  failed: "天气数据获取失败，请稍后再试",
};

export function WeatherCard({ data, activeDay }: WeatherCardProps) {
  const { city, status, days } = data;

  // 无逐日数据：显示友好说明卡，而非整卡消失（让用户知道为什么没有天气）
  if (days.length === 0) {
    const hint = STATUS_HINT[status] ?? "暂无天气数据";
    return (
      <div className="rounded-xl bg-white p-5 shadow-[0_2px_12px_rgba(0,0,0,0.05)]">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-bold text-gray-800">{city}天气预报</h2>
        </div>
        <div className="flex items-center gap-3 rounded-lg bg-gray-50 px-3 py-3">
          <i className="fa-solid fa-cloud-sun text-lg text-gray-300" aria-hidden="true" />
          <p className="text-[11px] leading-relaxed text-gray-500">{hint}</p>
        </div>
      </div>
    );
  }

  const head: WeatherDay = days.find((d) => d.day === activeDay) ?? days[0];

  return (
    <div className="rounded-xl border border-gray-100 bg-white p-5 shadow-[0_2px_10px_rgba(0,0,0,0.02)]">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-bold text-gray-800">{city}天气预报</h2>
        <span className="text-[11px] text-gray-500">未来 {days.length} 天</span>
      </div>

      {/* 提醒条（黄色，贴卡顶） */}
      {head.reminders.length > 0 && (
        <div className="mb-4 flex items-start gap-2 rounded-lg border border-accent-100 bg-accent-50 px-3 py-2.5">
          <i className="fa-solid fa-triangle-exclamation mt-0.5 shrink-0 text-xs text-accent-500" aria-hidden="true" />
          <div className="space-y-1">
            {head.reminders.map((r) => (
              <p key={r} className="text-[11px] leading-relaxed text-accent-700">{r}</p>
            ))}
          </div>
        </div>
      )}

      {/* 大头部（当前选中天） */}
      <div className="mb-6 flex items-center gap-5">
        <div className="text-[40px] leading-none drop-shadow-sm">{weatherIcon(head.icon_code)}</div>
        <div>
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-bold text-gray-800 tabular-nums">{head.temp_max_c}°</span>
            <span className="text-xs font-medium text-gray-600">{head.weather_text}</span>
          </div>
          <div className="mt-1 text-[11px] text-gray-500 tabular-nums">
            最低 {head.temp_min_c}° · {head.wind_text}
          </div>
        </div>
      </div>

      {/* 多日横条 */}
      <div className="flex justify-between text-center">
        {days.map((d) => {
          const { md, label } = fmtDate(d.date);
          const isHead = d.day === head.day;
          return (
            <div
              key={d.date}
              className={`flex flex-1 flex-col items-center gap-0.5 rounded-lg py-1.5 ${
                isHead ? "bg-primary-50" : ""
              }`}
            >
              <div className={`mb-0.5 text-xs font-medium ${isHead ? "text-primary-700" : "text-gray-700"}`}>{label}</div>
              <div className="mb-1 text-[10px] text-gray-500 tabular-nums">{md}</div>
              <div className="my-1 text-lg leading-none">{weatherIcon(d.icon_code)}</div>
              <div className="mt-1 text-xs font-bold text-gray-800 tabular-nums">{d.temp_max_c}°</div>
              <div className="mt-0.5 text-[11px] text-gray-500 tabular-nums">{d.temp_min_c}°</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
