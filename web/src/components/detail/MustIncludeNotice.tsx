import type { TripMustInclude } from "@/types/trip";

interface MustIncludeNoticeProps {
  items?: TripMustInclude[] | null;
}

export function MustIncludeNotice({ items }: MustIncludeNoticeProps) {
  if (!items || items.length === 0) return null;

  const unscheduledItems = items.filter(
    (item) =>
      item.status === "not_scheduled" ||
      item.status === "cross_city" ||
      item.status === "recorded_candidate" ||
      item.status === "recorded_unmatched" ||
      item.status !== "scheduled",
  );
  if (unscheduledItems.length === 0) return null;

  return (
    <div
      role="region"
      aria-label="必去地点调整说明"
      className="mx-auto max-w-3xl px-5 sm:px-8 mb-8"
    >
      <div className="rounded-2xl border border-amber-200/80 bg-amber-50/90 p-4 text-xs text-amber-900 shadow-xs space-y-2">
        <div className="flex items-center gap-2 font-bold text-amber-800">
          <i className="fa-solid fa-circle-exclamation text-amber-600 text-sm" aria-hidden="true" />
          <span>必去地点调整提醒（{unscheduledItems.length} 项未排入行程）</span>
        </div>
        <ul className="space-y-1.5 pl-5 list-disc text-[11px] leading-relaxed">
          {unscheduledItems.map((item) => {
            const key = item.place_id != null ? String(item.place_id) : item.name;
            const statusLabel =
              item.status === "cross_city"
                ? " (不在本城市)"
                : item.status === "recorded_unmatched"
                  ? " (未匹配到对应地点)"
                  : item.status === "recorded_candidate"
                    ? " (候选地点备用)"
                    : "";
            return (
              <li key={key}>
                <span className="font-bold text-amber-950">{item.name}</span>
                {statusLabel}
                {item.reason && `：${item.reason}`}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
