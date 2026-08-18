import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { PlaceDetailModal } from "@/components/detail/PlaceDetailModal";
import { Timeline } from "@/components/detail/Timeline";
import type { PlaceDetail, TripDay, TripPlace } from "@/types/trip";

const { fetchPlaceDetail } = vi.hoisted(() => ({ fetchPlaceDetail: vi.fn() }));

vi.mock("@/services/api", () => ({ fetchPlaceDetail }));

const place: TripPlace = {
  place_id: 4900,
  name: "北京路",
  category: "attraction",
  longitude: 113.27,
  latitude: 23.13,
  role: "anchor",
  optional: false,
  brief: "",
};

const gallery = [1, 2, 3].map((position) => ({
  asset_id: position.toString(16).padStart(16, "0"),
  position,
  alt_text: `北京路实拍图 ${position}`,
  desktop: {
    url: `https://assets.example.com/poi/4900/${position}.desktop.webp`,
    width: 1280,
    height: 960,
  },
  mobile: {
    url: `https://assets.example.com/poi/4900/${position}.mobile.webp`,
    width: 768,
    height: 576,
  },
  thumb: {
    url: `https://assets.example.com/poi/4900/${position}.thumb.webp`,
    width: 360,
    height: 270,
  },
}));

const detail: PlaceDetail = {
  place_id: place.place_id,
  name: place.name,
  place_type: place.category,
  district: "越秀区",
  longitude: place.longitude,
  latitude: place.latitude,
  summary: "适合步行浏览的城市街区",
  top_reasons: [],
  warnings: [],
  source_count: 0,
  mention_count: 0,
  gallery,
};

describe("POI detail gallery", () => {
  beforeEach(() => {
    fetchPlaceDetail.mockReset();
    fetchPlaceDetail.mockResolvedValue(detail);
  });

  test("does not request images until a POI detail opens", async () => {
    const { rerender } = render(
      <PlaceDetailModal place={null} onClose={() => undefined} />,
    );
    expect(fetchPlaceDetail).not.toHaveBeenCalled();

    rerender(<PlaceDetailModal place={place} onClose={() => undefined} />);
    await waitFor(() => expect(fetchPlaceDetail).toHaveBeenCalledOnce());
    expect(fetchPlaceDetail).toHaveBeenCalledWith(4900);
    expect(await screen.findByAltText("北京路实拍图 1")).toHaveAttribute(
      "src",
      gallery[0].thumb.url,
    );
    expect(screen.getByAltText("北京路实拍图 1")).toHaveAttribute(
      "srcset",
      expect.stringContaining(gallery[0].mobile.url),
    );
  });

  test("shows an available single image without carousel controls", async () => {
    fetchPlaceDetail.mockResolvedValueOnce({
      ...detail,
      gallery: gallery.slice(0, 1),
    });
    render(<PlaceDetailModal place={place} onClose={() => undefined} />);

    expect(await screen.findByAltText("北京路实拍图 1")).toBeInTheDocument();
    expect(screen.getByText("实拍 · 1/1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "上一张图片" })).toBeNull();
    expect(screen.queryByRole("button", { name: "下一张图片" })).toBeNull();
    expect(screen.queryByLabelText("图片位置")).toBeNull();
  });

  test("supports desktop buttons, dots, keyboard and touch swipe", async () => {
    render(<PlaceDetailModal place={place} onClose={() => undefined} />);
    await screen.findByAltText("北京路实拍图 1");

    fireEvent.click(screen.getByRole("button", { name: "下一张图片" }));
    expect(screen.getByAltText("北京路实拍图 2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "查看第 3 张图片" }));
    expect(screen.getByAltText("北京路实拍图 3")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "ArrowLeft" });
    expect(screen.getByAltText("北京路实拍图 2")).toBeInTheDocument();

    const image = screen.getByAltText("北京路实拍图 2");
    const frame = image.parentElement as HTMLElement;
    fireEvent.touchStart(frame, { changedTouches: [{ clientX: 240 }] });
    fireEvent.touchEnd(frame, { changedTouches: [{ clientX: 120 }] });
    expect(screen.getByAltText("北京路实拍图 3")).toBeInTheDocument();
  });

  test("removes the gallery after individual image failures or an API failure", async () => {
    const { rerender } = render(
      <PlaceDetailModal place={place} onClose={() => undefined} />,
    );
    fireEvent.error(await screen.findByAltText("北京路实拍图 1"));
    fireEvent.error(await screen.findByAltText("北京路实拍图 2"));
    fireEvent.error(await screen.findByAltText("北京路实拍图 3"));
    await waitFor(() =>
      expect(screen.queryByLabelText("北京路实拍画廊")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("heading", { name: "北京路" })).toBeInTheDocument();

    fetchPlaceDetail.mockRejectedValueOnce(new Error("slow network timeout"));
    rerender(
      <PlaceDetailModal
        place={{ ...place, place_id: 4901, name: "沙面" }}
        onClose={() => undefined}
      />,
    );
    await waitFor(() =>
      expect(screen.queryByLabelText("沙面实拍画廊")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("heading", { name: "沙面" })).toBeInTheDocument();
  });

  test("shows a skeleton only while a slow empty response is pending", async () => {
    let resolveDetail: (value: PlaceDetail) => void = () => undefined;
    fetchPlaceDetail.mockReturnValueOnce(
      new Promise<PlaceDetail>((resolve) => {
        resolveDetail = resolve;
      }),
    );
    render(<PlaceDetailModal place={place} onClose={() => undefined} />);
    expect(screen.getByLabelText("图片加载中")).toBeInTheDocument();
    expect(screen.queryByRole("img")).toBeNull();

    resolveDetail({ ...detail, gallery: [] });
    await waitFor(() =>
      expect(screen.queryByLabelText("北京路实拍画廊")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("heading", { name: "北京路" })).toBeInTheDocument();
  });

  test("keeps itinerary list rows image-free", () => {
    const day: TripDay = {
      day: 1,
      title: "城市漫步",
      places: [place],
      commute_legs: [],
      commute_summary: "",
      pace_status: "WITHIN_LIMIT",
      narrative: "",
    };
    const { container } = render(<Timeline day={day} />);
    expect(container.querySelector("img")).toBeNull();
  });
});
