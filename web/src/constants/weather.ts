/** 后端 weather.days[].icon_code → emoji。后端取值集见 yuntu-travel。 */
const WEATHER_ICON_EMOJI: Record<string, string> = {
  sunny: "☀️",
  clear: "☀️",
  cloudy: "☁️",
  partly_cloudy: "⛅",
  overcast: "🌥️",
  rain: "🌧️",
  light_rain: "🌦️",
  moderate_rain: "🌧️",
  heavy_rain: "⛈️",
  thunderstorm: "⛈️",
  thunder: "⛈️",
  snow: "🌨️",
  light_snow: "🌨️",
  heavy_snow: "❄️",
  sleet: "🌨️",
  fog: "🌫️",
  haze: "😶‍🌫️",
  windy: "💨",
  unknown: "🌡️",
};

/** 取天气 emoji，未知 code 回退到 unknown */
export function weatherIcon(code: string | null | undefined): string {
  if (!code) return WEATHER_ICON_EMOJI.unknown;
  return WEATHER_ICON_EMOJI[code] ?? WEATHER_ICON_EMOJI.unknown;
}

/** 取 FA 单色线性图标，含 fog/haze/wind 及 snowflake 正确映射 */
export function weatherFaIcon(iconCode: string | null | undefined): string {
  if (!iconCode) return "fa-sun";
  const code = iconCode.toLowerCase();
  if (code.includes("rain") || code.includes("drizzle")) return "fa-cloud-rain";
  if (code.includes("cloud") || code.includes("overcast")) return "fa-cloud";
  if (code.includes("snow") || code.includes("sleet")) return "fa-snowflake";
  if (code.includes("thunder") || code.includes("storm")) return "fa-bolt";
  if (code.includes("fog") || code.includes("haze") || code.includes("smog")) return "fa-smog";
  if (code.includes("wind")) return "fa-wind";
  return "fa-sun";
}

import type { WeatherDay } from "@/types/trip";

/** 统一的气象提醒与极端高温收集去重函数 */
export function collectWeatherReminders(days: WeatherDay[] | undefined): string[] {
  if (!days || days.length === 0) return [];
  const set = new Set<string>();
  days.forEach((day: WeatherDay) => {
    if (day.reminders) {
      day.reminders.forEach((r) => {
        if (r && r.trim()) set.add(r.trim());
      });
    }
    if (day.temp_max_c >= 40) {
      set.add(`第${day.day}天有 ${day.temp_max_c}°C 极端高温，请做好防暑降温`);
    }
  });
  return Array.from(set);
}
