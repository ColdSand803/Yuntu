import type { CommuteLeg as CommuteLegType, TransitStep } from "@/types/trip";
import { commuteModeName, formatMinutes, formatDistance, commuteModeIcon } from "@/utils/format";

interface CommuteLegProps {
  leg: CommuteLegType;
}

const STEP_KIND_ICON: Record<string, string> = {
  walking: "fa-person-walking",
  bus: "fa-bus",
  rail: "fa-train-subway",
  other: "fa-route",
};

function TransitStepItem({ step }: { step: TransitStep }) {
  const icon = STEP_KIND_ICON[step.kind] ?? "fa-route";
  const isTransit = step.kind === "bus" || step.kind === "rail";
  return (
    <div className="flex items-start gap-2">
      <div className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary-50">
        <i className={`fa-solid ${icon} text-[9px] text-primary-500`} aria-hidden="true" />
      </div>
      <div className="min-w-0 text-[11px] leading-snug text-gray-600">
        {isTransit && step.line_name ? (
          <>
            <span className="font-medium text-gray-700">{step.line_name}</span>
            {step.from_stop && step.to_stop && (
              <span className="text-gray-400"> · {step.from_stop} → {step.to_stop}</span>
            )}
            {step.stop_count != null && (
              <span className="text-gray-400"> ({step.stop_count}站)</span>
            )}
            {step.duration_minutes != null && (
              <span className="ml-1 text-gray-400">{formatMinutes(step.duration_minutes)}</span>
            )}
          </>
        ) : (
          <>
            {step.kind === "walking" ? "步行" : commuteModeName(step.kind)}
            {step.duration_minutes != null && (
              <span className="ml-1 text-gray-400">{formatMinutes(step.duration_minutes)}</span>
            )}
            {step.distance_meters != null && (
              <span className="ml-1 text-gray-400">{formatDistance(step.distance_meters)}</span>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export function CommuteLeg({ leg }: CommuteLegProps) {
  const icon = commuteModeIcon(leg.mode);
  const hasSteps = leg.mode === "transit" && leg.transit_steps && leg.transit_steps.length > 0;
  const summary = leg.transit_summary;

  return (
    <div className="ml-[22px] border-l border-dashed border-primary-200 py-1.5 pl-5">
      {/* 顶行：出行方式 + 时间 + 距离 */}
      <span className="inline-flex items-center gap-1 rounded-full bg-sand-50 px-2 py-0.5 text-[11px] text-sand-500">
        <i className={`fa-solid ${icon} text-[9px]`} aria-hidden="true" />
        {commuteModeName(leg.mode)}{" "}
        {formatMinutes(leg.duration_minutes)} · {formatDistance(leg.distance_meters)}
      </span>

      {/* transit 明细 */}
      {leg.mode === "transit" && (
        <div className="mt-1.5 space-y-1.5">
          {hasSteps ? (
            leg.transit_steps!.map((step, i) => <TransitStepItem key={i} step={step} />)
          ) : summary ? (
            <p className="text-[11px] leading-snug text-gray-400">{summary}</p>
          ) : null}
        </div>
      )}
    </div>
  );
}
