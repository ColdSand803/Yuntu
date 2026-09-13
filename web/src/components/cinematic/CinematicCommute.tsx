import { Check } from "lucide-react";
import type { RequestedCommuteMode } from "@/types/form";
import { CINEMATIC_COMMUTE_OPTIONS } from "@/types/cinematic";

interface CinematicCommuteProps {
  commuteMode: RequestedCommuteMode;
  onSelectCommuteMode: (mode: RequestedCommuteMode) => void;
}

export function CinematicCommute({
  commuteMode,
  onSelectCommuteMode,
}: CinematicCommuteProps) {
  return (
    <div className="cmp-commute-cards" role="radiogroup" aria-label="市内出行方式">
      {CINEMATIC_COMMUTE_OPTIONS.map((opt) => {
        const isSelected = commuteMode === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={isSelected}
            className={`cmp-commute-card ${isSelected ? "is-selected" : ""}`}
            onClick={() => onSelectCommuteMode(opt.value)}
          >
            <div className="cmp-commute-title">
              <span>{opt.label}</span>
              {isSelected && <Check size={18} />}
            </div>
            <div className="cmp-commute-desc">{opt.desc}</div>
          </button>
        );
      })}
    </div>
  );
}
