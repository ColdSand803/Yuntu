import { useEffect, useMemo, useRef, useState } from "react";

interface DateRangeInputProps {
  startDate: string; // YYYY-MM-DD
  endDate: string;
  onStartChange: (date: string) => void;
  onEndChange: (date: string) => void;
}

const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];
const MONTH_NAMES = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"];

/* ---------- 纯本地日期工具（避免 UTC 偏移导致差一天） ---------- */

function parseISO(s: string): Date | null {
  if (!s) return null;
  const [y, m, d] = s.split("-").map(Number);
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d);
}

function toISO(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** 生成某月日历网格（周一为首列，补齐前后月占位，共 6 行 42 格） */
function monthGrid(year: number, month: number): Date[] {
  const first = new Date(year, month, 1);
  // JS getDay: 0=周日…6=周六；转成周一=0
  const offset = (first.getDay() + 6) % 7;
  const gridStart = new Date(year, month, 1 - offset);
  return Array.from({ length: 42 }, (_, i) => {
    return new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + i);
  });
}

function diffDays(startISO: string, endISO: string): number | null {
  const s = parseISO(startISO);
  const e = parseISO(endISO);
  if (!s || !e) return null;
  const diff = Math.round((e.getTime() - s.getTime()) / 86400000);
  return diff >= 0 ? diff + 1 : null;
}

function formatDisplay(iso: string): string {
  const d = parseISO(iso);
  if (!d) return "选择日期";
  return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")}`;
}

