import { useState, useMemo } from "react";
import {
  REGIONS,
  type RegionType,
} from "@/constants/chinaGeo";
import { Check, Compass, Sparkles } from "lucide-react";
import { useDestinations } from "@/hooks/useDestinations";


interface RegionCityCardsProps {
  selectedCity?: string;
  onSelectCity?: (cityName: string) => void;
  className?: string;
}

export function RegionCityCards({
  selectedCity = "成都",
  onSelectCity,
  className = "",
}: RegionCityCardsProps) {
  const { data: destinationsData, isLoading, error, refetch } = useDestinations();
  const [activeRegion, setActiveRegion] = useState<RegionType>("全部");
  const [searchQuery, setSearchQuery] = useState("");

  const CHINA_CITIES_GEO = useMemo(() => {
    if (destinationsData?.destinations) {
      return destinationsData.destinations.map(d => ({ name: d.name, enName: d.nameEn || "", tag: d.tagline || "", iata: d.iataCode || "", region: d.region, desc: d.description }));
    }
    return [];
  }, [destinationsData]);

  // 过滤城市
  const filteredCities = useMemo(() => {
    return CHINA_CITIES_GEO.filter((c) => {
      const matchRegion = activeRegion === "全部" || c.region === activeRegion;
      const matchQuery =
        !searchQuery.trim() ||
        c.name.includes(searchQuery.trim()) ||
        c.enName.toLowerCase().includes(searchQuery.trim().toLowerCase()) ||
        c.tag.includes(searchQuery.trim()) ||
        c.iata.toLowerCase().includes(searchQuery.trim().toLowerCase());
      return matchRegion && matchQuery;
    });
  }, [CHINA_CITIES_GEO, activeRegion, searchQuery]);

  if (isLoading) {
    return (
      <div className={`flex items-center justify-center py-8 ${className}`}>
        <p className="text-sm text-gray-500">加载城市数据中...</p>
      </div>
    );
  }

  if (error) return <div role="alert">城市目录加载失败 <button type="button" onClick={() => void refetch()}>重试</button></div>;

  return (
    <div className={`flex flex-col space-y-3.5 ${className}`}>
      {/* 1. 顶部控制栏：大区切换 Pills + 搜索辅助 */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 pb-2 border-b border-sand-200/80">
        {/* 大区过滤标签 */}
        <div className="flex items-center gap-1.5 overflow-x-auto hide-scrollbar py-0.5">
          {REGIONS.map((region) => {
            const count =
              region === "全部"
                ? CHINA_CITIES_GEO.length
                : CHINA_CITIES_GEO.filter((c) => c.region === region).length;
            const active = activeRegion === region;
            return (
              <button
                key={region}
                type="button"
                onClick={() => setActiveRegion(region)}
                className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold transition-all ${
                  active
                    ? "bg-emerald-700 text-white shadow-xs font-bold ring-2 ring-emerald-600/30"
                    : "bg-sand-100 text-gray-600 hover:bg-sand-200/80 hover:text-gray-900 border border-sand-200"
                }`}
              >
                {region} <span className="opacity-75 text-[10px]">({count})</span>
              </button>
            );
          })}
        </div>

        {/* 搜索/提示 */}
        <div className="flex items-center justify-between sm:justify-end gap-2 text-xs text-gray-500">
          <span className="hidden md:inline-flex items-center gap-1 text-[11px] text-gray-400">
            <Compass size={12} />
            <span>点选即锁定目的地并推荐线路</span>
          </span>
          <div className="relative">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="快速搜索城市..."
              className="w-32 sm:w-40 rounded-lg border border-sand-300 bg-white px-2.5 py-1 text-xs text-gray-800 placeholder-gray-400 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                className="absolute right-2 top-1 text-gray-400 hover:text-gray-600 text-xs"
              >
                ×
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 2. 城市多维文化卡片网格（跨端友好：手机双列大卡片、PC 四列精致卡片） */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2.5 max-h-[50vh] overflow-y-auto custom-scrollbar p-0.5">
        {filteredCities.map((c) => {
          const isSelected = selectedCity === c.name;
          return (
            <button
              key={c.name}
              type="button"
              onClick={() => onSelectCity?.(c.name)}
              className={`group relative flex flex-col justify-between p-3 rounded-2xl border text-left transition-all ${
                isSelected
                  ? "bg-gradient-to-br from-emerald-50 to-white border-emerald-600 shadow-md ring-2 ring-emerald-500/20"
                  : "bg-white border-sand-200 hover:border-emerald-400 hover:bg-sand-50/60 hover:shadow-sm"
              }`}
            >
              {/* 头部：城市名 + 区域/IATA 徽标 */}
              <div className="flex items-start justify-between gap-1 w-full">
                <div className="flex items-baseline gap-1.5">
                  <span
                    className={`font-black text-base sm:text-lg tracking-tight ${
                      isSelected ? "text-emerald-900" : "text-gray-900 group-hover:text-emerald-700"
                    }`}
                  >
                    {c.name}
                  </span>
                  <span className="text-[10px] text-gray-400 font-mono">
                    {c.iata}
                  </span>
                </div>

                <div className="flex items-center gap-1">
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                      isSelected
                        ? "bg-emerald-600 text-white"
                        : "bg-sand-100 text-gray-600 group-hover:bg-emerald-100 group-hover:text-emerald-800"
                    }`}
                  >
                    {c.region}
                  </span>
                  {isSelected && (
                    <span className="flex h-4 w-4 items-center justify-center rounded-full bg-emerald-600 text-white text-[10px]">
                      <Check size={10} strokeWidth={3} />
                    </span>
                  )}
                </div>
              </div>

              {/* 中部：特色文化标签 */}
              <div className="my-1.5">
                <span
                  className={`inline-block text-[11px] font-semibold truncate max-w-full ${
                    isSelected
                      ? "text-emerald-800"
                      : "text-gray-600 group-hover:text-emerald-700"
                  }`}
                >
                  {c.tag}
                </span>
              </div>

              {/* 底部：地道风物微语录 (移动端单行，桌面两行) */}
              <p className="text-[10px] text-gray-400 group-hover:text-gray-500 line-clamp-1 sm:line-clamp-2 leading-relaxed">
                {c.desc}
              </p>
            </button>
          );
        })}

        {filteredCities.length === 0 && (
          <div className="col-span-full py-8 text-center text-xs text-gray-400">
            {CHINA_CITIES_GEO.length ? `未找到包含 “${searchQuery}” 的城市` : "暂无可选城市"}
          </div>
        )}
      </div>

      {/* 3. 底部大区速览提示 */}
      <div className="flex items-center justify-between text-[11px] text-gray-400 pt-1 border-t border-sand-100">
        <span className="flex items-center gap-1">
          <Sparkles size={11} className="text-emerald-600" />
          <span>支持扩展至全国 30+ 官方名城，大区分类触控不误触</span>
        </span>
        <span>当前展示 {filteredCities.length} 座名城</span>
      </div>
    </div>
  );
}
