/**
 * 解析高德路径规划 API 的 polyline 明文串。
 * 格式："lng,lat;lng,lat;..."（经度,纬度，分号分隔，GCJ-02 坐标系）。
 * 后端把一个 commute_leg 跨越的所有 steps[].polyline 拼接成一条传入。
 * 返回 [lng, lat][]，与高德地图 AMap.Polyline 的 path 顺序一致。
 */
export function decodePolyline(encoded?: string | null): [number, number][] {
  const coords: [number, number][] = [];
  if (!encoded || typeof encoded !== "string") return coords;

  for (const pair of encoded.split(";")) {
    const trimmedPair = pair.trim();
    if (!trimmedPair) continue;
    const parts = trimmedPair.split(",");
    if (parts.length !== 2) continue;
    const lngStr = parts[0].trim();
    const latStr = parts[1].trim();
    if (lngStr === "" || latStr === "") continue;
    const lng = Number(lngStr);
    const lat = Number(latStr);
    if (Number.isFinite(lng) && Number.isFinite(lat)) {
      coords.push([lng, lat]);
    }
  }

  return coords;
}
