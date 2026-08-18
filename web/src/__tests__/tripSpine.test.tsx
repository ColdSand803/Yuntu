import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { TripSpine } from "@/components/detail/TripSpine";
import type { TripDay, TripWeather } from "@/types/trip";

describe("TripSpine Component Tests (PR-3)", () => {
  const mockDays: TripDay[] = [
    { day: 1, title: "杭州漫步", places: [], commute_legs: [], commute_summary: "", pace_status: "WITHIN_LIMIT", narrative: "" },
    { day: 2, title: "西湖风光", places: [], commute_legs: [], commute_summary: "", pace_status: "WITHIN_LIMIT", narrative: "" },
  ];

  it("[PR3-1] 无天气数据时，脊柱仍正常渲染日序号，不抛错", () => {
    render(<TripSpine days={mockDays} weather={null} activeDay={1} />);

    expect(screen.getByRole("navigation", { name: "每日行程导航" })).toBeInTheDocument();
    expect(screen.getByText("01")).toBeInTheDocument();
    expect(screen.getByText("02")).toBeInTheDocument();
  });

  it("[PR3-2] 有天气数据时，渲染 FontAwesome 图标、气温及当前高亮标记", () => {
    const mockWeather: TripWeather = {
      status: "ok",
      city: "杭州",
      days: [
        {
          day: 1,
          date: "2026-08-05",
          weather_text: "晴",
          temp_min_c: 28,
          temp_max_c: 38,
          wind_text: "无风",
          icon_code: "sun",
          reminders: [],
        },
        {
          day: 2,
          date: "2026-08-06",
          weather_text: "大雨",
          temp_min_c: 25,
          temp_max_c: 30,
          wind_text: "北风",
          icon_code: "rain",
          reminders: ["第2天有雨"],
        },
      ],
    };

    render(<TripSpine days={mockDays} weather={mockWeather} activeDay={1} />);

    expect(screen.getByText(/38/)).toBeInTheDocument();
    expect(screen.getByText(/30/)).toBeInTheDocument();
    expect(screen.getByText("第2天有雨")).toBeInTheDocument();
  });
});
