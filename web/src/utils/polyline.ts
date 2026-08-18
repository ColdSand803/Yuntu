/**
 * 解析高德路径规划 API 的 polyline 明文串。
 * 格式："lng,lat;lng,lat;..."（经度,纬度，分号分隔，GCJ-02 坐标系）。
 * 后端把一个 commute_leg 跨越的所有 steps[].polyline 拼接成一条传入。
 * 返回 [lng, lat][]，与高德地图 AMap.Polyline 的 path 顺序一致。
 */
export function decodePolyline(encoded: string): [number, number][] {
  const coords: [number, number][] = [];
  if (!encoded) return coords;

  for (const pair of encoded.split(";")) {
    if (!pair) continue;
    const [lngStr, latStr] = pair.split(",");
    const lng = Number(lngStr);
    const lat = Number(latStr);
    if (Number.isFinite(lng) && Number.isFinite(lat)) {
      coords.push([lng, lat]);
    }
  }

  return coords;
}
