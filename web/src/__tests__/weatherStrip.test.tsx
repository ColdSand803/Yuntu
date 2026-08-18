import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { WeatherStrip } from "@/components/detail/WeatherStrip";
import type { TripWeather } from "@/types/trip";

describe("WeatherStrip Component Tests (PR-2)", () => {
  it("[PR2-1] weather 为 null 时零渲染", () => {
    const { container } = render(<WeatherStrip data={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("[PR2-2] weather.status 为 skipped_date_out_of_range 时渲染友好提示", () => {
    const mockWeather: TripWeather = {
      status: "skipped_date_out_of_range",
      city: "杭州",
      days: [],
    };

    render(<WeatherStrip data={mockWeather} />);
    expect(
      screen.getByText("出发日期较远，临近出行时可查看天气预报"),
    ).toBeInTheDocument();
  });

  it("[PR2-3] 正常 weather.status === 'ok' 渲染多日细带与聚合提醒条", () => {
    const mockWeather: TripWeather = {
      status: "ok",
      city: "北京",
      days: [
        {
          day: 1,
          date: "2026-08-10",
          weather_text: "晴",
          temp_min_c: 26,
          temp_max_c: 40,
          wind_text: "南风 2级",
          icon_code: "sun",
          reminders: ["注意防晒"],
        },
        {
          day: 2,
          date: "2026-08-11",
          weather_text: "雷阵雨",
          temp_min_c: 24,
          temp_max_c: 32,
          wind_text: "北风 3级",
          icon_code: "thunder",
          reminders: ["出行请带伞"],
        },
      ],
    };

    render(<WeatherStrip data={mockWeather} />);

    expect(screen.getByText(/天气趋势/)).toBeInTheDocument();
    expect(screen.getByText("注意防晒")).toBeInTheDocument();
    expect(screen.getByText("出行请带伞")).toBeInTheDocument();
    expect(
      screen.getByText("第1天有 40°C 极端高温，请做好防暑降温"),
    ).toBeInTheDocument();
  });
});
