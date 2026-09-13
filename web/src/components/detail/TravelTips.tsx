import type { TravelTip } from "@/types/trip";
import { Lightbulb, Info } from "lucide-react";

interface TravelTipsProps {
  tips: TravelTip[];
}

export function TravelTips({ tips }: TravelTipsProps) {
  if (!tips || tips.length === 0) return null;

  return (
    <div className="flex h-full flex-col rounded-3xl border border-sand-200/90 bg-white p-6 sm:p-7 shadow-card transition-shadow hover:shadow-card-hover">
      {/* 模块头部 */}
      <div className="mb-5 flex items-center justify-between border-b border-sand-200/80 pb-3.5">
        <div className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-xl bg-amber-50 text-amber-600 shadow-2xs border border-amber-200/80">
            <Lightbulb size={12} aria-hidden="true" />
          </span>
          <h3 className="text-base sm:text-lg font-bold text-gray-900 tracking-tight">
            实用避坑贴士
          </h3>
        </div>
        <span className="rounded-full bg-sand-100 px-2.5 py-0.5 text-[11px] font-medium text-gray-600 border border-sand-200/70">
          共 {tips.length} 条
        </span>
      </div>

      {/* 贴士列表 */}
      <div className="flex-1 space-y-3.5">
        {tips.map((tip, idx) => (
          <div
            key={`${tip.title}-${idx}`}
            className="rounded-2xl border border-amber-100/90 bg-amber-50/40 p-4 sm:p-4.5 transition-colors hover:bg-amber-50/70"
          >
            <div className="flex items-center gap-2">
              <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-amber-100 text-amber-700 text-[10px]">
                <Info size={9} aria-hidden="true" />
              </span>
              <h4 className="text-xs sm:text-sm font-bold text-gray-900 leading-snug break-words">
                {tip.title}
              </h4>
            </div>

            <p className="mt-2 text-xs sm:text-sm text-gray-700 leading-relaxed break-words pl-6">
              {tip.content}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
