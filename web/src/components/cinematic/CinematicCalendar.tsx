import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import {
  toLocalIsoDate,
  formatDateLabel,
  getMaxEndDate,
  getInclusiveDays,
} from "@/utils/cinematicDate";

interface CinematicCalendarProps {
  start: string;
  end: string;
  onChange: (start: string, end: string) => void;
}

export function CinematicCalendar({
  start,
  end,
  onChange,
}: CinematicCalendarProps) {
  const today = useMemo(() => toLocalIsoDate(new Date()), []);

  const [monthDate, setMonthDate] = useState<Date>(() => {
    if (start && /^\d{4}-\d{2}-\d{2}$/.test(start)) {
      const [y, m] = start.split("-").map(Number);
      return new Date(y, m - 1, 1);
    }
    const d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), 1);
  });

  const year = monthDate.getFullYear();
  const month = monthDate.getMonth(); // 0-indexed
  const monthIso = `${year}-${String(month + 1).padStart(2, "0")}`;
  const todayMonthIso = today.slice(0, 7);
  const prevDisabled = monthIso <= todayMonthIso;

  const firstWeekday = (new Date(year, month, 1).getDay() + 6) % 7; // Monday = 0
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const maxAllowedEnd = useMemo(() => {
    if (!start || end) return null;
    return getMaxEndDate(start, 7);
  }, [start, end]);

  const handlePrevMonth = () => {
    setMonthDate(new Date(year, month - 1, 1));
  };

  const handleNextMonth = () => {
    setMonthDate(new Date(year, month + 1, 1));
  };

  const handleDayClick = (dayIso: string) => {
    if (!start || end) {
      // First click or reset
      onChange(dayIso, "");
    } else if (dayIso < start) {
      // Clicked before current start -> restart with this date
      onChange(dayIso, "");
    } else {
      // Selected end date
      const days = getInclusiveDays(start, dayIso);
      if (days <= 7) {
        onChange(start, dayIso);
      } else {
        // Exceeds 7 days: start over from this day
        onChange(dayIso, "");
      }
    }
  };

  const daysSummary = useMemo(() => {
    if (start && end) {
      const count = getInclusiveDays(start, end);
      return `${formatDateLabel(start)} — ${formatDateLabel(end)}（共 ${count} 天）`;
    }
    if (start) {
      return `${formatDateLabel(start)} 出发，请选择返程日期（最多 7 天）`;
    }
    return "先选出发日期，再选返程日期（最多 7 天）";
  }, [start, end]);

  return (
    <div className="cmp-calendar">
      <div className="cmp-calendar-heading">
        <span>
          {year} 年 {month + 1} 月
        </span>
        <div>
          <button
            type="button"
            aria-label="上个月"
            disabled={prevDisabled}
            onClick={handlePrevMonth}
          >
            <ChevronLeft size={16} />
          </button>
          <button
            type="button"
            aria-label="下个月"
            onClick={handleNextMonth}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      <div className="cmp-calendar-grid">
        <div className="cmp-weekdays" aria-hidden="true">
          {["一", "二", "三", "四", "五", "六", "日"].map((d) => (
            <span key={d}>{d}</span>
          ))}
        </div>

        {Array.from({ length: firstWeekday }).map((_, i) => (
          <span key={`empty-${i}`} aria-hidden="true" />
        ))}

        {Array.from({ length: daysInMonth }).map((_, i) => {
          const dayNum = i + 1;
          const dayIso = `${year}-${String(month + 1).padStart(2, "0")}-${String(dayNum).padStart(2, "0")}`;
          const isPast = dayIso < today;
          const isExceedingRange = Boolean(maxAllowedEnd && dayIso > maxAllowedEnd);
          const isDisabled = isPast || isExceedingRange;
          const isSelected = dayIso === start || dayIso === end;
          const isInRange = Boolean(start && end && dayIso > start && dayIso < end);

          let className = "";
          if (isSelected) className += " is-selected";
          if (isInRange) className += " in-range";

          return (
            <button
              key={dayIso}
              type="button"
              className={className.trim()}
              disabled={isDisabled}
              aria-label={`${year}年${month + 1}月${dayNum}日${isSelected ? " 已选择" : ""}`}
              aria-pressed={isSelected}
              onClick={() => handleDayClick(dayIso)}
            >
              {dayNum}
            </button>
          );
        })}
      </div>

      <p className="cmp-calendar-feedback" aria-live="polite">
        {daysSummary}
      </p>
    </div>
  );
}
