/**
 * Local date handling utilities for Cinematic Homepage.
 * Complies with design.md:
 * - Local YYYY-MM-DD calendar dates (no UTC offset shifting)
 * - Inclusive range 1..7 days
 * - Re-validates against local today
 */

export function toLocalIsoDate(date: Date = new Date()): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function parseLocalIsoDate(isoString: string): Date {
  const [y, m, d] = isoString.split("-").map(Number);
  return new Date(y, m - 1, d, 12, 0, 0);
}

export function formatDateLabel(isoString: string): string {
  if (!isoString || !/^\d{4}-\d{2}-\d{2}$/.test(isoString)) return "";
  const parts = isoString.split("-");
  return `${Number(parts[1])}月${Number(parts[2])}日`;
}

export function getInclusiveDays(startIso: string, endIso: string): number {
  if (!startIso || !endIso) return 0;
  const start = parseLocalIsoDate(startIso);
  const end = parseLocalIsoDate(endIso);
  const diffMs = end.getTime() - start.getTime();
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24));
  return diffDays + 1;
}

export function addDaysToLocalIso(startIso: string, days: number): string {
  const date = parseLocalIsoDate(startIso);
  date.setDate(date.getDate() + days);
  return toLocalIsoDate(date);
}

export function getMaxEndDate(startIso: string, maxDays = 7): string {
  return addDaysToLocalIso(startIso, maxDays - 1);
}

export function isDateExpired(isoString: string, todayIso: string = toLocalIsoDate()): boolean {
  if (!isoString) return false;
  return isoString < todayIso;
}

export function validateDateRange(
  startIso: string,
  endIso: string,
  todayIso: string = toLocalIsoDate(),
): { valid: boolean; error?: string; days: number } {
  if (!startIso || !endIso) {
    return { valid: false, error: "请选择完整的出发与返程日期", days: 0 };
  }

  if (!/^\d{4}-\d{2}-\d{2}$/.test(startIso) || !/^\d{4}-\d{2}-\d{2}$/.test(endIso)) {
    return { valid: false, error: "日期格式不合法", days: 0 };
  }

  if (startIso < todayIso) {
    return { valid: false, error: "出发日期不能早于今天", days: 0 };
  }

  if (endIso < startIso) {
    return { valid: false, error: "返程日期不能早于出发日期", days: 0 };
  }

  const days = getInclusiveDays(startIso, endIso);
  if (days < 1) {
    return { valid: false, error: "行程天数至少为 1 天", days };
  }

  if (days > 7) {
    return { valid: false, error: "行程最多支持 7 天", days };
  }

  return { valid: true, days };
}