function formatShort(iso: string): string {
  const d = parseISO(iso);
  if (!d) return "";
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export function DateRangeInput({ startDate, endDate, onStartChange, onEndChange }: DateRangeInputProps) {
  const [open, setOpen] = useState(false);
  // 面板显示的月份（以 startDate 为锚，无则当月）
  const [viewDate, setViewDate] = useState<Date>(() => parseISO(startDate) ?? new Date());
  // 选择进行中的临时起点：点第一下存这里，点第二下补成完整区间
  const [pendingStart, setPendingStart] = useState<string | null>(null);
  // 悬停日期：选定起点后预览 起点→悬停日 的区间
  const [hoverIso, setHoverIso] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const today = useMemo(() => startOfDay(new Date()), []);
  const days = diffDays(startDate, endDate);

  // 打开面板：视图对齐已选起点月份，重开一轮选择。
  // 不能放进依赖 startDate 的 useEffect —— 第一次点击日期会改 startDate，
  // effect 重跑会清掉 pendingStart，导致必须点两次才能锁定出发日期（历史 bug）
  function openPanel() {
    setViewDate(parseISO(startDate) ?? new Date());
    setPendingStart(null);
    setHoverIso(null);
    setOpen(true);
  }

  // 点击面板外关闭
  useEffect(() => {
    if (!open) return;
    function onClickOutside(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onEsc(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onClickOutside);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  function handlePick(day: Date) {
    if (day < today) return; // 不允许选过去
    const iso = toISO(day);

    // 第一下：锁定出发日期，立即生效（终点暂与起点同日），等待第二下选返程
    if (!pendingStart) {
      setPendingStart(iso);
      setHoverIso(null);
      onStartChange(iso);
      onEndChange(iso);
      return;
    }

    // 第二下：无论点在起点前后都直接成区间（点早了就反向成段），一次完成
    const start = parseISO(pendingStart)!;
    if (day < start) {
      onStartChange(iso);
      onEndChange(pendingStart);
    } else {
      onEndChange(iso);
    }
    setPendingStart(null);
    setHoverIso(null);
    setOpen(false); // 区间选定，收起
  }

  const grid = useMemo(() => monthGrid(viewDate.getFullYear(), viewDate.getMonth()), [viewDate]);
  const sIso = parseISO(startDate);
  const eIso = parseISO(endDate);
  // 选择进行中：区间预览端点 = 临时起点 → 悬停日（悬停早于起点则反向）
  const pStart = parseISO(pendingStart ?? "");
  const pHover = parseISO(hoverIso ?? "");
  const previewLo = pStart && pHover ? (pHover < pStart ? pHover : pStart) : pStart;
  const previewHi = pStart && pHover ? (pHover < pStart ? pStart : pHover) : pStart;

  const rangeLo = pendingStart ? previewLo : sIso;
  const rangeHi = pendingStart ? previewHi : eIso;

  function inRange(day: Date): boolean {
    if (!rangeLo || !rangeHi) return false;
    const t = day.getTime();
    return t >= startOfDay(rangeLo).getTime() && t <= startOfDay(rangeHi).getTime();
  }

  function prevMonth() {
    setViewDate((d) => new Date(d.getFullYear(), d.getMonth() - 1, 1));
  }
  function nextMonth() {
    setViewDate((d) => new Date(d.getFullYear(), d.getMonth() + 1, 1));
  }

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3" ref={rootRef}>
      <div className="relative flex-1">
        {/* 触发区：整块可点，双日期 + 分隔 */}
        <button
          type="button"
          onClick={() => (open ? setOpen(false) : openPanel())}
          aria-haspopup="dialog"
          aria-expanded={open}
          className={`flex w-full items-center rounded-2xl bg-gray-100/60 px-4 py-3.5 text-left transition-all duration-300 sm:px-5 ${
            open ? "bg-white shadow-md ring-2 ring-primary-300" : "hover:bg-gray-200/80 shadow-inner"
          }`}
        >
          <i className="far fa-calendar text-primary-500" aria-hidden="true" />
          <span className="ml-3 flex flex-1 items-center gap-2 text-sm">
            <span className={sIso ? "text-gray-700" : "text-gray-400"}>{formatDisplay(startDate)}</span>
            <span className="text-gray-300" aria-hidden="true">~</span>
            <span className={eIso ? "text-gray-700" : "text-gray-400"}>{formatDisplay(endDate)}</span>
          </span>
          <i className={`fas fa-chevron-down text-xs text-gray-400 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
        </button>

        {/* 日历弹层 */}
        {open && (
          <div
            role="dialog"
            aria-label="选择旅行日期"
            className="absolute left-0 top-full z-40 mt-3 w-[300px] rounded-3xl border border-white/40 bg-white/95 p-4 shadow-[0_8px_30px_rgba(0,0,0,0.12)] backdrop-blur-3xl"
          >
            {/* 月份切换 */}
            <div className="mb-3 flex items-center justify-between">
              <button
                type="button"
                onClick={prevMonth}
                aria-label="上个月"
                className="flex h-8 w-8 items-center justify-center rounded-lg text-gray-500 transition-colors hover:bg-primary-50 hover:text-primary-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
              >
                <i className="fas fa-chevron-left text-xs" aria-hidden="true" />
              </button>
              <span className="text-sm font-bold text-gray-800">
                {viewDate.getFullYear()} 年 {MONTH_NAMES[viewDate.getMonth()]}
              </span>
              <button
                type="button"
                onClick={nextMonth}
                aria-label="下个月"
                className="flex h-8 w-8 items-center justify-center rounded-lg text-gray-500 transition-colors hover:bg-primary-50 hover:text-primary-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
              >
                <i className="fas fa-chevron-right text-xs" aria-hidden="true" />
              </button>
            </div>

            {/* 星期头 */}
            <div className="mb-1 grid grid-cols-7 text-center text-[11px] font-medium text-gray-400">
              {WEEKDAYS.map((w) => (
                <div key={w} className="py-1">{w}</div>
              ))}
            </div>

            {/* 日期网格 */}
            <div className="grid grid-cols-7 gap-y-1" onMouseLeave={() => setHoverIso(null)}>
              {grid.map((day) => {
                const isCurMonth = day.getMonth() === viewDate.getMonth();
                const isPast = day < today;
                const isStart = rangeLo ? sameDay(day, rangeLo) : false;
                const isEnd = rangeHi ? sameDay(day, rangeHi) : false;
                const isEndpoint = isStart || isEnd;
                const isMid = inRange(day) && !isEndpoint;
                const isToday = sameDay(day, today);
                const hasSpan = rangeLo && rangeHi && !sameDay(rangeLo, rangeHi);

                return (
                  <div
                    key={day.getTime()}
                    className={`flex justify-center ${
                      isMid ? "bg-primary-50" : ""
                    } ${isStart && hasSpan ? "rounded-l-full bg-primary-50" : ""} ${
                      isEnd && hasSpan ? "rounded-r-full bg-primary-50" : ""
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => handlePick(day)}
                      onMouseEnter={() => {
                        if (pendingStart && !isPast) setHoverIso(toISO(day));
                      }}
                      disabled={isPast}
                      aria-label={toISO(day)}
                      aria-pressed={isEndpoint}
                      className={`relative flex h-9 w-9 items-center justify-center rounded-full text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 ${
                        isEndpoint
                          ? "bg-primary-500 font-bold text-white"
                          : isMid
                            ? "text-primary-700"
                            : isPast
                              ? "cursor-not-allowed text-gray-300"
                              : isCurMonth
                                ? "text-gray-700 hover:bg-primary-100"
                                : "text-gray-300 hover:bg-gray-50"
                      }`}
                    >
                      {day.getDate()}
                      {isToday && !isEndpoint && (
                        <span className="absolute bottom-1 h-1 w-1 rounded-full bg-primary-500" aria-hidden="true" />
                      )}
                    </button>
                  </div>
                );
              })}
            </div>

            {/* 底部：分步提示 + 今天快捷 */}
            <div className="mt-3 flex items-center justify-between border-t border-gray-100 pt-3">
              <span className="text-[11px] text-gray-500" aria-live="polite">
                {pendingStart ? (
                  <>
                    <span className="font-medium text-primary-600">{formatShort(pendingStart)} 出发</span>
                    {" · 再点一天作为返程"}
                  </>
                ) : (
                  "点击选出发日期，再点返程日期"
                )}
              </span>
              <button
                type="button"
                onClick={() => {
                  const iso = toISO(today);
                  setPendingStart(iso);
                  setHoverIso(null);
                  onStartChange(iso);
                  onEndChange(iso);
                  setViewDate(new Date(today.getFullYear(), today.getMonth(), 1));
                }}
                className="text-xs font-medium text-primary-600 transition-colors hover:text-primary-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 rounded"
              >
                今天出发
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 天数 */}
      <div className="flex shrink-0 items-center justify-center rounded-xl border border-gray-100 bg-gray-50 px-4 py-2.5 sm:w-24">
        <span className="whitespace-nowrap text-sm text-gray-700">{days ? `${days} 天` : "- 天"}</span>
      </div>
    </div>
  );
}
