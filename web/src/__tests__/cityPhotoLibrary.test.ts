import { describe, expect, it } from "vitest";
import {
  cityImageList,
  cityNameOfImage,
} from "@/components/input/RotatingBackground";
import { SUPPORTED_CITIES } from "@/constants/preferences";

const CITY_FOLDERS = [
  ["北京", "beijing"],
  ["上海", "shanghai"],
  ["重庆", "chongqing"],
  ["成都", "chengdu"],
  ["杭州", "hangzhou"],
  ["西安", "xian"],
  ["南京", "nanjing"],
  ["长沙", "changsha"],
  ["青岛", "qingdao"],
  ["桂林", "guilin"],
  ["广州", "guangzhou"],
  ["武汉", "wuhan"],
  ["苏州", "suzhou"],
  ["厦门", "xiamen"],
  ["昆明", "kunming"],
  ["三亚", "sanya"],
] as const;

describe("city photo library", () => {
  it("keeps the six-city expansion in the controlled city selector", () => {
    expect(SUPPORTED_CITIES).toHaveLength(16);
    expect(SUPPORTED_CITIES).toEqual(
      expect.arrayContaining(["广州", "武汉", "苏州", "厦门", "昆明", "三亚"]),
    );
  });

  it.each(CITY_FOLDERS)("keeps eight mapped photos for %s", (city, folder) => {
    const images = cityImageList(city);

    expect(images).toHaveLength(8);
    expect(new Set(images).size).toBe(8);
    expect(images.every((url) => url.includes(`/city-opt/${folder}/`))).toBe(
      true,
    );
    expect(images.every((url) => cityNameOfImage(url) === city)).toBe(true);
  });
});
