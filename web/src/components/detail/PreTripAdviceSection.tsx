import { useMemo } from "react";
import type { PackingChecklistGroup, TravelTip } from "@/types/trip";
import { filterPackingChecklist, filterTravelTips } from "@/utils/preTripAdvice";
import { DraftingCompass } from "lucide-react";
import { PackingChecklist } from "./PackingChecklist";
import { TravelTips } from "./TravelTips";

interface PreTripAdviceSectionProps {
  packingChecklist?: PackingChecklistGroup[] | null;
  travelTips?: TravelTip[] | null;
  hideHeader?: boolean;
}

export function PreTripAdviceSection({
  packingChecklist,
  travelTips,
  hideHeader = false,
}: PreTripAdviceSectionProps) {
  const validPacking = useMemo(
    () => filterPackingChecklist(packingChecklist),
    [packingChecklist],
  );
  const validTips = useMemo(
    () => filterTravelTips(travelTips),
    [travelTips],
  );

  const hasPacking = validPacking.length > 0;
  const hasTips = validTips.length > 0;

  if (!hasPacking && !hasTips) return null;

  const content = (
    <div
      className={
        hasPacking && hasTips
          ? "grid grid-cols-1 gap-6 lg:grid-cols-2 items-stretch"
          : "space-y-6"
      }
    >
      {hasPacking && <PackingChecklist groups={validPacking} />}
      {hasTips && <TravelTips tips={validTips} />}
    </div>
  );

  if (hideHeader) {
    return content;
  }

  return (
    <section
      id="pretrip-advice"
      className="scroll-mt-24 space-y-6"
      aria-label="行前准备"
    >
      {/* 区域标题与副标 */}
      <div className="border-b border-sand-200/80 pb-3">
        <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-widest text-primary-600">
          <DraftingCompass size={11} aria-hidden="true" />
          <span>PRE-TRIP ADVICE</span>
        </div>
        <h2 className="font-display text-2xl sm:text-3xl font-extrabold text-gray-900 tracking-tight mt-1">
          行前准备
        </h2>
      </div>

      {/* 响应式栅格布局：双栏并存时 lg:grid-cols-2，单栏时自适应 */}
      {content}
    </section>
  );
}
