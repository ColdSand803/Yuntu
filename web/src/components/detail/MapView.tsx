import { useEffect, useRef, useState } from "react";
import AMapLoader from "@amap/amap-jsapi-loader";
import type { TripDay, AccommodationInfo } from "@/types/trip";
import { decodePolyline } from "@/utils/polyline";
import { isAnchorRole } from "@/constants/places";

interface MapViewProps {
  day: TripDay;
  accommodation?: AccommodationInfo | null;
  activePlaceId?: number | null;
  onMarkerClick?: (placeId: number) => void;
}

const MODE_COLOR: Record<string, string> = {
  walking: "#0f766e",
  transit: "#1d9e91",
  taxi: "#f97316",
  driving: "#1d9e91",
};

export function MapView({ day, accommodation, activePlaceId, onMarkerClick }: MapViewProps) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mapRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const amapRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const satelliteRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const markersRef = useRef<any[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const polylinesRef = useRef<any[]>([]);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<"standard" | "satellite">("standard");
  const containerRef = useRef<HTMLDivElement>(null);

  function toggleView(next: "standard" | "satellite") {
    const AMap = amapRef.current;
    const map = mapRef.current;
    if (!AMap || !map || next === view) return;
    if (next === "satellite") {
      if (!satelliteRef.current) satelliteRef.current = new AMap.TileLayer.Satellite();
      map.add(satelliteRef.current);
    } else {
      if (satelliteRef.current) {
        map.remove(satelliteRef.current);
      }
    }
    setView(next);
  }

  useEffect(() => {
    let destroyed = false;

    const key = import.meta.env.VITE_AMAP_KEY;
    if (!key) {
      setError(true);
      return;
    }

    // 新版高德 Web JS API 需要安全密钥配对（本地明文，上线改后端代理）
    const security = import.meta.env.VITE_AMAP_SECURITY;
    if (security) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (window as any)._AMapSecurityConfig = { securityJsCode: security };
    }

    AMapLoader.load({ key, version: "2.0" })
      .then((AMap) => {
        if (destroyed || !containerRef.current) return;

        amapRef.current = AMap;
        const map = new AMap.Map(containerRef.current, {
          zoom: 13,
          viewMode: "2D",
        });
        mapRef.current = map;

        updateMarkers(AMap, map, day, accommodation, activePlaceId, onMarkerClick, markersRef);
        updatePolylines(AMap, map, day, polylinesRef);
        fitView(map);
        setLoading(false);
      })
      .catch(() => {
        if (!destroyed) {
          setError(true);
          setLoading(false);
        }
      });

    return () => {
      destroyed = true;
      mapRef.current?.destroy();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // day/accommodation 变化：重建全部覆盖物并 fitView 全览
  useEffect(() => {
    const AMap = amapRef.current;
    const map = mapRef.current;
    if (!AMap || !map) return;

    clearOverlays(markersRef, polylinesRef);
    updateMarkers(AMap, map, day, accommodation, activePlaceId, onMarkerClick, markersRef);
    updatePolylines(AMap, map, day, polylinesRef);
    fitView(map);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [day, accommodation]);

  // activePlaceId 变化：重建 marker 更新高亮，并平移到选中点（不重置缩放）
  useEffect(() => {
    const AMap = amapRef.current;
    const map = mapRef.current;
    if (!AMap || !map) return;

    clearOverlays(markersRef, polylinesRef);
    updateMarkers(AMap, map, day, accommodation, activePlaceId, onMarkerClick, markersRef);
    updatePolylines(AMap, map, day, polylinesRef);

    const active = day.places.find((p) => p.place_id === activePlaceId);
    if (active?.longitude && active?.latitude) {
      map.panTo([active.longitude, active.latitude], 250);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activePlaceId]);

  // 容器尺寸变化（移动端 Tab 切换：地图从 hidden(0尺寸) 变可见）时，
  // 高德地图需 resize + 重新 fitView，否则会停在 0 尺寸初始化时的错误缩放（缩太远）
  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    let prevW = el.clientWidth;
    const ro = new ResizeObserver(() => {
      const map = mapRef.current;
      const w = el.clientWidth;
      // 仅在从不可见(0)变为可见时重排，避免正常缩放/拖动被打断
      if (map && prevW === 0 && w > 0) {
        map.resize();
        fitView(map);
      }
      prevW = w;
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  if (error)
    return (
      <div className="card flex h-full w-full flex-col items-center justify-center gap-3 bg-primary-50/30 p-6 text-center">
        <i className="fa-solid fa-map-location-dot text-3xl text-primary-200" aria-hidden="true" />
        <p className="text-sm font-medium text-gray-600">地图加载失败</p>
        <p className="text-xs text-gray-400">行程信息不受影响，可刷新页面重试</p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="mt-1 rounded-lg border border-primary-200 px-4 py-1.5 text-sm font-medium text-primary-700 transition-colors hover:bg-primary-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
        >
          刷新重试
        </button>
      </div>
    );

  return (
    <div className="card relative h-full w-full overflow-hidden">
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-primary-50/50">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary-200 border-t-primary-500" />
        </div>
      )}
      <div ref={containerRef} className="h-full w-full" />

      {/* 图层切换 */}
      <div className="absolute right-2 top-2 flex overflow-hidden rounded-lg border border-gray-100 bg-white shadow-sm">
        <button
          type="button"
          onClick={() => toggleView("standard")}
          className={`px-3 py-1.5 text-xs font-medium transition-colors ${
            view === "standard" ? "bg-primary-50 text-primary-600" : "bg-white text-gray-600 hover:bg-gray-50"
          }`}
        >
          地图
        </button>
        <button
          type="button"
          onClick={() => toggleView("satellite")}
          className={`border-l border-gray-100 px-3 py-1.5 text-xs font-medium transition-colors ${
            view === "satellite" ? "bg-primary-50 text-primary-600" : "bg-white text-gray-600 hover:bg-gray-50"
          }`}
        >
          卫星
        </button>
      </div>

      <div className="absolute bottom-2 right-2 rounded-lg bg-white/80 px-2.5 py-1 text-[10px] text-sand-500 backdrop-blur-sm">
        路线顺序示意图
      </div>
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function updateMarkers(AMap: any, map: any, day: TripDay, accommodation: AccommodationInfo | null | undefined, activePlaceId: number | null | undefined, onMarkerClick: ((id: number) => void) | undefined, markersRef: React.MutableRefObject<any[]>) {
  // 如果有住宿建议且坐标有效，绘制住宿锚点 Marker
  if (accommodation && accommodation.longitude && accommodation.latitude) {
    const isUserSpecified = accommodation.source === "user_specified";
    const bg = isUserSpecified ? "#0284c7" : "#0d9488";
    const dot = 26;
    const ring = 2;
    const nameBg = isUserSpecified ? "#f0f9ff" : "#f0fdf4";
    const nameBorder = isUserSpecified ? "#7dd3fc" : "#86efac";
    const nameColor = isUserSpecified ? "#0369a1" : "#15803d";
    const tagText = isUserSpecified ? "住宿" : "推荐住";

    const accMarker = new AMap.Marker({
      position: [accommodation.longitude, accommodation.latitude],
      zIndex: 150,
      content: `
        <div style="display:flex;align-items:center;gap:5px;transform:translate(-${dot / 2}px,-${dot / 2}px);white-space:nowrap;cursor:pointer">
          <div style="width:${dot}px;height:${dot}px;border-radius:50%;background:${bg};color:#fff;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;box-shadow:0 2px 6px rgba(0,0,0,.3);border:${ring}px solid #fff">🏨</div>
          <div style="font-size:12px;font-weight:700;color:${nameColor};background:${nameBg};border:1px solid ${nameBorder};border-radius:8px;padding:2px 7px;box-shadow:0 1px 4px rgba(0,0,0,.15);backdrop-filter:blur(2px)">
            <span style="font-size:10px;opacity:0.85;margin-right:3px;">[${tagText}]</span>${accommodation.name}
          </div>
        </div>`,
      offset: new AMap.Pixel(0, 0),
    });

    map.add(accMarker);
    markersRef.current.push(accMarker);
  }

  day.places.forEach((place, i) => {
    if (!place.longitude || !place.latitude) return;

    const isActive = place.place_id === activePlaceId;
    const isAnchor = isAnchorRole(place.role);
    const bg = isActive ? "#0c625b" : isAnchor ? "#0f766e" : "#fb923c";
    // 选中态：圆点放大、白描边加粗、整块加阴影与边框高亮
    const dot = isActive ? 30 : 24;
    const ring = isActive ? 3 : 2;
    const nameWeight = isActive ? 700 : 600;
    const nameColor = isActive ? "#0a4f49" : "#374151";
    const nameBg = isActive ? "#eef9f7" : "rgba(255,255,255,.92)";
    const nameBorder = isActive ? "#6ec6bb" : "#e5e7eb";

    const marker = new AMap.Marker({
      position: [place.longitude, place.latitude],
      // 选中项提到最上层，避免被其它 marker 名称遮住
      zIndex: isActive ? 200 : 100,
      content: `
        <div style="display:flex;align-items:center;gap:5px;transform:translate(-${dot / 2}px,-${dot / 2}px);white-space:nowrap;cursor:pointer">
          <div style="width:${dot}px;height:${dot}px;border-radius:50%;background:${bg};color:#fff;display:flex;align-items:center;justify-content:center;font-size:${isActive ? 14 : 12}px;font-weight:700;box-shadow:0 2px 6px rgba(0,0,0,.28);border:${ring}px solid #fff">${i + 1}</div>
          <div style="font-size:12px;font-weight:${nameWeight};color:${nameColor};background:${nameBg};border:1px solid ${nameBorder};border-radius:8px;padding:2px 7px;box-shadow:0 1px 4px rgba(0,0,0,.12);backdrop-filter:blur(2px)">${place.name}</div>
        </div>`,
      offset: new AMap.Pixel(0, 0),
    });

    marker.on("click", () => onMarkerClick?.(place.place_id));
    map.add(marker);
    markersRef.current.push(marker);
  });
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function updatePolylines(AMap: any, map: any, day: TripDay, polylinesRef: React.MutableRefObject<any[]>) {
  day.commute_legs.forEach((leg) => {
    const from = day.places.find((p) => p.place_id === leg.from_place_id);
    const to = day.places.find((p) => p.place_id === leg.to_place_id);
    if (!from?.longitude || !to?.longitude) return;

    let path: [number, number][];
    let hasRealRoute = false;

    if (leg.encoded_polyline) {
      try {
        path = decodePolyline(leg.encoded_polyline);
        hasRealRoute = true;
      } catch {
        path = [
          [from.longitude, from.latitude],
          [to.longitude, to.latitude],
        ];
      }
    } else {
      path = [
        [from.longitude, from.latitude],
        [to.longitude, to.latitude],
      ];
    }

    const color = MODE_COLOR[leg.mode] ?? "#94a3b8";

    // 底层：白色描边线（比主线更粗），让彩色路线在地图底图上跳得出来——竞品(高德)的关键手法
    const outline = new AMap.Polyline({
      path,
      strokeColor: "#ffffff",
      strokeWeight: 9,
      strokeOpacity: 0.9,
      lineJoin: "round",
      lineCap: "round",
      zIndex: 50,
    });
    map.add(outline);
    polylinesRef.current.push(outline);

    // 上层：彩色实线 + 方向箭头。无真实路网(直线段)用虚线区分"非实际路径"，但仍加粗醒目
    const polyline = new AMap.Polyline({
      path,
      strokeColor: color,
      strokeWeight: 6,
      strokeStyle: hasRealRoute ? "solid" : "dashed",
      strokeOpacity: 0.95,
      strokeDasharray: hasRealRoute ? undefined : [12, 6],
      showDir: true, // 行进方向箭头，一眼看出走向
      lineJoin: "round",
      lineCap: "round",
      zIndex: 51,
    });

    map.add(polyline);
    polylinesRef.current.push(polyline);
  });
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function clearOverlays(markersRef: React.MutableRefObject<any[]>, polylinesRef: React.MutableRefObject<any[]>) {
  markersRef.current.forEach((m) => m.setMap(null));
  polylinesRef.current.forEach((p) => p.setMap(null));
  markersRef.current = [];
  polylinesRef.current = [];
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function fitView(map: any) {
  setTimeout(() => {
    map.setFitView(null, false, [40, 40, 40, 40], 300);
  }, 100);
}
