import { useEffect, useRef, useState } from "react";
import { SUPPORTED_CITIES } from "@/constants/preferences";
import { cityImageList } from "@/components/input/RotatingBackground";

interface MultiCitySelectProps {
  value: string[];
  onChange: (cities: string[]) => void;
  multiCity?: boolean;
  error?: string;
}

// 热门目的地 = 后端已开放城市，复用 SUPPORTED_CITIES 单一数据源
const HOT_CITIES = SUPPORTED_CITIES;
const MAX_CITIES = 5;

export function MultiCitySelect({ value, onChange, multiCity = true, error }: MultiCitySelectProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!pickerOpen) return;
    function onClickOutside(e: MouseEvent) {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setPickerOpen(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [pickerOpen]);

  function addCity(city: string) {
    if (multiCity) {
      if (!value.includes(city) && value.length < MAX_CITIES) {
        onChange([...value, city]);
      }
    } else {
      onChange([city]);
    }
    setPickerOpen(false);
  }

  function removeCity(city: string) {
    onChange(value.filter((c) => c !== city));
  }

  function prefetchCity(city: string) {
    if (typeof window !== "undefined") {
      const urls = cityImageList(city);
      if (urls.length > 0) {
        const img = new Image();
        img.src = urls[0];
      }
    }
  }

  const available = SUPPORTED_CITIES.filter((c) => !value.includes(c));

  return (
    <div className="space-y-2.5">
      {/* 已选城市芯片 */}
      <div className="flex flex-wrap items-center gap-2">
        {value.map((city, idx) => (
          <div
            key={city}
            className={`inline-flex items-center gap-2 rounded-2xl px-5 py-2.5 text-sm font-medium shadow-sm transition-all duration-300 ${
              idx === 0
                ? 'bg-primary-500 text-white shadow-primary-500/20 scale-[1.02]'
                : 'bg-gray-100/60 text-gray-700 hover:bg-gray-200/80'
            }`}
          >
            <span>{city}</span>
            <button
              type="button"
              onClick={() => removeCity(city)}
              className={`text-xs transition-opacity p-1 -m-1 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 ${
                idx === 0 ? 'opacity-80 hover:opacity-100' : 'text-gray-400 hover:text-gray-600'
              }`}
              aria-label={`移除 ${city}`}
            >
              ✕
            </button>
          </div>
        ))}

        {(multiCity ? value.length < MAX_CITIES : true) && available.length > 0 && (
          <div className="relative" ref={pickerRef}>
            <button
              type="button"
              onClick={() => setPickerOpen((o) => !o)}
              aria-expanded={pickerOpen}
              aria-haspopup="listbox"
              aria-invalid={!!error}
              className={`flex items-center px-5 py-2.5 rounded-2xl text-sm transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 ${
                error
                  ? 'bg-red-50 text-red-600'
                  : 'bg-gray-100/60 text-gray-500 hover:bg-gray-200/80 hover:text-gray-900 hover:scale-[1.02]'
              }`}
            >
              {multiCity ? '+ 添加城市' : value.length > 0 ? '更换城市' : '+ 选择城市'}
            </button>
            {pickerOpen && (
              <div
                role="listbox"
                className="absolute top-full left-0 mt-3 z-30 w-72 bg-white/95 backdrop-blur-3xl rounded-3xl border border-white/40 shadow-[0_8px_30px_rgba(0,0,0,0.12)] p-4"
              >
                <p className="text-xs text-gray-400 mb-2">当前支持以下城市：</p>
                <div className="grid grid-cols-3 gap-1.5">
                  {available.map((city) => (
                    <button
                      key={city}
                      type="button"
                      role="option"
                      aria-selected={false}
                      onClick={() => addCity(city)}
                      onMouseEnter={() => prefetchCity(city)}
                      className="rounded-xl px-2 py-2 text-sm text-gray-600 hover:bg-gray-100/80 hover:text-gray-900 transition-colors text-center focus-visible:outline-none"
                    >
                      {city}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 热门目的地快选 */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-gray-400">热门目的地：</span>
        {HOT_CITIES.filter((c) => !value.includes(c)).map((city) => (
          <button
            key={city}
            type="button"
            onClick={() => addCity(city)}
            onMouseEnter={() => prefetchCity(city)}
            className="rounded-xl bg-gray-100/60 px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-200/80 hover:text-gray-900 transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 hover:scale-105"
          >
            {city}
          </button>
        ))}
      </div>
      {error && (
        <p className="flex items-center gap-1.5 text-xs text-red-600">
          <i className="fas fa-circle-exclamation" aria-hidden="true"></i>
          {error}
        </p>
      )}
    </div>
  );
}
