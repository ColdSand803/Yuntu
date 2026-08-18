import { describe, expect, it } from "vitest";
import {
  bundledCityImages,
  cityAssetPathname,
  resolveCityAssetVariant,
  usesBundledCityAssets,
  withCityAssetBase,
} from "@/config/cityAssets";

describe("city asset URL helpers", () => {
  it("treats empty CDN origin as bundled OSS assets", () => {
    expect(usesBundledCityAssets("")).toBe(true);
    expect(bundledCityImages("chongqing")).toEqual(["/bundled/chongqing.png"]);
    expect(bundledCityImages("hangzhou")).toEqual(["/bundled/chongqing.png"]);
  });

  it("keeps same-origin paths when no CDN origin is configured", () => {
    expect(withCityAssetBase("/city-opt/beijing/photo.webp", "")).toBe(
      "/city-opt/beijing/photo.webp",
    );
  });

  it("joins city paths to a CDN origin without a double slash", () => {
    expect(
      withCityAssetBase(
        "/city-opt/beijing/photo.webp",
        "https://assets.example.com/",
      ),
    ).toBe("https://assets.example.com/city-opt/beijing/photo.webp");
  });

  it("does not move unrelated public assets to the city CDN", () => {
    expect(withCityAssetBase("/logo.svg", "https://assets.example.com")).toBe(
      "/logo.svg",
    );
  });

  it("extracts city paths from absolute CDN URLs", () => {
    expect(
      cityAssetPathname(
        "https://assets.example.com/city-opt/chengdu/photo.mobile.webp",
      ),
    ).toBe("/city-opt/chengdu/photo.mobile.webp");
  });

  it("selects the requested responsive published variant", () => {
    expect(
      resolveCityAssetVariant("/city/chengdu/photo.jpg", {
        mobile: true,
        format: "jpg",
      }),
    ).toBe("/city-opt/chengdu/photo.mobile.jpg");
  });
});
