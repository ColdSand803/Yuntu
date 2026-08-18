import { useEffect, useRef, useState } from "react";
import { fetchHotPlaces, type HotPlace } from "@/services/api";
import type { RequestedCommuteMode, MustIncludeItem } from "@/types/form";

interface MorePreferencesProps {
  city: string;
  mustInclude: MustIncludeItem[];
  onMustIncludeChange: (v: MustIncludeItem[]) => void;
  commuteMode: RequestedCommuteMode;
  onCommuteModeChange: (v: RequestedCommuteMode) => void;
  dailyStart: string;
  dailyEnd: string;
  onDailyStartChange: (v: string) => void;
  onDailyEndChange: (v: string) => void;
  accommodationName?: string;
  onAccommodationNameChange?: (v: string) => void;
  /** 嵌在外层「行程细节」折叠内时不自带手风琴壳 */
  embedded?: boolean;
}

const COMMUTE_OPTIONS: { value: RequestedCommuteMode; label: string }[] = [
  { value: "driving", label: "打车" },
  { value: "transit", label: "公共交通" },
  { value: "cycling", label: "骑行优先" },
];

const MAX_MUST_INCLUDE = 5;

/** 可选时间：空态不露出浏览器 --:--，点击整块打开原生 time 选择 */
function TimeOptionalInput({
  value,
  onChange,
  ariaLabel,
  emptyLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  ariaLabel: string;
  emptyLabel: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  function openPicker() {
    const el = inputRef.current;
    if (!el) return;
    el.focus();
    try {
      el.showPicker?.();
    } catch {
      /* 部分环境无 showPicker */
    }
  }

  return (
    <div className="relative inline-flex h-9 min-w-[6.5rem] items-stretch">
      <input
        ref={inputRef}
        type="time"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={ariaLabel}
        className={`w-full rounded-xl bg-white px-3 py-2 text-sm shadow-inner focus:outline-none focus:ring-2 focus:ring-primary-300 transition-all ${
          value ? "text-gray-800" : "text-transparent caret-transparent"
        }`}
      />
      {!value && (
        <button
          type="button"
          tabIndex={-1}
          onClick={openPicker}
          className="absolute inset-0 z-[1] flex items-center justify-center rounded-xl bg-white text-sm text-gray-400 shadow-inner hover:bg-gray-50 transition-all"
        >
          {emptyLabel}
        </button>
      )}
    </div>
  );
}

export function MorePreferences({
  city,
  mustInclude,
  onMustIncludeChange,
  commuteMode,
  onCommuteModeChange,
  dailyStart,
  dailyEnd,
  onDailyStartChange,
  onDailyEndChange,
  accommodationName = "",
  onAccommodationNameChange,
  embedded = false,
}: MorePreferencesProps) {
  const [open, setOpen] = useState(false);
  const [hotPlaces, setHotPlaces] = useState<HotPlace[]>([]);
  const [input, setInput] = useState("");
  const fetchedCityRef = useRef<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const panelOpen = embedded || open;

  useEffect(() => {
    if (!panelOpen || !city || fetchedCityRef.current === city) return;
    let cancelled = false;
    fetchedCityRef.current = city;
    fetchHotPlaces(city)
      .then((places) => {
        if (!cancelled) setHotPlaces(places);
      })
      .catch(() => {
        if (!cancelled) setHotPlaces([]);
      });
    return () => {
      cancelled = true;
    };
  }, [panelOpen, city]);

  // 展开后滚入可视区，避免被手机底部 sticky CTA 挡住
  useEffect(() => {
    if (!open || embedded) return;
    const id = window.setTimeout(() => {
      rootRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      // 若仍贴底，再滚一点让「时间习惯」完整露出
      panelRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }, 80);
    return () => clearTimeout(id);
  }, [open, embedded]);

  const full = mustInclude.length >= MAX_MUST_INCLUDE;

  function addPlace(name: string, placeId?: number) {
    const trimmed = name.trim();
    if (!trimmed || mustInclude.some((p) => p.name === trimmed) || full) return;
    onMustIncludeChange([
      ...mustInclude,
      placeId != null ? { name: trimmed, place_id: placeId } : { name: trimmed },
    ]);
  }

  function removePlace(name: string) {
    onMustIncludeChange(mustInclude.filter((p) => p.name !== name));
  }

  const selectedCount =
    (mustInclude.length > 0 ? 1 : 0) +
    (commuteMode !== "driving" ? 1 : 0) +
    (dailyStart || dailyEnd ? 1 : 0) +
    (accommodationName ? 1 : 0);

  const body = (
    <div className={embedded ? "space-y-5" : "space-y-5 border-t border-gray-100 px-4 py-4"}>
      <div>
        <p className="mb-2 text-[13px] font-medium text-gray-700">
          必去地点
          <span className="ml-1.5 font-normal text-gray-400">
            最多 {MAX_MUST_INCLUDE} 个，会优先安排进行程
          </span>
        </p>

        {mustInclude.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {mustInclude.map(({ name }) => (
              <span
                key={name}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary-500 px-2.5 py-1 text-xs text-white"
              >
                {name}
                <button
                  type="button"
                  onClick={() => removePlace(name)}
                  aria-label={`移除 ${name}`}
                  className="-m-0.5 rounded p-0.5 opacity-80 hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
                >
                  {"✕"}
                </button>
              </span>
            ))}
          </div>
        )}

        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) {
              e.preventDefault();
              addPlace(input);
              setInput("");
            }
          }}
          disabled={full}
          placeholder={full ? `最多 ${MAX_MUST_INCLUDE} 个` : "输入地点名，回车添加"}
          aria-label="输入必去地点"
          className="w-full rounded-2xl bg-white px-4 py-3 text-sm placeholder:text-gray-400 shadow-inner focus:outline-none focus:ring-2 focus:ring-primary-300 disabled:cursor-not-allowed disabled:opacity-60 transition-all duration-300"
        />

        {hotPlaces.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] text-gray-500">{city}热门：</span>
            {hotPlaces
              .filter((p) => !mustInclude.some((m) => m.name === p.name))
              .slice(0, 10)
              .map((p) => (
                <button
                  key={p.place_id}
                  type="button"
                  onClick={() => addPlace(p.name, p.place_id)}
                  disabled={full}
                  className="rounded-md border border-gray-100 bg-gray-50 px-2 py-1 text-[11px] text-gray-600 transition-colors hover:border-primary-300 hover:bg-primary-50/50 hover:text-primary-600 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                >
                  + {p.name}
                </button>
              ))}
          </div>
        )}
      </div>

      <div>
        <p className="mb-2 text-[13px] font-medium text-gray-700" id="commute-mode-label">
          市内出行方式
        </p>
        <div className="flex gap-2" role="radiogroup" aria-labelledby="commute-mode-label">
          {COMMUTE_OPTIONS.map(({ value, label }) => {
            const active = commuteMode === value;
            return (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => onCommuteModeChange(value)}
                className={`flex flex-1 items-center justify-center rounded-2xl px-2 py-3 text-xs font-medium transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 ${
                  active
                    ? "bg-primary-500 text-white shadow-md shadow-primary-500/20 scale-[1.02]"
                    : "bg-white text-gray-600 shadow-sm hover:bg-gray-50 hover:scale-[1.01]"
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <p className="text-[13px] font-medium text-gray-700">
            时间习惯
            <span className="ml-1.5 font-normal text-gray-400">
              {dailyStart || dailyEnd ? "" : "未设置，默认无固定时间"}
            </span>
          </p>
          {(dailyStart || dailyEnd) && (
            <button
              type="button"
              onClick={() => {
                onDailyStartChange("");
                onDailyEndChange("");
              }}
              className="rounded px-1 text-xs text-gray-400 transition-colors hover:text-primary-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
            >
              清除，恢复无固定时间
            </button>
          )}
        </div>
        {/* 空 time 在 PC 上会露出原生 --:--/时钟，空态用遮罩按钮点开选择 */}
        <div className="flex flex-wrap items-center gap-2 text-sm text-gray-600">
          <span>每天</span>
          <TimeOptionalInput
            value={dailyStart}
            onChange={onDailyStartChange}
            ariaLabel="每天出发时间（选填）"
            emptyLabel="选填"
          />
          <span>出发 ·</span>
          <TimeOptionalInput
            value={dailyEnd}
            onChange={onDailyEndChange}
            ariaLabel="每天结束时间（选填）"
            emptyLabel="选填"
          />
          <span>前结束</span>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-gray-500">常用：</span>
          {(
            [
              ["朝九晚九", "09:00", "21:00"],
              ["睡到自然醒", "10:30", "22:00"],
              ["只管晚上", "", "22:30"],
            ] as const
          ).map(([label, s, e]) => {
            const active = dailyStart === s && dailyEnd === e;
            return (
              <button
                key={label}
                type="button"
                aria-pressed={active}
                onClick={() => {
                  onDailyStartChange(s);
                  onDailyEndChange(e);
                }}
                className={`rounded-md border px-2 py-1 text-[11px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 ${
                  active
                    ? "border-primary-400 bg-primary-50 font-medium text-primary-600"
                    : "border-gray-100 bg-gray-50 text-gray-600 hover:border-primary-300 hover:bg-primary-50/50 hover:text-primary-600"
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>
        <p className="mt-1.5 text-[11px] text-gray-400">
          {dailyStart && dailyEnd
            ? `每天 ${dailyStart} - ${dailyEnd} 内安排行程`
            : dailyStart
              ? `不早于 ${dailyStart} 开始，结束时间不限`
              : dailyEnd
                ? `尽量在 ${dailyEnd} 前结束，开始时间不限`
                : "无固定时间：按行程节奏自由安排"}
        </p>
      </div>

      <div>
        <p className="mb-2 text-[13px] font-medium text-gray-700">
          已知住宿地点
          <span className="ml-1.5 font-normal text-gray-400">
            选填，系统将围绕你的住宿地排布路线
          </span>
        </p>
        <input
          type="text"
          value={accommodationName}
          onChange={(e) => onAccommodationNameChange?.(e.target.value)}
          placeholder="如：解放碑威斯汀酒店 / 观音桥"
          aria-label="输入住宿地点"
          className="w-full rounded-2xl bg-white px-4 py-3 text-sm placeholder:text-gray-400 shadow-inner focus:outline-none focus:ring-2 focus:ring-primary-300 transition-all duration-300"
        />
      </div>
    </div>
  );

  if (embedded) return body;

  return (
    <div ref={rootRef} className="rounded-3xl bg-gray-100/40 border border-transparent transition-all duration-300 hover:bg-gray-100/60">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between rounded-3xl px-5 py-4 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
      >
        <span className="flex min-w-0 items-center font-bold text-gray-700">
          更多偏好
          <span className="ml-1 font-normal text-gray-400">(选填)</span>
          {!open && selectedCount > 0 ? (
            <span className="ml-2 shrink-0 rounded-full bg-primary-50 px-2 py-0.5 text-[10px] font-medium text-primary-600">
              已设置 {selectedCount} 项
            </span>
          ) : (
            !open && (
              <span className="ml-2 truncate text-xs font-normal text-gray-400">
                必去地点 · 出行方式 · 时间习惯
              </span>
            )
          )}
        </span>
        <i
          className={`fas fa-chevron-down text-xs text-gray-400 transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>
      {open && (
        <div ref={panelRef} className="pb-1">
          {body}
        </div>
      )}
    </div>
  );
}
